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
