"""Protocol v2 describes intent without changing observation protocol v1."""
from __future__ import annotations

from typing import Literal
from uuid import uuid4

from pydantic import Field, JsonValue, field_validator

from ..models import WireModel, timestamp
from .semantic_models import SemanticGraph, TargetRef, ScopeSelector


def uid() -> str:
    return uuid4().hex


class SourceObject(WireModel):
    id: str
    path: str
    qualname: str
    name: str
    scope: str = '<module>'
    kind: Literal['function', 'class', 'assignment', 'parameter', 'import', 'step']
    line: int
    end_line: int
    column: int = 0
    end_column: int = 0
    logical_key: str = ''
    block_id: str = ''
    source_digest: str
    code: str = ''
    inputs: list[str] = Field(default_factory=list)
    mutation: bool = False
    provenance: Literal['inferred', 'declared'] = 'inferred'


class Relation(WireModel):
    source: str
    target: str
    label: str = 'depends on'
    provenance: Literal['observed', 'inferred', 'declared', 'unknown'] = 'inferred'
    evidence: list[str] = Field(default_factory=list)


class AnalysisDocument(WireModel):
    protocol_version: Literal[2, 3] = 3
    id: str = Field(default_factory=uid)
    path: str
    source_digest: str
    objects: list[SourceObject] = Field(default_factory=list)
    relations: list[Relation] = Field(default_factory=list)
    graph: SemanticGraph = Field(default_factory=SemanticGraph)
    diagnostics: list[str] = Field(default_factory=list)
    imported_at: str = Field(default_factory=timestamp)


class ProbeDefinition(WireModel):
    id: str
    label: str
    capability: Literal['view', 'check', 'interpret']
    execution: Literal['builtin', 'program', 'model', 'skill', 'manual']
    supported_kinds: list[str] = Field(default_factory=list)
    tool_id: str | None = None
    parameter_schema: dict[str, JsonValue] = Field(default_factory=dict)
    version: str = '1'


class ProbeInstance(WireModel):
    id: str = Field(default_factory=uid)
    definition_id: str
    binding: str = '*'
    enabled: bool = True
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
    policy: Literal['continue', 'pause', 'cancel'] = 'continue'
    budget_ms: int = Field(default=5000, ge=1, le=120000)


class ProbeOutput(WireModel):
    protocol_version: Literal[2] = 2
    id: str = Field(default_factory=uid)
    instance_id: str
    definition_id: str
    capability: Literal['view', 'check', 'interpret']
    execution: Literal['builtin', 'program', 'model', 'skill', 'manual']
    status: Literal['ready', 'pass', 'fail', 'error', 'skipped', 'unknown', 'cancelled']
    run_id: str | None = None
    snapshot_id: str | None = None
    analysis_id: str | None = None
    created_at: str = Field(default_factory=timestamp)
    fidelity: str = 'metadata_only'
    message: str = ''
    data: dict[str, JsonValue] = Field(default_factory=dict)
    artifact_id: str | None = None
    cache_key: str = ''
    duration_ms: float = 0
    provenance: Literal['observed', 'inferred', 'declared', 'manual', 'model', 'skill', 'unknown'] = 'observed'


class HarnessPolicy(WireModel):
    role: Literal['parse', 'explain', 'probe', 'code'] = 'explain'
    provider_id: str = 'offline'
    model: str | None = None
    input_tokens: int = Field(default=12000, ge=512, le=128000)
    output_tokens: int = Field(default=2048, ge=128, le=16384)
    max_steps: int = Field(default=6, ge=1, le=16)
    max_calls: int = Field(default=6, ge=1, le=16)
    include_samples: bool = False
    allow_execute: bool = False


class WorkbenchConfig(WireModel):
    protocol_version: Literal[2] = 2
    revision: int = Field(default=0, ge=0)
    script: str = ''
    interpreter: str = ''
    arguments: list[str] = Field(default_factory=list, max_length=256)
    capture: Literal['metadata', 'summary', 'sample', 'full'] = 'summary'
    probes: list[ProbeInstance] = Field(default_factory=lambda: [
        ProbeInstance(id='auto-view', definition_id='view.auto'),
        ProbeInstance(id='finite-check', definition_id='check.finite'),
    ], max_length=128)
    adapters: list[str] = Field(default_factory=list)
    harness: list[HarnessPolicy] = Field(default_factory=lambda: [HarnessPolicy(role=role) for role in ('parse', 'explain', 'probe', 'code')])
    max_outputs: int = Field(default=128, ge=1, le=512)

    @field_validator('harness')
    @classmethod
    def complete_roles(cls, value):
        if len(value) != 4 or {policy.role for policy in value} != {'parse', 'explain', 'probe', 'code'}:
            raise ValueError('harness roles must include parse, explain, probe and code exactly once')
        return value


class ExecutionPlan(WireModel):
    protocol_version: Literal[2] = 2
    id: str = Field(default_factory=uid)
    created_at: str = Field(default_factory=timestamp)
    analysis_id: str
    source_digest: str
    config_digest: str
    environment_digest: str = ''
    config: WorkbenchConfig
    definitions: list[ProbeDefinition]
    scope: Literal['compute', 'probes', 'replot'] = 'compute'
    run_id: str | None = None
    snapshot_ids: list[str] = Field(default_factory=list)
    diagnostics: list[str] = Field(default_factory=list)


class TaskRecord(WireModel):
    protocol_version: Literal[2] = 2
    id: str = Field(default_factory=uid)
    kind: str
    status: Literal['queued', 'running', 'completed', 'failed', 'cancelled', 'interrupted'] = 'queued'
    created_at: str = Field(default_factory=timestamp)
    updated_at: str = Field(default_factory=timestamp)
    plan_id: str | None = None
    run_id: str | None = None
    calculation_status: str = 'not_requested'
    progress: float = Field(default=0, ge=0, le=1)
    output_ids: list[str] = Field(default_factory=list)
    message: str = ''
    receipt: dict[str, JsonValue] = Field(default_factory=dict)


class CodeProposal(WireModel):
    protocol_version: Literal[2] = 2
    id: str = Field(default_factory=uid)
    analysis_id: str
    object_id: str | None = None
    path: str
    source_digest: str
    candidate: str = Field(max_length=16384)
    original_fragment: str | None = None
    diff: str = ''
    diagnostics: list[str] = Field(default_factory=list)
    status: Literal['proposed', 'valid', 'invalid', 'accepted', 'rejected', 'conflict'] = 'proposed'
    behavior: Literal['unverified', 'verified'] = 'unverified'
    accepted_digest: str | None = None
    validation_run_id: str | None = None
    validation_output_ids: list[str] = Field(default_factory=list)
    rollback_of: str | None = None
    created_at: str = Field(default_factory=timestamp)
