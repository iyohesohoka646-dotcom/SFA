"""Real regressions found during the complete branch and installed-package reviews."""
import json
import threading
import time

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from contract_driven_ai_flow.api import create_app
from contract_driven_ai_flow.cli import app
from contract_driven_ai_flow.compiler import compile_project
from contract_driven_ai_flow.context import build_context
from contract_driven_ai_flow.examples import bind, create_example, module, object_schema
from contract_driven_ai_flow.export import export_data
from contract_driven_ai_flow.models import ModuleSpec, ProbeSpec, ProjectSpec, RouteGuard, RunEvent
from contract_driven_ai_flow.privacy import sanitize, sanitize_plan
from contract_driven_ai_flow.runtime import Runner
from contract_driven_ai_flow.storage import Store, atomic_write, file_digest, now


def secret_project(tmp_path):
    project = ProjectSpec(modules=[module("f", {"secret": {"type": "integer"}}, {"type": "integer"})],
                          bindings=[bind("f", "secret", literal=7382941)])
    Store(tmp_path).save(project, None)
    atomic_write(tmp_path / "src/steps.py", "PASSWORD = 'unrelated-sensitive-source'\n\ndef f(secret):\n    return secret\n")
    return project


def test_check_and_plan_compile_original_but_return_safe_values(tmp_path):
    project = secret_project(tmp_path)
    with TestClient(create_app(tmp_path, token="session")) as client:
        client.headers["Authorization"] = "Bearer session"
        displayed = client.get("/api/v1/project").json()
        for response in (client.post("/api/v1/check", json=displayed["project"]), client.get("/api/v1/plan")):
            value = response.json()
            assert value["valid"] and value["revision"] == project.revision
            assert "7382941" not in json.dumps(value)


def test_cli_plan_and_changes_do_not_dump_literal_or_unrelated_source(tmp_path):
    secret_project(tmp_path)
    candidate = tmp_path / "candidate.py"
    candidate.write_text("def f(secret):\n    return secret + 1\n", encoding="utf-8")
    cli = CliRunner()
    for args in (["plan"], ["generate", "f", "--candidate", str(candidate)], ["review"]):
        result = cli.invoke(app, [*args, "--project", str(tmp_path)])
        assert result.exit_code == 0, result.output
        assert "7382941" not in result.output and "unrelated-sensitive-source" not in result.output
        assert '"before"' not in result.output and '"after"' not in result.output


def test_version_works_without_a_subcommand():
    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0 and result.output.strip() == "0.2.0"


def test_context_redacts_description_at_the_lowest_visibility(tmp_path):
    root = create_example(tmp_path / "context")
    store = Store(root)
    project = store.load()
    project.modules[0].description = "Contact private@example.com; token=very-private-token"
    store.save(project, store.load().revision)
    value = json.dumps(build_context(root, "normalize", "L1"))
    assert "private@example.com" not in value and "very-private-token" not in value


def test_quoted_source_secret_is_fully_redacted_with_spaces():
    source = "def f(password='private words with spaces'):\n    return password\n"
    displayed = sanitize(source, ["password"])
    assert "private" not in displayed and "words" not in displayed and "spaces" not in displayed


def test_capture_pointer_is_redacted_before_selection_in_runtime_and_preview(tmp_path):
    probe = ProbeSpec(id="secret_capture", module="f", kind="capture", pointer="/password")
    project = ProjectSpec(modules=[module("f", {}, object_schema({"password": {"type": "integer"}}))], probes=[probe])
    Store(tmp_path).save(project, None)
    atomic_write(tmp_path / "src/steps.py", "def f():\n    return {'password': 7382941}\n")
    run = Runner(tmp_path).run({})
    assert run["status"] == "completed"
    assert "7382941" not in json.dumps(export_data(tmp_path, run["id"]))
    with TestClient(create_app(tmp_path, token="session")) as client:
        response = client.post("/api/v1/probes/preview", headers={"Authorization": "Bearer session"},
                               json={"probe": probe.model_dump(), "output": {"password": 7382941}})
        assert response.status_code == 200 and "7382941" not in response.text


