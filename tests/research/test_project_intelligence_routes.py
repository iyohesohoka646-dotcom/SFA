"""Own tests for the P4 project-intelligence HTTP gateway.

These tests drive a deterministic FAKE model adapter. They never contact a
network, provider, credential store or real model, and they are NOT a test of
any actual external inference behaviour.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from contract_driven_ai_flow.research.projects.ai_models import ProjectAIRequest
from contract_driven_ai_flow.research.projects.changes import ProjectChangeService
from contract_driven_ai_flow.research.projects.intelligence import ProjectIntelligenceService
from contract_driven_ai_flow.research.routes import create_research_app

PREFIX = "/api/v1/research/projects/"
TOKEN = "ai-test"
HEADERS = {"Authorization": "Bearer " + TOKEN}


class FakeModels:
    """FAKE structured-tool-loop adapter: no network, no vendor, no secret."""

    def __init__(self, actions=None):
        self.actions = list(actions or [])
        self.calls = []

    def profile(self, key):
        return SimpleNamespace(protocol="openai-compatible")

    def secret(self, profile):
        return None

    def cancel(self, key):
        pass

    async def complete(self, key, messages, **kwargs):
        self.calls.append(messages)
        if self.actions:
            action = self.actions.pop(0)
        else:
            receipt = json.loads(messages[-1]["content"].split("\n", 1)[1])
            action = {"answer": "ok", "citations": [receipt["reference"]]}
        return SimpleNamespace(
            status="connected",
            text=json.dumps(action),
            requests=1,
            usage={},
            duration_ms=1,
            message="",
        )


class GatedModels(FakeModels):
    """FAKE adapter that holds the job at profile() until released."""

    def __init__(self):
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()

    def profile(self, key):
        self.entered.set()
        self.release.wait(15)
        return SimpleNamespace(protocol="openai-compatible")


def lab(root: Path, extra=None):
    root.mkdir(parents=True, exist_ok=True)
    (root / "calc.py").write_text("def double(v):\n    return v*2\n", encoding="utf-8")
    (root / "main.py").write_text("from calc import double\nY=double(7)\n", encoding="utf-8")
    for name, text in (extra or {}).items():
        (root / name).write_text(text, encoding="utf-8")


def prepared(client, root, models):
    if not root.exists():
        lab(root)
    app = client.app.state.projects
    app.models = models
    project = app.open(root)
    revision = app.index(project.id)
    body = {
        "project_id": project.id,
        "project_revision_id": revision.id,
        "question": "Explain the calculation",
        "policy": {"provider_id": "test", "input_tokens": 16000, "max_steps": 4, "max_calls": 4},
    }
    return app, project, revision, body


def interrupted_accept(app, project, revision):
    """Create a live recovery journal by interrupting a reviewed accept."""
    changes = ProjectChangeService(app.projects)
    change = changes.propose(
        project.id,
        revision.id,
        [{"path": "calc.py", "content": "X=3\n"}, {"path": "main.py", "content": "Y=4\n"}],
    )

    original = changes._write_file
    count = {"n": 0}

    def interrupt(path, data):
        count["n"] += 1
        if count["n"] == 2:
            raise OSError("interrupted")
        return original(path, data)

    changes._write_file = interrupt
    with pytest.raises(OSError):
        changes.accept(project.id, change.id)


# -- auth and identity -------------------------------------------------------

def test_routes_require_the_local_session_token(tmp_path):
    with TestClient(create_research_app(tmp_path / "host", token=TOKEN)) as client:
        app, project, revision, body = prepared(client, tmp_path / "lab", FakeModels())
        assert client.post(PREFIX + project.id + "/intelligence/context", json=body).status_code == 401
        assert client.post(PREFIX + project.id + "/intelligence", json=body).status_code == 401
        assert client.get(PREFIX + project.id + "/intelligence/contexts/x").status_code == 401
        assert not app.research(project.id).store.runs()


def test_unknown_project_is_404_and_mismatched_body_pid_is_rejected(tmp_path):
    with TestClient(create_research_app(tmp_path / "host", token=TOKEN)) as client:
        models = FakeModels()
        app, project, revision, body = prepared(client, tmp_path / "lab", models)
        assert client.post(PREFIX + "missing/intelligence/context", headers=HEADERS, json=body).status_code == 404
        assert client.post(PREFIX + "missing/intelligence", headers=HEADERS, json=body).status_code == 404
        wrong = dict(body, project_id="foreign")
        assert client.post(PREFIX + project.id + "/intelligence/context", headers=HEADERS, json=wrong).status_code in (409, 422)
        assert client.post(PREFIX + project.id + "/intelligence", headers=HEADERS, json=wrong).status_code in (409, 422)
        assert not models.calls


# -- inert, bounded preview --------------------------------------------------

def test_preview_is_bounded_inert_and_persists_no_task(tmp_path):
    with TestClient(create_research_app(tmp_path / "host", token=TOKEN)) as client:
        models = FakeModels()
        app, project, revision, body = prepared(client, tmp_path / "lab", models)
        response = client.post(PREFIX + project.id + "/intelligence/context", headers=HEADERS, json=body)
        assert response.status_code == 200, response.text
        preview = response.json()
        assert preview["project_id"] == project.id
        assert preview["project_revision_id"] == revision.id
        assert preview["messages"] and 0 <= preview["token_bound"] <= body["policy"]["input_tokens"]
        assert preview["tools"]
        assert not models.calls
        assert app.workbench(project.id).jobs.list() == []
        assert "double(7)" not in json.dumps(preview)
        assert not app.research(project.id).store.runs()


# -- owned task, mock tool loop, honest provider failure ---------------------

def test_ask_runs_mock_tool_loop_and_get_reads_owned_context(tmp_path):
    with TestClient(create_research_app(tmp_path / "host", token=TOKEN)) as client:
        models = FakeModels(actions=[{"tool": "project.describe", "arguments": {}}])
        app, project, revision, body = prepared(client, tmp_path / "lab", models)
        base = PREFIX + project.id + "/intelligence"
        queued = client.post(base, headers=HEADERS, json=body)
        assert queued.status_code == 202, queued.text
        task = app.workbench(project.id).jobs.wait(queued.json()["id"], 20)
        assert task.status == "completed", task.message
        assert len(models.calls) == 2
        context_id = task.receipt["context_id"]
        context = client.get(base + "/contexts/" + context_id, headers=HEADERS)
        assert context.status_code == 200, context.text
        assert context.json()["project_id"] == project.id
        assert context.json()["citations"]
        assert not app.research(project.id).store.runs()


def test_unconfigured_provider_fails_honestly_without_fake_success(tmp_path):
    with TestClient(create_research_app(tmp_path / "host", token=TOKEN)) as client:
        app, project, revision, body = prepared(client, tmp_path / "lab", FakeModels())
        # Leave the real (empty) shared model settings in place: the profile
        # named by the request is not configured, so the owned task must fail.
        app.models = client.app.state.models
        base = PREFIX + project.id + "/intelligence"
        queued = client.post(base, headers=HEADERS, json=body)
        assert queued.status_code == 202, queued.text
        task = app.workbench(project.id).jobs.wait(queued.json()["id"], 20)
        assert task.status == "failed"
        assert not task.receipt.get("answer")
        contexts = app.workbench(project.id).store.list("contexts")
        assert all(record.get("status") != "completed" for record in contexts)


def test_stale_queued_request_is_rechecked_before_inference(tmp_path):
    with TestClient(create_research_app(tmp_path / "host", token=TOKEN)) as client:
        models = GatedModels()
        app, project, revision, body = prepared(client, tmp_path / "lab", models)
        base = PREFIX + project.id + "/intelligence"
        queued = client.post(base, headers=HEADERS, json=body)
        assert queued.status_code == 202, queued.text
        assert models.entered.wait(15)
        # Publish a new revision while the owned job is still queued/running.
        app.index(project.id)
        models.release.set()
        task = app.workbench(project.id).jobs.wait(queued.json()["id"], 20)
        assert task.status == "failed"
        assert not task.receipt.get("answer")
        assert not models.calls


# -- partial transaction recovery --------------------------------------------

def test_partial_journal_before_request_blocks_preview_and_ask(tmp_path):
    with TestClient(create_research_app(tmp_path / "host", token=TOKEN)) as client:
        models = FakeModels()
        app, project, revision, body = prepared(client, tmp_path / "lab", models)
        interrupted_accept(app, project, revision)
        base = PREFIX + project.id + "/intelligence"
        assert client.post(base + "/context", headers=HEADERS, json=body).status_code == 409
        assert client.post(base, headers=HEADERS, json=body).status_code == 409
        service = ProjectIntelligenceService(app, project.id)
        with pytest.raises((RuntimeError, ValueError), match="[Rr]ecover"):
            service.context(ProjectAIRequest(**body))
        assert not models.calls


def test_journal_created_during_response_is_not_accepted(tmp_path, monkeypatch):
    with TestClient(create_research_app(tmp_path / "host", token=TOKEN)) as client:
        models = FakeModels()
        app, project, revision, body = prepared(client, tmp_path / "lab", models)
        changes = ProjectChangeService(app.projects)
        triggered = {"done": False}

        async def complete(key, messages, **kwargs):
            models.calls.append(messages)
            if not triggered["done"]:
                triggered["done"] = True
                change = changes.propose(
                    project.id,
                    revision.id,
                    [{"path": "calc.py", "content": "X=9\n"}, {"path": "main.py", "content": "Y=9\n"}],
                )
                original = changes._write_file
                count = {"n": 0}

                def interrupt(path, data):
                    count["n"] += 1
                    if count["n"] == 2:
                        raise OSError("interrupted")
                    return original(path, data)

                monkeypatch.setattr(changes, "_write_file", interrupt)
                with pytest.raises(OSError):
                    changes.accept(project.id, change.id)
            return SimpleNamespace(
                status="connected",
                text=json.dumps({"answer": "must not be accepted", "citations": []}),
                requests=1,
                usage={},
                duration_ms=1,
                message="",
            )

        models.complete = complete
        base = PREFIX + project.id + "/intelligence"
        queued = client.post(base, headers=HEADERS, json=body)
        assert queued.status_code == 202, queued.text
        task = app.workbench(project.id).jobs.wait(queued.json()["id"], 20)
        assert task.status == "failed"
        assert not task.receipt.get("answer")


# -- user code is never executed --------------------------------------------

def test_intelligence_never_runs_user_code(tmp_path):
    sentinel = tmp_path / "ran.txt"
    with TestClient(create_research_app(tmp_path / "host", token=TOKEN)) as client:
        models = FakeModels(actions=[{"tool": "project.describe", "arguments": {}}])
        payload = "import pathlib\npathlib.Path(r'" + str(sentinel) + "').write_text('ran')\n"
        lab(tmp_path / "lab", extra={"runs_on_import.py": payload})
        app, project, revision, body = prepared(client, tmp_path / "lab", models)
        base = PREFIX + project.id + "/intelligence"
        assert client.post(base + "/context", headers=HEADERS, json=body).status_code == 200
        queued = client.post(base, headers=HEADERS, json=body)
        assert queued.status_code == 202
        app.workbench(project.id).jobs.wait(queued.json()["id"], 20)
        assert not sentinel.exists()
        assert not app.research(project.id).store.runs()


def test_queue_admission_failure_is_an_explicit_http_error(tmp_path, monkeypatch):
    headers = {'Authorization': 'Bearer ai-token'}
    with TestClient(create_research_app(tmp_path/'host', token='ai-token'), raise_server_exceptions=False) as client:
        root=tmp_path/'lab'; root.mkdir(); (root/'main.py').write_text('X=1\n')
        app=client.app.state.projects; p=app.open(root); r=app.index(p.id)
        def full(*args, **kwargs):
            raise ValueError('Task queue is full or closed')
        monkeypatch.setattr(app.workbench(p.id).jobs, 'submit', full)
        response=client.post('/api/v1/research/projects/'+p.id+'/intelligence',headers=headers,json={'project_id':p.id,'project_revision_id':r.id,'question':'Explain'})
        assert response.status_code in (409,429), response.text
        assert 'queue' in response.json()['detail'].lower()
