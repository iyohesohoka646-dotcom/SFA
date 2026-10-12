"""Wire models for reviewed multi-file project changes (public, sanitized)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from ..models import WireModel, timestamp

__all__ = ["ChangeValidation", "ProjectFileEdit", "ProjectChangeSet"]

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
