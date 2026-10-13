"""Project-level (P1) records: identity, revisions and bounded pages."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, JsonValue

from ..models import WireModel, timestamp
from ..workbench.models import ProjectSection, RunConfiguration
from ..workbench.semantic_models import SemanticGraph

__all__ = [
    "RunConfiguration",
    "ProjectSection",
    "SourceUnit",
    "FilePage",
    "ProjectRevision",
    "ProjectGraphSlice",
    "ResearchProject",
    "ProjectLoadedFile",
    "ProjectExecutionReceipt",
]


class ProjectLoadedFile(WireModel):
    """One file the interpreter actually entered during a project run.

    Paths are root-relative and sanitized; no machine path or source body is
    ever carried. ``file_id`` is empty for an in-root file outside the frozen
    manifest, which keeps a coverage gap explicit instead of implying membership.
    """

    path: str = ""
    file_id: str = ""
    digest: str = ""
    project_id: str = ""
    project_revision_id: str = ""
    module_name: str = ""
    state: Literal["entered", "completed", "failed"] = "entered"
    coverage: Literal["supported", "unsupported", "partial"] = "supported"
    count: int = Field(default=1, ge=1)


class ProjectExecutionReceipt(WireModel):
    """Durable loaded-file receipt attached to a project run finish payload.

    ``complete`` means the load ledger was finalized and flushed, independent of
    whether the user's calculation succeeded; any budget omission makes it false.
    """

    project_id: str = ""
    project_revision_id: str = ""
    loaded_count: int = Field(default=0, ge=0)
    loaded_files: list[ProjectLoadedFile] = Field(default_factory=list)
    omitted_from_summary: int = Field(default=0, ge=0)
    omitted_count: int = Field(default=0, ge=0)
    complete: bool = False
    coverage: dict[str, JsonValue] = Field(default_factory=dict)


class SourceUnit(WireModel):
    id: str
    relative_path: str
    digest: str = ""
    analysis_id: str = ""
    module_names: list[str] = Field(default_factory=list)
    status: Literal["parsed", "error"] = "parsed"
    diagnostics: list[str] = Field(default_factory=list)


class FilePage(WireModel):
    protocol_version: Literal[1] = 1
    items: list[SourceUnit] = Field(default_factory=list)
    total: int = Field(default=0, ge=0)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=200, ge=1)
    project_id: str = ""
    revision_id: str = ""


class ProjectRevision(WireModel):
    protocol_version: Literal[1] = 1
    id: str
    project_id: str
    parent_revision_id: str | None = None
    created_at: str = Field(default_factory=timestamp)
    files_count: int = Field(default=0, ge=0)
    parsed_files: int = Field(default=0, ge=0)
    reused_files: int = Field(default=0, ge=0)
    diagnostics: list[str] = Field(default_factory=list)


class ResearchProject(WireModel):
    protocol_version: Literal[1] = 1
    id: str
    root: str
    name: str = ""
    latest_revision_id: str | None = None
    source_roots: list[str] = Field(default_factory=list)
    include: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)
    run_configurations: list[RunConfiguration] = Field(default_factory=list)


class ProjectGraphSlice(WireModel):
    protocol_version: Literal[1] = 1
    graph: SemanticGraph = Field(default_factory=SemanticGraph)
    project_id: str = ""
    revision_id: str = ""
    scope_id: str | None = None
    view: Literal["code", "data"] = "code"
    omitted_count: int = Field(default=0, ge=0)