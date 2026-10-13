"""Normalized per-file project index. No bulk JSON document, no execution."""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path


class ProjectStore:
    def __init__(self, project_root: Path):
        self.root = Path(project_root).resolve()
        self.state = self.root / ".cdaf" / "research"
        self.state.mkdir(parents=True, exist_ok=True)
        self.path = self.state / "projects.sqlite3"
        # Thread-local scoped connection; never shared across threads.
        self._local = threading.local()
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS files(
                    project_id TEXT, file_id TEXT, relative_path TEXT,
                    digest TEXT, analysis_id TEXT, module_names TEXT,
                    status TEXT, diagnostics TEXT,
                    PRIMARY KEY(project_id, file_id));
                CREATE INDEX IF NOT EXISTS files_path ON files(project_id, relative_path);
                CREATE INDEX IF NOT EXISTS files_digest ON files(project_id, digest);
                CREATE TABLE IF NOT EXISTS revisions(
                    revision_id TEXT PRIMARY KEY, project_id TEXT, parent_id TEXT,
                    created INTEGER, files_count INTEGER, parsed_files INTEGER,
                    reused_files INTEGER, diagnostics TEXT);
                CREATE INDEX IF NOT EXISTS revisions_project ON revisions(project_id, created);
                CREATE TABLE IF NOT EXISTS revision_files(
                    revision_id TEXT, file_id TEXT, relative_path TEXT, digest TEXT,
                    analysis_id TEXT, module_names TEXT, status TEXT, diagnostics TEXT,
                    PRIMARY KEY(revision_id, file_id));
                CREATE TABLE IF NOT EXISTS analyses(
                    analysis_id TEXT PRIMARY KEY, digest TEXT, payload TEXT, facts TEXT, symbols TEXT);
                CREATE TABLE IF NOT EXISTS sources(
                    digest TEXT PRIMARY KEY, code TEXT);
                CREATE TABLE IF NOT EXISTS relationships(
                    revision_id TEXT, source_file_id TEXT, target_file_id TEXT,
                    kind TEXT, provenance TEXT, payload TEXT);
                CREATE INDEX IF NOT EXISTS rel_revision ON relationships(revision_id);
                """
            )
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(analyses)").fetchall()
            }
            if "facts" not in columns:
                conn.execute("ALTER TABLE analyses ADD COLUMN facts TEXT")
            if "symbols" not in columns:
                conn.execute("ALTER TABLE analyses ADD COLUMN symbols TEXT")

    @contextmanager
    def connect(self):
        """Borrow the scoped connection when one is open, else a transient one."""
        active = getattr(self._local, "connection", None)
        if active is not None:
            yield active
            return
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    @contextmanager
    def session(self):
        """One connection/transaction for a group of calls in this thread.

        Methods borrow this connection instead of opening their own. The outer
        owner commits on success and rolls back on any error or cancellation, so
        a cancelled index discards its uncommitted caches atomically. Connections
        are thread-local and never shared across threads.
        """
        active = getattr(self._local, "connection", None)
        if active is not None:
            yield active
            return
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        self._local.connection = conn
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            self._local.connection = None
            conn.close()

    # -- file identity -------------------------------------------------
    def current_file(self, project_id: str, relative_path: str):
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM files WHERE project_id=? AND relative_path=?",
                (project_id, relative_path),
            ).fetchone()
        return dict(row) if row else None

    def all_files(self, project_id: str):
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM files WHERE project_id=?", (project_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    # -- analyses, facts and archived (redacted) source ----------------
    def put_analysis(self, analysis_id: str, digest: str, payload: dict):
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO analyses(analysis_id,digest,payload) VALUES(?,?,?) "
                "ON CONFLICT(analysis_id) DO UPDATE SET payload=excluded.payload",
                (analysis_id, digest, json.dumps(payload, ensure_ascii=False)),
            )

    def get_analysis(self, analysis_id: str):
        with self.connect() as conn:
            row = conn.execute(
                "SELECT payload FROM analyses WHERE analysis_id=?", (analysis_id,)
            ).fetchone()
        return json.loads(row["payload"]) if row else None

    def put_facts(self, analysis_id: str, facts: dict):
        with self.connect() as conn:
            conn.execute(
                "UPDATE analyses SET facts=? WHERE analysis_id=?",
                (json.dumps(facts, ensure_ascii=False), analysis_id),
            )

    def get_facts(self, analysis_id: str):
        with self.connect() as conn:
            row = conn.execute(
                "SELECT facts FROM analyses WHERE analysis_id=?", (analysis_id,)
            ).fetchone()
        if not row or not row["facts"]:
            return None
        return json.loads(row["facts"])

    def put_symbols(self, analysis_id: str, symbols: list):
        with self.connect() as conn:
            conn.execute(
                "UPDATE analyses SET symbols=? WHERE analysis_id=?",
                (json.dumps(symbols, ensure_ascii=False), analysis_id),
            )

    def get_symbols(self, analysis_id: str):
        with self.connect() as conn:
            row = conn.execute(
                "SELECT symbols FROM analyses WHERE analysis_id=?", (analysis_id,)
            ).fetchone()
        if not row or not row["symbols"]:
            return None
        return json.loads(row["symbols"])

    def put_source(self, digest: str, code: str):
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO sources(digest,code) VALUES(?,?) ON CONFLICT(digest) DO UPDATE SET code=excluded.code",
                (digest, code),
            )

    def get_source(self, digest: str):
        with self.connect() as conn:
            row = conn.execute(
                "SELECT code FROM sources WHERE digest=?", (digest,)
            ).fetchone()
        return row["code"] if row else ""

    _READ_CHUNK = 500

    def compact_records(self, analysis_ids) -> dict:
        """Bulk-read compact (facts, symbols) for many analyses on one connection."""
        unique = [aid for aid in dict.fromkeys(analysis_ids) if aid]
        records: dict = {}
        if not unique:
            return records
        with self.connect() as conn:
            for start in range(0, len(unique), self._READ_CHUNK):
                chunk = unique[start : start + self._READ_CHUNK]
                placeholders = ",".join("?" for _ in chunk)
                rows = conn.execute(
                    f"SELECT analysis_id, facts, symbols FROM analyses "
                    f"WHERE analysis_id IN ({placeholders})",
                    tuple(chunk),
                ).fetchall()
                for row in rows:
                    records[row["analysis_id"]] = (
                        json.loads(row["facts"]) if row["facts"] else None,
                        json.loads(row["symbols"]) if row["symbols"] else None,
                    )
        return records

    def iter_graph_block_identities(self, revision_id: str):
        """Stream compact archived graph block identities for one revision.

        Only the small identity fields are extracted from the stored analysis
        payload via ``json_each``; no full ``AnalysisDocument`` is instantiated
        and no user source is re-read. Yields ``(file_id, local_id, kind,
        logical_key)`` tuples lazily so callers can stop as soon as they match.
        """
        sql = (
            "SELECT rf.file_id AS file_id, "
            "json_extract(b.value, '$.id') AS local_id, "
            "json_extract(b.value, '$.kind') AS kind, "
            "json_extract(b.value, '$.logical_key') AS logical_key "
            "FROM revision_files rf "
            "JOIN analyses a ON a.analysis_id = rf.analysis_id, "
            "json_each(a.payload, '$.graph.blocks') b "
            "WHERE rf.revision_id = ?"
        )
        with self.connect() as conn:
            cursor = conn.execute(sql, (revision_id,))
            for row in cursor:
                yield (
                    row["file_id"],
                    row["local_id"],
                    row["kind"],
                    row["logical_key"],
                )

    # -- publication (single transaction) ------------------------------
    def publish(self, project_id: str, revision: dict, files: list, relationships: list) -> None:
        """Atomically publish revision, visible file identities and edges."""
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO revisions(revision_id,project_id,parent_id,created,files_count,"
                "parsed_files,reused_files,diagnostics) VALUES(?,?,?,unixepoch(),?,?,?,?)",
                (
                    revision["id"],
                    revision["project_id"],
                    revision.get("parent_revision_id"),
                    revision["files_count"],
                    revision["parsed_files"],
                    revision["reused_files"],
                    json.dumps(revision.get("diagnostics", [])),
                ),
            )
            for row in files:
                conn.execute(
                    "INSERT INTO revision_files(revision_id,file_id,relative_path,digest,"
                    "analysis_id,module_names,status,diagnostics) VALUES(?,?,?,?,?,?,?,?)",
                    (
                        revision["id"],
                        row["file_id"],
                        row["relative_path"],
                        row["digest"],
                        row.get("analysis_id", ""),
                        json.dumps(row.get("module_names", [])),
                        row.get("status", "parsed"),
                        json.dumps(row.get("diagnostics", [])),
                    ),
                )
                conn.execute(
                    "INSERT INTO files(project_id,file_id,relative_path,digest,analysis_id,"
                    "module_names,status,diagnostics) VALUES(?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(project_id,file_id) DO UPDATE SET relative_path=excluded.relative_path,"
                    "digest=excluded.digest, analysis_id=excluded.analysis_id, "
                    "module_names=excluded.module_names, status=excluded.status, diagnostics=excluded.diagnostics",
                    (
                        project_id,
                        row["file_id"],
                        row["relative_path"],
                        row["digest"],
                        row.get("analysis_id", ""),
                        json.dumps(row.get("module_names", [])),
                        row.get("status", "parsed"),
                        json.dumps(row.get("diagnostics", [])),
                    ),
                )
            for row in relationships:
                conn.execute(
                    "INSERT INTO relationships(revision_id,source_file_id,target_file_id,"
                    "kind,provenance,payload) VALUES(?,?,?,?,?,?)",
                    (
                        revision["id"],
                        row["source_file_id"],
                        row["target_file_id"],
                        row["kind"],
                        row.get("provenance", "inferred"),
                        json.dumps(row.get("payload", {})),
                    ),
                )
            kept = [row["file_id"] for row in files]
            if kept:
                placeholders = ",".join("?" for _ in kept)
                conn.execute(
                    f"DELETE FROM files WHERE project_id=? AND file_id NOT IN ({placeholders})",
                    (project_id, *kept),
                )
            else:
                conn.execute("DELETE FROM files WHERE project_id=?", (project_id,))

    # -- reads ---------------------------------------------------------
    def latest_revision(self, project_id: str):
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM revisions WHERE project_id=? ORDER BY created DESC, rowid DESC LIMIT 1",
                (project_id,),
            ).fetchone()
        return dict(row) if row else None

    def get_revision(self, revision_id: str):
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM revisions WHERE revision_id=?", (revision_id,)
            ).fetchone()
        return dict(row) if row else None

    def revision_files(self, revision_id: str):
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM revision_files WHERE revision_id=? ORDER BY relative_path",
                (revision_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def revision_file(self, revision_id: str, file_id: str):
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM revision_files WHERE revision_id=? AND file_id=?",
                (revision_id, file_id),
            ).fetchone()
        return dict(row) if row else None

    def relationships(self, revision_id: str):
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM relationships WHERE revision_id=?", (revision_id,)
            ).fetchall()
        return [dict(row) for row in rows]