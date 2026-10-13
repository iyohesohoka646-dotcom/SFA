"""Authored Git files and SQLite execution evidence have separate lifecycles."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from .models import ChangeSet, ProjectSpec, RunEvent, canonical
from .paths import Conflict, FlowError, inside
from .privacy import sanitize, sanitize_project
from .privatefiles import restrict_private


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def file_digest(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def atomic_write(path: Path, content: str | bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temp.open("wb") as handle:
            handle.write(content.encode("utf-8") if isinstance(content, str) else content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def atomic_write_private(path: Path, content: str | bytes):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    restrict_private(path.parent)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with os.fdopen(os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as handle:
            restrict_private(temp)
            handle.write(content.encode("utf-8") if isinstance(content, str) else content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


class Store:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.state = inside(self.root, ".cdaf")
        self.state.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, started TEXT NOT NULL, finished TEXT,
                    status TEXT NOT NULL, quality TEXT NOT NULL, revision TEXT NOT NULL,
                    graph TEXT NOT NULL, environment TEXT NOT NULL, owner INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
                    body TEXT NOT NULL, FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE);
                CREATE INDEX IF NOT EXISTS events_run ON events(run_id,sequence);
                CREATE TABLE IF NOT EXISTS controls (run_id TEXT PRIMARY KEY, action TEXT NOT NULL);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.state / "runs.sqlite3", timeout=10)
        try:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA journal_mode=WAL")
            with db:
                yield db
        finally:
            db.close()

    @contextmanager
    def lock(self):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            yield db

    def load(self) -> ProjectSpec:
        with self.lock():
            self._recover_files()
            return self._load()

    def _load(self):
        try:
            value = yaml.safe_load((self.root / "flow.yaml").read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            mark = getattr(exc, "problem_mark", None)
            location = f" at line {mark.line + 1}, column {mark.column + 1}" if mark else ""
            raise FlowError(f"Invalid flow.yaml{location}; repair the project definition before opening it") from exc
        return ProjectSpec.model_validate(value)

    def _recover_files(self):
        journal_path = self.state / "transaction.json"
        if not journal_path.exists():
            return
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
        for item in journal["writes"]:
            path = inside(self.root, item["path"])
            current = file_digest(path.read_text(encoding="utf-8")) if path.exists() else None
            if current == file_digest(item["after"]):
                continue
            if current != item["before_digest"]:
                raise Conflict(f"Recovery conflict at {item['path']}; preserve transaction.json and review the external edit")
            atomic_write(path, item["after"])
        journal_path.unlink()

    def write_transaction(self, writes: dict[str, str]):
        """Caller owns lock. Durable intent permits idempotent roll-forward after interruption."""
        items = []
        for relative, content in writes.items():
            path = inside(self.root, relative)
            items.append({"path": relative, "before_digest": file_digest(path.read_text(encoding="utf-8")) if path.exists() else None, "after": content})
        atomic_write(self.state / "transaction.json", canonical({"writes": items, "created": now()}))
        self._recover_files()

    def project_writes(self, project: ProjectSpec) -> dict[str, str]:
        writes = {"flow.yaml": yaml.safe_dump(project.model_dump(mode="json"), allow_unicode=True, sort_keys=False)}
        for module in project.modules:
            writes[f"flow/contracts/{module.id}.{module.contract.revision[:12]}.json"] = json.dumps(module.contract.model_dump(), ensure_ascii=False, indent=2)
        return writes

    def save(self, project: ProjectSpec, expected_revision: str | None):
        with self.lock():
            self._recover_files()
            current = self._load().revision if (self.root / "flow.yaml").exists() else None
            if current != expected_revision:
                raise Conflict("Project changed; reload and revalidate the proposal")
            self.write_transaction(self.project_writes(project))
        return project

    def views(self):
        path = self.root / "flow/views.json"
        value = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"positions": {}, "collapsed": [], "theme": "dark"}
        return {"revision": file_digest(canonical(value)), "view": value}

    def save_views(self, view: dict, expected_revision: str):
        with self.lock():
            if self.views()["revision"] != expected_revision:
                raise Conflict("View changed; reload before saving layout")
            atomic_write(self.root / "flow/views.json", canonical(view))
        return self.views()

    def changes(self) -> list[ChangeSet]:
        return sorted([ChangeSet.model_validate_json(p.read_text(encoding="utf-8")) for p in (self.root / "flow/changes").glob("*.json")], key=lambda c: c.created, reverse=True)

    def change(self, change_id: str):
        path = inside(self.root, f"flow/changes/{change_id}.json")
        if not path.is_file():
            raise FlowError(f"Unknown change {change_id}")
        return ChangeSet.model_validate_json(path.read_text(encoding="utf-8"))

    def write_change(self, change: ChangeSet):
        atomic_write(inside(self.root, f"flow/changes/{change.id}.json"), change.model_dump_json(indent=2))

    def create_run(self, project: ProjectSpec, environment: dict, run_id: str | None = None, *, status="running") -> str:
        run_id = run_id or uuid.uuid4().hex
        safe_graph = sanitize_project(project)
        with self.lock() as db:
            existing = db.execute("SELECT status,revision FROM runs WHERE id=?", (run_id,)).fetchone()
            if existing:
                if existing["status"] != "queued" or existing["revision"] != project.revision or status != "running":
                    raise Conflict("Run reservation changed or was already activated")
                db.execute("UPDATE runs SET status='running',environment=? WHERE id=?", (canonical(environment), run_id))
            else:
                db.execute("INSERT INTO runs VALUES (?,?,NULL,?,'pending',?,?,?,?)", (run_id, now(), status, project.revision, canonical(safe_graph), canonical(environment), os.getpid()))
        return run_id

    def event(self, event: RunEvent, sensitive_fields: list[str]) -> RunEvent:
        # Structured data has already passed capture policy; sanitize narrative errors too.
        event = event.model_copy(update={"data": sanitize(event.data, sensitive_fields)})
        with self.connect() as db:
            cursor = db.execute("INSERT INTO events(run_id,body) VALUES (?,?)", (event.run_id, event.model_dump_json()))
            event.sequence = cursor.lastrowid
        return event

    def events(self, run_id: str, after: int = 0, limit: int = 10000) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT sequence,body FROM events WHERE run_id=? AND sequence>? ORDER BY sequence LIMIT ?", (run_id, after, min(limit, 10000))).fetchall()
        return [{**json.loads(row["body"]), "sequence": row["sequence"]} for row in rows]

    def all_events(self, run_id: str) -> list[dict]:
        result, cursor = [], 0
        while True:
            batch = self.events(run_id, cursor)
            result.extend(batch)
            if len(batch) < 10000:
                return result
            cursor = batch[-1]["sequence"]

    def runs(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT id,started,finished,status,quality,revision FROM runs ORDER BY started DESC LIMIT 200")]

    def run(self, run_id: str):
        with self.connect() as db:
            row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise FlowError(f"Unknown run {run_id}")
        value = dict(row)
        for key in ("graph", "environment"):
            value[key] = json.loads(value[key])
        return value

    def finish(self, run_id: str, status: str, quality: str):
        with self.connect() as db:
            db.execute("UPDATE runs SET status=?,quality=?,finished=? WHERE id=?", (status, quality, now(), run_id))

    def set_status(self, run_id: str, status: str):
        with self.connect() as db:
            db.execute("UPDATE runs SET status=? WHERE id=?", (status, run_id))

    def control(self, run_id: str, action: str):
        if action not in ("cancel", "resume", "pause"):
            raise FlowError("Unknown control action")
        self.recover_runs()
        with self.lock() as db:
            row = db.execute("SELECT status FROM runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise FlowError(f"Unknown run {run_id}")
            if row["status"] not in ("queued", "running", "paused"):
                raise Conflict("Run has finished; create a new run to execute again")
            db.execute("INSERT OR REPLACE INTO controls VALUES (?,?)", (run_id, action))

    def take_control(self, run_id: str) -> str | None:
        with self.lock() as db:
            row = db.execute("SELECT action FROM controls WHERE run_id=?", (run_id,)).fetchone()
            if row:
                db.execute("DELETE FROM controls WHERE run_id=?", (run_id,))
                return row[0]
        return None

    def recover_runs(self):
        """Called at startup. Dead worker owners become interrupted, never successful."""
        with self.connect() as db:
            rows = db.execute("SELECT id,owner FROM runs WHERE status IN ('queued','running','paused')").fetchall()
        for row in rows:
            if not process_alive(row["owner"]):
                self.finish(row["id"], "interrupted", "unknown")

    def artifact(self, value: dict, fields: list[str]) -> str:
        content = canonical(sanitize(value, fields))
        key = file_digest(content)
        atomic_write(self.state / "artifacts" / (key + ".json"), content)
        return key

    def clean(self, runs_before: str | None = None):
        import shutil
        cache = inside(self.root, ".cdaf/cache")
        if cache.is_dir():
            shutil.rmtree(cache)
        deleted = 0
        if runs_before:
            cutoff = datetime.fromisoformat(runs_before)
            if cutoff.tzinfo is None:
                cutoff = cutoff.replace(tzinfo=timezone.utc)
            cutoff = cutoff.astimezone(timezone.utc).isoformat()
            with self.connect() as db:
                deleted = db.execute("DELETE FROM runs WHERE julianday(started)<julianday(?) AND status NOT IN ('queued','running','paused')", (cutoff,)).rowcount
        return {"cache_cleared": True, "runs_deleted": deleted, "definitions_preserved": True}

    def enforce_retention(self, days: int):
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        self.clean(cutoff)
        for path in (self.state / "artifacts").glob("*.json"):
            if datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat() < cutoff:
                path.unlink()


def process_alive(pid: int) -> bool:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() == 5  # access denied is not evidence of death
        try:
            code = wintypes.DWORD()
            return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
