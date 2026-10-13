import threading

import pytest

from contract_driven_ai_flow.research.models import SnapshotRef, SourceRef, ValueDescriptor
from contract_driven_ai_flow.research.workbench.analysis import analyze_source
from contract_driven_ai_flow.research.workbench.catalog import ProbeCatalog
from contract_driven_ai_flow.research.workbench.configuration import ConfigurationStore
from contract_driven_ai_flow.research.workbench.models import ProbeDefinition, ProbeInstance, WorkbenchConfig
from contract_driven_ai_flow.research.workbench.planning import compile_plan
from contract_driven_ai_flow.research.workbench.rendering import DrawingService


def test_selected_historical_evidence_is_loaded_and_frozen_without_snapshot_list(tmp_path):
    from contract_driven_ai_flow.research.service import ResearchService
    from contract_driven_ai_flow.research.workbench.bindings import snapshot_target
    from contract_driven_ai_flow.research.workbench.semantic_models import ScopeSelector
    script = tmp_path / 'versions.py'
    script.write_text('X = 1\nX = 2\n', encoding='utf-8')
    with ResearchService(tmp_path) as research:
        wb = research.workbench
        analysis = wb.import_source(script)
        run = research.wait(research.start_analysis(script).run_id, 15)
        old, current = [s for s in research.store.snapshots(run['id'], latest=False) if s.name == 'X']
        ref = snapshot_target(old, analysis).model_copy(update={'exact_evidence': True})
        cfg = wb.configurations.load()
        wb.configure(cfg.model_copy(update={'probes': [ProbeInstance(id='scalar', definition_id='view.scalar')]}), expected_revision=cfg.revision)
        plan = wb.plan(analysis.id, scope='replot', run_id=run['id'], target_scope=ScopeSelector(mode='selection', targets=[ref]))
        assert [t.snapshot_id for t in plan.resolved_targets] == [old.id]
        assert [call.targets[0].snapshot_id for call in plan.invocations] == [old.id]
        task = wb.execute(plan.id)
        assert wb.jobs.wait(task.id, 15).status == 'completed'
        outputs = wb.outputs(task_id=task.id)
        assert len(outputs) == 1 and outputs[0]['snapshot_id'] == old.id
        assert outputs[0]['snapshot_id'] != current.id
        missing = ref.model_copy(update={'snapshot_id': 'missing-snapshot'})
        with pytest.raises((ValueError, LookupError), match='snapshot|evidence|available'):
            wb.plan(analysis.id, scope='replot', run_id=run['id'], target_scope=ScopeSelector(mode='selection', targets=[missing]))


def test_stale_exact_selection_is_never_a_silent_empty_scope(tmp_path):
    from contract_driven_ai_flow.research.workbench.bindings import snapshot_target
    from contract_driven_ai_flow.research.workbench.semantic_models import ScopeSelector
    from contract_driven_ai_flow.research.workbench.scopes import resolve_scope
    analysis, value = fixture(tmp_path)
    old = snapshot_target(value('X', 1), analysis).model_copy(update={'exact_evidence': True})
    latest = snapshot_target(value('X', 2), analysis)
    with pytest.raises(ValueError, match='evidence|available'):
        resolve_scope(analysis.graph, ScopeSelector(mode='selection', targets=[old]), [latest])


def fixture(tmp_path):
    script = tmp_path / 'analysis.py'
    script.write_text('X = 1\nY = X + 1\n', encoding='utf-8')
    analysis = analyze_source(script)
    def value(name, version=1):
        obj = next(obj for obj in analysis.objects if obj.name == name)
        return SnapshotRef(id=name+str(version), name=name, run_id='run', binding_id='main:'+name, scope_id='main', version=version,
            descriptor=ValueDescriptor(kind='scalar', backend='python', type_name='int'), sample={'values': [[version]]}, fidelity='exact',
            source=SourceRef(path=analysis.path, digest=analysis.source_digest, line=obj.line, end_line=obj.end_line))
    return analysis, value


