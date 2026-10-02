/* Generated from Python scientific workbench protocol v2; scripts/export_schema.py + npm run types. */

export type ProtocolVersion = 2 | 3;
export type Id = string;
export type Path = string;
export type SourceDigest = string;
export type Id1 = string;
export type Path1 = string;
export type Qualname = string;
export type Name = string;
export type Scope = string;
export type Kind = "function" | "class" | "assignment" | "parameter" | "import" | "step";
export type Line = number;
export type EndLine = number;
export type Column = number;
export type EndColumn = number;
export type LogicalKey = string;
export type BlockId = string;
export type SourceDigest1 = string;
export type Code = string;
export type Inputs = string[];
export type Mutation = boolean;
export type Provenance = "inferred" | "declared";
export type Objects = SourceObject[];
export type Source = string;
export type Target = string;
export type Label = string;
export type Provenance1 = "observed" | "inferred" | "declared" | "unknown";
export type Evidence = string[];
export type Relations = Relation[];
export type ProtocolVersion1 = 3;
export type SourceDigest2 = string;
export type Roots = string[];
export type Id2 = string;
export type LogicalKey1 = string;
export type Kind1 =
  "file" | "function" | "class" | "condition" | "loop" | "try" | "with" | "folder" | "project" | "stream";
export type Label1 = string;
export type ParentId = string | null;
export type Path2 = string;
export type Qualname1 = string;
export type Line1 = number;
export type EndLine1 = number;
export type Digest = string;
export type Code1 = string;
export type SourceObjectId = string | null;
export type Members = string[];
export type RuntimeCoverage = "supported" | "partial" | "unsupported";
export type Blocks = GraphBlock[];
export type Id3 = string;
export type Kind2 =
  | "operation"
  | "data"
  | "parameter"
  | "condition"
  | "loop_header"
  | "merge"
  | "return"
  | "call"
  | "entry"
  | "exit"
  | "unknown";
export type Label2 = string;
export type BlockId1 = string;
export type LogicalKey2 = string;
export type SourceObjectId1 = string | null;
export type Id4 = string;
export type Name1 = string;
export type Direction = "input" | "output";
export type Ports = GraphPort[];
export type Version = number;
export type Nodes = GraphNode[];
export type Id5 = string;
export type Source1 = string;
export type Target1 = string;
export type Kind3 = "data" | "control" | "call" | "argument" | "return" | "merge" | "backedge" | "contains" | "block";
export type Label3 = string;
export type SourcePort = string | null;
export type TargetPort = string | null;
export type Branch = ("true" | "false" | "body" | "exit" | "exception") | null;
export type Provenance2 = "inferred" | "declared" | "observed" | "unknown";
export type OriginalIds = string[];
export type Count = number;
export type Edges = GraphEdge[];
export type Code2 = string;
export type Message = string;
export type Runtime = "supported" | "partial" | "unsupported";
export type Coverage = GraphCoverage[];
export type OmittedCount = number;
export type Diagnostics = string[];
export type ImportedAt = string;
export type Id6 = string;
export type Label4 = string;
export type Capability = "view" | "check" | "interpret";
export type Execution = "builtin" | "program" | "model" | "skill" | "manual";
export type SupportedKinds = string[];
export type ToolId = string | null;
export type JsonValue = unknown;
export type Version1 = string;
export type Id7 = string;
export type DefinitionId = string;
export type Binding = string;
export type Enabled = boolean;
export type Policy = "continue" | "pause" | "cancel";
export type BudgetMs = number;
export type ProtocolVersion2 = 2;
export type Id8 = string;
export type InstanceId = string;
export type DefinitionId1 = string;
export type Capability1 = "view" | "check" | "interpret";
export type Execution1 = "builtin" | "program" | "model" | "skill" | "manual";
export type Status = "ready" | "pass" | "fail" | "error" | "skipped" | "unknown" | "cancelled";
export type RunId = string | null;
export type SnapshotId = string | null;
export type AnalysisId = string | null;
export type CreatedAt = string;
export type Fidelity = string;
export type Message1 = string;
export type ArtifactId = string | null;
export type CacheKey = string;
export type DurationMs = number;
export type Provenance3 = "observed" | "inferred" | "declared" | "manual" | "model" | "skill" | "unknown";
export type ProtocolVersion3 = 2;
export type Revision = number;
export type Script = string;
export type Interpreter = string;
/**
 * @maxItems 256
 */
export type Arguments = string[];
export type Capture = "metadata" | "summary" | "sample" | "full";
/**
 * @maxItems 128
 */
