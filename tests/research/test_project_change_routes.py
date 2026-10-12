"""P4 reviewed project-change HTTP gateway tests (own tests)."""

from __future__ import annotations

import sys
import threading

import pytest
from fastapi.testclient import TestClient

from contract_driven_ai_flow.research.routes import create_research_app
from contract_driven_ai_flow.research.workbench.models import TaskRecord

PREFIX = "/api/v1/research/projects"
TOKEN = "changes-token"
HEADERS = {"Authorization": "Bearer " + TOKEN}


def lab(root):
    root.mkdir(parents=True, exist_ok=True)
    (root / "calc.py").write_text("def double(v):\n    return v*2\n", encoding="utf-8")
    (root / "main.py").write_text("from calc import double\nY=double(7)\n", encoding="utf-8")


def prepared(client, root):
    app = client.app.state.projects
    project = app.open(root)
    revision = app.index(project.id)
    return app, project, revision


def propose(client, pid, revision_id, edits):
    response = client.post(
        PREFIX + "/" + pid + "/changes",
        headers=HEADERS,
        json={"base_revision": revision_id, "edits": edits},
    )
    assert response.status_code == 200, response.text
    return response.json()


def accept(client, app, pid, change_id, expected_revision):
    response = client.post(
        PREFIX + "/" + pid + "/changes/" + change_id + "/accept",
        headers=HEADERS,
        json={"expected_revision": expected_revision},
    )
    assert response.status_code == 202, response.text
    return app.workbench(pid).jobs.wait(response.json()["id"], 20)


def test_change_routes_require_auth_and_unknown_project_is_404(tmp_path):
    root = tmp_path / "lab"; lab(root)
    with TestClient(create_research_app(tmp_path / "host", token=TOKEN)) as client:
        assert client.get(PREFIX + "/missing/changes").status_code == 401
        assert client.get(PREFIX + "/missing/changes", headers=HEADERS).status_code == 404
        assert client.get(PREFIX + "/missing/changes/recovery", headers=HEADERS).status_code == 404
        assert client.post(
            PREFIX + "/missing/changes", headers=HEADERS,
            json={"base_revision": "x", "edits": []},
        ).status_code == 404


def test_proposal_page_get_and_ownership(tmp_path):
    root = tmp_path / "lab"; lab(root)
    other = tmp_path / "other"; other.mkdir(); (other / "main.py").write_text("X=1\n")
    with TestClient(create_research_app(tmp_path / "host", token=TOKEN)) as client:
        app, project, revision = prepared(client, root)
        base = PREFIX + "/" + project.id
        page = client.get(base + "/changes", headers=HEADERS).json()
        assert page["project_id"] == project.id and page["revision_id"] == revision.id
        assert page["items"] == [] and page["recovery_required"] is False
        change = propose(client, project.id, revision.id, [
            {"path": "calc.py", "content": "def double(v):\n    return v*3\n"},
        ])
        assert change["status"] == "ready" and change["project_id"] == project.id
        got = client.get(base + "/changes/" + change["id"], headers=HEADERS).json()
        assert got["id"] == change["id"]
        assert [c["id"] for c in client.get(base + "/changes", headers=HEADERS).json()["items"]] == [change["id"]]
        p2 = app.open(other)
        assert client.get(PREFIX + "/" + p2.id + "/changes/" + change["id"], headers=HEADERS).status_code == 404
        assert client.get(base + "/changes/" + "0" * 32, headers=HEADERS).status_code == 404
        bad = client.post(base + "/changes", headers=HEADERS, json={
            "base_revision": revision.id,
            "edits": [{"path": "../escape.py", "content": "x=1\n", "operation": "create"}],
        })
        assert bad.status_code == 422, bad.text
        assert client.post(base + "/changes", headers=HEADERS, json={
            "base_revision": revision.id, "edits": []}).status_code == 422
        unknown = client.post(base + "/changes", headers=HEADERS, json={
            "base_revision": "0" * 32,
            "edits": [{"path": "calc.py", "content": "X=1\n"}]})
        assert unknown.status_code == 404, unknown.text
        app.index(project.id)
        stale = client.post(base + "/changes", headers=HEADERS, json={
            "base_revision": revision.id,
            "edits": [{"path": "calc.py", "content": "Y=1\n"}]})
        assert stale.status_code == 409, stale.text


