"""Tests for the M5 probe system (DSL, storage, validation, runtime)."""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from sfa import extract as extract_mod
from sfa import init as init_mod
from sfa import module as module_mod
from sfa import pipe as pipe_mod
from sfa import probe as probe_mod
from sfa.config import SFAError


# ---------------------------------------------------------------------------
# Project fixtures
# ---------------------------------------------------------------------------


def _make_project(tmp_path: Path, *sources: tuple[str, str]) -> Path:
    root = init_mod.init_project(tmp_path)
    src = root / "src"
    src.mkdir(exist_ok=True)
    for filename, content in sources:
        (src / filename).write_text(content, encoding="utf-8")
    extract_mod.extract(root)
    return root


SAMPLE_GEN = '''def gen(seed: int) -> dict:
    """Generate."""
    return {"score": seed * 2, "items": [{"id": 1}, {"id": 2}]}
'''

SAMPLE_BRANCH = '''def branch(score: int, items: list) -> dict:
    """Branch."""
    return {"ok": True}
'''

SAMPLE_LIST = '''def produce(n: int) -> list:
    """Produce list."""
    return [n, n * 2, n * 3]
'''


def _three_module_project(tmp_path: Path) -> Path:
    root = _make_project(
        tmp_path,
        ("gen.py", SAMPLE_GEN),
        ("branch.py", SAMPLE_BRANCH),
        ("list.py", SAMPLE_LIST),
    )
    module_mod.add_module(root, "gen", "gen")
    module_mod.add_module(root, "branch1", "branch")
    module_mod.add_module(root, "branch2", "branch")
    pipe_mod.add_pipe(root, "gen", "branch1")
    pipe_mod.add_pipe(root, "gen", "branch2")
    return root


# ---------------------------------------------------------------------------
# DSL: parsing / whitelist
# ---------------------------------------------------------------------------


def test_dsl_parse_and_evaluate_field_access() -> None:
    tree = probe_mod.validate_condition("$output.score > 0.8", {})
    assert probe_mod.evaluate(tree, {"score": 1.0}) is True
    assert probe_mod.evaluate(tree, {"score": 0.5}) is False


def test_dsl_nested_field_access() -> None:
    tree = probe_mod.validate_condition("$output.user.id == 'x'", {})
    assert probe_mod.evaluate(tree, {"user": {"id": "x"}}) is True
    assert probe_mod.evaluate(tree, {"user": {"id": "y"}}) is False


def test_dsl_subscript_positive_and_negative() -> None:
    tree = probe_mod.validate_condition("$output[0] <= $output[-1]", {})
    assert probe_mod.evaluate(tree, [1, 2, 3]) is True
    assert probe_mod.evaluate(tree, [3, 2, 1]) is False


def test_dsl_subscript_then_attribute() -> None:
    tree = probe_mod.validate_condition("$output[0].id == 1", {})
    assert probe_mod.evaluate(tree, [{"id": 1}, {"id": 2}]) is True


def test_dsl_arithmetic_and_boolean() -> None:
    tree = probe_mod.validate_condition("$output.a + $output.b > 10 and $output.c", {})
    assert probe_mod.evaluate(tree, {"a": 6, "b": 5, "c": True}) is True
    assert probe_mod.evaluate(tree, {"a": 3, "b": 4, "c": True}) is False


def test_dsl_membership_in_list() -> None:
    tree = probe_mod.validate_condition("$output.tag in ['a', 'b']", {})
    assert probe_mod.evaluate(tree, {"tag": "a"}) is True
    assert probe_mod.evaluate(tree, {"tag": "c"}) is False


def test_dsl_rejects_call() -> None:
    try:
        probe_mod.validate_condition("$output.keys()", {})
    except probe_mod.ProbeDefinitionError as exc:
        assert "Call" in str(exc)
        return
    raise AssertionError("expected ProbeDefinitionError for Call")


def test_dsl_rejects_import() -> None:
    for expr in ["__import__('os')", "$output.__class__", "$output._private"]:
        try:
            probe_mod.validate_condition(expr, {})
        except probe_mod.ProbeDefinitionError:
            continue
        raise AssertionError(f"expected ProbeDefinitionError for {expr!r}")


