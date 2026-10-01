/* Generated from Python scientific wire models; scripts/export_schema.py + npm run types. */

export type Path = string;
export type Qualname = string;
export type Line = number;
export type EndLine = number;
export type Digest = string;
export type Code = string;
export type SchemaVersion = 1;
export type Kind = string;
export type Backend = string;
export type TypeName = string;
export type Shape = number[] | null;
export type Dtype = string | null;
export type Nbytes = number | null;
export type Device = string | null;
export type Axes = string[];
export type Unit = string | null;
export type Capabilities = string[];
export type JsonValue = unknown;
export type Id = string;
export type RunId = string;
export type BindingId = string;
export type ScopeId = string;
export type Name = string;
export type Version = number;
export type ObservedAt = string;
export type OperationId = string | null;
export type Parents = string[];
export type Provenance = "observed" | "inferred" | "declared" | "unknown";
export type Fidelity = "exact" | "sampled" | "metadata_only";
export type Truncation = string[];
export type Redacted = string[];
export type ArtifactRef = string | null;
export type Id1 = string;
export type RunId1 = string;
export type Label = string;
export type ScopeId1 = string;
export type Iteration = number;
export type InputSnapshots = string[];
export type OutputSnapshots = string[];
export type Kind1 = string;
export type Status = string;
export type DurationMs = number | null;
export type Provenance1 = "observed" | "inferred" | "declared" | "unknown";
export type SchemaVersion1 = 1;
export type RunId2 = string;
export type Sequence = number;
export type Kind2 = string;
export type Timestamp = string;
export type OperationId1 = string | null;
export type SnapshotId = string | null;
export type Id2 = string;
export type Kind3 = string;
export type Binding = string;
export type Enabled = boolean;
export type Policy = "continue" | "pause" | "cancel";
export type BudgetMs = number;
export type ProtocolVersion = 1;
export type ProbeId = string;
export type SnapshotId1 = string;
export type Status1 = "pass" | "fail" | "error" | "skipped" | "unknown";
export type Fidelity1 = "exact" | "sampled" | "metadata_only";
export type Message = string;
export type DurationMs1 = number;
export type OperationId2 = string;
export type Text = string;
export type Origin = "rule" | "annotation" | "model";
export type Evidence1 = string[];
export type Uncertainty = string[];

export interface ResearchProtocol {
  SourceRef: SourceRef;
  ValueDescriptor: ValueDescriptor;
  SnapshotRef: SnapshotRef;
  OperationRecord: OperationRecord;
  ObservationEvent: ObservationEvent;
  ProbeSpec: ProbeSpec;
  ProbeResult: ProbeResult;
  Explanation: Explanation;
}
export interface SourceRef {
  path: Path;
  qualname: Qualname;
  line: Line;
  end_line: EndLine;
  digest: Digest;
  code: Code;
}
export interface ValueDescriptor {
  schema_version: SchemaVersion;
  kind: Kind;
  backend: Backend;
  type_name: TypeName;
  shape: Shape;
  dtype: Dtype;
  nbytes: Nbytes;
  device: Device;
  axes: Axes;
  unit: Unit;
  capabilities: Capabilities;
  metadata: Metadata;
}
export interface Metadata {
  [k: string]: JsonValue;
}
export interface SnapshotRef {
  id: Id;
  run_id: RunId;
  binding_id: BindingId;
  scope_id: ScopeId;
  name: Name;
  version: Version;
  descriptor: ValueDescriptor;
  observed_at: ObservedAt;
  source: SourceRef | null;
  operation_id: OperationId;
  parents: Parents;
  provenance: Provenance;
  fidelity: Fidelity;
  sample: Sample;
  statistics: Statistics;
  truncation: Truncation;
  redacted: Redacted;
  artifact_ref: ArtifactRef;
  coverage: Coverage;
}
export interface Sample {
  [k: string]: JsonValue;
}
export interface Statistics {
  [k: string]: JsonValue;
}
export interface Coverage {
  [k: string]: JsonValue;
}
export interface OperationRecord {
  id: Id1;
  run_id: RunId1;
  label: Label;
  source: SourceRef | null;
  scope_id: ScopeId1;
  iteration: Iteration;
  input_snapshots: InputSnapshots;
  output_snapshots: OutputSnapshots;
  kind: Kind1;
  status: Status;
  duration_ms: DurationMs;
  parameters: Parameters;
  provenance: Provenance1;
}
export interface Parameters {
  [k: string]: JsonValue;
}
export interface ObservationEvent {
  schema_version: SchemaVersion1;
  run_id: RunId2;
  sequence: Sequence;
  kind: Kind2;
  timestamp: Timestamp;
  source: SourceRef | null;
  operation_id: OperationId1;
  snapshot_id: SnapshotId;
  payload: Payload;
}
export interface Payload {
  [k: string]: JsonValue;
}
export interface ProbeSpec {
  id: Id2;
  kind: Kind3;
  binding: Binding;
  enabled: Enabled;
  parameters: Parameters1;
  policy: Policy;
  budget_ms: BudgetMs;
  protocol_version: ProtocolVersion;
}
export interface Parameters1 {
  [k: string]: JsonValue;
}
export interface ProbeResult {
  probe_id: ProbeId;
  snapshot_id: SnapshotId1;
  status: Status1;
  fidelity: Fidelity1;
  message: Message;
  evidence: Evidence;
  duration_ms: DurationMs1;
}
export interface Evidence {
  [k: string]: JsonValue;
}
export interface Explanation {
  operation_id: OperationId2;
  text: Text;
  origin: Origin;
  evidence: Evidence1;
  uncertainty: Uncertainty;
  usage: Usage;
  sent_scope: SentScope;
}
export interface Usage {
  [k: string]: JsonValue;
}
export interface SentScope {
  [k: string]: JsonValue;
}
