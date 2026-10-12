"""P2b application contract: project-keyed services, freeze and real execution.

``ProjectApplication`` owns one project-scoped service pair per opened project
(no mutable active-project backend). Opening or indexing never runs or imports
user code. Plans freeze a compact source manifest and an authored entry; the
only executed entry is the exactly one the user saved and planned.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ..service import ExecutionBudget, ResearchService
from ..workbench.models import RunConfiguration
from . import local_runtime, runtime
from .changes import ProjectChangeService
from .service import ProjectService
from .workbench import ProjectWorkbenchService

MAX_PLAN_FILES = 20000
PAGE = 1000


class ProjectApplication:
    def __init__(self, host_root: Path, models=None, *, max_workers=3, admission_limit=16):
        self.host_root = Path(host_root).resolve()
        self.projects = ProjectService(self.host_root)
        self.models = models
        # One application-wide computation budget (subprocess launches) and one
        # application-wide background worker/admission budget shared by every
        # project service; the two limits are independent and never double-count.
        self.budget = ExecutionBudget(4)
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="cdaf-application"
        )
        self._admission = threading.BoundedSemaphore(int(admission_limit))
        self._task_admission_limit = int(admission_limit)
        self._changes = ProjectChangeService(self.projects)
        self._services: dict = {}
        self._lock = threading.RLock()
        self._closed = False

    # -- project-keyed services ---------------------------------------
    def _service(self, project_id: str):
        with self._lock:
            if self._closed:
                raise ValueError("Project application is closed")
            service = self._services.get(project_id)
            if service is None:
                root = Path(self.projects.project(project_id).root)
                research = ResearchService(
                    root,
                    budget=self.budget,
                    job_executor=self._executor,
                    task_admission=self._admission,
                    task_admission_limit=self._task_admission_limit,
                )
                workbench = ProjectWorkbenchService(
                    research,
                    project_id=project_id,
                    project_root=root,
                    host_root=self.host_root,
                    projects=self.projects,
                    models=self.models,
                )
                # The project workbench is the one and only workbench for this
                # project service; HTTP presenters/tasks/config and the research
                # service must share the exact same instance.
                research._workbench = workbench
                service = {"research": research, "workbench": workbench}
                self._services[project_id] = service
            return service

    def workbench(self, project_id: str) -> ProjectWorkbenchService:
        return self._service(project_id)["workbench"]

    def research(self, project_id: str) -> ResearchService:
        return self._service(project_id)["research"]

    def changes(self, project_id: str) -> ProjectChangeService:
        """Shared reviewed-change service for a project (recovery-ready gate)."""
        return self._changes

    def assert_ready(self, project_id: str) -> None:
        self._changes.assert_ready(project_id)

    # -- identity and indexing ----------------------------------------
    def open(self, path):
        return self.projects.open(path)

    def index(self, project_id: str, cancel=None, progress=None):
        # Asynchronous UI progress flows straight through; the signature stays
        # backwards compatible for existing callers.
        self._changes.assert_ready(project_id)
        return self.projects.index(project_id, cancel=cancel, progress=progress)

    def configuration(self, project_id: str):
        return self.workbench(project_id).configurations.load()

    def save_entries(self, project_id: str, entries, *, expected_revision: int):
        return self.workbench(project_id).save_entries(
            entries, expected_revision=expected_revision
        )

    # -- inert suggestions --------------------------------------------
    def entry_candidates(self, project_id: str, revision_id: str | None = None):
        units = self._revision_units(project_id, revision_id)
        saved = {c.target for c in self.projects.entries(project_id)}
        named_main: list = []
        package_main: list = []
        ordinary: list = []
        for unit in units:
            if unit.status != "parsed" or unit.relative_path in saved:
                continue
            relative = unit.relative_path
            if relative.endswith("__init__.py"):
                continue
            base = relative.rsplit("/", 1)[-1]
            if base == "main.py":
                named_main.append(unit)
            elif relative.endswith("__main__.py"):
                package_main.append(unit)
            else:
                ordinary.append(unit)
        primary = named_main + package_main
        if primary:
            ordered = primary
        else:
            root = Path(self.projects.project(project_id).root)
            guarded = [u for u in ordinary if self._has_main_guard(root, u)]
            ordered = guarded or ordinary
        return [
            RunConfiguration(
                id="suggest:" + unit.id,
                name=unit.relative_path,
                kind="script",
                target=unit.relative_path,
            )
            for unit in ordered
        ]

    @staticmethod
    def _has_main_guard(root: Path, unit) -> bool:
        path = root / unit.relative_path
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return False
        return "__name__" in text and "__main__" in text

    # -- planning and execution ---------------------------------------
    def plan(
        self,
        project_id: str,
        configuration_id: str,
        *,
        revision_id: str,
        scope: str = "compute",
        run_id=None,
        snapshot_ids=(),
        instance_ids=None,
        target_scope=None,
    ):
        if scope not in ("compute", "probes", "replot"):
            raise ValueError("Unknown project plan scope: " + str(scope))
        self._changes.assert_ready(project_id)
        project = self.projects.project(project_id)
        workbench = self.workbench(project_id)
        config, run_config = workbench.entry(configuration_id)
        revision_id = revision_id or project.latest_revision_id
        if not revision_id:
            raise ValueError("Project has no published revision")
        units = self._revision_units(project_id, revision_id)
        entry = runtime.resolve_entry(units, run_config)
        entry_relative = (
            entry["target"]
            if entry["kind"] == "script"
            else self._module_relative(units, entry["target"])
        )
        manifest = runtime.build_manifest(project.root, project_id, revision_id, units)
        if scope == "compute":
            # A fresh computation must launch the exact bytes on disk. Evidence
            # only scopes reuse the archived revision and never require current
            # files to still exist on disk.
            runtime.verify_manifest(project.root, manifest)
        entry_unit = next(u for u in units if u.relative_path == entry_relative)
        entry_public = {
            **entry,
            "relative": entry_relative,
            "interpreter_ref": run_config.interpreter_ref,
            "environment": list(run_config.environment),
            "file_id": entry_unit.id,
            "analysis_id": entry_unit.analysis_id,
            "cwd": run_config.cwd,
            "configuration_id": configuration_id,
        }
        options = dict(run_config.options or {})
        if "timeout_seconds" in options:
            entry_public["timeout_seconds"] = options["timeout_seconds"]
        return workbench.plan_project(
            configuration_id,
            revision_id=revision_id,
            entry_relative=entry_relative,
            entry_analysis_id=entry_unit.analysis_id,
            manifest=manifest,
            entry_public=entry_public,
            scope=scope,
            run_id=run_id,
            snapshot_ids=snapshot_ids,
            instance_ids=instance_ids,
            target_scope=target_scope,
        )

    def execute(self, project_id: str, plan_id: str):
        self._changes.assert_ready(project_id)
        return self.workbench(project_id).execute_plan(plan_id)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            services = list(self._services.values())
            self._services.clear()
        for service in services:
            try:
                service["workbench"].close()
            finally:
                service["research"].close()
        self.projects.close()
        # Owned background pool: a per-project close never shuts it; only the
        # application teardown does.
        self._executor.shutdown(wait=True)

    # -- helpers ------------------------------------------------------
    def _revision_units(self, project_id: str, revision_id: str | None):
        if revision_id is None:
            revision = self.projects.revision(project_id)
            revision_id = revision.id
        units = []
        offset = 0
        while True:
            page = self.projects.files(project_id, revision_id, offset=offset, limit=PAGE)
            units.extend(page.items)
            offset += len(page.items)
            if offset >= page.total or not page.items:
                break
            if offset >= MAX_PLAN_FILES:
                raise ValueError("Project revision exceeds the planning file cap")
        return units

    @staticmethod
    def _module_relative(units, module: str) -> str:
        # ``python -m package`` executes ``package/__main__.py``; the package
        # ``__init__`` stays indexed but is not the executed unit.
        package_main = module + ".__main__"
        for unit in units:
            if package_main in unit.module_names:
                return unit.relative_path
        for unit in units:
            if module in unit.module_names:
                return unit.relative_path
        raise ValueError("Entry module is not part of the indexed revision")
