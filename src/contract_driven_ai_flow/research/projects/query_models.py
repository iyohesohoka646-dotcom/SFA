"""Typed, versioned query payloads for the P3 project HTTP gateway.

Exported here so a later schema worker can publish them without touching the
route or service layers.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from ..models import SourceRef, WireModel
from ..workbench.semantic_models import TargetRef

__all__ = [
    "TreeItem",
    "TreePage",
    "ObjectItem",
    "ObjectPage",
    "SymbolRef",
    "SymbolPage",
    "ReferenceItem",
    "ReferencePage",
]


class TreeItem(WireModel):
    id: str
    parent_id: str | None = None
    kind: Literal["project", "folder", "file"] = "file"
    label: str
    path: str = ""
    file_id: str | None = None
    child_count: int = Field(default=0, ge=0)
    target: TargetRef | None = None


class TreePage(WireModel):
    protocol_version: Literal[1] = 1
    project_id: str = ""
    revision_id: str = ""
    items: list[TreeItem] = Field(default_factory=list)
    total: int = Field(default=0, ge=0)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=200, ge=1)


class ObjectItem(WireModel):
    target: TargetRef
    name: str
    kind: str = "assignment"
    line: int = Field(default=0, ge=0)
    end_line: int = Field(default=0, ge=0)
    type: str | None = None
    shape: list[int] | None = None
    probe_count: int = Field(default=0, ge=0)
    probe_status: Literal["normal", "failed", "unknown"] = "unknown"
    source: SourceRef = Field(default_factory=SourceRef)


class ObjectPage(WireModel):
    protocol_version: Literal[1] = 1
    project_id: str = ""
    revision_id: str = ""
    items: list[ObjectItem] = Field(default_factory=list)
    total: int = Field(default=0, ge=0)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=200, ge=1)


class SymbolRef(WireModel):
    name: str
    kind: str = "function"
    scope: str = "<module>"
    line: int = Field(default=0, ge=0)
    end_line: int = Field(default=0, ge=0)
    logical_key: str = ""
    source: SourceRef = Field(default_factory=SourceRef)


class SymbolPage(WireModel):
    protocol_version: Literal[1] = 1
    project_id: str = ""
    revision_id: str = ""
    items: list[SymbolRef] = Field(default_factory=list)
    total: int = Field(default=0, ge=0)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=200, ge=1)


class ReferenceItem(WireModel):
    kind: Literal["call", "import", "argument", "return", "contains"] = "call"
    name: str = ""
    logical_key: str = ""
    provenance: Literal["inferred", "declared", "observed", "unknown"] = "inferred"
    source: SourceRef = Field(default_factory=SourceRef)
    target: SourceRef | None = None
    target_line: int = Field(default=0, ge=0)


class ReferencePage(WireModel):
    protocol_version: Literal[1] = 1
    project_id: str = ""
    revision_id: str = ""
    items: list[ReferenceItem] = Field(default_factory=list)
    total: int = Field(default=0, ge=0)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=200, ge=1)


