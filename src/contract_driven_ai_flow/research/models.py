"""Versioned, backend-neutral wire models for scientific observations."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


class WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)


class SourceRef(WireModel):
    path: str = ""
    qualname: str = ""
    line: int = Field(default=0, ge=0)
    end_line: int = Field(default=0, ge=0)
    digest: str = ""
    code: str = ""


class ValueDescriptor(WireModel):
    schema_version: Literal[1] = 1
    kind: str
    backend: str
    type_name: str
    shape: list[int] | None = None
    dtype: str | None = None
    nbytes: int | None = Field(default=None, ge=0)
    device: str | None = None
    axes: list[str] = Field(default_factory=list)
    unit: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class SnapshotRef(WireModel):
    id: str
    run_id: str
    binding_id: str
    scope_id: str
    name: str
    version: int = Field(ge=1)
    descriptor: ValueDescriptor
    observed_at: str = Field(default_factory=timestamp)
    source: SourceRef | None = None
    operation_id: str | None = None
    parents: list[str] = Field(default_factory=list)
    provenance: Literal["observed", "inferred", "declared", "unknown"] = "unknown"
    fidelity: Literal["exact", "sampled", "metadata_only"] = "metadata_only"
    sample: dict[str, JsonValue] = Field(default_factory=dict)
    statistics: dict[str, JsonValue] = Field(default_factory=dict)
    truncation: list[str] = Field(default_factory=list)
    redacted: list[str] = Field(default_factory=list)
    artifact_ref: str | None = None
    coverage: dict[str, JsonValue] = Field(default_factory=dict)


class OperationRecord(WireModel):
    id: str
    run_id: str
    label: str
    source: SourceRef | None = None
    scope_id: str = "main"
    iteration: int = 1
    input_snapshots: list[str] = Field(default_factory=list)
    output_snapshots: list[str] = Field(default_factory=list)
    kind: str = "custom"
    status: str = "started"
    duration_ms: float | None = None
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
    provenance: Literal["observed", "inferred", "declared", "unknown"] = "unknown"


class ObservationEvent(WireModel):
    schema_version: Literal[1] = 1
    run_id: str
    sequence: int = Field(default=0, ge=0)
    kind: str
    timestamp: str = Field(default_factory=timestamp)
    source: SourceRef | None = None
    operation_id: str | None = None
    snapshot_id: str | None = None
    payload: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def strict_json(self):
        if self.kind == "value.observed" and "snapshot" in self.payload:
            self.payload["snapshot"] = SnapshotRef.model_validate(self.payload["snapshot"]).model_dump(mode="json")
        if self.kind.startswith("operation.") and "operation" in self.payload:
            self.payload["operation"] = OperationRecord.model_validate(self.payload["operation"]).model_dump(mode="json")
        # Prevent NaN/Infinity from crossing JSON and browser boundaries.
        encoded = json.dumps(self.model_dump(mode="json"), ensure_ascii=False, allow_nan=False)
        if len(encoded.encode("utf-8")) > 2 * 1024 * 1024:
            raise ValueError("Observation exceeds the 2 MiB event limit")
        return self


class ProbeSpec(WireModel):
    id: str
    kind: str = "finite"
    binding: str = "*"
    enabled: bool = True
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
    policy: Literal["continue", "pause", "cancel"] = "continue"
    budget_ms: int = Field(default=50, ge=1, le=30000)
    protocol_version: Literal[1] = 1


class ProbeResult(WireModel):
    probe_id: str
    snapshot_id: str
    status: Literal["pass", "fail", "error", "skipped", "unknown"]
    fidelity: Literal["exact", "sampled", "metadata_only"] = "metadata_only"
    message: str = ""
    evidence: dict[str, JsonValue] = Field(default_factory=dict)
    duration_ms: float = 0


class ExperimentSpec(WireModel):
    schema_version: Literal[1] = 1
    name: str = "Scientific analysis"
    script: str
    interpreter: str = ""
    arguments: list[str] = Field(default_factory=list)
    capture: dict[str, JsonValue] = Field(default_factory=dict)
    annotations: dict[str, JsonValue] = Field(default_factory=dict)
    adapters: list[str] = Field(default_factory=list)
    probes: list[ProbeSpec] = Field(default_factory=list)


class Explanation(WireModel):
    operation_id: str
    text: str
    origin: Literal["rule", "annotation", "model"] = "rule"
    evidence: list[str] = Field(default_factory=list)
    uncertainty: list[str] = Field(default_factory=list)
