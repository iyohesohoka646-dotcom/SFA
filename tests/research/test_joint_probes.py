import json
import sys

import numpy as np
import pandas as pd
import pytest

from contract_driven_ai_flow.research.agent.budget import CapturePolicy
from contract_driven_ai_flow.research.agent.sdk import TraceSession
from contract_driven_ai_flow.research.models import ObservationEvent, SourceRef
from contract_driven_ai_flow.research.service import ResearchService
from contract_driven_ai_flow.research.workbench.models import ProbeInstance


def inputs(research, values, *, full=True):
    wb = research.workbench
    path = research.root / 'input.py'
    path.write_text(''.join(name+' = None\n' for name in values))
    analysis = wb.import_source(path)
    run = research.store.create_run(str(path), interpreter=sys.executable, source_digest=analysis.source_digest)
    trace = TraceSession('joint', policy=CapturePolicy(level='full' if full else 'summary'), run_id=run['id'], artifact_root=research.store.state)
    snapshots = []
    for line, (name, value) in enumerate(values.items(), 1):
        snapshots.append(trace.watch(name, value, source={'path': str(path), 'qualname': '', 'line': line, 'end_line': line, 'digest': analysis.source_digest}))
    trace.finish('completed')
    research.store.append([ObservationEvent.model_validate(event) for event in trace.transport.drain()])
    return analysis, run['id'], snapshots


def joint(research, analysis, run_id, snapshots, definition, parameters=None):
    from contract_driven_ai_flow.research.workbench.bindings import snapshot_target
    from contract_driven_ai_flow.research.workbench.semantic_models import ScopeSelector
    wb = research.workbench
    roles = [role.name for role in wb.catalog.resolve(definition).input_roles]
    refs = [snapshot_target(research.store.snapshot(snapshot['id']), analysis) for snapshot in snapshots]
    cfg = wb.configurations.load()
    instance = ProbeInstance(id='joint', definition_id=definition, parameters=parameters or {}, inputs=dict(zip(roles, refs)))
    wb.configure(cfg.model_copy(update={'probes': [instance]}), expected_revision=cfg.revision)
    plan = wb.plan(analysis.id, scope='probes', run_id=run_id, snapshot_ids=[snapshot['id'] for snapshot in snapshots], target_scope=ScopeSelector(mode='selection', targets=refs))
    task = wb.execute(plan.id)
    final = wb.jobs.wait(task.id, 30)
    assert final.status == 'completed', final.message
    outputs = wb.outputs(task_id=task.id)
    assert len(outputs) == 1
    return outputs[0]


def test_matrix_derivation_is_exact_immutable_and_can_be_reprobed(tmp_path):
    with ResearchService(tmp_path) as research:
        left, right = np.arange(6.).reshape(2, 3), np.arange(6.).reshape(3, 2)
        analysis, run_id, snapshots = inputs(research, {'A': left, 'B': right})
        original = [(research.store.state / snapshot['artifact_ref']).read_bytes() for snapshot in snapshots]
        output = joint(research, analysis, run_id, snapshots, 'derive.matmul')
        assert output['status'] == 'ready', output['message']
        assert output['fidelity'] == 'exact'
        derived = research.store.snapshot(output['data']['derived_snapshot_id'])
        assert derived.parents == [snapshot['id'] for snapshot in snapshots]
        np.testing.assert_array_equal(np.load(research.store.state/derived.artifact_ref, allow_pickle=False), left@right)
        assert original == [(research.store.state / snapshot['artifact_ref']).read_bytes() for snapshot in snapshots]
        cfg = research.workbench.configurations.load()
        research.workbench.configure(cfg.model_copy(update={'probes': [ProbeInstance(definition_id='view.matrix', binding=derived.logical_key)]}), expected_revision=cfg.revision)
        assert research.workbench.presenters(derived.id)
        # A retained derived analysis protects its parent artifacts from normal expiry.
        with research.store.connect() as db:
            db.execute("UPDATE runs SET finished='2000-01-01T00:00:00+00:00' WHERE id=?", (run_id,))
        research.store.expire_artifacts()
        assert all((research.store.state / snapshot['artifact_ref']).exists() for snapshot in snapshots)


