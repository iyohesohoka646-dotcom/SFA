import hashlib
from contract_driven_ai_flow.research.agent.project_runner import run_project
from contract_driven_ai_flow.research.agent.sdk import TraceSession
from contract_driven_ai_flow.research.agent.transport import EventTransport


def test_observer_error_cannot_upgrade_a_program_failure(tmp_path,monkeypatch):
    path=tmp_path/'main.py';path.write_text('raise ValueError("actual program error")\n')
    manifest={str(path.resolve()):{'digest':hashlib.sha256(path.read_bytes()).hexdigest(),'file_id':'f','project_id':'p','project_revision_id':'r'}}
    events=[];session=TraceSession('p',EventTransport(sink=events));emit=session.emit
    def faulty(kind,payload,**kwargs):
        if kind=='analysis.error':raise RuntimeError('observer unavailable')
        return emit(kind,payload,**kwargs)
    monkeypatch.setattr(session,'emit',faulty)
    assert run_project(tmp_path,{'kind':'script','target':'main.py'},session=session,manifest=manifest)==1
    record=next(event for event in events if event['kind']=='run.finished')['payload']
    assert record['status']=='failed' and record['error_type']=='ValueError'
    assert record['project_execution']['complete'] is False