def test_default_presenter_is_visible_and_deletion_survives_reload(tmp_path):
    from contract_driven_ai_flow.research.workbench.bindings import effective_presenters
    analysis, value = fixture(tmp_path)
    config_store = ConfigurationStore(tmp_path)
    config = config_store.load()
    auto = next(probe for probe in config.probes if probe.definition_id == 'view.auto')
    assert auto.origin == 'project_default'
    config = config_store.save(config.model_copy(update={'probes': []}), expected_revision=0)
    assert effective_presenters(config, ProbeCatalog().definitions(), value('X'), analysis) == []
    assert ConfigurationStore(tmp_path).load().probes == []
    assert effective_presenters(ConfigurationStore(tmp_path).load(), ProbeCatalog().definitions(), value('X', 2), analysis) == []


def test_local_exception_and_manual_views_are_independent(tmp_path):
    from contract_driven_ai_flow.research.workbench.bindings import effective_presenters, set_local_override
    analysis, value = fixture(tmp_path)
    config = WorkbenchConfig()
    original = config.model_dump_json()
    changed = set_local_override(config, 'auto-view', analysis.objects[0].logical_key, enabled=False)
    assert effective_presenters(changed, ProbeCatalog().definitions(), value('X', 2), analysis) == []
    assert effective_presenters(changed, ProbeCatalog().definitions(), value('Y'), analysis)
    assert config.model_dump_json() == original
    changed.probes.append(ProbeInstance(id='manual-values', definition_id='view.scalar', binding='X'))
    assert [probe.id for probe in effective_presenters(changed, ProbeCatalog().definitions(), value('X'), analysis)] == ['manual-values']
    restored = set_local_override(changed, 'auto-view', analysis.objects[0].logical_key, restore=True)
    assert {probe.id for probe in effective_presenters(restored, ProbeCatalog().definitions(), value('X'), analysis)} == {'auto-view', 'manual-values'}


def test_resolved_call_freezes_definition_targets_parameters_and_version(tmp_path):
    from contract_driven_ai_flow.research.workbench.semantic_models import ScopeSelector
    from contract_driven_ai_flow.research.workbench.bindings import snapshot_target
    analysis, value = fixture(tmp_path)
    target = snapshot_target(value('X'), analysis)
    config = WorkbenchConfig(probes=[ProbeInstance(id='scalar', definition_id='view.scalar', parameters={'precision': 3})])
    catalog = ProbeCatalog()
    plan = compile_plan(analysis, config, catalog.definitions(), scope='probes', run_id='run', snapshots=[value('X'), value('Y')],
        target_scope=ScopeSelector(mode='selection', targets=[target, target]))
    assert len(plan.invocations) == 1
    call = plan.invocations[0]
    assert call.targets[0].snapshot_id == 'X1' and call.definition.id == 'view.scalar'
    config.probes[0].parameters['precision'] = 9
    catalog._definitions['view.scalar'].version = '2'
    assert call.instance.parameters['precision'] == 3 and call.definition.version == '1'
    assert len(plan.resolved_targets) == 1


def test_drawing_uses_frozen_definition_instead_of_mutated_catalog(tmp_path):
    analysis, value = fixture(tmp_path)
    catalog = ProbeCatalog()
    frozen = catalog.resolve('view.scalar')
    catalog._definitions['view.scalar'] = ProbeDefinition(id='view.scalar', label='changed', capability='check', execution='manual', version='2')
    with DrawingService(tmp_path, catalog) as drawing:
        output = drawing.render(ProbeInstance(definition_id='view.scalar'), value('X'), definition=frozen)
    assert output.capability == 'view' and output.status == 'ready'
    assert output.data['definition_version'] == '1'


def test_taxonomy_and_manifest_are_validated_before_enable(tmp_path):
    catalog = ProbeCatalog()
    definitions = catalog.definitions()
    assert {'view', 'check', 'interpret', 'derive'} <= {definition.capability for definition in definitions}
    assert any('file' in definition.supported_targets for definition in definitions)
    assert any('function' in definition.supported_targets for definition in definitions)
    from contract_driven_ai_flow.research.workbench.resources import ResourceManager
    manager = ResourceManager(tmp_path, catalog)
    manifest = {'id': 'custom.view', 'label': 'Custom values', 'version': '1', 'source': 'local',
        'definitions': [{'id': 'view.custom', 'label': 'Custom', 'capability': 'view', 'execution': 'builtin',
            'supported_targets': ['data'], 'parameter_schema': {'type': 'object', 'properties': {'precision': {'type': 'integer', 'minimum': 0}}}}]}
    resource = manager.import_manifest(manifest)
    assert resource.status == 'draft'
    assert not any(definition.id == 'view.custom' for definition in catalog.definitions())
    manager.enable(resource.id)
    assert catalog.resolve('view.custom').resource_id == 'custom.view'
    manager.disable(resource.id)
    with pytest.raises(ValueError, match='registered'):
        catalog.resolve('view.custom')
    manifest['definitions'][0]['parameter_schema'] = {'type': 'not-a-json-schema-type'}
    with pytest.raises(ValueError, match='schema'):
        manager.import_manifest(manifest)


