"""`sfa pipe add/remove/list` implementation.

Connects modules via data pipes in pipeline.yml, validating endpoint
existence and computing the pipe's parent (composite context).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from . import probe as probe_mod
from .config import SFAError, find_project_root, load_config
from . import topology

_VALID_VISIBILITY = {"L1", "L2", "L3", "L4"}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def add_pipe(
    root: Path,
    source: str,
    target: str,
    visibility: str | None = None,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Create a pipe from *source* to *target*.

    Validates that both modules exist, there is no duplicate, and
    source != target.  The pipe's *parent* is the common parent of
    the two endpoints (or ``None`` when they differ).

    Idempotent: if a pipe with the same source->target already exists it is
    returned unchanged unless ``force`` is set, in which case it is replaced
    in place (probes referencing the pipe ID are preserved).
    """
    root = find_project_root(root)
    cfg = load_config(root)
    vis = visibility or str(cfg.get("default_visibility", "L2"))
    if vis not in _VALID_VISIBILITY:
        raise SFAError(
            f"无效的可见性级别：{vis}\n"
            f"可操作建议：使用以下之一：{', '.join(sorted(_VALID_VISIBILITY))}。"
        )

    if source == target:
        raise SFAError(
            f"管道的源和目标不能相同：{source}\n"
            "可操作建议：选择两个不同的模块。"
        )

    src_mod = topology.find_module(root, source)
    tgt_mod = topology.find_module(root, target)

    _reject_composite_endpoint(source, src_mod)
    _reject_composite_endpoint(target, tgt_mod)

    existing = topology.find_pipe_by_endpoints(root, source, target)
    if existing is not None:
        if not force:
            return existing
        topology.remove_pipe(root, existing["id"])

    parent = src_mod.get("parent") if src_mod.get("parent") == tgt_mod.get("parent") else None

    pipe = {
        "id": topology.make_pipe_id(source, target),
        "source": source,
        "target": target,
        "visibility": vis,
        "parent": parent,
    }
    topology.add_pipe(root, pipe)
    return pipe


def remove_pipe(root: Path, pipe_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Remove pipe *pipe_id* from pipeline.yml and cascade-delete its probes.

    Returns ``(removed_pipe, removed_probes)``.
    """
    root = find_project_root(root)
    removed = topology.remove_pipe(root, pipe_id)
    removed_probes = probe_mod.remove_probes_for_pipe(root, pipe_id)
    return removed, removed_probes


def list_pipes(root: Path) -> list[dict[str, Any]]:
    """Return all pipes from pipeline.yml."""
    root = find_project_root(root)
    return topology.list_pipes(root)


# ---------------------------------------------------------------------------
# Composite-endpoint guard
# ---------------------------------------------------------------------------


def _reject_composite_endpoint(module_id: str, module: dict[str, Any]) -> None:
    """Pipes may only connect atomic modules; reject composite endpoints."""
    if module.get("type") == "composite":
        raise SFAError(
            f"管道的端点必须是原子模块：{module_id} 是复合模块。\n"
            "可操作建议：指定复合模块内部的具体子模块 ID（执行 `sfa drill <composite_id>` 查看子模块）。"
        )
