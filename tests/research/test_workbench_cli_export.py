import base64
import json
import sys

from typer.testing import CliRunner

from contract_driven_ai_flow.cli import app
from contract_driven_ai_flow.research.service import ResearchService


def invoke(root, *args):
    result = CliRunner().invoke(app, ['--json', 'research', *args, '--project', str(root)])
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def test_cli_inert_import_plan_real_run_and_saved_probe_outputs(tmp_path):
    source = tmp_path / 'analysis.py'
    source.write_text('import numpy as np\nX = np.arange(6.).reshape(2,3)\n')
    analysis = invoke(tmp_path, 'import', str(source), '--python', sys.executable)
    assert invoke(tmp_path, 'runs') == []
    plan = invoke(tmp_path, 'plan', analysis['id'])
    assert plan['scope'] == 'compute'
    task = invoke(tmp_path, 'run', '--plan', plan['id'])
    assert task['status'] == task['calculation_status'] == 'completed'
    outputs = invoke(tmp_path, 'probes', '--run', task['run_id'])
    assert any(o['definition_id'] == 'view.auto' and o['status'] == 'ready' for o in outputs)
    assert len(invoke(tmp_path, 'tools')) >= 7
    answer = invoke(tmp_path, 'ask', analysis['id'], 'Explain X')
    assert answer['context']['status'] == 'offline'
    assert invoke(tmp_path, 'changes') == []


def test_cli_configuration_migration_preserves_legacy_and_does_not_run(tmp_path):
    legacy = tmp_path / 'research.yaml'
    legacy.write_text('script: sample.py\nprobes:\n- id: finite\n  kind: finite\n', encoding='utf-8')
    original = legacy.read_bytes()
    assert not invoke(tmp_path, 'migrate-config')['applied']
    assert not (tmp_path / 'workbench.yaml').exists()
    assert invoke(tmp_path, 'migrate-config', '--apply')['applied']
    assert legacy.read_bytes() == (tmp_path / 'research.yaml.v1.bak').read_bytes() == original
    assert invoke(tmp_path, 'runs') == []


def test_offline_export_includes_real_plot_and_provenance_without_rerun(tmp_path):
    from contract_driven_ai_flow.research.export import offline_report
    from contract_driven_ai_flow.research.workbench.models import ProbeInstance
    source = tmp_path / 'plot.py'
    source.write_text('import numpy as np\nX = np.arange(6.).reshape(2,3)\n')
    with ResearchService(tmp_path) as research:
        wb = research.workbench
        analysis = wb.import_source(source)
        cfg = wb.configurations.load()
        cfg = wb.configure(cfg.model_copy(update={'script': str(source), 'interpreter': sys.executable,
            'probes': [ProbeInstance(id='plot', definition_id='view.matplotlib', binding='X', budget_ms=30000)]}), expected_revision=cfg.revision)
        task = wb.jobs.wait(wb.execute(wb.plan(analysis.id).id).id, 45)
        assert task.status == 'completed'
        artifact = wb.outputs(task_id=task.id)[0]
        assert artifact['status'] == 'ready', artifact
        path, _ = wb.drawing.artifact(artifact['artifact_id'])
        report = offline_report(research, task.run_id)
        assert 'data:image/png;base64,' + base64.b64encode(path.read_bytes()).decode() in report
        assert artifact['id'] in report and 'program' in report
        assert len(research.store.runs()) == 1
        assert '<script src="http' not in report


def test_terminal_harness_command_preserves_json_and_windows_path():
    from contract_driven_ai_flow.terminal.commands import parse_command
    assert parse_command('/workbench import {"path":"D:\\\\分析\\\\代码.py"}') == ('workbench.import', {'path': 'D:\\分析\\代码.py'})
