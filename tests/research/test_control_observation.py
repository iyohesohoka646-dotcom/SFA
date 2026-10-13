import pytest

from contract_driven_ai_flow.research.agent.instrument import instrument
from contract_driven_ai_flow.research.agent.sdk import TraceSession
from contract_driven_ai_flow.research.agent.transport import EventTransport
from contract_driven_ai_flow.research.models import ObservationEvent
from contract_driven_ai_flow.research.store import ExperimentStore


def observed(source, *, sink=None, name='control.py'):
    trace = TraceSession('controls', EventTransport(sink=sink))
    namespace = {'__name__': '__main__'}
    error = None
    try:
        instrument(source, name).execute(trace, namespace)
    except BaseException as exc:
        error = (type(exc).__name__, str(exc))
    events = trace.transport.drain() if sink is None else []
    return namespace, error, events


def plain(source):
    namespace = {'__name__': '__main__'}
    error = None
    try:
        exec(compile(source, 'control.py', 'exec'), namespace)
    except BaseException as exc:
        error = (type(exc).__name__, str(exc))
    return namespace, error


def summaries(events):
    return [summary for event in events if event['kind'] == 'control.summary' for summary in event['payload']['summaries'] if summary['complete']]


@pytest.mark.parametrize('source,expected', [
    ('if True:\n    result = 1\nelse:\n    result = 2\n', {'true_count': 1, 'false_count': 0}),
    ('for i in range(0):\n    pass\nelse:\n    result = 0\n', {'body_entries': 0, 'natural_exits': 1}),
    ('for i in range(4):\n    pass\n', {'body_entries': 4, 'natural_exits': 1}),
    ('for i in range(4):\n    break\n', {'body_entries': 1, 'break_exits': 1}),
    ('for i in range(4):\n    continue\n', {'body_entries': 4, 'natural_exits': 1}),
    ('while False:\n    pass\n', {'body_entries': 0, 'natural_exits': 1}),
    ('for a, b in [(1, 2), (3,)]:\n    pass\n', {'body_entries': 1, 'exception_exits': 1}),
])
def test_actual_branch_and_loop_body_counts(source, expected):
    baseline, error = plain(source)
    result, actual_error, events = observed(source)
    assert actual_error == error
    assert result.get('result') == baseline.get('result')
    records = summaries(events)
    assert records, 'Actual control summaries were not emitted'
    assert all(records[-1][key] == value for key, value in expected.items())


def test_short_circuit_truth_and_iterators_are_never_reevaluated():
    source = '''
calls = []
class Truth:
    def __init__(self, value):
        self.value = value
    def __bool__(self):
        calls.append(self.value)
        return self.value
def iterable():
    calls.append('iterable')
    return [1, 2, 3]
if Truth(False) and Truth(True):
    result = 'yes'
else:
    result = 'no'
for i in iterable():
    if Truth(i < 2) or Truth(False):
        continue
result = (result, list(calls))
'''
    baseline, error = plain(source)
    result, actual_error, events = observed(source)
    assert actual_error == error is None
    assert result['result'] == baseline['result']
    assert summaries(events)


@pytest.mark.parametrize('body,expected', [
    ('try:\n            break\n        finally:\n            continue', 'natural_exits'),
    ('try:\n            continue\n        finally:\n            break', 'break_exits'),
    ('try:\n            return 7\n        finally:\n            break', 'break_exits'),
    ('try:\n            break\n        finally:\n            return 7', 'nonlocal_exits'),
    ('return 7', 'nonlocal_exits'),
    ("raise ValueError('boom')", 'exception_exits'),
])
def test_finally_control_transfers_keep_original_behavior(body, expected):
    source = 'def f():\n    for i in range(3):\n        ' + body + '\n    return 9\nresult = f()\n'
    baseline, error = plain(source)
    result, actual_error, events = observed(source)
    assert actual_error == error
    assert result.get('result') == baseline.get('result')
    loop = next(item for item in summaries(events) if item['kind'] == 'loop')
    assert loop[expected] == 1


def test_recursive_invocations_and_pure_return_functions_are_counted():
    source = 'def f(n):\n    if n:\n        return f(n-1)\n    return 0\nresult = f(3)\n'
    result, error, events = observed(source)
    assert error is None and result['result'] == 0
    branch = next(item for item in summaries(events) if item['kind'] == 'branch')
    assert branch['true_count'] == 3 and branch['false_count'] == 1
    assert len(branch['activation_samples']) == 4
    assert sum(sample['true_count'] for sample in branch['activation_samples']) == 3
    details = [detail for event in events if event['kind'] == 'control.details' for detail in event['payload']['details']]
    activations = {detail['activation_id'] for detail in details if detail['kind'] == 'branch'}
    assert len(activations) == 4
    assert any(detail['parent_activation_id'] for detail in details)


def test_long_loop_has_bounded_durable_details_and_latest_summary(tmp_path):
    store = ExperimentStore(tmp_path)
    run = store.create_run('long.py', interpreter='python', source_digest='test')
    received = []
    def sink(batch):
        received.extend(batch)
        store.append([ObservationEvent.model_validate(dict(event, run_id=run['id'])) for event in batch])
    trace = TraceSession('long', EventTransport(sink=sink, publish_interval_ms=5))
    instrument('for item in range(100_000):\n    pass\n', 'long.py').execute(trace)
    trace.finish('completed')
    controls = store.control_summaries(run['id'])
    assert len(controls) == 1 and controls[0]['body_entries'] == 100_000
    assert controls[0]['complete'] is True
    detail_page = store.control_details(run['id'])
    assert len(detail_page['items']) <= 512
    assert detail_page['omitted'] >= 100_000 - 512
    with store.connect() as db:
        event_count = db.execute('SELECT COUNT(*) FROM events WHERE run_id=?', (run['id'],)).fetchone()[0]
    assert event_count < 600


