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
                CREATE TABLE IF NOT EXISTS control_summaries (
                    run_id TEXT NOT NULL, node_id TEXT NOT NULL, revision INTEGER NOT NULL,
                    body TEXT NOT NULL, PRIMARY KEY(run_id,node_id));
                CREATE TABLE IF NOT EXISTS control_details (
                    run_id TEXT NOT NULL, ordinal INTEGER NOT NULL, body TEXT NOT NULL,
                    PRIMARY KEY(run_id,ordinal));
                CREATE TABLE IF NOT EXISTS control_receipts (
                    run_id TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS artifact_leases (
                    reference TEXT NOT NULL, owner TEXT NOT NULL, until TEXT,
                    PRIMARY KEY(reference,owner));
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
            # Resolve parents of this bounded bootstrap independently of the
            # preview cache. Older versions may no longer be among latest rows.
            parent_ids = {parent for r in rows for parent in json.loads(r['body']).get('parents', [])}
            parent_bindings = {}
            ordered_parents = sorted(parent_ids)
            for offset in range(0, len(ordered_parents), 500):
                batch = ordered_parents[offset:offset+500]
                parents = db.execute('SELECT id,binding_id FROM snapshots WHERE run_id=? AND id IN (%s)' % ','.join('?' for _ in batch), (run_id, *batch)).fetchall()
                parent_bindings.update({p['id']:p['binding_id'] for p in parents})
            operations = db.execute("SELECT body FROM operations WHERE run_id=? ORDER BY rowid DESC LIMIT 256", (run_id,)).fetchall()
            probes = db.execute("SELECT body FROM events WHERE run_id=? AND json_extract(body,'$.kind')='probe.evaluated' ORDER BY sequence DESC LIMIT 512", (run_id,)).fetchall()
        indexed = []
        for r in rows:
            snapshot = json.loads(r["body"])
            snapshot["sample"] = {}
            snapshot["coverage"]["delivery"] = "metadata-index"
            indexed.append(snapshot)
        return {"run": self._run(row), "cursor": cursor, "binding_count": count,
                "parent_bindings": parent_bindings,
                "snapshots": indexed, "operations": [json.loads(r["body"]) for r in reversed(operations)],
                "probe_events": [json.loads(r["body"]) for r in reversed(probes)],
                "control_summaries": self.control_summaries(run_id)}

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
                if event.kind.startswith('control.'):
                    self._append_control(db, event, cursor.lastrowid)
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

    def _append_control(self, db, event, sequence):
        """Cumulative summaries replace old versions; detail storage is bounded."""
        if event.kind == 'control.summary':
            for summary in event.payload.get('summaries', [])[:16]:
                if not isinstance(summary, dict) or not summary.get('node_id'):
                    raise ValueError('Control summary requires a semantic node identity')
                revision = summary.get('revision', 0)
                if type(revision) is not int or revision < 0:
                    raise ValueError('Control summary revision must be nonnegative')
                count = db.execute('SELECT COUNT(*) FROM control_summaries WHERE run_id=?', (event.run_id,)).fetchone()[0]
                if count >= 4096 and not db.execute('SELECT 1 FROM control_summaries WHERE run_id=? AND node_id=?', (event.run_id, summary['node_id'])).fetchone():
                    continue
                db.execute('INSERT INTO control_summaries VALUES (?,?,?,?) ON CONFLICT(run_id,node_id) DO UPDATE SET revision=excluded.revision,body=excluded.body WHERE excluded.revision>=control_summaries.revision',
                    (event.run_id, summary['node_id'], revision, encode(summary)))
        elif event.kind == 'control.details':
            count = db.execute('SELECT COUNT(*) FROM control_details WHERE run_id=?', (event.run_id,)).fetchone()[0]
            for offset, detail in enumerate(event.payload.get('details', [])[:max(0, 512-count)]):
                db.execute('INSERT INTO control_details VALUES (?,?,?)', (event.run_id, count+offset, encode(detail)))
        elif event.kind == 'control.finished':
            db.execute('INSERT INTO control_receipts VALUES (?,?) ON CONFLICT(run_id) DO UPDATE SET body=excluded.body', (event.run_id, encode(event.payload)))
        # SSE still has a monotonically increasing cursor. Bootstrap reads the
        # tables, so reconnect does not depend on unbounded old checkpoint events.
        db.execute("DELETE FROM events WHERE run_id=? AND json_extract(body,'$.kind')=? AND sequence NOT IN (SELECT sequence FROM events WHERE run_id=? AND json_extract(body,'$.kind')=? ORDER BY sequence DESC LIMIT 4)",
            (event.run_id, event.kind, event.run_id, event.kind))

    def control_summaries(self, run_id):
        self.run(run_id)
        with self.connect() as db:
            rows = db.execute('SELECT revision,body FROM control_summaries WHERE run_id=? ORDER BY node_id', (run_id,)).fetchall()
            receipt_row = db.execute('SELECT body FROM control_receipts WHERE run_id=?', (run_id,)).fetchone()
        receipt = json.loads(receipt_row['body']) if receipt_row else {}
        records = [json.loads(row['body']) for row in rows]
        # Missing final chunks or a forced exit never turn lower bounds into
        # complete counts just because an earlier checkpoint said complete.
        finished = bool(receipt.get('complete')) and len(records) == receipt.get('node_count') and all(row['revision'] == receipt.get('revision') for row in rows)
        for record in records:
            record['complete'] = finished and bool(record.get('complete'))
        return records

    def control_details(self, run_id):
        self.run(run_id)
        with self.connect() as db:
            rows = db.execute('SELECT body FROM control_details WHERE run_id=? ORDER BY ordinal LIMIT 512', (run_id,)).fetchall()
            events = db.execute("SELECT body FROM events WHERE run_id=? AND json_extract(body,'$.kind') IN ('control.summary','control.details','control.finished')", (run_id,)).fetchall()
        omitted = max((json.loads(row['body'])['payload'].get('omitted', 0) for row in events), default=0)
        return {'items': [json.loads(row['body']) for row in rows], 'omitted': omitted}

    def snapshots(self, run_id: str, *, latest: bool = True, limit: int = 1000, after: str | None = None, metadata_only: bool = False) -> list[SnapshotRef]:
        self.run(run_id)
        if not 1 <= limit <= 10000:
            raise ValueError("Snapshot page limit is invalid")
        projection = "json_set(s.body,'$.sample',json('{}')) AS body" if metadata_only else 's.body'
        query = f"SELECT {projection} FROM snapshots s WHERE s.run_id=?"
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

    def history(self, run_id: str, binding: str, before: int | None = None, limit=100):
        self.run(run_id)
        if not 1 <= limit <= 1000 or before is not None and before < 1:
            raise ValueError("Invalid variable history page")
        query = "SELECT body FROM snapshots WHERE run_id=? AND binding_id=?"
        parameters = [run_id, binding]
        if before is not None:
            query += " AND version<?"
            parameters.append(before)
        with self.connect() as db:
            rows = db.execute(query + " ORDER BY version DESC LIMIT ?", (*parameters, limit)).fetchall()
        return [SnapshotRef.model_validate_json(row["body"]) for row in rows]

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
            leases = db.execute('SELECT reference FROM artifact_leases WHERE until IS NULL OR until>?', (timestamp(),)).fetchall()
        expired, protected = set(), set()
        protected.update(row['reference'] for row in leases)
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
                path.with_suffix(path.suffix+'.meta.json').unlink(missing_ok=True)
                count += 1
        return {"artifacts_deleted": count, "history_preserved": True, "definitions_preserved": True}

    def retain_artifacts(self, snapshot_ids, owner, minutes=None):
        until = (datetime.now(timezone.utc)+timedelta(minutes=minutes)).isoformat() if minutes else None
        pending, seen, references = list(snapshot_ids), set(), set()
        while pending:
            key = pending.pop()
            if key in seen:
                continue
            seen.add(key)
            snapshot = self.snapshot(key)
            if snapshot.artifact_ref:
                references.add(snapshot.artifact_ref)
            pending.extend(snapshot.parents)
        with self.connect() as db:
            for reference in references:
                db.execute('INSERT INTO artifact_leases VALUES (?,?,?) ON CONFLICT(reference,owner) DO UPDATE SET until=excluded.until', (reference, owner, until))

    def release_artifacts(self, owner):
        with self.connect() as db:
            db.execute('DELETE FROM artifact_leases WHERE owner=?', (owner,))

    def slice(self, snapshot_id: str, selectors: Sequence[dict]) -> dict:
        snapshot = self.snapshot(snapshot_id)
        if not snapshot.artifact_ref:
            return {"available": False, "snapshot_id": snapshot_id, "reason": "This observation did not save the complete value"}
        from .artifacts import read_slice
        return read_slice(self.state, snapshot, selectors)