@pytest.mark.parametrize('definition,left,right,parameters,code', [
    ('derive.elementwise', np.ones((2, 3)), np.ones((1, 3)), {}, 'shape_mismatch'),
    ('derive.matmul', np.ones((2, 3)), np.ones((4, 2)), {}, 'shape_mismatch'),
    ('derive.correlation', np.ones(3), np.arange(3.), {}, 'constant_input'),
    ('derive.elementwise', np.array([np.nan]), np.ones(1), {}, 'missing_values'),
])
def test_invalid_joint_inputs_return_specific_diagnostics(tmp_path, definition, left, right, parameters, code):
    with ResearchService(tmp_path) as research:
        analysis, run_id, snapshots = inputs(research, {'A': left, 'B': right})
        output = joint(research, analysis, run_id, snapshots, definition, parameters)
        assert output['status'] == 'error', output['message']
        assert output['data']['diagnostic_code'] == code
        assert 'derived_snapshot_id' not in output['data']


def test_explicit_broadcast_and_correlation_aggregate_create_new_objects(tmp_path):
    with ResearchService(tmp_path) as research:
        analysis, run_id, snapshots = inputs(research, {'A': np.arange(6.).reshape(2, 3), 'B': np.ones((1, 3))})
        output = joint(research, analysis, run_id, snapshots, 'derive.elementwise', {'broadcast': True, 'operation': 'add'})
        assert output['status'] == 'ready', output['message']
        analysis, run_id, snapshots = inputs(research, {'A': np.arange(5.), 'B': np.arange(5.)*2})
        output = joint(research, analysis, run_id, snapshots, 'derive.correlation')
        assert output['status'] == 'ready' and output['data']['statistics']['coefficient'] == pytest.approx(1)
        output = joint(research, analysis, run_id, snapshots[:1], 'derive.aggregate', {'method': 'mean'})
        assert output['status'] == 'ready', output['message']
        derived = research.store.snapshot(output['data']['derived_snapshot_id'])
        assert derived.sample['values'] == [[2.0]]


def test_preview_and_expired_artifacts_never_become_complete_results(tmp_path):
    with ResearchService(tmp_path) as research:
        analysis, run_id, snapshots = inputs(research, {'A': np.ones((2, 2)), 'B': np.ones((2, 2))}, full=False)
        output = joint(research, analysis, run_id, snapshots, 'derive.elementwise')
        assert output['status'] == 'unknown' and output['data']['diagnostic_code'] == 'full_data_not_captured'
        analysis, run_id, snapshots = inputs(research, {'A': np.ones((2, 2)), 'B': np.ones((2, 2))})
        (research.store.state / snapshots[0]['artifact_ref']).unlink()
        output = joint(research, analysis, run_id, snapshots, 'derive.elementwise')
        assert output['status'] == 'unknown' and output['data']['diagnostic_code'] == 'artifact_expired'


def test_comparison_keeps_inputs_separate_without_new_numeric_conclusions(tmp_path):
    with ResearchService(tmp_path) as research:
        analysis, run_id, snapshots = inputs(research, {'A': np.ones((2, 2)), 'B': np.ones((3, 2))}, full=False)
        output = joint(research, analysis, run_id, snapshots, 'view.compare', {'shared_scale': True})
        assert output['status'] == 'ready'
        assert output['data']['renderer'] == 'compare'
        assert output['parent_snapshot_ids'] == [snapshot['id'] for snapshot in snapshots]
        assert 'derived_snapshot_id' not in output['data']

def test_cross_run_joint_requires_explicit_opt_in_at_plan_and_freezes_versions(tmp_path):
    with ResearchService(tmp_path) as research:
        analysis,first,left=inputs(research,{'A':np.array([1.,2.]),'B':np.array([3.,4.])})
        analysis,second,right=inputs(research,{'A':np.array([5.,6.]),'B':np.array([7.,8.])})
        with pytest.raises(ValueError,match='run'):
            joint(research,analysis,second,[left[0],right[1]],'derive.elementwise')
        output=joint(research,analysis,second,[left[0],right[1]],'derive.elementwise',{'allow_cross_run':True,'operation':'add'})
        assert output['status']=='ready',output
        derived=research.store.snapshot(output['data']['derived_snapshot_id'])
        np.testing.assert_array_equal(np.load(research.store.state/derived.artifact_ref,allow_pickle=False),[8.,10.])
        assert {research.store.snapshot(k).run_id for k in derived.parents}=={first,second}

