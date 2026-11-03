from contract_driven_ai_flow.research.service import ResearchService
from contract_driven_ai_flow.research.workbench.scopes import resolve_scope, source_targets
from contract_driven_ai_flow.research.workbench.semantic_models import ScopeSelector
from contract_driven_ai_flow.research.workbench.bindings import matches_instance
from contract_driven_ai_flow.research.workbench.models import ProbeInstance
import pytest


def test_same_name_function_redefinitions_do_not_share_selected_locals(tmp_path):
    path = tmp_path / 'analysis.py'
    path.write_text('def f():\n    x = 1\n    x = x + 1\n    return x\ndef f():\n    x = 8\n    return x\n', encoding='utf-8')
    with ResearchService(tmp_path) as research:
        analysis = research.workbench.import_source(path)
        available = source_targets(analysis)
        first = next(t for t in available if t.object_id == next(o.id for o in analysis.objects if o.name == 'x' and o.line == 2))
        targets = resolve_scope(analysis.graph, ScopeSelector(mode='selection', targets=[first]), available)
        selected_ids = {t.object_id for t in targets if t.kind == 'data'}
        first_ids = {o.id for o in analysis.objects if o.name == 'x' and o.line in (2, 3)}
        assert selected_ids == first_ids
        functions = [t for t in available if t.kind == 'function']
        selected = resolve_scope(analysis.graph, ScopeSelector(mode='selection', targets=[functions[0]]), available)
        assert functions[1].object_id not in {t.object_id for t in selected}


def test_local_probe_binding_does_not_match_other_same_name_function(tmp_path):
    path = tmp_path / 'analysis.py'
    path.write_text('def f():\n    x = 1\n    x = x + 1\n    return x\ndef f():\n    x = 8\n    return x\n', encoding='utf-8')
    with ResearchService(tmp_path) as research:
        analysis = research.workbench.import_source(path)
        available = source_targets(analysis)
        objects = sorted((o for o in analysis.objects if o.name == 'x'), key=lambda o: o.line)
        refs = [next(t for t in available if t.object_id == obj.id and t.kind == 'data') for obj in objects]
        instance = ProbeInstance(id='local', definition_id='view.auto', binding=refs[0].logical_key, selector=ScopeSelector(mode='selection', targets=[refs[0]]))
        assert matches_instance(instance, refs[0], analysis)
        assert matches_instance(instance, refs[1], analysis)
        assert not matches_instance(instance, refs[2], analysis)


def test_branch_assignments_in_one_lexical_scope_are_one_logical_selection(tmp_path):
    path = tmp_path / 'analysis.py'
    path.write_text('a = 1\nif a > 0:\n    x = 2\nelse:\n    x = 3\ny = x + 1\n', encoding='utf-8')
    with ResearchService(tmp_path) as research:
        analysis = research.workbench.import_source(path)
        available = source_targets(analysis)
        objects = [o for o in analysis.objects if o.name == 'x']
        first = next(t for t in available if t.object_id == objects[0].id and t.kind == 'data')
        selected = resolve_scope(analysis.graph, ScopeSelector(mode='selection', targets=[first]), available)
        assert {t.object_id for t in selected if t.kind == 'data'} == {o.id for o in objects}


def test_saved_function_binding_survives_writing_only_source_revision(tmp_path):
    path = tmp_path / 'analysis.py'
    path.write_text('def f():\n    x=1\n    return x\n', encoding='utf-8')
    with ResearchService(tmp_path) as research:
        old = research.workbench.import_source(path)
        old_ref = next(t for t in source_targets(old) if t.kind == 'function')
        instance = ProbeInstance(id='local', definition_id='interpret.model', selector=ScopeSelector(mode='selection', targets=[old_ref]))
        path.write_text('\n\ndef f():\n    x = 1\n    return x\n', encoding='utf-8')
        new = research.workbench.import_source(path)
        new_targets = source_targets(new)
        new_ref = next(t for t in new_targets if t.kind == 'function')
        assert old_ref.object_id != new_ref.object_id
        assert matches_instance(instance, new_ref, new)
        assert matches_instance(instance, next(t for t in new_targets if t.kind == 'data' and t.logical_key.endswith('::x')), new)
        assert resolve_scope(new.graph, instance.selector, new_targets)