def test_summary_without_final_receipt_is_a_lower_bound(tmp_path):
    store = ExperimentStore(tmp_path)
    run = store.create_run('interrupted.py', interpreter='python', source_digest='test')
    store.append([ObservationEvent(run_id=run['id'], kind='control.summary', payload={
        'summaries': [{'node_id': 'loop', 'kind': 'loop', 'body_entries': 10, 'revision': 1, 'complete': False}],
        'final': False})])
    assert store.control_summaries(run['id'])[0]['complete'] is False


def test_missing_final_summary_chunk_and_late_old_checkpoints_stay_partial(tmp_path):
    store = ExperimentStore(tmp_path)
    run = store.create_run('partial.py', interpreter='python', source_digest='test')
    def event(kind, payload):
        return ObservationEvent(run_id=run['id'], kind=kind, payload=payload)
    store.append([event('control.summary', {'summaries': [{'node_id': 'loop', 'kind': 'loop', 'body_entries': 20, 'revision': 2, 'complete': True}]}),
        event('control.finished', {'node_count': 2, 'revision': 2, 'complete': True}),
        event('control.summary', {'summaries': [{'node_id': 'loop', 'kind': 'loop', 'body_entries': 1, 'revision': 1, 'complete': False}]})])
    summary = store.control_summaries(run['id'])[0]
    assert summary['body_entries'] == 20 and summary['complete'] is False


def test_observer_failure_does_not_replace_original_exception(monkeypatch):
    from contract_driven_ai_flow.research.agent.control_observation import ControlCollector
    def broken(self, *args):
        raise RuntimeError('observer')
    monkeypatch.setattr(ControlCollector, 'record', broken)
    _, error, events = observed("for i in range(1):\n    raise ValueError('user')\n")
    assert error == ('ValueError', 'user')
    receipt = next(event for event in events if event['kind'] == 'control.finished')
    assert receipt['payload']['complete'] is False


def test_function_controls_are_redacted_before_transport_and_storage(tmp_path):
    import json
    source = 'def f():\n    api_key = "synthetic-control-credential"\n    return 42\nresult = f()\n'
    compiled = instrument(source, 'private.py')
    assert 'synthetic-control-credential' not in json.dumps(compiled.references)
    store = ExperimentStore(tmp_path)
    run = store.create_run('private.py', interpreter='python', source_digest='test')
    trace = TraceSession('private', run_id=run['id'])
    result = compiled.execute(trace)
    assert result['result'] == 42
    events = trace.transport.drain()
    assert 'synthetic-control-credential' not in json.dumps(events)
    store.append([ObservationEvent.model_validate(event) for event in events])
    assert 'synthetic-control-credential' not in json.dumps(store.bootstrap(run['id']))
    assert 'synthetic-control-credential' not in json.dumps([e.model_dump() for e in store.events(run['id'])])


def test_old_control_source_records_are_scrubbed_on_reopen(tmp_path):
    import json
    store = ExperimentStore(tmp_path)
    run = store.create_run('old.py', interpreter='python', source_digest='old')
    summary = {'node_id': 'f', 'kind': 'function', 'revision': 1, 'source': {'code': 'api_key = "synthetic-legacy-control"'}}
    event = ObservationEvent(run_id=run['id'], kind='control.summary', payload={'summaries': [summary]})
    with store.connect() as db:
        db.execute('INSERT INTO control_summaries VALUES (?,?,?,?)', (run['id'], 'f', 1, json.dumps(summary)))
        db.execute('INSERT INTO events(run_id,body) VALUES (?,?)', (run['id'], event.model_dump_json()))
        # Simulate a pre-migration store without the current privacy marker.
        if db.execute("SELECT name FROM sqlite_master WHERE name='research_migrations'").fetchone():
            db.execute("DELETE FROM research_migrations WHERE name='control-source-privacy-v1'")
    reopened = ExperimentStore(tmp_path)
    assert 'synthetic-legacy-control' not in json.dumps(reopened.bootstrap(run['id']))
    with reopened.connect() as db:
        assert all('synthetic-legacy-control' not in row[0] for row in db.execute('SELECT body FROM control_summaries'))
        assert all('synthetic-legacy-control' not in row[0] for row in db.execute('SELECT body FROM events'))


def test_function_control_probe_and_offline_export_never_expose_credentials(tmp_path):
    from contract_driven_ai_flow.research.service import ResearchService
    from contract_driven_ai_flow.research.export import offline_report
    from contract_driven_ai_flow.research.workbench.models import ProbeInstance
    script = tmp_path / 'credentials.py'
    original = 'def calculate():\n    api_key = "synthetic-export-control"\n    return 42\nresult = calculate()\n'
    script.write_text(original, encoding='utf-8')
    with ResearchService(tmp_path) as research:
        wb = research.workbench
        analysis = wb.import_source(script)
        run = research.wait(research.start_analysis(script).run_id, 15)
        config = wb.configurations.load()
        wb.configure(config.model_copy(update={'probes':[ProbeInstance(id='controls',definition_id='view.controls')]}), expected_revision=config.revision)
        task = wb.execute(wb.plan(analysis.id, scope='probes', run_id=run['id']).id)
        assert wb.jobs.wait(task.id, 15).status == 'completed'
        assert wb.outputs(task_id=task.id)
        report = offline_report(research, run['id'])
        assert 'synthetic-export-control' not in report and '[REDACTED]' in report
        assert script.read_text(encoding='utf-8') == original
