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
export type Column1 = number;
export type EndColumn1 = number;
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
export type Capability = "view" | "check" | "interpret" | "derive";
export type Execution = "builtin" | "program" | "model" | "skill" | "manual";
export type SupportedKinds = string[];
export type ToolId = string | null;
export type JsonValue = unknown;
export type Version1 = string;
export type SupportedTargets = (
  "data" | "operation" | "function" | "control" | "file" | "project" | "folder" | "stream"
)[];
export type InputMode = "single" | "per_target" | "joint";
export type Name2 = string;
export type Required = boolean;
export type SupportedKinds1 = string[];
export type SupportedTargets1 = (
  "data" | "operation" | "function" | "control" | "file" | "project" | "folder" | "stream"
)[];
export type InputRoles = InputRole[];
export type Evidence1 = "metadata" | "sample" | "full" | "full_coordinates";
export type OutputKinds = string[];
export type Renderer = ("auto" | "matrix" | "table" | "scalar" | "raw" | "relationships" | "compare") | null;
export type ResourceId = string | null;
export type ResourceVersion = string | null;
export type Dependencies = string[];
export type Entrypoint = string | null;
export type ImplementationDigest = string | null;
export type Examples = {
  [k: string]: JsonValue;
}[];
export type Id7 = string;
export type DefinitionId = string;
export type Binding = string;
export type Enabled = boolean;
export type Policy = "continue" | "pause" | "cancel";
export type BudgetMs = number;
export type Mode = "selection" | "block" | "project";
export type BlockId2 = string | null;
export type Kind4 = "data" | "operation" | "function" | "control" | "file" | "project" | "folder" | "stream";
export type LogicalKey3 = string;
export type ObjectId = string | null;
export type BlockId3 = string | null;
export type AnalysisId = string | null;
export type RunId = string | null;
export type SnapshotId = string | null;
export type Targets = TargetRef[];
export type ExcludedKeys = string[];
export type Origin = "project_default" | "local" | "manual";
export type Enabled1 = boolean | null;
export type ProtocolVersion2 = 2 | 3;
export type Id8 = string;
export type InstanceId = string;
export type DefinitionId1 = string;
export type Capability1 = "view" | "check" | "interpret" | "derive";
export type Execution1 = "builtin" | "program" | "model" | "skill" | "manual";
export type Status = "ready" | "pass" | "fail" | "error" | "skipped" | "unknown" | "cancelled";
export type RunId1 = string | null;
export type SnapshotId1 = string | null;
export type AnalysisId1 = string | null;
export type CreatedAt = string;
export type Fidelity = string;
export type Message1 = string;
export type ArtifactId = string | null;
export type CacheKey = string;
export type DurationMs = number;
export type Provenance3 = "observed" | "inferred" | "declared" | "manual" | "model" | "skill" | "unknown";
export type InvocationId = string | null;
export type Targets1 = TargetRef[];
export type ParentSnapshotIds = string[];
export type ProtocolVersion3 = 2 | 3;
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
export type ProtocolVersion4 = 2 | 3;
export type Id9 = string;
export type CreatedAt1 = string;
export type AnalysisId2 = string;
export type SourceDigest3 = string;
export type ConfigDigest = string;
export type EnvironmentDigest = string;
export type Definitions = ProbeDefinition[];
export type Scope1 = "compute" | "probes" | "replot";
export type RunId2 = string | null;
export type SnapshotIds = string[];
export type Diagnostics1 = string[];
export type ResolvedTargets = TargetRef[];
export type Id10 = string;
export type Targets2 = TargetRef[];
export type InputDigest = string;
export type Invocations = ResolvedProbeCall[];
export type ProtocolVersion5 = 2;
export type Id11 = string;
export type Kind5 = string;
export type Status1 = "queued" | "running" | "completed" | "failed" | "cancelled" | "interrupted";
export type CreatedAt2 = string;
export type UpdatedAt = string;
export type PlanId = string | null;
export type RunId3 = string | null;
export type CalculationStatus = string;
export type Progress = number;
export type OutputIds = string[];
export type Message2 = string;
export type ProtocolVersion6 = 2;
export type Id12 = string;
export type AnalysisId3 = string;
export type ObjectId1 = string | null;
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
export type NodeId = string;
export type Kind6 = "branch" | "loop" | "function";
export type TrueCount = number;
export type FalseCount = number;
export type BodyEntries = number;
export type Activations = number;
export type NaturalExits = number;
export type BreakExits = number;
export type NonlocalExits = number;
export type ExceptionExits = number;
export type Complete = boolean;
export type Revision1 = number;
/**
 * @maxItems 16
 */
export type ActivationSamples =
  | []
  | [
      {
        [k: string]: JsonValue;
      }
    ]
  | [
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      }
    ]
  | [
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      }
    ]
  | [
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      }
    ]
  | [
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      }
    ]
  | [
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      }
    ]
  | [
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      }
    ]
  | [
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      }
    ]
  | [
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      }
    ]
  | [
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      }
    ]
  | [
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      }
    ]
  | [
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      }
    ]
  | [
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      }
    ]
  | [
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      }
    ]
  | [
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      }
    ]
  | [
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      },
      {
        [k: string]: JsonValue;
      }
    ];
