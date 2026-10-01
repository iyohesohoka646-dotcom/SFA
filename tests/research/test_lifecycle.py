import asyncio
import socket
import threading
import time

import pytest


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
