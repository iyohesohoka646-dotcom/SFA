"""ProjectService: registers local project roots and indexes them inertly."""

from __future__ import annotations

import ast
import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import yaml

from ...storage import atomic_write
from ..agent.privacy import clean_text
from ..workbench.analysis import analyze_source
from ..workbench.models import AnalysisDocument
from . import discovery, resolver
from .models import (
    FilePage,
    ProjectGraphSlice,
    ProjectRevision,
    ResearchProject,
    SourceUnit,
    ProjectSection,
)
from .resolver import FileFacts
from .store import ProjectStore

MAX_ARCHIVE_BYTES = 10 * 1024 * 1024

# Above this many files an overview graph is built from compact index records
# (module/import/symbol facts) instead of loading every full analysis document.
DETAIL_FILE_LIMIT = 64


@dataclass(frozen=True)
class GraphScope:
    """A resolved, existing graph identity for one published revision."""

    kind: str = "project"
    file_id: str | None = None
    folder: str | None = None
    block_id: str | None = None
    graph_scope_id: str | None = None


def _file_id(project_id: str, relative_path: str) -> str:
    return "f" + hashlib.sha256(
        f"{project_id}\0{relative_path}".encode("utf-8")
    ).hexdigest()[:20]


class ProjectService:
    def __init__(self, host_root: Path):
        self.host_root = Path(host_root).resolve()
        self.state = self.host_root / ".cdaf" / "research"
        self.state.mkdir(parents=True, exist_ok=True)
        self.registry = self.state / "host.sqlite3"
        self._closed = False
        with self._connect_registry() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS projects(project_id TEXT PRIMARY KEY, root TEXT, name TEXT)"
            )

    @contextmanager
    def _connect_registry(self):
        conn = sqlite3.connect(self.registry, timeout=15)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    # -- registration --------------------------------------------------
    def _register(self, project: ResearchProject) -> None:
        with self._connect_registry() as conn:
            conn.execute(
                "INSERT INTO projects(project_id,root,name) VALUES(?,?,?) "
                "ON CONFLICT(project_id) DO UPDATE SET root=excluded.root, name=excluded.name",
                (project.id, project.root, project.name),
            )

    def _lookup_root(self, project_id: str) -> str:
        with self._connect_registry() as conn:
            row = conn.execute(
                "SELECT root FROM projects WHERE project_id=?", (project_id,)
            ).fetchone()
        if not row:
            raise KeyError(f"Unknown project: {project_id}")
        return row["root"]

    def _registered_root(self, project_id: str):
        with self._connect_registry() as conn:
            row = conn.execute(
                "SELECT root FROM projects WHERE project_id=?", (project_id,)
            ).fetchone()
        return row["root"] if row else None

    # -- authored section ---------------------------------------------
    def _read_raw(self, root: Path) -> dict:
        path = root / "workbench.yaml"
        if not path.exists():
            return {}
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}

    def _ensure_section(self, root: Path) -> ProjectSection:
        raw = self._read_raw(root)
        section = raw.get("project")
        changed = False
        if not isinstance(section, dict):
            section = {}
            changed = True
        if not section.get("id"):
            section["id"] = uuid.uuid4().hex
            changed = True
        if not section.get("name"):
            section["name"] = root.name
            changed = True
        section.setdefault("source_roots", ["."])
        section.setdefault("include", ["**/*.py"])
        if "exclude" not in section:
            section["exclude"] = []
            changed = True
        raw["project"] = section
        target = root / "workbench.yaml"
        if changed:
            raw.setdefault("protocol_version", 3)
            if target.exists():
                backup = target.with_name(target.name + ".bak")
                if not backup.exists():
                    # Preserve authored bytes exactly; never overwrite an earlier backup.
                    atomic_write(backup, target.read_bytes())
            atomic_write(target, yaml.safe_dump(raw, allow_unicode=True, sort_keys=False))
        return ProjectSection.model_validate(dict(section))

    def _project_model(self, root: Path, store: ProjectStore) -> ResearchProject:
        section = self._ensure_section(root)
        latest = store.latest_revision(section.id)
        from ..workbench.models import RunConfiguration

        raw = self._read_raw(root)
        configs = [
            RunConfiguration.model_validate(item)
            for item in raw.get("run_configurations", [])
        ]
        if not configs and section.run_configurations:
            configs = list(section.run_configurations)
        return ResearchProject(
            id=section.id,
            root=str(root),
            name=section.name,
            latest_revision_id=latest["revision_id"] if latest else None,
            source_roots=list(section.source_roots),
            include=list(section.include),
            exclude=list(section.exclude),
            run_configurations=configs,
        )

    # -- public API ----------------------------------------------------
    def open(self, path) -> ResearchProject:
        project, _ = self._prepare_open(path)
        self._register(project)
        return project

    def _prepare_open(self, path):
        """Resolve a project without mutating the registry.

        Returns ``(project, previous_root)``. ``previous_root`` is set only when
        ``path`` is the same project UUID recorded at a different root (a genuine
        relocation to a moved folder); a duplicate copy at another *existing*
        root is still refused here before any registry change.
        """
        root = Path(path).expanduser()
        if not root.is_dir():
            raise ValueError("Project root does not exist or is not a directory")
        root = root.resolve()
        raw = self._read_raw(root)
        section = raw.get("project") if isinstance(raw, dict) else None
        existing_id = section.get("id") if isinstance(section, dict) else None
        previous_root = None
        if existing_id:
            registered = self._registered_root(existing_id)
            if registered is not None:
                registered_path = Path(registered).resolve()
                if registered_path != root and registered_path.is_dir():
                    raise ValueError(
                        "Project UUID is already registered at another existing root; "
                        "refusing to retarget it. Remove the duplicate copy or open the original."
                    )
                if registered_path != root:
                    previous_root = registered_path
        store = ProjectStore(root)
        project = self._project_model(root, store)
        return project, previous_root

    def project(self, project_id: str) -> ResearchProject:
        root = Path(self._lookup_root(project_id)).resolve()
        return self._project_model(root, ProjectStore(root))

    def index(self, project_id: str, cancel=None, progress=None) -> ProjectRevision:
        root = Path(self._lookup_root(project_id)).resolve()
        store = ProjectStore(root)
        section = self._ensure_section(root)
        project_id = section.id

        def check_cancel():
            if cancel is not None and cancel.is_set():
                raise InterruptedError("Project index cancelled")

        check_cancel()
        files, scan_diagnostics = discovery.discover_files(
            root, section, cancel=cancel, progress=progress
        )
        latest = store.latest_revision(project_id)
        parent = latest["revision_id"] if latest else None

        previous = {row["relative_path"]: row for row in store.all_files(project_id)}
        discovered = {f.relative_path for f in files}
        rebind_pool: dict = {}
        for rel, row in previous.items():
            if rel not in discovered:
                rebind_pool.setdefault(row["digest"], []).append(row)
        diagnostics = list(scan_diagnostics)
        assignments: dict = {}
        used_ids: set = set()
        for candidate in files:
            existing = previous.get(candidate.relative_path)
            if existing:
                fid = existing["file_id"]
            else:
                matches = [
                    row
                    for row in rebind_pool.get(candidate.digest, [])
                    if row["file_id"] not in used_ids
                ]
                if len(matches) == 1:
                    fid = matches[0]["file_id"]
                    diagnostics.append(
                        f"Rebound identity for renamed file {matches[0]['relative_path']} -> {candidate.relative_path}"
                    )
                elif len(matches) > 1:
                    fid = _file_id(project_id, candidate.relative_path)
                    diagnostics.append(
                        f"Ambiguous rename for {candidate.relative_path}; a new identity was assigned"
                    )
                else:
                    fid = _file_id(project_id, candidate.relative_path)
            used_ids.add(fid)
            assignments[candidate.relative_path] = fid

        module_index: dict = {}
        for candidate in files:
            for name in candidate.module_names:
                owner = module_index.get(name)
                fid = assignments[candidate.relative_path]
                if owner is not None and owner != fid:
                    diagnostics.append(
                        f"Ambiguous module name {name} shared by multiple files; resolution disabled"
                    )
                    module_index[name] = None
                elif name not in module_index:
                    module_index[name] = fid
        module_index = {k: v for k, v in module_index.items() if v}

        with store.session():
            return self._write_revision(
                store,
                project_id,
                files,
                previous,
                assignments,
                module_index,
                diagnostics,
                parent,
                check_cancel,
                progress,
            )

    def _write_revision(
        self,
        store,
        project_id,
        files,
        previous,
        assignments,
        module_index,
        diagnostics,
        parent,
        check_cancel,
        progress=None,
    ) -> ProjectRevision:
        """Write caches and publish one revision inside a single transaction."""
        revision_files: list = []
        facts: dict = {}
        parsed = reused = 0
        analysis_ids = {
            candidate.relative_path: "a" + hashlib.sha256(
                f"{candidate.relative_path}\0{candidate.digest}".encode("utf-8")
            ).hexdigest()[:24]
            for candidate in files
        }
        # One bulk query replaces two per-file connections during reuse checks.
        compact = store.compact_records(analysis_ids.values())
        for candidate in files:
            check_cancel()
            fid = assignments[candidate.relative_path]
            rel = candidate.relative_path
            module = candidate.module_names[0] if candidate.module_names else ""
            is_init = rel.endswith("__init__.py")
            analysis_id = analysis_ids[rel]
            previous_row = previous.get(rel)
            cached_facts, cached_symbols = compact.get(analysis_id, (None, None))
            unchanged = (
                previous_row is not None
                and previous_row.get("digest") == candidate.digest
                and previous_row.get("analysis_id") == analysis_id
                and cached_facts is not None
                and cached_symbols is not None
            )
            if unchanged:
                # Same published bytes: reuse compact records; never load the
                # full analysis document for this file.
                fact = FileFacts.from_json(cached_facts)
                fact.file_id = fid
                fact.relative_path = rel
                status = previous_row.get("status", "parsed")
                file_diagnostics = (
                    json.loads(previous_row["diagnostics"])
                    if previous_row.get("diagnostics")
                    else []
                )
                reused += 1
                if progress is not None:
                    progress(
                        {
                            "stage": "parse",
                            "completed": parsed + reused,
                            "total": len(files),
                            "file": rel,
                            "parsed": parsed,
                            "reused": reused,
                        }
                    )
            else:
                from ..agent.source import read_source

                source = read_source(candidate.path)
                if source.digest != candidate.digest:
                    raise RuntimeError(
                        f"Source changed during indexing: {rel}; re-open the project"
                    )
                text = source.text
                document = analyze_source(candidate.path)
                if document.source_digest != candidate.digest:
                    raise RuntimeError(f"Analyzed digest mismatch for {rel}")
                document = self._rebase(document, project_id, fid, rel)
                store.put_source(candidate.digest, clean_text(text, MAX_ARCHIVE_BYTES))
                store.put_analysis(
                    analysis_id, candidate.digest, document.model_dump(mode="json")
                )
                store.put_symbols(analysis_id, _compact_symbols(document))
                try:
                    fact = resolver.scan(ast.parse(text), module=module, is_init=is_init)
                except SyntaxError:
                    fact = FileFacts(module=module)
                fact.file_id = fid
                fact.relative_path = rel
                store.put_facts(analysis_id, fact.to_json())
                parsed += 1
                if progress is not None:
                    progress(
                        {
                            "stage": "parse",
                            "completed": parsed + reused,
                            "total": len(files),
                            "file": rel,
                            "parsed": parsed,
                            "reused": reused,
                        }
                    )
            if not unchanged:
                status = "error" if document.diagnostics and not document.objects else "parsed"
                file_diagnostics = list(document.diagnostics)
            facts[fid] = fact
            revision_files.append(
                {
                    "file_id": fid,
                    "relative_path": rel,
                    "digest": candidate.digest,
                    "analysis_id": analysis_id,
                    "module_names": candidate.module_names,
                    "status": status,
                    "diagnostics": file_diagnostics,
                }
            )

        relationships = self._relationships(facts, assignments, module_index)
        check_cancel()
        revision = {
            "id": uuid.uuid4().hex,
            "project_id": project_id,
            "parent_revision_id": parent,
            "files_count": len(revision_files),
            "parsed_files": parsed,
            "reused_files": reused,
            "diagnostics": diagnostics,
        }
        store.publish(project_id, revision, revision_files, relationships)
        return ProjectRevision(**revision)

    def _rebase(self, document, project_id, file_id, relative_path):
        object_key = {obj.id: f"{project_id}::{file_id}::{obj.scope}::{obj.name}" for obj in document.objects}
        for obj in document.objects:
            obj.path = relative_path
            obj.logical_key = object_key[obj.id]
        document.path = relative_path
        for block in document.graph.blocks:
            block.logical_key = object_key.get(
                block.source_object_id or "", f"{project_id}::{file_id}::{block.kind}::{block.label}"
            )
            block.source = self._stamp_ref(block.source, project_id, file_id)
        for node in document.graph.nodes:
            node.logical_key = object_key.get(
                node.source_object_id or "", f"{project_id}::{file_id}::{node.kind}::{node.label}"
            )
            node.source = self._stamp_ref(node.source, project_id, file_id)
        for item in document.graph.coverage:
            item.source = self._stamp_ref(item.source, project_id, file_id)
        return document

    @staticmethod
    def _stamp_ref(ref, project_id, file_id):
        if ref is None:
            return None
        return ref.model_copy(update={"project_id": project_id, "file_id": file_id})

    def _relationships(self, facts, assignments, module_index):
        rows = []
        for fid, fact in facts.items():
            for imp in fact.imports:
                base = resolver._resolve_relative(imp["module"], imp["level"], fact.package)
                target = module_index.get(base)
                if target and target != fid:
                    rows.append(
                        {
                            "source_file_id": fid,
                            "target_file_id": target,
                            "kind": "import",
                            "provenance": "inferred",
                            "payload": {"name": imp["local"]},
                        }
                    )
        return rows

    # -- reads ---------------------------------------------------------
    def _header(self, store, project_id, revision_id):
        row = (
            store.get_revision(revision_id)
            if revision_id
            else store.latest_revision(project_id)
        )
        if row and row["project_id"] != project_id:
            raise KeyError("Revision does not belong to the requested project")
        return row

    def revision(self, project_id: str, revision_id: str | None = None) -> ProjectRevision:
        store = ProjectStore(Path(self._lookup_root(project_id)).resolve())
        row = self._header(store, project_id, revision_id)
        if not row:
            raise KeyError("Project has no published revision")
        return ProjectRevision(
            id=row["revision_id"],
            project_id=row["project_id"],
            parent_revision_id=row["parent_id"],
            files_count=row["files_count"],
            parsed_files=row["parsed_files"],
            reused_files=row["reused_files"],
            diagnostics=json.loads(row["diagnostics"]) if row["diagnostics"] else [],
        )

    def files(
        self, project_id: str, revision_id: str | None = None, offset: int = 0, limit: int = 200
    ) -> FilePage:
        store = ProjectStore(Path(self._lookup_root(project_id)).resolve())
        header = self._header(store, project_id, revision_id)
        if not header:
            return FilePage(project_id=project_id, revision_id=revision_id or "")
        rows = store.revision_files(header["revision_id"])
        total = len(rows)
        offset = max(0, int(offset))
        limit = min(max(1, int(limit)), 1000)
        items = [
            SourceUnit(
                id=row["file_id"],
                relative_path=row["relative_path"],
                digest=row["digest"],
                analysis_id=row["analysis_id"],
                module_names=json.loads(row["module_names"]) if row["module_names"] else [],
                status=row["status"],
                diagnostics=json.loads(row["diagnostics"]) if row["diagnostics"] else [],
            )
            for row in rows[offset : offset + limit]
        ]
        return FilePage(
            items=items,
            total=total,
            offset=offset,
            limit=limit,
            project_id=header["project_id"],
            revision_id=header["revision_id"],
        )

    def analysis(self, project_id: str, file_id: str, revision_id: str | None = None) -> AnalysisDocument:
        store = ProjectStore(Path(self._lookup_root(project_id)).resolve())
        header = self._header(store, project_id, revision_id)
        if not header:
            raise KeyError("Project has no published revision")
        row = store.revision_file(header["revision_id"], file_id)
        if not row:
            raise KeyError("Unknown file in revision")
        payload = store.get_analysis(row["analysis_id"])
        if payload is None:
            raise KeyError("Archived analysis is unavailable")
        document = AnalysisDocument.model_validate(payload)
        rid = header["revision_id"]
        for block in document.graph.blocks:
            block.source = self._with_revision(block.source, rid)
        for node in document.graph.nodes:
            node.source = self._with_revision(node.source, rid)
        for item in document.graph.coverage:
            item.source = self._with_revision(item.source, rid)
        return document

    @staticmethod
    def _with_revision(ref, revision_id):
        if ref is None:
            return None
        return ref.model_copy(update={"project_revision_id": revision_id})

    def source(self, project_id: str, file_id: str, revision_id: str | None = None) -> dict:
        store = ProjectStore(Path(self._lookup_root(project_id)).resolve())
        header = self._header(store, project_id, revision_id)
        if not header:
            raise KeyError("Project has no published revision")
        row = store.revision_file(header["revision_id"], file_id)
        if not row:
            raise KeyError("Unknown file in revision")
        return {
            "path": row["relative_path"],
            "digest": row["digest"],
            "code": store.get_source(row["digest"]),
            "file_id": file_id,
            "revision_id": header["revision_id"],
            "project_id": header["project_id"],
        }

    def _revision_row_for_analysis(self, store, header, analysis_id: str):
        for row in store.revision_files(header["revision_id"]):
            if row["analysis_id"] == analysis_id:
                return row
        return None

    def analysis_by_id(
        self, project_id: str, analysis_id: str, revision_id: str | None = None
    ) -> AnalysisDocument:
        """Bounded lookup of an indexed per-file analysis by its stable ID."""
        store = ProjectStore(Path(self._lookup_root(project_id)).resolve())
        header = self._header(store, project_id, revision_id)
        if not header:
            raise KeyError("Project has no published revision")
        row = self._revision_row_for_analysis(store, header, analysis_id)
        if not row:
            raise KeyError("Unknown analysis in revision")
        return self.analysis(project_id, row["file_id"], header["revision_id"])

    def source_by_analysis_id(
        self, project_id: str, analysis_id: str, revision_id: str | None = None
    ) -> dict:
        store = ProjectStore(Path(self._lookup_root(project_id)).resolve())
        header = self._header(store, project_id, revision_id)
        if not header:
            raise KeyError("Project has no published revision")
        row = self._revision_row_for_analysis(store, header, analysis_id)
        if not row:
            raise KeyError("Unknown analysis in revision")
        return self.source(project_id, row["file_id"], header["revision_id"])
    def resolve_graph_scope(
        self,
        project_id: str,
        revision_id: str,
        rows,
        scope_id: str | None,
        store: ProjectStore | None = None,
    ) -> GraphScope:
        """Resolve a client graph identity to an existing file/folder/block scope.

        Accepts a bare file id, a semantic file/folder/block graph id, a folder
        path or a block logical key. Function and control scopes are recovered
        from the archived graph metadata (small ``json_each`` identity records),
        never by loading every full analysis document. An unknown scope raises
        ``KeyError`` explicitly before any rows are chosen.
        """
        if not scope_id:
            return GraphScope(kind="project")
        known = {row["file_id"] for row in rows}
        if scope_id in known:
            return GraphScope(
                kind="file",
                file_id=scope_id,
                graph_scope_id=resolver._id("file", scope_id),
            )
        file_match = next(
            (fid for fid in known if resolver._id("file", fid) == scope_id), None
        )
        if file_match is not None:
            return GraphScope(
                kind="file",
                file_id=file_match,
                graph_scope_id=resolver._id("file", file_match),
            )
        folder = scope_id.rstrip("/")
        if folder and any(
            row["relative_path"].startswith(folder + "/") for row in rows
        ):
            return GraphScope(
                kind="folder",
                folder=folder,
                graph_scope_id=resolver._id("folder", project_id, folder),
            )
        if scope_id.startswith("folder:"):
            candidates = set()
            for row in rows:
                parts = row["relative_path"].split("/")[:-1]
                for index in range(len(parts)):
                    candidates.add("/".join(parts[: index + 1]))
            for candidate in candidates:
                if resolver._id("folder", project_id, candidate) == scope_id:
                    return GraphScope(
                        kind="folder", folder=candidate, graph_scope_id=scope_id
                    )
        owner = self._archived_scope_owner(store, revision_id, scope_id, known)
        if owner is not None:
            file_id, local_id, canonical = owner
            return GraphScope(
                kind="block",
                file_id=file_id,
                block_id=local_id,
                graph_scope_id=canonical,
            )
        raise KeyError(f"Unknown graph scope: {scope_id}")

    @staticmethod
    def _archived_scope_owner(store, revision_id, scope_id, known):
        """Find the file/block behind a semantic id or logical key, or ``None``."""
        if store is None:
            return None
        for file_id, local_id, _kind, logical_key in store.iter_graph_block_identities(
            revision_id
        ):
            if file_id not in known or not local_id:
                continue
            if resolver._id("block", file_id, local_id) == scope_id:
                return file_id, local_id, scope_id
            if logical_key and logical_key == scope_id:
                return file_id, local_id, scope_id
        return None

    def graph(
        self,
        project_id: str,
        revision_id: str | None = None,
        scope_id: str | None = None,
        view: str = "code",
        limit: int = 350,
    ) -> ProjectGraphSlice:
        root = Path(self._lookup_root(project_id)).resolve()
        store = ProjectStore(root)
        with store.session():
            header = self._header(store, project_id, revision_id)
            if not header:
                return ProjectGraphSlice(
                    project_id=project_id,
                    revision_id=revision_id or "",
                    scope_id=scope_id,
                    view="data" if view == "data" else "code",
                )
            rid = header["revision_id"]
            all_rows = store.revision_files(rid)
            # Resolve the requested identity to a known file/folder/block before
            # choosing rows or detail level, so a focused function never loads
            # every project file merely because the project is small or large.
            scope = self.resolve_graph_scope(
                project_id, rid, all_rows, scope_id, store=store
            )
            if scope.kind == "file":
                rows = [row for row in all_rows if row["file_id"] == scope.file_id]
            elif scope.kind == "block":
                # A focused block lives in exactly one file; load only that file
                # instead of inflating every project file into full detail.
                rows = [row for row in all_rows if row["file_id"] == scope.file_id]
            elif scope.kind == "folder":
                prefix = (scope.folder or "").rstrip("/") + "/"
                rows = [
                    row
                    for row in all_rows
                    if row["relative_path"].startswith(prefix)
                ]
            else:
                rows = list(all_rows)
            detailed = scope.kind in ("file", "block") or len(rows) <= DETAIL_FILE_LIMIT
            units: list = []
            analyses: dict = {}
            facts: dict = {}
            symbols: dict = {}
            module_index: dict = {}
            ambiguous: set = set()
            # One bulk query replaces per-file get_symbols/get_facts connections.
            compact = store.compact_records([row["analysis_id"] for row in rows])
            for row in rows:
                unit = SourceUnit(
                    id=row["file_id"],
                    relative_path=row["relative_path"],
                    digest=row["digest"],
                    analysis_id=row["analysis_id"],
                    module_names=json.loads(row["module_names"]) if row["module_names"] else [],
                    status=row["status"],
                )
                units.append(unit)
                if detailed:
                    payload = store.get_analysis(row["analysis_id"])
                    if payload:
                        analyses[unit.id] = AnalysisDocument.model_validate(payload)
                cached_facts, cached_symbols = compact.get(row["analysis_id"], (None, None))
                symbols[unit.id] = cached_symbols or []
                facts[unit.id] = FileFacts.from_json(cached_facts) if cached_facts else FileFacts()
                for name in unit.module_names:
                    if name in ambiguous:
                        continue
                    owner = module_index.get(name)
                    if owner is not None and owner != unit.id:
                        module_index.pop(name, None)
                        ambiguous.add(name)
                    elif name not in module_index:
                        module_index[name] = unit.id
            project_model = self._project_model(root, store)
            data = resolver.ProjectGraphInput(
                project_id=project_id,
                project_name=project_model.name,
                revision_id=rid,
                units=units,
                analyses=analyses,
                facts=facts,
                module_index=module_index,
                limit=limit,
                scope_id=scope.graph_scope_id,
                view=view,
                symbols=symbols,
            )
            graph, omitted = resolver.build_project_graph(data)
            return ProjectGraphSlice(
                graph=graph,
                project_id=project_id,
                revision_id=rid,
                scope_id=scope_id,
                view="data" if view == "data" else "code",
                omitted_count=omitted,
            )
    def entries(self, project_id: str):
        root = Path(self._lookup_root(project_id)).resolve()
        section = self._ensure_section(root)
        raw = self._read_raw(root)
        from ..workbench.models import RunConfiguration

        # Top-level workbench.yaml.run_configurations is the single authored source.
        items = raw.get("run_configurations", [])
        if not items and section.run_configurations:
            items = [c.model_dump(mode="json") for c in section.run_configurations]
        return [RunConfiguration.model_validate(item) for item in items]

    def close(self) -> None:
        self._closed = True


def _compact_symbols(document) -> list:
    """Small, stable index of callable/class symbols for overview graphs."""
    return [
        {
            "id": obj.id,
            "name": obj.name,
            "kind": obj.kind,
            "scope": obj.scope,
        }
        for obj in document.objects
        if obj.kind in ("function", "class")
    ]
