from pathlib import Path
import sys
import time

from fastapi.testclient import TestClient
import pytest

from contract_driven_ai_flow.research.routes import create_research_app
from contract_driven_ai_flow.research.service import ResearchService
from contract_driven_ai_flow.research.workbench.models import ProbeInstance
from contract_driven_ai_flow.research.workbench.service import WorkbenchService


def configure(workbench, source, probes=None):
    analysis = workbench.import_source(source)
    cfg = workbench.configurations.load()
    return analysis, workbench.configure(cfg.model_copy(update={'script': str(source), 'interpreter': sys.executable,
        **({'probes': probes} if probes is not None else {})}), expected_revision=cfg.revision)


def test_import_configure_run_and_replot_do_not_repeat_side_effects(tmp_path):
    source = tmp_path / 'analysis.py'
    counter = tmp_path / 'counter'
    source.write_text("import numpy as np\nfrom pathlib import Path\np = Path(__file__).with_name('counter')\np.write_text(str(int(p.read_text()) + 1) if p.exists() else '1')\nX = np.arange(6.).reshape(2,3)\nZ = X - X.mean(axis=0)\n", encoding='utf-8')
    with ResearchService(tmp_path) as research:
        workbench = research.workbench
        analysis, config = configure(workbench, source)
        assert not counter.exists()
        plan = workbench.plan(analysis.id)
        task = workbench.execute(plan.id)
        finished = workbench.jobs.wait(task.id, 40)
        assert finished.status == 'completed', finished.message
        assert finished.calculation_status == 'completed'
        assert counter.read_text() == '1'
        outputs = workbench.outputs(task_id=task.id)
        assert any(o['capability'] == 'view' and o['status'] == 'ready' for o in outputs)
        assert any(o['capability'] == 'check' and o['status'] in ('pass', 'unknown') for o in outputs)
        rerender = workbench.replot(finished.run_id, instance_ids=['auto-view'])
        assert workbench.jobs.wait(rerender.id, 20).status == 'completed'
        assert counter.read_text() == '1'


def test_source_version_blocks_old_plan_without_executing(tmp_path):
    source = tmp_path / 'a.py'; source.write_text('X = 1\n')
    with ResearchService(tmp_path) as research:
        analysis, _ = configure(research.workbench, source)
        plan = research.workbench.plan(analysis.id)
        source.write_text('X = 2\n')
        with pytest.raises(ValueError, match='changed'):
            research.workbench.execute(plan.id)


def test_launch_rechecks_the_frozen_digest_before_creating_a_run(tmp_path):
    source = tmp_path / 'a.py'; source.write_text('X = 2\n')
    with ResearchService(tmp_path) as research:
        with pytest.raises(ValueError, match='changed'):
            research.start_analysis(source, expected_digest='stale')
        assert research.store.runs() == []


def test_failed_drawing_does_not_erase_successful_calculation(tmp_path):
    source = tmp_path / 'a.py'; source.write_text('import numpy as np\nX = np.ones((2,2))\n')
    with ResearchService(tmp_path) as research:
        wb = research.workbench
        analysis, _ = configure(wb, source, [ProbeInstance(id='plot', definition_id='view.matplotlib', binding='X', budget_ms=1)])
        task = wb.execute(wb.plan(analysis.id).id)
        finished = wb.jobs.wait(task.id, 30)
        assert finished.status == 'completed' and finished.calculation_status == 'completed'
        assert any(o['status'] == 'error' for o in wb.outputs(task_id=task.id))
        assert finished.receipt['drawing_errors'] >= 1


def test_cancellation_stops_owned_calculation(tmp_path):
    source = tmp_path / 'slow.py'; source.write_text('import time\nX = 1\ntime.sleep(30)\n')
    with ResearchService(tmp_path) as research:
        wb = research.workbench
        analysis, _ = configure(wb, source)
        task = wb.execute(wb.plan(analysis.id).id)
        wb.jobs.cancel(task.id)
        assert wb.jobs.wait(task.id, 12).status == 'cancelled'


def test_api_uses_same_config_and_caps_and_no_implicit_execution(tmp_path):
    source = tmp_path / 'a.py'; source.write_text('X = 1\n')
    with TestClient(create_research_app(tmp_path, token='session')) as client:
        headers = {'Authorization': 'Bearer session'}
        base = '/api/v1/research/workbench'
        result = client.post(base + '/analyses', headers=headers, json={'path': str(source)})
        assert result.status_code == 200, result.text
        assert result.json()['objects'][0]['name'] == 'X'
        assert client.get(base + '/probe-definitions', headers=headers).json()
        assert len(client.get(base + '/tools', headers=headers).json()) >= 7
        assert client.get('/api/v1/research/runs', headers=headers).json() == []


def test_wildcard_has_explicit_limit_and_missing_evidence_is_rejected(tmp_path):
    source = tmp_path / 'a.py'; source.write_text('import numpy as np\n' + ''.join(f'X{i} = np.ones(1)\n' for i in range(8)))
    with ResearchService(tmp_path) as research:
        wb = research.workbench
        analysis, config = configure(wb, source)
        config = wb.configure(config.model_copy(update={'max_outputs': 3}), expected_revision=config.revision)
        task = wb.execute(wb.plan(analysis.id).id)
        finished = wb.jobs.wait(task.id, 30)
        assert len(finished.output_ids) <= 3 and finished.receipt['truncated']
        with pytest.raises(LookupError): wb.replot('no-such-run')