def test_accept_applies_two_files_and_publishes(tmp_path):
    root = tmp_path / "lab"; lab(root)
    with TestClient(create_research_app(tmp_path / "host", token=TOKEN)) as client:
        app, project, revision = prepared(client, root)
        base = PREFIX + "/" + project.id
        change = propose(client, project.id, revision.id, [
            {"path": "calc.py", "content": "def double(v):\n    return v*3\n"},
            {"path": "main.py", "content": "from calc import double\nY=double(9)\n"},
        ])
        task = accept(client, app, project.id, change["id"], revision.id)
        assert task.status == "completed", task.message
        assert task.receipt["change_id"] == change["id"]
        assert task.receipt["project_id"] == project.id
        assert task.receipt["project_revision_id"] == task.project_revision_id
        changed = client.get(base + "/changes/" + change["id"], headers=HEADERS).json()
        assert changed["status"] == "accepted"
        assert changed["accepted_revision"] == task.project_revision_id
        assert changed["accepted_revision"] == app.projects.project(project.id).latest_revision_id
        assert "double(9)" in (root / "main.py").read_text()
        assert "v*3" in (root / "calc.py").read_text()
        assert app.research(project.id).store.runs() == []


def test_queued_accept_rechecks_expected_revision(tmp_path, monkeypatch):
    root = tmp_path / "lab"; lab(root)
    with TestClient(create_research_app(tmp_path / "host", token=TOKEN)) as client:
        app, project, revision = prepared(client, root)
        base = PREFIX + "/" + project.id
        change = propose(client, project.id, revision.id, [
            {"path": "calc.py", "content": "def double(v):\n    return v*3\n"},
        ])
        jobs = app.workbench(project.id).jobs
        captured = {}

        def fake_submit(kind, function, *, plan_id=None, receipt=None):
            captured["function"] = function
            return TaskRecord(kind=kind, receipt=receipt or {})

        monkeypatch.setattr(jobs, "submit", fake_submit)
        queued = client.post(base + "/changes/" + change["id"] + "/accept", headers=HEADERS,
                             json={"expected_revision": revision.id})
        assert queued.status_code == 202, queued.text
        app.index(project.id)  # a newer revision lands before the job starts
        with pytest.raises(RuntimeError):
            captured["function"](None, threading.Event())
        assert "v*2" in (root / "calc.py").read_text()


def test_interrupted_accept_requires_explicit_recovery(tmp_path, monkeypatch):
    root = tmp_path / "lab"; lab(root)
    with TestClient(create_research_app(tmp_path / "host", token=TOKEN)) as client:
        app, project, revision = prepared(client, root)
        base = PREFIX + "/" + project.id
        change = propose(client, project.id, revision.id, [
            {"path": "calc.py", "content": "def double(v):\n    return v*3\n"},
            {"path": "main.py", "content": "from calc import double\nY=double(9)\n"},
        ])
        service = client.app.state.project_changes
        original = service._write_file
        state = {"count": 0}

        def crash(path, data):
            state["count"] += 1
            if state["count"] == 2:
                raise OSError("simulated apply interruption")
            return original(path, data)

        monkeypatch.setattr(service, "_write_file", crash)
        accepted = client.post(base + "/changes/" + change["id"] + "/accept", headers=HEADERS,
                               json={"expected_revision": revision.id})
        task = app.workbench(project.id).jobs.wait(accepted.json()["id"], 20)
        assert task.status == "failed"
        assert client.get(base + "/changes/" + change["id"], headers=HEADERS).json()["status"] == "recovery_required"
        state_page = client.get(base + "/changes/recovery", headers=HEADERS).json()
        assert state_page["required"] is True and state_page["change_id"] == change["id"]
        blocked = client.post(base + "/changes", headers=HEADERS, json={
            "base_revision": revision.id,
            "edits": [{"path": "calc.py", "content": "Z=1\n"}]})
        assert blocked.status_code == 409, blocked.text
        recovered = client.post(base + "/changes/recover", headers=HEADERS,
                                json={"expected_revision": revision.id})
        assert recovered.status_code == 200, recovered.text
        assert recovered.json()["status"] == "rejected"
        assert client.get(base + "/changes/recovery", headers=HEADERS).json()["required"] is False
        assert "v*2" in (root / "calc.py").read_text()
        assert "double(7)" in (root / "main.py").read_text()