@pytest.mark.parametrize('kind', ['file', 'function'])
def test_saved_block_probe_survives_accepted_format_and_reimport(tmp_path, kind):
    from contract_driven_ai_flow.research.workbench.planning import compile_plan

    path = tmp_path / 'analysis.py'
    original = 'Z=9\ndef f():\n    x=1\n    return x\n'
    formatted = '\nZ = 9\n\n\ndef f():\n    x = 1\n    return x\n'
    path.write_text(original, encoding='utf-8')
    with ResearchService(tmp_path) as research:
        workbench = research.workbench
        old = workbench.import_source(path)
        reference = next(target for target in source_targets(old) if target.kind == kind)
        instance = ProbeInstance(id='block-check', definition_id='check.finite',
            selector=ScopeSelector(mode='block', block_id=reference.block_id, targets=[reference]))
        config = workbench.configurations.load()
        saved = workbench.configure(config.model_copy(update={'script': str(path), 'probes': [instance]}), expected_revision=config.revision)
        proposal = workbench.changes.propose_format(old.id, formatted)
        assert proposal.status == 'valid'
        workbench.changes.accept(proposal.id)
        current = workbench.import_source(path)
        available = source_targets(current)
        current_reference = next(target for target in available if target.kind == kind)
        assert reference.block_id != current_reference.block_id
        assert reference.logical_key == current_reference.logical_key
        expected = resolve_scope(current.graph, ScopeSelector(mode='block', block_id=current_reference.block_id), available)
        persisted = workbench.configurations.load().probes[0]
        selected = resolve_scope(current.graph, persisted.selector, available)
        assert selected == expected
        assert persisted.selector.block_id == reference.block_id
        assert persisted.selector.targets == [reference]
        data = [target for target in selected if target.kind == 'data']
        assert data and all(matches_instance(persisted, target, current) for target in data)
        if kind == 'function':
            assert all(not target.logical_key.endswith('::Z') for target in selected)
        plan = compile_plan(current, saved, workbench.catalog.definitions(), target_scope=persisted.selector)
        assert {call.targets[0].object_id for call in plan.invocations} == {target.object_id for target in data}
        assert research.store.runs() == []


def test_stale_block_probe_with_repeated_definitions_requires_rebinding(tmp_path):
    path = tmp_path / 'analysis.py'
    original = 'def f():\n    x=1\n    return x\ndef f():\n    x=2\n    return x\n'
    formatted = '\n\ndef f():\n    x = 1\n    return x\n\n\ndef f():\n    x = 2\n    return x\n'
    path.write_text(original, encoding='utf-8')
    with ResearchService(tmp_path) as research:
        old = research.workbench.import_source(path)
        reference = next(target for target in source_targets(old) if target.kind == 'function')
        selector = ScopeSelector(mode='block', block_id=reference.block_id, targets=[reference])
        proposal = research.workbench.changes.propose_format(old.id, formatted)
        assert proposal.status == 'valid'
        research.workbench.changes.accept(proposal.id)
        current = research.workbench.import_source(path)
        with pytest.raises(ValueError, match='ambiguous.*bind it again'):
            resolve_scope(current.graph, selector, source_targets(current))


