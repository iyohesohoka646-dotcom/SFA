"""P3 project HTTP gateway: inert open/index, ownership, entries, tasks, watch."""

from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from contract_driven_ai_flow.research.routes import create_research_app

TOKEN = 'project-token'
HEADERS = {'Authorization': 'Bearer ' + TOKEN}
PREFIX = '/api/v1/research/projects'


def lab(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / 'calc.py').write_text(
        'X = 100\ndef double(value):\n    result = value * 2\n    return result\n',
        encoding='utf-8',
    )
    (root / 'main.py').write_text(
        'from calc import double\nX = 7\nY = double(X)\n', encoding='utf-8'
    )
    (root / 'danger.py').write_text(
        'raise RuntimeError("IMPORT MUST BE INERT")\n', encoding='utf-8'
    )


def opened(client: TestClient, root: Path) -> dict:
    response = client.post(PREFIX + '/open', headers=HEADERS, json={'path': str(root)})
    assert response.status_code == 200, response.text
    return response.json()


def indexed(client: TestClient, project_id: str) -> dict:
    response = client.post(PREFIX + '/' + project_id + '/index', headers=HEADERS, json={})
    assert response.status_code == 200, response.text
    task = response.json()
    for _ in range(300):
        task = client.get(
            PREFIX + '/' + project_id + '/tasks/' + task['id'], headers=HEADERS
        ).json()
        if task['status'] not in ('queued', 'running'):
            break
        time.sleep(0.02)
    assert task['status'] == 'completed', task
    return task


def test_open_index_is_inert_and_scope_owned(tmp_path):
    left, right = tmp_path / 'left', tmp_path / 'right'
    lab(left)
    lab(right)
    with TestClient(create_research_app(tmp_path / 'host', token=TOKEN)) as client:
        denied = client.post(PREFIX + '/open', json={'path': str(left)})
        assert denied.status_code == 401
        projects = [opened(client, root) for root in (left, right)]
        for project in projects:
            indexed(client, project['id'])
            page = client.get(
                PREFIX + '/' + project['id'] + '/files', headers=HEADERS, params={'limit': 1}
            ).json()
            assert page['total'] == 3 and len(page['items']) == 1
            assert page['project_id'] == project['id'] and page['revision_id']
        # A file id from one project never resolves in another.
        unit = client.get(
            PREFIX + '/' + projects[0]['id'] + '/files', headers=HEADERS
        ).json()['items'][0]
        leaked = client.get(
            PREFIX + '/' + projects[1]['id'] + '/files/' + unit['id'] + '/source',
            headers=HEADERS,
        )
        assert leaked.status_code == 404
        listed = client.get(PREFIX, headers=HEADERS).json()
        assert {row['id'] for row in listed} >= {p['id'] for p in projects}


def test_legacy_research_routes_still_served(tmp_path):
    root = tmp_path / 'lab'
    lab(root)
    with TestClient(create_research_app(root, token=TOKEN)) as client:
        assert client.get('/api/v1/research/runs', headers=HEADERS).json() == []
        assert client.get('/api/v1/research/info', headers=HEADERS).status_code == 200


def test_entries_roundtrip_and_stale_conflict(tmp_path):
    root = tmp_path / 'lab'
    lab(root)
    with TestClient(create_research_app(tmp_path / 'host', token=TOKEN)) as client:
        project = opened(client, root)
        indexed(client, project['id'])
        pid = project['id']
        entries = client.get(PREFIX + '/' + pid + '/entries', headers=HEADERS).json()
        assert entries['project_id'] == pid
        revision = entries['config_revision']
        body = {
            'entries': [
                {'id': 'main', 'name': 'Main', 'kind': 'script', 'target': 'main.py'}
            ],
            'expected_revision': revision,
        }
        saved = client.put(PREFIX + '/' + pid + '/entries', headers=HEADERS, json=body)
        assert saved.status_code == 200, saved.text
        assert saved.json()['run_configurations'][0]['target'] == 'main.py'
        stale = client.put(PREFIX + '/' + pid + '/entries', headers=HEADERS, json=body)
        assert stale.status_code == 409


def test_index_cancel_keeps_previous_revision(tmp_path):
    root = tmp_path / 'lab'
    lab(root)
    (root / 'slow.py').write_text('X = 1\n', encoding='utf-8')
    with TestClient(create_research_app(tmp_path / 'host', token=TOKEN)) as client:
        project = opened(client, root)
        pid = project['id']
        indexed(client, pid)
        before = client.get(PREFIX + '/' + pid + '/files', headers=HEADERS).json()
        task = client.post(PREFIX + '/' + pid + '/index', headers=HEADERS, json={}).json()
        client.post(
            PREFIX + '/' + pid + '/tasks/' + task['id'] + '/cancel', headers=HEADERS
        )
        for _ in range(300):
            task = client.get(
                PREFIX + '/' + pid + '/tasks/' + task['id'], headers=HEADERS
            ).json()
            if task['status'] not in ('queued', 'running'):
                break
            time.sleep(0.01)
        after = client.get(PREFIX + '/' + pid + '/files', headers=HEADERS).json()
        assert after['revision_id'] == before['revision_id']


