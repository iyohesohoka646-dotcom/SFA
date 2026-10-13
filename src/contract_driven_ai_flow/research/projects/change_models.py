"""Wire models for reviewed multi-file project changes (public, sanitized)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from ..models import WireModel, timestamp

__all__ = [
    "ChangeValidation",
    "ProjectFileEdit",
    "ProjectChangeSet",
    "ProjectChangeEditRequest",
    "ProjectChangeProposalRequest",
    "ProjectChangeActionRequest",
    "ProjectChangePage",
    "ProjectRecoveryState",
]

Operation = Literal["modify", "create", "format"]
Status = Literal[
    "ready", "invalid", "accepted", "rejected", "conflict", "recovery_required"
]


class ChangeValidation(WireModel):
    kind: str
    status: Literal["pass", "fail", "not_run", "not_validated"] = "not_validated"
    detail: str = ""


class ProjectFileEdit(WireModel):
    protocol_version: Literal[1] = 1
    path: str
    before_digest: str = ""
    after_digest: str = ""
    before_exists: bool = True
    operation: Operation = "modify"
    content: str = ""
    diff: str = ""
    diagnostics: list[str] = Field(default_factory=list)


class ProjectChangeSet(WireModel):
    protocol_version: Literal[1] = 1
    id: str
    project_id: str
    base_revision: str = ""
    status: Status = "ready"
    files: list[ProjectFileEdit] = Field(default_factory=list)
    validation: list[ChangeValidation] = Field(default_factory=list)
    affected_references: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=timestamp)
    accepted_revision: str | None = None
    rollback_of: str | None = None


class ProjectChangeEditRequest(WireModel):
    """One requested file edit inside a reviewed proposal; content stays inert."""

    path: str = Field(max_length=4096)
    content: str = ""
    operation: Operation = "modify"


class ProjectChangeProposalRequest(WireModel):
    """POST body for creating a reviewed proposal.

    Per-file/per-set budgets (32 files, 1 MiB total) stay enforced by the change
    engine, never by the wire model, so the same limits apply to calls that skip
    the HTTP layer.
    """

    base_revision: str = Field(max_length=128)
    edits: list[ProjectChangeEditRequest] = Field(default_factory=list)


class ProjectChangeActionRequest(WireModel):
    """Review action body: the caller's expected latest project revision."""

    expected_revision: str = Field(max_length=128)


class ProjectChangePage(WireModel):
    """GET /{pid}/changes: the sanitized reviewed-proposal page."""

    protocol_version: Literal[1] = 1
    project_id: str = ""
    revision_id: str = ""
    items: list[ProjectChangeSet] = Field(default_factory=list)
    recovery_required: bool = False


class ProjectRecoveryState(WireModel):
    """GET /{pid}/changes/recovery: a public recovery summary, no private data."""

    protocol_version: Literal[1] = 1
    project_id: str = ""
    revision_id: str = ""
    required: bool = False
    change_id: str | None = None