@pytest.mark.parametrize('has_reference', [False, True])
def test_stale_block_without_an_available_logical_reference_never_expands_to_project(tmp_path, has_reference):
    path = tmp_path / 'analysis.py'
    path.write_text('def f():\n    x=1\n    return x\n', encoding='utf-8')
    with ResearchService(tmp_path) as research:
        old = research.workbench.import_source(path)
        reference = next(target for target in source_targets(old) if target.kind == 'function')
        selector = ScopeSelector(mode='block', block_id=reference.block_id,
            targets=[reference.model_copy(update={'logical_key': 'unavailable'})] if has_reference else [])
        proposal = research.workbench.changes.propose_format(old.id, '\n\ndef f():\n    x = 1\n    return x\n')
        research.workbench.changes.accept(proposal.id)
        current = research.workbench.import_source(path)
        with pytest.raises(ValueError, match='Scope block does not belong'):
            resolve_scope(current.graph, selector, source_targets(current))


CONTROL_SOURCES = [
    ('loop', 'outside=99\ntotal=0\nfor i in range(3):\n    total=total+i\nafter=total\n',
        '\n\noutside = 99\n\ntotal = 0\n\nfor i in range(3):\n    total = total + i\n\nafter = total\n'),
    ('condition', 'flag=True\noutside=99\nif flag:\n    x=1\nelse:\n    x=2\nafter=x\n',
        '\n\nflag = True\n\noutside = 99\n\nif flag:\n    x = 1\nelse:\n    x = 2\n\nafter = x\n'),
]


@pytest.mark.parametrize('kind,original,formatted', CONTROL_SOURCES, ids=[case[0] for case in CONTROL_SOURCES])
def test_control_block_binding_survives_accepted_format_and_keeps_runtime_identity(tmp_path, kind, original, formatted):
    from contract_driven_ai_flow.research.agent.instrument import instrument
    from contract_driven_ai_flow.research.agent.sdk import TraceSession

    path = tmp_path / 'analysis.py'
    path.write_text(original, encoding='utf-8')
    with ResearchService(tmp_path) as research:
        workbench = research.workbench
        old = workbench.import_source(path)
        old_text = path.read_bytes().decode('utf-8')
        old_block = next(block for block in old.graph.blocks if block.kind == kind)
        reference = next(target for target in source_targets(old) if target.block_id == old_block.id and target.kind == 'control')
        instance = ProbeInstance(id='control-check', definition_id='check.finite',
            selector=ScopeSelector(mode='block', block_id=old_block.id, targets=[reference]))
        config = workbench.configurations.load()
        workbench.configure(config.model_copy(update={'script': str(path), 'probes': [instance]}), expected_revision=config.revision)
        proposal = workbench.changes.propose_format(old.id, formatted)
        assert proposal.status == 'valid'
        workbench.changes.accept(proposal.id)
        current = workbench.import_source(path)
        current_block = next(block for block in current.graph.blocks if block.kind == kind)
        assert old_block.id != current_block.id
        assert old_block.source.line != current_block.source.line
        assert old_block.logical_key == current_block.logical_key
        available = source_targets(current)
        persisted = workbench.configurations.load().probes[0]
        selected = resolve_scope(current.graph, persisted.selector, available)
        expected = resolve_scope(current.graph, ScopeSelector(mode='block', block_id=current_block.id), available)
        assert selected == expected
        assert all(not target.logical_key.endswith('::outside') for target in selected)
        assert all(matches_instance(persisted, target, current) for target in selected)
        for document, text in [(old, old_text), (current, path.read_bytes().decode('utf-8'))]:
            compiled = instrument(text, document.path, source_digest=document.source_digest)
            ids = {block.id for block in document.graph.blocks if block.kind in ('condition', 'loop')}
            assert {ref['node_id'] for ref in compiled.references if ref['kind'] in ('branch', 'loop')} == ids
            trace = TraceSession('control-identity')
            compiled.execute(trace)
            observed = {summary['node_id'] for event in trace.transport.drain() if event['kind'] == 'control.summary'
                for summary in event['payload']['summaries']}
            assert observed == ids


