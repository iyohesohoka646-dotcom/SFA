import json
import sys

from fastapi.testclient import TestClient

from contract_driven_ai_flow.research.routes import create_research_app
from contract_driven_ai_flow.research.service import ResearchService

def test_probe_definition_is_authored_and_preview_does_not_apply_control(tmp_path):
    script=tmp_path/'analysis.py';script.write_text('import numpy as np\nX = np.array([float("nan")])\n')
    with ResearchService(tmp_path) as service:
        run=service.wait(service.start_analysis(script).run_id,10)
        snapshot=next(s for s in service.store.snapshots(run['id']) if s.name=='X')
        with TestClient(create_research_app(tmp_path,token='s',service=service)) as client:
            headers={'Authorization':'Bearer s'}
            definition={'name':'my experiment','script':str(script),'interpreter':sys.executable,'probes':[{'id':'finite-x','kind':'finite','binding':'X','policy':'pause'}]}
            response=client.put('/api/v1/research/experiment',headers=headers,json=definition)
            assert response.status_code==200
            assert (tmp_path/'research.yaml').is_file()
            restored=client.get('/api/v1/research/experiment',headers=headers).json()
            assert restored['probes'][0]['id']=='finite-x'
            preview=client.post(f'/api/v1/research/snapshots/{snapshot.id}/probe-preview',headers=headers,json=definition['probes'][0])
            assert preview.status_code==200 and preview.json()['status']=='fail'
        assert service.store.run(run['id'])['status']=='completed'

def test_source_preview_and_offline_report_do_not_leak_sensitive_values(tmp_path):
    script=tmp_path/'analysis.py';script.write_text('email = "private@example.org"\nX = 42\n')
    with ResearchService(tmp_path) as service:
        run=service.wait(service.start_analysis(script).run_id,10)
        with TestClient(create_research_app(tmp_path,token='s',service=service)) as client:
            headers={'Authorization':'Bearer s'}
            source=client.post('/api/v1/research/source-preview',headers=headers,json={'path':str(script)})
            assert source.status_code==200 and 'private@example.org' not in source.text
            artifact=client.get(f"/api/v1/research/runs/{run['id']}/export/html",headers=headers)
            assert artifact.status_code==200 and 'private@example.org' not in artifact.text
            assert 'Scientific Dataflow Inspector' in artifact.text
            assert 'source' in artifact.text and '42' in artifact.text

def test_variable_history_returns_exact_versions_in_pages(tmp_path):
    script=tmp_path/'analysis.py';script.write_text('X = 1\nX += 1\nX += 1\n')
    with ResearchService(tmp_path) as service:
        run=service.wait(service.start_analysis(script).run_id,10)
        with TestClient(create_research_app(tmp_path,token='s',service=service)) as client:
            headers={'Authorization':'Bearer s'}
            first=client.get(f"/api/v1/research/runs/{run['id']}/history",headers=headers,params={'binding':'main:X','limit':2})
            assert first.status_code==200
            assert [s['version'] for s in first.json()]==[3,2]
            tail=client.get(f"/api/v1/research/runs/{run['id']}/history",headers=headers,params={'binding':'main:X','limit':2,'before':2})
            assert [s['version'] for s in tail.json()]==[1]
            assert tail.json()[0]['sample']['values']==[[1]]


def test_bootstrap_only_transports_metadata_until_a_value_is_selected(tmp_path):
    script=tmp_path/'analysis.py';script.write_text('import numpy as np\nX = np.arange(10000).reshape(100,100)\n')
    with ResearchService(tmp_path) as service:
        run=service.wait(service.start_analysis(script).run_id,10)
        with TestClient(create_research_app(tmp_path,token='s',service=service)) as client:
            headers={'Authorization':'Bearer s'}
            bootstrap=client.get(f"/api/v1/research/runs/{run['id']}/bootstrap",headers=headers).json()
            indexed=next(item for item in bootstrap['snapshots'] if item['name']=='X')
            assert indexed['sample']=={}
            assert indexed['coverage']['delivery']=='metadata-index'
            assert indexed['fidelity']=='sampled'
            selected=client.get(f"/api/v1/research/snapshots/{indexed['id']}",headers=headers).json()
            assert len(selected['sample']['values'])==32
            assert selected['descriptor']['axes']==[]
            for event in client.get(f"/api/v1/research/runs/{run['id']}/event-page",headers=headers).json():
                if event['kind']=='value.observed':
                    assert 'axes' in event['payload']['snapshot']['descriptor']
