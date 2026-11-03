"""Bounded project-intelligence (P4) request and receipt models.

These models are intentionally additive over the shared workbench harness
protocol: a project request is a plain ``HarnessRequest`` plus the frozen
project/revision identity and an explicit, optional read-narrowing task scope.
They carry no model vendor defaults, keys or execution authority.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from ..models import WireModel
from ..workbench.intelligence.harness import HarnessRequest
from ..workbench.semantic_models import ScopeSelector

__all__ = [
    "ProjectAIRequest",
    "ProjectContextPreview",
    "ProjectFileInventoryItem",
    "ProjectContextManifest",
    "ProjectReadPermission",
    "ProjectToolReceipt",
    "ProjectEvidenceReceipt",
]


class ProjectAIRequest(HarnessRequest):
    """One task-scoped project question bound to an immutable revision.

    ``analysis_id`` stays for shared-harness compatibility but is unused by
    project work and defaults to the empty string.
    """

    analysis_id: str = ""
    project_id: str = Field(min_length=1)
    project_revision_id: str = Field(min_length=1)
    entry_id: str | None = None
    scope_id: str | None = None
    file_ids: list[str] | None = Field(default=None, max_length=4096)
    scope: ScopeSelector | None = None


class ProjectFileInventoryItem(WireModel):
    """A bounded, source-free inventory entry (relative name + kind only)."""

    file_id: str
    path: str
    kind: str = "file"


class ProjectReadPermission(WireModel):
    """Permission summary: which indexed files, and which line spans, are readable."""

    file_id: str
    path: str
    digest: str = ""
    whole_file: bool = True
    ranges: list[list[int]] = Field(default_factory=list)


class ProjectContextManifest(WireModel):
    """The typed, sanitized initial-context manifest assembled for one request."""

    project_id: str
    project_revision_id: str
    files_total: int = 0
    inventory: list[ProjectFileInventoryItem] = Field(default_factory=list)
    inventory_total: int = 0
    inventory_truncated: bool = False
    entry: dict = Field(default_factory=dict)
    scope_mode: str = "project"
    scope_id: str | None = None
    permissions: list[ProjectReadPermission] = Field(default_factory=list)
    permission_summary: str = ""
    tools: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    role: str = "explain"
    samples_allowed: bool = False
    omitted: list[str] = Field(default_factory=list)


class ProjectToolReceipt(WireModel):
    """A versioned tool receipt: the only token a model may cite."""

    reference: str
    tool: str
    project_id: str
    project_revision_id: str
    coverage: str = ""
    target: str = ""


class ProjectEvidenceReceipt(WireModel):
    """An evidence receipt for a sanitized snapshot observation."""

    reference: str
    snapshot_id: str
    project_id: str
    project_revision_id: str
    version: int = 1
    fidelity: Literal["exact", "sampled", "metadata_only"] = "metadata_only"
    redacted: bool = False

class ProjectContextPreview(WireModel):
    """Typed, inert preview of the bounded initial context for one request.

    It carries only the frozen project/revision identity, the assembled chat
    messages, a conservative token bound and the json tool descriptors. Building
    it never contacts a model profile, sends inference or persists a task, and
    the inventory is bounded to relative names and kinds (no source bodies).
    """

    project_id: str
    project_revision_id: str
    messages: list[dict] = Field(default_factory=list)
    token_bound: int = Field(default=0, ge=0)
    tools: list[dict] = Field(default_factory=list)