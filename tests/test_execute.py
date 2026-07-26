"""Tests for the execution engine (``sfa.execute``).

Covers topological ordering, cycle detection, parameter-name data binding,
contract validation levels, fail-fast behaviour, async/method entry points,
initial-input merge priority, multi-upstream merging and the defensive
composite-endpoint guard.
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from sfa import execute as exe
from sfa import extract as extract_mod
from sfa import init as init_mod
from sfa import module as module_mod
from sfa import pipe as pipe_mod
from sfa import snapshot as snap
from sfa import topology as topo
from sfa.config import SFAError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

GEN_SRC = 'def gen(seed: int) -> dict:\n    """gen."""\n    return {"features": [seed, seed * 2]}\n'
INFER_SRC = 'def infer(features: list) -> dict:\n    """infer."""\n    return {"prediction": sum(features)}\n'


def _make_project(tmp_path: Path, *sources: tuple[str, str]) -> Path:
    root = init_mod.init_project(tmp_path)
    src = root / "src"
    src.mkdir(exist_ok=True)
    for filename, content in sources:
        (src / filename).write_text(content, encoding="utf-8")
    extract_mod.extract(root)
    return root


def _run(root: Path, initial_input: dict | None = None) -> dict:
    return exe.run(root, initial_input=initial_input)


# ---------------------------------------------------------------------------
# Topological sort & cycle detection
# ---------------------------------------------------------------------------


def test_topo_order_two_module_chain(tmp_path: Path) -> None:
    root = _make_project(tmp_path, ("a.py", GEN_SRC), ("b.py", INFER_SRC))
    module_mod.add_module(root, "gen", "gen")
    module_mod.add_module(root, "infer", "infer")
    pipe_mod.add_pipe(root, "gen", "infer")
    manifest = _run(root, {"seed": 5})
    assert manifest["execution_order"] == ["gen", "infer"]
    assert manifest["overall_status"] == "success"


def test_topo_order_three_module_chain(tmp_path: Path) -> None:
    c_src = 'def out(prediction: int) -> dict:\n    """out."""\n    return {"label": str(prediction)}\n'
    root = _make_project(tmp_path, ("a.py", GEN_SRC), ("b.py", INFER_SRC), ("c.py", c_src))
    module_mod.add_module(root, "gen", "gen")
    module_mod.add_module(root, "infer", "infer")
    module_mod.add_module(root, "out", "out")
    pipe_mod.add_pipe(root, "gen", "infer")
    pipe_mod.add_pipe(root, "infer", "out")
    manifest = _run(root, {"seed": 3})
    assert manifest["execution_order"] == ["gen", "infer", "out"]
    out_snap = snap.read_snapshot(root, manifest["run_id"], "out")
    assert out_snap["output"] == {"label": "9"}


def test_cycle_detected(tmp_path: Path) -> None:
    root = _make_project(tmp_path, ("a.py", GEN_SRC), ("b.py", INFER_SRC))
    module_mod.add_module(root, "gen", "gen")
    module_mod.add_module(root, "infer", "infer")
    pipe_mod.add_pipe(root, "gen", "infer")
    pipe_mod.add_pipe(root, "infer", "gen")  # creates a cycle
    try:
        _run(root, {"seed": 1})
    except SFAError as exc:
        assert "循环" in str(exc)
        return
    raise AssertionError("expected SFAError for cycle")


def test_isolated_module_runs_with_initial_input(tmp_path: Path) -> None:
    root = _make_project(tmp_path, ("a.py", GEN_SRC))
    module_mod.add_module(root, "gen", "gen")
    manifest = _run(root, {"seed": 7})
    assert manifest["overall_status"] == "success"
    s = snap.read_snapshot(root, manifest["run_id"], "gen")
    assert s["output"] == {"features": [7, 14]}


def test_no_atomic_modules_raises(tmp_path: Path) -> None:
    root = init_mod.init_project(tmp_path)
    try:
        _run(root)
    except SFAError as exc:
        assert "无原子模块" in str(exc)
        return
    raise AssertionError("expected SFAError for no atomic modules")


# ---------------------------------------------------------------------------
# Parameter-name binding
# ---------------------------------------------------------------------------


def test_kwargs_binding_filters_extra_keys(tmp_path: Path) -> None:
    # infer accepts (features, scale=1.0); upstream emits an extra 'noise' key.
    infer_src = (
        'def infer(features: list, scale: float = 1.0) -> dict:\n'
        '    """infer."""\n'
        '    return {"prediction": sum(features) * scale}\n'
    )
    gen_src = (
        'def gen(seed: int) -> dict:\n'
        '    """gen."""\n'
        '    return {"features": [seed], "noise": "ignored"}\n'
    )
    root = _make_project(tmp_path, ("a.py", gen_src), ("b.py", infer_src))
    module_mod.add_module(root, "gen", "gen")
    module_mod.add_module(root, "infer", "infer")
    pipe_mod.add_pipe(root, "gen", "infer")
    manifest = _run(root, {"seed": 2})
    s = snap.read_snapshot(root, manifest["run_id"], "infer")
    # Only 'features' is bound; 'noise' dropped, 'scale' keeps its default.
    assert s["input"] == {"features": [2]}
    assert s["output"] == {"prediction": 2}


def test_scalar_upstream_output_rejected(tmp_path: Path) -> None:
    a_src = 'def a() -> int:\n    """a."""\n    return 5\n'
    b_src = 'def b(x: int) -> int:\n    """b."""\n    return x\n'
    root = _make_project(tmp_path, ("a.py", a_src), ("b.py", b_src))
    module_mod.add_module(root, "a", "a")
    module_mod.add_module(root, "b", "b")
    pipe_mod.add_pipe(root, "a", "b")
    try:
        _run(root, {})
    except exe.ModuleRunError as exc:
        assert "不是字典" in str(exc)
        return
    raise AssertionError("expected ModuleRunError for non-dict upstream output")


def test_none_upstream_output_rejected(tmp_path: Path) -> None:
    # A void module (-> None) feeding a downstream must error per spec
    # (non-dict upstream), not be silently skipped.
    a_src = 'def a() -> None:\n    """a."""\n    return None\n'
    b_src = 'def b(x: int) -> int:\n    """b."""\n    return x\n'
    root = _make_project(tmp_path, ("a.py", a_src), ("b.py", b_src))
    module_mod.add_module(root, "a", "a")
    module_mod.add_module(root, "b", "b")
    pipe_mod.add_pipe(root, "a", "b")
    try:
        _run(root, {"x": 1})
    except exe.ModuleRunError as exc:
        assert "不是字典" in str(exc)
        assert "NoneType" in str(exc)
        return
    raise AssertionError("expected ModuleRunError for None upstream output")


def test_fail_fast_on_missing_contract(tmp_path: Path) -> None:
    # A missing contract.json must trigger fail-fast AND still finalise the
    # run manifest + .latest (the unwrapped-SFAError gap).
    root = _make_project(tmp_path, ("a.py", GEN_SRC))
    module_mod.add_module(root, "gen", "gen")
    (root / ".sfa" / "modules" / "gen" / "contract.json").unlink()
    try:
        _run(root, {"seed": 1})
    except exe.ModuleRunError:
        pass
    else:
        raise AssertionError("expected ModuleRunError for missing contract")
    run_id = snap.read_latest(root)
    assert run_id is not None  # manifest finalised even on contract-load failure
    manifest = snap.read_run_manifest(root, run_id)
    assert manifest["overall_status"] == "error"
    assert manifest["modules"][0]["status"] == "error"


def test_module_path_traversal_rejected(tmp_path: Path) -> None:
    # A hand-edited module.path escaping the project must be rejected.
    root = _make_project(tmp_path, ("a.py", GEN_SRC))
    module_mod.add_module(root, "gen", "gen")
    path = root / ".sfa" / "pipeline.yml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["modules"][0]["path"] = "../evil.py"
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    try:
        _run(root, {"seed": 1})
    except exe.ModuleRunError as exc:
        assert "越界" in str(exc)
        return
    raise AssertionError("expected ModuleRunError for path traversal")


def test_initial_input_overridden_by_upstream(tmp_path: Path) -> None:
    # b(x) <- a outputs {"x": 10}; initial input has {"x": 99}; upstream wins.
    a_src = 'def a() -> dict:\n    """a."""\n    return {"x": 10}\n'
    b_src = 'def b(x: int) -> int:\n    """b."""\n    return x\n'
    root = _make_project(tmp_path, ("a.py", a_src), ("b.py", b_src))
    module_mod.add_module(root, "a", "a")
    module_mod.add_module(root, "b", "b")
    pipe_mod.add_pipe(root, "a", "b")
    manifest = _run(root, {"x": 99})
    s = snap.read_snapshot(root, manifest["run_id"], "b")
    assert s["input"] == {"x": 10}
    assert s["output"] == 10


def test_multi_upstream_merge(tmp_path: Path) -> None:
    a_src = 'def a() -> dict:\n    """a."""\n    return {"x": 1}\n'
    b_src = 'def b() -> dict:\n    """b."""\n    return {"y": 2}\n'
    c_src = 'def c(x: int, y: int) -> int:\n    """c."""\n    return x + y\n'
    root = _make_project(tmp_path, ("a.py", a_src), ("b.py", b_src), ("c.py", c_src))
    module_mod.add_module(root, "a", "a")
    module_mod.add_module(root, "b", "b")
    module_mod.add_module(root, "c", "c")
    pipe_mod.add_pipe(root, "a", "c")
    pipe_mod.add_pipe(root, "b", "c")
    manifest = _run(root, {})
    s = snap.read_snapshot(root, manifest["run_id"], "c")
    assert s["input"] == {"x": 1, "y": 2}
    assert s["output"] == 3


def test_kwargs_arbitrary_accepted(tmp_path: Path) -> None:
    # Entry with **kwargs accepts all merged keys unfiltered.  M2's contract
    # inference treats ``**kw`` as a required property, so validation is set
    # to none to isolate the binding behaviour under test.
    a_src = 'def a() -> dict:\n    """a."""\n    return {"x": 1, "y": 2, "z": 3}\n'
    b_src = 'def b(**kw) -> dict:\n    """b."""\n    return dict(kw)\n'
    root = _make_project(tmp_path, ("a.py", a_src), ("b.py", b_src))
    module_mod.add_module(root, "a", "a")
    module_mod.add_module(root, "b", "b", validation="none")
    pipe_mod.add_pipe(root, "a", "b")
    manifest = _run(root, {})
    s = snap.read_snapshot(root, manifest["run_id"], "b")
    assert s["input"] == {"x": 1, "y": 2, "z": 3}


# ---------------------------------------------------------------------------
# Contract validation levels
# ---------------------------------------------------------------------------


def test_strict_input_validation_fails(tmp_path: Path) -> None:
    root = _make_project(tmp_path, ("a.py", GEN_SRC))
    module_mod.add_module(root, "gen", "gen", validation="strict")
    try:
        _run(root, {"seed": "not-an-int"})
    except exe.ModuleRunError as exc:
        assert "输入契约校验失败" in str(exc)
        return
    raise AssertionError("expected ModuleRunError for strict input validation")


def test_lenient_input_validation_warns_and_continues(tmp_path: Path) -> None:
    echo_src = 'def echo(x: int) -> dict:\n    """echo."""\n    return {"value": x}\n'
    root = _make_project(tmp_path, ("a.py", echo_src))
    module_mod.add_module(root, "echo", "echo", validation="lenient")
    manifest = _run(root, {"x": "str"})
    assert manifest["overall_status"] == "success"
    rec = manifest["modules"][0]
    assert rec["warnings"], "lenient should record warnings"
    assert any("输入校验警告" in w for w in rec["warnings"])


def test_none_validation_skips(tmp_path: Path) -> None:
    echo_src = 'def echo(x: int) -> dict:\n    """echo."""\n    return {"value": x}\n'
    root = _make_project(tmp_path, ("a.py", echo_src))
    module_mod.add_module(root, "echo", "echo", validation="none")
    manifest = _run(root, {"x": "str"})
    assert manifest["overall_status"] == "success"
    assert "warnings" not in manifest["modules"][0]


def test_strict_output_validation_fails(tmp_path: Path) -> None:
    # Annotated `-> int` but returns a string => strict output validation fails.
    bad_src = 'def bad() -> int:\n    """bad."""\n    return "not-int"\n'
    root = _make_project(tmp_path, ("a.py", bad_src))
    module_mod.add_module(root, "bad", "bad", validation="strict")
    try:
        _run(root, {})
    except exe.ModuleRunError as exc:
        assert "输出契约校验失败" in str(exc)
        return
    raise AssertionError("expected ModuleRunError for strict output validation")


# ---------------------------------------------------------------------------
# Fail-fast
# ---------------------------------------------------------------------------


def test_fail_fast_records_error_snapshot(tmp_path: Path) -> None:
    bad_infer = 'def infer(features: list) -> dict:\n    """infer."""\n    raise ValueError("boom")\n'
    root = _make_project(tmp_path, ("a.py", GEN_SRC), ("b.py", bad_infer))
    module_mod.add_module(root, "gen", "gen")
    module_mod.add_module(root, "infer", "infer")
    pipe_mod.add_pipe(root, "gen", "infer")
    try:
        _run(root, {"seed": 5})
    except exe.ModuleRunError as exc:
        assert "infer" in str(exc)
        assert "执行失败" in str(exc)
        assert "输入快照" in str(exc)
    else:
        raise AssertionError("expected ModuleRunError")
    # The failing run still wrote a manifest + latest.
    run_id = snap.read_latest(root)
    assert run_id is not None
    manifest = snap.read_run_manifest(root, run_id)
    assert manifest["overall_status"] == "error"
    by_id = {r["id"]: r for r in manifest["modules"]}
    assert by_id["gen"]["status"] == "success"
    assert by_id["infer"]["status"] == "error"
    err_snap = snap.read_snapshot(root, run_id, "infer")
    assert err_snap["status"] == "error"
    assert "boom" in err_snap["error"]
    assert err_snap["input"] == {"features": [5, 10]}


# ---------------------------------------------------------------------------
# Entry-point variants
# ---------------------------------------------------------------------------


def test_async_entry_executed(tmp_path: Path) -> None:
    src = (
        'async def agen(seed: int) -> dict:\n'
        '    """agen."""\n'
        '    return {"features": [seed]}\n'
    )
    root = _make_project(tmp_path, ("a.py", src))
    module_mod.add_module(root, "agen", "agen")
    manifest = _run(root, {"seed": 9})
    s = snap.read_snapshot(root, manifest["run_id"], "agen")
    assert s["output"] == {"features": [9]}


def test_method_entry_no_arg_construct(tmp_path: Path) -> None:
    src = (
        'class Proc:\n'
        '    """Proc."""\n'
        '    def run(self, data: list) -> dict:\n'
        '        """run."""\n'
        '        return {"sum": sum(data)}\n'
    )
    root = _make_project(tmp_path, ("a.py", src))
    module_mod.add_module(root, "proc", "Proc.run")
    manifest = _run(root, {"data": [1, 2, 3]})
    s = snap.read_snapshot(root, manifest["run_id"], "proc")
    assert s["output"] == {"sum": 6}


def test_method_entry_constructor_needs_args_fails(tmp_path: Path) -> None:
    src = (
        'class C:\n'
        '    """C."""\n'
        '    def __init__(self, n: int):\n'
        '        self.n = n\n'
        '    def run(self) -> dict:\n'
        '        """run."""\n'
        '        return {}\n'
    )
    root = _make_project(tmp_path, ("a.py", src))
    module_mod.add_module(root, "c", "C.run")
    try:
        _run(root, {})
    except exe.ModuleRunError as exc:
        assert "无参构造" in str(exc) or "构造需要参数" in str(exc)
        return
    raise AssertionError("expected ModuleRunError for constructor needing args")


# ---------------------------------------------------------------------------
# Defensive: composite endpoint in pipeline.yml
# ---------------------------------------------------------------------------


def test_composite_pipe_endpoint_rejected_at_run(tmp_path: Path) -> None:
    root = _make_project(tmp_path, ("a.py", GEN_SRC), ("b.py", INFER_SRC))
    module_mod.add_module(root, "gen", "gen")
    module_mod.add_module(root, "infer", "infer")
    pipe_mod.add_pipe(root, "gen", "infer")
    composite = topo.group_modules(root, ["gen", "infer"], "复合")
    # Hand-edit pipeline.yml to add a pipe targeting the composite (bypassing
    # the add_pipe guard) to simulate a stale/edited topology.
    path = root / ".sfa" / "pipeline.yml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["pipes"].append(
        {"id": "pipe_bad", "source": "gen", "target": composite["id"], "visibility": "L2"}
    )
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    try:
        _run(root, {"seed": 1})
    except SFAError as exc:
        assert "复合模块" in str(exc)
        return
    raise AssertionError("expected SFAError for composite pipe endpoint")


# ---------------------------------------------------------------------------
# Manifest & latest pointer
# ---------------------------------------------------------------------------


def test_manifest_and_latest_written(tmp_path: Path) -> None:
    root = _make_project(tmp_path, ("a.py", GEN_SRC), ("b.py", INFER_SRC))
    module_mod.add_module(root, "gen", "gen")
    module_mod.add_module(root, "infer", "infer")
    pipe_mod.add_pipe(root, "gen", "infer")
    manifest = _run(root, {"seed": 4})
    assert snap.read_latest(root) == manifest["run_id"]
    on_disk = snap.read_run_manifest(root, manifest["run_id"])
    assert on_disk == manifest
    assert set(on_disk["execution_order"]) == {"gen", "infer"}
    assert len(on_disk["modules"]) == 2
    assert all(m["status"] == "success" for m in on_disk["modules"])