def test_invalid_probe_parameters_are_rejected_during_planning(tmp_path):
    analysis, _ = fixture(tmp_path)
    catalog = ProbeCatalog()
    config = WorkbenchConfig(probes=[ProbeInstance(definition_id='view.scalar', parameters={'precision': -1})])
    with pytest.raises(ValueError, match='precision'):
        compile_plan(analysis, config, catalog.definitions())


def test_structured_target_check_does_not_cancel_unselected_global(tmp_path):
    from contract_driven_ai_flow.research.service import ResearchService
    from contract_driven_ai_flow.research.workbench.semantic_models import ScopeSelector
    from contract_driven_ai_flow.research.workbench.scopes import source_targets
    script = tmp_path / 'scopes.py'
    script.write_text('import numpy as np\nX = np.array([float("nan")])\ndef f():\n    X = np.array([1.0])\n    return X\nresult = f()\n', encoding='utf-8')
    with ResearchService(tmp_path) as research:
        wb = research.workbench
        analysis = wb.import_source(script)
        local = next(target for target in source_targets(analysis) if target.logical_key.endswith('::f::X'))
        cfg = wb.configurations.load()
        wb.configure(cfg.model_copy(update={'script': str(script), 'probes': [ProbeInstance(id='local-finite', definition_id='check.finite', policy='cancel',
            selector=ScopeSelector(mode='selection', targets=[local]))]}), expected_revision=cfg.revision)
        task = wb.execute(wb.plan(analysis.id).id)
        final = wb.jobs.wait(task.id, 15)
        assert final.calculation_status == 'completed', final.message
        assert all(output['targets'][0]['logical_key'].endswith('::f::X') for output in wb.outputs(task_id=task.id))


def test_presenter_endpoint_reflects_disabled_default_after_configuration_change(tmp_path):
    from fastapi.testclient import TestClient
    from contract_driven_ai_flow.research.routes import create_research_app
    from contract_driven_ai_flow.research.service import ResearchService
    analysis, value = fixture(tmp_path)
    with ResearchService(tmp_path) as research:
        wb = research.workbench
        imported = wb.import_source(analysis.path)
        run = research.wait(research.start_analysis(analysis.path).run_id, 15)
        snapshot = next(snapshot for snapshot in research.store.snapshots(run['id']) if snapshot.name == 'X')
        with TestClient(create_research_app(tmp_path, token='token', service=research)) as client:
            url = f'/api/v1/research/workbench/snapshots/{snapshot.id}/presenters'
            headers = {'Authorization': 'Bearer token'}
            assert client.get(url, headers=headers).status_code == 200
            cfg = wb.configurations.load()
            wb.configure(cfg.model_copy(update={'probes': []}), expected_revision=cfg.revision)
            assert client.get(url, headers=headers).json() == []


def test_evidence_plan_does_not_reresolve_catalog_when_executing(tmp_path):
    from contract_driven_ai_flow.research.service import ResearchService
    analysis, _ = fixture(tmp_path)
    with ResearchService(tmp_path) as research:
        wb = research.workbench
        imported = wb.import_source(analysis.path)
        cfg = wb.configurations.load()
        wb.configure(cfg.model_copy(update={'probes': [ProbeInstance(id='values', definition_id='view.scalar', binding='X')]}), expected_revision=cfg.revision)
        run = research.wait(research.start_analysis(analysis.path).run_id, 15)
        plan = wb.plan(imported.id, scope='replot', run_id=run['id'])
        wb.catalog._definitions['view.scalar'] = ProbeDefinition(id='view.scalar', label='Changed', capability='check', execution='manual', version='2')
        task = wb.execute(plan.id)
        final = wb.jobs.wait(task.id, 15)
        assert final.status == 'completed', final.message
        outputs = wb.outputs(task_id=task.id)
        assert len(outputs) == 1 and outputs[0]['capability'] == 'view' and outputs[0]['status'] == 'ready'
        assert outputs[0]['data']['definition_version'] == '1'


