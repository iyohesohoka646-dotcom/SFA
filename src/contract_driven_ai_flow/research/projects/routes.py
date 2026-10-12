"""P3 project HTTP gateway: identity, indexing tasks, reads and execution.

The gateway is a thin adapter over one shared :class:`ProjectApplication`. It
never owns a mutable ambient project: every route resolves the project-bound
service by the explicit ``pid`` path parameter.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import Field

from ..models import WireModel
from .indexing import ProjectIndexService
from .queries import ProjectQueryService
from .query_models import ObjectPage, ReferencePage, SymbolPage, TreePage

MAX_PROJECTS = 200


class OpenRequest(WireModel):
    path: str = Field(max_length=4096)


class IndexRequest(WireModel):
    expected_revision: str | None = Field(default=None, max_length=128)


class WatchRequest(WireModel):
    enabled: bool = False


class EntryRequest(WireModel):
    entries: list[dict] = Field(default_factory=list, max_length=64)
    expected_revision: int = Field(ge=0)


class PlanRequest(WireModel):
    configuration_id: str = Field(max_length=256)
    revision_id: str | None = Field(default=None, max_length=128)
    scope: str = "compute"
    run_id: str | None = None
    snapshot_ids: list[str] = Field(default_factory=list, max_length=512)
    instance_ids: list[str] | None = None
    target_scope: dict | None = None


class ExecuteRequest(WireModel):
    plan_id: str = Field(max_length=256)


def _archived(project, record) -> bool:
    from pathlib import Path

    from .store import ProjectStore

    if not record.get("digest"):
        return True
    store = ProjectStore(Path(project.root))
    with store.connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM sources WHERE digest=?", (record["digest"],)
        ).fetchone()
    return row is not None

def attach_project_routes(app, application, *, prefix="/api/v1/research/projects"):
    application.models = getattr(app.state, "models", None) or application.models
    app.state.projects = application
    indexing = ProjectIndexService(application)
    app.state.project_indexing = indexing
    queries = ProjectQueryService(application.projects, application)
    app.state.project_queries = queries
    router = APIRouter(prefix=prefix)

    def _project(project_id: str):
        try:
            return application.projects.project(project_id)
        except KeyError:
            raise HTTPException(404, "Unknown project")

    def _latest(project_id: str):
        return application.projects.project(project_id).latest_revision_id

    @router.get("")
    def recent_projects(limit: int = Query(default=50, ge=1, le=MAX_PROJECTS)):
        rows = []
        with application.projects._connect_registry() as conn:
            rows = conn.execute(
                "SELECT project_id FROM projects ORDER BY name, project_id"
            ).fetchall()
        projects = []
        for row in rows[:limit]:
            try:
                projects.append(
                    application.projects.project(row["project_id"]).model_dump(mode="json")
                )
            except (KeyError, OSError):
                continue
        return projects

    @router.post("/open")
    def open_project(body: OpenRequest):
        return application.open(body.path)

    @router.get("/{project_id}")
    def project_info(project_id: str):
        project = _project(project_id)
        return {
            **project.model_dump(mode="json"),
            "latest_revision_id": project.latest_revision_id,
        }

    # -- indexing and tasks -------------------------------------------
    @router.post("/{project_id}/index", status_code=200)
    def index_project(project_id: str, body: IndexRequest | None = None):
        _project(project_id)
        request = body or IndexRequest()
        try:
            task = indexing.submit(project_id, request.expected_revision)
        except RuntimeError as error:
            raise HTTPException(409, str(error))
        return task

    @router.get("/{project_id}/tasks")
    def tasks(project_id: str):
        _project(project_id)
        return application.workbench(project_id).jobs.list()

    @router.get("/{project_id}/tasks/{task_id}")
    def task(project_id: str, task_id: str):
        _project(project_id)
        return application.workbench(project_id).task(task_id)

    @router.post("/{project_id}/tasks/{task_id}/cancel")
    def cancel_task(project_id: str, task_id: str):
        _project(project_id)
        return application.workbench(project_id).jobs.cancel(task_id)

    @router.put("/{project_id}/watch")
    def watch(project_id: str, body: WatchRequest):
        _project(project_id)
        return indexing.watch(project_id, body.enabled)

    @router.get("/{project_id}/watch")
    def watch_state(project_id: str):
        _project(project_id)
        return {"project_id": project_id, **indexing.watch_status(project_id)}

    # -- typed inert reads --------------------------------------------
    @router.get("/{project_id}/files")
    def files(
        project_id: str,
        revision_id: str | None = None,
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=200, ge=1, le=1000),
    ):
        _project(project_id)
        # An absent revision is an explicit failure, never an empty success.
        header = application.projects.revision(project_id, revision_id)
        return application.projects.files(
            project_id, header.id, offset=offset, limit=limit
        )

    @router.get("/{project_id}/files/{file_id}/analysis")
    def analysis(project_id: str, file_id: str, revision_id: str | None = None):
        _project(project_id)
        return application.projects.analysis(project_id, file_id, revision_id)

    @router.get("/{project_id}/files/{file_id}/source")
    def source(project_id: str, file_id: str, revision_id: str | None = None):
        project = _project(project_id)
        record = application.projects.source(project_id, file_id, revision_id)
        if not _archived(project, record):
            raise HTTPException(404, "Archived source is unavailable")
        return record

    @router.get("/{project_id}/tree", response_model=TreePage)
    def tree(
        project_id: str,
        revision_id: str | None = None,
        parent_id: str | None = None,
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=200, ge=1, le=1000),
    ):
        _project(project_id)
        return queries.tree(project_id, revision_id, parent_id, offset, limit)

    @router.get("/{project_id}/objects", response_model=ObjectPage)
    def objects(
        project_id: str,
        revision_id: str | None = None,
        file_id: str | None = None,
        scope_id: str | None = None,
        query: str | None = None,
        kind: str = "variables",
        probe_status: str = "all",
        run_id: str | None = None,
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=200, ge=1, le=1000),
    ):
        _project(project_id)
        return queries.objects(
            project_id,
            revision_id,
            file_id,
            scope_id,
            query,
            kind,
            probe_status,
            run_id,
            offset,
            limit,
        )

    @router.get("/{project_id}/symbols", response_model=SymbolPage)
    def symbols(
        project_id: str,
        revision_id: str | None = None,
        q: str | None = None,
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=200, ge=1, le=1000),
    ):
        _project(project_id)
        return queries.symbols(project_id, revision_id, q, offset, limit)

    @router.get("/{project_id}/references", response_model=ReferencePage)
    def references(
        project_id: str,
        revision_id: str | None = None,
        file_id: str | None = None,
        symbol: str | None = None,
        logical_key: str | None = None,
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=200, ge=1, le=1000),
    ):
        _project(project_id)
        return queries.references(
            project_id, revision_id, file_id, symbol, logical_key, offset, limit
        )

    @router.get("/{project_id}/graph")
    def graph(
        project_id: str,
        revision_id: str | None = None,
        scope_id: str | None = None,
        view: str = "code",
        limit: int = Query(default=350, ge=1, le=350),
    ):
        _project(project_id)
        return queries.graph(project_id, revision_id, scope_id, view, limit)

    # -- entries, plans and execution ---------------------------------
    @router.get("/{project_id}/entries")
    def entries(project_id: str):
        project = _project(project_id)
        workbench = application.workbench(project_id)
        config = workbench.configurations.load()
        revision_id = project.latest_revision_id
        candidates = (
            application.entry_candidates(project_id, revision_id)
            if revision_id
            else []
        )
        return {
            "project_id": project_id,
            "revision_id": revision_id,
            "config_revision": config.revision,
            "entries": config.run_configurations,
            "candidates": candidates,
        }

    @router.put("/{project_id}/entries")
    def save_entries(project_id: str, body: EntryRequest):
        _project(project_id)
        workbench = application.workbench(project_id)
        current = workbench.configurations.load()
        if current.revision != body.expected_revision:
            raise HTTPException(409, "Configuration revision conflict; reload before saving")
        from ..workbench.models import RunConfiguration

        entries = [RunConfiguration.model_validate(item) for item in body.entries]
        return application.save_entries(
            project_id, entries, expected_revision=body.expected_revision
        )

    @router.post("/{project_id}/plans")
    def plan(project_id: str, body: PlanRequest):
        project = _project(project_id)
        if body.revision_id and body.revision_id != project.latest_revision_id:
            raise HTTPException(409, "Project revision changed; index again before planning")
        try:
            return application.plan(
                project_id,
                body.configuration_id,
                revision_id=body.revision_id or project.latest_revision_id,
                scope=body.scope,
                run_id=body.run_id,
                snapshot_ids=body.snapshot_ids,
                instance_ids=body.instance_ids,
                target_scope=body.target_scope,
            )
        except LookupError:
            raise HTTPException(404, "Unknown run configuration")

    @router.get("/{project_id}/plans/{plan_id}")
    def get_plan(project_id: str, plan_id: str):
        _project(project_id)
        record = application.workbench(project_id).store.get("plans", plan_id)
        if record.get("project_id") != project_id:
            raise HTTPException(404, "Unknown plan")
        return record

    @router.post("/{project_id}/execute", status_code=202)
    def execute(project_id: str, body: ExecuteRequest):
        _project(project_id)
        return application.execute(project_id, body.plan_id)

    app.include_router(router)
    terminal_cleanup = getattr(app.state, "terminal_cleanup", None)

    def cleanup():
        indexing.close()
        if terminal_cleanup is not None:
            terminal_cleanup()

    app.state.project_cleanup = cleanup
    from .change_routes import attach_project_change_routes

    attach_project_change_routes(app, application, prefix=prefix)
    # Machine-scoped runtime profiles are mounted exactly once, beside (not
    # under) the project prefix; the project suffix is never carried over.
    from .runtime_routes import DEFAULT_RUNTIME_PREFIX, attach_runtime_routes

    base = prefix[: -len('/projects')] if prefix.endswith('/projects') else prefix
    runtime_prefix = base.rstrip('/') + '/runtime' if base else DEFAULT_RUNTIME_PREFIX
    attach_runtime_routes(app, application, prefix=runtime_prefix)
    return router






