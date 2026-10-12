"""Per-project indexing: serialized/coalesced jobs and an opt-in metadata watcher.

Indexing is inert (never imports user code) and always publishes atomically, so
a cancelled or failed run leaves the previously published revision usable. The
watcher stats only the included Python files; it never reads or executes code.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

from . import discovery

WATCH_INTERVAL = 1.0
DEBOUNCE = 0.4
WATCH_ROOT_LIMIT = 20000


class _MetadataWatcher(threading.Thread):
    """Debounced mtime/size polling over included Python files only."""

    def __init__(
        self,
        service,
        project_id: str,
        root: Path,
        section,
        interval: float = WATCH_INTERVAL,
    ):
        super().__init__(daemon=True, name="project-watch-" + project_id[:8])
        self.service = service
        self.project_id = project_id
        self.root = Path(root).resolve()
        self.section = section
        self.interval = interval
        self._stop_event = threading.Event()
        self._state: dict = {}
        self.limited = False
        self.diagnostic = ""
        self.last_error: str | None = None

    def _included(self, rel: str) -> bool:
        include = list(self.section.include) or ["**/*.py"]
        if list(self.section.exclude) and discovery._matches_any(
            rel, list(self.section.exclude)
        ):
            return False
        return discovery._matches_any(rel, include)

    def _snapshot(self):
        state: dict = {}
        limited = False
        source_roots = [str(s) for s in self.section.source_roots] or ["."]
        for source_root in source_roots:
            base = (
                self.root
                if source_root in (".", "")
                else (self.root / source_root).resolve()
            )
            if not base.is_dir() or not discovery._inside_resolved(self.root, base):
                continue
            for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
                current = Path(dirpath)
                kept = []
                for name in dirnames:
                    child = current / name
                    if (
                        name in discovery.EXCLUDED_DIRS
                        or child.is_symlink()
                        or not discovery._inside_resolved(self.root, child)
                    ):
                        continue
                    kept.append(name)
                dirnames[:] = kept
                for name in filenames:
                    if not name.endswith(".py"):
                        continue
                    path = current / name
                    if path.is_symlink() or not discovery._inside_resolved(
                        self.root, path
                    ):
                        continue
                    rel = discovery._relative_of(self.root, path)
                    if rel is None or not self._included(rel):
                        continue
                    try:
                        stat = path.stat()
                    except OSError:
                        continue
                    state[rel] = (stat.st_size, round(stat.st_mtime, 3))
                    if len(state) >= WATCH_ROOT_LIMIT:
                        limited = True
                        return state, limited
        return state, limited

    def run(self):
        self._state, self.limited = self._snapshot()
        while not self._stop_event.wait(self.interval):
            try:
                current, limited = self._snapshot()
            except OSError as error:
                self.last_error = f"{type(error).__name__}: {error}"[:512]
                continue
            self.limited = limited
            if current == self._state:
                continue
            # Debounce: let an in-progress write settle before deciding.
            if self._stop_event.wait(DEBOUNCE):
                return
            try:
                settled, limited = self._snapshot()
            except OSError as error:
                self.last_error = f"{type(error).__name__}: {error}"[:512]
                continue
            self._state = settled
            self.limited = limited
            if current == settled:
                continue
            try:
                self.service._auto_submit(self.project_id)
                self.last_error = None
            except Exception as error:  # bounded, surfaced via watch status
                self.last_error = f"{type(error).__name__}: {error}"[:512]

    def status(self):
        self.diagnostic = (
            f"Watch covers only the first {WATCH_ROOT_LIMIT} included Python files; "
            "the tree is larger and is not fully watched"
            if self.limited
            else ""
        )
        return {
            "enabled": True,
            "files": len(self._state),
            "limited": self.limited,
            "diagnostic": self.diagnostic,
            "last_error": self.last_error,
        }

    def stop(self):
        self._stop_event.set()


class ProjectIndexService:
    def __init__(self, application):
        self.application = application
        self._lock = threading.RLock()
        self._active: dict = {}
        self._watchers: dict = {}
        self._closed = False

    # -- indexing ------------------------------------------------------
    def submit(self, project_id: str, expected_revision: str | None = None):
        workbench = self.application.workbench(project_id)
        with self._lock:
            if self._closed:
                raise ValueError("Project indexing has ended")
            current = self.application.projects.project(project_id).latest_revision_id
            if expected_revision and expected_revision != current:
                raise RuntimeError("Project revision changed; refresh before indexing")
            active = self._active.get(project_id)
            if active is not None:
                return active
            task = workbench.jobs.submit(
                "project.index",
                lambda job, cancel: self._run(project_id, job, cancel),
                receipt={"project_id": project_id},
            )
            self._active[project_id] = task
            return task

    def _auto_submit(self, project_id: str):
        # The watcher records the bounded error for GET /watch; never silent.
        return self.submit(project_id)

    def _run(self, project_id: str, task, cancel):
        workbench = self.application.workbench(project_id)
        try:
            revision = self.application.index(project_id, cancel=cancel)
            workbench.jobs.update(
                task.id,
                project_id=project_id,
                project_revision_id=revision.id,
                receipt={
                    "project_id": project_id,
                    "revision_id": revision.id,
                    "parsed_files": revision.parsed_files,
                    "reused_files": revision.reused_files,
                },
            )
            return {
                "message": (
                    f"Indexed {revision.files_count} files "
                    f"({revision.parsed_files} parsed, {revision.reused_files} reused)"
                )
            }
        finally:
            with self._lock:
                self._active.pop(project_id, None)

    # -- watcher -------------------------------------------------------
    def watch(self, project_id: str, enabled: bool):
        project = self.application.projects.project(project_id)
        section = self.application.projects._ensure_section(Path(project.root))
        with self._lock:
            if self._closed:
                raise ValueError("Project indexing has ended")
            current = self._watchers.get(project_id)
            if enabled and current is None:
                watcher = _MetadataWatcher(
                    self, project_id, Path(project.root), section
                )
                self._watchers[project_id] = watcher
                watcher.start()
            elif not enabled and current is not None:
                self._watchers.pop(project_id, None)
                current.stop()
        return {"project_id": project_id, **self.watch_status(project_id)}

    def watch_status(self, project_id: str) -> dict:
        with self._lock:
            watcher = self._watchers.get(project_id)
        if watcher is None:
            return {
                "enabled": False,
                "files": 0,
                "limited": False,
                "diagnostic": "",
                "last_error": None,
            }
        return watcher.status()

    def watching(self, project_id: str) -> bool:
        with self._lock:
            return project_id in self._watchers

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            watchers = list(self._watchers.values())
            self._watchers.clear()
        for watcher in watchers:
            watcher.stop()
        for watcher in watchers:
            watcher.join(timeout=2)