def test_schema_authored_sensitive_data_stays_out_of_evidence(tmp_path):
    project = ProjectSpec(modules=[module("f", {}, object_schema({"password": {"type": "integer", "const": 7382941}}))])
    Store(tmp_path).save(project, None)
    atomic_write(tmp_path / "src/steps.py", "def f():\n    return {'password': 1}\n")
    run = Runner(tmp_path).run({})
    assert run["status"] == "failed" and run["quality"] == "failed"
    assert "7382941" not in json.dumps(export_data(tmp_path, run["id"]))


def test_flattened_literal_keeps_sensitive_public_port_provenance(tmp_path):
    project = ProjectSpec(modules=[
        ModuleSpec(id="group", kind="composite", contract={"input": object_schema({"secret": {"type": "integer"}}), "output": object_schema({})}),
        module("f", {"value": {"type": "integer"}}, {"type": "integer"}, parent="group"),
        module("other", {"value": {"type": "integer"}}, {"type": "integer"}),
    ], bindings=[bind("group", "secret", literal=7382941), bind("f", "value", "group", "/secret"), bind("other", "value", literal=7382941)])
    plan = compile_project(project)
    assert plan.valid
    value = sanitize_plan(plan, project)
    private = next(b for b in value["bindings"] if b["target"] == "f")
    assert private["source"]["value"] == "[REDACTED]"


def test_run_admission_reserves_initializing_runs_and_queued_cancel(tmp_path, monkeypatch):
    project = ProjectSpec(modules=[ModuleSpec(id="decision", kind="decision", condition="True",
                          contract={"input": object_schema({}), "output": {"type": "boolean"}})])
    Store(tmp_path).save(project, None)
    release = threading.Event()
    original = Runner.run

    def initializing(self, *args, **kwargs):
        release.wait(5)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Runner, "run", initializing)
    try:
        with TestClient(create_app(tmp_path, token="session")) as client:
            client.headers["Authorization"] = "Bearer session"
            replies = [client.post("/api/v1/runs", json={"input": {}, "base_revision": project.revision}) for _ in range(5)]
            try:
                assert [r.status_code for r in replies] == [202, 202, 202, 202, 429]
                run_id = replies[0].json()["id"]
                assert client.get(f"/api/v1/runs/{run_id}").json()["status"] == "queued"
                assert client.post(f"/api/v1/runs/{run_id}/cancel").status_code == 200
            finally:
                release.set()
    finally:
        release.set()


def test_composite_guard_controls_every_descendant(tmp_path):
    empty = {"input": object_schema({}), "output": object_schema({})}
    project = ProjectSpec(modules=[
        ModuleSpec(id="route", kind="decision", condition="False", contract={"input": object_schema({}), "output": {"type": "boolean"}}),
        ModuleSpec(id="group", kind="composite", contract=empty, guard=RouteGuard(decision="route", when=True)),
        module("f", {}, object_schema({}), parent="group"),
    ])
    Store(tmp_path).save(project, None)
    atomic_write(tmp_path / "src/steps.py", "def f():\n    raise RuntimeError('unselected branch ran')\n")
    plan = compile_project(project)
    assert plan.valid and "route" in plan.dependencies["f"]
    runner = Runner(tmp_path)
    result = runner.run({})
    assert result["status"] == "completed" and "f" not in runner.outputs
    assert any(e["kind"] == "module.skipped" and e["module"] == "f" for e in Store(tmp_path).events(result["id"]))


