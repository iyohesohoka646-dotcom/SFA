"""`sfa status` implementation: a compact project health/overview snapshot.

Pure rendering function reused by the CLI. Gathers config, extracted
elements, topology counts and the latest run into a single human-readable
block so users can assess a project at a glance without running several
commands.
"""
from __future__ import annotations

import json
import platform
from pathlib import Path
from typing import Any

from . import __version__
from . import probe as probe_mod
from . import snapshot as snap_mod
from . import topology as topo
from .config import SFAError, find_project_root, load_config, sfa_dir
from .extract import ELEMENTS_FILENAME


def _count_elements(root: Path) -> str:
    path = sfa_dir(root) / ELEMENTS_FILENAME
    if not path.is_file():
        return "未提取（运行 `sfa extract`）"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return "已提取但解析失败"
    return f"{len(doc.get('elements', []))} 个（已提取）"


def _safe_count(fn: Any, root: Path) -> int:
    try:
        return len(fn(root))
    except SFAError:
        return 0


def render_status(root: Path | None = None) -> str:
    """Return the ``sfa status`` overview as a string.

    Handles a missing/uninitialized project gracefully by returning a
    hint instead of raising.
    """
    try:
        root = find_project_root(root)
    except SFAError:
        return "未找到 SFA 项目根目录（缺少 .sfa/ 或 sfa.yml）。请先运行 `sfa init`。"

    lines: list[str] = [f"sfa {__version__}  (python {platform.python_version()})"]

    try:
        cfg = load_config(root)
    except SFAError as exc:
        lines.append(f"配置加载失败：{exc}")
        return "\n".join(lines)

    project = cfg.get("project", {}) or {}
    source_dir = str(cfg.get("source_dir", "src"))
    src_ok = (root / source_dir).is_dir()
    lines.append(f"项目：{project.get('name', '-')} ({project.get('language', '-')})")
    lines.append(
        f"source_dir：{source_dir}  [{'存在' if src_ok else '缺失'}]"
    )
    lines.append(
        f"默认可见性：{cfg.get('default_visibility', '-')}   "
        f"校验：{cfg.get('validation', '-')}"
    )
    lines.append(f"元素：{_count_elements(root)}")

    n_mod = _safe_count(topo.list_modules, root)
    n_pipe = _safe_count(topo.list_pipes, root)
    n_probe = _safe_count(probe_mod.list_probes, root)
    lines.append(f"模块：{n_mod}   管道：{n_pipe}   探针：{n_probe}")

    run_id = snap_mod.read_latest(root)
    if run_id is None:
        lines.append("最近运行：无运行记录")
    else:
        try:
            manifest = snap_mod.read_run_manifest(root, run_id)
            lines.append(
                f"最近运行：{run_id}  状态：{manifest.get('overall_status', '-')}"
            )
        except SFAError:
            lines.append(f"最近运行：{run_id}  状态：（清单缺失）")
    return "\n".join(lines)


__all__ = ["render_status"]