def test_dsl_rejects_lambda() -> None:
    try:
        probe_mod.validate_condition("lambda x: x", {})
    except probe_mod.ProbeDefinitionError as exc:
        assert "Lambda" in str(exc)
        return
    raise AssertionError("expected ProbeDefinitionError for Lambda")


def test_dsl_rejects_unknown_variable() -> None:
    try:
        probe_mod.validate_condition("x > 1", {})
    except probe_mod.ProbeDefinitionError as exc:
        assert "x" in str(exc)
        return
    raise AssertionError("expected ProbeDefinitionError for unknown variable")


def test_dsl_evaluation_error_missing_key() -> None:
    tree = probe_mod.validate_condition("$output.score > 0", {})
    try:
        probe_mod.evaluate(tree, {})
    except probe_mod.ProbeEvaluationError as exc:
        assert "score" in str(exc)
        return
    raise AssertionError("expected ProbeEvaluationError for missing key")


def test_dsl_evaluation_error_type_mismatch() -> None:
    tree = probe_mod.validate_condition("$output.score + 1", {})
    try:
        probe_mod.evaluate(tree, {"score": "not-a-number"})
    except probe_mod.ProbeEvaluationError:
        return
    raise AssertionError("expected ProbeEvaluationError for type mismatch")


# ---------------------------------------------------------------------------
# Static schema check
# ---------------------------------------------------------------------------


def test_static_check_simple_object_property_pass() -> None:
    schema = {
        "type": "object",
        "properties": {"score": {"type": "number"}},
    }
    probe_mod.validate_condition("$output.score > 0.5", schema)


def test_static_check_nested_property_pass() -> None:
    schema = {
        "type": "object",
        "properties": {
            "user": {
                "type": "object",
                "properties": {"id": {"type": "string"}},
            }
        },
    }
    probe_mod.validate_condition("$output.user.id == 'x'", schema)


def test_static_check_missing_property_fails() -> None:
    schema = {
        "type": "object",
        "properties": {"score": {"type": "number"}},
        "additionalProperties": False,
    }
    try:
        probe_mod.validate_condition("$output.missing > 0", schema)
    except probe_mod.ProbeDefinitionError as exc:
        assert "missing" in str(exc)
        return
    raise AssertionError("expected ProbeDefinitionError for missing property")


def test_static_check_unknown_schema_passes() -> None:
    probe_mod.validate_condition("$output.anything.whatever", {})


def test_static_check_array_index_pass() -> None:
    schema = {"type": "array", "items": {"type": "number"}}
    probe_mod.validate_condition("$output[0] > 0", schema)


def test_static_check_array_then_object() -> None:
    schema = {
        "type": "array",
        "items": {"type": "object", "properties": {"id": {"type": "integer"}}},
    }
    probe_mod.validate_condition("$output[0].id == 1", schema)


def test_static_check_not_object_fails() -> None:
    schema = {"type": "integer"}
    try:
        probe_mod.validate_condition("$output.field > 0", schema)
    except probe_mod.ProbeDefinitionError as exc:
        assert "$output.field" in str(exc)
        return
    raise AssertionError("expected ProbeDefinitionError for non-object schema")


def test_static_check_not_array_fails() -> None:
    schema = {"type": "object"}
    try:
        probe_mod.validate_condition("$output[0] > 0", schema)
    except probe_mod.ProbeDefinitionError as exc:
        assert "$output[0]" in str(exc)
        return
    raise AssertionError("expected ProbeDefinitionError for non-array schema")


def test_static_check_anyof_pass() -> None:
    schema = {
        "anyOf": [
            {"type": "object", "properties": {"a": {"type": "integer"}}},
            {"type": "object", "properties": {"b": {"type": "integer"}}},
        ]
    }
    probe_mod.validate_condition("$output.a > 0", schema)


def test_static_check_prefix_items() -> None:
    schema = {
        "type": "array",
        "prefixItems": [
            {"type": "object", "properties": {"id": {"type": "integer"}}},
        ],
    }
    probe_mod.validate_condition("$output[0].id == 1", schema)


