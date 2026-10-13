from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from contract_driven_ai_flow.api import create_app
from contract_driven_ai_flow.examples import create_example, definition, module, bind, object_schema
from contract_driven_ai_flow.export import export_data, render_export, visual_receipt
from contract_driven_ai_flow.models import CapturePolicy, ProbeSpec, ProjectSpec
from contract_driven_ai_flow.runtime import Runner
from contract_driven_ai_flow.storage import Store, atomic_write


@pytest.mark.parametrize("name", ["data-pipeline", "business-flow", "nested-composite"])
def test_real_examples_success_and_quality_failure(tmp_path, name):
    root = create_example(tmp_path / name, name)
    _, _, success, failure = definition(name)
    good = Runner(root).run(success)
    if good["status"] != "completed":
        print(json.dumps(Store(root).events(good["id"]), indent=2))
    assert (good["status"], good["quality"]) == ("completed", "passed"), Store(root).events(good["id"])
    bad = Runner(root).run(failure)
    assert (bad["status"], bad["quality"]) == ("completed", "failed"), Store(root).events(bad["id"])
    events = Store(root).events(bad["id"])
    assert any(e["kind"] == "probe.result" and e["data"]["status"] == "fail" for e in events)
    assert all(e["revision"] == bad["revision"] for e in events)
    if name == "business-flow":
        assert any(e["kind"] == "module.skipped" and e["module"] == "fulfill" for e in events)
        assert any(e["kind"] == "module.completed" and e["module"] == "decline" for e in events)
        assert any(e["kind"] == "probe.result" and e["data"]["kind"] == "branch_observer" for e in events)


@pytest.mark.parametrize("boundary,port,value", [("input", "value", -1), ("output", "result", -2)])
def test_composite_joint_contracts_are_runtime_boundaries(tmp_path, boundary, port, value):
    root = create_example(tmp_path / "nested", "nested-composite")
    store = Store(root)
    project = store.load()
    composite = next(m for m in project.modules if m.id == "pipeline")
    getattr(composite.contract, boundary)["not"] = {"properties": {port: {"const": value}}, "required": [port]}
    store.save(project, store.load().revision)
    result = Runner(root).run({"value": -1})
    assert result["status"] == "failed"
    events = store.events(result["id"])
    assert any(e["module"] == "pipeline" and e["kind"] == "contract.checked" and e["data"]["boundary"] == boundary and e["data"]["status"] == "fail" for e in events)
    assert not any(e["kind"] == "module.started" and e["module"] == "display" for e in events)


def test_composite_public_output_supports_readonly_probe(tmp_path):
    root = create_example(tmp_path / "composite-probe", "nested-composite")
    store = Store(root)
    project = store.load()
    project.probes.append(ProbeSpec(id="public_quality", module="pipeline", expression="$output.result < 100"))
    store.save(project, store.load().revision)
    run = Runner(root).run({"value": 80})
    assert (run["status"], run["quality"]) == ("completed", "failed")
    assert any(e["kind"] == "probe.result" and e["module"] == "pipeline" and e["data"]["probe"] == "public_quality" for e in store.events(run["id"]))


def test_business_loopback_fixture_does_not_depend_on_reverse_dns(monkeypatch):
    import socket

    _, source, _, _ = definition("business-flow")
    namespace = {}
    exec(source, namespace)

    def unavailable_reverse_dns(host):
        raise AssertionError("The loopback fixture must not perform a reverse DNS lookup")

    monkeypatch.setattr(socket, "getfqdn", unavailable_reverse_dns)
    assert namespace["inventory"](3) == {"available": True}
    assert namespace["inventory"](0) == {"available": False}


def single(tmp_path, source, *, output=None, timeout=3, retries=0, probes=None):
    root = tmp_path / "case"
    root.mkdir()
    spec = ProjectSpec(modules=[module("f", {}, output or {}, timeout_seconds=timeout, retries=retries, idempotent=bool(retries))], probes=probes or [])
    Store(root).save(spec, None)
    atomic_write(root / "src/steps.py", source)
    return root


@pytest.mark.parametrize("source,state,error", [("raise RuntimeError('import failed')\ndef f():\n    return 1\n", "failed", "RuntimeError"), ("def f():\n    import os\n    os._exit(3)\n", "failed", "WorkerExit"), ("def f():\n    import time\n    time.sleep(10)\n", "failed", "Timeout"), ("def f():\n    return object()\n", "failed", "TypeError")])
def test_import_crash_timeout_unsupported_have_final_evidence(tmp_path, source, state, error):
    # Only the sleeping case tests a short deadline. Other cases need enough
    # time for a cold spawned interpreter to report their actual failure.
    root = single(tmp_path, source, timeout=3 if error == "Timeout" else 10)
    result = Runner(root).run({})
    assert result["status"] == state
    events = Store(root).events(result["id"])
    assert events[-1]["kind"] == "run.finished"
    assert any(e["data"].get("error", {}).get("type") == error for e in events)


def test_async_scalar_null_and_retries(tmp_path):
    root = single(tmp_path, "async def f():\n    import asyncio\n    await asyncio.sleep(0)\n    return None\n", output={"anyOf": [{"type": "integer"}, {"type": "null"}]})
    assert Runner(root).run({})["status"] == "completed"
    project = Store(root).load()
    project.modules[0].idempotent = True
    project.modules[0].retries = 1
    Store(root).save(project, Store(root).load().revision)
    atomic_write(root / "src/steps.py", "def f():\n    raise RuntimeError('private error')\n")
    run = Runner(root).run({})
    events = Store(root).events(run["id"])
    assert [e["attempt"] for e in events if e["kind"] == "module.started"] == [1, 2]
    assert "private error" not in json.dumps(events)


