from __future__ import annotations

import json
from pathlib import Path

import pytest

from contract_driven_ai_flow.changes import accept, propose_architecture, propose_implementation, propose_rollback
from contract_driven_ai_flow.compiler import compatible, compile_project
from contract_driven_ai_flow.context import build_context
from contract_driven_ai_flow.examples import create_example, definition
from contract_driven_ai_flow.models import PortBinding, ProbeSpec, Source
from contract_driven_ai_flow.paths import Conflict, FlowError, inside
from contract_driven_ai_flow.privacy import capture, sanitize_project
from contract_driven_ai_flow.probes import compile_expression, evaluate_probe
from contract_driven_ai_flow.providers import generate
from contract_driven_ai_flow.source import read_symbol, replace_body, scan_candidates
from contract_driven_ai_flow.storage import Store, atomic_write, file_digest


@pytest.mark.parametrize("name", ["data-pipeline", "business-flow", "nested-composite"])
def test_reference_models_compile(name):
    result = compile_project(definition(name)[0])
    assert result.valid, result.diagnostics


def test_duplicate_writer_blocked():
    project = definition("data-pipeline")[0]
    project.bindings.append(PortBinding(id="collision", target="normalize", port="values", source=Source(kind="literal", value=[1])))
    assert "multiple_writers" in {d.code for d in compile_project(project).diagnostics}


def test_cycles_and_illegal_composite_boundaries():
    project = definition("nested-composite")[0]
    project.bindings[-1].source = Source(kind="module", module="double")
    assert "boundary" in {d.code for d in compile_project(project).diagnostics}
    project = definition("data-pipeline")[0]
    project.bindings[0].source = Source(kind="module", module="normalize")
    assert "cycle" in {d.code for d in compile_project(project).diagnostics}


def test_nested_composites_expand_to_real_boundary():
    plan = compile_project(definition("nested-composite")[0])
    assert plan.order == ["double", "display"]
    assert plan.bindings[0].source.kind == "project"
    assert plan.bindings[0].source.pointer == "/value"
    assert plan.bindings[1].source.module == "double"
    assert plan.bindings[1].source.pointer == ""


@pytest.mark.parametrize("a,b,result", [({"type":"integer"},{"type":"number"},"compatible"), ({"type":"number"},{"type":"integer"},"incompatible"), ({},{"type":"string"},"unknown"), ({"type":"number","minimum":0},{"type":"number"},"unknown"), ({"anyOf":[{"type":"integer"},{"type":"null"}]},{"type":["number","null"]},"compatible")])
def test_schema_proof(a,b,result):
    assert compatible(a,b) == result


@pytest.mark.parametrize("expression", ["2 ** 1000000", "'x' * 100000000", "__import__('os')", "$output.__class__", "[x for x in $output]", "open('file')"])
def test_expressions_cannot_expand_or_execute(expression):
    probe = ProbeSpec(id="p", module="m", expression=expression)
    assert evaluate_probe(probe, {}, {}).status == "error"


def test_strings_bool_missing_and_gas():
    assert compile_expression("'$output' == '$output'").evaluate({}, {}) is True
    assert evaluate_probe(ProbeSpec(id="p", module="m", expression="'truthy'"), {}, {}).status == "error"
    assert evaluate_probe(ProbeSpec(id="p", module="m", expression="-$output.value > 0"), {}, {"value": "bad"}).status == "error"
    assert evaluate_probe(ProbeSpec(id="p", module="m", expression="$output.missing > 0"), {}, {}).status == "error"
    with pytest.raises(ValueError, match="budget"):
        compile_expression("sum($output) > 0").evaluate({}, list(range(3000)), budget=100)


def test_nullable_path_and_schema_typo():
    schema = {"anyOf": [{"type": "object", "properties": {"value": {"type": "integer"}}, "additionalProperties": False}, {"type": "null"}]}
    assert compile_expression("$output is None or $output.value > 0", schema).evaluate({}, None)
    with pytest.raises(ValueError, match="Unknown contract path"):
        compile_expression("$output.typo > 0", schema)


@pytest.fixture
def demo(tmp_path):
    return create_example(tmp_path / "demo")


@pytest.mark.parametrize("candidate", ["def ingest(other):\n    return other\n", "def ingest(values):\n    import subprocess\n    return values\n", "def ingest(values):\n    return values\nTOP=True\n", "def ingest(:\n pass"])
def test_patch_rejects_signature_import_structure_syntax(demo, candidate):
    original = (demo / "src/steps.py").read_text(encoding="utf-8")
    change = propose_implementation(demo, "ingest", candidate)
    assert change.status == "invalid"
    with pytest.raises(Conflict):
        accept(demo, change.id, Store(demo).load().revision)
    assert (demo / "src/steps.py").read_text(encoding="utf-8") == original


