"""Tests for the snapshot engine (per-module snapshots, run manifest, .latest)."""
from __future__ import annotations

import json
from pathlib import Path

from sfa import init as init_mod
from sfa import snapshot as snap
from sfa.config import SFAError


def _root(tmp_path: Path) -> Path:
    return init_mod.init_project(tmp_path)


def test_write_and_read_snapshot(tmp_path: Path) -> None:
    root = _root(tmp_path)
    data = {
        "module": "mod_a",
        "run_id": "r1",
        "timestamp": "2026-07-22T00:00:00",
        "duration_ms": 12,
        "status": "success",
        "input": {"x": 1},
        "output": {"y": 2},
        "error": None,
        "contract_version_hash": "abc",
    }
    path = snap.write_snapshot(root, "r1", "mod_a", data)
    assert path.is_file()
    assert path.name == "mod_a.json"
    assert path.parent.name == "r1"
    got = snap.read_snapshot(root, "r1", "mod_a")
    assert got == data


def test_read_snapshot_missing_raises(tmp_path: Path) -> None:
    root = _root(tmp_path)
    try:
        snap.read_snapshot(root, "r1", "mod_a")
    except SFAError as exc:
        assert "mod_a" in str(exc)
        return
    raise AssertionError("expected SFAError for missing snapshot")


def test_write_and_read_run_manifest(tmp_path: Path) -> None:
    root = _root(tmp_path)
    manifest = {
        "run_id": "r1",
        "start_time": "t0",
        "end_time": "t1",
        "overall_status": "success",
        "execution_order": ["mod_a", "mod_b"],
        "modules": [
            {"id": "mod_a", "status": "success", "duration_ms": 1, "snapshot": "mod_a.json"},
        ],
        "input_file": None,
    }
    path = snap.write_run_manifest(root, "r1", manifest)
    assert path.name == "run.json"
    got = snap.read_run_manifest(root, "r1")
    assert got == manifest


def test_read_run_manifest_missing_raises(tmp_path: Path) -> None:
    root = _root(tmp_path)
    try:
        snap.read_run_manifest(root, "nope")
    except SFAError as exc:
        assert "nope" in str(exc)
        return
    raise AssertionError("expected SFAError for missing manifest")


def test_latest_pointer_roundtrip(tmp_path: Path) -> None:
    root = _root(tmp_path)
    assert snap.read_latest(root) is None
    snap.write_latest(root, "r1")
    assert snap.read_latest(root) == "r1"
    snap.write_latest(root, "r2")
    assert snap.read_latest(root) == "r2"


def test_latest_run_resolves_manifest(tmp_path: Path) -> None:
    root = _root(tmp_path)
    assert snap.latest_run(root) is None
    snap.write_run_manifest(root, "r1", {"run_id": "r1", "overall_status": "success"})
    snap.write_latest(root, "r1")
    got = snap.latest_run(root)
    assert got is not None
    assert got["run_id"] == "r1"


def test_list_run_ids_excludes_hidden(tmp_path: Path) -> None:
    root = _root(tmp_path)
    snap.write_snapshot(root, "r1", "mod_a", {"module": "mod_a"})
    snap.write_snapshot(root, "r2", "mod_a", {"module": "mod_a"})
    snap.write_latest(root, "r2")
    ids = snap.list_run_ids(root)
    assert set(ids) == {"r1", "r2"}
    assert ".latest" not in ids


def test_snapshot_serializes_non_json_objects(tmp_path: Path) -> None:
    root = _root(tmp_path)

    class Custom:
        def __str__(self) -> str:
            return "CUSTOM"

    data = {"module": "mod_a", "output": {"obj": Custom()}}
    path = snap.write_snapshot(root, "r1", "mod_a", data)
    loaded = json.loads(path.read_text(encoding="utf-8"))
    # The non-serializable object falls back to str().
    assert loaded["output"]["obj"] == "CUSTOM"


# ---------------------------------------------------------------------------
# Path containment (defence against hand-edited pipeline.yml / run_id)
# ---------------------------------------------------------------------------


def test_snapshot_rejects_traversal_module_id(tmp_path: Path) -> None:
    root = _root(tmp_path)
    try:
        snap.write_snapshot(root, "r1", "../../evil", {"module": "x"})
    except SFAError as exc:
        assert "越界" in str(exc)
        return
    raise AssertionError("expected SFAError for traversal module_id")


def test_snapshot_rejects_traversal_run_id(tmp_path: Path) -> None:
    root = _root(tmp_path)
    try:
        snap.read_run_manifest(root, "../../evil")
    except SFAError as exc:
        assert "越界" in str(exc)
        return
    raise AssertionError("expected SFAError for traversal run_id")


def test_snapshot_accepts_cjk_module_id(tmp_path: Path) -> None:
    # Containment must not break valid CJK module ids (which sanitize_id allows).
    root = _root(tmp_path)
    path = snap.write_snapshot(root, "r1", "预处理", {"module": "预处理"})
    assert path.name == "预处理.json"
    got = snap.read_snapshot(root, "r1", "预处理")
    assert got["module"] == "预处理"