def test_derived_code_is_inert_reviewable_and_retention_can_be_released(tmp_path):
    with ResearchService(tmp_path) as research:
        analysis,run_id,snapshots=inputs(research,{'A':np.ones((2,2)),'B':np.ones((2,2))})
        output=joint(research,analysis,run_id,snapshots,'derive.elementwise',{'operation':'add'})
        key=output['data']['derived_id'];wb=research.workbench
        proposal=wb.propose_derived(key)
        assert proposal.status=='valid' and not __import__('pathlib').Path(proposal.path).exists()
        assert 'left + right' in proposal.candidate and snapshots[0]['id'] in proposal.candidate
        assert wb.retain_derived(key,False)['retained'] is False
        with research.store.connect() as db:
            assert db.execute('SELECT COUNT(*) FROM artifact_leases WHERE owner=?',('derived:'+key,)).fetchone()[0]==0


def test_table_join_requires_complete_coordinates_and_explicit_keys(tmp_path):
    pytest.importorskip('pyarrow')
    with ResearchService(tmp_path) as research:
        analysis, run_id, snapshots = inputs(research, {'A': pd.DataFrame({'id': [1, 2], 'a': [3, 4]}), 'B': pd.DataFrame({'id': [1, 2], 'b': [5, 6]})})
        output = joint(research, analysis, run_id, snapshots, 'derive.join', {'keys': ['id']})
        assert output['status'] == 'ready', output['message']
        derived = research.store.snapshot(output['data']['derived_snapshot_id'])
        assert derived.sample['columns'] == ['id', 'a', 'b']
        output = joint(research, analysis, run_id, snapshots, 'derive.join')
        assert output['status'] == 'error' and output['data']['diagnostic_code'] == 'join_keys_required'


def test_targeted_full_capture_keeps_unrelated_objects_in_summary(tmp_path):
    source = tmp_path/'capture.py'
    source.write_text('import numpy as np\nA = np.ones((100,100))\nB = np.ones((100,100))\n')
    with ResearchService(tmp_path) as research:
        run = research.wait(research.start_analysis(source, capture={'full_targets': [f'{source}::<module>::A']} ).run_id, 15)
        snapshots = {snapshot.name: snapshot for snapshot in research.store.snapshots(run['id'])}
        assert snapshots['A'].artifact_ref and snapshots['A'].fidelity == 'sampled'
        assert snapshots['B'].artifact_ref is None


def test_coordinate_lengths_and_parameter_templates_are_validated(tmp_path):
    from contract_driven_ai_flow.research.workbench.data_semantics import DataSemantics, AxisSemantics, SemanticsService
    semantics = DataSemantics(logical_key='A', kind='matrix', axes=[AxisSemantics(label='subjects', coordinates=['s1', 's2']), AxisSemantics(label='features', coordinates=[1, 2, 3])])
    service = SemanticsService(tmp_path)
    stored = service.save(semantics, shape=[2, 3])
    assert service.get('A').axes[0].label == 'subjects'
    with pytest.raises(ValueError, match='axis'):
        service.save(semantics, shape=[3, 3])
    template = service.save_template('matrix-values', '矩阵数值', 'view.matrix', {'precision': 3, 'show_values': True}, stored)
    assert service.templates()[0]['id'] == template['id']


@pytest.mark.parametrize('missing', ['error', 'pairwise'])
def test_flattened_correlation_code_reproduces_the_frozen_kernel(tmp_path, missing):
    with ResearchService(tmp_path) as research:
        left = np.array([[1., 2.], [3., 4.]])
        right = np.array([2., 4., 6., 8.])
        if missing == 'pairwise':
            left[0, 1] = np.nan
        analysis, run_id, snapshots = inputs(research, {'A': left, 'B': right})
        output = joint(research, analysis, run_id, snapshots, 'derive.correlation', {'flatten': True, 'missing': missing})
        assert output['status'] == 'ready', output
        proposal = research.workbench.propose_derived(output['data']['derived_id'])
        assert proposal.status == 'valid'
        namespace = {}
        exec(proposal.candidate, namespace)
        kernel = next(value for key, value in namespace.items() if key.startswith('derive_'))
        assert kernel(left, right) == pytest.approx(output['data']['statistics']['coefficient'])


