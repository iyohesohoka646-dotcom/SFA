"""Snapshot engine: persistence of per-module run data and run manifests.

Each run gets a directory ``.sfa/snapshots/{run_id}/`` containing:

* ``{module_id}.json`` — a single module's input/output/duration/status snapshot.
* ``run.json`` — the run manifest (overall status, execution order, per-module
  summary, input file used).

A pointer file ``.sfa/snapshots/.latest`` records the most recent run_id so
``sfa observe`` can resolve "the last run" without scanning the filesystem.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import SFAError, find_project_root, sfa_dir

SNAPSHOT_DIRNAME = "snapshots"
MANIFEST_FILENAME = "run.json"
LATEST_FILENAME = ".latest"


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def _snapshots_dir(root: Path) -> Path:
    return sfa_dir(root) / SNAPSHOT_DIRNAME


def _contained(base: Path, *parts: str) -> Path:
    """Join *parts* under *base* and return the resolved path.

    Rejects any component that escapes *base* (e.g. ``..`` or an absolute
    path) so user-influenced ``run_id`` / ``module_id`` values cannot traverse
    outside the snapshots directory.
    """
    base_resolved = base.resolve()
    target = base_resolved.joinpath(*parts)
    try:
        resolved = target.resolve()
    except (OSError, ValueError) as exc:
        raise SFAError(
            f"路径非法或越界，拒绝访问：{'/'.join(parts)}\n"
            "可操作建议：检查 run_id / module_id 是否包含非法字符（如 .. 或路径分隔符）。"
        ) from exc
    if not resolved.is_relative_to(base_resolved):
        raise SFAError(
            f"路径越界，拒绝访问：{'/'.join(parts)}\n"
            "可操作建议：检查 run_id / module_id 是否包含非法字符（如 .. 或路径分隔符）。"
        )
    return resolved


def _snapshot_path(root: Path, run_id: str, module_id: str) -> Path:
    return _contained(_snapshots_dir(root), run_id, f"{module_id}.json")


def _manifest_path(root: Path, run_id: str) -> Path:
    return _contained(_snapshots_dir(root), run_id, MANIFEST_FILENAME)


def _latest_path(root: Path) -> Path:
    return _snapshots_dir(root) / LATEST_FILENAME


# ---------------------------------------------------------------------------
# Serialization helper
# ---------------------------------------------------------------------------


def _dumps(obj: Any) -> str:
    """Serialize *obj* as indented JSON, falling back to ``str`` for values
    that are not natively JSON-serializable (keeps snapshot writes from
    crashing a run on exotic return values)."""
    return json.dumps(obj, ensure_ascii=False, indent=2, default=str)


# ---------------------------------------------------------------------------
# Per-module snapshots
# ---------------------------------------------------------------------------


def write_snapshot(
    root: Path, run_id: str, module_id: str, snapshot: dict[str, Any]
) -> Path:
    """Persist a single module snapshot. Returns the written path.

    The snapshots directory is created if missing.
    """
    root = find_project_root(root)
    out = _snapshot_path(root, run_id, module_id)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_dumps(snapshot), encoding="utf-8")
    return out


def read_snapshot(root: Path, run_id: str, module_id: str) -> dict[str, Any]:
    """Read a single module snapshot. Raises SFAError if absent."""
    root = find_project_root(root)
    path = _snapshot_path(root, run_id, module_id)
    if not path.is_file():
        raise SFAError(
            f"快照不存在：模块 {module_id} 在运行 {run_id} 中无快照。\n"
            f"相关文件：{path}\n"
            "可操作建议：执行 `sfa observe` 查看该运行的模块摘要，确认模块确实执行过。"
        )
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Run manifest
# ---------------------------------------------------------------------------


def write_run_manifest(
    root: Path, run_id: str, manifest: dict[str, Any]
) -> Path:
    """Persist the run manifest (run.json). Returns its path."""
    root = find_project_root(root)
    out = _manifest_path(root, run_id)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_dumps(manifest), encoding="utf-8")
    return out


def read_run_manifest(root: Path, run_id: str) -> dict[str, Any]:
    """Read the run manifest for *run_id*. Raises SFAError if absent."""
    root = find_project_root(root)
    path = _manifest_path(root, run_id)
    if not path.is_file():
        raise SFAError(
            f"运行记录不存在：{run_id}\n"
            f"相关文件：{path}\n"
            "可操作建议：执行 `sfa observe` 查看最近运行，或检查 run_id 是否正确。"
        )
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Latest-run pointer
# ---------------------------------------------------------------------------


def write_latest(root: Path, run_id: str) -> Path:
    """Record *run_id* as the most recent run."""
    root = find_project_root(root)
    path = _latest_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(run_id, encoding="utf-8")
    return path


def read_latest(root: Path) -> str | None:
    """Return the latest run_id, or None when no runs have been recorded."""
    root = find_project_root(root)
    path = _latest_path(root)
    if not path.is_file():
        return None
    run_id = path.read_text(encoding="utf-8").strip()
    return run_id or None


def latest_run(root: Path) -> dict[str, Any] | None:
    """Return the manifest of the latest run, or None if there are no runs."""
    root = find_project_root(root)
    run_id = read_latest(root)
    if run_id is None:
        return None
    path = _manifest_path(root, run_id)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def list_run_ids(root: Path) -> list[str]:
    """Return all run_id directory names under ``.sfa/snapshots/``, sorted
    by modification time (newest first). Hidden files (e.g. ``.latest``)
    and the manifest file are excluded."""
    root = find_project_root(root)
    base = _snapshots_dir(root)
    if not base.is_dir():
        return []
    runs: list[Path] = []
    for entry in base.iterdir():
        if entry.name.startswith(".") or not entry.is_dir():
            continue
        runs.append(entry)
    runs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [p.name for p in runs]


__all__ = [
    "write_snapshot",
    "read_snapshot",
    "write_run_manifest",
    "read_run_manifest",
    "write_latest",
    "read_latest",
    "latest_run",
    "list_run_ids",
    "MANIFEST_FILENAME",
    "LATEST_FILENAME",
]