export type Probes = ProbeInstance[];
export type Adapters = string[];
export type Role = "parse" | "explain" | "probe" | "code";
export type ProviderId = string;
export type Model = string | null;
export type InputTokens = number;
export type OutputTokens = number;
export type MaxSteps = number;
export type MaxCalls = number;
export type IncludeSamples = boolean;
export type AllowExecute = boolean;
export type Harness = HarnessPolicy[];
export type MaxOutputs = number;
export type ProtocolVersion4 = 2;
export type Id9 = string;
export type CreatedAt1 = string;
export type AnalysisId1 = string;
export type SourceDigest3 = string;
export type ConfigDigest = string;
export type EnvironmentDigest = string;
export type Definitions = ProbeDefinition[];
export type Scope1 = "compute" | "probes" | "replot";
export type RunId1 = string | null;
export type SnapshotIds = string[];
export type Diagnostics1 = string[];
export type ProtocolVersion5 = 2;
export type Id10 = string;
export type Kind4 = string;
export type Status1 = "queued" | "running" | "completed" | "failed" | "cancelled" | "interrupted";
export type CreatedAt2 = string;
export type UpdatedAt = string;
export type PlanId = string | null;
export type RunId2 = string | null;
export type CalculationStatus = string;
export type Progress = number;
export type OutputIds = string[];
export type Message2 = string;
export type ProtocolVersion6 = 2;
export type Id11 = string;
export type AnalysisId2 = string;
export type ObjectId = string | null;
export type Path3 = string;
export type SourceDigest4 = string;
export type Candidate = string;
export type OriginalFragment = string | null;
export type Diff = string;
export type Diagnostics2 = string[];
export type Status2 = "proposed" | "valid" | "invalid" | "accepted" | "rejected" | "conflict";
export type Behavior = "unverified" | "verified";
export type AcceptedDigest = string | null;
export type ValidationRunId = string | null;
export type ValidationOutputIds = string[];
export type RollbackOf = string | null;
export type CreatedAt3 = string;
export type Kind5 = "data" | "operation" | "function" | "control" | "file" | "project" | "folder" | "stream";
export type LogicalKey3 = string;
export type ObjectId1 = string | null;
export type BlockId2 = string | null;
export type AnalysisId3 = string | null;
export type RunId3 = string | null;
export type SnapshotId1 = string | null;
export type Mode = "selection" | "block" | "project";
export type BlockId3 = string | null;
export type Targets = TargetRef[];
export type ExcludedKeys = string[];
export type Question = string;
export type AnalysisId4 = string;
export type ObjectId2 = string | null;
export type RunId4 = string | null;
export type SnapshotId2 = string | null;
export type SkillId = string | null;

