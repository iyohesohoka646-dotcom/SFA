"""End-to-end tests for `sfa generate` (mock provider, no API key)."""
from __future__ import annotations

import os
from pathlib import Path

import yaml

from sfa import extract as extract_mod
from sfa import generate as generate_mod
from sfa import history as history_mod
from sfa import init as init_mod
from sfa import module as module_mod
from sfa import pipe as pipe_mod
from sfa import topology as topo
from sfa.config import SFAError, load_config

SAMPLE_OWNED = '''"""Module with helper functions."""
from typing import List


def helper(x: int) -> int:
    """Double the input."""
    return x * 2


def preprocess(data: List[int], scale: float = 1.0) -> dict:
    """Preprocess raw data using helper."""
    return {"features": [helper(x) * scale for x in data]}


def unused_func(y: str) -> str:
    """This function is not called by preprocess."""
    return y
'''

SAMPLE_B = '''def func_b(y: str) -> str:
    """Func B."""
    return y
'''


def _make_project(tmp_path: Path, *sources: tuple[str, str]) -> Path:
    root = init_mod.init_project(tmp_path)
    src = root / "src"
    src.mkdir(exist_ok=True)
    for filename, content in sources:
        (src / filename).write_text(content, encoding="utf-8")
    extract_mod.extract(root)
    # Force mock provider for offline tests.
    cfg_path = root / "sfa.yml"
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    cfg.setdefault("ai", {})
    cfg["ai"]["provider"] = "mock"
    cfg_path.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return root


# ---------------------------------------------------------------------------
# prepare_generation
# ---------------------------------------------------------------------------


def test_prepare_generation_diff_only_touches_entry(tmp_path: Path) -> None:
    root = _make_project(tmp_path, ("owned.py", SAMPLE_OWNED))
    module_mod.add_module(root, "preprocess", "preprocess")
    plan = generate_mod.prepare_generation(root, "preprocess")

    assert plan["module"]["id"] == "preprocess"
    assert plan["diff"]  # mock produces a body change
    # The unused_func lines must be unchanged in new content.
    assert "def unused_func" in plan["new_content"]
    assert 'return y' in plan["new_content"]
    # helper must be unchanged.
    assert "def helper" in plan["new_content"]
    # The entry function must now be the mock stub.
    assert "NotImplementedError" in plan["new_content"]
    assert "SFA mock provider stub" in plan["new_content"]


def test_prepare_generation_does_not_write(tmp_path: Path) -> None:
    root = _make_project(tmp_path, ("owned.py", SAMPLE_OWNED))
    module_mod.add_module(root, "preprocess", "preprocess")
    before = (root / "src" / "owned.py").read_text(encoding="utf-8")
    generate_mod.prepare_generation(root, "preprocess")
    after = (root / "src" / "owned.py").read_text(encoding="utf-8")
    assert before == after


def test_prepare_generation_creates_no_history(tmp_path: Path) -> None:
    root = _make_project(tmp_path, ("owned.py", SAMPLE_OWNED))
    module_mod.add_module(root, "preprocess", "preprocess")
    generate_mod.prepare_generation(root, "preprocess")
    assert history_mod.list_versions(root, "preprocess") == []


def test_prepare_generation_composite_rejected(tmp_path: Path) -> None:
    root = _make_project(tmp_path, ("owned.py", SAMPLE_OWNED), ("b.py", SAMPLE_B))
    module_mod.add_module(root, "preprocess", "preprocess")
    module_mod.add_module(root, "mod_b", "func_b")
    composite = topo.group_modules(root, ["preprocess", "mod_b"], "复合")
    try:
        generate_mod.prepare_generation(root, composite["id"])
    except SFAError as exc:
        assert "atomic" in str(exc) or "复合" in str(exc)
        return
    raise AssertionError("expected SFAError for generate on composite")


def test_prepare_generation_source_missing(tmp_path: Path) -> None:
    root = _make_project(tmp_path, ("owned.py", SAMPLE_OWNED))
    module_mod.add_module(root, "preprocess", "preprocess")
    (root / "src" / "owned.py").unlink()
    try:
        generate_mod.prepare_generation(root, "preprocess")
    except SFAError as exc:
        assert "源文件" in str(exc) or "不存在" in str(exc)
        return
    raise AssertionError("expected SFAError for missing source file")


def test_prepare_generation_module_not_found(tmp_path: Path) -> None:
    root = _make_project(tmp_path, ("owned.py", SAMPLE_OWNED))
    try:
        generate_mod.prepare_generation(root, "nonexistent")
    except SFAError as exc:
        assert "nonexistent" in str(exc)
        return
    raise AssertionError("expected SFAError for nonexistent module")


def test_prepare_generation_with_l4_upstream(tmp_path: Path) -> None:
    root = _make_project(tmp_path, ("owned.py", SAMPLE_OWNED), ("b.py", SAMPLE_B))
    module_mod.add_module(root, "preprocess", "preprocess")
    module_mod.add_module(root, "mod_b", "func_b")
    pipe_mod.add_pipe(root, "preprocess", "mod_b", visibility="L4")
    plan = generate_mod.prepare_generation(root, "mod_b")
    assert plan["diff"]
    assert "func_b" in plan["new_content"]


# ---------------------------------------------------------------------------
# apply_generation
# ---------------------------------------------------------------------------


def test_apply_generation_writes_and_saves_history(tmp_path: Path) -> None:
    root = _make_project(tmp_path, ("owned.py", SAMPLE_OWNED))
    module_mod.add_module(root, "preprocess", "preprocess")
    old = (root / "src" / "owned.py").read_text(encoding="utf-8")
    plan = generate_mod.prepare_generation(root, "preprocess")

    history_path = generate_mod.apply_generation(root, plan)
    assert history_path.is_file()
    assert history_path.read_text(encoding="utf-8") == old
    new = (root / "src" / "owned.py").read_text(encoding="utf-8")
    assert new == plan["new_content"]
    assert "NotImplementedError" in new


def test_apply_then_rollback_restores_original(tmp_path: Path) -> None:
    root = _make_project(tmp_path, ("owned.py", SAMPLE_OWNED))
    module_mod.add_module(root, "preprocess", "preprocess")
    original = (root / "src" / "owned.py").read_text(encoding="utf-8")
    plan = generate_mod.prepare_generation(root, "preprocess")
    generate_mod.apply_generation(root, plan)

    versions = history_mod.list_versions(root, "preprocess")
    assert len(versions) == 1
    history_mod.restore_version(root, "preprocess", versions[0]["filename"])
    restored = (root / "src" / "owned.py").read_text(encoding="utf-8")
    assert restored == original


def test_apply_preserves_unrelated_lines(tmp_path: Path) -> None:
    root = _make_project(tmp_path, ("owned.py", SAMPLE_OWNED))
    module_mod.add_module(root, "preprocess", "preprocess")
    plan = generate_mod.prepare_generation(root, "preprocess")
    generate_mod.apply_generation(root, plan)
    content = (root / "src" / "owned.py").read_text(encoding="utf-8")
    # helper and unused_func bodies remain untouched.
    assert "return x * 2" in content
    assert "This function is not called by preprocess." in content
