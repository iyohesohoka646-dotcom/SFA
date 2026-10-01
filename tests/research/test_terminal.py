import asyncio

from typer.testing import CliRunner


def test_terminal_entry_routes_tty_help_and_json_without_hijacking_pipes(monkeypatch):
    from contract_driven_ai_flow.cli import app
    from contract_driven_ai_flow.terminal.app import should_open_terminal
    assert should_open_terminal(True,True,False)
    assert not should_open_terminal(False,True,False)
    assert not should_open_terminal(True,True,True)
    assert CliRunner().invoke(app,[]).exit_code==0
    assert CliRunner().invoke(app,['--help']).exit_code==0
    assert CliRunner().invoke(app,['--json']).exit_code==0


def test_terminal_commands_preserve_quoted_windows_paths_and_empty_arguments():
    from contract_driven_ai_flow.terminal.commands import parse_command
    assert parse_command('/open "C:\\My Lab\\analysis.py"')==('open',{'script':'C:\\My Lab\\analysis.py'})
    assert parse_command('/run -- "" "a b"')==('run',{'arguments':['','a b']})
    assert parse_command('/model lab manual-model')==('models.use',{'profile_id':'lab','model':'manual-model'})
    assert parse_command('/model search manual')==('models.search',{'search':'manual'})
    assert parse_command('/explain --provider lab --model manual --sample')==('explain',{'provider_id':'lab','model':'manual','include_sample':True})


def test_disconnected_command_cancels_the_actual_model_transport(tmp_path):
    import httpx
    from contract_driven_ai_flow.application.request import await_connected
    from contract_driven_ai_flow.settings.models import ProviderProfile
    from contract_driven_ai_flow.settings.service import ModelSettingsService
    async def scenario():
        started,ended=asyncio.Event(),asyncio.Event()
        async def handler(request):
            started.set()
            try:await asyncio.Event().wait()
            finally:ended.set()
        class Request:
            async def is_disconnected(self):return started.is_set()
        settings=ModelSettingsService(tmp_path,transport=httpx.MockTransport(handler))
        settings.save(ProviderProfile(id='local',protocol='openai-compatible',base_url='http://127.0.0.1:1234/v1'))
        result=await await_connected(Request(),settings.test('local',operation_id='disconnect'))
        assert result.status=='cancelled' and ended.is_set()
        assert not settings._tasks
    asyncio.run(scenario())


def test_terminal_input_and_help_stay_available_during_a_slow_model_request(tmp_path):
    import httpx
    from textual.widgets import Input
    from contract_driven_ai_flow.terminal.app import ResearchTerminal
    from contract_driven_ai_flow.terminal.client import LocalResearchClient
    from contract_driven_ai_flow.research.service import ResearchService
    from contract_driven_ai_flow.settings.service import ModelSettingsService
    from contract_driven_ai_flow.settings.models import ProviderProfile
    async def scenario():
        started,cancelled=asyncio.Event(),asyncio.Event()
        async def handler(request):
            started.set()
            try:await asyncio.Event().wait()
            finally:cancelled.set()
        with ResearchService(tmp_path) as service:
            settings=ModelSettingsService(tmp_path,transport=httpx.MockTransport(handler))
            settings.save(ProviderProfile(id='lab',protocol='openai-compatible',base_url='https://models.example/v1'))
            client=LocalResearchClient(service,settings)
            terminal=ResearchTerminal(client)
            async with terminal.run_test(size=(120,36)) as pilot:
                command=terminal.query_one('#command',Input)
                command.value='/model test lab'
                await pilot.press('enter')
                await asyncio.wait_for(started.wait(),3)
                command.value='/help'
                await pilot.press('enter')
                await pilot.pause()
                assert terminal.last_result.status=='ok' and '/open' in terminal.last_result.data['help']
                assert not command.disabled
                await pilot.press('ctrl+c')
                await asyncio.wait_for(cancelled.wait(),3)
                await pilot.pause()
                command.value='/quit'
                await pilot.press('enter')
            assert not settings._tasks
    asyncio.run(scenario())


def test_terminal_runs_stream_values_and_recovers_an_existing_run(tmp_path):
    from textual.widgets import Input,DataTable
    from contract_driven_ai_flow.terminal.app import ResearchTerminal
    from contract_driven_ai_flow.terminal.client import LocalResearchClient
    from contract_driven_ai_flow.research.service import ResearchService
    from contract_driven_ai_flow.settings.service import ModelSettingsService
    script=tmp_path/'analysis.py';script.write_text('X = 42\n')
    async def scenario():
        with ResearchService(tmp_path) as service:
            existing=service.wait(service.start_analysis(script).run_id,10)
            terminal=ResearchTerminal(LocalResearchClient(service,ModelSettingsService(tmp_path)))
            async with terminal.run_test(size=(120,36)) as pilot:
                command=terminal.query_one('#command',Input)
                command.value='/resume '+existing['id']
                await pilot.press('enter')
                for _ in range(50):
                    await pilot.pause(.05)
                    if terminal.query_one('#variables',DataTable).row_count:break
                assert terminal.query_one('#variables',DataTable).row_count==1
                assert terminal.run_id==existing['id']
                command.value='/quit';await pilot.press('enter')
    asyncio.run(scenario())


def test_terminal_reconnects_after_early_eof_without_repeating_events(monkeypatch):
    import json
    import threading
    from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
    from contract_driven_ai_flow.terminal.client import ResearchClient
    monkeypatch.setenv('CDAF_TERMINAL_TEST_SESSION','synthetic-terminal-session')
    requests=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            if not self.path.split('?',1)[0].endswith('/events'):
                body=json.dumps({'status':'running' if len(requests)==1 else 'completed'}).encode()
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body);return
            requests.append((self.path,self.headers.get('Last-Event-ID')))
            events=[{'sequence':1,'kind':'run.started'}]
            if len(requests)>1:events.append({'sequence':2,'kind':'run.finished'})
            body=''.join('data: '+json.dumps(event)+'\n\n' for event in events).encode()
            self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
    async def scenario():
        client=ResearchClient(f'http://127.0.0.1:{server.server_port}','env:CDAF_TERMINAL_TEST_SESSION')
        try:return [event['sequence'] async for event in client.events('fixture')]
        finally:await client.close()
    try:
        assert asyncio.run(scenario())==[1,2]
        assert requests[1][1]=='1' and 'after=1' in requests[1][0]
    finally:server.shutdown();server.server_close();worker.join(2)


def test_terminal_model_commands_follow_the_server_deadline(monkeypatch):
    import json
    import threading
    import time
    from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
    from contract_driven_ai_flow.terminal.client import ResearchClient
    monkeypatch.setenv('CDAF_TERMINAL_TEST_SESSION','synthetic-terminal-session')
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            self.rfile.read(int(self.headers['Content-Length']))
            time.sleep(11)
            body=json.dumps({'status':'ok','data':{'status':'connected'},'error':'','run_id':None}).encode()
            self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers()
            try:self.wfile.write(body)
            except OSError:pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
    async def scenario():
        client=ResearchClient(f'http://127.0.0.1:{server.server_port}','env:CDAF_TERMINAL_TEST_SESSION')
        try:return await client.command('models.test',{'profile_id':'fixture'})
        finally:await client.close()
    try:assert asyncio.run(scenario()).status=='ok'
    finally:server.shutdown();server.server_close();worker.join(2)
