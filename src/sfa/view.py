"""Visualization layer for SFA: ``sfa list`` and ``sfa graph`` rendering.

Pure functions that turn pipeline.yml + the latest run into human-readable
ASCII tables and data-flow diagrams.  Kept free of CLI concerns so it can be
unit-tested directly and reused by the example bootstrap script.
"""
from __future__ import annotations

import json
import unicodedata
from pathlib import Path
from typing import Any

from . import snapshot as snap
from . import topology
from .config import SFAError, find_project_root

_STATUS_OK = "OK"
_STATUS_ERR = "ERR"
_STATUS_NONE = "--"
_DASH = "-"

FOLD_THRESHOLD = 15


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def one_line(value: object, width: int = 60) -> str:
    """Render *value* as a single-line JSON snippet truncated to *width*."""
    if value is None:
        return _DASH
    try:
        text = json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        text = str(value)
    if len(text) > width:
        return text[: width - 1] + "…"
    return text


def _display_width(text: str) -> int:
    """Terminal display width accounting for wide (CJK) characters."""
    total = 0
    for ch in text:
        if unicodedata.east_asian_width(ch) in ("W", "F"):
            total += 2
        else:
            total += 1
    return total


def _pad(text: str, width: int) -> str:
    """Left-align *text* in a field of *width* display cells."""
    pad = width - _display_width(text)
    return text + (" " * max(0, pad))


# ---------------------------------------------------------------------------
# Module list (sfa list)
# ---------------------------------------------------------------------------


def _status_for(module: dict[str, Any], manifest: dict[str, Any] | None) -> str:
    if module.get("type") == "composite":
        return _STATUS_NONE
    if manifest is None:
        return _STATUS_NONE
    for rec in manifest.get("modules", []):
        if rec.get("id") == module["id"]:
            return _STATUS_OK if rec.get("status") == "success" else _STATUS_ERR
    return _STATUS_NONE


def _io_for(
    root: Path,
    module: dict[str, Any],
    manifest: dict[str, Any] | None,
) -> tuple[str, str]:
    if module.get("type") == "composite" or manifest is None:
        return _DASH, _DASH
    run_id = manifest.get("run_id")
    for rec in manifest.get("modules", []):
        if rec.get("id") == module["id"]:
            try:
                data = snap.read_snapshot(root, run_id, module["id"])
            except SFAError:
                return _DASH, _DASH
            return one_line(data.get("input")), one_line(data.get("output"))
    return _DASH, _DASH


def render_module_list(root: Path) -> str:
    """Return the ``sfa list`` table as a string.

    Columns: ID, 名称, 类型, 状态灯, 输入(一行), 输出(一行), 耗时(ms).
    Status + I/O are sourced from the latest run manifest/snapshots; modules
    absent from the latest run (or composites) show ``--`` / ``-``.
    """
    root = find_project_root(root)
    modules = topology.list_modules(root)
    if not modules:
        return "（暂无模块）"

    manifest = snap.latest_run(root)

    headers = ("ID", "名称", "类型", "状态", "输入", "输出", "耗时ms")
    rows: list[list[str]] = []
    for m in modules:
        status = _status_for(m, manifest)
        inp, out = _io_for(root, m, manifest)
        dur = _DASH
        if manifest is not None and m.get("type") != "composite":
            for rec in manifest.get("modules", []):
                if rec.get("id") == m["id"]:
                    dur = str(rec.get("duration_ms", _DASH))
                    break
        mtype = "Composite" if m.get("type") == "composite" else "Atomic"
        rows.append([m["id"], m.get("name", m["id"]), mtype, status, inp, out, dur])

    cols = list(zip(headers, *rows))
    widths = [max(_display_width(str(c)) for c in col) for col in cols]

    lines: list[str] = []
    lines.append("  ".join(_pad(h, w) for h, w in zip(headers, widths)))
    lines.append("  ".join("-" * w for w in widths))
    for row in rows:
        lines.append("  ".join(_pad(str(c), w) for c, w in zip(row, widths)))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Graph (sfa graph)
# ---------------------------------------------------------------------------


