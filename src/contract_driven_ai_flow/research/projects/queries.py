"""Inert, paged project queries: tree, objects, symbols, references and graph.

All reads go through the persisted per-file index. Bounded pages use SQLite's
``json_each``/``json_extract`` over the compact ``analyses`` payload so a page
never instantiates every project ``AnalysisDocument``. Nothing imports or runs
user code; dynamic patterns stay unknown instead of being guessed.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..models import SourceRef
from ..workbench.bindings import matches_instance
from ..workbench.semantic_models import (
    GraphBlock,
    GraphEdge,
    SemanticGraph,
    TargetRef,
)
from .models import ProjectGraphSlice
from .query_models import (
    ObjectItem,
    ObjectPage,
    ReferenceItem,
    ReferencePage,
    SymbolPage,
    SymbolRef,
    TreeItem,
    TreePage,
)
from .resolver import FileFacts, ProjectGraphInput, _Resolver, _id
from .store import ProjectStore

CODE_NODE_KINDS = {
    "operation",
    "condition",
    "loop_header",
    "merge",
    "call",
    "entry",
    "exit",
    "return",
    "unknown",
}
DATA_NODE_KINDS = {"data", "parameter", "return", "operation"}
CODE_EDGE_KINDS = {"control", "call", "contains", "block", "merge", "backedge"}
DATA_EDGE_KINDS = {"data", "argument", "return", "contains", "block"}
# Value-flow edges and the value plates they pass through when a hidden
# variable must be projected into a visible calculation dependency.
_DATA_FLOW_EDGE_KINDS = {"data", "argument", "return"}
_TRANSPARENT_NODE_KINDS = {"data", "parameter"}
_CALCULATION_NODE_KINDS = {"operation", "call"}

_ASSIGNMENT_SQL = """
SELECT rf.file_id AS file_id, rf.relative_path AS relative_path,
       rf.digest AS digest, rf.analysis_id AS analysis_id,
       json_extract(je.value, '$.logical_key') AS logical_key,
       MAX(json_extract(je.value, '$.line')) AS line,
       json_extract(je.value, '$.name') AS name,
       json_extract(je.value, '$.kind') AS kind,
       json_extract(je.value, '$.scope') AS scope,
       json_extract(je.value, '$.end_line') AS end_line,
       json_extract(je.value, '$.block_id') AS block_id,
       json_extract(je.value, '$.id') AS object_id,
       json_extract(je.value, '$.qualname') AS qualname,
       json_extract(je.value, '$.code') AS code
FROM revision_files rf
JOIN analyses a ON a.analysis_id = rf.analysis_id,
json_each(a.payload, '$.objects') je
WHERE rf.revision_id = ?
  AND json_extract(je.value, '$.kind') {kind}
  {extra}
GROUP BY COALESCE(NULLIF(json_extract(je.value, '$.logical_key'), ''),
                  rf.file_id || '::' || COALESCE(json_extract(je.value, '$.scope'),'') || '::' || json_extract(je.value, '$.name'))
"""

_IMPORT_SQL = """
SELECT rf.file_id AS file_id,
       json_extract(je.value, '$.line') AS line,
       json_extract(je.value, '$.name') AS name