def test_pause_prevents_new_dispatch_until_resume(tmp_path, monkeypatch):
    project = ProjectSpec(concurrency=2, modules=[module(mid, {}, {"type": "integer"}) for mid in ("blocked", "quick", "later")],
                          probes=[ProbeSpec(id="break", module="blocked", boundary="input", expression="True", policy="breakpoint")])
    Store(tmp_path).save(project, None)
    atomic_write(tmp_path / "src/steps.py", "def blocked():\n    return 1\ndef quick():\n    return 1\ndef later():\n    return 1\n")
    store, runner, result = Store(tmp_path), Runner(tmp_path), []
    paused = threading.Event()
    real_pause = runner.pause

    def pause(reason):
        paused.set()
        return real_pause(reason)

    def work(current, kwargs):
        if current.id == "quick":
            assert paused.wait(3)
            time.sleep(.15)
        return {"status": "completed", "output": 1}

    monkeypatch.setattr(runner, "pause", pause)
    monkeypatch.setattr(runner, "work", work)
    thread = threading.Thread(target=lambda: result.append(runner.run({}, run_id="paused-run")))
    thread.start()
    try:
        assert paused.wait(3)
        time.sleep(.4)
        assert not any(e["kind"] == "module.started" and e["module"] == "later" for e in store.events("paused-run"))
        store.control("paused-run", "resume")
        thread.join(5)
        assert not thread.is_alive() and result[0]["status"] == "completed"
    finally:
        runner.cancelled.set()
        thread.join(5)


def test_declared_symbol_digest_blocks_unreviewed_code(tmp_path):
    original = "def f():\n    return 1\n"
    project = ProjectSpec(modules=[module("f", {}, {"type": "integer"})])
    project.modules[0].symbol.digest = file_digest(original)
    Store(tmp_path).save(project, None)
    atomic_write(tmp_path / "src/steps.py", "def f():\n    return 2\n")
    runner = Runner(tmp_path)
    result = runner.run({})
    assert result["status"] == "failed" and not runner.outputs
    assert any(e["data"].get("error", {}).get("type") == "SymbolVersion" for e in Store(tmp_path).events(result["id"]))


@pytest.mark.parametrize("filename", ["steps.py", "__init__.py"])
def test_existing_python_package_relative_imports_run_from_file_identity(tmp_path, filename):
    project = ProjectSpec(modules=[module("f", {"value": {"type": "integer"}}, {"type": "integer"})],
                          bindings=[bind("f", "value", literal=3)])
    project.modules[0].symbol.path = "src/package/" + filename
    Store(tmp_path).save(project, None)
    atomic_write(tmp_path / "src/package/__init__.py", "from .steps import f\n" if filename == "steps.py" else "")
    atomic_write(tmp_path / "src/package/helpers.py", "def double(value):\n    return value * 2\n")
    atomic_write(tmp_path / project.modules[0].symbol.path, "from .helpers import double\n\ndef f(value):\n    return double(value)\n")
    runner = Runner(tmp_path)
    result = runner.run({})
    assert result["status"] == "completed" and runner.outputs["f"] == 6


def test_current_architecture_export_does_not_choose_an_old_run(tmp_path):
    root = create_example(tmp_path / "export")
    runner = Runner(root)
    run = runner.run({"values": [1, 2], "scale": 1})
    store = Store(root)
    project = store.load()
    project.name = "Reviewed new architecture"
    store.save(project, store.load().revision)
    with TestClient(create_app(root, token="session")) as client:
        client.headers["Authorization"] = "Bearer session"
        current = client.get("/api/v1/export/json?current=true").json()
        historical = client.get(f'/api/v1/export/json?run_id={run["id"]}').json()
        assert current["revision"] == project.revision and current["run"] is None and current["events"] == []
        assert current["project"]["name"] == project.name
        assert historical["revision"] == run["revision"] and historical["project"]["name"] != project.name


def test_historical_export_reads_beyond_the_event_page_limit(tmp_path):
    project = ProjectSpec()
    store = Store(tmp_path)
    store.save(project, None)
    run_id = store.create_run(project, {})
    event = RunEvent(run_id=run_id, time=now(), kind="module.started", revision=project.revision).model_dump_json()
    with store.connect() as db:
        db.executemany("INSERT INTO events(run_id,body) VALUES (?,?)", [(run_id, event)] * 10005)
    store.finish(run_id, "completed", "passed")
    assert len(store.events(run_id)) == 10000
    assert len(export_data(tmp_path, run_id)["events"]) == 10005
