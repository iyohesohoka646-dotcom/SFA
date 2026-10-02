"""Small durable records; bulk scientific evidence stays in ExperimentStore."""
from contextlib import contextmanager
import json
import sqlite3
from pathlib import Path

from ..agent.privacy import sanitize_json


class WorkbenchStore:
    kinds = {'analyses', 'plans', 'tasks', 'outputs', 'proposals', 'contexts', 'skills', 'artifacts', 'resources', 'invocations', 'semantics', 'templates', 'derived', 'settings'}

    def __init__(self, root: Path):
        self.state = root.resolve() / '.cdaf' / 'research'
        self.state.mkdir(parents=True, exist_ok=True)
        self.path = self.state / 'workbench.sqlite3'
        with self.connect() as conn:
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('CREATE TABLE IF NOT EXISTS records(kind TEXT, id TEXT, payload TEXT NOT NULL, created INTEGER DEFAULT (unixepoch()), PRIMARY KEY(kind,id))')

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def put(self, kind, key, value):
        if kind not in self.kinds:
            raise ValueError('Unknown workbench record kind')
        data = value.model_dump(mode='json') if hasattr(value, 'model_dump') else value
        data = sanitize_json(data, string_limit=131072 if kind == 'contexts' else 16384)
        payload = json.dumps(data, ensure_ascii=False, allow_nan=False)
        if len(payload.encode()) > 4 * 1024 * 1024:
            raise ValueError('Workbench record exceeds 4 MiB')
        with self.connect() as conn:
            conn.execute('INSERT INTO records(kind,id,payload) VALUES(?,?,?) ON CONFLICT(kind,id) DO UPDATE SET payload=excluded.payload', (kind, key, payload))
        return data

    def get(self, kind, key):
        with self.connect() as conn:
            row = conn.execute('SELECT payload FROM records WHERE kind=? AND id=?', (kind, key)).fetchone()
        if not row:
            raise KeyError(f'{kind} record not found')
        return json.loads(row['payload'])

    def list(self, kind, *, limit=100):
        with self.connect() as conn:
            rows = conn.execute('SELECT payload FROM records WHERE kind=? ORDER BY created DESC, rowid DESC LIMIT ?', (kind, min(max(int(limit), 1), 1000))).fetchall()
        return [json.loads(row['payload']) for row in rows]

    def recover(self):
        from .ownership import owner_alive
        with self.connect() as conn:
            rows = conn.execute("SELECT id,payload FROM records WHERE kind='tasks'").fetchall()
            for row in rows:
                task = json.loads(row['payload'])
                if task['status'] in ('queued', 'running') and not owner_alive(task.get('receipt', {}).get('_owner')):
                    task.update(status='interrupted', message='Service restarted before completion')
                    conn.execute("UPDATE records SET payload=? WHERE kind='tasks' AND id=?", (json.dumps(task), row['id']))
