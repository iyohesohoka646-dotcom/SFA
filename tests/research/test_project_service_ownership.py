"""Coordinator integration assertions for shared application ownership."""
from contract_driven_ai_flow.research.routes import create_research_app


def test_http_and_child_commands_reuse_exact_application(tmp_path):
    app = create_research_app(tmp_path / "host", token="local-test")
    application = app.state.projects
    try:
        assert app.state.research.project_application is application
        source = tmp_path / "lab"
        source.mkdir()
        (source / "main.py").write_text("X = 1\n", encoding="utf-8")
        project = application.open(source)
        child = application.research(project.id)
        assert child.project_application is application
        assert child._budget is application.budget
        assert not child._owns_project_application
    finally:
        application.close()
        app.state.models.close()
        app.state.research.close()
