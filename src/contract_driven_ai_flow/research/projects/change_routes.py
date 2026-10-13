"""P4 reviewed project-change HTTP gateway.

Every route carries an explicit ``pid`` and only ever touches the shared
``app.state.projects`` application: there is no ambient project. The gateway is a
thin adapter over :class:`ProjectChangeService`; proposals stay inert and no
route imports, executes or applies user code. Acceptance is a reviewed action
that applies private exact bytes and then publishes a new revision through the
shared workbench job queue.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .change_models import (
    ProjectChangeActionRequest,
    ProjectChangePage,
    ProjectChangeProposalRequest,
    ProjectRecoveryState,
)
from .changes import ProjectChangeService


def _run_accept(
    application, changes, project_id, change_id, expected_revision, *, cancel=None, task=None
):
    """Apply one reviewed change and bind it to a freshly published revision.

    The expected revision is re-checked inside the job so a change that went
    stale while queued fails explicitly instead of writing over a newer revision.
    The actual cancel token is honored before any write; once the reviewed bytes
    are committed the publication/binding always completes and is recorded as a
    real completion, even if a cancellation arrives while it was in flight.
    """
    if cancel is not None and cancel.is_set():
        raise InterruptedError("Project change acceptance cancelled")
    if (application.projects.project(project_id).latest_revision_id or "") != expected_revision:
        raise RuntimeError("Project revision changed before the change could be applied")
    # Raising here means an interruption/conflict: the change record carries the
    # recovery_required/conflict state and no indexing happens on a half write.
    changes.accept(project_id, change_id, cancel=cancel)
    # Commit point: the reviewed bytes are durably applied and the record is
    # accepted. From here the new revision must be published and bound, and no
    # late cancellation may turn that real completion into "cancelled".
    if task is not None:
        application.workbench(project_id).jobs.mark_committed(task.id)
    try:
        revision = application.index(project_id)
        changes.mark_indexed(project_id, change_id, revision.id)
    except Exception as error:
        # The reviewed source is already applied and accepted. Only the publish
        # step failed, so accepted_revision must stay unset rather than claiming
        # a revision that does not exist.
        raise RuntimeError(
            "The reviewed source was applied and accepted, but the new revision is not "
            f"published yet (indexing/binding failed: {type(error).__name__}). "
            "The accepted revision stays unset; reindex the project to publish it."
        )
    return {
        "message": f"Applied change {change_id} as revision {revision.id}",
        "project_revision_id": revision.id,
        "receipt": {
            "change_id": change_id,
            "project_id": project_id,
            "project_revision_id": revision.id,
        },
    }


def attach_project_change_routes(app, application, *, prefix="/api/v1/research/projects"):
    changes = ProjectChangeService(application.projects)
    app.state.project_changes = changes
    router = APIRouter(prefix=prefix)

    def _project(project_id: str):
        try:
            return application.projects.project(project_id)
        except (KeyError, OSError):
            raise HTTPException(404, "Unknown project")

    def _latest(project_id: str) -> str:
        return _project(project_id).latest_revision_id or ""

    def _expect_latest(project_id: str, expected_revision: str) -> None:
        if expected_revision != _latest(project_id):
            raise HTTPException(409, "Project revision changed; refresh before continuing")

    def _guard_recovery(project_id: str) -> None:
        try:
            changes.assert_ready(project_id)
        except RuntimeError as error:
            raise HTTPException(409, str(error))

    def _record(project_id: str, change_id: str):
        try:
            return changes.get(project_id, change_id)
        except LookupError:
            raise HTTPException(404, "Unknown change set")

    # -- literal recovery routes, registered before /{change_id} --------
    @router.get("/{project_id}/changes/recovery", response_model=ProjectRecoveryState)
    def recovery_state(project_id: str):
        project = _project(project_id)
        state = changes.recovery_state(project_id)
        return ProjectRecoveryState(
            project_id=project_id,
            revision_id=project.latest_revision_id or "",
            required=bool(state["required"]),
            change_id=state.get("change_id"),
        )

    @router.post("/{project_id}/changes/recover", status_code=200)
    def recover(project_id: str, body: ProjectChangeActionRequest):
        _expect_latest(project_id, body.expected_revision)
        try:
            return changes.recover(project_id)
        except LookupError:
            raise HTTPException(404, "Unknown change set")
        except (ValueError, RuntimeError) as error:
            raise HTTPException(409, str(error))

    # -- collection -----------------------------------------------------
    @router.get("/{project_id}/changes", response_model=ProjectChangePage)
    def list_changes(project_id: str):
        project = _project(project_id)
        state = changes.recovery_state(project_id)
        return ProjectChangePage(
            project_id=project_id,
            revision_id=project.latest_revision_id or "",
            items=changes.list(project_id),
            recovery_required=bool(state["required"]),
        )

    @router.post("/{project_id}/changes", status_code=200)
    def propose(project_id: str, body: ProjectChangeProposalRequest):
        project = _project(project_id)
        latest = project.latest_revision_id
        if not latest:
            raise HTTPException(409, "Project has no published revision to review against")
        if body.base_revision != latest:
            # An unknown revision is a 404; a superseded one is a 409 conflict.
            try:
                application.projects.revision(project_id, body.base_revision)
            except (KeyError, LookupError):
                raise HTTPException(404, "Unknown project revision")
            raise HTTPException(409, "Project revision changed; refresh before proposing")
        try:
            return changes.propose(
                project_id,
                body.base_revision,
                [edit.model_dump() for edit in body.edits],
            )
        except LookupError:
            raise HTTPException(404, "Unknown project revision")
        except RuntimeError as error:
            raise HTTPException(409, str(error))
        except ValueError as error:
            raise HTTPException(422, str(error))

    # -- review actions -------------------------------------------------
    @router.post("/{project_id}/changes/{change_id}/accept", status_code=202)
    def accept(project_id: str, change_id: str, body: ProjectChangeActionRequest):
        project = _project(project_id)
        record = _record(project_id, change_id)
        _guard_recovery(project_id)
        _expect_latest(project_id, body.expected_revision)
        if record.status != "ready":
            raise HTTPException(409, "Only a ready change set can be accepted")
        if record.base_revision and record.base_revision != (project.latest_revision_id or ""):
            raise HTTPException(409, "Project revision changed since this proposal was created")
        jobs = application.workbench(project_id).jobs
        return jobs.submit(
            "project.change.accept",
            lambda job, cancel: _run_accept(
                application,
                changes,
                project_id,
                change_id,
                body.expected_revision,
                cancel=cancel,
                task=job,
            ),
            receipt={"change_id": change_id, "project_id": project_id},
        )

    @router.post("/{project_id}/changes/{change_id}/reject", status_code=200)
    def reject(project_id: str, change_id: str, body: ProjectChangeActionRequest):
        _project(project_id)
        _record(project_id, change_id)
        _guard_recovery(project_id)
        _expect_latest(project_id, body.expected_revision)
        try:
            return changes.reject(project_id, change_id)
        except (ValueError, RuntimeError) as error:
            raise HTTPException(409, str(error))

    @router.post("/{project_id}/changes/{change_id}/rollback", status_code=200)
    def rollback(project_id: str, change_id: str, body: ProjectChangeActionRequest):
        _project(project_id)
        _record(project_id, change_id)
        _guard_recovery(project_id)
        _expect_latest(project_id, body.expected_revision)
        try:
            return changes.rollback(project_id, change_id)
        except (ValueError, RuntimeError) as error:
            raise HTTPException(409, str(error))

    @router.get("/{project_id}/changes/{change_id}")
    def get_change(project_id: str, change_id: str):
        _project(project_id)
        return _record(project_id, change_id)

    app.include_router(router)
    return router
