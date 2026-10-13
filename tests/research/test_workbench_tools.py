import sys

import pytest

from contract_driven_ai_flow.research.workbench.tools import ToolManager


def test_public_catalog_does_not_depend_on_host_packages(tmp_path):
    tools = ToolManager(tmp_path)
    catalog = tools.catalog()
    assert {'matplotlib', 'seaborn', 'plotly', 'altair', 'bokeh', 'pyvista', 'holoviews'} <= {t['id'] for t in catalog}
    assert next(t for t in catalog if t['id'] == 'pyvista')['adapter_status'] == 'candidate'
    result = tools.scan(sys.executable)
    assert result['method'] == 'distribution-metadata'
    assert result['interpreter'] == sys.executable
    assert 'import matplotlib' not in tools.discovery_code
    assert next(t for t in tools.catalog() if t['id'] == 'matplotlib')['available']


def test_install_commands_only_target_project_managed_environment(tmp_path):
    tools = ToolManager(tmp_path)
    command = tools.install_command('plotly')
    assert str(tmp_path / '.cdaf') in command[0]
    assert command[-1].startswith('plotly')
    with pytest.raises(ValueError): tools.install_command('anything; bad')
    with pytest.raises(ValueError): tools.remove('matplotlib', interpreter=sys.executable)
    tools.disable('matplotlib')
    assert not next(t for t in tools.catalog() if t['id'] == 'matplotlib')['enabled']


@pytest.mark.parametrize('tool,magic', [('seaborn', b'\x89PNG'), ('plotly', b'<!'), ('altair', b'{')])
def test_optional_adapters_produce_actual_outputs(tmp_path, tool, magic):
    from contract_driven_ai_flow.research.workbench.catalog import ProbeCatalog
    from contract_driven_ai_flow.research.workbench.rendering import DrawingService
    from contract_driven_ai_flow.research.workbench.models import ProbeInstance
    from test_workbench_probes import snapshot
    with DrawingService(tmp_path, ProbeCatalog()) as drawing:
        output = drawing.render(ProbeInstance(definition_id='view.' + tool, budget_ms=30000), snapshot())
        assert output.status == 'ready', output.message
        path, receipt = drawing.artifact(output.artifact_id)
        assert path.read_bytes().startswith(magic)
        assert receipt['tool_id'] == tool and receipt['bytes'] > 20


@pytest.mark.parametrize('tool,kind', [('plotly', 'line'), ('altair', 'line'), ('altair', 'histogram')])
def test_adapter_honors_requested_chart_semantics(tmp_path, tool, kind):
    import json
    from contract_driven_ai_flow.research.workbench.catalog import ProbeCatalog
    from contract_driven_ai_flow.research.workbench.rendering import DrawingService
    from contract_driven_ai_flow.research.workbench.models import ProbeInstance
    from test_workbench_probes import snapshot
    with DrawingService(tmp_path, ProbeCatalog()) as drawing:
        output = drawing.render(ProbeInstance(definition_id='view.' + tool, parameters={'kind': kind}, budget_ms=30000), snapshot())
        assert output.status == 'ready', output.message
        path, _ = drawing.artifact(output.artifact_id)
        if tool == 'plotly':
            import re
            html = path.read_text(encoding='utf-8')
            offset = list(re.finditer(r'Plotly\.newPlot\(\s*"[a-f0-9-]+"\s*,\s*', html))[-1].end()
            traces, _ = json.JSONDecoder().raw_decode(html[offset:])
            assert len(traces) == 1 and traces[0]['mode'] == 'lines' and traces[0]['type'] == 'scatter'
        else:
            spec = json.loads(path.read_text())
            assert spec['mark']['type'] == ('line' if kind == 'line' else 'bar')


def test_environment_scan_uses_first_visible_distribution_for_duplicate_names(monkeypatch,capsys):
    import importlib.metadata, json
    from types import SimpleNamespace
    from contract_driven_ai_flow.research.workbench.tools import ToolManager
    monkeypatch.setattr(importlib.metadata,'distributions',lambda:[SimpleNamespace(metadata={'Name':'probe_pkg','Version':'2'}),SimpleNamespace(metadata={'Name':'probe-pkg','Version':'1'})])
    exec(ToolManager.discovery_code,{})
    assert json.loads(capsys.readouterr().out)=={'probe-pkg':'2'}