def test_configured_joint_roles_can_follow_logical_objects_in_a_new_compute_run(tmp_path):
    from contract_driven_ai_flow.research.workbench.scopes import source_targets
    source = tmp_path/'fresh.py'
    source.write_text('import numpy as np\nA = np.ones((2,3))\nB = np.ones((3,2))\nC = np.ones((30,30))\n')
    with ResearchService(tmp_path) as research:
        wb = research.workbench
        analysis = wb.import_source(source)
        targets = {target.logical_key.rsplit('::',1)[-1]:target for target in source_targets(analysis) if target.kind == 'data'}
        cfg = wb.configurations.load()
        wb.configure(cfg.model_copy(update={'script': str(source), 'capture': 'summary', 'probes': [ProbeInstance(id='matmul', definition_id='derive.matmul', inputs={'left':targets['A'], 'right':targets['B']})]}), expected_revision=cfg.revision)
        task = wb.execute(wb.plan(analysis.id).id)
        final = wb.jobs.wait(task.id, 25)
        assert final.status == 'completed', final.message
        output = wb.outputs(task_id=task.id)[0]
        assert output['status'] == 'ready', output['message']
        values = {snapshot.name:snapshot for snapshot in research.store.snapshots(final.run_id)}
        assert values['A'].artifact_ref and values['B'].artifact_ref and values['C'].artifact_ref is None


def test_old_coordinate_incomplete_table_and_changed_artifact_are_diagnosed(tmp_path):
    pa = pytest.importorskip('pyarrow')
    import pyarrow.ipc as ipc
    with ResearchService(tmp_path) as research:
        analysis, run_id, snapshots = inputs(research, {'A': pd.DataFrame({'id':[1], 'a':[2]}), 'B':pd.DataFrame({'id':[1],'b':[3]})})
        path = research.store.state/snapshots[0]['artifact_ref']
        with pa.memory_map(str(path),'r') as reader:
            table = ipc.open_file(reader).read_all().combine_chunks()
            table = pa.Table.from_pydict(table.to_pydict(), schema=table.schema)
        with path.open('wb') as stream:
            old = table.replace_schema_metadata({b'cdaf.cell_encoding': b'json-v1'})
            with ipc.new_file(stream, old.schema) as writer:
                writer.write_table(old)
        path.with_suffix(path.suffix+'.meta.json').unlink()
        output = joint(research,analysis,run_id,snapshots,'derive.join',{'keys':['id']})
        assert output['status'] == 'error' and output['data']['diagnostic_code'] == 'coordinate_metadata_missing'
        analysis, run_id, snapshots = inputs(research, {'A':np.ones((2,2)), 'B':np.ones((2,2))})
        path = research.store.state/snapshots[0]['artifact_ref']
        data=bytearray(path.read_bytes()); data[-1]^=1; path.write_bytes(data)
        output = joint(research,analysis,run_id,snapshots,'derive.elementwise')
        assert output['status'] == 'error' and output['data']['diagnostic_code'] == 'artifact_changed'


def test_matrix_semantics_endpoint_validates_and_persists_coordinate_meaning(tmp_path):
    from fastapi.testclient import TestClient
    from contract_driven_ai_flow.research.routes import create_research_app
    with ResearchService(tmp_path) as research:
        analysis, run_id, snapshots=inputs(research,{'A':np.ones((2,3))})
        url=f"/api/v1/research/workbench/snapshots/{snapshots[0]['id']}/semantics"
        with TestClient(create_research_app(tmp_path,token='session',service=research)) as client:
            headers={'Authorization':'Bearer session'}
            body={'semantics':{'logical_key':snapshots[0]['logical_key'],'kind':'matrix','axes':[{'label':'subjects','coordinates':['s1','s2']} ]},'expected_revision':0}
            response=client.put(url,headers=headers,json=body)
            assert response.status_code==200, response.text
            assert client.get(url,headers=headers).json()['axes'][0]['label']=='subjects'
            body['semantics']['axes'][0]['coordinates']=['one']
            assert client.put(url,headers=headers,json=body).status_code==400


