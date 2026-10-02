from fastapi.testclient import TestClient
from contract_driven_ai_flow.research.service import ResearchService
from contract_driven_ai_flow.research.routes import create_research_app

def test_settings_project_override_and_group_reset_preserve_user_defaults(tmp_path):
    from contract_driven_ai_flow.research.workbench.preferences import PreferenceService
    service=PreferenceService(tmp_path,user_path=tmp_path/'user.json')
    service.save('user',{'graph':{'dim_unrelated':True}},expected_revision=0)
    current=service.load()
    service.save('project',{'graph':{'dim_unrelated':False}},expected_revision=current['project_revision'])
    assert service.load()['values']['graph']['dim_unrelated'] is False
    assert service.load()['sources']['graph.dim_unrelated']=='project'
    service.reset('project','graph',expected_revision=1)
    assert service.load()['values']['graph']['dim_unrelated'] is True
    assert service.load()['sources']['graph.dim_unrelated']=='user'


def test_settings_routes_and_invalid_budget_are_visible(tmp_path):
    with ResearchService(tmp_path) as research,TestClient(create_research_app(tmp_path,token='session',service=research)) as client:
        h={'Authorization':'Bearer session'}
        result=client.get('/api/v1/research/workbench/settings',headers=h)
        assert result.status_code==200
        revision=result.json()['project_revision']
        result=client.put('/api/v1/research/workbench/settings',headers=h,json={'scope':'project','values':{'capture':{'max_artifact_bytes':-1}},'expected_revision':revision})
        assert result.status_code==400
