import sys
from pathlib import Path

import pytest

from contract_driven_ai_flow.research.workbench.analysis import analyze_source
from contract_driven_ai_flow.research.workbench.configuration import ConfigurationStore
from contract_driven_ai_flow.research.workbench.models import ProbeDefinition, ProbeInstance, WorkbenchConfig
from contract_driven_ai_flow.research.workbench.planning import compile_plan
from contract_driven_ai_flow.research.workbench.store import WorkbenchStore


def test_parse_is_inert_and_qualifies_symbols(tmp_path):
    script = tmp_path / 'analysis.py'
    marker = tmp_path / 'executed'
    script.write_text(f"from pathlib import Path\nPath({str(marker)!r}).touch()\nclass A:\n    def transform(self, x):\n        y = x + 1\n        return y\nclass B:\n    def transform(self, x):\n        return x\n", encoding='utf-8')
    document = analyze_source(script)
    assert not marker.exists()
    assert document.path == str(script.resolve())
    assert {'A.transform', 'B.transform'} <= {o.qualname for o in document.objects}
    selected = next(o for o in document.objects if o.qualname == 'A.transform')
    assert 'class B' not in selected.code
    assert selected.source_digest == document.source_digest


def test_mutation_depends_on_previous_binding_and_scope(tmp_path):
    path = tmp_path / 'flow.py'
    path.write_text('X = [[1, 2]]\nZ = X.copy()\nZ[0][1] = 0\ny = Z\ndef f(X):\n    Z = X\n    return Z\n', encoding='utf-8')
    analysis = analyze_source(path)
    z = [o for o in analysis.objects if o.name == 'Z' and o.scope == '<module>']
    assert len(z) == 2 and z[1].mutation
    assert any(r.source == z[0].id and r.target == z[1].id for r in analysis.relations)
    assert all(r.provenance == 'inferred' for r in analysis.relations)
    assert len({o.id for o in analysis.objects}) == len(analysis.objects)


def test_invalid_source_has_diagnostic_without_execution(tmp_path):
    path = tmp_path / 'bad.py'
    path.write_text('def broken(:\n', encoding='utf-8')
    analysis = analyze_source(path)
    assert analysis.objects == []
    assert any('syntax' in issue.lower() for issue in analysis.diagnostics)
    with pytest.raises(ValueError, match='diagnostic'):
        compile_plan(analysis, WorkbenchConfig(script=str(path)), [])


def test_analysis_uses_the_same_raw_source_digest_as_runtime(tmp_path):
    from contract_driven_ai_flow.research.agent.source import read_source
    path = tmp_path / 'windows.py'
    path.write_bytes(b'X = 1\r\n')
    assert analyze_source(path).source_digest == read_source(path).digest


def test_frozen_plan_and_revision_conflicts(tmp_path):
    script = tmp_path / 'a.py'
    script.write_text('X = [1, 2]\n', encoding='utf-8')
    configs = ConfigurationStore(tmp_path)
    original = configs.load()
    config = configs.save(original.model_copy(update={'script': str(script), 'probes': [ProbeInstance(id='matrix', definition_id='view.matrix')]}), expected_revision=original.revision)
    with pytest.raises(ValueError, match='revision'):
        configs.save(original, expected_revision=original.revision)
    analysis = analyze_source(script)
    definitions = [ProbeDefinition(id='view.matrix', label='矩阵', capability='view', execution='builtin')]
    plan = compile_plan(analysis, config, definitions)
    frozen = plan.model_dump_json()
    config.probes[0].parameters['limit'] = 4
    assert plan.model_dump_json() == frozen
    assert plan.source_digest == analysis.source_digest and plan.config_digest
    store = WorkbenchStore(tmp_path)
    store.put('plans', plan.id, plan)
    assert store.get('plans', plan.id)['config_digest'] == plan.config_digest
    assert len(store.list('plans')) == 1


def test_unknown_or_mismatched_probe_cannot_compile(tmp_path):
    script = tmp_path / 'a.py'
    script.write_text('X = 1\n', encoding='utf-8')
    config = WorkbenchConfig(script=str(script), interpreter=sys.executable, probes=[ProbeInstance(id='unknown', definition_id='not-registered')])
    with pytest.raises(ValueError, match='registered'):
        compile_plan(analyze_source(script), config, [])


def test_legacy_migration_preserves_authored_file(tmp_path):
    old = tmp_path / 'research.yaml'
    original = 'schema_version: 1\nname: old\nscript: analysis.py\nprobes:\n  - id: finite\n    kind: finite\n    binding: X\n'
    old.write_text(original, encoding='utf-8')
    store = ConfigurationStore(tmp_path)
    preview = store.migrate_legacy(apply=False)
    assert preview['config']['probes'][0]['definition_id'] == 'check.finite'
    assert not store.path.exists()
    store.migrate_legacy(apply=True)
    assert old.read_text(encoding='utf-8') == original
    assert (tmp_path / 'research.yaml.v1.bak').read_text(encoding='utf-8') == original
    assert store.load().protocol_version == 3
def test_harness_roles_are_complete_and_unique():
    from pydantic import ValidationError
    from contract_driven_ai_flow.research.workbench.models import WorkbenchConfig, HarnessPolicy
    import pytest
    with pytest.raises(ValidationError, match='harness roles'):
        WorkbenchConfig(harness=[])
    with pytest.raises(ValidationError, match='harness roles'):
        WorkbenchConfig(harness=[HarnessPolicy(role='explain')] * 4)
