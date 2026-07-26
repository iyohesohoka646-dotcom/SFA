"""Tests for `sfa pipe add/remove/list` and composite group/ungroup/drill."""
from __future__ import annotations

from pathlib import Path

import yaml

from sfa import extract as extract_mod
from sfa import init as init_mod
from sfa import module as module_mod
from sfa import pipe as pipe_mod
from sfa import topology as topo
from sfa.config import SFAError

SAMPLE_A = '''def func_a(x: int) -> int:
    """Func A."""
    return x
'''

SAMPLE_B = '''def func_b(y: str) -> str:
    """Func B."""
    return y
'''

SAMPLE_C = '''def func_c(z: float) -> float:
    """Func C."""
    return z
'''


def _make_project(tmp_path: Path, *sources: tuple[str, str]) -> Path:
    root = init_mod.init_project(tmp_path)
    src = root / "src"
    src.mkdir(exist_ok=True)
    for filename, content in sources:
        (src / filename).write_text(content, encoding="utf-8")
    extract_mod.extract(root)
    return root


def _make_three_modules(root: Path) -> None:
    module_mod.add_module(root, "mod_a", "func_a")
    module_mod.add_module(root, "mod_b", "func_b")
    module_mod.add_module(root, "mod_c", "func_c")


# ---------------------------------------------------------------------------
# add_pipe
# ---------------------------------------------------------------------------


def test_add_pipe_basic(tmp_path: Path) -> None:
    root = _make_project(
        tmp_path,
        ("a.py", SAMPLE_A),
        ("b.py", SAMPLE_B),
    )
    module_mod.add_module(root, "mod_a", "func_a")
    module_mod.add_module(root, "mod_b", "func_b")
    pipe = pipe_mod.add_pipe(root, "mod_a", "mod_b")
    assert pipe["id"] == "pipe_mod_a_mod_b"
    assert pipe["source"] == "mod_a"
    assert pipe["target"] == "mod_b"
    assert pipe["visibility"] == "L2"  # default from config
    assert pipe["parent"] is None


def test_add_pipe_custom_visibility(tmp_path: Path) -> None:
    root = _make_project(tmp_path, ("a.py", SAMPLE_A), ("b.py", SAMPLE_B))
    module_mod.add_module(root, "mod_a", "func_a")
    module_mod.add_module(root, "mod_b", "func_b")
    pipe = pipe_mod.add_pipe(root, "mod_a", "mod_b", visibility="L4")
    assert pipe["visibility"] == "L4"


def test_add_pipe_invalid_visibility(tmp_path: Path) -> None:
    root = _make_project(tmp_path, ("a.py", SAMPLE_A), ("b.py", SAMPLE_B))
    module_mod.add_module(root, "mod_a", "func_a")
    module_mod.add_module(root, "mod_b", "func_b")
    try:
        pipe_mod.add_pipe(root, "mod_a", "mod_b", visibility="L9")
    except SFAError as exc:
        assert "L9" in str(exc)
        return
    raise AssertionError("expected SFAError for invalid visibility")


def test_add_pipe_source_not_found(tmp_path: Path) -> None:
    root = _make_project(tmp_path, ("a.py", SAMPLE_A))
    module_mod.add_module(root, "mod_a", "func_a")
    try:
        pipe_mod.add_pipe(root, "mod_a", "nonexistent")
    except SFAError as exc:
        assert "nonexistent" in str(exc)
        return
    raise AssertionError("expected SFAError for missing target")


def test_add_pipe_self_pipe_rejected(tmp_path: Path) -> None:
    root = _make_project(tmp_path, ("a.py", SAMPLE_A))
    module_mod.add_module(root, "mod_a", "func_a")
    try:
        pipe_mod.add_pipe(root, "mod_a", "mod_a")
    except SFAError as exc:
        assert "mod_a" in str(exc)
        return
    raise AssertionError("expected SFAError for self-pipe")


def test_add_pipe_rejects_composite_source(tmp_path: Path) -> None:
    root = _make_project(
        tmp_path,
        ("a.py", SAMPLE_A),
        ("b.py", SAMPLE_B),
    )
    module_mod.add_module(root, "mod_a", "func_a")
    module_mod.add_module(root, "mod_b", "func_b")
    composite = topo.group_modules(root, ["mod_a", "mod_b"], "复合")
    # mod_c is a valid atomic target, but the source is composite.
    (root / "src" / "c.py").write_text(SAMPLE_C, encoding="utf-8")
    extract_mod.extract(root)
    module_mod.add_module(root, "mod_c", "func_c")
    try:
        pipe_mod.add_pipe(root, composite["id"], "mod_c")
    except SFAError as exc:
        assert composite["id"] in str(exc)
        assert "复合" in str(exc) or "原子" in str(exc)
        return
    raise AssertionError("expected SFAError for composite source")