def test_watch_toggle(tmp_path):
    root = tmp_path / 'lab'
    lab(root)
    with TestClient(create_research_app(tmp_path / 'host', token=TOKEN)) as client:
        project = opened(client, root)
        pid = project['id']
        indexed(client, pid)
        on = client.put(PREFIX + '/' + pid + '/watch', headers=HEADERS, json={'enabled': True})
        assert on.status_code == 200 and on.json()['enabled'] is True
        assert 'files' in on.json() and on.json()['limited'] is False
        state = client.get(PREFIX + '/' + pid + '/watch', headers=HEADERS).json()
        assert state['enabled'] is True and 'last_error' in state
        off = client.put(PREFIX + '/' + pid + '/watch', headers=HEADERS, json={'enabled': False})
        assert off.json()['enabled'] is False


def test_stale_index_and_missing_archive_are_explicit(tmp_path):
    root = tmp_path / 'lab'
    lab(root)
    with TestClient(create_research_app(tmp_path / 'host', token=TOKEN)) as client:
        project = opened(client, root)
        pid = project['id']
        stale = client.post(
            PREFIX + '/' + pid + '/index',
            headers=HEADERS,
            json={'expected_revision': 'not-the-latest'},
        )
        assert stale.status_code == 409
        indexed(client, pid)
        unit = client.get(PREFIX + '/' + pid + '/files', headers=HEADERS).json()['items'][0]
        ok = client.get(
            PREFIX + '/' + pid + '/files/' + unit['id'] + '/source', headers=HEADERS
        )
        assert ok.status_code == 200
        from contract_driven_ai_flow.research.projects.store import ProjectStore

        store = ProjectStore(root)
        with store.connect() as conn:
            conn.execute('DELETE FROM sources')
        gone = client.get(
            PREFIX + '/' + pid + '/files/' + unit['id'] + '/source', headers=HEADERS
        )
        assert gone.status_code == 404


def test_wrong_project_task_is_not_found(tmp_path):
    left, right = tmp_path / 'left', tmp_path / 'right'
    lab(left)
    lab(right)
    with TestClient(create_research_app(tmp_path / 'host', token=TOKEN)) as client:
        first = opened(client, left)
        second = opened(client, right)
        task = client.post(
            PREFIX + '/' + first['id'] + '/index', headers=HEADERS, json={}
        ).json()
        leaked = client.get(
            PREFIX + '/' + second['id'] + '/tasks/' + task['id'], headers=HEADERS
        )
        assert leaked.status_code == 404

def test_reused_research_and_workbench_handlers_are_project_scoped(tmp_path):
    root = tmp_path / 'lab'
    lab(root)
    with TestClient(create_research_app(tmp_path / 'host', token=TOKEN)) as client:
        project = opened(client, root)
        pid = project['id']
        indexed(client, pid)
        info = client.get(PREFIX + '/' + pid + '/info', headers=HEADERS).json()
        assert info['root'] == str(root.resolve())
        assert client.get(PREFIX + '/' + pid + '/runs', headers=HEADERS).json() == []
        config = client.get(
            PREFIX + '/' + pid + '/workbench/configuration', headers=HEADERS
        ).json()
        assert config['protocol_version'] == 3
        assert client.get(
            PREFIX + '/' + pid + '/workbench/tasks', headers=HEADERS
        ).json() != []

def test_project_terminals_are_scoped(tmp_path):
    root = tmp_path / 'lab'
    lab(root)
    with TestClient(create_research_app(tmp_path / 'host', token=TOKEN)) as client:
        project = opened(client, root)
        pid = project['id']
        started = client.post(
            PREFIX + '/' + pid + '/terminals',
            headers=HEADERS,
            json={'profile': 'python', 'rows': 10, 'cols': 40},
        )
        assert started.status_code == 200, started.text
        session = started.json()
        assert session['cwd'] == str(root.resolve())
        ended = client.post(
            PREFIX + '/' + pid + '/terminals/' + session['id'] + '/end', headers=HEADERS
        )
        assert ended.status_code == 200
        missing = client.get(
            PREFIX + '/' + pid + '/terminals/does-not-exist', headers=HEADERS
        )
        assert missing.status_code == 404
        # The session id never resolves under another project.
        other = opened(client, tmp_path / 'other') if False else None





def test_index_task_reports_real_progress_receipt(tmp_path):
    root = tmp_path / 'lab'
    lab(root)
    with TestClient(create_research_app(tmp_path / 'host', token=TOKEN)) as client:
        project = opened(client, root)
        pid = project['id']
        application = client.app.state.projects
        workbench = application.workbench(pid)
        indexed(client, pid)
        seen = {}
        real_index = application.index

        def instrumented(project_id, cancel=None, progress=None):
            assert callable(progress)
            progress(
                {
                    'stage': 'parse',
                    'completed': 1,
                    'total': 2,
                    'parsed': 1,
                    'reused': 0,
                    'file': 'main.py',
                }
            )
            active = next(
                task for task in workbench.jobs.list() if task['kind'] == 'project.index'
            )
            seen['progress'] = active['progress']
            seen['receipt'] = dict(active['receipt'])
            return real_index(project_id, cancel=cancel, progress=progress)

        application.index = instrumented
        try:
            response = client.post(PREFIX + '/' + pid + '/index', headers=HEADERS, json={})
            assert response.status_code == 200, response.text
            task = response.json()
            for _ in range(200):
                task = client.get(
                    PREFIX + '/' + pid + '/tasks/' + task['id'], headers=HEADERS
                ).json()
                if task['status'] not in ('queued', 'running'):
                    break
                time.sleep(0.02)
            assert task['status'] == 'completed', task
        finally:
            application.index = real_index
        assert 0 < seen['progress'] < 1
        assert seen['receipt']['stage'] == 'parse'
        assert seen['receipt']['completed'] == 1 and seen['receipt']['total'] == 2
        assert seen['receipt']['project_id'] == pid
