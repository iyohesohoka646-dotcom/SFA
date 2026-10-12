from pathlib import Path
import shutil
import pytest
from contract_driven_ai_flow.research.projects.service import ProjectService


def test_regular_python_binding_forms(tmp_path):
    root = tmp_path/'lab'; root.mkdir()
    (root/'compute.py').write_text('def scale(v):\n    return v * 2\n', encoding='utf-8')
    (root/'main.py').write_text('from compute import scale\nX: int = 2\nX += 1\nY = scale(X)\n', encoding='utf-8')
    service = ProjectService(tmp_path/'host')
    project = service.open(root); service.index(project.id)
    main = next(u for u in service.files(project.id).items if u.relative_path == 'main.py')
    assert main.status == 'parsed', main.diagnostics
    graph = service.graph(project.id).graph
    assert any(edge.kind == 'call' for edge in graph.edges)


def test_existing_project_copy_does_not_retarget_registry(tmp_path):
    root = tmp_path/'first'; root.mkdir(); (root/'main.py').write_text('X = 1\n')
    service = ProjectService(tmp_path/'host'); project = service.open(root); service.index(project.id)
    clone = tmp_path/'copy'; shutil.copytree(root, clone)
    try:
        copied = service.open(clone)
        assert copied.id != project.id
    except ValueError:
        pass
    assert Path(service.project(project.id).root) == root


def test_absolute_import_inside_package(tmp_path):
    root = tmp_path/'lab'; (root/'pkg').mkdir(parents=True)
    (root/'pkg/__init__.py').write_text('')
    (root/'compute.py').write_text('def scale(v):\n    return v * 2\n')
    (root/'pkg/main.py').write_text('from compute import scale\nY = scale(2)\n')
    service = ProjectService(tmp_path/'host'); project = service.open(root); service.index(project.id)
    graph = service.graph(project.id).graph
    assert any(edge.kind == 'call' for edge in graph.edges)


def test_large_graph_obeys_total_visible_budget(tmp_path):
    root = tmp_path/'lab'; root.mkdir()
    for number in range(70):
        (root/f'module_{number:03}.py').write_text(f'X = {number}\n')
    service = ProjectService(tmp_path/'host'); project = service.open(root); service.index(project.id)
    sliced = service.graph(project.id, limit=20)
    assert len(sliced.graph.nodes) + len(sliced.graph.blocks) <= 20
    assert sliced.omitted_count > 0


def test_same_named_argument_uses_lexical_scope(tmp_path):
    root = tmp_path/'lab'; root.mkdir()
    (root/'compute.py').write_text('def scale(v):\n    return v * 2\n')
    (root/'main.py').write_text('from compute import scale\nX = 1\ndef f():\n    X = 9\n    return X\nY = scale(X)\n')
    service = ProjectService(tmp_path/'host'); project = service.open(root); service.index(project.id)
    graph = service.graph(project.id).graph
    nodes = {node.id: node for node in graph.nodes}
    sources = [nodes[e.source] for e in graph.edges if e.kind == 'argument' and e.source in nodes]
    assert sources
    assert all(node.source.line == 2 for node in sources), [(n.label, n.source.line) for n in sources]


def test_folder_slice_retains_real_members(tmp_path):
    root = tmp_path/'lab'; (root/'pkg').mkdir(parents=True)
    (root/'pkg/a.py').write_text('X=1\n')
    (root/'pkg/b.py').write_text('Y=2\n')
    service = ProjectService(tmp_path/'host'); project=service.open(root);service.index(project.id)
    graph=service.graph(project.id,scope_id='pkg').graph
    assert len([block for block in graph.blocks if block.kind=='file']) == 2
    assert {node.label for node in graph.nodes if node.kind=='data'} >= {'X','Y'}