FROM revision_files rf
JOIN analyses a ON a.analysis_id = rf.analysis_id,
json_each(a.payload, '$.objects') je
WHERE rf.analysis_id = ? AND json_extract(je.value, '$.kind') = 'import'
"""


def _split_logical_key(logical_key: str, project_id: str):
    prefix = project_id + "::"
    if not logical_key.startswith(prefix):
        return None
    parts = logical_key[len(prefix) :].split("::")
    if len(parts) < 3:
        return None
    return parts[0], "::".join(parts[1:-1]), parts[-1]


class ProjectQueryService:
    def __init__(self, projects, application=None):
        self.projects = projects
        self.application = application

    # -- helpers -------------------------------------------------------
    def _root(self, project_id: str) -> Path:
        return Path(self.projects._lookup_root(project_id)).resolve()

    def _revision(self, project_id: str, revision_id):
        return self.projects.revision(project_id, revision_id)

    def _rows(self, project_id: str, revision_id: str | None):
        header = self._revision(project_id, revision_id)
        store = ProjectStore(self._root(project_id))
        return header, store, store.revision_files(header.id)

    def _config(self, project_id: str):
        if self.application is None:
            return None, {}
        workbench = self.application.workbench(project_id)
        config = workbench.configurations.load()
        definitions = {d.id: d for d in workbench.catalog.definitions()}
        return config, definitions

    def _run(self, project_id: str, revision_id: str, run_id: str | None):
        """Resolve exactly one owned run bound to ``revision_id``.

        An explicit run must record the requested project revision, otherwise a
        version leak would attach another revision's evidence to this one. When
        none is given, the newest run recorded for the requested revision wins
        even if it observed nothing; legacy runs without a recorded revision are
        a coverage gap and are never assumed to match.
        """
        if self.application is None:
            if run_id is not None:
                raise KeyError("Run does not belong to the project")
            return None
        research = self.application.research(project_id)
        workbench = self.application.workbench(project_id)
        tasks = workbench.store.list("tasks", limit=1000)

        def recorded(run):
            for task in tasks:
                if task.get("run_id") == run:
                    return (
                        task.get("project_revision_id"),
                        "workbench",
                    )
            run_record = research.store.run(run)
            environment = run_record.get("environment") or {}
            return environment.get("project_revision_id"), "environment"

        if run_id is not None:
            research.store.run(run_id)  # unknown -> LookupError -> 404
            revision, source = recorded(run_id)
            if revision != revision_id:
                raise ValueError(
                    "Run does not match the requested project revision"
                )
            return run_id
        for task in tasks:
            candidate = task.get("run_id")
            if not candidate or task.get("project_revision_id") != revision_id:
                continue
            research.store.run(candidate)  # never assume a vanished run
            return candidate
        for row in research.store.runs(64):
            environment = row.get("environment") or {}
            if environment.get("project_revision_id") == revision_id:
                return row.get("id")
        return None

    def _observed(self, project_id: str, run_id: str | None):
        """Latest observation per canonical key within exactly one owned run."""
        if self.application is None or run_id is None:
            return {}
        research = self.application.research(project_id)
        snapshots = research.store.snapshots(run_id, latest=True, limit=10000)
        observed: dict = {}
        for snapshot in snapshots:
            key = snapshot.logical_key
            if not key:
                continue
            current = observed.get(key)
            if current is None or snapshot.version >= current.version:
                observed[key] = snapshot
        return observed

    def _status_map(self, project_id: str, run_id: str | None):
        """Check verdict per canonical key for one run (lightweight, no docs)."""
        statuses: dict = {}
        if self.application is None or run_id is None:
            return statuses
        workbench = self.application.workbench(project_id)
        for output in workbench.store.list_outputs(run_id=run_id, limit=1000):
            if output.get("capability") != "check":
                continue
            verdict = output.get("status")
            if verdict not in ("pass", "fail"):
                continue
            for target in output.get("targets", []):
                key = target.get("logical_key")
                if not key:
                    continue
                if verdict == "fail":
                    statuses[key] = "failed"
                elif statuses.get(key) != "failed":
                    statuses[key] = "normal"
        return statuses

    # -- tree ----------------------------------------------------------
    def tree(
        self,
        project_id: str,
        revision_id: str | None = None,
        parent_id: str | None = None,
        offset: int = 0,
        limit: int = 200,
    ) -> TreePage:
        header, _store, rows = self._rows(project_id, revision_id)
        offset = max(0, int(offset))
        limit = min(max(1, int(limit)), 1000)
        name = self.projects.project(project_id).name or project_id
        project_item = TreeItem(
            id=f"project:{project_id}",
            parent_id=None,
            kind="project",
            label=name,
            path="",
            child_count=len(rows),
            target=TargetRef(
                kind="project",
                logical_key=f"{project_id}::project::{name}",
                project_id=project_id,
                project_revision_id=header.id,
            ),
        )
        if parent_id is None:
            return TreePage(
                project_id=project_id,
                revision_id=header.id,
                items=[project_item],
                total=1,
                offset=0,
                limit=limit,
            )
        if parent_id == project_item.id:
            prefix = ""
        elif parent_id.startswith("folder:"):
            prefix = parent_id[len("folder:") :]
        else:
            return TreePage(
                project_id=project_id,
                revision_id=header.id,
                items=[],
                total=0,
                offset=offset,
                limit=limit,
            )
        folders: dict = {}
        files: list = []
        for row in rows:
            rel = row["relative_path"]
            if prefix and not rel.startswith(prefix + "/"):
                continue
            remainder = rel[len(prefix) + 1 :] if prefix else rel
            if "/" in remainder:
                name = remainder.split("/", 1)[0]
                path = f"{prefix}/{name}" if prefix else name
                folders[path] = folders.get(path, 0) + 1
            else:
                files.append(row)
        parent = project_item.id if not prefix else "folder:" + prefix
        items = [
            TreeItem(
                id="folder:" + path,
                parent_id=parent,
                kind="folder",
                label=path.rsplit("/", 1)[-1],
                path=path,
                child_count=count,
                target=TargetRef(
                    kind="folder",
                    logical_key=f"{project_id}::folder::{path}",
                    project_id=project_id,
                    project_revision_id=header.id,
                ),
            )
            for path, count in sorted(folders.items())
        ]
        items.extend(
            TreeItem(
                id=row["file_id"],
                parent_id=parent,
                kind="file",
                label=row["relative_path"].rsplit("/", 1)[-1],
                path=row["relative_path"],
                file_id=row["file_id"],
                child_count=0,
                target=TargetRef(
                    kind="file",
                    logical_key=(
                        f"{project_id}::{row['file_id']}::file::"
                        f"{row['relative_path']}"
                    ),
                    block_id=_id("file", row["file_id"]),
                    project_id=project_id,
                    file_id=row["file_id"],
                    project_revision_id=header.id,
                ),
            )
            for row in sorted(files, key=lambda item: item["relative_path"])
        )
        total = len(items)
        return TreePage(
            project_id=project_id,
            revision_id=header.id,
            items=items[offset : offset + limit],
            total=total,
            offset=offset,
            limit=limit,
        )

    # -- symbols -------------------------------------------------------
    def symbol_index(self, project_id: str, revision_id: str | None):
        header, store, rows = self._rows(project_id, revision_id)
        compact = store.compact_records([row["analysis_id"] for row in rows])
        index: list = []
        for row in rows:
            symbols = compact.get(row["analysis_id"], (None, None))[1] or []
            for position, symbol in enumerate(symbols):
                index.append(
                    {
                        "file_id": row["file_id"],
                        "relative_path": row["relative_path"],
                        "digest": row["digest"],
                        "position": position,
                        "symbol": symbol,
                    }
                )
        return header, store, index

    def symbols(
        self,
        project_id: str,
        revision_id: str | None = None,
        q: str | None = None,
        offset: int = 0,
        limit: int = 200,
    ) -> SymbolPage:
        header, store, index = self.symbol_index(project_id, revision_id)
        needle = (q or "").strip().lower()
        if needle:
            index = [
                entry
                for entry in index
                if needle in str(entry["symbol"].get("name", "")).lower()
            ]
        offset = max(0, int(offset))
        limit = min(max(1, int(limit)), 1000)
        page = index[offset : offset + limit]
        documents: dict = {}
        items: list = []
        for entry in page:
            symbol = entry["symbol"]
            if entry["file_id"] not in documents:
                try:
                    documents[entry["file_id"]] = self.projects.analysis(
                        project_id, entry["file_id"], header.id
                    )
                except (KeyError, LookupError):
                    documents[entry["file_id"]] = None
            document = documents[entry["file_id"]]
            line = end_line = 0
            logical_key = ""
            if document is not None:
                match = next(
                    (obj for obj in document.objects if obj.id == symbol.get("id")), None
                )
                if match is not None:
                    line, end_line = match.line, match.end_line
                    logical_key = match.logical_key
            items.append(
                SymbolRef(
                    name=str(symbol.get("name", "")),
                    kind=str(symbol.get("kind", "function")),
                    scope=str(symbol.get("scope", "<module>")),
                    line=line,
                    end_line=end_line,
                    logical_key=logical_key,
                    source=SourceRef(
                        path=entry["relative_path"],
                        qualname=str(symbol.get("name", "")),
                        line=line,
                        end_line=end_line,
                        digest=entry["digest"],
                        project_id=project_id,
                        file_id=entry["file_id"],
                        project_revision_id=header.id,
                    ),
                )
            )
        return SymbolPage(
            project_id=project_id,
            revision_id=header.id,
            items=items,
            total=len(index),
            offset=offset,
            limit=limit,
        )

    # -- references ----------------------------------------------------
    def references(
        self,
        project_id: str,
        revision_id: str | None = None,
        file_id: str | None = None,
        symbol: str | None = None,
        logical_key: str | None = None,
        offset: int = 0,
        limit: int = 200,
    ) -> ReferencePage:
        header, store, rows = self._rows(project_id, revision_id)
        path_of = {row["file_id"]: row["relative_path"] for row in rows}
        if file_id is not None and file_id not in path_of:
            raise KeyError("Unknown file in revision")
        compact = store.compact_records([row["analysis_id"] for row in rows])
        facts: dict = {}
        symbols: dict = {}
        module_index: dict = {}
        for row in rows:
            cached_facts, cached_symbols = compact.get(row["analysis_id"], (None, None))
            facts[row["file_id"]] = (
                FileFacts.from_json(cached_facts) if cached_facts else FileFacts()
            )
            symbols[row["file_id"]] = cached_symbols or []
            for name in json.loads(row["module_names"]) if row["module_names"] else []:
                module_index[name] = row["file_id"]
        resolver = _Resolver(
            ProjectGraphInput(
                project_id=project_id,
                project_name="",
                revision_id=header.id,
                units=[],
                analyses={},
                facts=facts,
                module_index=module_index,
                symbols=symbols,
            )
        )
        needle = (symbol or "").strip()
        wanted_key = logical_key
        items: list = []
        for row in rows:
            if file_id is not None and row["file_id"] != file_id:
                continue
            fid, rel = row["file_id"], row["relative_path"]
            record = facts[fid]
            for call in record.calls:
                resolved = resolver.resolve_call(record, call)
                target_file = target_name = target_key = None
                if resolved is not None:
                    target_file, target_name = resolved
                    if target_file:
                        target_key = self._resolved_key(
                            project_id, target_file, target_name, symbols
                        )
                name = str(call.get("attr") or call.get("name") or "")
                if needle and needle not in (name, target_name):
                    continue
                if wanted_key and target_key != wanted_key:
                    continue
                items.append(
                    ReferenceItem(
                        kind="call",
                        name=name,
                        logical_key=target_key or "",
                        provenance="inferred",
                        source=SourceRef(
                            path=rel,
                            digest=row["digest"],
                            line=int(call.get("lineno", 0)),
                            qualname=str(call.get("scope", "")),
                            project_id=project_id,
                            file_id=fid,
                            project_revision_id=header.id,
                        ),
                        target=(
                            SourceRef(
                                path=path_of.get(target_file, ""),
                                project_id=project_id,
                                file_id=target_file,
                                project_revision_id=header.id,
                            )
                            if target_file
                            else None
                        ),
                    )
                )
            for imp in record.imports:
                base = self._resolve_relative(
                    imp.get("module", ""), imp.get("level", 0), record.package
                )
                target_file = module_index.get(base)
                target = imp.get("name") or imp.get("local")
                target_key = None
                if target_file:
                    sub = f"{base}.{target}" if target and imp.get("name") else base
                    owner = module_index.get(sub, target_file)
                    target_key = self._resolved_key(
                        project_id, owner, target, symbols
                    )
                    target_file = owner
                name = str(imp.get("name") or imp.get("local") or "")
                if needle and needle != name:
                    continue
                if wanted_key and target_key != wanted_key:
                    continue
                items.append(
                    ReferenceItem(
                        kind="import",
                        name=name,
                        logical_key=target_key or "",
                        provenance="inferred",
                        source=SourceRef(
                            path=rel,
                            digest=row["digest"],
                            line=0,
                            project_id=project_id,
                            file_id=fid,
                            project_revision_id=header.id,
                        ),
                        target=(
                            SourceRef(
                                path=path_of.get(target_file, ""),
                                project_id=project_id,
                                file_id=target_file,
                                project_revision_id=header.id,
                            )
                            if target_file
                            else None
                        ),
                    )
                )
        # Import statement lines come from the persisted import objects.
        import_lines = self._import_lines(store, rows)
        for item in items:
            if item.kind == "import":
                key = (item.source.file_id, item.name)
                if key in import_lines:
                    item.source = item.source.model_copy(
                        update={"line": import_lines[key]}
                    )
        # Enrich the bounded page with exact target definition positions.
        offset = max(0, int(offset))
        limit = min(max(1, int(limit)), 1000)
        page = items[offset : offset + limit]
        self._enrich_targets(project_id, header.id, page, symbols)
        return ReferencePage(
            project_id=project_id,
            revision_id=header.id,
            items=page,
            total=len(items),
            offset=offset,
            limit=limit,
        )

    @staticmethod
    def _resolve_relative(module: str, level: int, package: str) -> str:
        if not level:
            return module
        parts = package.split(".") if package else []
        if level > 1:
            parts = parts[: max(0, len(parts) - (level - 1))]
        prefix = ".".join(parts)
        return f"{prefix}.{module}" if prefix and module else (prefix or module)

    @staticmethod
    def _resolved_key(project_id, target_file, target_name, symbols):
        if not target_file or not target_name:
            return None
        for symbol in symbols.get(target_file, []):
            if symbol.get("name") == target_name:
                return f"{project_id}::{target_file}::{symbol.get('scope') or '<module>'}::{target_name}"
        return f"{project_id}::{target_file}::<module>::{target_name}"

    def _import_lines(self, store, rows):
        lines: dict = {}
        with store.connect() as conn:
            for row in rows:
                cursor = conn.execute(_IMPORT_SQL, (row["analysis_id"],))
                for entry in cursor.fetchall():
                    lines[(row["file_id"], entry["name"])] = int(entry["line"] or 0)
        return lines

    def _enrich_targets(self, project_id, revision_id, page, symbols):
        files = {
            item.target.file_id
            for item in page
            if item.target is not None and item.target.file_id
        }
        loaded: dict = {}
        for fid in files:
            try:
                loaded[fid] = self.projects.analysis(project_id, fid, revision_id)
            except (KeyError, LookupError):
                loaded[fid] = None
        for index, item in enumerate(page):
            if item.target is None or not item.target.file_id:
                continue
            document = loaded.get(item.target.file_id)
            if document is None:
                continue
            match = next(
                (obj for obj in document.objects if obj.name == item.name),
                None,
            )
            if match is None:
                continue
            page[index] = item.model_copy(
                update={
                    "target": item.target.model_copy(
                        update={
                            "logical_key": match.logical_key or item.target.logical_key,
                            "object_id": match.id,
                            "block_id": match.block_id or None,
                        }
                    ),
                    "target_line": match.line,
                }
            )

    # -- objects -------------------------------------------------------
    def objects(
        self,
        project_id: str,
        revision_id: str | None = None,
        file_id: str | None = None,
        scope_id: str | None = None,
        query: str | None = None,
        kind: str = "variables",
        probe_status: str = "all",
        run_id: str | None = None,
        offset: int = 0,
        limit: int = 200,
    ) -> ObjectPage:
        header, store, rows = self._rows(project_id, revision_id)
        known = {row["file_id"] for row in rows}
        if file_id is not None and file_id not in known:
            raise KeyError("Unknown file in revision")
        if scope_id is not None and scope_id not in known and not any(
            row["relative_path"] == scope_id for row in rows
        ):
            # scope may be a folder prefix; leave the SQL filter to decide.
            pass
        chosen_run = self._run(project_id, header.id, run_id)
        observed = self._observed(project_id, chosen_run)
        statuses = self._status_map(project_id, chosen_run)
        config, definitions = self._config(project_id)
        kinds = (
            "IN ('assignment', 'parameter')"
            if kind != "all"
            else "IN ('assignment', 'parameter', 'function', 'class', 'step')"
        )
        clauses = []
        parameters: list = [header.id]
        if file_id is not None:
            clauses.append("rf.file_id = ?")
            parameters.append(file_id)
        if scope_id:
            clauses.append(
                "(json_extract(je.value, '$.scope') = ? OR rf.relative_path LIKE ? ESCAPE '\\')"
            )
            parameters.extend((scope_id, scope_id.rstrip("/") + "/%"))
        needle = (query or "").strip()
        if needle:
            clauses.append("json_extract(je.value, '$.name') LIKE ? ESCAPE '\\'")
            escaped = (
                needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            )
            parameters.append("%" + escaped + "%")
        extra = ("AND " + " AND ".join(clauses)) if clauses else ""
        sql = _ASSIGNMENT_SQL.format(kind=kinds, extra=extra)
        with store.connect() as conn:
            records = [dict(row) for row in conn.execute(sql, tuple(parameters))]
        entries: list = []
        for record in records:
            logical_key = record["logical_key"] or (
                f"{project_id}::{record['file_id']}::{record['scope']}::"
                f"{record['name']}"
            )
            status = statuses.get(logical_key, "unknown")
            if probe_status == "failed" and status != "failed":
                continue
            if probe_status == "normal" and status != "normal":
                continue
            entries.append((record, logical_key, status))
        entries.sort(
            key=lambda entry: (
                entry[0]["relative_path"] or "",
                int(entry[0]["line"] or 0),
                entry[0]["name"] or "",
            )
        )
        offset = max(0, int(offset))
        limit = min(max(1, int(limit)), 1000)
        page = entries[offset : offset + limit]
        # Only the bounded page instantiates per-file analyses for probe counts.
        documents: dict = {}
        items: list = []
        for record, logical_key, status in page:
            if config is not None and record["analysis_id"] not in documents:
                try:
                    documents[record["analysis_id"]] = self.projects.analysis(
                        project_id, record["file_id"], header.id
                    )
                except (KeyError, LookupError):
                    documents[record["analysis_id"]] = None
            document = documents.get(record["analysis_id"])
            probe_count = self._probe_count(
                config, definitions, document, logical_key, record
            )
            object_kind = record["kind"] or "assignment"
            target_kind = (
                "function"
                if object_kind in ("function", "class")
                else ("operation" if object_kind == "step" else "data")
            )
            block_id = record["block_id"] or self._find_block(
                document, record["object_id"]
            )
            snapshot = observed.get(logical_key)
            items.append(
                ObjectItem(
                    target=TargetRef(
                        kind=target_kind,
                        logical_key=logical_key,
                        object_id=record["object_id"],
                        block_id=block_id,
                        analysis_id=record["analysis_id"],
                        run_id=chosen_run,
                        snapshot_id=snapshot.id if snapshot else None,
                        project_id=project_id,
                        file_id=record["file_id"],
                        project_revision_id=header.id,
                    ),
                    name=record["name"] or "",
                    kind=object_kind,
                    line=int(record["line"] or 0),
                    end_line=int(record["end_line"] or record["line"] or 0),
                    type=snapshot.descriptor.type_name if snapshot else None,
                    shape=snapshot.descriptor.shape if snapshot else None,
                    probe_count=probe_count,
                    probe_status=status,
                    source=SourceRef(
                        path=record["relative_path"],
                        qualname=record["qualname"] or record["name"] or "",
                        line=int(record["line"] or 0),
                        end_line=int(record["end_line"] or record["line"] or 0),
                        digest=record["digest"],
                        code=record["code"] or "",
                        project_id=project_id,
                        file_id=record["file_id"],
                        project_revision_id=header.id,
                        scope_id=record["scope"] or "",
                    ),
                )
            )
        return ObjectPage(
            project_id=project_id,
            revision_id=header.id,
            items=items,
            total=len(entries),
            offset=offset,
            limit=limit,
        )
    @staticmethod
    def _find_block(document, object_id):
        if document is None:
            return None
        for block in document.graph.blocks:
            if block.source_object_id == object_id:
                return block.id
        return None

    def _probe_count(self, config, definitions, document, logical_key, record):
        if config is None or document is None:
            return 0
        target = next(
            (
                TargetRef(
                    kind="data",
                    logical_key=logical_key,
                    object_id=record["object_id"],
                    block_id=record["block_id"] or None,
                    analysis_id=record["analysis_id"],
                )
                for _ in (0,)
            ),
            None,
        )
        if target is None:
            return 0
        count = 0
        for instance in config.probes:
            if not instance.enabled:
                continue
            definition = definitions.get(instance.definition_id)
            if definition is None:
                continue
            if target.kind not in definition.supported_targets:
                continue
            try:
                if matches_instance(instance, target, document):
                    count += 1
            except (ValueError, KeyError):
                continue
        return count

    # -- graph ---------------------------------------------------------
    def graph(
        self,
        project_id: str,
        revision_id: str | None = None,
        scope_id: str | None = None,
        view: str = "code",
        limit: int = 350,
    ) -> ProjectGraphSlice:
        limit = min(max(1, int(limit)), 350)
        view = "data" if view == "data" else "code"
        header, store, rows = self._rows(project_id, revision_id)
        base = self.projects.graph(
            project_id, header.id, scope_id=scope_id, view=view, limit=limit
        )
        graph = base.graph
        if scope_id and scope_id in {row["file_id"] for row in rows}:
            graph = self._with_boundaries(
                project_id, header.id, scope_id, graph, rows, store
            )
        graph = self._project_view(graph, view)
        graph = self._enforce_limit(graph, limit)
        return ProjectGraphSlice(
            graph=graph,
            project_id=project_id,
            revision_id=header.id,
            scope_id=scope_id,
            view=view,
            omitted_count=base.omitted_count,
        )

    @staticmethod
    def _project_view(graph: SemanticGraph, view: str) -> SemanticGraph:
        node_kinds = CODE_NODE_KINDS if view == "code" else DATA_NODE_KINDS
        edge_kinds = CODE_EDGE_KINDS if view == "code" else DATA_EDGE_KINDS
        blocks = list(graph.blocks)
        nodes = [node for node in graph.nodes if node.kind in node_kinds]
        known = {block.id for block in blocks} | {node.id for node in nodes}
        edges = [
            edge
            for edge in graph.edges
            if edge.kind in edge_kinds and edge.source in known and edge.target in known
        ]
        if view == "code":
            edges.extend(ProjectQueryService._calculation_edges(graph, nodes))
            seen: set = set()
            deduped: list = []
            for edge in edges:
                key = (edge.source, edge.target, edge.kind)
                if key in seen:
                    continue
                seen.add(key)
                deduped.append(edge)
            edges = deduped
        for block in blocks:
            block.members = [member for member in block.members if member in known]
        return graph.model_copy(
            update={"blocks": blocks, "nodes": nodes, "edges": edges}
        )

    @staticmethod
    def _calculation_edges(graph: SemanticGraph, nodes) -> list:
        """Project hidden value nodes into visible calculation dependencies.

        A variable is not a code plate, so an operation -> data -> operation
        dependency would vanish once the code view drops data/parameter nodes.
        Rather than enumerate every simple path (exponential across a diamond),
        each visible origin is traversed forward through transparent value nodes
        to collect its destinations, then each destination is traversed
        backwards so the original edge ids of every converging path are unioned.
        Cycle-safe, keyed by node identity, never by name or line order.
        """
        visible = {node.id: node for node in nodes}
        transparent = {
            node.id
            for node in graph.nodes
            if node.kind in _TRANSPARENT_NODE_KINDS
        }
        forward: dict = {}
        backward: dict = {}
        for edge in graph.edges:
            if edge.kind in _DATA_FLOW_EDGE_KINDS:
                forward.setdefault(edge.source, []).append(edge)
                backward.setdefault(edge.target, []).append(edge)
        projections: dict = {}
        for origin, node in visible.items():
            if node.kind not in _CALCULATION_NODE_KINDS:
                continue
            reachable = {origin}
            destinations: list = []
            stack = [origin]
            while stack:
                current = stack.pop()
                for edge in forward.get(current, ()):
                    target = edge.target
                    if target in reachable:
                        continue
                    if target in transparent:
                        reachable.add(target)
                        stack.append(target)
                    elif target in visible and target != origin:
                        reachable.add(target)
                        destinations.append(target)
            for destination in destinations:
                ids: list = []
                seen = {destination}
                pending = [destination]
                terminal = None
                origin_label = ""
                while pending:
                    current = pending.pop()
                    for edge in backward.get(current, ()):
                        source = edge.source
                        if source != origin and source not in transparent:
                            continue
                        if source not in reachable:
                            continue
                        if edge.id not in ids:
                            ids.append(edge.id)
                            if current == destination and terminal is None:
                                terminal = edge
                            if source == origin and not origin_label:
                                origin_label = edge.label or ""
                        if source != origin and source not in seen:
                            seen.add(source)
                            pending.append(source)
                if not ids:
                    continue
                existing = projections.get((origin, destination))
                if existing is None:
                    projections[(origin, destination)] = GraphEdge(
                        id=_id("calculation", origin, destination),
                        source=origin,
                        target=destination,
                        kind="data",
                        label=(terminal.label if terminal else "") or origin_label,
                        provenance=terminal.provenance if terminal else "inferred",
                        original_ids=ids,
                        count=len(ids),
                    )
                else:
                    for original in ids:
                        if original not in existing.original_ids:
                            existing.original_ids.append(original)
                    existing.count = len(existing.original_ids)
        return list(projections.values())

    def _with_boundaries(self, project_id, revision_id, scope_id, graph, rows, store):
        path_of = {row["file_id"]: row["relative_path"] for row in rows}
        project_block = graph.roots[0] if graph.roots else None
        scope_block = _id("file", scope_id)
        block_ids = {block.id for block in graph.blocks}
        node_ids = {node.id for node in graph.nodes}
        blocks = list(graph.blocks)
        edges = list(graph.edges)
        compact = store.compact_records([row["analysis_id"] for row in rows])
        facts: dict = {}
        symbols: dict = {}
        module_index: dict = {}
        for row in rows:
            cached_facts, cached_symbols = compact.get(row["analysis_id"], (None, None))
            facts[row["file_id"]] = (
                FileFacts.from_json(cached_facts) if cached_facts else None
            )
            symbols[row["file_id"]] = cached_symbols or []
            for name in json.loads(row["module_names"]) if row["module_names"] else []:
                module_index[name] = row["file_id"]
        document = None
        try:
            document = self.projects.analysis(project_id, scope_id, revision_id)
        except (KeyError, LookupError):
            document = None
        resolver = _Resolver(
            ProjectGraphInput(
                project_id=project_id,
                project_name="",
                revision_id=revision_id,
                units=[],
                analyses={scope_id: document} if document else {},
                facts={fid: value for fid, value in facts.items() if value},
                module_index=module_index,
                symbols=symbols,
            )
        )
        external: dict = {}

        def boundary_block(file_id):
            if file_id in external:
                return external[file_id].id
            block_id = _id("file", file_id)
            if block_id in block_ids:
                return block_id
            rel = path_of.get(file_id, file_id)
            block = GraphBlock(
                id=block_id,
                logical_key=f"{project_id}::{file_id}::file::{rel}",
                kind="file",
                label=rel,
                parent_id=project_block,
                source=SourceRef(
                    path=rel,
                    project_id=project_id,
                    file_id=file_id,
                    project_revision_id=revision_id,
                ),
                runtime_coverage="partial",
                members=[],
            )
            external[file_id] = block
            return block_id

        def add_edge(source, target, kind, label, original_ids, direction):
            if source == target:
                return
            edges.append(
                GraphEdge(
                    id=_id("boundary", source, target, kind, label),
                    source=source,
                    target=target,
                    kind=kind,
                    label=label,
                    provenance="inferred",
                    original_ids=list(original_ids),
                    count=max(1, len(original_ids)),
                    source_port=None,
                    target_port=direction,
                )
            )

        for fid, record in facts.items():
            if record is None:
                continue
            for call in record.calls:
                resolved = resolver.resolve_call(record, call)
                if resolved is None:
                    continue
                target_file, target_name = resolved
                if not target_file or not target_name:
                    continue
                name = str(call.get("attr") or call.get("name") or "")
                label = target_name
                if fid == scope_id and target_file != scope_id:
                    edge_id = _id(
                        "e", scope_block, _id("file", target_file), "call", label
                    )
                    add_edge(
                        scope_block,
                        boundary_block(target_file),
                        "call",
                        label,
                        [edge_id],
                        "out",
                    )
                elif target_file == scope_id and fid != scope_id:
                    edge_id = _id(
                        "e", _id("file", fid), scope_block, "call", label
                    )
                    add_edge(
                        boundary_block(fid),
                        scope_block,
                        "call",
                        label,
                        [edge_id],
                        "in",
                    )
        for rel in store.relationships(revision_id):
            source, target = rel["source_file_id"], rel["target_file_id"]
            kind = rel["kind"] if rel["kind"] in ("call", "import") else "block"
            if source == scope_id and target != scope_id:
                add_edge(
                    scope_block,
                    boundary_block(target),
                    "block",
                    "import",
                    [rel["kind"] + ":" + str(rel.get("payload") or "")],
                    "out",
                )
            elif target == scope_id and source != scope_id:
                add_edge(
                    boundary_block(source),
                    scope_block,
                    "block",
                    "import",
                    [rel["kind"] + ":" + str(rel.get("payload") or "")],
                    "in",
                )
        blocks.extend(external.values())
        known = {block.id for block in blocks} | set(node_ids)
        edges = [
            edge for edge in edges if edge.source in known and edge.target in known
        ]
        for block in blocks:
            block.members = [member for member in block.members if member in known]
            if block.parent_id is not None and block.parent_id not in known:
                block.parent_id = None
        return graph.model_copy(
            update={"blocks": blocks, "nodes": graph.nodes, "edges": edges}
        )

    @staticmethod
    def _enforce_limit(graph: SemanticGraph, limit: int) -> SemanticGraph:
        blocks = list(graph.blocks)
        nodes = list(graph.nodes)
        edges = list(graph.edges)
        while len(blocks) + len(nodes) > limit:
            removable = next(
                (
                    block
                    for block in reversed(blocks)
                    if block.kind == "file"
                    and block.id not in graph.roots
                    and block.parent_id is not None
                    and block.runtime_coverage == "partial"
                ),
                None,
            )
            if removable is not None:
                blocks.remove(removable)
                continue
            if nodes:
                nodes.pop()
                continue
            if len(blocks) > 1:
                blocks.pop()
                continue
            break
        known = {block.id for block in blocks} | {node.id for node in nodes}
        edges = [
            edge for edge in edges if edge.source in known and edge.target in known
        ]
        for block in blocks:
            block.members = [member for member in block.members if member in known]
            if block.parent_id is not None and block.parent_id not in known:
                block.parent_id = None
        roots = [root for root in graph.roots if root in known]
        if not roots and blocks:
            roots = [blocks[0].id]
        return graph.model_copy(
            update={"blocks": blocks, "nodes": nodes, "edges": edges, "roots": roots}
        )







