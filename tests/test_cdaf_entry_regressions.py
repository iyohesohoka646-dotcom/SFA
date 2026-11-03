"""Regression cases found while using the installed Web and CLI entry points."""
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from contract_driven_ai_flow.api import create_app
from contract_driven_ai_flow.cli import app
from contract_driven_ai_flow.examples import module
from contract_driven_ai_flow.models import ProbeSpec, ProjectSpec
from contract_driven_ai_flow.storage import Store, atomic_write
from contract_driven_ai_flow.workspace import Workspace, create_workspace_app


@pytest.mark.parametrize("cutoff", ["2026-01-01T18:00:00+08:00", "2026-01-01T10:00:00"])
def test_clean_compares_instants_and_treats_naive_cutoff_as_utc(tmp_path, cutoff):
    store = Store(tmp_path)
    project = ProjectSpec()
    store.save(project, None)
    for run_id, started, status in [
        ("old", "2026-01-01T09:00:00+00:00", "completed"),
        ("new", "2026-01-01T12:00:00+00:00", "completed"),
        ("new_offset", "2026-01-01T17:00:00+05:00", "completed"),
        ("active", "2026-01-01T08:00:00+00:00", "running"),
    ]:
        store.create_run(project, {}, run_id)
        with store.connect() as db:
            db.execute("UPDATE runs SET started=?,status=? WHERE id=?", (started, status, run_id))
    with TestClient(create_app(tmp_path, token="review-session")) as client:
        response = client.post("/api/v1/clean", headers={"Authorization": "Bearer review-session"}, json={"runs_before": cutoff})
        assert response.status_code == 200
        assert response.json()["runs_deleted"] == 1
    assert {run["id"] for run in store.runs()} == {"new", "new_offset", "active"}
    assert (tmp_path / "flow.yaml").is_file()


def test_cli_capture_redacts_sensitive_pointer_before_returning_preview(tmp_path):
    sample = tmp_path / "sample.json"
    sample.write_text(json.dumps({"password": "private-capture-value"}), encoding="utf-8")
    result = CliRunner().invoke(app, ["probe", "True", str(sample), "--kind", "capture", "--pointer", "/password"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["value"] == "[REDACTED]"
    assert "private-capture-value" not in result.output


@pytest.mark.parametrize("action,expected", [("cancel", "cancelled"), ("resume", "completed")])
def test_second_project_service_controls_shared_active_run(tmp_path, action, expected):
    store = Store(tmp_path)
    project = ProjectSpec(modules=[module("f", {}, {"type": "integer"})],
                          probes=[ProbeSpec(id="hold", module="f", expression="True", policy="breakpoint")])
    store.save(project, None)
    atomic_write(tmp_path / "src/steps.py", "def f():\n    return 1\n")
    headers = {"Authorization": "Bearer review-session"}
    with TestClient(create_app(tmp_path, token="review-session")) as owner, TestClient(create_app(tmp_path, token="review-session")) as viewer:
        response = owner.post("/api/v1/runs", headers=headers, json={"input": {}, "base_revision": project.revision})
        assert response.status_code == 202
        run_id = response.json()["id"]
        deadline = time.monotonic() + 10
        while store.run(run_id)["status"] != "paused" and time.monotonic() < deadline:
            time.sleep(.05)
        assert viewer.get(f"/api/v1/runs/{run_id}", headers=headers).json()["status"] == "paused"
        response = viewer.post(f"/api/v1/runs/{run_id}/{action}", headers=headers)
        assert response.status_code == 200, response.text
        deadline = time.monotonic() + 5
        while store.run(run_id)["status"] in ("queued", "running", "paused") and time.monotonic() < deadline:
            time.sleep(.05)
        assert store.run(run_id)["status"] == expected
        assert viewer.post(f"/api/v1/runs/{run_id}/cancel", headers=headers).status_code == 409


def test_migration_reports_redact_narrative_but_preserve_authored_definitions(tmp_path):
    source = tmp_path / "legacy"
    atomic_write(source / ".sfa/pipeline.yml", "modules:\n  - id: convert\n    path: src/steps.py\n    entry: convert\npipes: []\n")
    original = {"natural_summary": "Contact test@example.com with token=private-migration-token",
                "input_schema": {"type": "object", "properties": {"password": {"type": "string"}}, "required": ["password"], "additionalProperties": False},
                "output_schema": {"type": "string"}}
    atomic_write(source / ".sfa/modules/convert/contract.json", json.dumps(original))
    atomic_write(source / "src/steps.py", "def convert(password):\n    return password\n")
    home = tmp_path / "home"
    destination = tmp_path / "migrated"
    with TestClient(create_workspace_app(home, token="review-session")) as client:
        headers = {"Authorization": "Bearer review-session"}
        preview = client.post("/api/v1/migrate", headers=headers, json={"source": str(source), "destination": str(destination)})
        assert preview.status_code == 200, preview.text
        assert not preview.json()["issues"]
        assert "private-migration-token" not in preview.text
        assert "test@example.com" not in preview.text
        assert preview.json()["project"]["modules"][0]["contract"]["input"]["properties"]["password"] == {"type": "string"}
        applied = client.post("/api/v1/migrate", headers=headers, json={"source": str(source), "destination": str(destination), "apply": True})
        assert applied.status_code == 200 and applied.json()["applied"]
    assert Store(destination).load().modules[0].description == original["natural_summary"]
    assert json.loads((destination / "legacy/.sfa/modules/convert/contract.json").read_text()) == original
    assert "private-migration-token" not in (destination / "flow/migration-report.json").read_text()


def test_invalid_registered_project_does_not_block_workspace_or_healthy_project(tmp_path, monkeypatch):
    home = tmp_path / "home"
    workspace = Workspace(home)
    healthy = workspace.create("Healthy")
    broken = workspace.create("Broken")
    atomic_write(workspace.project(broken["id"]).root / "flow.yaml", "modules: [\n")
    records = workspace.bootstrap()["projects"]
    assert next(item for item in records if item["id"] == broken["id"])["available"] is False
    with TestClient(create_workspace_app(home, token="review-session")) as client:
        headers = {"Authorization": "Bearer review-session"}
        assert client.get("/api/v1/workspace", headers=headers).status_code == 200
        response = client.get(f"/p/{healthy['id']}/api/v1/project", headers=headers)
        assert response.status_code == 200 and response.json()["project"]["name"] == "Healthy"
    monkeypatch.setenv("CDAF_HOME", str(home))
    result = CliRunner().invoke(app, ["projects", "list"])
    assert result.exit_code == 0, result.output
    assert len(json.loads(result.stdout)) == 2


def test_different_projects_start_simultaneously_on_available_auto_ports(tmp_path):
    from contract_driven_ai_flow.studio import start, stop
    roots = [tmp_path / "first", tmp_path / "second"]
    for root in roots:
        Store(root).save(ProjectSpec(), None)
    ready = threading.Barrier(2)

    def launch(root):
        ready.wait(timeout=5)
        return start(root)

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(launch, root) for root in roots]
            records = [future.result(timeout=40) for future in futures]
        assert len({record["port"] for record in records}) == 2
        assert all(record["pid"] for record in records)
    finally:
        for root in roots:
            stop(root)
