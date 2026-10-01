import asyncio
import json

import httpx


def test_multiline_secret_literals_are_redacted_without_changing_source_lines():
    from contract_driven_ai_flow.research.agent.privacy import clean_text
    source='API_SECRET = """\nsynthetic-first-line\nsynthetic-second-line\n"""\nX = 42\n'
    redacted=clean_text(source,16384)
    assert 'synthetic-first-line' not in redacted
    assert 'synthetic-second-line' not in redacted
    assert redacted.count('\n')==source.count('\n')


def test_explanation_context_defaults_to_evidence_without_samples_or_adjacent_source(tmp_path):
    from contract_driven_ai_flow.research.service import ResearchService
    from contract_driven_ai_flow.settings.service import ModelSettingsService
    from contract_driven_ai_flow.settings.explanations import ExplanationService
    script=tmp_path/'analysis.py'
    script.write_text('import numpy as np\napi_secret = "synthetic-source-secret"\nX = np.arange(12).reshape(3,4)\nmu = X.mean(axis=0)\n',encoding='utf-8')
    with ResearchService(tmp_path) as service:
        run=service.wait(service.start_analysis(script).run_id,10)
        operation=next(o for o in service.store.operations(run['id']) if o.label.startswith('mu ='))
        explanations=ExplanationService(service,ModelSettingsService(tmp_path))
        context=explanations.context(operation.id)
        encoded=json.dumps(context)
        assert 'sample' not in context['values'][0]
        assert 'synthetic-source-secret' not in encoded and 'api_secret' not in encoded
        assert context['operation']['source']['digest']==run['source_digest']
        assert context['operation']['source']['code']=='mu = X.mean(axis=0)'
        explicit=explanations.context(operation.id,include_sample=True)
        assert any(v['sample'] for v in explicit['values'])
        explained=asyncio.run(explanations.explain(operation.id,provider_id='offline',model='rules'))
        assert explained.origin=='rule' and operation.id in explained.evidence


def test_model_explanation_preserves_evidence_and_scrubs_echoed_credentials(tmp_path,monkeypatch):
    from contract_driven_ai_flow.research.service import ResearchService
    from contract_driven_ai_flow.settings.models import ProviderProfile
    from contract_driven_ai_flow.settings.service import ModelSettingsService
    from contract_driven_ai_flow.settings.explanations import ExplanationService
    monkeypatch.setenv('CDAF_EXPLANATION_TEST_KEY','synthetic-explanation-key')
    messages=[]
    def handler(request):
        messages.append(json.loads(request.content))
        return httpx.Response(200,json={'choices':[{'message':{'content':'事实：沿 axis=0 求均值。推测：可能代表样本。synthetic-explanation-key'}}],'usage':{'prompt_tokens':42,'completion_tokens':8}})
    script=tmp_path/'analysis.py';script.write_text('import numpy as np\nX = np.ones((2,3))\nmu = X.mean(axis=0)\n')
    with ResearchService(tmp_path) as service:
        run=service.wait(service.start_analysis(script).run_id,10)
        operation=next(o for o in service.store.operations(run['id']) if o.label.startswith('mu ='))
        settings=ModelSettingsService(tmp_path,transport=httpx.MockTransport(handler))
        settings.save(ProviderProfile(id='lab',protocol='openai-compatible',base_url='https://models.example/v1',default_model='manual',credential_ref='env:CDAF_EXPLANATION_TEST_KEY'))
        explanation=asyncio.run(ExplanationService(service,settings).explain(operation.id,provider_id='lab',model='manual'))
        assert explanation.origin=='model' and explanation.usage['prompt_tokens']==42
        assert operation.id in explanation.evidence
        assert 'synthetic-explanation-key' not in explanation.text
        assert explanation.uncertainty
        assert messages[0]['messages'][0]['role']=='system'
        assert 'sample' not in json.loads(messages[0]['messages'][1]['content'])['values'][0]


def test_cli_explanations_and_context_use_the_shared_saved_evidence(tmp_path):
    from typer.testing import CliRunner
    from contract_driven_ai_flow.cli import app
    from contract_driven_ai_flow.research.service import ResearchService
    script=tmp_path/'analysis.py';script.write_text('import numpy as np\nX = np.ones((2,3))\nmu = X.mean(axis=0)\n')
    with ResearchService(tmp_path) as service:
        run=service.wait(service.start_analysis(script).run_id,10)
        operation=next(o for o in service.store.operations(run['id']) if o.label.startswith('mu ='))
    runner=CliRunner()
    result=runner.invoke(app,['--json','research','explain',operation.id,'--project',str(tmp_path)])
    assert result.exit_code==0,result.output
    data=json.loads(result.output)
    assert data['origin']=='rule' and 'axis=0' in data['text'] and operation.id in data['evidence']
    context=runner.invoke(app,['--json','research','explain',operation.id,'--project',str(tmp_path),'--context'])
    assert context.exit_code==0
    assert 'sample' not in json.loads(context.output)['values'][0]