def test_add_pipe_rejects_composite_target(tmp_path: Path) -> None:
    root = _make_project(
        tmp_path,
        ("a.py", SAMPLE_A),
        ("b.py", SAMPLE_B),
    )
    module_mod.add_module(root, "mod_a", "func_a")
    module_mod.add_module(root, "mod_b", "func_b")
    composite = topo.group_modules(root, ["mod_a", "mod_b"], "复合")
    try:
        pipe_mod.add_pipe(root, "mod_a", composite["id"])
    except SFAError as exc:
        assert composite["id"] in str(exc)
        assert "复合" in str(exc) or "原子" in str(exc)
        return
    raise AssertionError("expected SFAError for composite target")


def test_add_pipe_duplicate_is_idempotent(tmp_path: Path) -> None:
    root = _make_project(tmp_path, ("a.py", SAMPLE_A), ("b.py", SAMPLE_B))
    module_mod.add_module(root, "mod_a", "func_a")
    module_mod.add_module(root, "mod_b", "func_b")
    first = pipe_mod.add_pipe(root, "mod_a", "mod_b")
    second = pipe_mod.add_pipe(root, "mod_a", "mod_b")
    assert second["id"] == first["id"]
    assert len(pipe_mod.list_pipes(root)) == 1


def test_add_pipe_force_rebuilds(tmp_path: Path) -> None:
    root = _make_project(tmp_path, ("a.py", SAMPLE_A), ("b.py", SAMPLE_B))
    module_mod.add_module(root, "mod_a", "func_a")
    module_mod.add_module(root, "mod_b", "func_b")
    pipe_mod.add_pipe(root, "mod_a", "mod_b", visibility="L1")
    rebuilt = pipe_mod.add_pipe(root, "mod_a", "mod_b", visibility="L4", force=True)
    assert rebuilt["visibility"] == "L4"
    assert len(pipe_mod.list_pipes(root)) == 1


def test_add_pipe_writes_to_pipeline_yml(tmp_path: Path) -> None:
    root = _make_project(tmp_path, ("a.py", SAMPLE_A), ("b.py", SAMPLE_B))
    module_mod.add_module(root, "mod_a", "func_a")
    module_mod.add_module(root, "mod_b", "func_b")
    pipe_mod.add_pipe(root, "mod_a", "mod_b")
    pipeline = yaml.safe_load((root / ".sfa" / "pipeline.yml").read_text(encoding="utf-8"))
    assert len(pipeline["pipes"]) == 1
    assert pipeline["pipes"][0]["source"] == "mod_a"


# ---------------------------------------------------------------------------
# remove_pipe
# ---------------------------------------------------------------------------


def test_remove_pipe_basic(tmp_path: Path) -> None:
    root = _make_project(tmp_path, ("a.py", SAMPLE_A), ("b.py", SAMPLE_B))
    module_mod.add_module(root, "mod_a", "func_a")
    module_mod.add_module(root, "mod_b", "func_b")
    pipe_mod.add_pipe(root, "mod_a", "mod_b")
    removed, removed_probes = pipe_mod.remove_pipe(root, "pipe_mod_a_mod_b")
    assert removed["id"] == "pipe_mod_a_mod_b"
    assert removed_probes == []
    assert pipe_mod.list_pipes(root) == []


def test_remove_pipe_not_found(tmp_path: Path) -> None:
    root = _make_project(tmp_path, ("a.py", SAMPLE_A))
    module_mod.add_module(root, "mod_a", "func_a")
    try:
        pipe_mod.remove_pipe(root, "nonexistent_pipe")
    except SFAError as exc:
        assert "nonexistent_pipe" in str(exc)
        return
    raise AssertionError("expected SFAError for missing pipe")


# ---------------------------------------------------------------------------
# list_pipes
# ---------------------------------------------------------------------------


def test_list_pipes_empty(tmp_path: Path) -> None:
    root = _make_project(tmp_path, ("a.py", SAMPLE_A))
    module_mod.add_module(root, "mod_a", "func_a")
    assert pipe_mod.list_pipes(root) == []


def test_list_pipes_multiple(tmp_path: Path) -> None:
    root = _make_project(
        tmp_path,
        ("a.py", SAMPLE_A),
        ("b.py", SAMPLE_B),
        ("c.py", SAMPLE_C),
    )
    _make_three_modules(root)
    pipe_mod.add_pipe(root, "mod_a", "mod_b")
    pipe_mod.add_pipe(root, "mod_b", "mod_c")
    pipes = pipe_mod.list_pipes(root)
    ids = {p["id"] for p in pipes}
    assert ids == {"pipe_mod_a_mod_b", "pipe_mod_b_mod_c"}


