"""Topology engine: CRUD for ``pipeline.yml`` modules, pipes and composites.

This is the data-access layer used by ``module.py`` and ``pipe.py``.
All validation of uniqueness / referential integrity lives here.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from .config import SFAError, sfa_dir
from .init import PIPELINE_YML

_MODULES_KEY = "modules"
_PIPES_KEY = "pipes"

_VALID_VISIBILITY = {"L1", "L2", "L3", "L4"}


# ---------------------------------------------------------------------------
# Load / save
# ---------------------------------------------------------------------------


def _pipeline_path(root: Path) -> Path:
    return sfa_dir(root) / PIPELINE_YML


def load_pipeline(root: Path) -> dict[str, Any]:
    """Load ``pipeline.yml``.  Returns ``{"modules": [...], "pipes": [...]}``.

    Handles a missing file or the legacy empty ``modules: []\\npipes: []``
    format gracefully.
    """
    path = _pipeline_path(root)
    if not path.is_file():
        raise SFAError(
            f"pipeline.yml 不存在：{path}\n"
            "可操作建议：请先执行 `sfa init` 初始化项目。"
        )
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise SFAError(
            f"pipeline.yml 格式错误（应为映射）：{path}\n"
            "可操作建议：检查文件内容，或执行 `sfa init --force` 重新生成。"
        )
    data.setdefault(_MODULES_KEY, [])
    data.setdefault(_PIPES_KEY, [])
    return data


def save_pipeline(root: Path, data: dict[str, Any]) -> None:
    """Write *data* back to ``pipeline.yml``."""
    path = _pipeline_path(root)
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Module CRUD
# ---------------------------------------------------------------------------


def list_modules(root: Path) -> list[dict[str, Any]]:
    return load_pipeline(root)[_MODULES_KEY]


def get_module(root: Path, module_id: str) -> dict[str, Any] | None:
    for m in list_modules(root):
        if m["id"] == module_id:
            return m
    return None


def find_module(root: Path, module_id: str) -> dict[str, Any]:
    mod = get_module(root, module_id)
    if mod is None:
        raise SFAError(
            f"模块不存在：{module_id}\n"
            f"相关文件：{_pipeline_path(root)}\n"
            "可操作建议：执行 `sfa module list` 查看现有模块。"
        )
    return mod


def add_module(root: Path, module: dict[str, Any]) -> None:
    """Append *module* to pipeline.yml.  Raises on duplicate ID."""
    data = load_pipeline(root)
    for existing in data[_MODULES_KEY]:
        if existing["id"] == module["id"]:
            raise SFAError(
                f"模块 ID 已存在：{module['id']}\n"
                f"相关文件：{_pipeline_path(root)}\n"
                "可操作建议：使用不同的名称，或先执行 `sfa module remove {id}` 删除现有模块。".format(
                    id=module["id"]
                )
            )
    data[_MODULES_KEY].append(module)
    save_pipeline(root, data)


def remove_module(root: Path, module_id: str) -> dict[str, Any]:
    """Remove module *module_id* from pipeline.yml (no pipe cascade)."""
    data = load_pipeline(root)
    for i, m in enumerate(data[_MODULES_KEY]):
        if m["id"] == module_id:
            data[_MODULES_KEY].pop(i)
            save_pipeline(root, data)
            return m
    raise SFAError(
        f"模块不存在：{module_id}\n"
        f"相关文件：{_pipeline_path(root)}\n"
        "可操作建议：执行 `sfa module list` 查看现有模块。"
    )


# ---------------------------------------------------------------------------
# Pipe CRUD
# ---------------------------------------------------------------------------


def list_pipes(root: Path) -> list[dict[str, Any]]:
    return load_pipeline(root)[_PIPES_KEY]


def get_pipe(root: Path, pipe_id: str) -> dict[str, Any] | None:
    for p in list_pipes(root):
        if p["id"] == pipe_id:
            return p
    return None


def find_pipe(root: Path, pipe_id: str) -> dict[str, Any]:
    pipe = get_pipe(root, pipe_id)
    if pipe is None:
        raise SFAError(
            f"管道不存在：{pipe_id}\n"
            f"相关文件：{_pipeline_path(root)}\n"
            "可操作建议：执行 `sfa pipe list` 查看现有管道。"
        )
    return pipe


def find_pipe_by_endpoints(root: Path, source: str, target: str) -> dict[str, Any] | None:
    for p in list_pipes(root):
        if p["source"] == source and p["target"] == target:
            return p
    return None


def add_pipe(root: Path, pipe: dict[str, Any]) -> None:
    """Append *pipe* to pipeline.yml.  Raises on duplicate source-target pair."""
    data = load_pipeline(root)
    for existing in data[_PIPES_KEY]:
        if existing["source"] == pipe["source"] and existing["target"] == pipe["target"]:
            raise SFAError(
                f"管道已存在：{existing['source']} -> {existing['target']}\n"
                f"相关文件：{_pipeline_path(root)}\n"
                "可操作建议：使用 `sfa pipe remove {id}` 删除后重试。".format(id=existing["id"])
            )
    data[_PIPES_KEY].append(pipe)
    save_pipeline(root, data)


def remove_pipe(root: Path, pipe_id: str) -> dict[str, Any]:
    data = load_pipeline(root)
    for i, p in enumerate(data[_PIPES_KEY]):
        if p["id"] == pipe_id:
            data[_PIPES_KEY].pop(i)
            save_pipeline(root, data)
            return p
    raise SFAError(
        f"管道不存在：{pipe_id}\n"
        f"相关文件：{_pipeline_path(root)}\n"
        "可操作建议：执行 `sfa pipe list` 查看现有管道。"
    )


def remove_pipes_referencing(root: Path, module_id: str) -> list[dict[str, Any]]:
    """Remove every pipe whose *source* or *target* is *module_id*.

    Returns the removed pipes (may be empty).
    """
    data = load_pipeline(root)
    removed: list[dict[str, Any]] = []
    remaining: list[dict[str, Any]] = []
    for p in data[_PIPES_KEY]:
        if p["source"] == module_id or p["target"] == module_id:
            removed.append(p)
        else:
            remaining.append(p)
    if removed:
        data[_PIPES_KEY] = remaining
        save_pipeline(root, data)
    return removed


# ---------------------------------------------------------------------------
# Composite operations
# ---------------------------------------------------------------------------


def group_modules(root: Path, child_ids: list[str], name: str) -> dict[str, Any]:
    """Pack *child_ids* into a new composite module.

    Returns the created composite dict.
    """
    if not child_ids:
        raise SFAError(
            "至少需要指定一个子模块。\n"
            "可操作建议：执行 `sfa group <module_id> [<module_id> ...] --name <名称>`。"
        )

    # De-duplicate while preserving order
    seen: set[str] = set()
    unique_ids: list[str] = []
    for cid in child_ids:
        if cid not in seen:
            seen.add(cid)
            unique_ids.append(cid)
    child_ids = unique_ids

    modules = list_modules(root)
    by_id = {m["id"]: m for m in modules}

    # All children must exist
    for cid in child_ids:
        if cid not in by_id:
            raise SFAError(
                f"模块不存在：{cid}\n"
                f"相关文件：{_pipeline_path(root)}\n"
                "可操作建议：执行 `sfa module list` 查看现有模块。"
            )

    # All children must share the same parent
    parents = {by_id[cid].get("parent") for cid in child_ids}
    if len(parents) > 1:
        raise SFAError(
            f"待打包的模块属于不同的父模块，无法打包：{child_ids}\n"
            f"父模块集合：{parents}\n"
            "可操作建议：仅打包同一层级（相同 parent）的模块。"
        )
    common_parent = parents.pop() if parents else None

    # Cannot group a composite into itself or its descendant
    composite_id = sanitize_id(name)
    _check_not_descendant(root, composite_id, child_ids, by_id)

    # Ensure composite ID is unique
    if composite_id in by_id:
        raise SFAError(
            f"模块 ID 已存在：{composite_id}\n"
            f"相关文件：{_pipeline_path(root)}\n"
            "可操作建议：使用不同的名称。"
        )

    composite = {
        "id": composite_id,
        "name": name,
        "type": "composite",
        "parent": common_parent,
    }

    data = load_pipeline(root)
    # Update children parents
    for m in data[_MODULES_KEY]:
        if m["id"] in child_ids:
            m["parent"] = composite_id
    # Internal pipes get the composite as parent
    child_set = set(child_ids)
    for p in data[_PIPES_KEY]:
        if p["source"] in child_set and p["target"] in child_set:
            p["parent"] = composite_id
    data[_MODULES_KEY].append(composite)
    save_pipeline(root, data)
    return composite


def ungroup_composite(root: Path, composite_id: str) -> tuple[dict[str, Any], list[str]]:
    """Remove composite *composite_id*, promoting its children to its parent.

    Returns ``(composite_dict, child_ids)``.
    """
    composite = find_module(root, composite_id)
    if composite.get("type") != "composite":
        raise SFAError(
            f"模块 {composite_id} 不是复合模块（type={composite.get('type')}）。\n"
            f"相关文件：{_pipeline_path(root)}\n"
            "可操作建议：`sfa ungroup` 仅适用于 type=composite 的模块。"
        )

    grandparent = composite.get("parent")
    data = load_pipeline(root)

    child_ids: list[str] = []
    for m in data[_MODULES_KEY]:
        if m.get("parent") == composite_id:
            m["parent"] = grandparent
            child_ids.append(m["id"])
    for p in data[_PIPES_KEY]:
        if p.get("parent") == composite_id:
            p["parent"] = grandparent

    # Remove the composite entry
    data[_MODULES_KEY] = [m for m in data[_MODULES_KEY] if m["id"] != composite_id]
    save_pipeline(root, data)
    return composite, child_ids


def drill_composite(root: Path, composite_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return ``(child_modules, internal_pipes)`` for *composite_id*."""
    find_module(root, composite_id)  # validates existence
    mods = [m for m in list_modules(root) if m.get("parent") == composite_id]
    pipes = [p for p in list_pipes(root) if p.get("parent") == composite_id]
    return mods, pipes


