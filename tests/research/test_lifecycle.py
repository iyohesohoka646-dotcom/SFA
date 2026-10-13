import asyncio
import socket
import threading
import time

import pytest


def test_shutdown_state_cleanup_survives_transient_windows_sharing(tmp_path, monkeypatch):
    import json
    from pathlib import Path
    from contract_driven_ai_flow import studio
    path = tmp_path / '.cdaf/studio.json'; path.parent.mkdir()
    state = {'pid': 123, 'port': 8765, 'token': 'fixture'}
    path.write_text(json.dumps(state))
    original = Path.unlink
    failures = []
    def sharing(self, *args, **kwargs):
        if self == path and len(failures) < 3:
            failures.append(True); raise PermissionError('Windows sharing violation')
        return original(self, *args, **kwargs)
    monkeypatch.setattr(Path, 'unlink', sharing)
    studio.clear_state(tmp_path, state)
    assert len(failures) == 3 and not path.exists()


def test_shutdown_cleanup_preserves_a_new_owner(tmp_path, monkeypatch):
    import json
    from pathlib import Path
    from contract_driven_ai_flow import studio
    path = tmp_path / '.cdaf/studio.json'; path.parent.mkdir()
    state = {'pid': 123, 'port': 8765, 'token': 'fixture'}
    newer = {**state, 'pid': 124}
    path.write_text(json.dumps(state))
    def sharing(self, *args, **kwargs):
        path.write_text(json.dumps(newer))
        raise PermissionError('Windows sharing violation')
    monkeypatch.setattr(Path, 'unlink', sharing)
    studio.clear_state(tmp_path, state)
    assert json.loads(path.read_text()) == newer


def test_connected_leases_survive_background_and_refresh_then_close():
    from contract_driven_ai_flow.application.lifecycle import ClientLease
    now=[0.0];closed=[]
    leases=ClientLease(lambda:closed.append(True),clock=lambda:now[0])
    one=leases.acquire('one');leases.connected(one.id,True)
    now[0]=300;leases.sweep();assert not closed
    two=leases.acquire('two');leases.connected(two.id,True)
    leases.release(one.id);now[0]+=4;leases.sweep();assert not closed
    leases.connected(two.id,False);now[0]+=2
    leases.connected(two.id,True);leases.sweep();assert not closed
    leases.connected(two.id,False);leases.release(two.id)
    now[0]+=3.1;leases.sweep();assert closed==[True]


def test_abandoned_startup_lease_expires_and_shutdown_is_once():
    from contract_driven_ai_flow.application.lifecycle import ClientLease
    now=[0.0];closed=[]
    leases=ClientLease(lambda:closed.append(True),clock=lambda:now[0])
    leases.acquire('lost');now[0]=119;leases.sweep();assert not closed
    now[0]=120.1;leases.sweep();leases.sweep();assert closed==[True]


def test_last_transport_disconnect_stops_without_a_pagehide_request():
    from contract_driven_ai_flow.application.lifecycle import ClientLease
    now=[0.0];closed=[]
    leases=ClientLease(lambda:closed.append(True),clock=lambda:now[0])
    client=leases.acquire('one');leases.connected(client.id,True)
    now[0]=300;leases.connected(client.id,False)
    now[0]=302.9;leases.sweep();assert not closed
    now[0]=303.1;leases.sweep();leases.sweep();assert closed==[True]


def test_a_cancelled_acquisition_cannot_keep_a_used_service_alive():
    from contract_driven_ai_flow.application.lifecycle import ClientLease
    now=[0.0];closed=[]
    leases=ClientLease(lambda:closed.append(True),clock=lambda:now[0])
    leases.acquire('closed-before-response')
    client=leases.acquire('live');leases.connected(client.id,True)
    now[0]=20;leases.release(client.id)
    now[0]=23.1;leases.sweep();assert closed==[True]


def test_owned_service_plain_folder_close_releases_port_and_keeps_cli_run(tmp_path):
    from contract_driven_ai_flow.application.lifecycle import BackendOwner
    from contract_driven_ai_flow.research.service import ResearchService
    script=tmp_path/'slow.py';script.write_text('import time\nX=1\ntime.sleep(5)\nX=2\n')
    with ResearchService(tmp_path) as independent:
        running=independent.start_analysis(script)
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1',0));port=reservation.getsockname()[1]
        owner=BackendOwner(tmp_path,port=port)
        first=owner.start();assert owner.state=='ready' and first.owned
        assert owner.start().pid==first.pid
        borrowed=BackendOwner(tmp_path);assert not borrowed.start().owned
        borrowed.stop();assert owner.state=='ready'
        owner.stop();assert owner.state=='stopped'
        with socket.socket() as connection:assert connection.connect_ex(('127.0.0.1',first.port))!=0
        assert independent.wait(running.run_id,15)['status']=='completed'


def test_close_during_startup_cleans_child_and_failed_attempt_can_retry(tmp_path):
    from contract_driven_ai_flow.application.lifecycle import BackendOwner
    owner=BackendOwner(tmp_path)
    result=[]
    worker=threading.Thread(target=lambda:result.append(owner.start()))
    worker.start();time.sleep(.1);owner.stop();worker.join(10)
    assert not worker.is_alive() and owner.state=='stopped'
    with socket.socket() as listener:
        listener.bind(('127.0.0.1',0));listener.listen()
        failed=BackendOwner(tmp_path,port=listener.getsockname()[1])
        with pytest.raises(Exception):failed.start()
        assert failed.state=='error'
    ready=failed.start();failed.stop();assert ready.owned and failed.state=='stopped'
