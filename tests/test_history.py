"""Tests for history version storage."""
from __future__ import annotations

from pathlib import Path

from sfa import extract as extract_mod
from sfa import history as history_mod
from sfa import init as init_mod
from sfa import module as module_mod
from sfa.config import SFAError

SAMPLE = '''def func_a(x: int) -> int:
    """Func A."""
    return x
'''


def _make_project(tmp_path: Path) -> Path:
    root = init_mod.init_project(tmp_path)
    src = root / "src"
    src.mkdir(exist_ok=True)
    (src / "a.py").write_text(SAMPLE, encoding="utf-8")
    extract_mod.extract(root)
    module_mod.add_module(root, "mod_a", "func_a")
    return root


def test_save_version_creates_file(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    path = history_mod.save_version(root, "mod_a", "old content\n")
    assert path.is_file()
    assert path.read_text(encoding="utf-8") == "old content\n"
    assert path.name.startswith("v")
    assert path.parent.name == "mod_a"


def test_list_versions_empty(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    assert history_mod.list_versions(root, "mod_a") == []


def test_list_versions_sorted(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    history_mod.save_version(root, "mod_a", "v1\n")
    history_mod.save_version(root, "mod_a", "v2\n")
    versions = history_mod.list_versions(root, "mod_a")
    assert len(versions) == 2
    assert versions[0]["filename"] < versions[1]["filename"]


def test_restore_version_writes_to_module_path(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    history_mod.save_version(root, "mod_a", "ORIGINAL CONTENT\n")
    versions = history_mod.list_versions(root, "mod_a")
    fname = versions[0]["filename"]
    # Mutate the current source first.
    (root / "src" / "a.py").write_text("CHANGED\n", encoding="utf-8")
    target = history_mod.restore_version(root, "mod_a", fname)
    assert target.is_file()
    assert target.read_text(encoding="utf-8") == "ORIGINAL CONTENT\n"


def test_restore_version_missing(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    try:
        history_mod.restore_version(root, "mod_a", "v99999999T999999999999.py")
    except SFAError as exc:
        assert "v99999999T999999999999" in str(exc) or "不存在" in str(exc)
        return
    raise AssertionError("expected SFAError for missing version")


def test_restore_version_rejects_traversal(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    for bad in ["../evil.py", "sub/dir/v.py", "..\\evil.py"]:
        try:
            history_mod.restore_version(root, "mod_a", bad)
        except SFAError:
            continue
        raise AssertionError(f"expected SFAError for traversal filename: {bad}")


def test_restore_version_rejects_bad_format(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    try:
        history_mod.restore_version(root, "mod_a", "not-a-version.txt")
    except SFAError as exc:
        assert "格式" in str(exc) or "文件名" in str(exc)
        return
    raise AssertionError("expected SFAError for malformed filename")


def test_restore_version_empty_name(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    try:
        history_mod.restore_version(root, "mod_a", "")
    except SFAError:
        return
    raise AssertionError("expected SFAError for empty filename")