export interface WorkbenchProtocol {
  AnalysisDocument: AnalysisDocument;
  SourceObject: SourceObject;
  Relation: Relation;
  ProbeDefinition: ProbeDefinition;
  ProbeInstance: ProbeInstance;
  ProbeOutput: ProbeOutput;
  WorkbenchConfig: WorkbenchConfig;
  ExecutionPlan: ExecutionPlan;
  TaskRecord: TaskRecord;
  HarnessPolicy: HarnessPolicy;
  CodeProposal: CodeProposal;
  SemanticGraph: SemanticGraph;
  TargetRef: TargetRef;
  ScopeSelector: ScopeSelector;
  HarnessRequest: HarnessRequest;
}
export interface AnalysisDocument {
  protocol_version: ProtocolVersion;
  id: Id;
  path: Path;
  source_digest: SourceDigest;
  objects: Objects;
  relations: Relations;
  graph: SemanticGraph;
  diagnostics: Diagnostics;
  imported_at: ImportedAt;
}
export interface SourceObject {
  id: Id1;
  path: Path1;
  qualname: Qualname;
  name: Name;
  scope: Scope;
  kind: Kind;
  line: Line;
  end_line: EndLine;
  column: Column;
  end_column: EndColumn;
  logical_key: LogicalKey;
  block_id: BlockId;
  source_digest: SourceDigest1;
  code: Code;
  inputs: Inputs;
  mutation: Mutation;
  provenance: Provenance;
}
export interface Relation {
  source: Source;
  target: Target;
  label: Label;
  provenance: Provenance1;
  evidence: Evidence;
}
export interface SemanticGraph {
  protocol_version: ProtocolVersion1;
  source_digest: SourceDigest2;
  roots: Roots;
  blocks: Blocks;
  nodes: Nodes;
  edges: Edges;
  coverage: Coverage;
  omitted_count: OmittedCount;
}
export interface GraphBlock {
  id: Id2;
  logical_key: LogicalKey1;
  kind: Kind1;
  label: Label1;
  parent_id: ParentId;
  source: SourceRef | null;
  source_object_id: SourceObjectId;
  members: Members;
  runtime_coverage: RuntimeCoverage;
}
export interface SourceRef {
  path: Path2;
  qualname: Qualname1;
  line: Line1;
  end_line: EndLine1;
  digest: Digest;
  code: Code1;
}
export interface GraphNode {
  id: Id3;
  kind: Kind2;
  label: Label2;
  block_id: BlockId1;
  logical_key: LogicalKey2;
  source: SourceRef | null;
  source_object_id: SourceObjectId1;
  ports: Ports;
  version: Version;
}
export interface GraphPort {
  id: Id4;
  name: Name1;
  direction: Direction;
}
export interface GraphEdge {
  id: Id5;
  source: Source1;
  target: Target1;
  kind: Kind3;
  label: Label3;
  source_port: SourcePort;
  target_port: TargetPort;
  branch: Branch;
  provenance: Provenance2;
  original_ids: OriginalIds;
  count: Count;
}
export interface GraphCoverage {
  code: Code2;
  message: Message;
  source: SourceRef | null;
  runtime: Runtime;
}
export interface ProbeDefinition {
  id: Id6;
  label: Label4;
  capability: Capability;
  execution: Execution;
  supported_kinds: SupportedKinds;
  tool_id: ToolId;
  parameter_schema: ParameterSchema;
  version: Version1;
}
export interface ParameterSchema {
  [k: string]: JsonValue;
}
export interface ProbeInstance {
  id: Id7;
  definition_id: DefinitionId;
  binding: Binding;
  enabled: Enabled;
  parameters: Parameters;
  policy: Policy;
  budget_ms: BudgetMs;
}
export interface Parameters {
  [k: string]: JsonValue;
}
export interface ProbeOutput {
  protocol_version: ProtocolVersion2;
  id: Id8;
  instance_id: InstanceId;
  definition_id: DefinitionId1;
  capability: Capability1;
  execution: Execution1;
  status: Status;
  run_id: RunId;
  snapshot_id: SnapshotId;
  analysis_id: AnalysisId;
  created_at: CreatedAt;
  fidelity: Fidelity;
  message: Message1;
  data: Data;
  artifact_id: ArtifactId;
  cache_key: CacheKey;
  duration_ms: DurationMs;
  provenance: Provenance3;
}
export interface Data {
  [k: string]: JsonValue;
}
export interface WorkbenchConfig {
  protocol_version: ProtocolVersion3;
  revision: Revision;
  script: Script;
  interpreter: Interpreter;
  arguments: Arguments;
  capture: Capture;
  probes: Probes;
  adapters: Adapters;
  harness: Harness;
  max_outputs: MaxOutputs;
}
export interface HarnessPolicy {
  role: Role;
  provider_id: ProviderId;
  model: Model;
  input_tokens: InputTokens;
  output_tokens: OutputTokens;
  max_steps: MaxSteps;
  max_calls: MaxCalls;
  include_samples: IncludeSamples;
  allow_execute: AllowExecute;
}
export interface ExecutionPlan {
  protocol_version: ProtocolVersion4;
  id: Id9;
  created_at: CreatedAt1;
  analysis_id: AnalysisId1;
  source_digest: SourceDigest3;
  config_digest: ConfigDigest;
  environment_digest: EnvironmentDigest;
  config: WorkbenchConfig;
  definitions: Definitions;
  scope: Scope1;
  run_id: RunId1;
  snapshot_ids: SnapshotIds;
  diagnostics: Diagnostics1;
}
export interface TaskRecord {
  protocol_version: ProtocolVersion5;
  id: Id10;
  kind: Kind4;
  status: Status1;
  created_at: CreatedAt2;
  updated_at: UpdatedAt;
  plan_id: PlanId;
  run_id: RunId2;
  calculation_status: CalculationStatus;
  progress: Progress;
  output_ids: OutputIds;
  message: Message2;
  receipt: Receipt;
}
export interface Receipt {
  [k: string]: JsonValue;
}
export interface CodeProposal {
  protocol_version: ProtocolVersion6;
  id: Id11;
  analysis_id: AnalysisId2;
  object_id: ObjectId;
  path: Path3;
  source_digest: SourceDigest4;
  candidate: Candidate;
  original_fragment: OriginalFragment;
  diff: Diff;
  diagnostics: Diagnostics2;
  status: Status2;
  behavior: Behavior;
  accepted_digest: AcceptedDigest;
  validation_run_id: ValidationRunId;
  validation_output_ids: ValidationOutputIds;
  rollback_of: RollbackOf;
  created_at: CreatedAt3;
}
export interface TargetRef {
  kind: Kind5;
  logical_key: LogicalKey3;
  object_id: ObjectId1;
  block_id: BlockId2;
  analysis_id: AnalysisId3;
  run_id: RunId3;
  snapshot_id: SnapshotId1;
}
export interface ScopeSelector {
  mode: Mode;
  block_id: BlockId3;
  targets: Targets;
  excluded_keys: ExcludedKeys;
}
export interface HarnessRequest {
  question: Question;
  analysis_id: AnalysisId4;
  object_id: ObjectId2;
  run_id: RunId4;
  snapshot_id: SnapshotId2;
  skill_id: SkillId;
  policy: HarnessPolicy;
}