@pytest.mark.parametrize('kind,original,formatted', CONTROL_SOURCES, ids=[case[0] for case in CONTROL_SOURCES])
def test_control_body_change_does_not_reuse_the_old_block_selector(tmp_path, kind, original, formatted):
    path = tmp_path / 'analysis.py'
    path.write_text(original, encoding='utf-8')
    with ResearchService(tmp_path) as research:
        old = research.workbench.import_source(path)
        old_block = next(block for block in old.graph.blocks if block.kind == kind)
        reference = next(target for target in source_targets(old) if target.kind == 'control' and target.block_id == old_block.id)
        selector = ScopeSelector(mode='block', block_id=old_block.id, targets=[reference])
        changed = original.replace('total+i', 'total-i') if kind == 'loop' else original.replace('x=1', 'x=7')
        path.write_text(changed, encoding='utf-8')
        current = research.workbench.import_source(path)
        current_block = next(block for block in current.graph.blocks if block.kind == kind)
        assert current_block.label == old_block.label
        assert current_block.logical_key != old_block.logical_key
        available = source_targets(current)
        with pytest.raises(ValueError, match='Scope block does not belong'):
            resolve_scope(current.graph, selector, available)
        selected = ProbeInstance(definition_id='check.finite', selector=ScopeSelector(mode='selection', targets=[reference]))
        assert not any(matches_instance(selected, target, current) for target in available)


@pytest.mark.parametrize('kind,original,formatted', CONTROL_SOURCES, ids=[case[0] for case in CONTROL_SOURCES])
def test_identical_control_blocks_require_rebinding_after_source_revision(tmp_path, kind, original, formatted):
    path = tmp_path / 'analysis.py'
    path.write_text(original + original, encoding='utf-8')
    with ResearchService(tmp_path) as research:
        old = research.workbench.import_source(path)
        old_blocks = [block for block in old.graph.blocks if block.kind == kind]
        assert len(old_blocks) == 2 and old_blocks[0].id != old_blocks[1].id
        reference = next(target for target in source_targets(old) if target.kind == 'control' and target.block_id == old_blocks[0].id)
        selector = ScopeSelector(mode='block', block_id=reference.block_id, targets=[reference])
        assert all(target.block_id != old_blocks[1].id for target in resolve_scope(old.graph, selector, source_targets(old)))
        proposal = research.workbench.changes.propose_format(old.id, formatted + formatted)
        assert proposal.status == 'valid'
        research.workbench.changes.accept(proposal.id)
        current = research.workbench.import_source(path)
        with pytest.raises(ValueError, match='ambiguous.*bind it again'):
            resolve_scope(current.graph, selector, source_targets(current))


def test_one_if_keeps_separate_true_and_false_entries(tmp_path):
    path = tmp_path / 'analysis.py'
    path.write_text('flag = True\nif flag:\n    x = 1\nelse:\n    x = 2\n', encoding='utf-8')
    with ResearchService(tmp_path) as research:
        analysis = research.workbench.import_source(path)
        blocks = [block for block in analysis.graph.blocks if block.kind == 'condition']
        assert len(blocks) == 1
        entries = [node for node in analysis.graph.nodes if node.kind == 'entry' and node.block_id == blocks[0].id]
        assert {node.label for node in entries} == {'true', 'false'}
        assert len({node.id for node in entries}) == len({node.logical_key for node in entries}) == 2


REPEATED_FUNCTION_SOURCE = 'def f():\n    x = 1\n    return x\nfirst = f\ndef f():\n    x = 8\n    return x\na = first()\nb = f()\n'


def _local_snapshots(analysis):
    from contract_driven_ai_flow.research.models import SnapshotRef, SourceRef, ValueDescriptor

    return [SnapshotRef(id=f'x-{obj.line}', name='x', logical_key=obj.logical_key,
        run_id='run', binding_id=f'f:{obj.line}:x', scope_id=f'f:{obj.line}', version=1,
        descriptor=ValueDescriptor(kind='scalar', backend='python', type_name='int'),
        sample={'values': [[obj.line]]}, fidelity='exact',
        source=SourceRef(path=analysis.path, digest=analysis.source_digest, line=obj.line, end_line=obj.end_line))
        for obj in analysis.objects if obj.name == 'x']


