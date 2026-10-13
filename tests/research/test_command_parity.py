import asyncio
import json
from collections import Counter

from fastapi.testclient import TestClient
from typer.testing import CliRunner


def test_web_and_batch_cli_use_the_same_observation_semantics(tmp_path):
    from contract_driven_ai_flow.application.commands import dispatch
    from contract_driven_ai_flow.cli import app
    from contract_driven_ai_flow.research.routes import create_research_app
    from contract_driven_ai_flow.research.service import ResearchService
    from contract_driven_ai_flow.research.store import ExperimentStore
    script = tmp_path / 'analysis.py'
    script.write_text('X = 1\nX += 1\n', encoding='utf-8')
    with ResearchService(tmp_path/'web') as service:
        with TestClient(create_research_app(service.root, token='session', service=service)) as client:
            response=client.post('/api/v1/research/commands/run',headers={'Authorization':'Bearer session'},json={'script':str(script)})
            assert response.status_code==200
            result=response.json()
            assert result['status']=='ok' and result['run_id']
            web_run=service.wait(result['run_id'],10)
            web_events=service.events(result['run_id'])
            web_values=service.store.snapshots(result['run_id'],latest=False)
    cli=CliRunner().invoke(app,['--json','observe',str(script),'--project',str(tmp_path/'cli')])
    assert cli.exit_code==0,cli.output
    cli_run=json.loads(cli.output)
    store=ExperimentStore(tmp_path/'cli')
    assert web_run['source_digest']==cli_run['source_digest']
    assert Counter(e['kind'] for e in web_events)==Counter(e.kind for e in store.events(cli_run['id']))
    assert [s.sample['values'] for s in web_values if s.name=='X']==[[[1]],[[2]]]
    assert [s.sample['values'] for s in store.snapshots(cli_run['id'],latest=False) if s.name=='X']==[[[1]],[[2]]]


def test_shared_commands_inspect_records_and_preserve_model_configuration(tmp_path):
    from contract_driven_ai_flow.application.commands import dispatch
    from contract_driven_ai_flow.research.service import ResearchService
    from contract_driven_ai_flow.settings.service import ModelSettingsService
    with ResearchService(tmp_path) as service:
        settings=ModelSettingsService(tmp_path)
        async def scenario():
            saved=await dispatch('models.configure',{'profile':{'id':'local','protocol':'openai-compatible','base_url':'http://127.0.0.1:11434/v1','default_model':'manual'}},service=service,settings=settings)
            assert saved.status=='ok' and saved.data['default_model']=='manual'
            listed=await dispatch('models.list',{},service=service,settings=settings)
            assert any(p['id']=='local' for p in listed.data)
            selected=await dispatch('models.use',{'profile_id':'offline','model':'rules'},service=service,settings=settings)
            assert selected.status=='ok' and selected.data['default_model']=='rules'
            searched=await dispatch('models.search',{'search':'manual'},service=service,settings=settings)
            assert searched.status=='ok' and searched.data==[{'profile_id':'local','model':'manual'}]
            error=await dispatch('run',{'script':'synthetic-missing-file'},service=service,settings=settings)
            assert error.status=='error' and 'synthetic-missing-file' not in error.error
        asyncio.run(scenario())
