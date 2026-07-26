"""Tests for the AI agent layer: prompt assembly, scanning, range location."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from sfa import ai as ai_mod
from sfa import extract as extract_mod
from sfa import init as init_mod
from sfa import module as module_mod
from sfa import pipe as pipe_mod
from sfa import topology as topo
from sfa.config import load_config

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


# ---------------------------------------------------------------------------
# build_prompt
# ---------------------------------------------------------------------------


def test_build_prompt_no_upstream(tmp_path: Path) -> None:
    root = _make_project(tmp_path, ("owned.py", SAMPLE_OWNED))
    module_mod.add_module(root, "preprocess", "preprocess")
    mod = topo.find_module(root, "preprocess")
    cfg = load_config(root)
    system, user = ai_mod.build_prompt(root, mod, cfg)
    assert "目标模块契约" in user
    assert "def preprocess" in user
    assert "无上游管道" in user
    assert "allowed" in system.lower() or "只能使用" in system


def test_build_prompt_l1_upstream(tmp_path: Path) -> None:
    root = _make_project(tmp_path, ("owned.py", SAMPLE_OWNED), ("b.py", SAMPLE_B))
    module_mod.add_module(root, "preprocess", "preprocess")
    module_mod.add_module(root, "mod_b", "func_b")
    pipe_mod.add_pipe(root, "preprocess", "mod_b", visibility="L1")
    mod = topo.find_module(root, "mod_b")
    cfg = load_config(root)
    _, user = ai_mod.build_prompt(root, mod, cfg)
    assert "preprocess" in user
    assert "输出 Schema" in user
    # L1 should not include full source code
    assert "return x * 2" not in user


def test_build_prompt_l4_upstream_includes_source(tmp_path: Path) -> None:
    root = _make_project(tmp_path, ("owned.py", SAMPLE_OWNED), ("b.py", SAMPLE_B))
    module_mod.add_module(root, "preprocess", "preprocess")
    module_mod.add_module(root, "mod_b", "func_b")
    pipe_mod.add_pipe(root, "preprocess", "mod_b", visibility="L4")
    mod = topo.find_module(root, "mod_b")
    cfg = load_config(root)
    _, user = ai_mod.build_prompt(root, mod, cfg)
    assert "完整源代码" in user
    assert "def preprocess" in user
    assert "return" in user  # source body present


def test_build_prompt_l3_includes_function_list_not_source(tmp_path: Path) -> None:
    root = _make_project(tmp_path, ("owned.py", SAMPLE_OWNED), ("b.py", SAMPLE_B))
    module_mod.add_module(root, "preprocess", "preprocess")
    module_mod.add_module(root, "mod_b", "func_b")
    pipe_mod.add_pipe(root, "preprocess", "mod_b", visibility="L3")
    mod = topo.find_module(root, "mod_b")
    cfg = load_config(root)
    _, user = ai_mod.build_prompt(root, mod, cfg)
    assert "上游函数列表" in user
    assert "def preprocess" in user or "def helper" in user
    # Full source block should NOT be present at L3
    assert "完整源代码" not in user


def test_build_prompt_excludes_downstream(tmp_path: Path) -> None:
    # Chain A -> B -> C; generating B must include A but NOT C.
    root = _make_project(
        tmp_path,
        ("owned.py", SAMPLE_OWNED),
        ("b.py", SAMPLE_B),
        ("c.py", SAMPLE_C),
    )
    module_mod.add_module(root, "preprocess", "preprocess")
    module_mod.add_module(root, "mod_b", "func_b")
    module_mod.add_module(root, "mod_c", "func_c")
    pipe_mod.add_pipe(root, "preprocess", "mod_b")
    pipe_mod.add_pipe(root, "mod_b", "mod_c")
    mod = topo.find_module(root, "mod_b")
    cfg = load_config(root)
    _, user = ai_mod.build_prompt(root, mod, cfg)
    assert "preprocess" in user  # upstream
    assert "mod_c" not in user  # downstream excluded


def test_build_prompt_missing_contract(tmp_path: Path) -> None:
    root = _make_project(tmp_path, ("owned.py", SAMPLE_OWNED))
    module_mod.add_module(root, "preprocess", "preprocess")
    mod = topo.find_module(root, "preprocess")
    # Delete the contract file.
    (root / ".sfa" / "modules" / mod["id"] / "contract.json").unlink()
    cfg = load_config(root)
    try:
        ai_mod.build_prompt(root, mod, cfg)
    except SFAError as exc:
        assert "contract" in str(exc) or "契约" in str(exc)
        return
    raise AssertionError("expected SFAError for missing contract")


from sfa.config import SFAError  # noqa: E402


# ---------------------------------------------------------------------------
# extract_code_block
# ---------------------------------------------------------------------------


def test_extract_code_block_fenced() -> None:
    text = "here is code:\n```python\ndef f():\n    return 1\n```\ndone"
    assert ai_mod.extract_code_block(text) == "def f():\n    return 1\n"


def test_extract_code_block_no_fence() -> None:
    assert ai_mod.extract_code_block("def f():\n    return 1") == "def f():\n    return 1\n"


def test_extract_code_block_multiple_blocks_takes_first() -> None:
    text = "```python\ndef a():\n    pass\n```\n```python\ndef b():\n    pass\n```"
    assert ai_mod.extract_code_block(text) == "def a():\n    pass\n"


# ---------------------------------------------------------------------------
# scan_imports
# ---------------------------------------------------------------------------


def test_scan_imports_allowed() -> None:
    code = "import json\nfrom math import sqrt\n\ndef f():\n    return sqrt(4)"
    assert ai_mod.scan_imports(code, ["json", "math"]) == []


def test_scan_imports_violation() -> None:
    code = "import os\nimport json\n\ndef f():\n    pass"
    assert ai_mod.scan_imports(code, ["json"]) == ["os"]


def test_scan_imports_from_import() -> None:
    code = "from collections import OrderedDict\n\ndef f():\n    pass"
    assert ai_mod.scan_imports(code, ["json"]) == ["collections"]


def test_scan_imports_relative_skipped() -> None:
    code = "from . import foo\n\ndef f():\n    pass"
    assert ai_mod.scan_imports(code, []) == []


def test_scan_imports_dedupe() -> None:
    code = "import os\nimport os.path\n\ndef f():\n    pass"
    assert ai_mod.scan_imports(code, []) == ["os"]


def test_scan_imports_syntax_error_returns_empty() -> None:
    assert ai_mod.scan_imports("def f(:\n", []) == []


# ---------------------------------------------------------------------------
# detect_side_effects
# ---------------------------------------------------------------------------


def test_detect_side_effects_clean() -> None:
    assert ai_mod.detect_side_effects("def f():\n    return 1") == []


def test_detect_side_effects_os_environ() -> None:
    code = "def f():\n    import os\n    os.environ['X'] = '1'"
    warnings = ai_mod.detect_side_effects(code)
    assert any("os.environ" in w for w in warnings)


def test_detect_side_effects_exec() -> None:
    code = "def f():\n    exec('print(1)')"
    warnings = ai_mod.detect_side_effects(code)
    assert any("exec" in w for w in warnings)


def test_detect_side_effects_globals() -> None:
    code = "def f():\n    g = globals()"
    warnings = ai_mod.detect_side_effects(code)
    assert any("globals" in w for w in warnings)


def test_detect_side_effects_syntax_error_returns_empty() -> None:
    assert ai_mod.detect_side_effects("def f(:\n") == []


# ---------------------------------------------------------------------------
# locate_entry_range
# ---------------------------------------------------------------------------


def test_locate_entry_range(tmp_path: Path) -> None:
    root = _make_project(tmp_path, ("owned.py", SAMPLE_OWNED))
    module_mod.add_module(root, "preprocess", "preprocess")
    mod = topo.find_module(root, "preprocess")
    start, end = ai_mod.locate_entry_range(root, mod, "src")
    # preprocess is the 2nd function in the file (helper is 1st).
    assert start > 1
    assert end >= start


def test_locate_entry_range_file_missing(tmp_path: Path) -> None:
    root = _make_project(tmp_path, ("owned.py", SAMPLE_OWNED))
    module_mod.add_module(root, "preprocess", "preprocess")
    mod = topo.find_module(root, "preprocess")
    (root / mod["path"]).unlink()
    try:
        ai_mod.locate_entry_range(root, mod, "src")
    except SFAError as exc:
        assert "源文件" in str(exc) or "不存在" in str(exc)
        return
    raise AssertionError("expected SFAError for missing source file")


def test_locate_entry_range_entry_not_found(tmp_path: Path) -> None:
    root = _make_project(tmp_path, ("owned.py", SAMPLE_OWNED))
    module_mod.add_module(root, "preprocess", "preprocess")
    mod = topo.find_module(root, "preprocess")
    # Overwrite the file with content lacking the entry.
    (root / mod["path"]).write_text("def other():\n    pass\n", encoding="utf-8")
    try:
        ai_mod.locate_entry_range(root, mod, "src")
    except SFAError as exc:
        assert "preprocess" in str(exc) or "入口" in str(exc)
        return
    raise AssertionError("expected SFAError for entry not found")