@pytest.mark.parametrize('disabled', [False, True])
def test_repeated_function_local_overrides_are_isolated_in_presenters_and_plans(tmp_path, disabled):
    from contract_driven_ai_flow.research.workbench.analysis import analyze_source
    from contract_driven_ai_flow.research.workbench.bindings import effective_presenters, set_local_override, snapshot_target
    from contract_driven_ai_flow.research.workbench.catalog import ProbeCatalog
    from contract_driven_ai_flow.research.workbench.models import WorkbenchConfig
    from contract_driven_ai_flow.research.workbench.override_keys import target_override_key
    from contract_driven_ai_flow.research.workbench.planning import compile_plan

    path = tmp_path / 'analysis.py'
    path.write_text(REPEATED_FUNCTION_SOURCE, encoding='utf-8')
    analysis = analyze_source(path)
    values = _local_snapshots(analysis)
    targets = [snapshot_target(value, analysis) for value in values]
    keys = [target_override_key(target, analysis.graph) for target in targets]
    assert targets[0].logical_key == targets[1].logical_key and keys[0] != keys[1]
    config = WorkbenchConfig(probes=[ProbeInstance(id='auto', definition_id='view.auto', parameters={'precision': 3})])
    changed = set_local_override(config, 'auto', keys[0], enabled=not disabled, parameters={'precision': 6})
    definitions = ProbeCatalog().definitions()
    first = effective_presenters(changed, definitions, values[0], analysis)
    second = effective_presenters(changed, definitions, values[1], analysis)
    assert first == [] if disabled else first[0].parameters['precision'] == 6
    assert second[0].parameters['precision'] == 3
    plan = compile_plan(analysis, changed, definitions, scope='replot', run_id='run', snapshots=values)
    calls = {call.targets[0].snapshot_id: call for call in plan.invocations}
    assert (values[0].id in calls) == (not disabled)
    if not disabled:
        assert calls[values[0].id].instance.parameters['precision'] == 6
    assert calls[values[1].id].instance.parameters['precision'] == 3
    restored = set_local_override(changed, 'auto', keys[0], restore=True)
    assert all(effective_presenters(restored, definitions, value, analysis)[0].parameters['precision'] == 3 for value in values)


def test_override_keys_preserve_ordinary_variables_and_one_owner_branch_assignments(tmp_path):
    from contract_driven_ai_flow.research.workbench.analysis import analyze_source
    from contract_driven_ai_flow.research.workbench.override_keys import target_override_key

    path = tmp_path / 'analysis.py'
    path.write_text('X = 1\ndef f(flag):\n    if flag:\n        x = 2\n    else:\n        x = 3\n    return x\ndef g():\n    x = 8\n    return x\n', encoding='utf-8')
    analysis = analyze_source(path)
    refs = [target for target in source_targets(analysis) if target.kind == 'data']
    assert all(target_override_key(ref, analysis.graph) == ref.logical_key for ref in refs)


def test_repeated_function_targets_use_their_own_block_for_overrides(tmp_path):
    from contract_driven_ai_flow.research.workbench.analysis import analyze_source
    from contract_driven_ai_flow.research.workbench.bindings import set_local_override
    from contract_driven_ai_flow.research.workbench.models import WorkbenchConfig
    from contract_driven_ai_flow.research.workbench.override_keys import target_override_key

    path = tmp_path / 'analysis.py'
    path.write_text(REPEATED_FUNCTION_SOURCE, encoding='utf-8')
    analysis = analyze_source(path)
    functions = [target for target in source_targets(analysis) if target.kind == 'function']
    keys = [target_override_key(target, analysis.graph) for target in functions]
    assert keys[0] != keys[1]
    config = WorkbenchConfig(probes=[ProbeInstance(id='model', definition_id='interpret.model')])
    changed = set_local_override(config, 'model', keys[0], enabled=False)
    assert [matches_instance(changed.probes[0], target, analysis) for target in functions] == [False, True]