export type OmittedActivations = number;
export type TotalMs = number;
export type MinimumMs = number;
export type MaximumMs = number;
export type Timing = string;
export type Id13 = string;
export type Label5 = string;
export type Version2 = string;
export type Source2 = "builtin" | "public" | "local" | "model" | "skill";
export type Kind7 = "definition" | "adapter" | "skill";
export type Status3 = "available" | "installed" | "draft" | "disabled" | "error";
/**
 * @maxItems 128
 */
export type Definitions1 = ProbeDefinition[];
/**
 * @maxItems 128
 */
export type Dependencies1 = string[];
export type Url = string | null;
export type Diagnostics3 = string[];
export type PendingVersion = string | null;
export type ProtocolVersion7 = 3;
export type Id14 = string;
export type SnapshotId2 = string;
export type RunId4 = string;
export type InvocationId1 = string;
export type Operator = string;
export type Parents = TargetRef[];
export type Retained = boolean;
export type CreatedAt4 = string;
export type ProtocolVersion8 = 3;
export type LogicalKey4 = string;
export type Kind8 = "matrix" | "table" | "series" | "scatter" | "points" | "graph" | "generic";
export type Label6 = string;
export type Meaning = string;
export type Unit = string;
/**
 * @maxItems 100000
 */
export type Coordinates = JsonValue[];
/**
 * @maxItems 100000
 */
export type Labels = string[];
export type Origin1 = "program" | "user" | "model";
/**
 * @maxItems 32
 */
export type Axes = AxisSemantics[];
export type Key = string;
export type Label7 = string;
export type Meaning1 = string;
export type Unit1 = string;
export type Format = string;
export type Missing = string;
export type Origin2 = "program" | "user" | "model";
/**
 * @maxItems 4096
 */