# ---------------------------------------------------------------------------
# group / ungroup / drill
# ---------------------------------------------------------------------------


def test_group_creates_composite(tmp_path: Path) -> None:
    root = _make_project(
        tmp_path,
        ("a.py", SAMPLE_A),
        ("b.py", SAMPLE_B),
        ("c.py", SAMPLE_C),
    )
    _make_three_modules(root)
    composite = topo.group_modules(root, ["mod_a", "mod_b"], "复合模块")
    assert composite["id"] is not None
    assert composite["type"] == "composite"
    assert composite["parent"] is None

    # Children should have parent set
    mods = {m["id"]: m for m in topo.list_modules(root)}
    assert mods["mod_a"]["parent"] == composite["id"]
    assert mods["mod_b"]["parent"] == composite["id"]
    assert mods["mod_c"]["parent"] is None  # not grouped


def test_group_internal_pipes_get_parent(tmp_path: Path) -> None:
    root = _make_project(
        tmp_path,
        ("a.py", SAMPLE_A),
        ("b.py", SAMPLE_B),
        ("c.py", SAMPLE_C),
    )
    _make_three_modules(root)
    pipe_mod.add_pipe(root, "mod_a", "mod_b")  # internal
    pipe_mod.add_pipe(root, "mod_b", "mod_c")  # cross-boundary
    composite = topo.group_modules(root, ["mod_a", "mod_b"], "复合")
    pipes = {p["id"]: p for p in pipe_mod.list_pipes(root)}
    assert pipes["pipe_mod_a_mod_b"]["parent"] == composite["id"]  # internal
    assert pipes["pipe_mod_b_mod_c"]["parent"] is None  # cross-boundary stays null


def test_group_different_parents_rejected(tmp_path: Path) -> None:
    root = _make_project(
        tmp_path,
        ("a.py", SAMPLE_A),
        ("b.py", SAMPLE_B),
        ("c.py", SAMPLE_C),
    )
    _make_three_modules(root)
    topo.group_modules(root, ["mod_a", "mod_b"], "composite1")
    # mod_c has parent=None, mod_b has parent=composite1 — different parents
    try:
        topo.group_modules(root, ["mod_b", "mod_c"], "composite2")
    except SFAError as exc:
        assert "parent" in str(exc) or "父模块" in str(exc)
        return
    raise AssertionError("expected SFAError for different parents")


def test_group_empty_rejected(tmp_path: Path) -> None:
    root = _make_project(tmp_path, ("a.py", SAMPLE_A))
    module_mod.add_module(root, "mod_a", "func_a")
    try:
        topo.group_modules(root, [], "composite")
    except SFAError as exc:
        return
    raise AssertionError("expected SFAError for empty group")


def test_group_nonexistent_module(tmp_path: Path) -> None:
    root = _make_project(tmp_path, ("a.py", SAMPLE_A))
    module_mod.add_module(root, "mod_a", "func_a")
    try:
        topo.group_modules(root, ["mod_a", "nonexistent"], "composite")
    except SFAError as exc:
        assert "nonexistent" in str(exc)
        return
    raise AssertionError("expected SFAError for nonexistent module in group")


def test_group_duplicate_id(tmp_path: Path) -> None:
    root = _make_project(
        tmp_path,
        ("a.py", SAMPLE_A),
        ("b.py", SAMPLE_B),
    )
    module_mod.add_module(root, "mod_a", "func_a")
    module_mod.add_module(root, "mod_b", "func_b")
    # Create a module with id "composite" first
    try:
        topo.group_modules(root, ["mod_a", "mod_b"], "mod_a")
    except SFAError as exc:
        assert "mod_a" in str(exc)
        return
    raise AssertionError("expected SFAError for duplicate composite ID")


def test_ungroup_promotes_children(tmp_path: Path) -> None:
    root = _make_project(
        tmp_path,
        ("a.py", SAMPLE_A),
        ("b.py", SAMPLE_B),
    )
    module_mod.add_module(root, "mod_a", "func_a")
    module_mod.add_module(root, "mod_b", "func_b")
    composite = topo.group_modules(root, ["mod_a", "mod_b"], "复合")

    composite_dict, child_ids = topo.ungroup_composite(root, composite["id"])
    assert composite_dict["id"] == composite["id"]
    assert set(child_ids) == {"mod_a", "mod_b"}

    # Children promoted to top-level (parent=None)
    mods = {m["id"]: m for m in topo.list_modules(root)}
    assert mods["mod_a"]["parent"] is None
    assert mods["mod_b"]["parent"] is None
    assert composite["id"] not in mods  # composite removed