def test_coordinate_alignment_is_checked_and_frozen_in_joint_plan(tmp_path):
    from contract_driven_ai_flow.research.workbench.data_semantics import DataSemantics, AxisSemantics
    from contract_driven_ai_flow.research.workbench.bindings import snapshot_target
    with ResearchService(tmp_path) as research:
        analysis, run_id, snapshots=inputs(research, {'A':np.ones((2,2)), 'B':np.ones((2,2))})
        wb=research.workbench
        for snapshot, labels in zip(snapshots, [['a','b'],['b','a']]):
            wb.semantics.save(DataSemantics(logical_key=snapshot['logical_key'], axes=[AxisSemantics(coordinates=labels)]), shape=[2,2])
        result=joint(research, analysis, run_id, snapshots, 'derive.elementwise')
        assert result['data']['diagnostic_code']=='coordinate_mismatch'
        result=joint(research, analysis, run_id, snapshots, 'derive.elementwise', {'alignment':'positional'})
        assert result['status']=='ready'


def test_artifact_receipt_failure_removes_new_data_file(tmp_path):
    from contract_driven_ai_flow.research.agent.artifact_writer import ArtifactWriter
    class BrokenMetadata:
        artifact_extension='.npy'
        def save(self, value, stream, policy):
            stream.write(b'data')
            return {'bad':object()}
    writer=ArtifactWriter(tmp_path, CapturePolicy(level='full'))
    ref, error=writer.save(None, BrokenMetadata(), {'capabilities':['materialize'], 'nbytes':4})
    assert ref is None and error
    assert not list((tmp_path/'artifacts').iterdir())


def define_axes(wb, snapshot, coordinates):
    from contract_driven_ai_flow.research.workbench.data_semantics import DataSemantics, AxisSemantics
    wb.semantics.save(DataSemantics(logical_key=snapshot['logical_key'], kind='matrix', axes=[AxisSemantics(label='subjects' if i == 0 else 'features', coordinates=axis) for i, axis in enumerate(coordinates)]), shape=snapshot['descriptor']['shape'])


def test_two_level_derivation_preserves_coordinates_and_rejects_reversed_subjects(tmp_path):
    with ResearchService(tmp_path) as research:
        wb = research.workbench
        analysis, run_id, snapshots = inputs(research, {'A': np.array([1., 2.]), 'B': np.array([10., 20.]), 'C': np.array([200., 100.]), 'D': np.array([2000., 1000.])})
        for snapshot, coords in zip(snapshots, [['s1', 's2'], ['s1', 's2'], ['s2', 's1'], ['s2', 's1']]):
            define_axes(wb, snapshot, [coords])
        results = [joint(research, analysis, run_id, pair, 'derive.elementwise', {'operation':'add'}) for pair in [snapshots[:2], snapshots[2:]]]
        derived = [research.store.snapshot(output['data']['derived_snapshot_id']) for output in results]
        assert [wb.semantics.get(s.logical_key).axes[0].coordinates for s in derived] == [['s1', 's2'], ['s2', 's1']]
        combined = joint(research, analysis, run_id, [s.model_dump(mode='json') for s in derived], 'derive.elementwise', {'operation':'add'})
        assert combined['status'] == 'error' and combined['data']['diagnostic_code'] == 'coordinate_mismatch'
        assert 'derived_snapshot_id' not in combined['data']


def test_matmul_and_aggregate_propagate_only_the_surviving_axes(tmp_path):
    with ResearchService(tmp_path) as research:
        wb = research.workbench
        analysis, run_id, snapshots = inputs(research, {'A': np.ones((2,3)), 'B': np.ones((3,4))})
        define_axes(wb, snapshots[0], [['s1','s2'], ['a','b','c']])
        define_axes(wb, snapshots[1], [['a','b','c'], ['m','n','o','p']])
        output = joint(research, analysis, run_id, snapshots, 'derive.matmul')
        derived = research.store.snapshot(output['data']['derived_snapshot_id'])
        assert [a.coordinates for a in wb.semantics.get(derived.logical_key).axes] == [['s1','s2'], ['m','n','o','p']]
        reduced = joint(research, analysis, run_id, [derived.model_dump(mode='json')], 'derive.aggregate', {'axis': 1})
        final = research.store.snapshot(reduced['data']['derived_snapshot_id'])
        assert [a.coordinates for a in wb.semantics.get(final.logical_key).axes] == [['s1','s2']]
        records = wb.store.list('derived')
        assert all(record['semantics']['origin'] == 'program' for record in records)


