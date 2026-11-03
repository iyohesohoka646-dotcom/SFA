"""Disposable real multi-file project for browser acceptance."""
from pathlib import Path
import shutil
import tempfile

import uvicorn
from fastapi.staticfiles import StaticFiles

from browser_session import fixture_session
from contract_driven_ai_flow.research.routes import create_research_app
from contract_driven_ai_flow.research.workbench.models import RunConfiguration

if __name__ == '__main__':
    base=Path(__file__).resolve().parents[1]
    (base/'.work').mkdir(exist_ok=True)
    host=Path(tempfile.mkdtemp(prefix='project-browser-',dir=base/'.work'))
    root=host/'flat-lab'
    shutil.copytree(base/'examples/research/projects/flat-lab',root)
    other=host/'other';other.mkdir();(other/'main.py').write_text('X=42\n',encoding='utf-8')
    app=create_research_app(host,token=fixture_session(),port=8880)
    application=app.state.projects
    project=application.open(root);revision=application.index(project.id)
    config=application.configuration(project.id)
    application.save_entries(project.id,[RunConfiguration(id='main',name='Main',kind='script',target='main.py')],expected_revision=config.revision)
    matrix=host/'matrix-lab'
    shutil.copytree(base/'examples/research/projects/matrix-lab',matrix)
    matrix_project=application.open(matrix);application.index(matrix_project.id)
    config=application.configuration(matrix_project.id)
    application.save_entries(matrix_project.id,[RunConfiguration(id='main',name='Main',kind='script',target='main.py')],expected_revision=config.revision)

    @app.get('/api/v1/project-test-fixture')
    def fixture():
        return {'root':str(root),'other':str(other),'project_id':project.id,'revision_id':revision.id,'matrix_root':str(matrix),'matrix_project_id':matrix_project.id}

    app.mount('/',StaticFiles(directory=base/'src/contract_driven_ai_flow/static',html=True))
    uvicorn.run(app,host='127.0.0.1',port=8880,access_log=False)
