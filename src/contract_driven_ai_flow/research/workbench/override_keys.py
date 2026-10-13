"""Local probe overrides share logical variables only within one lexical owner."""

CONTAINER_KINDS = frozenset(('function', 'control', 'file', 'folder', 'project', 'stream'))
SCOPE_MARKER = '::scope:'


def lexical_owner(graph, ref, *, function_parent=False):
    blocks = {block.id: block for block in graph.blocks}
    block_id = ref.block_id
    if function_parent and ref.kind == 'function' and block_id in blocks:
        block_id = blocks[block_id].parent_id
    seen = set()
    while block_id in blocks and block_id not in seen:
        seen.add(block_id)
        block = blocks[block_id]
        if block.kind in ('function', 'class', 'file'):
            return block_id
        block_id = block.parent_id
    return None


def target_owners(graph, target):
    if target.kind in CONTAINER_KINDS:
        return {block.id for block in graph.blocks if block.logical_key == target.logical_key}
    return {
        owner for node in graph.nodes
        if node.logical_key == target.logical_key
        and ((node.kind in ('data', 'parameter')) == (target.kind == 'data'))
        if (owner := lexical_owner(graph, node)) is not None
    }


def target_override_key(target, graph):
    owners = target_owners(graph, target)
    if len(owners) <= 1:
        return target.logical_key
    owner = target.block_id if target.kind in CONTAINER_KINDS else lexical_owner(graph, target)
    if owner not in owners:
        raise ValueError('Local override scope is unavailable after source revision; bind it again')
    return f'{target.logical_key}{SCOPE_MARKER}{owner}'


def target_override(instance, target, graph):
    owners = target_owners(graph, target)
    prefix = target.logical_key + SCOPE_MARKER
    scoped = {key for key in instance.overrides if key.startswith(prefix)}
    valid = {prefix + owner for owner in owners}
    if scoped - valid or len(owners) > 1 and target.logical_key in instance.overrides:
        raise ValueError('Local override scope is ambiguous or changed after source revision; bind it again')
    key = target_override_key(target, graph)
    if key == target.logical_key and scoped:
        # A once-ambiguous owner cannot be remapped from a stale scope ID.
        return instance.overrides.get(next(iter(scoped)))
    return instance.overrides.get(key)
