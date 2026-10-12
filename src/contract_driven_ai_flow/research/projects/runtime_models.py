"""Typed, secret-free public models for machine runtime references.

These describe the *sanitized* view the HTTP gateway returns: symbolic
reference ids and environment variable *names* only. Actual interpreter paths
and environment values never appear here, in a project document, in a public
plan or in a receipt.
"""

from __future__ import annotations

from pydantic import Field

from ..models import WireModel


class InterpreterReference(WireModel):
    id: str


class EnvironmentReference(WireModel):
    id: str
    keys: list[str] = Field(default_factory=list)


class RuntimeReferenceState(WireModel):
    """Fresh, sanitized machine runtime state (never carries private values)."""

    revision: int = Field(default=0, ge=0)
    interpreters: list[InterpreterReference] = Field(default_factory=list)
    environments: list[EnvironmentReference] = Field(default_factory=list)
    legacy_environment: list[str] = Field(default_factory=list)


class InterpreterReferenceRequest(WireModel):
    expected_revision: int = Field(ge=0)
    path: str = Field(max_length=4096)


class EnvironmentReferenceRequest(WireModel):
    expected_revision: int = Field(ge=0)
    values: dict[str, str] = Field(default_factory=dict)
