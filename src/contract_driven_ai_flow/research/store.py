"""Durable scientific metadata, independent of legacy port graphs."""
from __future__ import annotations

import json
import os
import re
import sqlite3
import uuid
from collections.abc import Sequence
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime, timedelta, timezone

from .models import ObservationEvent, OperationRecord, SnapshotRef, timestamp


def encode(value) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


class ExperimentStore:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.state = self.root / ".cdaf/research"
        self.state.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, script TEXT NOT NULL,
                    interpreter TEXT NOT NULL, source_digest TEXT NOT NULL,
                    started TEXT NOT NULL, finished TEXT, status TEXT NOT NULL,
                    summary TEXT NOT NULL, environment TEXT NOT NULL, owner INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
                    body TEXT NOT NULL, FOREIGN KEY(run_id) REFERENCES runs(id));
                CREATE INDEX IF NOT EXISTS research_events_run ON events(run_id,sequence);
                CREATE TABLE IF NOT EXISTS snapshots (
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL, binding_id TEXT NOT NULL,
                    version INTEGER NOT NULL, body TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES runs(id));
                CREATE INDEX IF NOT EXISTS research_snapshots_binding ON snapshots(run_id,binding_id,version);
                CREATE TABLE IF NOT EXISTS operations (
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL, body TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES runs(id));
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.state / "experiments.sqlite3", timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA journal_mode=WAL")
            with db:
                yield db
        finally:
            db.close()

    def create_run(self, script: str, *, interpreter: str, source_digest: str, name: str = "Analysis", environment: dict | None = None) -> dict:
        run_id = uuid.uuid4().hex
        with self.connect() as db:
            db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,NULL,?,?,?,?)", (
                run_id, name, script, interpreter, source_digest, timestamp(), "queued", "{}", encode(environment or {}), os.getpid()))
        return self.run(run_id)

    @staticmethod
    def _run(row):
        result = dict(row)
        result["summary"] = json.loads(result["summary"])
        result["environment"] = json.loads(result["environment"])
        return result

    def run(self, run_id: str) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise LookupError("Unknown scientific run")
        return self._run(row)

    def bootstrap(self, run_id: str):
        # A read transaction fixes the cursor and value versions together, so
        # reconnecting from this cursor cannot miss an intervening observation.
        with self.connect() as db:
            db.execute("BEGIN")
            row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise LookupError("Unknown scientific run")
            cursor = db.execute("SELECT COALESCE(MAX(sequence),0) FROM events WHERE run_id=?", (run_id,)).fetchone()[0]
            count = db.execute("SELECT COUNT(DISTINCT binding_id) FROM snapshots WHERE run_id=?", (run_id,)).fetchone()[0]
            rows = db.execute("SELECT s.body FROM snapshots s WHERE s.run_id=? AND s.version=(SELECT MAX(o.version) FROM snapshots o WHERE o.run_id=s.run_id AND o.binding_id=s.binding_id) ORDER BY s.rowid LIMIT 2048", (run_id,)).fetchall()
            operations = db.execute("SELECT body FROM operations WHERE run_id=? ORDER BY rowid DESC LIMIT 256", (run_id,)).fetchall()
            probes = db.execute("SELECT body FROM events WHERE run_id=? AND json_extract(body,'$.kind')='probe.evaluated' ORDER BY sequence DESC LIMIT 512", (run_id,)).fetchall()
        return {"run": self._run(row), "cursor": cursor, "binding_count": count,
                "snapshots": [json.loads(r["body"]) for r in rows], "operations": [json.loads(r["body"]) for r in reversed(operations)],
                "probe_events": [json.loads(r["body"]) for r in reversed(probes)]}

    def runs(self, limit: int = 100) -> list[dict]:
        if not 1 <= limit <= 1000:
            raise ValueError("Run page must contain 1-1000 records")
        with self.connect() as db:
            return [self._run(row) for row in db.execute("SELECT * FROM runs ORDER BY started DESC LIMIT ?", (limit,))]

    def append(self, events: Sequence[ObservationEvent]) -> None:
        if not events:
            return
        with self.connect() as db:
            identifiers = tuple({e.run_id for e in events})
            known_runs = {r[0] for r in db.execute("SELECT id FROM runs WHERE id IN (%s)" % ",".join("?" for _ in identifiers), identifiers)}
            for event in events:
                if event.run_id not in known_runs:
                    raise ValueError("Observation references an unknown run")
                if event.kind == "run.finished" and db.execute("SELECT finished FROM runs WHERE id=?", (event.run_id,)).fetchone()[0]:
                    continue
                body = event.model_dump(mode="json")
                cursor = db.execute("INSERT INTO events(run_id,body) VALUES (?,?)", (event.run_id, "{}"))
                body["sequence"] = cursor.lastrowid
                db.execute("UPDATE events SET body=? WHERE sequence=?", (encode(body), cursor.lastrowid))
                if event.kind == "value.observed" and "snapshot" in event.payload:
                    snapshot = SnapshotRef.model_validate(event.payload["snapshot"])
                    if snapshot.run_id != event.run_id or event.snapshot_id != snapshot.id:
                        raise ValueError("Snapshot envelope does not match its run and identifier")
                    # Immutable observation identity: duplicate IDs must not overwrite history.
                    db.execute("INSERT INTO snapshots VALUES (?,?,?,?,?)", (snapshot.id, snapshot.run_id, snapshot.binding_id, snapshot.version, encode(snapshot.model_dump(mode="json"))))
                if event.kind.startswith("operation.") and "operation" in event.payload:
                    operation = OperationRecord.model_validate(event.payload["operation"])
                    if operation.run_id != event.run_id or event.operation_id != operation.id:
                        raise ValueError("Operation envelope does not match its run and identifier")
                    db.execute("INSERT INTO operations VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body WHERE operations.run_id=excluded.run_id", (operation.id, operation.run_id, encode(operation.model_dump(mode="json"))))
                if event.kind == "run.started":
                    db.execute("UPDATE runs SET status='running',environment=? WHERE id=?", (encode(event.payload.get("environment", {})), event.run_id))
                if event.kind == "environment.observed":
                    db.execute("UPDATE runs SET environment=? WHERE id=?", (encode(event.payload), event.run_id))
                if event.kind == "control.paused":
                    db.execute("UPDATE runs SET status='paused' WHERE id=?", (event.run_id,))
                if event.kind == "control.resumed":
                    db.execute("UPDATE runs SET status='running' WHERE id=?", (event.run_id,))
                if event.kind == "run.finished":
                    status = event.payload.get("status", "failed")
                    if status not in ("completed", "failed", "cancelled", "interrupted", "timeout"):
                        raise ValueError("Invalid terminal scientific run state")
                    db.execute("UPDATE runs SET status=?,finished=?,summary=? WHERE id=?", (status, event.timestamp, encode(event.payload), event.run_id))

    def events(self, run_id: str, after: int = 0, limit: int = 1000) -> list[ObservationEvent]:
        if not 1 <= limit <= 10000 or after < 0:
            raise ValueError("Event cursor or page limit is invalid")
        self.run(run_id)
        with self.connect() as db:
            rows = db.execute("SELECT body FROM events WHERE run_id=? AND sequence>? ORDER BY sequence LIMIT ?", (run_id, after, limit)).fetchall()
        return [ObservationEvent.model_validate_json(row["body"]) for row in rows]

    def snapshot(self, snapshot_id: str) -> SnapshotRef:
        with self.connect() as db:
            row = db.execute("SELECT body FROM snapshots WHERE id=?", (snapshot_id,)).fetchone()
        if row is None:
            raise LookupError("Unknown scientific snapshot")
        return SnapshotRef.model_validate_json(row["body"])

    def snapshots(self, run_id: str, *, latest: bool = True, limit: int = 1000, after: str | None = None) -> list[SnapshotRef]:
        self.run(run_id)
        if not 1 <= limit <= 10000:
            raise ValueError("Snapshot page limit is invalid")
        query = "SELECT s.body FROM snapshots s WHERE s.run_id=?"
        if latest:
            query += " AND s.version=(SELECT MAX(o.version) FROM snapshots o WHERE o.run_id=s.run_id AND o.binding_id=s.binding_id)"
        parameters = [run_id]
        if after is not None:
            query += " AND s.rowid > COALESCE((SELECT rowid FROM snapshots WHERE id=? AND run_id=?),9223372036854775807)"
            parameters.extend((after, run_id))
        query += " ORDER BY s.rowid LIMIT ?"
        parameters.append(limit)
        with self.connect() as db:
            rows = db.execute(query, parameters).fetchall()
        return [SnapshotRef.model_validate_json(row["body"]) for row in rows]

    def operations(self, run_id: str, limit: int = 1000) -> list[OperationRecord]:
        self.run(run_id)
        if not 1 <= limit <= 10000:
            raise ValueError("Operation page limit is invalid")
        with self.connect() as db:
            rows = db.execute("SELECT body FROM operations WHERE run_id=? ORDER BY rowid LIMIT ?", (run_id, limit)).fetchall()
        return [OperationRecord.model_validate_json(row["body"]) for row in rows]

    def recover_runs(self):
        from ..storage import process_alive
        with self.connect() as db:
            owners = db.execute("SELECT id,owner FROM runs WHERE finished IS NULL").fetchall()
        for owner in owners:
            if not process_alive(owner["owner"]):
                self.append([ObservationEvent(run_id=owner["id"], kind="run.finished",
                    payload={"status": "interrupted", "execution_status": "interrupted", "quality": "unknown", "reason": "owner_process_exited"})])

    def expire_artifacts(self, days=7):
        if type(days) is not int or days < 1:
            raise ValueError("Artifact retention must be at least one day")
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with self.connect() as db:
            rows = db.execute("SELECT s.body,r.finished FROM snapshots s JOIN runs r ON r.id=s.run_id").fetchall()
        expired, protected = set(), set()
        for row in rows:
            reference = json.loads(row["body"]).get("artifact_ref")
            if reference:
                (expired if row["finished"] and row["finished"] < cutoff else protected).add(reference)
        count = 0
        directory = (self.state / "artifacts").resolve()
        for reference in expired - protected:
            if not re.fullmatch(r"artifacts/[0-9a-f]{32}\.(npy|arrow)", reference):
                continue
            path = self.state / reference
            if path.is_file() and not path.is_symlink() and path.resolve().parent == directory:
                path.unlink()
                count += 1
        return {"artifacts_deleted": count, "history_preserved": True, "definitions_preserved": True}

    def slice(self, snapshot_id: str, selectors: Sequence[dict]) -> dict:
        snapshot = self.snapshot(snapshot_id)
        if not snapshot.artifact_ref:
            return {"available": False, "snapshot_id": snapshot_id, "reason": "This observation did not save the complete value"}
        from .artifacts import read_slice
        return read_slice(self.state, snapshot, selectors)