def _by_id(modules: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {m["id"]: m for m in modules}


def _top_ancestor(module_id: str, by_id: dict[str, dict[str, Any]]) -> str:
    cur = by_id.get(module_id)
    while cur is not None and cur.get("parent") is not None:
        parent = by_id.get(cur["parent"])
        if parent is None:
            break
        cur = parent
    return cur["id"] if cur else module_id


def _node_label(module_id: str, by_id: dict[str, dict[str, Any]]) -> str:
    mod = by_id.get(module_id, {})
    name = mod.get("name", module_id)
    if mod.get("type") == "composite":
        return f"({name})"
    return f"[{name}]"


def _topo_order(ids: list[str], edges: list[tuple[str, str]]) -> list[str]:
    """Kahn topological sort over *ids*; ties break by declaration order."""
    rank = {mid: i for i, mid in enumerate(ids)}
    indeg = {mid: 0 for mid in ids}
    adj: dict[str, list[str]] = {mid: [] for mid in ids}
    for s, t in edges:
        if s in adj and t in indeg:
            adj[s].append(t)
            indeg[t] += 1
    available = sorted((mid for mid in ids if indeg[mid] == 0), key=lambda x: rank[x])
    order: list[str] = []
    while available:
        n = available.pop(0)
        order.append(n)
        for t in adj[n]:
            indeg[t] -= 1
            if indeg[t] == 0:
                available.append(t)
        available.sort(key=lambda x: rank[x])
    # Any remaining (cyclic) nodes appended in declaration order.
    for mid in ids:
        if mid not in order:
            order.append(mid)
    return order


def render_graph(
    root: Path,
    module_id: str | None = None,
    hops: int = 2,
    fold_threshold: int = FOLD_THRESHOLD,
) -> str:
    """Render the data-flow graph.

    *module_id* is None  -> full top-level graph (composites collapsed).
    *module_id* is set   -> 1-*hops* neighborhood around that module.
    """
    root = find_project_root(root)
    modules = topology.list_modules(root)
    pipes = topology.list_pipes(root)
    by_id = _by_id(modules)

    if not modules:
        return "（暂无模块）"

    if module_id is not None:
        return _render_neighborhood(root, module_id, hops, modules, pipes, by_id)
    return _render_full(modules, pipes, by_id, fold_threshold)


def _render_full(
    modules: list[dict[str, Any]],
    pipes: list[dict[str, Any]],
    by_id: dict[str, dict[str, Any]],
    fold_threshold: int,
) -> str:
    top_ids = [m["id"] for m in modules if m.get("parent") is None]

    if len(top_ids) > fold_threshold:
        return (
            "节点数超过阈值，已折叠为索引视图：\n\n"
            + render_module_list_via_data(modules, by_id)
        )

    edges: list[tuple[str, str]] = []
    seen_edges: set[tuple[str, str]] = set()
    for p in pipes:
        s = _top_ancestor(p["source"], by_id)
        t = _top_ancestor(p["target"], by_id)
        if s == t:
            continue  # internal to a composite
        if (s, t) in seen_edges:
            continue
        seen_edges.add((s, t))
        edges.append((s, t))

    order = _topo_order(top_ids, edges)
    lines: list[str] = []
    lines.append(f"顶层数据流图（{len(top_ids)} 模块，{len(edges)} 管道）：")
    lines.append("")

    for mid in order:
        label = _node_label(mid, by_id)
        outs = [t for (s, t) in edges if s == mid]
        if not outs:
            lines.append(f"  {label}")
        elif len(outs) == 1:
            lines.append(f"  {label} --> {_node_label(outs[0], by_id)}")
        else:
            lines.append(f"  {label}")
            for t in outs:
                lines.append(f"    --> {_node_label(t, by_id)}")
    return "\n".join(lines)


def render_module_list_via_data(
    modules: list[dict[str, Any]], by_id: dict[str, dict[str, Any]]
) -> str:
    """Lightweight list rendering used by the fold fallback (no run data)."""
    headers = ("ID", "名称", "类型")
    rows = []
    for m in modules:
        if m.get("parent") is not None:
            continue
        mtype = "Composite" if m.get("type") == "composite" else "Atomic"
        rows.append([m["id"], m.get("name", m["id"]), mtype])
    if not rows:
        return "（暂无模块）"
    cols = list(zip(headers, *rows))
    widths = [max(_display_width(str(c)) for c in col) for col in cols]
    lines = ["  ".join(_pad(h, w) for h, w in zip(headers, widths))]
    lines.append("  ".join("-" * w for w in widths))
    for row in rows:
        lines.append("  ".join(_pad(str(c), w) for c, w in zip(row, widths)))
    return "\n".join(lines)


def _render_neighborhood(
    root: Path,
    module_id: str,
    hops: int,
    modules: list[dict[str, Any]],
    pipes: list[dict[str, Any]],
    by_id: dict[str, dict[str, Any]],
) -> str:
    target = by_id.get(module_id)
    if target is None:
        raise SFAError(
            f"模块不存在：{module_id}\n"
            "可操作建议：执行 `sfa module list` 查看现有模块。"
        )

    # Composite with no direct pipe edges -> show its internal structure.
    if target.get("type") == "composite":
        return _render_composite_internal(target, modules, pipes, by_id)

    upstream_by_hop = _bfs(module_id, pipes, reverse=True, max_hops=hops)
    downstream_by_hop = _bfs(module_id, pipes, reverse=False, max_hops=hops)

    lines: list[str] = []
    lines.append(f"模块 {_node_label(module_id, by_id)} 的邻域（{hops} 跳）：")
    lines.append("")

    lines.append("上游：")
    if not upstream_by_hop:
        lines.append("  （无）")
    else:
        for hop in sorted(upstream_by_hop):
            for src, path in upstream_by_hop[hop]:
                flow = list(reversed(path))
                chain = " --> ".join(_node_label(n, by_id) for n in flow)
                lines.append(f"  {chain}")
    lines.append("")

    lines.append("下游：")
    if not downstream_by_hop:
        lines.append("  （无）")
    else:
        for hop in sorted(downstream_by_hop):
            for dst, path in downstream_by_hop[hop]:
                chain = " --> ".join(_node_label(n, by_id) for n in path)
                lines.append(f"  {chain}")
    return "\n".join(lines)


def _bfs(
    start: str,
    pipes: list[dict[str, Any]],
    *,
    reverse: bool,
    max_hops: int,
) -> dict[int, list[tuple[str, list[str]]]]:
    """Breadth-first walk along pipes up to *max_hops*.

    *reverse* True  -> walk upstream (follow edges target->source).
    *reverse* False -> walk downstream (follow edges source->target).

    Returns ``{hop: [(node, path)]}`` where *path* is the list of module IDs
    from *start* to *node* (inclusive), in traversal order. Excludes *start*.
    """
    adj: dict[str, list[str]] = {}
    for p in pipes:
        if reverse:
            s, t = p["target"], p["source"]
        else:
            s, t = p["source"], p["target"]
        adj.setdefault(s, []).append(t)

    result: dict[int, list[tuple[str, list[str]]]] = {}
    paths: dict[str, list[str]] = {start: [start]}
    frontier: list[str] = [start]
    for hop in range(1, max_hops + 1):
        next_frontier: list[str] = []
        for node in frontier:
            for nxt in adj.get(node, []):
                if nxt in paths:
                    continue
                path = paths[node] + [nxt]
                paths[nxt] = path
                next_frontier.append(nxt)
                result.setdefault(hop, []).append((nxt, path))
        frontier = next_frontier
        if not frontier:
            break
    return result


def _render_composite_internal(
    composite: dict[str, Any],
    modules: list[dict[str, Any]],
    pipes: list[dict[str, Any]],
    by_id: dict[str, dict[str, Any]],
) -> str:
    cid = composite["id"]
    children = [m for m in modules if m.get("parent") == cid]
    internal_pipes = [p for p in pipes if p.get("parent") == cid]

    lines: list[str] = []
    lines.append(f"复合模块 {_node_label(cid, by_id)} 的内部结构：")
    lines.append("")
    lines.append(f"子模块（{len(children)}）：")
    if children:
        for c in children:
            lines.append(f"  - {_node_label(c['id'], by_id)}")
    else:
        lines.append("  （无）")
    lines.append("")
    lines.append(f"内部管道（{len(internal_pipes)}）：")
    if internal_pipes:
        for p in internal_pipes:
            vis = p.get("visibility", "L2")
            lines.append(
                f"  {_node_label(p['source'], by_id)} --> {_node_label(p['target'], by_id)}"
                f"  ({vis})"
            )
    else:
        lines.append("  （无）")
    return "\n".join(lines)


__all__ = [
    "render_module_list",
    "render_graph",
    "one_line",
    "FOLD_THRESHOLD",
]