export type Columns = ColumnSemantics[];
export type ElementMeaning = string;
export type Unit2 = string;
export type Origin3 = "program" | "user" | "model";
export type Revision2 = number;
export type Accepted = boolean;
export type Precision = number;
export type ShowValues = boolean;
export type ShowCoordinates = boolean;
export type Palette = "diverging" | "sequential" | "gray";
export type Scale = "linear" | "log" | "symmetric";
export type RowLabels = string[];
export type ColumnLabels = string[];
export type Question = string;
export type AnalysisId4 = string;
export type ObjectId2 = string | null;
export type SourceObjectIds = string[] | null;
export type RunId5 = string | null;
export type SnapshotId3 = string | null;
export type SkillId = string | null;
export type Id15 = string;
export type Profile = string;
export type Cwd = string;
export type Status4 = string;
export type Pid = number | null;
export type Rows = number;
export type Cols = number;
export type Error = string | null;

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
  ControlSummary: ControlSummary;
  ProbeResource: ProbeResource;
  ResolvedProbeCall: ResolvedProbeCall;
  DerivedData: DerivedData;
  DataSemantics: DataSemantics;
  PresentationSpec: PresentationSpec;
  HarnessRequest: HarnessRequest;
  TerminalSession: TerminalSession;
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
  column: Column1;
  end_column: EndColumn1;
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
  supported_targets: SupportedTargets;
  input_mode: InputMode;
  input_roles: InputRoles;
  evidence: Evidence1;
  output_kinds: OutputKinds;
  renderer: Renderer;
  resource_id: ResourceId;
  resource_version: ResourceVersion;
  dependencies: Dependencies;
  entrypoint: Entrypoint;
  implementation_digest: ImplementationDigest;
  examples: Examples;
}
export interface ParameterSchema {
  [k: string]: JsonValue;
}
export interface InputRole {
  name: Name2;
  required: Required;
  supported_kinds: SupportedKinds1;
  supported_targets: SupportedTargets1;
}
export interface ProbeInstance {
  id: Id7;
  definition_id: DefinitionId;
  binding: Binding;
  enabled: Enabled;
  parameters: Parameters;
  policy: Policy;
  budget_ms: BudgetMs;
  selector: ScopeSelector | null;
  inputs: Inputs1;
  origin: Origin;
  overrides: Overrides;
}
export interface Parameters {
  [k: string]: JsonValue;
}
export interface ScopeSelector {
  mode: Mode;
  block_id: BlockId2;
  targets: Targets;
  excluded_keys: ExcludedKeys;
}
export interface TargetRef {
  kind: Kind4;
  logical_key: LogicalKey3;
  object_id: ObjectId;
  block_id: BlockId3;
  analysis_id: AnalysisId;
  run_id: RunId;
  snapshot_id: SnapshotId;
}
export interface Inputs1 {
  [k: string]: TargetRef;
}
export interface Overrides {
  [k: string]: TargetOverride;
}
export interface TargetOverride {
  enabled: Enabled1;
  parameters: Parameters1;
}
export interface Parameters1 {
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
  run_id: RunId1;
  snapshot_id: SnapshotId1;
  analysis_id: AnalysisId1;
  created_at: CreatedAt;
  fidelity: Fidelity;
  message: Message1;
  data: Data;
  artifact_id: ArtifactId;
  cache_key: CacheKey;
  duration_ms: DurationMs;
  provenance: Provenance3;
  invocation_id: InvocationId;
  targets: Targets1;
  parent_snapshot_ids: ParentSnapshotIds;
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
  analysis_id: AnalysisId2;
  source_digest: SourceDigest3;
  config_digest: ConfigDigest;
  environment_digest: EnvironmentDigest;
  config: WorkbenchConfig;
  definitions: Definitions;
  scope: Scope1;
  run_id: RunId2;
  snapshot_ids: SnapshotIds;
  diagnostics: Diagnostics1;
  target_scope: ScopeSelector;
  resolved_targets: ResolvedTargets;
  invocations: Invocations;
  preferences: Preferences;
}
export interface ResolvedProbeCall {
  semantics: Semantics;
  id: Id10;
  definition: ProbeDefinition;
  instance: ProbeInstance;
  targets: Targets2;
  inputs: Inputs2;
  resource_versions: ResourceVersions;
  input_digest: InputDigest;
}
export interface Semantics {
  [k: string]: JsonValue;
}
export interface Inputs2 {
  [k: string]: TargetRef;
}
export interface ResourceVersions {
  [k: string]: string;
}
export interface Preferences {
  [k: string]: JsonValue;
}
export interface TaskRecord {
  protocol_version: ProtocolVersion5;
  id: Id11;
  kind: Kind5;
  status: Status1;
  created_at: CreatedAt2;
  updated_at: UpdatedAt;
  plan_id: PlanId;
  run_id: RunId3;
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
  id: Id12;
  analysis_id: AnalysisId3;
  object_id: ObjectId1;
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
export interface ControlSummary {
  node_id: NodeId;
  kind: Kind6;
  source: SourceRef | null;
  true_count: TrueCount;
  false_count: FalseCount;
  body_entries: BodyEntries;
  activations: Activations;
  natural_exits: NaturalExits;
  break_exits: BreakExits;
  nonlocal_exits: NonlocalExits;
  exception_exits: ExceptionExits;
  complete: Complete;
  revision: Revision1;
  activation_samples: ActivationSamples;
  omitted_activations: OmittedActivations;
  total_ms: TotalMs;
  minimum_ms: MinimumMs;
  maximum_ms: MaximumMs;
  timing: Timing;
}
export interface ProbeResource {
  id: Id13;
  label: Label5;
  version: Version2;
  source: Source2;
  kind: Kind7;
  status: Status3;
  definitions: Definitions1;
  dependencies: Dependencies1;
  url: Url;
  diagnostics: Diagnostics3;
  pending_version: PendingVersion;
}
export interface DerivedData {
  protocol_version: ProtocolVersion7;
  id: Id14;
  snapshot_id: SnapshotId2;
  run_id: RunId4;
  invocation_id: InvocationId1;
  operator: Operator;
  parents: Parents;
  inputs: Inputs3;
  parameters: Parameters2;
  input_digests: InputDigests;
  retained: Retained;
  created_at: CreatedAt4;
}
export interface Inputs3 {
  [k: string]: TargetRef;
}
export interface Parameters2 {
  [k: string]: JsonValue;
}
export interface InputDigests {
  [k: string]: string;
}
export interface DataSemantics {
  protocol_version: ProtocolVersion8;
  logical_key: LogicalKey4;
  kind: Kind8;
  axes: Axes;
  columns: Columns;
  element_meaning: ElementMeaning;
  unit: Unit2;
  mappings: Mappings;
  origin: Origin3;
  revision: Revision2;
  accepted: Accepted;
}
export interface AxisSemantics {
  label: Label6;
  meaning: Meaning;
  unit: Unit;
  coordinates: Coordinates;
  labels: Labels;
  origin: Origin1;
}
export interface ColumnSemantics {
  key: Key;
  label: Label7;
  meaning: Meaning1;
  unit: Unit1;
  format: Format;
  missing: Missing;
  origin: Origin2;
}
export interface Mappings {
  [k: string]: JsonValue;
}
export interface PresentationSpec {
  precision: Precision;
  show_values: ShowValues;
  show_coordinates: ShowCoordinates;
  palette: Palette;
  scale: Scale;
  row_labels: RowLabels;
  column_labels: ColumnLabels;
  semantics: DataSemantics | null;
}
export interface HarnessRequest {
  question: Question;
  analysis_id: AnalysisId4;
  object_id: ObjectId2;
  source_object_ids: SourceObjectIds;
  run_id: RunId5;
  snapshot_id: SnapshotId3;
  skill_id: SkillId;
  policy: HarnessPolicy;
}
export interface TerminalSession {
  id: Id15;
  profile: Profile;
  cwd: Cwd;
  status: Status4;
  pid: Pid;
  rows: Rows;
  cols: Cols;
  error: Error;
}