def test_resource_catalog_separates_public_availability_from_local_installation(tmp_path):
    from contract_driven_ai_flow.research.workbench.resources import ResourceManager
    from contract_driven_ai_flow.research.workbench.tools import ToolManager
    manager = ResourceManager(tmp_path, ProbeCatalog(), ToolManager(tmp_path))
    resources = manager.resources()
    assert next(resource for resource in resources if resource['id'] == 'builtin')['status'] == 'installed'
    assert next(resource for resource in resources if resource['id'] == 'adapter.matplotlib')['status'] == 'available'


def test_control_scope_can_be_probed_from_saved_evidence(tmp_path):
    from contract_driven_ai_flow.research.service import ResearchService
    from contract_driven_ai_flow.research.workbench.scopes import source_targets
    from contract_driven_ai_flow.research.workbench.semantic_models import ScopeSelector
    script = tmp_path/'controls.py'
    script.write_text('for i in range(3):\n    pass\n', encoding='utf-8')
    with ResearchService(tmp_path) as research:
        wb = research.workbench
        analysis = wb.import_source(script)
        loop = next(target for target in source_targets(analysis) if target.kind == 'control')
        cfg = wb.configurations.load()
        wb.configure(cfg.model_copy(update={'probes': [ProbeInstance(definition_id='view.controls', selector=ScopeSelector(mode='selection', targets=[loop]))]}), expected_revision=cfg.revision)
        run = research.wait(research.start_analysis(script).run_id, 15)
        plan = wb.plan(analysis.id, scope='probes', run_id=run['id'], target_scope=ScopeSelector(mode='selection', targets=[loop]))
        task = wb.execute(plan.id)
        final = wb.jobs.wait(task.id, 15)
        assert final.status == 'completed', final.message
        outputs = wb.outputs(task_id=task.id)
        assert len(outputs) == 1 and outputs[0]['status'] == 'ready'
        assert outputs[0]['data']['control_summaries'][0]['body_entries'] == 3


def test_explicit_model_source_scope_does_not_expand_via_control_edges(tmp_path):
    from contract_driven_ai_flow.research.workbench.intelligence.context import HarnessContextBuilder
    from contract_driven_ai_flow.research.workbench.intelligence.harness import HarnessRequest
    script = tmp_path/'scope.py'
    script.write_text('flag = True\nif flag:\n    X = 1\ndef unrelated():\n    secret_logic = 2\n    return secret_logic\n', encoding='utf-8')
    analysis = analyze_source(script)
    x = next(obj for obj in analysis.objects if obj.name == 'X')
    request = HarnessRequest(question='Explain', analysis_id=analysis.id, source_object_ids=[x.id])
    permitted = HarnessContextBuilder(None).authorized_objects(analysis, request)
    assert permitted == {x.id}


def test_changed_drawing_resource_version_is_blocked_before_worker_launch(tmp_path):
    _, value = fixture(tmp_path)
    class Tools:
        def resolve(self, tool):
            return 'nonexistent-interpreter', '2'
    with DrawingService(tmp_path, ProbeCatalog(), tools=Tools()) as drawing:
        output = drawing.render(ProbeInstance(definition_id='view.matplotlib'), value('X'),
            definition=ProbeCatalog().resolve('view.matplotlib'), resource_versions={'matplotlib': '1'})
    assert output.status == 'unknown' and 'version changed' in output.message


def test_matching_does_not_truncate_objects_before_resolving_probe_scope(tmp_path):
    from contract_driven_ai_flow.research.service import ResearchService
    script = tmp_path/'many.py'
    script.write_text(''.join(f'X{i} = {i}\n' for i in range(8)))
    with ResearchService(tmp_path) as research:
        wb = research.workbench
        analysis = wb.import_source(script)
        cfg = wb.configurations.load()
        wb.configure(cfg.model_copy(update={'script': str(script), 'max_outputs': 1, 'probes': [ProbeInstance(definition_id='view.scalar', binding='X7')]}), expected_revision=cfg.revision)
        task = wb.execute(wb.plan(analysis.id).id)
        final = wb.jobs.wait(task.id, 15)
        assert final.status == 'completed', final.message
        outputs = wb.outputs(task_id=task.id)
        assert len(outputs) == 1 and outputs[0]['status'] == 'ready'
        assert outputs[0]['targets'][0]['logical_key'].endswith('::X7')
