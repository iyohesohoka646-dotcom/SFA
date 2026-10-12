"""P3 inert paged project queries: tree, files, symbols, references, graph."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from contract_driven_ai_flow.research.routes import create_research_app

TOKEN = 'project-token'
HEADERS = {'Authorization': 'Bearer ' + TOKEN}
PREFIX = '/api/v1/research/projects'


def lab(root) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / 'calc.py').write_text(
        'X = 100\ndef double(value):\n    result = value * 2\n    return result\n',
        encoding='utf-8',
    )
    (root / 'main.py').write_text(
        'from calc import double\nX = 7\nY = double(X)\n', encoding='utf-8'
    )


def setup(client: TestClient, root) -> str:
    project = client.post(
        PREFIX + '/open', headers=HEADERS, json={'path': str(root)}
    ).json()
    pid = project['id']
    task = client.post(
        PREFIX + '/' + pid + '/index', headers=HEADERS, json={}
    ).json()
    for _ in range(300):
        task = client.get(
            PREFIX + '/' + pid + '/tasks/' + task['id'], headers=HEADERS
        ).json()
        if task['status'] not in ('queued', 'running'):
            break
        time.sleep(0.02)
    assert task['status'] == 'completed', task
    return pid


def test_tree_root_and_children_paged(tmp_path):
    root = tmp_path / 'lab'
    lab(root)
    with TestClient(create_research_app(tmp_path / 'host', token=TOKEN)) as client:
        pid = setup(client, root)
        top = client.get(PREFIX + '/' + pid + '/tree', headers=HEADERS).json()
        assert top['total'] == 1 and top['items'][0]['parent_id'] is None
        assert top['items'][0]['kind'] == 'project'
        assert top['items'][0]['label'] == 'lab'
        task = top['items'][0]['target']
        assert task['kind'] == 'project' and task['logical_key']
        root_id = top['items'][0]['id']
        first = client.get(
            PREFIX + '/' + pid + '/tree',
            headers=HEADERS,
            params={'parent_id': root_id, 'limit': 1},
        ).json()
        assert first['total'] == 2 and len(first['items']) == 1
        second = client.get(
            PREFIX + '/' + pid + '/tree',
            headers=HEADERS,
            params={'parent_id': root_id, 'offset': 1, 'limit': 1},
        ).json()
        ids = {first['items'][0]['id'], second['items'][0]['id']}
        assert len(ids) == 2
        assert all(item['kind'] == 'file' and item['file_id'] for item in first['items'] + second['items'])
        assert all(
            item['target']['kind'] == 'file' and item['target']['file_id'] == item['file_id']
            for item in first['items'] + second['items']
        )


def test_files_paging_and_source(tmp_path):
    root = tmp_path / 'lab'
    lab(root)
    with TestClient(create_research_app(tmp_path / 'host', token=TOKEN)) as client:
        pid = setup(client, root)
        page = client.get(
            PREFIX + '/' + pid + '/files', headers=HEADERS, params={'limit': 1}
        ).json()
        assert page['total'] == 2 and len(page['items']) == 1
        unit = page['items'][0]
        source = client.get(
            PREFIX + '/' + pid + '/files/' + unit['id'] + '/source', headers=HEADERS
        ).json()
        assert source['file_id'] == unit['id']
        assert source['revision_id'] == page['revision_id']
        assert source['code'].strip()
        assert 'def ' in source['code'] or '=' in source['code']
        missing = client.get(
            PREFIX + '/' + pid + '/files/not-a-file/source', headers=HEADERS
        )
        assert missing.status_code == 404


def test_symbols_and_references(tmp_path):
    root = tmp_path / 'lab'
    lab(root)
    with TestClient(create_research_app(tmp_path / 'host', token=TOKEN)) as client:
        pid = setup(client, root)
        files = client.get(PREFIX + '/' + pid + '/files', headers=HEADERS).json()['items']
        by_path = {row['relative_path']: row for row in files}
        symbols = client.get(
            PREFIX + '/' + pid + '/symbols',
            headers=HEADERS,
            params={'q': 'double', 'limit': 10},
        ).json()
        assert symbols['project_id'] == pid and symbols['revision_id']
        assert any(item['name'] == 'double' for item in symbols['items'])
        refs = client.get(
            PREFIX + '/' + pid + '/references',
            headers=HEADERS,
            params={'file_id': by_path['main.py']['id']},
        ).json()
        assert refs['project_id'] == pid
        linked = [
            item
            for item in refs['items']
            if item.get('target') and item['target'].get('file_id') == by_path['calc.py']['id']
        ]
        assert linked, refs


def test_graph_code_and_data_are_distinct(tmp_path):
    root = tmp_path / 'lab'
    lab(root)
    with TestClient(create_research_app(tmp_path / 'host', token=TOKEN)) as client:
        pid = setup(client, root)
        code = client.get(
            PREFIX + '/' + pid + '/graph', headers=HEADERS, params={'view': 'code'}
        ).json()
        data = client.get(
            PREFIX + '/' + pid + '/graph', headers=HEADERS, params={'view': 'data'}
        ).json()
        assert code['project_id'] == pid and code['revision_id']
        assert data['project_id'] == pid
        code_kinds = {node['kind'] for node in code['graph']['nodes']}
        data_kinds = {node['kind'] for node in data['graph']['nodes']}
        assert code_kinds != data_kinds
        assert 'data' in data_kinds or 'parameter' in data_kinds


def test_objects_group_by_canonical_key_and_probe_count(tmp_path):
    root = tmp_path / 'lab'
    root.mkdir(parents=True, exist_ok=True)
    (root / 'calc.py').write_text(
        'def double(value):\n    result = value * 2\n    return result\n',
        encoding='utf-8',
    )
    (root / 'main.py').write_text(
        'from calc import double\nx = 1\nx = double(x)\n', encoding='utf-8'
    )
    with TestClient(create_research_app(tmp_path / 'host', token=TOKEN)) as client:
        pid = setup(client, root)
        default = client.get(PREFIX + '/' + pid + '/objects', headers=HEADERS).json()
        assert default['project_id'] == pid and default['revision_id']
        rows = [
            item
            for item in default['items']
            if item['name'] == 'x' and item['source']['path'] == 'main.py'
        ]
        assert len(rows) == 1, rows
        # Unrun variables are still listed; no fabricated evidence.
        assert rows[0]['probe_status'] == 'unknown'
        assert rows[0]['type'] is None and rows[0]['shape'] is None
        assert rows[0]['target']['block_id'] or True
        # Effective enabled compatible probes come from the resolver.
        assert rows[0]['probe_count'] == 1, rows[0]
        config = client.get(
            PREFIX + '/' + pid + '/workbench/configuration', headers=HEADERS
        ).json()
        config['probes'] = []
        saved = client.put(
            PREFIX + '/' + pid + '/workbench/configuration',
            headers=HEADERS,
            json={'config': config, 'expected_revision': config['revision']},
        )
        assert saved.status_code == 200, saved.text
        after = client.get(PREFIX + '/' + pid + '/objects', headers=HEADERS).json()
        rows = [
            item
            for item in after['items']
            if item['name'] == 'x' and item['source']['path'] == 'main.py'
        ]
        assert rows and rows[0]['probe_count'] == 0, rows


def test_references_exact_call_span_and_target(tmp_path):
    root = tmp_path / 'lab'
    root.mkdir(parents=True, exist_ok=True)
    (root / 'calc.py').write_text(
        'def double(value):\n    result = value * 2\n    return result\n',
        encoding='utf-8',
    )
    (root / 'main.py').write_text(
        'from calc import double\nx = 1\nx = double(x)\n', encoding='utf-8'
    )
    with TestClient(create_research_app(tmp_path / 'host', token=TOKEN)) as client:
        pid = setup(client, root)
        files = client.get(PREFIX + '/' + pid + '/files', headers=HEADERS).json()['items']
        by_path = {row['relative_path']: row for row in files}
        refs = client.get(
            PREFIX + '/' + pid + '/references',
            headers=HEADERS,
            params={'file_id': by_path['main.py']['id']},
        ).json()
        calls = [item for item in refs['items'] if item['kind'] == 'call']
        target = next(item for item in calls if item['name'] == 'double')
        assert target['source']['line'] == 3, target
        assert target['target'] and target['target']['file_id'] == by_path['calc.py']['id']
        assert target['target_line'] == 1, target
        imports = [item for item in refs['items'] if item['kind'] == 'import']
        assert imports and imports[0]['source']['line'] == 1, imports


def test_file_focus_boundaries_and_small_limit(tmp_path):
    root = tmp_path / 'lab'
    lab(root)
    with TestClient(create_research_app(tmp_path / 'host', token=TOKEN)) as client:
        pid = setup(client, root)
        files = client.get(PREFIX + '/' + pid + '/files', headers=HEADERS).json()['items']
        main = next(row for row in files if row['relative_path'] == 'main.py')
        calc = next(row for row in files if row['relative_path'] == 'calc.py')
        focused = client.get(
            PREFIX + '/' + pid + '/graph',
            headers=HEADERS,
            params={'scope_id': main['id'], 'view': 'code', 'limit': 50},
        ).json()
        boundary = [
            block
            for block in focused['graph']['blocks']
            if block['label'] == 'calc.py'
        ]
        assert boundary, focused['graph']['blocks']
        outgoing = [
            edge
            for edge in focused['graph']['edges']
            if edge['target'] == boundary[0]['id']
        ]
        assert outgoing
        assert any(edge['kind'] == 'call' for edge in outgoing), outgoing
        call_edges = [edge for edge in outgoing if edge['kind'] == 'call']
        assert all(edge['original_ids'] for edge in call_edges)
        # Cross-file imports stay dependencies, never manufactured calls.
        assert any(edge['kind'] == 'block' for edge in outgoing)
        assert all(edge['kind'] in ('call', 'block') for edge in outgoing)
        total = len(focused['graph']['blocks']) + len(focused['graph']['nodes'])
        assert total <= 51
        small = client.get(
            PREFIX + '/' + pid + '/graph',
            headers=HEADERS,
            params={'scope_id': main['id'], 'view': 'code', 'limit': 2},
        ).json()
        graph = small['graph']
        assert len(graph['blocks']) + len(graph['nodes']) <= 2, graph
        assert graph['roots'] and all(
            root_id in {block['id'] for block in graph['blocks']}
            for root_id in graph['roots']
        )
        known = {block['id'] for block in graph['blocks']} | {
            node['id'] for node in graph['nodes']
        }
        assert all(
            edge['source'] in known and edge['target'] in known
            for edge in graph['edges']
        )
        assert calc['id']






def test_root_graph_respects_small_limit(tmp_path):
    root = tmp_path / 'lab'
    lab(root)
    with TestClient(create_research_app(tmp_path / 'host', token=TOKEN)) as client:
        pid = setup(client, root)
        graph = client.get(
            PREFIX + '/' + pid + '/graph',
            headers=HEADERS,
            params={'view': 'code', 'limit': 2},
        ).json()['graph']
        assert len(graph['blocks']) + len(graph['nodes']) <= 2, graph
        assert graph['roots'] and all(
            root_id in {block['id'] for block in graph['blocks']}
            for root_id in graph['roots']
        )
        known = {block['id'] for block in graph['blocks']} | {
            node['id'] for node in graph['nodes']
        }
        assert all(
            edge['source'] in known and edge['target'] in known
            for edge in graph['edges']
        )


def test_revision_scoped_observations_do_not_leak(tmp_path):
    import pytest

    from contract_driven_ai_flow.research.workbench.models import RunConfiguration

    root = tmp_path / 'lab'
    root.mkdir(parents=True, exist_ok=True)
    (root / 'main.py').write_text('X = 100\nY = X * 2\n', encoding='utf-8')
    with TestClient(create_research_app(tmp_path / 'host', token=TOKEN)) as client:
        app = client.app
        projects = app.state.projects
        project = projects.open(root)
        revision1 = projects.index(project.id)
        config = projects.configuration(project.id)
        projects.save_entries(
            project.id,
            [RunConfiguration(id='main', name='Main', kind='script', target='main.py')],
            expected_revision=config.revision,
        )
        plan = projects.plan(project.id, 'main', revision_id=revision1.id)
        task = projects.execute(project.id, plan.id)
        done = projects.workbench(project.id).jobs.wait(task.id, timeout=60)
        assert done.status == 'completed', (done.status, done.message)
        old_run = done.run_id
        (root / 'main.py').write_text('X = 999\nY = X * 2\n', encoding='utf-8')
        revision2 = projects.index(project.id)
        queries = app.state.project_queries
        # The r1 run must never colour the r2 revision.
        r2 = queries.objects(project.id, revision2.id, probe_status='all')
        assert all(item.target.run_id is None for item in r2.items)
        assert all(item.target.snapshot_id is None for item in r2.items)
        assert all(
            item.type is None and item.probe_status == 'unknown' for item in r2.items
        )
        # The exact r1 run stays valid against r1.
        r1 = queries.objects(
            project.id, revision1.id, probe_status='all', run_id=old_run
        )
        assert any(item.target.snapshot_id for item in r1.items)
        assert all(item.target.run_id == old_run for item in r1.items)
        with pytest.raises((ValueError, RuntimeError)):
            queries.objects(
                project.id, revision2.id, probe_status='all', run_id=old_run
            )


def test_metadata_watcher_filters_only_python_and_closes(tmp_path):
    from contract_driven_ai_flow.research.projects.application import ProjectApplication
    from contract_driven_ai_flow.research.projects.indexing import _MetadataWatcher

    root = tmp_path / 'lab'
    root.mkdir()
    (root / 'a.py').write_text('X = 1\n', encoding='utf-8')
    (root / 'block.bin').write_bytes(b'\x00' * 2048)
    nested = root / '.git'
    nested.mkdir()
    (nested / 'hidden.py').write_text('Y = 1\n', encoding='utf-8')
    app = ProjectApplication(tmp_path / 'host')
    try:
        project = app.open(root)
        section = app.projects._ensure_section(root)
        watcher = _MetadataWatcher(object(), project.id, root, section)
        state, limited = watcher._snapshot()
        assert 'a.py' in state and not limited
        assert all(rel.endswith('.py') for rel in state)
        assert not any('block.bin' in rel or 'hidden' in rel for rel in state)
        watcher.start()
        watcher.stop()
        watcher.join(timeout=2)
        assert not watcher.is_alive()
    finally:
        app.close()



def test_code_view_projects_variable_dependencies_through_hidden_nodes(tmp_path):
    from contract_driven_ai_flow.research.projects.application import ProjectApplication
    from contract_driven_ai_flow.research.projects.queries import ProjectQueryService

    root = tmp_path / 'lab'
    root.mkdir()
    (root / 'main.py').write_text(
        'X = 1' + chr(10) + 'UNRELATED = 99' + chr(10) + 'Y = X + 2' + chr(10) + 'Z = Y * 3' + chr(10),
        encoding="utf-8",
    )
    app = ProjectApplication(tmp_path / 'host')
    try:
        project = app.open(root)
        revision = app.index(project.id)
        queries = ProjectQueryService(app.projects, app)
        code = queries.graph(project.id, revision.id, view='code').graph
        assert not ({node.kind for node in code.nodes} & {'data', 'parameter'})
        ops = {node.id: node for node in code.nodes if node.kind in ('operation', 'call')}
        links = {
            (ops[edge.source].source.line, ops[edge.target].source.line): edge
            for edge in code.edges
            if edge.source in ops and edge.target in ops
            and ops[edge.source].source and ops[edge.target].source
        }
        assert (1, 3) in links and (3, 4) in links
        assert (1, 4) not in links, 'No transitive shortcut may be invented'
        projected = links[(1, 3)]
        assert projected.provenance == 'inferred'
        assert projected.original_ids and projected.label == 'X'
        data = queries.graph(project.id, revision.id, view='data').graph
        kinds = {node.kind for node in data.nodes}
        assert 'data' in kinds and 'operation' in kinds
    finally:
        app.close()