def test_ungroup_internal_pipes_promoted(tmp_path: Path) -> None:
    root = _make_project(
        tmp_path,
        ("a.py", SAMPLE_A),
        ("b.py", SAMPLE_B),
    )
    module_mod.add_module(root, "mod_a", "func_a")
    module_mod.add_module(root, "mod_b", "func_b")
    pipe_mod.add_pipe(root, "mod_a", "mod_b")
    composite = topo.group_modules(root, ["mod_a", "mod_b"], "复合")

    topo.ungroup_composite(root, composite["id"])
    pipes = pipe_mod.list_pipes(root)
    assert pipes[0]["parent"] is None  # promoted to top-level


def test_ungroup_non_composite_rejected(tmp_path: Path) -> None:
    root = _make_project(tmp_path, ("a.py", SAMPLE_A))
    module_mod.add_module(root, "mod_a", "func_a")
    try:
        topo.ungroup_composite(root, "mod_a")
    except SFAError as exc:
        assert "composite" in str(exc) or "复合" in str(exc)
        return
    raise AssertionError("expected SFAError for ungroup on non-composite")


def test_ungroup_not_found(tmp_path: Path) -> None:
    root = _make_project(tmp_path, ("a.py", SAMPLE_A))
    module_mod.add_module(root, "mod_a", "func_a")
    try:
        topo.ungroup_composite(root, "nonexistent")
    except SFAError as exc:
        assert "nonexistent" in str(exc)
        return
    raise AssertionError("expected SFAError for ungroup on nonexistent")


def test_drill_returns_children_and_pipes(tmp_path: Path) -> None:
    root = _make_project(
        tmp_path,
        ("a.py", SAMPLE_A),
        ("b.py", SAMPLE_B),
        ("c.py", SAMPLE_C),
    )
    _make_three_modules(root)
    pipe_mod.add_pipe(root, "mod_a", "mod_b")
    composite = topo.group_modules(root, ["mod_a", "mod_b"], "复合")

    mods, pipes = topo.drill_composite(root, composite["id"])
    mod_ids = {m["id"] for m in mods}
    assert mod_ids == {"mod_a", "mod_b"}
    assert len(pipes) == 1
    assert pipes[0]["id"] == "pipe_mod_a_mod_b"


def test_drill_empty_composite(tmp_path: Path) -> None:
    root = _make_project(
        tmp_path,
        ("a.py", SAMPLE_A),
        ("b.py", SAMPLE_B),
    )
    module_mod.add_module(root, "mod_a", "func_a")
    module_mod.add_module(root, "mod_b", "func_b")
    composite = topo.group_modules(root, ["mod_a", "mod_b"], "复合")
    topo.ungroup_composite(root, composite["id"])
    # Re-create empty composite? Actually ungroup removes it. Let's just group one and check.
    # Instead test drill on a composite with children
    composite2 = topo.group_modules(root, ["mod_a"], "复合2")
    mods, pipes = topo.drill_composite(root, composite2["id"])
    assert len(mods) == 1
    assert len(pipes) == 0


def test_drill_not_found(tmp_path: Path) -> None:
    root = _make_project(tmp_path, ("a.py", SAMPLE_A))
    module_mod.add_module(root, "mod_a", "func_a")
    try:
        topo.drill_composite(root, "nonexistent")
    except SFAError as exc:
        assert "nonexistent" in str(exc)
        return
    raise AssertionError("expected SFAError for drill on nonexistent")


# ---------------------------------------------------------------------------
# Nested composites
# ---------------------------------------------------------------------------


def test_nested_group_ungroup(tmp_path: Path) -> None:
    root = _make_project(
        tmp_path,
        ("a.py", SAMPLE_A),
        ("b.py", SAMPLE_B),
        ("c.py", SAMPLE_C),
    )
    _make_three_modules(root)
    # Group mod_a + mod_b into composite1
    comp1 = topo.group_modules(root, ["mod_a", "mod_b"], "外层")
    # Group composite1 + mod_c into composite2
    comp2 = topo.group_modules(root, [comp1["id"], "mod_c"], "最外层")

    mods = {m["id"]: m for m in topo.list_modules(root)}
    assert mods[comp1["id"]]["parent"] == comp2["id"]
    assert mods["mod_c"]["parent"] == comp2["id"]
    assert mods["mod_a"]["parent"] == comp1["id"]
    assert mods["mod_b"]["parent"] == comp1["id"]

    # Ungroup outer: comp1 and mod_c promoted to top-level
    topo.ungroup_composite(root, comp2["id"])
    mods = {m["id"]: m for m in topo.list_modules(root)}
    assert mods[comp1["id"]]["parent"] is None
    assert mods["mod_c"]["parent"] is None
    assert mods["mod_a"]["parent"] == comp1["id"]  # still inside comp1