def test_existing_positional_only_entry_runs_from_named_ports(tmp_path):
    root = tmp_path / "positional"
    root.mkdir()
    project = ProjectSpec(modules=[module("f", {"value": {"type": "integer"}}, {"type": "integer"})],
                          bindings=[bind("f", "value", literal=3)])
    Store(root).save(project, None)
    atomic_write(root / "src/steps.py", "def f(value, /, factor=2):\n    return value * factor\n")
    runner = Runner(root)
    result = runner.run({})
    assert result["status"] == "completed"
    assert runner.outputs["f"] == 6


def test_nested_mutation_cannot_modify_upstream(tmp_path):
    root = tmp_path / "isolated"
    root.mkdir()
    schema = object_schema({"items": {"type": "array", "items": {"type": "integer"}}})
    project = ProjectSpec(modules=[module("produce", {}, schema), module("mutate", {"payload": schema}, schema)], bindings=[bind("mutate", "payload", "produce")])
    Store(root).save(project, None)
    atomic_write(root / "src/steps.py", "def produce():\n    return {'items': [1]}\n\ndef mutate(payload):\n    payload['items'].append(2)\n    return payload\n")
    runner = Runner(root)
    assert runner.run({})["status"] == "completed"
    assert runner.outputs["produce"] == {"items": [1]}
    assert runner.outputs["mutate"] == {"items": [1, 2]}


def wait_for(store, run_id, predicate, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate(store.events(run_id)):
            return
        time.sleep(.05)
    raise AssertionError("Timed out waiting for a recorded boundary")


def test_cancel_stops_active_worker(tmp_path):
    root = single(tmp_path, "def f():\n    import time\n    time.sleep(20)\n", timeout=30)
    store, runner = Store(root), Runner(root)
    result = []
    thread = threading.Thread(target=lambda: result.append(runner.run({}, run_id="cancel-test")))
    thread.start()
    wait_for(store, "cancel-test", lambda ev: any(e["kind"] == "module.started" for e in ev))
    store.control("cancel-test", "cancel")
    thread.join(8)
    assert not thread.is_alive()
    assert result[0]["status"] == "cancelled"


def test_gating_probe_error_pauses_until_reviewed_resume(tmp_path):
    probe = ProbeSpec(id="gate", module="f", expression="-$output.value > 0", policy="block")
    root = single(tmp_path, "def f():\n    return {'value':'invalid-type'}\n", output={"type": "object"}, probes=[probe])
    store, runner = Store(root), Runner(root)
    result = []
    thread = threading.Thread(target=lambda: result.append(runner.run({}, run_id="pause-test")))
    thread.start()
    wait_for(store, "pause-test", lambda ev: any(e["kind"] == "control.paused" for e in ev))
    assert store.run("pause-test")["status"] == "paused"
    store.control("pause-test", "resume")
    thread.join(8)
    assert not thread.is_alive()
    assert result[0]["quality"] == "degraded"


def test_sensitive_samples_absent_from_db_exports_and_context(tmp_path):
    root = single(tmp_path, "def f():\n    return {'password':'very-private-123','email':'private@example.com','count':1}\n", output={"type": "object"})
    store = Store(root)
    project = store.load()
    project.capture.level = "full"
    store.save(project, store.load().revision)
    run = Runner(root).run({})
    serialized = json.dumps(store.events(run["id"]))
    for format in ("html", "svg", "mermaid", "json"):
        value, _ = render_export(root, format, run["id"])
        serialized += value
    assert "very-private-123" not in serialized
    assert "private@example.com" not in serialized
    for path in (root / ".cdaf").glob("*.sqlite3*"):
        assert b"very-private-123" not in path.read_bytes()


def test_api_session_origin_revision_and_parity(tmp_path):
    root = create_example(tmp_path / "api")
    with TestClient(create_app(root, token="test-session")) as client:
        assert client.get("/api/v1/project").status_code == 401
        client.headers["Authorization"] = "Bearer test-session"
        assert client.get("/api/v1/project", headers={"Origin": "https://attacker.example"}).status_code == 403
        doc = client.get("/api/v1/project").json()
        check = client.post("/api/v1/check", json=doc["project"]).json()
        assert check["valid"]
        assert check["revision"] == doc["revision"]
        assert client.post("/api/v1/changes/architecture", json={"project": doc["project"], "base_revision": "old"}).status_code == 409
        doc["project"]["name"] = "Edited on canvas"
        change = client.post("/api/v1/changes/architecture", json={"project": doc["project"], "base_revision": doc["revision"]}).json()
        assert client.get("/api/v1/project").json()["project"]["name"] != "Edited on canvas"
        assert client.post(f'/api/v1/changes/{change["id"]}/accept', json={"base_revision": doc["revision"]}).status_code == 200
        assert Store(root).load().name == "Edited on canvas"


def test_export_offline_escaping_and_receipt(tmp_path):
    root = create_example(tmp_path / "export")
    store = Store(root)
    project = store.load()
    project.name = '</script><script>alert("x")</script>'
    store.save(project, store.load().revision)
    text, _ = render_export(root, "html")
    assert '</script><script>alert("x")</script>' not in text
    assert "https://" not in text and "fetch(" not in text
    assert visual_receipt(export_data(root))["node_overlaps"] == []
    image, media = render_export(root, "png")
    assert image.startswith(b"\x89PNG") and media == "image/png"
