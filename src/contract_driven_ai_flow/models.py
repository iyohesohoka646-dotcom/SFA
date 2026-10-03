"""Versioned semantics shared by the compiler, CLI, HTTP API and editor."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def canonical(value: Any) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SymbolRef(Model):
    path: str
    qualname: str
    digest: str = ""


class Contract(Model):
    input: dict[str, Any] = Field(default_factory=lambda: {"type": "object", "properties": {}, "additionalProperties": False})
    output: dict[str, Any] = Field(default_factory=dict)
    examples: list[dict[str, Any]] = Field(default_factory=list)

    @property
    def revision(self) -> str:
        return digest(self)


class Source(Model):
    """A JSON Pointer within project input, module output or a literal value."""
    kind: Literal["project", "module", "literal"]
    module: str | None = None
    pointer: str = ""
    value: Any = None

    @model_validator(mode="after")
    def source_shape(self):
        if self.kind == "module" and not self.module:
            raise ValueError("module source requires a module id")
        if self.pointer and not self.pointer.startswith("/"):
            raise ValueError("pointer must be an RFC 6901 JSON Pointer")
        return self


class PortBinding(Model):
    id: str
    target: str
    port: str
    source: Source
    dynamic: bool = False
    visibility: Literal["L1", "L2", "L3", "L4"] = "L2"
    provenance: Literal["designed", "migrated"] = "designed"


class RouteGuard(Model):
    decision: str
    when: bool


class ModuleSpec(Model):
    id: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_.-]*$")
    name: str = ""
    description: str = ""
    kind: Literal["python", "composite", "decision"] = "python"
    symbol: SymbolRef | None = None
    contract: Contract = Field(default_factory=Contract)
    parent: str | None = None
    # Composite input names are exposed as Source(module=composite, pointer='/name')
    # to immediate children; outputs map public output names to child sources.
    outputs: dict[str, Source] = Field(default_factory=dict)
    condition: str | None = None
    guard: RouteGuard | None = None
    timeout_seconds: float = Field(default=30, gt=0, le=86400)
    retries: int = Field(default=0, ge=0, le=5)
    idempotent: bool = False
    allowed_imports: list[str] = Field(default_factory=lambda: ["json", "math", "typing", "dataclasses", "__future__"])
    dependencies: list[SymbolRef] = Field(default_factory=list)
    side_effects: bool = False

    @model_validator(mode="after")
    def implementation_shape(self):
        if self.kind == "python" and self.symbol is None:
            raise ValueError("Python module needs a symbol")
        if self.kind == "decision" and not self.condition:
            raise ValueError("Decision module needs a condition")
        if self.retries and not self.idempotent:
            raise ValueError("Automatic retries require idempotent=true")
        return self


class ProbeSpec(Model):
    id: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_.-]*$")
    module: str
    binding: str | None = None
    boundary: Literal["input", "output"] = "output"
    kind: Literal["assertion", "metric", "capture", "branch_observer"] = "assertion"
    expression: str = "True"
    policy: Literal["continue", "block", "pause", "breakpoint"] = "continue"
    pointer: str = ""
    enabled: bool = True
    language_version: Literal[1] = 1
    true_target: str | None = None
    false_target: str | None = None


class CapturePolicy(Model):
    level: Literal["metadata", "summary", "sample", "full"] = "summary"
    sensitive_fields: list[str] = Field(default_factory=lambda: ["password", "token", "secret", "api_key", "authorization", "email"])
    max_bytes: int = Field(default=16384, ge=128, le=1048576)
    sample_items: int = Field(default=5, ge=0, le=100)
    retention_days: int = Field(default=7, ge=1, le=365)


class ProjectSpec(Model):
    schema_version: Literal[1] = 1
    name: str = "Contract-Driven AI Flow"
    input_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object"})
    modules: list[ModuleSpec] = Field(default_factory=list)
    bindings: list[PortBinding] = Field(default_factory=list)
    probes: list[ProbeSpec] = Field(default_factory=list)
    capture: CapturePolicy = Field(default_factory=CapturePolicy)
    concurrency: int = Field(default=1, ge=1, le=16)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def revision(self) -> str:
        return digest(self)


class Diagnostic(Model):
    code: str
    message: str
    severity: Literal["error", "warning", "info"] = "error"
    module: str | None = None
    binding: str | None = None


class ExecutionPlan(Model):
    revision: str
    modules: list[ModuleSpec]
    bindings: list[PortBinding]
    order: list[str]
    hierarchy: dict[str, str | None]
    diagnostics: list[Diagnostic]
    composite_inputs: list[PortBinding] = Field(default_factory=list)
    composite_outputs: dict[str, dict[str, Source]] = Field(default_factory=dict)
    dependencies: dict[str, list[str]] = Field(default_factory=dict)

    @property
    def valid(self) -> bool:
        return not any(d.severity == "error" for d in self.diagnostics)


class ProbeResult(Model):
    probe: str
    status: Literal["pass", "fail", "error", "skipped"]
    kind: str
    value: Any = None
    message: str = ""
    policy: str = "continue"
    redacted: list[str] = Field(default_factory=list)


class RunEvent(Model):
    run_id: str
    sequence: int = 0
    time: str
    kind: str
    revision: str
    module: str | None = None
    binding: str | None = None
    attempt: int = 0
    contract_revision: str | None = None
    links: list[dict[str, Any]] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict)


class ChangeSet(Model):
    id: str
    kind: Literal["architecture", "implementation", "rollback"]
    base_revision: str
    created: str
    status: Literal["proposed", "accepted", "rejected", "invalid"] = "proposed"
    title: str
    module: str | None = None
    base_source_digest: str | None = None
    before: str | None = None
    after: str | None = None
    project: ProjectSpec | None = None
    diff: str = ""
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    usage: dict[str, Any] = Field(default_factory=dict)