@pytest.mark.parametrize('compute', [False, True])
def test_logical_coordinate_metadata_is_revalidated_for_new_shape(tmp_path, compute):
    with ResearchService(tmp_path) as research:
        wb = research.workbench
        analysis, run_id, old = inputs(research, {'A': np.ones(2), 'B': np.ones(2)})
        for snapshot in old:
            define_axes(wb, snapshot, [['s1','s2']])
        if not compute:
            analysis, run_id, newer = inputs(research, {'A': np.ones(3), 'B': np.ones(3)})
            with pytest.raises(ValueError, match='axis|coordinate'):
                joint(research, analysis, run_id, newer, 'derive.elementwise')
        else:
            from contract_driven_ai_flow.research.workbench.scopes import source_targets
            source = research.root / 'input.py'
            source.write_text('import numpy as np\nA = np.ones(3)\nB = np.ones(3)\n')
            analysis = wb.import_source(source)
            refs = {t.logical_key.rsplit('::',1)[-1]:t for t in source_targets(analysis) if t.kind == 'data'}
            cfg = wb.configurations.load()
            wb.configure(cfg.model_copy(update={'probes':[ProbeInstance(id='derive', definition_id='derive.elementwise', inputs={'left':refs['A'],'right':refs['B']})]}), expected_revision=cfg.revision)
            task = wb.execute(wb.plan(analysis.id).id)
            assert wb.jobs.wait(task.id, 20).status == 'completed'
            output = wb.outputs(task_id=task.id)[0]
            assert output['status'] in ('error','unknown') and output['data']['diagnostic_code'] == 'coordinate_shape_mismatch'
            assert 'derived_snapshot_id' not in output['data']


def test_explicit_broadcast_preserves_nonbroadcast_coordinates(tmp_path):
    with ResearchService(tmp_path) as research:
        wb = research.workbench
        analysis, run_id, snapshots = inputs(research, {'A':np.ones((2,3)), 'B':np.ones(3)})
        define_axes(wb, snapshots[0], [['s1','s2'], ['a','b','c']])
        define_axes(wb, snapshots[1], [['a','b','c']])
        output = joint(research, analysis, run_id, snapshots, 'derive.elementwise', {'broadcast':True, 'operation':'add'})
        assert output['status'] == 'ready', output
        derived = research.store.snapshot(output['data']['derived_snapshot_id'])
        assert [a.coordinates for a in wb.semantics.get(derived.logical_key).axes] == [['s1','s2'], ['a','b','c']]


def test_coordinate_gap_requires_an_explicit_definition_or_positional_choice(tmp_path):
    from contract_driven_ai_flow.research.workbench.data_semantics import DataSemantics, AxisSemantics
    with ResearchService(tmp_path) as research:
        wb = research.workbench
        analysis, run_id, snapshots = inputs(research, {'A':np.ones((2,2)), 'B':np.ones((2,2))})
        output = joint(research, analysis, run_id, snapshots, 'derive.elementwise')
        derived = research.store.snapshot(output['data']['derived_snapshot_id'])
        value = wb.semantics.get(derived.logical_key)
        value.mappings['coordinate_gaps'] = [0]
        wb.semantics.save(value, shape=[2,2])
        refs = [derived.model_dump(mode='json'), derived.model_dump(mode='json')]
        blocked = joint(research, analysis, run_id, refs, 'derive.elementwise')
        assert blocked['status'] == 'error' and blocked['data']['diagnostic_code'] == 'coordinate_metadata_missing'
        explicit = joint(research, analysis, run_id, refs, 'derive.elementwise', {'alignment':'positional'})
        assert explicit['status'] == 'ready'
        value.origin = 'user'
        value.axes = [AxisSemantics(coordinates=['a','b']), AxisSemantics(coordinates=[1,2])]
        accepted = wb.semantics.save(value, shape=[2,2])
        assert not accepted.mappings.get('coordinate_gaps')
        defined = joint(research, analysis, run_id, refs, 'derive.elementwise')
        assert defined['status'] == 'ready'