def test_index_failure_after_apply_keeps_revision_unset(tmp_path, monkeypatch):
    root = tmp_path / "lab"; lab(root)
    with TestClient(create_research_app(tmp_path / "host", token=TOKEN)) as client:
        app, project, revision = prepared(client, root)
        base = PREFIX + "/" + project.id
        change = propose(client, project.id, revision.id, [
            {"path": "calc.py", "content": "def double(v):\n    return v*3\n"},
        ])

        def boom(project_id, *args, **kwargs):
            raise RuntimeError("index pipeline down")

        monkeypatch.setattr(app, "index", boom)
        task = accept(client, app, project.id, change["id"], revision.id)
        assert task.status == "failed"
        assert "accepted" in task.message.lower()
        changed = client.get(base + "/changes/" + change["id"], headers=HEADERS).json()
        assert changed["status"] == "accepted"
        assert changed["accepted_revision"] is None
        assert "v*3" in (root / "calc.py").read_text()
        assert app.projects.project(project.id).latest_revision_id == revision.id
        assert client.get(base + "/changes/recovery", headers=HEADERS).json()["required"] is False


def test_rollback_rejects_corrupted_backup_without_proposal(tmp_path):
    root = tmp_path / "lab"; lab(root)
    with TestClient(create_research_app(tmp_path / "host", token=TOKEN)) as client:
        app, project, revision = prepared(client, root)
        base = PREFIX + "/" + project.id
        change = propose(client, project.id, revision.id, [
            {"path": "calc.py", "content": "def double(v):\n    return v*3\n"},
        ])
        task = accept(client, app, project.id, change["id"], revision.id)
        assert task.status == "completed", task.message
        blob = root / ".cdaf/research/project-changes" / change["id"] / "blobs/0.original"
        blob.write_bytes(b"corrupted backup")
        conflict = client.post(base + "/changes/" + change["id"] + "/rollback", headers=HEADERS,
                               json={"expected_revision": task.project_revision_id})
        assert conflict.status_code == 409, conflict.text
        assert "original" in conflict.json()["detail"]
        assert [c["id"] for c in client.get(base + "/changes", headers=HEADERS).json()["items"]] == [change["id"]]


def test_rollback_after_user_edit_is_conflict(tmp_path):
    root = tmp_path / "lab"; lab(root)
    with TestClient(create_research_app(tmp_path / "host", token=TOKEN)) as client:
        app, project, revision = prepared(client, root)
        base = PREFIX + "/" + project.id
        change = propose(client, project.id, revision.id, [
            {"path": "calc.py", "content": "def double(v):\n    return v*3\n"},
        ])
        task = accept(client, app, project.id, change["id"], revision.id)
        assert task.status == "completed", task.message
        (root / "calc.py").write_text("USER=1\n")
        conflict = client.post(base + "/changes/" + change["id"] + "/rollback", headers=HEADERS,
                               json={"expected_revision": task.project_revision_id})
        assert conflict.status_code == 409, conflict.text
        assert (root / "calc.py").read_text() == "USER=1\n"


def test_accept_never_imports_or_runs_project_code(tmp_path):
    root = tmp_path / "lab"; lab(root)
    (root / "boom.py").write_text("raise RuntimeError('MUST NOT IMPORT')\n", encoding="utf-8")
    with TestClient(create_research_app(tmp_path / "host", token=TOKEN)) as client:
        app, project, revision = prepared(client, root)
        change = propose(client, project.id, revision.id, [
            {"path": "main.py", "content": "from calc import double\nY=double(11)\n"},
        ])
        task = accept(client, app, project.id, change["id"], revision.id)
        assert task.status == "completed", task.message
        assert "boom" not in sys.modules
        assert app.research(project.id).store.runs() == []
