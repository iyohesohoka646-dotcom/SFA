"""Resolve UI scope once against explicit available targets; no ambient selection."""

from .semantic_models import ScopeSelector, TargetRef


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

    if selector.mode == "block" and selector.block_id not in known_blocks:
        raise ValueError("Scope block does not belong to this analysis")
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
            and inside(target.block_id, selector.block_id)
        )
        if selector.mode == "selection":
            include = any(
                (
                    focus.logical_key == target.logical_key
                    and (
                        not focus.snapshot_id or focus.snapshot_id == target.snapshot_id
                    )
                )
                or focus.kind
                in ("function", "control", "file", "folder", "project", "stream")
                and focus.block_id
                and inside(target.block_id, focus.block_id)
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
