"""Resolve UI scope once against explicit available targets; no ambient selection."""

from .semantic_models import ScopeSelector, TargetRef
from .override_keys import lexical_owner, target_owners


def same_logical_target(graph, focus, target):
    if focus.logical_key != target.logical_key:
        return False
    if focus.snapshot_id and focus.snapshot_id != target.snapshot_id:
        return False
    blocks = {block.id: block for block in graph.blocks}
    if focus.kind == "function" and target.kind == "function" and focus.object_id:
        known = {block.source_object_id for block in graph.blocks}
        if focus.object_id in known:
            return focus.object_id == target.object_id
        choices = [block for block in graph.blocks if block.logical_key == focus.logical_key]
        if len(choices) > 1:
            raise ValueError("Saved function scope is ambiguous after source revision; bind it again")
        return len(choices) == 1

    if focus.object_id and target.object_id:
        left = lexical_owner(graph, focus, function_parent=True)
        right = lexical_owner(graph, target, function_parent=True)
        if left is not None and right is not None:
            return left == right
        if focus.kind == "data" and left is None:
            owners = target_owners(graph, target)
            if len(owners) > 1:
                raise ValueError("Saved data scope is ambiguous after source revision; bind it again")
            return len(owners) == 1 and right in owners
    return True


def selection_matches(graph, focus, target):
    if same_logical_target(graph, focus, target):
        return True
    if focus.kind not in ("function", "control", "file", "folder", "project", "stream"):
        return False
    blocks = {block.id: block for block in graph.blocks}
    ancestor = focus.block_id
    if ancestor not in blocks:
        choices = [block.id for block in graph.blocks if block.logical_key == focus.logical_key]
        if len(choices) > 1:
            raise ValueError("Saved block scope is ambiguous after source revision; bind it again")
        ancestor = choices[0] if choices else None
    if not ancestor:
        return False
    block, seen = target.block_id, set()
    while block in blocks and block not in seen:
        if block == ancestor:
            return True
        seen.add(block)
        block = blocks[block].parent_id
    return False


def source_targets(analysis):
    targets = [
        TargetRef(
            kind="function" if obj.kind in ("function", "class") else "data",
            logical_key=obj.logical_key or f"{obj.path}::{obj.scope}::{obj.name}",
            object_id=obj.id,
            block_id=obj.block_id or None,
            analysis_id=analysis.id,
        )
        for obj in analysis.objects
    ]
    for block in analysis.graph.blocks:
        if block.kind in ("condition", "loop", "try", "with", "file"):
            targets.append(
                TargetRef(
                    kind="file" if block.kind == "file" else "control",
                    logical_key=block.logical_key,
                    block_id=block.id,
                    analysis_id=analysis.id,
                )
            )
    for node in analysis.graph.nodes:
        if node.kind not in ("data", "parameter") and node.source:
            matches = [
                obj
                for obj in analysis.objects
                if obj.kind == "assignment"
                and obj.line == node.source.line
                and obj.column == node.source.column
            ]
            targets.append(
                TargetRef(
                    kind="operation",
                    logical_key=node.logical_key,
                    object_id=matches[0].id if len(matches) == 1 else None,
                    block_id=node.block_id,
                    analysis_id=analysis.id,
                )
            )
    return targets


def resolve_scope(
    graph, selector: ScopeSelector, available: list[TargetRef]
) -> list[TargetRef]:
    parents = {block.id: block.parent_id for block in graph.blocks}
    known_blocks = set(parents)

    def inside(block, ancestor):
        while block is not None:
            if block == ancestor:
                return True
            block = parents.get(block)
        return False

    block_id = selector.block_id
    if selector.mode == "block" and block_id not in known_blocks:
        keys = {
            ref.logical_key for ref in selector.targets
            if ref.kind in ("function", "control", "file", "folder", "project", "stream")
        }
        choices = [block.id for block in graph.blocks if block.logical_key in keys]
        if len(choices) > 1:
            raise ValueError("Saved block scope is ambiguous after source revision; bind it again")
        if not choices:
            raise ValueError("Scope block does not belong to this analysis")
        block_id = choices[0]
    selected = selector.targets
    available_keys = {(target.kind, target.logical_key) for target in available}
    if selector.mode == "selection" and any(
        (target.kind, target.logical_key) not in available_keys
        or target.snapshot_id is not None
        and not any(
            item.kind == target.kind
            and item.logical_key == target.logical_key
            and item.snapshot_id == target.snapshot_id
            for item in available
        )
        for target in selected
    ):
        raise ValueError("Selected target is unavailable in this analysis or run")
    resolved, seen = [], set()
    for target in available:
        include = (
            selector.mode == "project"
            or selector.mode == "block"
            and inside(target.block_id, block_id)
        )
        if selector.mode == "selection":
            include = any(
                selection_matches(graph, focus, target)
                for focus in selected
            )
        identity = (
            target.kind,
            target.logical_key,
            target.snapshot_id or target.object_id or target.block_id,
        )
        if (
            include
            and target.logical_key not in selector.excluded_keys
            and identity not in seen
        ):
            seen.add(identity)
            resolved.append(target.model_copy(deep=True))
    return resolved
