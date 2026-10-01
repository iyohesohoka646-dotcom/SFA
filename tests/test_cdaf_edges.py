from pathlib import Path
import json

from contract_driven_ai_flow.changes import propose_architecture
from contract_driven_ai_flow.examples import create_example
from contract_driven_ai_flow.privacy import sanitize
from contract_driven_ai_flow.storage import Store
from contract_driven_ai_flow.api import create_app
from contract_driven_ai_flow.models import Source, PortBinding
from fastapi.testclient import TestClient
import yaml
from contract_driven_ai_flow.migration import migrate
from contract_driven_ai_flow.compiler import compile_project
import sqlite3
import pytest
from contract_driven_ai_flow.context import build_context
from contract_driven_ai_flow.examples import definition


def test_sensitive_json_diff_is_redacted():
    value = '+    "password": "very-private-password",\n+    "custom_secret": "very-private-custom"\n'
    result = sanitize(value, ["password", "custom_secret"])
    assert "very-private-password" not in result
    assert "very-private-custom" not in result


def test_store_connections_are_closed_after_their_transaction(tmp_path):
    store = Store(tmp_path)
    with store.connect() as db:
        db.execute("SELECT 1")
    with pytest.raises(sqlite3.ProgrammingError):
        db.execute("SELECT 1")


def test_context_request_cannot_override_edge_visibility(tmp_path):
    root = create_example(tmp_path / "context")
    store = Store(root)
    project = store.load()
    edge = next(b for b in project.bindings if b.target == "normalize" and b.source.kind == "module")
    edge.visibility = "L1"
    store.save(project, store.load().revision)
    entry = next(e for e in build_context(root, "normalize", "L4")["entries"] if e["role"] == "upstream")
    assert "source" not in entry and "examples" not in entry and "symbol" not in entry
    assert entry["visibility"] == "L1"


def test_public_composite_contract_cannot_be_bypassed_by_flattening():
    project = definition("nested-composite")[0]
    outer = next(m for m in project.modules if m.id == "pipeline")
    outer.contract.output["properties"]["result"] = {}
    plan = compile_project(project)
    assert not plan.valid
    assert any(d.code == "contract_unknown" and d.module == "display" for d in plan.diagnostics)


def test_architecture_diff_uses_sanitized_fixtures(tmp_path):
    root = create_example(tmp_path / "demo")
    store = Store(root)
    project = store.load()
    project.modules[0].contract.examples.append({"input": {"password": "very-private-fixture"}, "output": []})
    change = propose_architecture(root, project, store.load().revision)
    assert "very-private-fixture" not in change.diff


def test_redacted_editor_roundtrip_preserves_authored_literals(tmp_path):
    root = create_example(tmp_path / "api")
    store = Store(root)
    spec = store.load()
    spec.modules[0].contract.input["properties"]["password"] = {"type": "string"}
    spec.bindings.append(PortBinding(id="credential", target="ingest", port="password", source=Source(kind="literal", value="authored-sensitive-value")))
    store.save(spec, store.load().revision)
    with TestClient(create_app(root, token="session")) as client:
        client.headers["Authorization"] = "Bearer session"
        current = client.get("/api/v1/project").json()
        assert current["project"]["bindings"][-1]["source"]["value"] == "[REDACTED]"
        current["project"]["name"] = "Edited title"
        result = client.post("/api/v1/changes/architecture", json={"project": current["project"], "base_revision": current["revision"]})
        change = result.json()
        assert result.status_code == 200
        assert client.post(f'/api/v1/changes/{change["id"]}/accept', json={"base_revision": current["revision"]}).status_code == 200
    assert store.load().bindings[-1].source.value == "authored-sensitive-value"


def test_migration_requires_fanin_resolution_and_keeps_original(tmp_path):
    root = tmp_path / "old"
    (root / ".sfa").mkdir(parents=True)
    (root / "src").mkdir()
    (root / "src/steps.py").write_text("def a():\n    return {'value':1}\n\ndef b():\n    return {'value':2}\n\ndef c(value):\n    return value\n", encoding="utf-8")
    output = {"type": "object", "properties": {"value": {"type": "integer"}}, "required": ["value"], "additionalProperties": False}
    topology = {"modules": [], "pipes": []}
    for name in ("a", "b", "c"):
        directory = root / ".sfa/modules" / name
        directory.mkdir(parents=True)
        contract = {"input_schema": {"type": "object", "properties": {"value": {"type": "integer"}} if name == "c" else {}, "required": ["value"] if name == "c" else [], "additionalProperties": False}, "output_schema": {"type": "integer"} if name == "c" else output}
        (directory / "contract.json").write_text(json.dumps(contract), encoding="utf-8")
        topology["modules"].append({"id": name, "type": "atomic", "path": "src/steps.py", "entry": name})
    topology["pipes"] = [{"id": "a_c", "source": "a", "target": "c"}, {"id": "b_c", "source": "b", "target": "c"}]
    before = yaml.safe_dump(topology)
    (root / ".sfa/pipeline.yml").write_text(before, encoding="utf-8")
    preview = migrate(root)
    assert any(i["code"] == "ambiguous_binding" for i in preview["issues"])
    assert not (tmp_path / "old-cdaf").exists()
    applied = migrate(root, resolutions={"c.value": {"kind": "module", "module": "a", "pointer": "/value"}}, apply=True)
    assert applied["applied"], applied["issues"]
    assert (root / ".sfa/pipeline.yml").read_text(encoding="utf-8") == before
    destination = Path(applied["destination"])
    assert (destination / "legacy/.sfa/pipeline.yml").exists()
    assert compile_project(Store(destination).load()).valid
