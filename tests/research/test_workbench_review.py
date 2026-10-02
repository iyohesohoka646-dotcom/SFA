"""Regression boundaries found in the independent 0.4 review."""
import json
import subprocess
import sys
import threading
import time

import pytest

from contract_driven_ai_flow.research.service import ResearchService
from contract_driven_ai_flow.research.workbench.jobs import JobManager
from contract_driven_ai_flow.research.workbench.store import WorkbenchStore
from contract_driven_ai_flow.research.workbench.process import run_process
from contract_driven_ai_flow.research.workbench.models import ProbeInstance


def test_sensitive_assignment_never_rolls_back_to_redacted_source(tmp_path):
    path = tmp_path / 'private.py'
    path.write_text('X = {"password": "original-private-value", "n": 1}\nY = 3\n', encoding='utf-8')
    with ResearchService(tmp_path) as research:
        wb = research.workbench
        analysis = wb.import_source(path)
        obj = next(o for o in analysis.objects if o.name == 'X')
        proposal = wb.changes.propose(analysis.id, obj.id, 'X = {"n": 2}\n')
        assert proposal.status == 'valid'
        assert proposal.original_fragment is None
        assert 'original-private-value' not in json.dumps(wb.store.get('proposals', proposal.id))
        wb.changes.accept(proposal.id)
        before = path.read_bytes()
        with pytest.raises(ValueError, match='safe scoped rollback'):
            wb.changes.rollback(proposal.id)
        assert path.read_bytes() == before and b'[REDACTED]' not in before


def test_another_job_manager_keeps_live_tasks_and_recovers_dead_owner(tmp_path):
    store = WorkbenchStore(tmp_path)
    first = JobManager(store)
    started, release = threading.Event(), threading.Event()
    def work(task, cancel):
        started.set()
        release.wait(4)
    task = first.submit('blocking', work)
    assert started.wait(2)
    second = JobManager(store)
    try:
        assert first.get(task.id).status == 'running'
    finally:
        release.set()
        first.close()
        second.close()
    script = ('from pathlib import Path\nfrom contract_driven_ai_flow.research.workbench.jobs import JobManager\n'
              'from contract_driven_ai_flow.research.workbench.store import WorkbenchStore\n'
              'import os,time\nm=JobManager(WorkbenchStore(Path(' + repr(str(tmp_path)) + ')))\n'
              'm.submit("crashed-owner",lambda task,cancel:time.sleep(30))\ntime.sleep(.1)\nos._exit(0)\n')
    subprocess.run([sys.executable, '-X', 'utf8', '-c', script], check=True, timeout=8)
    third = JobManager(store)
    try:
        assert next(t for t in third.list() if t['kind'] == 'crashed-owner')['status'] == 'interrupted'
    finally:
        third.close()


@pytest.mark.parametrize('stream', ['stdout', 'stderr'])
def test_worker_diagnostic_budget_stops_output_before_timeout(stream):
    script = f'import sys,time;sys.{stream}.buffer.write(b"x"*2097152);sys.{stream}.flush();time.sleep(10)'
    started = time.monotonic()
    with pytest.raises(ValueError, match='byte budget'):
        run_process([sys.executable, '-c', script], timeout=1.5)
    assert time.monotonic() - started < 1.5


def test_cancelled_historical_probes_can_be_retried_without_poisoning_run(tmp_path, monkeypatch):
    path = tmp_path / 'analysis.py'
    path.write_text('import numpy as np\nX = np.ones((2,2))\n', encoding='utf-8')
    with ResearchService(tmp_path) as research:
        wb = research.workbench
        analysis = wb.import_source(path)
        cfg = wb.configurations.load()
        wb.configure(cfg.model_copy(update={'script': str(path), 'probes': []}), expected_revision=cfg.revision)
        run_task = wb.jobs.wait(wb.execute(wb.plan(analysis.id).id).id, 30)
        snapshot = next(s for s in research.store.snapshots(run_task.run_id) if s.name == 'X')
        cfg = wb.configurations.load()
        probes = [ProbeInstance(id='a', definition_id='check.finite', binding='X'), ProbeInstance(id='b', definition_id='check.shape', binding='X', parameters={'expected': [2, 2]})]
        wb.configure(cfg.model_copy(update={'probes': probes}), expected_revision=cfg.revision)
        render = wb.drawing.render
        def cancelled(instance, value, *, cancel=None):
            result = render(instance, value, cancel=cancel)
            cancel.set()
            return result
        monkeypatch.setattr(wb.drawing, 'render', cancelled)
        first = wb.execute_probes(run_task.run_id, snapshot_ids=[snapshot.id])
        assert wb.jobs.wait(first.id, 15).status == 'cancelled'
        monkeypatch.setattr(wb.drawing, 'render', render)
        second = wb.execute_probes(run_task.run_id, snapshot_ids=[snapshot.id])
        assert wb.jobs.wait(second.id, 15).status == 'completed'
        assert {o['status'] for o in wb.outputs(task_id=second.id)} == {'pass'}


@pytest.mark.parametrize('switch_source', [False, True])
def test_legacy_wildcard_matches_saved_evidence_and_old_source_path(tmp_path, switch_source):
    path = tmp_path / 'a.py'
    path.write_text('import numpy as np\nX1 = np.ones(2)\nX2 = np.ones(2)\nY = np.zeros(2)\n')
    with ResearchService(tmp_path) as research:
        wb = research.workbench
        analysis = wb.import_source(path)
        cfg = wb.configurations.load()
        wb.configure(cfg.model_copy(update={'script': str(path), 'probes': []}), expected_revision=cfg.revision)
        run = wb.jobs.wait(wb.execute(wb.plan(analysis.id).id).id, 30).run_id
        other = tmp_path / 'b.py' if switch_source else path
        if switch_source: other.write_text('Z = 2\n')
        wb.import_source(other)
        cfg = wb.configurations.load()
        wb.configure(cfg.model_copy(update={'script': str(other), 'probes': [ProbeInstance(id='finite', definition_id='check.finite', binding='X*')]}), expected_revision=cfg.revision)
        task = wb.execute_probes(run)
        assert wb.jobs.wait(task.id, 15).status == 'completed'
        outputs = wb.outputs(task_id=task.id)
        assert len(outputs) == 2 and {research.store.snapshot(o['snapshot_id']).name for o in outputs} == {'X1', 'X2'}
