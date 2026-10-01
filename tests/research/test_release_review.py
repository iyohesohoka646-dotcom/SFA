"""Regressions through the user-facing scientific service and terminal commands."""
import asyncio
import os
from pathlib import Path
import subprocess
import sys
import time
import venv

import pytest

from contract_driven_ai_flow.application.commands import dispatch
from contract_driven_ai_flow.research.models import ProbeSpec
from contract_driven_ai_flow.research.service import ResearchService
from contract_driven_ai_flow.settings.service import ModelSettingsService


@pytest.mark.parametrize('filtered', [False, True])
def test_plain_function_and_empty_watch_filter_execute_unchanged(tmp_path, filtered):
    script = tmp_path / 'plain.py'
    script.write_text('def f(x):\n    return x+1\nprint(f(2))\n', encoding='utf-8')
    with ResearchService(tmp_path) as service:
        record = service.wait(service.start_analysis(script, watched_names=('absent',) if filtered else ()).run_id, 15)
    assert record['status'] == 'completed', record['summary']
    assert record['summary']['exit_code'] == 0


def test_selected_venv_keeps_its_prefix_and_dependency_boundary(tmp_path):
    target = tmp_path / 'scientific-python'
    venv.EnvBuilder(with_pip=False).create(target)
    python = target / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    script = tmp_path / 'prefix.py'
    script.write_text('import sys\nfrom pathlib import Path\nassert Path(sys.prefix) == Path(sys.argv[1])\nX = 42\n')
    with ResearchService(tmp_path) as service:
        record = service.wait(service.start_analysis(script, interpreter=python, arguments=[str(target)]).run_id, 15)
    assert record['interpreter'] == str(python.absolute())
    assert record['status'] == 'completed', record['summary']


def test_terminal_inspect_returns_real_persisted_snapshot(tmp_path):
    script = tmp_path / 'analysis.py'; script.write_text('X = 42\n')
    with ResearchService(tmp_path) as service:
        record = service.wait(service.start_analysis(script).run_id, 15)
        value = next(s for s in service.store.snapshots(record['id']) if s.name == 'X')
        result = asyncio.run(dispatch('inspect', {'snapshot_id': value.id}, service=service, settings=ModelSettingsService(tmp_path)))
    assert result.status == 'ok', result.error
    assert result.data['id'] == value.id and result.data['sample']['values'] == [[42]]
    assert result.data['operation_id']


@pytest.mark.parametrize('policy', ['cancel', 'pause'])
def test_terminal_saved_probe_controls_the_next_run(tmp_path, policy):
    script = tmp_path / 'analysis.py'; script.write_text('import numpy as np\nX = np.array([float("nan")])\nY = 42\n')
    async def scenario(service):
        settings = ModelSettingsService(tmp_path)
        added = await dispatch('probe.add', {'script': str(script), 'kind': 'finite', 'binding': 'X', 'policy': policy}, service=service, settings=settings)
        assert added.status == 'ok', added.error
        run = await dispatch('run', {'script': str(script)}, service=service, settings=settings)
        assert run.status == 'ok', run.error
        deadline = time.monotonic()+15
        while time.monotonic() < deadline:
            record = service.store.run(run.run_id)
            if record['status'] not in ('queued', 'running'): break
            await asyncio.sleep(.05)
        assert record['status'] == ('paused' if policy == 'pause' else 'cancelled'), record
        assert 'Y' not in {s.name for s in service.store.snapshots(run.run_id)}
        if policy == 'pause':
            resumed = await dispatch('continue', {'run_id': run.run_id}, service=service, settings=settings)
            assert resumed.status == 'ok'
            record = await asyncio.to_thread(service.wait, run.run_id, 15)
            assert record['status'] == 'completed'
            assert 'Y' in {s.name for s in service.store.snapshots(run.run_id)}
    with ResearchService(tmp_path) as service: asyncio.run(scenario(service))


@pytest.mark.parametrize(('limit', 'expected'), [(0, 'fail'), (10000, 'pass')])
def test_duration_probe_uses_the_measured_statement_time(tmp_path, limit, expected):
    script = tmp_path / 'analysis.py'; script.write_text('X = sum(range(1000))\n')
    probe = ProbeSpec(id='time', kind='duration', binding='X', parameters={'max_ms': limit})
    with ResearchService(tmp_path) as service:
        run = service.wait(service.start_analysis(script, probes=[probe]).run_id, 15)
        results = [e.payload['result'] for e in service.store.events(run['id']) if e.kind == 'probe.evaluated']
    assert len(results) == 1 and results[0]['status'] == expected, results
    assert results[0]['evidence']['actual'] > 0


def test_duration_probe_without_timing_evidence_is_unknown():
    from contract_driven_ai_flow.research.models import SnapshotRef, ValueDescriptor
    from contract_driven_ai_flow.research.probes import evaluate_probe
    snapshot=SnapshotRef(id='no-time',run_id='r',binding_id='main:X',scope_id='main',name='X',version=1,
        descriptor=ValueDescriptor(kind='scalar',backend='python',type_name='int'))
    evaluated=evaluate_probe(ProbeSpec(id='duration',kind='duration',parameters={'max_ms':1000}),snapshot)
    assert evaluated.status=='unknown'


def test_bootstrap_preserves_parents_that_are_no_longer_latest(tmp_path):
    script = tmp_path / 'analysis.py'; script.write_text('A = 1\nB = A+1\nA = 3\n')
    with ResearchService(tmp_path) as service:
        run = service.wait(service.start_analysis(script).run_id, 15)
        restored = service.store.bootstrap(run['id'])
    b = next(s for s in restored['snapshots'] if s['name'] == 'B')
    a = next(s for s in restored['snapshots'] if s['name'] == 'A')
    assert b['parents'] and b['parents'][0] != a['id']
    assert restored['parent_bindings'][b['parents'][0]] == a['binding_id']


def test_abrupt_browser_disconnect_retains_service_for_120_seconds():
    from contract_driven_ai_flow.application.lifecycle import ClientLease
    now = [0.0]; closed = []
    leases = ClientLease(lambda: closed.append(True), clock=lambda: now[0])
    lease = leases.acquire('browser'); leases.connected(lease.id, True)
    now[0] = 300; leases.connected(lease.id, False)
    now[0] = 303.1; leases.sweep(); assert not closed
    now[0] = 419.9; leases.sweep(); assert not closed
    now[0] = 420.1; leases.sweep(); leases.sweep(); assert closed == [True]