def test_saved_data_scope_after_accepted_format_requires_rebinding_if_owners_are_ambiguous(tmp_path):
    path = tmp_path / 'analysis.py'
    path.write_text(REPEATED_FUNCTION_SOURCE, encoding='utf-8')
    with ResearchService(tmp_path) as research:
        old = research.workbench.import_source(path)
        ref = next(target for target in source_targets(old) if target.kind == 'data' and target.logical_key.endswith('::x'))
        selector = ScopeSelector(mode='selection', targets=[ref])
        instance = ProbeInstance(definition_id='view.auto', selector=selector)
        proposal = research.workbench.changes.propose_format(old.id, '\n\n' + REPEATED_FUNCTION_SOURCE)
        assert proposal.status == 'valid'
        research.workbench.changes.accept(proposal.id)
        current = research.workbench.import_source(path)
        targets = [target for target in source_targets(current) if target.logical_key == ref.logical_key]
        assert len(targets) == 2 and all(target.block_id != ref.block_id for target in targets)
        with pytest.raises(ValueError, match='Saved data scope is ambiguous.*bind it again'):
            resolve_scope(current.graph, selector, source_targets(current))
        with pytest.raises(ValueError, match='Saved data scope is ambiguous.*bind it again'):
            matches_instance(instance, targets[0], current)


def test_saved_data_scope_with_one_owner_recovers_after_accepted_format(tmp_path):
    path = tmp_path / 'analysis.py'
    text = 'def f(flag):\n    if flag:\n        x = 1\n    else:\n        x = 2\n    return x\n'
    path.write_text(text, encoding='utf-8')
    with ResearchService(tmp_path) as research:
        old = research.workbench.import_source(path)
        ref = next(target for target in source_targets(old) if target.kind == 'data' and target.logical_key.endswith('::x'))
        proposal = research.workbench.changes.propose_format(old.id, '\n\n' + text)
        assert proposal.status == 'valid'
        research.workbench.changes.accept(proposal.id)
        current = research.workbench.import_source(path)
        selected = resolve_scope(current.graph, ScopeSelector(mode='selection', targets=[ref]), source_targets(current))
        assert {target.object_id for target in selected} == {obj.id for obj in current.objects if obj.name == 'x'}


def test_stale_scoped_override_after_format_requires_rebinding_instead_of_restoring_defaults(tmp_path):
    from contract_driven_ai_flow.research.workbench.bindings import effective_presenters, set_local_override, snapshot_target
    from contract_driven_ai_flow.research.workbench.catalog import ProbeCatalog
    from contract_driven_ai_flow.research.workbench.models import WorkbenchConfig
    from contract_driven_ai_flow.research.workbench.override_keys import target_override_key
    from contract_driven_ai_flow.research.workbench.planning import compile_plan

    path = tmp_path / 'analysis.py'
    path.write_text(REPEATED_FUNCTION_SOURCE, encoding='utf-8')
    with ResearchService(tmp_path) as research:
        old = research.workbench.import_source(path)
        value = _local_snapshots(old)[0]
        key = target_override_key(snapshot_target(value, old), old.graph)
        config = set_local_override(WorkbenchConfig(), 'auto-view', key, enabled=False)
        proposal = research.workbench.changes.propose_format(old.id, '\n\n' + REPEATED_FUNCTION_SOURCE)
        assert proposal.status == 'valid'
        research.workbench.changes.accept(proposal.id)
        current = research.workbench.import_source(path)
        values = _local_snapshots(current)
        definitions = ProbeCatalog().definitions()
        with pytest.raises(ValueError, match='Local override scope.*bind it again'):
            effective_presenters(config, definitions, values[0], current)
        with pytest.raises(ValueError, match='Local override scope.*bind it again'):
            compile_plan(current, config, definitions)
        unrelated = next(target for target in source_targets(current) if target.kind == 'data' and target.logical_key.endswith('::a'))
        assert matches_instance(config.probes[0], unrelated, current)
