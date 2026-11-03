import asyncio
from types import SimpleNamespace


def test_opening_another_project_does_not_retarget_existing_run_controls():
    from contract_driven_ai_flow.application.commands import CommandResult
    from contract_driven_ai_flow.terminal.app import ResearchTerminal

    class Client:
        def __init__(self): self.calls=[]
        async def command(self,name,arguments):
            self.calls.append((name,dict(arguments)))
            if name=='project.open': return CommandResult(status='ok',data={'id':arguments['path']})
            return CommandResult(status='ok',project_id=arguments.get('project_id'),run_id='run-B',data={'snapshots':[]})
        async def events(self,run_id,after=0,project_id=None):
            if False: yield None
        async def close(self): pass

    async def scenario():
        client=Client(); terminal=ResearchTerminal(client)
        async with terminal.run_test(size=(120,36)) as pilot:
            await terminal.execute('project.run',{'project_id':'B'})
            await pilot.pause()
            await terminal.execute('project.open',{'path':'C'})
            assert terminal.project_id=='C'
            await terminal.action_cancel_or_quit()
            assert client.calls[-1]==('cancel',{'run_id':'run-B','project_id':'B'})
            terminal.on_data_table_row_selected(SimpleNamespace(row_key=SimpleNamespace(value='snapshot-B')))
            await pilot.pause()
            assert client.calls[-1]==('inspect',{'snapshot_id':'snapshot-B','project_id':'B'})
    asyncio.run(scenario())
