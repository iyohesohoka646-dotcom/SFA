"""Reviewed multi-file project changes: inert proposals, private exact bytes.

Proposal creation never imports, executes or applies project code. Public
records only ever carry sanitized, root-relative display text; the exact
candidate and original bytes are kept in restricted private storage so a later
reviewed acceptance can apply or restore them without trusting display text.

Acceptance is a recoverable, per-file transaction: it never claims the whole set
was written atomically. A durable private journal is staged before the first
write and only cleared once every write and the accepted record are durable.
After an interruption the documented policy is RESTORE-ALL: recovery verifies
each file is at its expected before or after bytes, then restores every original
byte (and unlinks a file this transaction created). It never rolls forward.
"""

from __future__ import annotations

import ast
import difflib
import hashlib
import io
import json
import os
import re
import time
import tokenize
import uuid
from contextlib import contextmanager
from pathlib import Path

from ...storage import atomic_write, atomic_write_private
from ..agent.privacy import clean_text
from ..models import timestamp
from ..workbench.source_format import verify_format
from .change_models import ChangeValidation, ProjectChangeSet, ProjectFileEdit
from .store import ProjectStore

_CHANGE_ID = re.compile(r"[0-9a-f]{32}\Z")
_MAX_EVENTS = 200
_CONTENT_LIMIT = 65536
_DIFF_LIMIT = 65536
_MAX_FILE_BYTES = 262144
_MAX_TOTAL_BYTES = 1048576
_MAX_FILES = 32


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _detect_encoding(raw: bytes) -> str:
    try:
        encoding, _ = tokenize.detect_encoding(io.BytesIO(raw).readline)
        return encoding
    except (SyntaxError, UnicodeDecodeError):
        return "utf-8"


def _decode(raw: bytes) -> str:
    return raw.decode(_detect_encoding(raw))


def _encode(before_raw: bytes | None, text: str) -> bytes:
    if not before_raw:
        return text.encode("utf-8")
    encoding = _detect_encoding(before_raw)
    raw_text = before_raw.decode(encoding, errors="replace")
    if "\r\n" in raw_text:
        text = text.replace("\r\n", "\n").replace("\n", "\r\n")
    return text.encode(encoding)


def _imports(text: str):
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return None
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            found.add("." * node.level + (node.module or ""))
    return found


def _resolve_target(root: Path, raw_path):
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError("Change path must be a relative Python file")
    rel = raw_path.replace("\\", "/")
    if rel.startswith("/") or Path(rel).is_absolute() or Path(rel).drive:
        raise ValueError("Change paths must be relative to the project root")
    parts = [part for part in rel.split("/") if part != ""]
    if any(part in (".", "..") for part in parts):
        raise ValueError("Change paths may not traverse outside the project root")
    if not parts:
        raise ValueError("Change path must name a file")
    root = root.resolve()
    resolved = (root / rel).resolve()
    if resolved != root and not resolved.is_relative_to(root):
        raise ValueError("Change path escapes the project root")
    relative = resolved.relative_to(root).as_posix()
    if relative.split("/")[0] == ".cdaf":
        raise ValueError("Ignored metadata under .cdaf cannot be changed")
    if Path(relative).suffix != ".py":
        raise ValueError("Only Python files can be proposed for change")
    return resolved, relative