# ---------------------------------------------------------------------------
# Storage CRUD
# ---------------------------------------------------------------------------


def test_write_and_list_probe(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    probe = {"id": "my_probe", "name": "My Probe", "type": "assertion", "pipe": "p1", "condition": "$output.x > 0"}
    probe_mod.write_probe(root, probe)
    probes = probe_mod.list_probes(root)
    assert len(probes) == 1
    assert probes[0]["id"] == "my_probe"
    assert probes[0]["name"] == "My Probe"


def test_find_probe_missing_raises(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    try:
        probe_mod.find_probe(root, "nope")
    except SFAError as exc:
        assert "nope" in str(exc)
        return
    raise AssertionError("expected SFAError for missing probe")


def test_remove_probe(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    probe = {"id": "p", "type": "assertion", "pipe": "p1", "condition": "$output.x > 0"}
    probe_mod.write_probe(root, probe)
    removed = probe_mod.remove_probe(root, "p")
    assert removed["id"] == "p"
    assert probe_mod.list_probes(root) == []


def test_list_probes_for_pipe(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    probe_mod.write_probe(root, {"id": "p1", "type": "assertion", "pipe": "pipe_a_b", "condition": "$output.x > 0"})
    probe_mod.write_probe(root, {"id": "p2", "type": "assertion", "pipe": "pipe_a_b", "condition": "$output.y > 0"})
    probe_mod.write_probe(root, {"id": "p3", "type": "assertion", "pipe": "pipe_c_d", "condition": "$output.z > 0"})
    matches = probe_mod.list_probes_for_pipe(root, "pipe_a_b")
    assert {p["id"] for p in matches} == {"p1", "p2"}


def test_remove_probes_for_pipe(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    probe_mod.write_probe(root, {"id": "p1", "type": "assertion", "pipe": "pipe_a_b", "condition": "$output.x > 0"})
    removed = probe_mod.remove_probes_for_pipe(root, "pipe_a_b")
    assert [p["id"] for p in removed] == ["p1"]
    assert probe_mod.list_probes(root) == []


def test_remove_probes_referencing_module(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    probe_mod.write_probe(
        root,
        {"id": "r1", "type": "router", "pipe": "p", "condition": "$output.x > 0", "on_true": "mod_a", "on_false": "mod_b"},
    )
    removed = probe_mod.remove_probes_referencing_module(root, "mod_b")
    assert [p["id"] for p in removed] == ["r1"]
    assert probe_mod.list_probes(root) == []


# ---------------------------------------------------------------------------
# Definition-time validation
# ---------------------------------------------------------------------------


def test_add_router_probe_success(tmp_path: Path) -> None:
    root = _three_module_project(tmp_path)
    probe = probe_mod.add_router_probe(
        root, "score_gate", "pipe_gen_branch1", "$output.score > 5", "branch1", "branch2"
    )
    assert probe["id"] == "score_gate"
    assert probe["type"] == "router"
    assert (root / ".sfa" / "probes" / "score_gate.yml").is_file()


def test_add_router_probe_rejects_on_true_not_pipe_target(tmp_path: Path) -> None:
    root = _three_module_project(tmp_path)
    try:
        probe_mod.add_router_probe(
            root, "bad", "pipe_gen_branch1", "$output.score > 5", "branch2", "branch1"
        )
    except probe_mod.ProbeDefinitionError as exc:
        assert "on_true" in str(exc)
        return
    raise AssertionError("expected on_true != target rejection")


def test_add_router_probe_rejects_same_branches(tmp_path: Path) -> None:
    root = _three_module_project(tmp_path)
    try:
        probe_mod.add_router_probe(
            root, "bad", "pipe_gen_branch1", "$output.score > 5", "branch1", "branch1"
        )
    except probe_mod.ProbeDefinitionError as exc:
        assert "on_true" in str(exc) or "on_false" in str(exc)
        return
    raise AssertionError("expected same branch rejection")


def test_add_router_probe_rejects_missing_on_false_pipe(tmp_path: Path) -> None:
    root = _three_module_project(tmp_path)
    # Remove the on_false pipe to create a missing branch.
    pipe_mod.remove_pipe(root, "pipe_gen_branch2")
    try:
        probe_mod.add_router_probe(
            root, "bad", "pipe_gen_branch1", "$output.score > 5", "branch1", "branch2"
        )
    except probe_mod.ProbeDefinitionError as exc:
        assert "on_false" in str(exc) or "管道" in str(exc)
        return
    raise AssertionError("expected missing on_false pipe rejection")


def test_add_router_probe_rejects_static_check_failure(tmp_path: Path) -> None:
    root = _three_module_project(tmp_path)
    # Tighten the gen contract so the missing field is rejected.
    contract_path = root / ".sfa" / "modules" / "gen" / "contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract["output_schema"] = {
        "type": "object",
        "properties": {"score": {"type": "number"}},
        "additionalProperties": False,
    }
    contract_path.write_text(json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8")

    try:
        probe_mod.add_router_probe(
            root, "bad", "pipe_gen_branch1", "$output.nonexistent > 5", "branch1", "branch2"
        )
    except probe_mod.ProbeDefinitionError as exc:
        assert "nonexistent" in str(exc)
        return
    raise AssertionError("expected static check failure")


def test_add_assertion_probe_success(tmp_path: Path) -> None:
    root = _three_module_project(tmp_path)
    probe = probe_mod.add_assertion_probe(
        root, "ordered", "pipe_gen_branch1", "$output.score > 0"
    )
    assert probe["id"] == "ordered"
    assert probe["type"] == "assertion"


def test_add_assertion_probe_rejects_bad_condition(tmp_path: Path) -> None:
    root = _three_module_project(tmp_path)
    try:
        probe_mod.add_assertion_probe(root, "bad", "pipe_gen_branch1", "$output[0] > 0")
    except probe_mod.ProbeDefinitionError as exc:
        assert "$output[0]" in str(exc)
        return
    raise AssertionError("expected array schema rejection")


def test_add_probe_rejects_duplicate_id(tmp_path: Path) -> None:
    root = _three_module_project(tmp_path)
    probe_mod.add_assertion_probe(root, "dup", "pipe_gen_branch1", "$output.score > 0")
    try:
        probe_mod.add_assertion_probe(root, "dup", "pipe_gen_branch1", "$output.score > 1")
    except probe_mod.ProbeDefinitionError as exc:
        assert "dup" in str(exc)
        return
    raise AssertionError("expected duplicate id rejection")


# ---------------------------------------------------------------------------
# Cascade deletion
# ---------------------------------------------------------------------------


def test_pipe_remove_cascades_to_probes(tmp_path: Path) -> None:
    root = _three_module_project(tmp_path)
    probe_mod.add_assertion_probe(root, "ap", "pipe_gen_branch1", "$output.score > 0")
    removed_pipe, removed_probes = pipe_mod.remove_pipe(root, "pipe_gen_branch1")
    assert removed_pipe["id"] == "pipe_gen_branch1"
    assert [p["id"] for p in removed_probes] == ["ap"]
    assert probe_mod.list_probes(root) == []


def test_module_remove_cascades_to_probes(tmp_path: Path) -> None:
    root = _three_module_project(tmp_path)
    probe_mod.add_router_probe(
        root, "rg", "pipe_gen_branch1", "$output.score > 5", "branch1", "branch2"
    )
    mod, removed_pipes, removed_probes = module_mod.remove_module(root, "gen")
    assert len(removed_pipes) == 2
    assert [p["id"] for p in removed_probes] == ["rg"]


def test_module_remove_cascades_on_true_on_false_refs(tmp_path: Path) -> None:
    root = _three_module_project(tmp_path)
    probe_mod.add_router_probe(
        root, "rg", "pipe_gen_branch1", "$output.score > 5", "branch1", "branch2"
    )
    # Remove branch2; the pipe gen->branch2 is removed, and the router probe is
    # removed both because it is attached to a removed pipe and because branch2
    # is its on_false target.
    mod, removed_pipes, removed_probes = module_mod.remove_module(root, "branch2")
    assert [p["id"] for p in removed_pipes] == ["pipe_gen_branch2"]
    assert [p["id"] for p in removed_probes] == ["rg"]


# ---------------------------------------------------------------------------
# Runtime helpers
# ---------------------------------------------------------------------------


def test_load_probes_by_source_groups_by_source(tmp_path: Path) -> None:
    root = _three_module_project(tmp_path)
    probe_mod.add_assertion_probe(root, "ap1", "pipe_gen_branch1", "$output.score > 0")
    probe_mod.add_assertion_probe(root, "ap2", "pipe_gen_branch2", "$output.score > 0")
    by_source, orphans = probe_mod.load_probes_by_source(root)
    assert set(by_source.keys()) == {"gen"}
    assert len(by_source["gen"]) == 2
    assert orphans == []


def test_load_probes_by_source_reports_orphan(tmp_path: Path) -> None:
    root = _three_module_project(tmp_path)
    probe_mod.write_probe(
        root,
        {"id": "orphan", "type": "assertion", "pipe": "nonexistent_pipe", "condition": "$output.x > 0"},
    )
    by_source, orphans = probe_mod.load_probes_by_source(root)
    assert by_source == {}
    assert len(orphans) == 1
    assert orphans[0]["probe_id"] == "orphan"
    assert orphans[0]["status"] == "orphan"


def test_evaluate_probe_router_records_branch(tmp_path: Path) -> None:
    root = _three_module_project(tmp_path)
    probe_mod.add_router_probe(
        root, "rg", "pipe_gen_branch1", "$output.score > 5", "branch1", "branch2"
    )
    probe = probe_mod.get_probe(root, "rg")
    result = probe_mod.evaluate_probe(probe, {"score": 10})
    assert result["condition_result"] is True
    assert result["branch"] == "on_true"
    assert result["branch_target"] == "branch1"


def test_evaluate_probe_assertion_pass_and_fail(tmp_path: Path) -> None:
    root = _three_module_project(tmp_path)
    probe_mod.add_assertion_probe(root, "ap", "pipe_gen_branch1", "$output.score > 0")
    probe = probe_mod.get_probe(root, "ap")
    assert probe_mod.evaluate_probe(probe, {"score": 5})["passed"] is True
    result = probe_mod.evaluate_probe(probe, {"score": -1})
    assert result["passed"] is False
    assert "score" in result["message"]


def test_evaluate_probe_assertion_runtime_error(tmp_path: Path) -> None:
    root = _three_module_project(tmp_path)
    probe_mod.add_assertion_probe(root, "ap", "pipe_gen_branch1", "$output.score > 0")
    probe = probe_mod.get_probe(root, "ap")
    try:
        probe_mod.evaluate_probe(probe, "not-a-dict")
    except probe_mod.ProbeEvaluationError as exc:
        assert "score" in str(exc)
        return
    raise AssertionError("expected ProbeEvaluationError")


# ---------------------------------------------------------------------------
# Execute engine integration
# ---------------------------------------------------------------------------


def test_execute_records_probe_results(tmp_path: Path) -> None:
    from sfa import execute as execute_mod

    root = _three_module_project(tmp_path)
    probe_mod.add_router_probe(
        root, "rg", "pipe_gen_branch1", "$output.score > 5", "branch1", "branch2"
    )
    probe_mod.add_assertion_probe(root, "ap", "pipe_gen_branch1", "$output.score > 0")

    inp = tmp_path / "input.json"
    inp.write_text(json.dumps({"seed": 10}), encoding="utf-8")
    manifest = execute_mod.run(root, json.loads(inp.read_text(encoding="utf-8")), input_file=str(inp))

    assert manifest["overall_status"] == "success"
    assert len(manifest["probes"]) == 2
    router = next(p for p in manifest["probes"] if p["probe_id"] == "rg")
    assertion = next(p for p in manifest["probes"] if p["probe_id"] == "ap")
    assert router["condition_result"] is True
    assert router["branch"] == "on_true"
    assert assertion["passed"] is True


def test_execute_assertion_failure_does_not_stop_run(tmp_path: Path) -> None:
    from sfa import execute as execute_mod

    root = _three_module_project(tmp_path)
    probe_mod.add_assertion_probe(root, "ap", "pipe_gen_branch1", "$output.score > 1000")

    inp = tmp_path / "input.json"
    inp.write_text(json.dumps({"seed": 10}), encoding="utf-8")
    manifest = execute_mod.run(root, json.loads(inp.read_text(encoding="utf-8")), input_file=str(inp))

    assert manifest["overall_status"] == "success"
    assertion = next(p for p in manifest["probes"] if p["probe_id"] == "ap")
    assert assertion["passed"] is False
    assert "message" in assertion
    gen_record = next(r for r in manifest["modules"] if r["id"] == "gen")
    assert any("断言失败" in w for w in gen_record.get("warnings", []))


def test_execute_probe_runtime_error_recorded(tmp_path: Path) -> None:
    from sfa import execute as execute_mod

    root = _three_module_project(tmp_path)
    # Schema is object; runtime will be a dict with score, but condition accesses missing field.
    probe_mod.add_assertion_probe(root, "ap", "pipe_gen_branch1", "$output.missing_field > 0")

    inp = tmp_path / "input.json"
    inp.write_text(json.dumps({"seed": 10}), encoding="utf-8")
    manifest = execute_mod.run(root, json.loads(inp.read_text(encoding="utf-8")), input_file=str(inp))

    assert manifest["overall_status"] == "success"
    assertion = next(p for p in manifest["probes"] if p["probe_id"] == "ap")
    assert assertion["status"] == "error"
    assert "missing_field" in assertion["error"]


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


from typer.testing import CliRunner
from sfa.cli import app

runner = CliRunner()


def test_cli_probe_add_router(tmp_path: Path) -> None:
    root = _three_module_project(tmp_path)
    res = runner.invoke(
        app,
        [
            "probe", "add", "router",
            "pipe_gen_branch1",
            "--condition", "$output.score > 5",
            "--on-true", "branch1",
            "--on-false", "branch2",
            "--name", "score gate",
            "--project", str(root),
        ],
    )
    assert res.exit_code == 0, res.stdout
    assert "score_gate" in res.stdout
    assert (root / ".sfa" / "probes" / "score_gate.yml").is_file()


def test_cli_probe_add_assertion(tmp_path: Path) -> None:
    root = _three_module_project(tmp_path)
    res = runner.invoke(
        app,
        [
            "probe", "add", "assertion",
            "pipe_gen_branch1",
            "--condition", "$output.score > 0",
            "--name", "positive",
            "--project", str(root),
        ],
    )
    assert res.exit_code == 0, res.stdout
    assert "positive" in res.stdout


def test_cli_probe_list_and_remove(tmp_path: Path) -> None:
    root = _three_module_project(tmp_path)
    probe_mod.add_assertion_probe(root, "p1", "pipe_gen_branch1", "$output.score > 0")
    probe_mod.add_assertion_probe(root, "p2", "pipe_gen_branch2", "$output.score > 0")

    res = runner.invoke(app, ["probe", "list", "--project", str(root)])
    assert res.exit_code == 0, res.stdout
    assert "p1" in res.stdout
    assert "p2" in res.stdout

    res = runner.invoke(app, ["probe", "remove", "p1", "--project", str(root)])
    assert res.exit_code == 0, res.stdout
    assert probe_mod.get_probe(root, "p1") is None
    assert probe_mod.get_probe(root, "p2") is not None


def test_cli_observe_shows_probes(tmp_path: Path) -> None:
    root = _three_module_project(tmp_path)
    probe_mod.add_router_probe(
        root, "rg", "pipe_gen_branch1", "$output.score > 5", "branch1", "branch2"
    )
    probe_mod.add_assertion_probe(root, "ap", "pipe_gen_branch1", "$output.score > 0")

    inp = tmp_path / "input.json"
    inp.write_text(json.dumps({"seed": 10}), encoding="utf-8")
    runner.invoke(app, ["run", "--input", str(inp), "--project", str(root)])

    res = runner.invoke(app, ["observe", "--project", str(root)])
    assert res.exit_code == 0, res.stdout
    assert "[ROUTE]" in res.stdout
    assert "[PASS]" in res.stdout
