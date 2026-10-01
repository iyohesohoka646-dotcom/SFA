"""Read-only migration of old port-flow evidence; never invent scientific values."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path

from .agent.privacy import sanitize_json
from .store import ExperimentStore, encode


@dataclass(frozen=True)
class MigrationReport:
    source: str
    destination: str
    original_ids: list[str]
    converted_items: int
    unsupported_items: list[str]
    warnings: list[str]
    applied: bool


def import_legacy(source: Path, destination: Path, *, preview=True):
    source, destination = Path(source).resolve(strict=True), Path(destination).resolve()
    if source == destination or destination.is_relative_to(source):
        raise ValueError("Migration destination must be separate from the original project")
    database = source / ".cdaf/runs.sqlite3"
    records, definitions = [], []
    if database.is_file():
        db = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
        db.row_factory = sqlite3.Row
        try:
            for row in db.execute("SELECT * FROM runs ORDER BY started"):
                body = dict(row)
                for key in ("graph", "environment"):
                    if key in body and isinstance(body[key], str):
                        body[key] = json.loads(body[key])
                events = [json.loads(item[0]) for item in db.execute("SELECT body FROM events WHERE run_id=? ORDER BY sequence", (body["id"],))]
                records.append(sanitize_json({**body, "events": events, "format": "legacy-port-flow", "scientific_values": "not_captured"}))
        finally:
            db.close()
    for name in ("flow.yaml", "sfa.yml"):
        path = source / name
        if path.is_file():
            definitions.append((name, path.read_bytes()))
    sfa = source / ".sfa"
    if sfa.is_dir() and not sfa.is_symlink():
        for directory in ("modules", "probes"):
            for path in (sfa / directory).glob("*.json"):
                if path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(source):
                    definitions.append((path.relative_to(source).as_posix(), path.read_bytes()))
        for directory in (sfa / "snapshots").iterdir() if (sfa / "snapshots").is_dir() else []:
            manifest = directory / "run.json"
            if not directory.is_dir() or directory.is_symlink() or not manifest.is_file() or manifest.is_symlink():
                continue
            record = {"id": directory.name, "format": "legacy-sfa-json", "scientific_values": "not_captured",
                      "manifest": json.loads(manifest.read_text(encoding="utf-8")), "snapshots": {}}
            for path in directory.glob("*.json"):
                if path.name != "run.json" and not path.is_symlink():
                    record["snapshots"][path.stem] = json.loads(path.read_text(encoding="utf-8"))
            records.append(sanitize_json(record))
    if not definitions:
        raise ValueError("No legacy flow.yaml or sfa.yml project was found")
    warnings = ["Old JSON boundary evidence is preserved under its original semantics; matrices, axes and exact source versions were not captured"]
    report = MigrationReport(str(source), str(destination), [r["id"] for r in records], len(records),
                             ["scientific snapshots", "axis semantics", "native alias history"], warnings, not preview)
    if preview:
        return report
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError("Migration never overwrites an existing non-empty destination")
    destination.mkdir(parents=True, exist_ok=True)
    store = ExperimentStore(destination)
    backup = store.state / "legacy-definitions"
    backup.mkdir()
    manifest = []
    for name, data in definitions:
        (backup / name).parent.mkdir(parents=True, exist_ok=True)
        with os.fdopen(os.open(backup / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as stream:
            stream.write(data)
        manifest.append({"name": name, "sha256": hashlib.sha256(data).hexdigest()})
    with store.connect() as db:
        db.execute("CREATE TABLE IF NOT EXISTS legacy_runs(id TEXT PRIMARY KEY,body TEXT NOT NULL)")
        db.executemany("INSERT INTO legacy_runs VALUES (?,?)", [(r["id"], encode(r)) for r in records])
    temporary = store.state / "migration-report.partial"
    temporary.write_text(encode({**asdict(report), "definition_backup": manifest}), encoding="utf-8")
    os.replace(temporary, store.state / "migration-report.json")
    return report


def legacy_runs(root: Path):
    database = Path(root).resolve() / ".cdaf/research/experiments.sqlite3"
    if not database.is_file():
        return []
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='legacy_runs'").fetchone():
            return []
        return [json.loads(row[0]) for row in db.execute("SELECT body FROM legacy_runs ORDER BY rowid DESC")]