def test_stale_patch_and_safe_inverse(demo):
    store = Store(demo)
    path = demo / "src/steps.py"
    change = propose_implementation(demo, "ingest", "def ingest(values):\n    return list(values)\n")
    accept(demo, change.id, store.load().revision)
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n# independently added\ndef unrelated():\n    return 7\n")
    inverse = propose_rollback(demo, change.id)
    accept(demo, inverse.id, store.load().revision)
    assert "independently added" in path.read_text(encoding="utf-8")
    stale = propose_implementation(demo, "ingest", "def ingest(values):\n    return values[:]\n")
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n# concurrent change\n")
    with pytest.raises(Conflict, match="Source changed"):
        accept(demo, stale.id, store.load().revision)


def test_libcst_preserves_decorators_indentation_and_other_symbols():
    code = "# top\nclass A:\n    @staticmethod\n    def f(x: int, /, *, factor=2) -> int:\n        return x\n\n    def other(self):\n        return 5  # keep\n"
    candidate = "@staticmethod\ndef f(x: int, /, *, factor=2) -> int:\n    return x * factor\n"
    updated = replace_body(code, "A.f", candidate, [])
    assert "    @staticmethod\n    def f(x: int, /, *, factor=2) -> int:\n        return x * factor" in updated
    assert "return 5  # keep" in updated


def test_context_only_authorized_symbols_and_mock_runs(demo):
    store = Store(demo)
    spec = store.load()
    for binding in spec.bindings:
        if binding.target == "normalize":
            binding.visibility = "L4"
    store.save(spec, store.load().revision)
    context = build_context(demo, "normalize", "L4")
    encoded = json.dumps(context)
    assert "def normalize" in encoded and "def ingest" in encoded
    assert "def report" not in encoded and "def summarize" not in encoded
    assert context["entries"][1]["examples"]
    change = generate(demo, "ingest")
    assert change.status == "proposed"
    assert "NotImplementedError" not in change.after


def test_file_qualified_scan(tmp_path):
    (tmp_path / "src").mkdir()
    for filename in ("one.py", "two.py"):
        (tmp_path / "src" / filename).write_text("def run(x):\n    return x\n", encoding="utf-8")
    found = scan_candidates(tmp_path)
    assert {f["symbol"]["path"] for f in found} == {"src/one.py", "src/two.py"}
    assert all(not f["confirmed"] for f in found)
    with pytest.raises(FlowError):
        inside(tmp_path, "../escape.py")


def test_view_does_not_invalidate_semantics_and_architecture_conflicts(demo):
    store = Store(demo)
    project = store.load()
    change = propose_architecture(demo, project.model_copy(update={"name": "Renamed"}), project.revision)
    store.save_views({"positions": {"ingest": {"x": 10, "y": 20}}}, store.views()["revision"])
    assert store.load().revision == project.revision
    accept(demo, change.id, project.revision)
    with pytest.raises(Conflict):
        propose_architecture(demo, project, project.revision)


def test_capture_redacts_before_sizing_and_preserves_schema_names(demo):
    project = Store(demo).load()
    project.capture.level = "full"
    result = capture({"email": "secret@example.com", "nested": {"password": "highly-secret"}, "items": [1, 2]}, project.capture)
    assert "highly-secret" not in json.dumps(result)
    assert "secret@example.com" not in json.dumps(result)
    assert len(result["redacted"]) == 2
    project.input_schema["properties"]["password"] = {"type": "string"}
    assert sanitize_project(project)["input_schema"]["properties"]["password"] == {"type": "string"}
    project.capture.max_bytes = 128
    assert capture("x" * 1000, project.capture)["truncated"]


def test_journal_recovers_and_clean_preserves_definitions(demo):
    store = Store(demo)
    old = (demo / "src/steps.py").read_text(encoding="utf-8")
    journal = {"writes": [{"path": "src/steps.py", "before_digest": file_digest(old), "after": old + "\n# recovered\n"}]}
    atomic_write(store.state / "transaction.json", json.dumps(journal))
    store.load()
    assert "# recovered" in (demo / "src/steps.py").read_text(encoding="utf-8")
    assert not (store.state / "transaction.json").exists()
    before = (demo / "flow.yaml").read_bytes()
    store.clean()
    assert (demo / "flow.yaml").read_bytes() == before
