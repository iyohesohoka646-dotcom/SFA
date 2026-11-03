import threading
import time

from contract_driven_ai_flow.research.models import SnapshotRef, ValueDescriptor, ObservationEvent
from contract_driven_ai_flow.research.store import ExperimentStore
from contract_driven_ai_flow.research.workbench.catalog import ProbeCatalog
from contract_driven_ai_flow.research.workbench.models import ProbeInstance
from contract_driven_ai_flow.research.workbench.rendering import DrawingService
from contract_driven_ai_flow.research.workbench.relations import relationship_output
from contract_driven_ai_flow.research.workbench.jobs import JobManager
from contract_driven_ai_flow.research.workbench.store import WorkbenchStore


def snapshot(**changes):
    return SnapshotRef(id='s1', run_id='r1', binding_id='module:X', scope_id='<module>', name='X', version=1,
        descriptor=ValueDescriptor(kind='matrix', backend='numpy', type_name='numpy.ndarray', shape=[2, 2], dtype='float64', nbytes=32),
        fidelity='sampled', sample={'values': [[1, 2], [3, 4]], 'row_indices': [0, 1], 'column_indices': [0, 1]},
        statistics={'sample_count': 4, 'population_count': 8, 'finite_count': 4, 'method': 'sample'}, **changes)


def test_picture_and_check_keep_distinct_status_and_coverage(tmp_path):
    drawing = DrawingService(tmp_path, ProbeCatalog())
    pic = drawing.render(ProbeInstance(id='matrix', definition_id='view.matrix'), snapshot())
    check = drawing.render(ProbeInstance(id='finite', definition_id='check.finite'), snapshot())
    assert pic.status == 'ready' and pic.capability == 'view'
    assert pic.fidelity == 'sampled' and pic.snapshot_id == 's1'
    assert check.status == 'unknown' and check.capability == 'check'
    other = snapshot().model_copy(update={'id': 's2', 'version': 2})
    assert drawing.render(ProbeInstance(id='matrix', definition_id='view.matrix'), other).cache_key != pic.cache_key
    drawing.close()


def test_unknown_type_cannot_be_drawn_as_invented_matrix(tmp_path):
    with DrawingService(tmp_path, ProbeCatalog()) as drawing:
        unknown = snapshot().model_copy(update={'descriptor': ValueDescriptor(kind='object', backend='unknown', type_name='custom.Tensor'), 'sample': {}})
        output = drawing.render(ProbeInstance(definition_id='view.matrix'), unknown)
        assert output.status == 'unknown' and output.data['snapshot_id'] == unknown.id


def test_relation_probe_returns_direct_neighbors_with_provenance(tmp_path):
    store = ExperimentStore(tmp_path)
    run = store.create_run('flow.py', name='relations', interpreter='python', source_digest='digest')
    a = snapshot().model_copy(update={'parents': [], 'run_id': run['id']})
    b = a.model_copy(update={'id': 's2', 'name': 'Z', 'binding_id': 'module:Z', 'parents': ['s1'], 'provenance': 'inferred'})
    c = a.model_copy(update={'id': 's3', 'name': 'Y', 'binding_id': 'module:Y', 'parents': ['s2'], 'provenance': 'observed'})
    store.append([ObservationEvent(run_id=run['id'], kind='value.observed', snapshot_id=s.id, payload={'snapshot': s.model_dump(mode='json')}) for s in [a, b, c]])
    research = type('Research', (), {'store': store})()
    out = relationship_output(research, 's2')
    assert out.data['parents'][0]['id'] == 's1'
    assert out.data['consumers'][0]['id'] == 's3'
    assert {r['provenance'] for r in out.data['relations']} == {'inferred', 'observed'}


def test_jobs_cancel_and_recover_terminal_records(tmp_path):
    store = WorkbenchStore(tmp_path)
    jobs = JobManager(store)
    def slow(task, cancel):
        while not cancel.wait(.01):
            pass
        raise InterruptedError('cancelled')
    task = jobs.submit('drawing', slow)
    jobs.cancel(task.id)
    assert jobs.wait(task.id, 3).status == 'cancelled'
    jobs.close()
    JobManager(store).close()
    assert store.get('tasks', task.id)['status'] == 'cancelled'


def test_matplotlib_returns_real_png_and_cancellation(tmp_path):
    with DrawingService(tmp_path, ProbeCatalog()) as drawing:
        instance = ProbeInstance(definition_id='view.matplotlib', budget_ms=20000)
        result = drawing.render(instance, snapshot())
        assert result.status == 'ready', result.message
        assert drawing.artifact(result.artifact_id)[0].read_bytes().startswith(b'\x89PNG')
        cancel = threading.Event(); cancel.set()
        assert drawing.render(instance.model_copy(update={'parameters': {'kind': 'histogram'}}), snapshot(), cancel=cancel).status == 'cancelled'


def test_worker_budget_kills_plot_without_reusing_success(tmp_path):
    with DrawingService(tmp_path, ProbeCatalog()) as drawing:
        output = drawing.render(ProbeInstance(definition_id='view.matplotlib', budget_ms=1), snapshot())
        assert output.status == 'error' and 'budget' in output.message
        assert list(drawing.artifacts.iterdir()) == []
