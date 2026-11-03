import os
import sys
import time
import pytest
from fastapi.testclient import TestClient
from contract_driven_ai_flow.research.workbench.terminal import TerminalService
from contract_driven_ai_flow.research.routes import create_research_app

def wait_text(service, key, text, timeout=12):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        value=service.read(key,0)
        if text in value['data']: return value
        time.sleep(.02)
    raise AssertionError(service.read(key,0))

def test_real_python_unicode_tty_resize_interrupt_reconnect_and_cleanup(tmp_path):
    service=TerminalService(tmp_path)
    try:
        session=service.create('python',sys.executable)
        key=session['id'];assert session['status']=='running'
        service.write(key,"import os; print('中文终端', os.isatty(0), os.getcwd())\r")
        result=wait_text(service,key,'中文终端 True')
        assert str(tmp_path) in result['data']
        service.resize(key,41,101)
        assert service.get(key)['rows']==41 and service.get(key)['cols']==101
        service.write(key,"import time; print('sleep-'+str(40+2), flush=True); time.sleep(30)\r")
        wait_text(service,key,'sleep-42');service.write(key,'\x03')
        wait_text(service,key,'KeyboardInterrupt')
        cursor=service.read(key,0)['cursor'];service.write(key,"print('RESUME-'+str(6*7))\r")
        wait_text(service,key,'RESUME-42')
        assert 'RESUME-42' in service.read(key,cursor)['data']
        service.end(key);assert service.get(key)['status']=='ended'
        assert not service.alive(key)
    finally:service.close()

def test_bounded_replay_and_visible_start_failure(tmp_path):
    service=TerminalService(tmp_path,buffer_chars=4096)
    try:
        bad=service.create('python',str(tmp_path/'missing-python'))
        assert bad['status']=='error' and bad['error']
        session=service.create('python',sys.executable)
        service.write(session['id'],"print('A'*18000); print('ENDMARK')\r")
        result=wait_text(service,session['id'],'ENDMARK\r\n')
        assert len(result['data'])<=4096 and result['truncated'] and result['start']>0
    finally:service.close()

def test_terminal_authentication_and_origin_and_cursor(tmp_path):
    app=create_research_app(tmp_path,token='private-test-session',port=8765)
    headers={'Authorization':'Bearer private-test-session'}
    with TestClient(app) as client:
        assert client.post('/api/v1/research/terminals',json={'profile':'python'}).status_code==401
        session=client.post('/api/v1/research/terminals',headers=headers,json={'profile':'python'}).json()
        assert session['status']=='running'
        from starlette.websockets import WebSocketDisconnect
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect('/api/v1/research/terminals/'+session['id']+'/socket',headers={'Origin':'https://foreign.invalid'}) as ws:
                ws.receive_json()
        with client.websocket_connect('/api/v1/research/terminals/'+session['id']+'/socket',headers={'Origin':'http://127.0.0.1:8765'}) as ws:
            ws.send_json({'type':'authenticate','token':'private-test-session','after':0})
            initial = ws.receive_json()
            # First connection must answer fresh ConPTY initialization queries.
            assert initial['replay'] is False
            ws.send_json({'type':'input','data':"print('WEBSOCKET_OK')\r"})
            output=''
            while 'WEBSOCKET_OK' not in output:
                frame=ws.receive_json();output+=frame.get('data','')
                assert frame['replay'] is False
        with client.websocket_connect('/api/v1/research/terminals/'+session['id']+'/socket',headers={'Origin':'http://127.0.0.1:8765'}) as ws:
            ws.send_json({'type':'authenticate','token':'private-test-session','after':0})
            replay = ws.receive_json()
            assert replay['replay'] is True
            assert 'WEBSOCKET_OK' in replay['data']
        assert client.post('/api/v1/research/terminals/'+session['id']+'/end',headers=headers).json()['status']=='ended'

def test_real_shell_commands_and_application_cli(tmp_path):
    service=TerminalService(tmp_path)
    try:
        shell=service.create('shell');assert shell['status']=='running',shell
        service.write(shell['id'],"Write-Output ('SHELL-'+(6*7))\r" if os.name=='nt' else "printf 'SHELL-%s\\n' $((6*7))\r")
        wait_text(service,shell['id'],'SHELL-42')
        cli=service.create('cli',sys.executable);assert cli['status']=='running',cli
        wait_text(service,cli['id'],'Scientific',timeout=20)
        service.end(cli['id']);assert not service.alive(cli['id'])
    finally:service.close()
