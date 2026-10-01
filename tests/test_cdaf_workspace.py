"""Installed users have the same project operations in the terminal and browser."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from contract_driven_ai_flow.cli import app
from contract_driven_ai_flow.examples import create_example
from contract_driven_ai_flow.paths import FlowError
from contract_driven_ai_flow.workspace import Workspace, create_workspace_app


def test_first_use_creates_reusable_example_without_executing_code(tmp_path):
    workspace = Workspace(tmp_path / "user data")
    first = workspace.bootstrap()
    assert first["projects"][0]["name"] == "Signal quality · 数据质量流水线"
    assert workspace.bootstrap()["projects"] == first["projects"]
    root = Path(first["projects"][0]["path"])
    assert (root / "src/steps.py").is_file()
    assert not workspace.project(first["projects"][0]["id"]).runs()


def test_catalogue_registration_and_unlink_never_change_authored_files(tmp_path):
    root = create_example(tmp_path / "existing 项目")
    authored = (root / "flow.yaml").read_bytes()
    workspace = Workspace(tmp_path / "home")
    item = workspace.add(root)
    assert workspace.add(root)["id"] == item["id"]
    workspace.remove(item["id"])
    assert (root / "flow.yaml").read_bytes() == authored
    with pytest.raises(FlowError):
        workspace.project(item["id"])
    with pytest.raises(FlowError):
        workspace.add(tmp_path)


def test_workspace_project_apis_are_scoped_and_authenticated(tmp_path):
    workspace = Workspace(tmp_path / "home")
    workspace.bootstrap()
    with TestClient(create_workspace_app(workspace.root, token="test-session")) as client:
        assert client.get("/api/v1/workspace").status_code == 401
        client.headers["Authorization"] = "Bearer test-session"
        first = client.get("/api/v1/workspace").json()["projects"][0]
        second = client.post("/api/v1/workspace/projects", json={"name": "New project", "template": "blank"}).json()
        prefix = "/p/" + second["id"]
        assert client.get(prefix + "/api/v1/project").json()["project"]["name"] == "New project"
        assert client.get("/p/" + first["id"] + "/api/v1/project").json()["project"]["modules"]
        assert client.get(prefix + "/").status_code == 200
        assert client.get("/p/does-not-exist/api/v1/project").status_code == 404
        client.headers.pop("Authorization")
        assert client.post(prefix + "/api/v1/clean", json={}).status_code == 401


def test_workspace_cli_matches_browser_and_diagnoses_without_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("CDAF_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("OPENAI_API_KEY", "private-test-credential-must-never-appear")
    runner = CliRunner()
    result = runner.invoke(app, ["projects", "create", "--name", "CLI project", "--template", "nested-composite"])
    assert result.exit_code == 0, result.output
    created = json.loads(result.stdout)
    listed = json.loads(runner.invoke(app, ["projects", "list"]).stdout)
    assert created["id"] in [p["id"] for p in listed]
    with TestClient(create_workspace_app(tmp_path / "home", token="test-session")) as client:
        client.headers["Authorization"] = "Bearer test-session"
        assert created["id"] in [p["id"] for p in client.get("/api/v1/workspace").json()["projects"]]
        browser = client.get("/p/" + created["id"] + "/api/v1/doctor").json()
    terminal = json.loads(runner.invoke(app, ["doctor", "--project", created["path"]]).stdout)
    assert browser["checks"] == terminal["checks"]
    assert "private-test-credential-must-never-appear" not in json.dumps(browser)
    assert browser["providers"][1]["configured"] is True


def test_invalid_json_and_exclusive_review_flags_have_readable_errors(tmp_path):
    root = create_example(tmp_path / "project")
    invalid = tmp_path / "input.json"
    invalid.write_text("{not JSON}", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(app, ["run", "-p", str(root), "--input", str(invalid)])
    assert result.exit_code == 1
    assert "Invalid JSON" in result.stderr
    assert "Traceback" not in result.output
    result = runner.invoke(app, ["review", "missing", "-p", str(root), "--accept", "--reject"])
    assert result.exit_code != 0
    assert "one" in result.output.lower()


def test_installed_shortcuts_are_bound_to_the_current_interpreter(tmp_path):
    from contract_driven_ai_flow.shortcuts import create_shortcuts
    import sys
    records = create_shortcuts(tmp_path / "shortcuts", workspace=tmp_path / "home")
    assert records["files"]
    assert all(Path(path).is_file() for path in records["files"])
    assert records["python"] == sys.executable
    assert records["workspace"] == str((tmp_path / "home").resolve())


def test_invalid_request_diagnostics_do_not_repeat_sensitive_values(tmp_path):
    root = create_example(tmp_path / "project")
    from contract_driven_ai_flow.api import create_app
    with TestClient(create_app(root, token="test-session")) as client:
        client.headers["Authorization"] = "Bearer test-session"
        result = client.post("/api/v1/generate", json={"module": "ingest", "provider": {"password": "private-value-in-invalid-body"}})
        assert result.status_code == 422
        assert "private-value-in-invalid-body" not in result.text
