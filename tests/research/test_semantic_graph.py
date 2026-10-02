from pathlib import Path

from contract_driven_ai_flow.research.workbench.analysis import analyze_source


def analyze(tmp_path, text):
    path = tmp_path / 'experiment.py'
    path.write_text(text, encoding='utf-8')
    return analyze_source(path)


def test_same_line_bindings_have_distinct_identity_and_exact_source(tmp_path):
    doc = analyze(tmp_path, 'x = 1; x = 2\ny = x\n')
    xs = [obj for obj in doc.objects if obj.name == 'x']
    assert len({obj.id for obj in xs}) == 2
    assert xs[0].code == 'x = 1'
    assert xs[1].code == 'x = 2'
    assert xs[0].logical_key == xs[1].logical_key
    y = next(obj for obj in doc.objects if obj.name == 'y')
    assert [edge.source for edge in doc.relations if edge.target == y.id] == [xs[1].id]


def test_future_local_assignment_does_not_read_global(tmp_path):
    doc = analyze(tmp_path, 'x = 9\ndef f():\n    y = x\n    x = 2\n    return y\n')
    global_x = next(obj for obj in doc.objects if obj.name == 'x' and obj.scope == '<module>')
    y = next(obj for obj in doc.objects if obj.name == 'y')
    assert not any(edge.source == global_x.id and edge.target == y.id for edge in doc.relations)
    assert any(item.code == 'unbound_local' for item in doc.graph.coverage)


def test_conditional_merge_preserves_both_possible_definitions(tmp_path):
    doc = analyze(tmp_path, 'flag = True\nif flag:\n    x = 1\nelse:\n    x = 2\ny = x\n')
    xs = {obj.id for obj in doc.objects if obj.name == 'x'}
    y = next(obj for obj in doc.objects if obj.name == 'y')
    assert {edge.source for edge in doc.relations if edge.target == y.id} == xs
    graph = doc.graph
    assert any(block.kind == 'condition' for block in graph.blocks)
    merge = next(node for node in graph.nodes if node.kind == 'merge' and node.label == 'x')
    assert len([edge for edge in graph.edges if edge.target == merge.id and edge.kind == 'merge']) == 2
    assert {edge.branch for edge in graph.edges if edge.kind == 'control'} >= {'true', 'false'}


def test_loops_and_function_call_have_explicit_ports_and_boundaries(tmp_path):
    doc = analyze(tmp_path, 'def f(x):\n    total = 0\n    for item in x:\n        if item > 0:\n            total += item\n    return total\ny = f([1, 2])\n')
    graph = doc.graph
    kinds = {edge.kind for edge in graph.edges}
    assert {'data', 'control', 'call', 'argument', 'return', 'backedge', 'contains'} <= kinds
    assert {'file', 'function', 'condition', 'loop'} <= {block.kind for block in graph.blocks}
    identities = {node.id for node in graph.nodes} | {block.id for block in graph.blocks}
    assert all(edge.source in identities and edge.target in identities for edge in graph.edges)
    assert len(identities) == len(graph.nodes) + len(graph.blocks)
    assert any(port.name == 'item' for node in graph.nodes for port in node.ports)
    assert all(edge.provenance == 'inferred' for edge in graph.edges)
    # Presentation containment/control/call edges must not become AI source read authorization.
    source_ids = {obj.id for obj in doc.objects}
    assert all(edge.source in source_ids and edge.target in source_ids for edge in doc.relations)


def test_nested_shadowing_dynamic_calls_and_unsupported_control_disclosed(tmp_path):
    doc = analyze(tmp_path, 'x = 1\ndef f(x):\n    def inner(x):\n        return x\n    return inner(x)\nasync def a():\n    if x:\n        return x\nunknown = external(x)\n')
    graph = doc.graph
    assert any(item.code == 'dynamic_call' for item in graph.coverage)
    assert any(item.code == 'async_control' and item.runtime == 'unsupported' for item in graph.coverage)
    keys = [obj.logical_key for obj in doc.objects if obj.name == 'x']
    assert len(set(keys)) == 3
    assert all(obj.block_id for obj in doc.objects)


def test_graph_projection_collapse_preserves_edges_and_stream_overlap(tmp_path):
    doc = analyze(tmp_path, 'def f(x):\n    y = x + 1\n    return y\na = 2\nb = f(a)\n')
    from contract_driven_ai_flow.research.workbench.semantics import project_graph, MemberBlockProvider
    function = next(block for block in doc.graph.blocks if block.kind == 'function')
    view = project_graph(doc.graph, collapsed={function.id})
    ids = {node.id for node in view.nodes} | {block.id for block in view.blocks}
    assert all(edge.source in ids and edge.target in ids for edge in view.edges)
    original = {edge.id for edge in doc.graph.edges if edge.kind != 'contains'}
    assert original == {ref for edge in view.edges for ref in edge.original_ids}
    provider = MemberBlockProvider()
    first = provider.provide('stream:a', 'A', doc.graph, [function.id])
    second = provider.provide('stream:b', 'B', doc.graph, [function.id])
    assert first.members == second.members == [function.id]
    assert first.parent_id is None and first.kind == 'stream'


def test_scope_freezes_all_members_and_deduplicates_parent_child_selection(tmp_path):
    from contract_driven_ai_flow.research.workbench.semantic_models import ScopeSelector, TargetRef
    from contract_driven_ai_flow.research.workbench.scopes import resolve_scope, source_targets
    doc = analyze(tmp_path, 'global_x = 1\ndef f(x):\n    y = x + 1\n    return y\n')
    available = source_targets(doc)
    function = next(target for target in available if target.kind == 'function')
    y = next(target for target in available if target.logical_key.endswith('::y'))
    selector = ScopeSelector(mode='selection', targets=[function, y, y])
    resolved = resolve_scope(doc.graph, selector, available)
    assert len({target.logical_key for target in resolved}) == len(resolved)
    assert {target.logical_key for target in resolved} == {target.logical_key for target in available if target.block_id == function.block_id}
    selector.targets.clear()
    assert y in resolved


def test_decorated_function_objects_remain_mapped_to_function_plate(tmp_path):
    doc = analyze(tmp_path, 'def decor(f):\n    return f\n@decor\ndef f(x):\n    return x\n')
    obj = next(obj for obj in doc.objects if obj.name == 'f' and obj.kind == 'function')
    block = next(block for block in doc.graph.blocks if block.label == 'f')
    assert block.source_object_id == obj.id
    assert obj.block_id == block.id
def test_folder_provider_contract_references_file_blocks_without_claiming_cross_file_parsing(tmp_path):
    from contract_driven_ai_flow.research.workbench.analysis import analyze_source
    from contract_driven_ai_flow.research.workbench.semantics import StructuralBlockProvider
    script = tmp_path / 'analysis.py'
    script.write_text('X=1\n')
    graph = analyze_source(script).graph
    original = graph.model_dump()
    folder = StructuralBlockProvider('folder').provide('folder:lab','Lab',graph,graph.roots)
    assert folder.kind == 'folder' and folder.members == graph.roots
    assert folder.runtime_coverage == 'unsupported'
    assert graph.model_dump() == original