class ProjectChangeService:
    def __init__(self, projects):
        self.projects = projects

    # -- paths and private storage -------------------------------------
    def _root(self, project_id: str) -> Path:
        return Path(self.projects._lookup_root(project_id)).resolve()

    def _state(self, root: Path) -> Path:
        state = root / ".cdaf" / "research" / "project-changes"
        resolved = state.resolve()
        if not resolved.is_relative_to(root):
            raise ValueError("Project change metadata must remain inside the project root")
        state.mkdir(parents=True, exist_ok=True)
        return state

    def _resolve_stored(self, root: Path, rel: str) -> Path:
        target, resolved_rel = _resolve_target(root, rel)
        if resolved_rel != rel:
            raise ValueError(f"Stored change path {rel} no longer resolves to its recorded location")
        return target

    def _reject_if_recovering(self, root: Path) -> None:
        if self._journal_path(root).exists():
            raise RuntimeError("An interrupted project change transaction requires explicit recovery first")

    @contextmanager
    def _lock(self, root: Path, cancel=None):
        # The same project-specific cross-process file lock serialises reviewed
        # change transactions and project indexing/publishing. A caller may pass
        # a ``cancel`` Event so that a waiting index can abandon the lock quickly.
        if cancel is not None and cancel.is_set():
            raise InterruptedError("Project index cancelled")
        state = self._state(root)
        handle = os.open(state / "project.lock", os.O_CREAT | os.O_RDWR, 0o600)
        if os.fstat(handle).st_size == 0:
            os.write(handle, b"\0")
        deadline = time.monotonic() + 15
        owned = False
        try:
            while True:
                if cancel is not None and cancel.is_set():
                    raise InterruptedError("Project index cancelled")
                try:
                    self._lock_handle(handle, True)
                    owned = True
                    break
                except OSError:
                    if time.monotonic() > deadline:
                        raise RuntimeError("Another project change transaction is in progress")
                    time.sleep(0.02)
            yield
        finally:
            if owned:
                try:
                    self._lock_handle(handle, False)
                except OSError:
                    pass
            os.close(handle)

    @staticmethod
    def _lock_handle(handle, acquire: bool):
        os.lseek(handle, 0, os.SEEK_SET)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle, msvcrt.LK_NBLCK if acquire else msvcrt.LK_UNLCK, 1)
            return
        import fcntl

        fcntl.flock(handle, (fcntl.LOCK_EX if acquire else fcntl.LOCK_UN) | (fcntl.LOCK_NB if acquire else 0))
    def _event(self, root: Path, project_id, change_id, kind, detail=""):
        path = self._state(root) / "events.json"
        events = []
        if path.exists():
            try:
                events = json.loads(path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                events = []
        events.append(
            {
                "at": timestamp(),
                "project_id": project_id,
                "change_id": change_id,
                "event": kind,
                "detail": clean_text(str(detail), 512),
            }
        )
        atomic_write_private(path, json.dumps(events[-_MAX_EVENTS:]))

    def _store(self, root: Path, change: ProjectChangeSet, items: list) -> None:
        folder = self._state(root) / change.id
        (folder / "blobs").mkdir(parents=True, exist_ok=True)
        meta = []
        for index, item in enumerate(items):
            candidate_blob = original_blob = None
            if change.status == "ready":
                atomic_write_private(
                    folder / "blobs" / f"{index}.candidate", item["candidate_bytes"]
                )
                candidate_blob = f"blobs/{index}.candidate"
                if item["before_exists"]:
                    atomic_write_private(
                        folder / "blobs" / f"{index}.original", item["original_bytes"]
                    )
                    original_blob = f"blobs/{index}.original"
            meta.append(
                {
                    "path": item["path"],
                    "before_exists": item["before_exists"],
                    "before_digest": item["before_digest"],
                    "after_digest": item["after_digest"],
                    "candidate_blob": candidate_blob,
                    "original_blob": original_blob,
                }
            )
        atomic_write_private(
            folder / "private.json",
            json.dumps(
                {
                    "change_id": change.id,
                    "project_id": change.project_id,
                    "base_revision": change.base_revision,
                    "files": meta,
                }
            ),
        )
        atomic_write_private(folder / "record.json", change.model_dump_json(indent=2))

    def _update(self, root: Path, change: ProjectChangeSet) -> None:
        atomic_write_private(
            self._state(root) / change.id / "record.json",
            change.model_dump_json(indent=2),
        )

    def _load(self, root: Path, project_id: str, change_id: str) -> ProjectChangeSet:
        if not isinstance(change_id, str) or not _CHANGE_ID.match(change_id):
            raise LookupError("Unknown change set")
        path = self._state(root) / change_id / "record.json"
        if not path.is_file():
            raise LookupError("Unknown change set")
        change = ProjectChangeSet.model_validate_json(path.read_text(encoding="utf-8"))
        if change.project_id != project_id:
            raise LookupError("Change set does not belong to this project")
        return change

    def get(self, project_id: str, change_id: str) -> ProjectChangeSet:
        return self._load(self._root(project_id), project_id, change_id)

    def list(self, project_id: str) -> list[ProjectChangeSet]:
        root = self._root(project_id)
        items = []
        for folder in self._state(root).iterdir():
            if not folder.is_dir() or not _CHANGE_ID.match(folder.name):
                continue
            record = folder / "record.json"
            if not record.is_file():
                continue
            change = ProjectChangeSet.model_validate_json(record.read_text(encoding="utf-8"))
            if change.project_id == project_id:
                items.append(change)
        items.sort(key=lambda item: item.created_at, reverse=True)
        return items

    def _load_private(self, root: Path, change_id: str) -> dict:
        path = self._state(root) / change_id / "private.json"
        if not path.is_file():
            raise LookupError("Private change record is unavailable")
        return json.loads(path.read_text(encoding="utf-8"))

    # -- proposal ------------------------------------------------------
    def propose(self, project_id: str, revision_id: str, edits) -> ProjectChangeSet:
        if not isinstance(edits, list) or not edits:
            raise ValueError("A change set requires at least one file edit")
        root = self._root(project_id)
        with self._lock(root):
            self._reject_if_recovering(root)
            return self._propose(root, project_id, revision_id, edits)

    def _propose(self, root, project_id, revision_id, edits):
        if len(edits) > _MAX_FILES:
            raise ValueError(f"A change set may review at most {_MAX_FILES} files")
        store = ProjectStore(root)
        revision = store.get_revision(revision_id)
        if not revision or revision["project_id"] != project_id:
            raise LookupError("Unknown project revision for this project")
        rows = store.revision_files(revision_id)
        indexed = {row["relative_path"]: row for row in rows}
        modules = {name for row in rows for name in json.loads(row["module_names"] or "[]")}

        seen = set()
        evaluated = []
        for edit in edits:
            if not isinstance(edit, dict):
                raise ValueError("Each edit must be a mapping")
            operation = edit.get("operation", "modify")
            if operation not in ("modify", "create", "format"):
                raise ValueError("Unsupported change operation")
            content = edit.get("content", "")
            if not isinstance(content, str):
                raise ValueError("Edit content must be text")
            target, rel = _resolve_target(root, edit.get("path"))
            if rel in seen:
                raise ValueError(f"Duplicate file path in change set: {rel}")
            seen.add(rel)
            evaluated.append(
                self._evaluate(indexed, rel, target, operation, content, modules)
            )

        invalid = any(not item["valid"] for item in evaluated)
        total_bytes = sum(len(item["candidate_bytes"]) for item in evaluated)
        if total_bytes > _MAX_TOTAL_BYTES:
            invalid = True
        validation = [
            ChangeValidation(
                kind="root",
                status="pass",
                detail="All paths are relative Python files inside the project root",
            )
        ]
        for item in evaluated:
            validation.extend(item["checks"])
        validation.append(
            ChangeValidation(
                kind="tests",
                status="not_run",
                detail="Tests were not executed; no run validated this proposal",
            )
        )
        if total_bytes > _MAX_TOTAL_BYTES:
            validation.append(
                ChangeValidation(kind="budget", status="fail", detail=f"Change set exceeds the total review budget of {_MAX_TOTAL_BYTES} bytes")
            )
        change = ProjectChangeSet(
            id=uuid.uuid4().hex,
            project_id=project_id,
            base_revision=revision_id,
            status="invalid" if invalid else "ready",
            files=[self._edit_model(item) for item in evaluated],
            validation=validation,
            affected_references=self._callers(store, revision_id, [item["path"] for item in evaluated]),
        )
        self._store(root, change, evaluated)
        return change

    def _evaluate(self, indexed, rel, target, operation, content, modules):
        checks = []
        diagnostics = []
        valid = True
        exists = target.is_file()
        before_raw = b""
        before_digest = ""
        row = indexed.get(rel)
        if operation == "create":
            if exists or row is not None:
                valid = False
                diagnostics.append("A new file must not already exist or be indexed")
        elif not exists:
            valid = False
            diagnostics.append("The target file does not exist")
        elif row is None:
            valid = False
            diagnostics.append("The target file is not part of the indexed base revision")
        else:
            before_raw = target.read_bytes()
            before_digest = _digest(before_raw)
            if before_digest != row["digest"]:
                valid = False
                diagnostics.append("Source changed since the indexed base revision")
        original_text = _decode(before_raw) if exists and before_raw else ""
        try:
            candidate_bytes = _encode(before_raw if exists else None, content)
            encoding_status, encoding_detail = "pass", f"{rel}: encoding preserved"
        except (UnicodeEncodeError, UnicodeDecodeError) as error:
            candidate_bytes = b""
            encoding_status, encoding_detail = "fail", f"{rel}: cannot encode candidate ({error})"
            valid = False
            diagnostics.append(encoding_detail)
        checks.append(ChangeValidation(kind="encoding", status=encoding_status, detail=encoding_detail))
        syntax_status, syntax_detail = "pass", f"{rel}: syntax parses"
        try:
            ast.parse(content)
            compile(content, rel, "exec")
        except (SyntaxError, ValueError) as error:
            syntax_status = "fail"
            syntax_detail = f"{rel}: {error}"
            valid = False
            diagnostics.append(syntax_detail)
        checks.append(ChangeValidation(kind="syntax", status=syntax_status, detail=syntax_detail))
        if operation == "format":
            if not exists:
                format_status, format_detail = "fail", f"{rel}: formatting requires an existing file"
                valid = False
            else:
                try:
                    verify_format(original_text, content)
                    format_status, format_detail = "pass", f"{rel}: AST, comments and order preserved"
                except (ValueError, SyntaxError) as error:
                    format_status = "fail"
                    format_detail = clean_text(str(error), 512)
                    valid = False
                    diagnostics.append(format_detail)
            checks.append(ChangeValidation(kind="format", status=format_status, detail=format_detail))
        checks.append(
            ChangeValidation(
                kind="imports",
                status=self._imports_status(original_text, content, modules, rel),
                detail=self._imports_detail(original_text, content, rel),
            )
        )
        diff = self._diff(rel, original_text if exists else "", content)
        if len(candidate_bytes) > _MAX_FILE_BYTES:
            valid = False
            diagnostics.append(f"{rel}: candidate exceeds the per-file review budget of {_MAX_FILE_BYTES} bytes")
        if len(content) > _CONTENT_LIMIT or len(diff) >= _DIFF_LIMIT:
            valid = False
            diagnostics.append(f"{rel}: candidate is larger than the public review limit and would hide its tail")
        checks.append(
            ChangeValidation(
                kind="budget",
                status="fail" if len(candidate_bytes) > _MAX_FILE_BYTES or len(content) > _CONTENT_LIMIT or len(diff) >= _DIFF_LIMIT else "pass",
                detail=f"{rel}: candidate {len(candidate_bytes)} bytes within the reviewable budget",
            )
        )
        return {
            "path": rel,
            "operation": operation,
            "before_exists": exists,
            "before_digest": before_digest,
            "after_digest": _digest(candidate_bytes),
            "original_bytes": before_raw,
            "candidate_bytes": candidate_bytes,
            "content": clean_text(content, _CONTENT_LIMIT),
            "diff": diff,
            "diagnostics": [clean_text(text, 512) for text in diagnostics],
            "valid": valid,
            "checks": checks,
        }

    @staticmethod
    def _edit_model(item) -> ProjectFileEdit:
        return ProjectFileEdit(
            path=item["path"],
            before_digest=item["before_digest"],
            after_digest=item["after_digest"],
            before_exists=item["before_exists"],
            operation=item["operation"],
            content=item["content"],
            diff=item["diff"],
            diagnostics=list(item["diagnostics"]),
        )

    @staticmethod
    def _diff(rel, original, content):
        before = original.splitlines(keepends=True)
        after = content.splitlines(keepends=True)
        if not before:
            before = []
        return clean_text(
            "".join(difflib.unified_diff(before, after, fromfile=rel, tofile=rel)),
            _DIFF_LIMIT,
        )

    @staticmethod
    def _imports_detail(original, content, rel):
        before = _imports(original) or set()
        after = _imports(content) or set()
        added = sorted(after - before)
        removed = sorted(before - after)
        return f"{rel}: added={added} removed={removed}"

    @staticmethod
    def _imports_status(original, content, modules, rel):
        before = _imports(original) or set()
        after = _imports(content) or set()
        unresolved = []
        for name in sorted(after - before):
            base = name.lstrip(".")
            if not base:
                continue
            if not any(module == base or module.startswith(base + ".") for module in modules):
                unresolved.append(name)
        return "not_validated" if unresolved else "pass"

    @staticmethod
    def _callers(store, revision_id, paths):
        rows = store.revision_files(revision_id)
        by_id = {row["file_id"]: row["relative_path"] for row in rows}
        changed = {
            row["file_id"] for row in rows if row["relative_path"] in set(paths)
        }
        callers = []
        for rel in store.relationships(revision_id):
            if rel["kind"] == "import" and rel["target_file_id"] in changed:
                name = by_id.get(rel["source_file_id"])
                if name and name not in callers:
                    callers.append(name)
        return sorted(callers)

    # -- review actions ------------------------------------------------
    def reject(self, project_id: str, change_id: str) -> ProjectChangeSet:
        root = self._root(project_id)
        with self._lock(root):
            self._reject_if_recovering(root)
            change = self._load(root, project_id, change_id)
            if change.status == "accepted":
                raise ValueError("Accepted change sets require a reviewed rollback")
            change = change.model_copy(update={"status": "rejected"})
            self._update(root, change)
            self._event(root, project_id, change.id, "rejected")
            return change

    # -- application ---------------------------------------------------
    def _journal_path(self, root: Path) -> Path:
        return self._state(root) / "journal.json"

    def _write_file(self, path: Path, data: bytes) -> None:
        """Atomic file replace seam; tests monkeypatch this to interrupt a write."""
        atomic_write(path, data)

    @staticmethod
    def _current_digest(target: Path):
        return _digest(target.read_bytes()) if target.is_file() else None

    def _state_is_before(self, target: Path, meta) -> bool:
        current = self._current_digest(target)
        if meta["before_exists"]:
            return current == meta["before_digest"]
        return current is None

    def _state_is_after(self, target: Path, meta) -> bool:
        return self._current_digest(target) == meta["after_digest"]

    def _preflight(self, root: Path, private) -> str:
        for meta in private["files"]:
            target = self._resolve_stored(root, meta["path"])
            if not self._state_is_before(target, meta):
                return f"Whole-set preflight failed: {meta['path']} changed or appeared since the proposal"
        return ""

    def accept(self, project_id: str, change_id: str, cancel=None) -> ProjectChangeSet:
        root = self._root(project_id)
        # A cancellation while waiting for the cross-process lock aborts before
        # any byte is written; once the lock is held the write runs to its
        # recoverable conclusion.
        with self._lock(root, cancel=cancel):
            self._reject_if_recovering(root)
            change = self._load(root, project_id, change_id)
            if change.status != "ready":
                raise ValueError("Only a ready change set can be accepted")
            store = ProjectStore(root)
            latest = store.latest_revision(project_id)
            if latest and change.base_revision and latest["revision_id"] != change.base_revision:
                change = change.model_copy(
                    update={
                        "status": "conflict",
                        "validation": change.validation
                        + [ChangeValidation(kind="revision", status="fail", detail="Project revision changed since this proposal was created")],
                    }
                )
                self._update(root, change)
                raise ValueError("Project revision changed since this proposal was created")
            private = self._load_private(root, change_id)
            reason = self._preflight(root, private)
            if reason:
                change = change.model_copy(
                    update={
                        "status": "conflict",
                        "validation": change.validation
                        + [ChangeValidation(kind="preflight", status="fail", detail=reason)],
                    }
                )
                self._update(root, change)
                raise ValueError(reason)
            journal = {
                "change_id": change.id,
                "project_id": project_id,
                "base_revision": change.base_revision,
                "created_at": timestamp(),
                "files": [
                    {
                        "path": meta["path"],
                        "before_exists": meta["before_exists"],
                        "before_digest": meta["before_digest"],
                        "after_digest": meta["after_digest"],
                        "written": False,
                    }
                    for meta in private["files"]
                ],
            }
            journal_path = self._journal_path(root)
            atomic_write_private(journal_path, json.dumps(journal))
            try:
                for index, meta in enumerate(private["files"]):
                    target = self._resolve_stored(root, meta["path"])
                    if not self._state_is_before(target, meta):
                        raise RuntimeError(f"Concurrent change detected at {meta['path']}; aborting before writing it")
                    candidate = (self._state(root) / change.id / meta["candidate_blob"]).read_bytes()
                    if _digest(candidate) != meta["after_digest"]:
                        raise RuntimeError("Stored candidate no longer matches its recorded digest")
                    self._write_file(target, candidate)
                    journal["files"][index]["written"] = True
                    atomic_write_private(journal_path, json.dumps(journal))
            except BaseException:
                current = self._load(root, project_id, change_id)
                if current.status not in ("recovery_required", "conflict"):
                    current = current.model_copy(update={"status": "recovery_required"})
                    self._update(root, current)
                raise
            current = self._load(root, project_id, change_id)
            current = current.model_copy(update={"status": "accepted", "accepted_revision": None})
            self._update(root, current)
            journal_path.unlink(missing_ok=True)
            self._event(root, project_id, change.id, "accepted")
            return current

    def mark_indexed(self, project_id: str, change_id: str, revision_id: str) -> ProjectChangeSet:
        """Bind an accepted change to an owned, published revision.

        The record moved to ``accepted`` with ``accepted_revision`` unset when the
        bytes were written; this call is the only place that records a revision.
        It never trusts the caller: the revision must be this project's published
        latest, and every changed file must still match the exact private
        candidate digest frozen in the proposal manifest. No current-file
        fallback, no history rewrite, and no partial claim is ever persisted.
        """
        root = self._root(project_id)
        with self._lock(root):
            change = self._load(root, project_id, change_id)
            if change.status != "accepted":
                raise ValueError("Only an accepted change set can be indexed")
            if change.accepted_revision is not None:
                if change.accepted_revision == revision_id:
                    return change
                raise ValueError("Change set already recorded a different accepted revision")
            store = ProjectStore(root)
            revision = store.get_revision(revision_id)
            if not revision or revision["project_id"] != project_id:
                raise LookupError("Unknown project revision for this project")
            latest = store.latest_revision(project_id)
            if not latest or latest["revision_id"] != revision_id:
                raise ValueError("Only the published latest revision can be recorded for this change")
            private = self._load_private(root, change_id)
            published = {
                row["relative_path"]: row["digest"] for row in store.revision_files(revision_id)
            }
            for meta in private["files"]:
                if published.get(meta["path"]) != meta["after_digest"]:
                    raise RuntimeError(
                        f"{meta['path']}: published revision does not contain the reviewed candidate; "
                        "refusing to record an accepted revision"
                    )
                target = self._resolve_stored(root, meta["path"])
                if self._current_digest(target) != meta["after_digest"]:
                    raise RuntimeError(
                        f"{meta['path']}: on-disk bytes no longer match the reviewed candidate; "
                        "refusing to record an accepted revision"
                    )
            change = change.model_copy(update={"accepted_revision": revision_id})
            self._update(root, change)
            self._event(root, project_id, change.id, "indexed", revision_id)
            return change

    def recovery_state(self, project_id: str) -> dict:
        """Public recovery summary; never exposes private blobs or the journal."""
        root = self._root(project_id)
        journal = self._journal_path(root)
        required = False
        change_id = None
        if journal.is_file():
            required = True
            try:
                data = json.loads(journal.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                data = {}
            if data.get("project_id") == project_id:
                change_id = data.get("change_id")
        if not required:
            for change in self.list(project_id):
                if change.status == "recovery_required":
                    required = True
                    change_id = change.id
                    break
        return {"required": required, "change_id": change_id}

    def assert_ready(self, project_id: str) -> None:
        root = self._root(project_id)
        if self._journal_path(root).exists():
            raise RuntimeError("A project change transaction needs explicit recovery before this project can run")
        for change in self.list(project_id):
            if change.status == "recovery_required":
                raise RuntimeError("A project change set requires explicit recovery")

    def recover(self, project_id: str) -> ProjectChangeSet:
        root = self._root(project_id)
        with self._lock(root):
            journal_path = self._journal_path(root)
            if not journal_path.exists():
                raise ValueError("No interrupted change set requires recovery")
            journal = json.loads(journal_path.read_text(encoding="utf-8"))
            if journal.get("project_id") != project_id:
                raise LookupError("Recovery journal belongs to another project")
            change = self._load(root, project_id, journal["change_id"])
            private = self._load_private(root, journal["change_id"])
            targets = []
            offenders = []
            for meta in private["files"]:
                target = self._resolve_stored(root, meta["path"])
                targets.append((target, meta))
                if not (self._state_is_before(target, meta) or self._state_is_after(target, meta)):
                    offenders.append(meta["path"])
            if offenders:
                change = change.model_copy(
                    update={
                        "status": "conflict",
                        "validation": change.validation
                        + [ChangeValidation(kind="recovery", status="fail", detail="External edits block recovery: " + ", ".join(sorted(offenders)))],
                    }
                )
                self._update(root, change)
                self._event(root, project_id, change.id, "recovery_blocked", ", ".join(sorted(offenders)))
                raise ValueError("External edits block recovery: " + ", ".join(sorted(offenders)))
            for target, meta in targets:
                if self._state_is_before(target, meta):
                    continue
                if not self._state_is_after(target, meta):
                    detail = "External edits block recovery: " + meta["path"]
                    change = change.model_copy(
                        update={
                            "status": "conflict",
                            "validation": change.validation
                            + [ChangeValidation(kind="recovery", status="fail", detail=detail)],
                        }
                    )
                    self._update(root, change)
                    self._event(root, project_id, change.id, "recovery_blocked", meta["path"])
                    raise ValueError(detail)
                if meta["before_exists"]:
                    original = (self._state(root) / change.id / meta["original_blob"]).read_bytes()
                    if _digest(original) != meta["before_digest"]:
                        detail = f"{meta['path']}: stored original bytes no longer match their recorded digest"
                        change = change.model_copy(
                            update={
                                "status": "conflict",
                                "validation": change.validation
                                + [ChangeValidation(kind="recovery", status="fail", detail=detail)],
                            }
                        )
                        self._update(root, change)
                        self._event(root, project_id, change.id, "recovery_blocked", meta["path"])
                        raise ValueError(detail)
                    self._write_file(target, original)
                elif target.exists():
                    target.unlink()
            change = self._load(root, project_id, change.id)
            change = change.model_copy(
                update={
                    "status": "rejected",
                    "validation": change.validation
                    + [ChangeValidation(kind="recovery", status="pass", detail="Restored the original bytes (restore-all policy)")],
                }
            )
            self._update(root, change)
            journal_path.unlink(missing_ok=True)
            self._event(root, project_id, change.id, "recovered")
            return change

    def rollback(self, project_id: str, change_id: str) -> ProjectChangeSet:
        root = self._root(project_id)
        with self._lock(root):
            self._reject_if_recovering(root)
            original = self._load(root, project_id, change_id)
            if original.status != "accepted":
                raise ValueError("Only an accepted change set can be rolled back")
            private = self._load_private(root, change_id)
            store = ProjectStore(root)
            latest = store.latest_revision(project_id)
            base = latest["revision_id"] if latest else original.base_revision
            items = []
            for meta in private["files"]:
                if not meta["before_exists"]:
                    original = original.model_copy(
                        update={
                            "validation": original.validation
                            + [ChangeValidation(kind="rollback", status="fail", detail=f"{meta['path']}: a created file has no original bytes; delete is unsupported, review and remove it manually")],
                        }
                    )
                    self._update(root, original)
                    raise ValueError(
                        "A created file cannot be rolled back automatically (delete is unsupported); review and remove it manually"
                    )
                target = self._resolve_stored(root, meta["path"])
                current_raw = target.read_bytes() if target.is_file() else None
                if current_raw is None or _digest(current_raw) != meta["after_digest"]:
                    raise ValueError("Source changed after acceptance; review a new rollback")
                original_bytes = (self._state(root) / change_id / meta["original_blob"]).read_bytes()
                if _digest(original_bytes) != meta["before_digest"]:
                    raise ValueError(
                        f"{meta['path']}: stored original bytes no longer match their recorded digest; "
                        "the rollback backup is corrupted and cannot produce a proposal"
                    )
                text = _decode(original_bytes)
                current_text = _decode(current_raw)
                items.append(
                    {
                        "path": meta["path"],
                        "operation": "modify",
                        "before_exists": True,
                        "before_digest": meta["after_digest"],
                        "after_digest": _digest(original_bytes),
                        "original_bytes": current_raw,
                        "candidate_bytes": original_bytes,
                        "content": clean_text(text, _CONTENT_LIMIT),
                        "diff": clean_text(
                            "".join(
                                difflib.unified_diff(
                                    current_text.splitlines(keepends=True),
                                    text.splitlines(keepends=True),
                                    fromfile=meta["path"],
                                    tofile=meta["path"],
                                )
                            ),
                            _DIFF_LIMIT,
                        ),
                        "diagnostics": [],
                        "valid": True,
                        "checks": [ChangeValidation(kind="rollback", status="pass", detail=f"{meta['path']}: restores the bytes recorded at acceptance")],
                    }
                )
            rollback = ProjectChangeSet(
                id=uuid.uuid4().hex,
                project_id=project_id,
                base_revision=base,
                status="ready",
                files=[self._edit_model(item) for item in items],
                validation=[
                    ChangeValidation(kind="rollback", status="pass", detail="Reviewed rollback proposal; acceptance still performs whole-set conflict preflight"),
                    ChangeValidation(kind="tests", status="not_run", detail="Tests were not executed; no run validated this proposal"),
                ],
                affected_references=self._callers(store, base, [item["path"] for item in items]) if base else [],
                rollback_of=original.id,
            )
            self._store(root, rollback, items)
            return rollback







