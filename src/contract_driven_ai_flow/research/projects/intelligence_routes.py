"""P4 provider-neutral project-intelligence HTTP gateway.

Every route carries an explicit ``project_id`` and builds a short-lived,
immutable :class:`ProjectIntelligenceService` bound to that one project: there is
no ambient current project and no vendor/profile default. The gateway never
queues or calls a model for the dry-run preview, and it re-checks identity,
latest revision and partial-transaction recovery before any model or queue
access. Context reads come only from the project's own workbench store.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..workbench.intelligence.context import token_bound
from .ai_models import ProjectAIRequest, ProjectContextPreview
from .context import ProjectConflictError
from .intelligence import ProjectIntelligenceService


def attach_project_intelligence_routes(
    app, application, *, prefix="/api/v1/research/projects"
):
    router = APIRouter(prefix=prefix)

    def _project(project_id: str):
        try:
            return application.projects.project(project_id)
        except (KeyError, OSError):
            raise HTTPException(404, "Unknown project")

    def _latest(project_id: str) -> str:
        return _project(project_id).latest_revision_id or ""

    def _service(project_id: str) -> ProjectIntelligenceService:
        _project(project_id)
        return ProjectIntelligenceService(application, project_id)

    def _identity(project_id: str, body: ProjectAIRequest) -> None:
        if body.project_id != project_id:
            raise HTTPException(
                409, "Request project does not match the addressed project"
            )

    def _version(project_id: str, body: ProjectAIRequest) -> None:
        latest = _latest(project_id)
        if not latest:
            raise HTTPException(409, "Project has no published revision")
        if body.project_revision_id != latest:
            raise HTTPException(
                409, "Project revision changed; re-index or open the current revision"
            )

    def _conflict(error) -> HTTPException:
        if isinstance(error, (ProjectConflictError, RuntimeError)):
            return HTTPException(409, str(error))
        return HTTPException(422, str(error))

    @router.post(
        "/{project_id}/intelligence/context",
        response_model=ProjectContextPreview,
    )
    def preview(project_id: str, body: ProjectAIRequest):
        service = _service(project_id)
        _identity(project_id, body)
        _version(project_id, body)
        try:
            context = service.context(body)
            tools = service.tools(body, context=context)
            messages = context.assemble(body, tools, service.skills)
        except (ValueError, LookupError, RuntimeError) as error:
            raise _conflict(error)
        definitions = [
            {"name": item["name"], "description": item.get("description", "")}
            for item in tools.describe(body)
        ]
        return ProjectContextPreview(
            project_id=project_id,
            project_revision_id=body.project_revision_id,
            messages=messages,
            token_bound=token_bound(messages),
            tools=definitions,
        )

    @router.post("/{project_id}/intelligence", status_code=202)
    def ask(project_id: str, body: ProjectAIRequest):
        service = _service(project_id)
        _identity(project_id, body)
        _version(project_id, body)
        # Resolve the full read scope/permission set without touching a model,
        # then hand off to an owned job whose execute path re-checks everything
        # (including the live recovery journal) before any inference is sent.
        try:
            context = service.context(body)
            context.validate_request(body)
        except (ValueError, LookupError, RuntimeError) as error:
            raise _conflict(error)
        try:
            return service.ask(body)
        except (ValueError, RuntimeError) as error:
            raise HTTPException(409, str(error))

    @router.get("/{project_id}/intelligence/contexts/{context_id}")
    def context_record(project_id: str, context_id: str):
        _project(project_id)
        store = application.workbench(project_id).store
        try:
            record = store.get("contexts", context_id)
        except (KeyError, LookupError):
            raise HTTPException(404, "Unknown context record")
        # The record must belong to this exact project and be explicitly bound
        # to a published revision of it. A legacy single-file context (no
        # project_revision_id) is never implicitly attributed to a project.
        if record.get("project_id") != project_id:
            raise HTTPException(404, "Unknown context record")
        revision_id = record.get("project_revision_id")
        if not revision_id:
            raise HTTPException(404, "Unknown context record")
        try:
            application.projects.revision(project_id, revision_id)
        except (KeyError, LookupError):
            raise HTTPException(404, "Unknown context record")
        return record

    app.include_router(router)
    return router
