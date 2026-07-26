"""History version storage for generated module code.

Each accepted generation saves a snapshot of the *entire source file*
(before the diff was applied) to ``.sfa/history/{module_id}/v{ts}.py``.
Rollback restores a chosen snapshot over the module's current file.
"""
from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path

from .config import SFAError, find_project_root, sfa_dir
from .topology import find_module

_HISTORY_DIRNAME = "history"
_VERSION_RE = re.compile(r"^v\d{8}T\d{6}\d{6}(?:_\d+)?\.py$")


def _history_dir(root: Path, module_id: str) -> Path:
    return sfa_dir(root) / _HISTORY_DIRNAME / module_id


def save_version(root: Path, module_id: str, content: str) -> Path:
    """Persist *content* as a new timestamped version. Returns its path."""
    root = find_project_root(root)
    out_dir = _history_dir(root, module_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = _dt.datetime.now().strftime("%Y%m%dT%H%M%S%f")
    path = out_dir / f"v{ts}.py"
    # Guard against microsecond-clock collisions on coarse-resolution
    # platforms (e.g. Windows) by appending a numeric suffix.
    if path.exists():
        i = 2
        while True:
            candidate = out_dir / f"v{ts}_{i}.py"
            if not candidate.exists():
                path = candidate
                break
            i += 1
    path.write_text(content, encoding="utf-8")
    return path


def list_versions(root: Path, module_id: str) -> list[dict[str, object]]:
    """List saved versions for *module_id*, oldest first."""
    root = find_project_root(root)
    out_dir = _history_dir(root, module_id)
    if not out_dir.is_dir():
        return []
    versions: list[dict[str, object]] = []
    for entry in sorted(out_dir.iterdir()):
        if entry.is_file() and _VERSION_RE.match(entry.name):
            stat = entry.stat()
            versions.append(
                {
                    "filename": entry.name,
                    "path": str(entry),
                    "size": stat.st_size,
                    "mtime": stat.st_mtime,
                }
            )
    versions.sort(key=lambda v: str(v["filename"]))
    return versions


def restore_version(root: Path, module_id: str, filename: str) -> Path:
    """Restore *filename* over the module's current source file.

    *filename* must be a bare basename; path traversal is rejected.
    Returns the module source path that was overwritten.
    """
    root = find_project_root(root)
    safe = _safe_basename(filename)
    version_path = _history_dir(root, module_id) / safe
    if not version_path.is_file():
        raise SFAError(
            f"历史版本不存在：{safe}\n"
            f"相关模块：{module_id}\n"
            "可操作建议：执行 `sfa rollback <module>` 查看可用版本列表。"
        )
    content = version_path.read_text(encoding="utf-8")
    module = find_module(root, module_id)
    target = (root / module["path"]).resolve()
    if not target.parent.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def _safe_basename(filename: str) -> str:
    if not filename:
        raise SFAError("历史版本文件名为空。\n可操作建议：从 `sfa rollback` 列表中选择一个版本。")
    # Reject anything that looks like a path or traversal attempt.
    if "/" in filename or "\\" in filename or ".." in filename:
        raise SFAError(
            f"非法的历史版本文件名：{filename!r}\n"
            "可操作建议：仅使用 `sfa rollback` 列出的文件名（不含路径）。"
        )
    if not _VERSION_RE.match(filename):
        raise SFAError(
            f"历史版本文件名格式不符：{filename!r}\n"
            "可操作建议：仅使用 `sfa rollback` 列出的文件名。"
        )
    return filename


__all__ = ["save_version", "list_versions", "restore_version"]