# ---------------------------------------------------------------------------
# ID sanitisation
# ---------------------------------------------------------------------------


def sanitize_id(name: str) -> str:
    """Convert a display *name* to a valid module ID slug.

    Unicode word characters (including CJK) are preserved; all other
    characters become ``_``. A leading digit is prefixed with ``m_``.
    """
    slug = re.sub(r"[^\w]+", "_", name, flags=re.UNICODE).strip("_").lower()
    if not slug:
        raise SFAError(
            f"无法从名称生成有效 ID：{name!r}\n"
            "可操作建议：名称至少包含一个字母、数字或 Unicode 文字字符。"
        )
    if slug[0].isdigit():
        slug = f"m_{slug}"
    return slug


def make_pipe_id(source: str, target: str) -> str:
    return f"pipe_{source}_{target}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _check_not_descendant(
    root: Path,
    composite_id: str,
    child_ids: list[str],
    by_id: dict[str, dict[str, Any]],
) -> None:
    """Ensure *composite_id* is not among *child_ids* or their descendants."""
    if composite_id in child_ids:
        raise SFAError(
            f"复合模块 ID {composite_id} 与待打包的子模块重复。\n"
            "可操作建议：使用不同的名称。"
        )
    # Walk up the parent chain of each child; if any ancestor equals composite_id, reject
    for cid in child_ids:
        current = by_id.get(cid)
        while current is not None and current.get("parent") is not None:
            if current["parent"] == composite_id:
                raise SFAError(
                    f"模块 {cid} 是 {composite_id} 的后代，不能打包进自身后代。\n"
                    "可操作建议：选择不形成循环的模块组合。"
                )
            current = by_id.get(current["parent"])
