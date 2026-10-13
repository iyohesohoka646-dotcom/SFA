/* Generated from Python P4 project protocol; scripts/export_schema.py + npm run types. */

export type ProtocolVersion = 1;
export type Id = string;
export type Root = string;
export type Name = string;
export type LatestRevisionId = string | null;
export type SourceRoots = string[];
export type Include = string[];
export type Exclude = string[];
export type Id1 = string;
export type Name1 = string;
export type Kind = "script" | "module";
export type Target = string;
export type Cwd = string;
export type InterpreterRef = string;
/**
 * @maxItems 256
 */
export type Arguments = string[];
/**
 * @maxItems 128
 */
export type Environment = string[];
export type JsonValue = unknown;
export type RunConfigurations = RunConfiguration[];
export type ProtocolVersion1 = 1;
export type Id2 = string;
export type ProjectId = string;
export type ParentRevisionId = string | null;
export type CreatedAt = string;
export type FilesCount = number;
export type ParsedFiles = number;
export type ReusedFiles = number;
export type Diagnostics = string[];
export type Id3 = string;
export type RelativePath = string;
export type Digest = string;
export type AnalysisId = string;
export type ModuleNames = string[];
export type Status = "parsed" | "error";
export type Diagnostics1 = string[];
export type ProtocolVersion2 = 1;
export type Items = SourceUnit[];
export type Total = number;
export type Offset = number;
export type Limit = number;
export type ProjectId1 = string;
export type RevisionId = string;
export type ProtocolVersion3 = 1;
export type ProtocolVersion4 = 3;
export type SourceDigest = string;
export type Roots = string[];
export type Id4 = string;
export type LogicalKey = string;
export type Kind1 =
  "file" | "function" | "class" | "condition" | "loop" | "try" | "with" | "folder" | "project" | "stream";
export type Label = string;
export type ParentId = string | null;
export type Path = string;
export type Qualname = string;
export type Line = number;
export type EndLine = number;
export type Digest1 = string;
export type Code = string;
export type Column = number;
export type EndColumn = number;
export type ProjectId2 = string;
export type FileId = string;
export type ProjectRevisionId = string;
export type ScopeId = string;
export type SourceObjectId = string | null;
export type Members = string[];
export type RuntimeCoverage = "supported" | "partial" | "unsupported";
export type Blocks = GraphBlock[];
export type Id5 = string;
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
export type Label1 = string;
export type BlockId = string;
export type LogicalKey1 = string;
export type SourceObjectId1 = string | null;
export type Id6 = string;
export type Name2 = string;
export type Direction = "input" | "output";
export type Ports = GraphPort[];
export type Version = number;
export type Nodes = GraphNode[];
export type Id7 = string;
export type Source = string;
export type Target1 = string;
export type Kind3 = "data" | "control" | "call" | "argument" | "return" | "merge" | "backedge" | "contains" | "block";
export type Label2 = string;
export type SourcePort = string | null;
export type TargetPort = string | null;
export type Branch = ("true" | "false" | "body" | "exit" | "exception") | null;
export type Provenance = "inferred" | "declared" | "observed" | "unknown";
export type OriginalIds = string[];
export type Count = number;
export type Edges = GraphEdge[];
export type Code1 = string;
export type Message = string;
export type Runtime = "supported" | "partial" | "unsupported";
export type Coverage = GraphCoverage[];
export type OmittedCount = number;
export type ProjectId3 = string;
export type RevisionId1 = string;
export type ScopeId1 = string | null;
export type View = "code" | "data";
export type OmittedCount1 = number;
export type Path1 = string;
export type FileId1 = string;
export type Digest2 = string;
export type ProjectId4 = string;
export type ProjectRevisionId1 = string;
export type ModuleName = string;
export type State = "entered" | "completed" | "failed";
export type Coverage1 = "supported" | "unsupported" | "partial";
export type Count1 = number;
export type ProjectId5 = string;
export type ProjectRevisionId2 = string;
export type LoadedCount = number;
export type LoadedFiles = ProjectLoadedFile[];
export type OmittedFromSummary = number;
export type OmittedCount2 = number;
export type Complete = boolean;
export type Id8 = string;
export type Name3 = string;
export type SourceRoots1 = string[];
export type Include1 = string[];
export type Exclude1 = string[];
/**
 * @maxItems 64
 */
export type RunConfigurations1 = RunConfiguration[];
export type Id9 = string;
export type ParentId1 = string | null;
export type Kind4 = "project" | "folder" | "file";
export type Label3 = string;
export type Path2 = string;
export type FileId2 = string | null;
export type ChildCount = number;
export type Kind5 = "data" | "operation" | "function" | "control" | "file" | "project" | "folder" | "stream";
export type LogicalKey2 = string;
export type ObjectId = string | null;
export type BlockId1 = string | null;
export type AnalysisId1 = string | null;
export type RunId = string | null;
export type SnapshotId = string | null;
export type ProjectId6 = string | null;
export type FileId3 = string | null;
export type ProjectRevisionId3 = string | null;
export type ExactEvidence = boolean;
export type ProtocolVersion5 = 1;
export type ProjectId7 = string;
export type RevisionId2 = string;
export type Items1 = TreeItem[];
export type Total1 = number;
export type Offset1 = number;
export type Limit1 = number;
export type Name4 = string;
export type Kind6 = string;
export type Line1 = number;
export type EndLine1 = number;
export type Type = string | null;
export type Shape = number[] | null;
export type ProbeCount = number;
export type ProbeStatus = "normal" | "failed" | "unknown";
export type ProtocolVersion6 = 1;
export type ProjectId8 = string;
export type RevisionId3 = string;
export type Items2 = ObjectItem[];
export type Total2 = number;
export type Offset2 = number;
export type Limit2 = number;
export type Name5 = string;
export type Kind7 = string;
export type Scope = string;
export type Line2 = number;
export type EndLine2 = number;
export type LogicalKey3 = string;
export type ProtocolVersion7 = 1;
export type ProjectId9 = string;
export type RevisionId4 = string;
export type Items3 = SymbolRef[];
export type Total3 = number;
export type Offset3 = number;
export type Limit3 = number;
export type Kind8 = "call" | "import" | "argument" | "return" | "contains";
export type Name6 = string;
export type LogicalKey4 = string;
export type Provenance1 = "inferred" | "declared" | "observed" | "unknown";
export type TargetLine = number;
export type ProtocolVersion8 = 1;
export type ProjectId10 = string;
export type RevisionId5 = string;
export type Items4 = ReferenceItem[];
export type Total4 = number;
export type Offset4 = number;
export type Limit4 = number;
export type Kind9 = string;
export type Status1 = "pass" | "fail" | "not_run" | "not_validated";
export type Detail = string;
export type ProtocolVersion9 = 1;
export type Path3 = string;
export type BeforeDigest = string;
export type AfterDigest = string;
export type BeforeExists = boolean;
export type Operation = "modify" | "create" | "format";
export type Content = string;
export type Diff = string;
export type Diagnostics2 = string[];
export type ProtocolVersion10 = 1;
export type Id10 = string;
export type ProjectId11 = string;
export type BaseRevision = string;
export type Status2 = "ready" | "invalid" | "accepted" | "rejected" | "conflict" | "recovery_required";
export type Files = ProjectFileEdit[];
export type Validation = ChangeValidation[];
export type AffectedReferences = string[];
export type CreatedAt1 = string;
export type AcceptedRevision = string | null;
export type RollbackOf = string | null;
export type Path4 = string;
export type Content1 = string;
export type Operation1 = "modify" | "create" | "format";
export type BaseRevision1 = string;
export type Edits = ProjectChangeEditRequest[];
export type ExpectedRevision = string;
export type ProtocolVersion11 = 1;
export type ProjectId12 = string;
export type RevisionId6 = string;
export type Items5 = ProjectChangeSet[];
export type RecoveryRequired = boolean;
export type ProtocolVersion12 = 1;
export type ProjectId13 = string;
export type RevisionId7 = string;
export type Required = boolean;
export type ChangeId = string | null;
export type Question = string;
export type AnalysisId2 = string;
export type ObjectId1 = string | null;
export type SourceObjectIds = string[] | null;
export type RunId1 = string | null;
export type SnapshotId1 = string | null;
export type SkillId = string | null;
export type Role = "parse" | "explain" | "probe" | "code";
export type ProviderId = string;
export type Model = string | null;
export type InputTokens = number;
export type OutputTokens = number;
export type MaxSteps = number;
export type MaxCalls = number;
export type IncludeSamples = boolean;
export type AllowExecute = boolean;
export type Purpose = "general" | "format_source";
export type ProjectId14 = string;
export type ProjectRevisionId4 = string;
export type EntryId = string | null;
export type ScopeId2 = string | null;
export type FileIds = string[] | null;
export type Mode = "selection" | "block" | "project";
export type BlockId2 = string | null;
export type Targets = TargetRef[];
export type ExcludedKeys = string[];
export type ProjectId15 = string;
export type ProjectRevisionId5 = string;
export type Messages = {
  [k: string]: unknown;
}[];
export type TokenBound = number;
export type Tools = {
  [k: string]: unknown;
}[];
export type FileId4 = string;
export type Path5 = string;
export type Kind10 = string;
export type ProjectId16 = string;
export type ProjectRevisionId6 = string;
export type FilesTotal = number;
export type Inventory = ProjectFileInventoryItem[];
export type InventoryTotal = number;
export type InventoryTruncated = boolean;
export type ScopeMode = string;
export type ScopeId3 = string | null;
export type FileId5 = string;
export type Path6 = string;
export type Digest3 = string;
export type WholeFile = boolean;
export type Ranges = number[][];
export type Permissions = ProjectReadPermission[];
export type PermissionSummary = string;
export type Tools1 = string[];
export type Skills = string[];
export type Role1 = string;
export type SamplesAllowed = boolean;
export type Omitted = string[];
export type Reference = string;
export type Tool = string;
export type ProjectId17 = string;
export type ProjectRevisionId7 = string;
export type Coverage3 = string;
export type Target2 = string;
export type Reference1 = string;
export type SnapshotId2 = string;
export type ProjectId18 = string;
export type ProjectRevisionId8 = string;
export type Version1 = number;
export type Fidelity = "exact" | "sampled" | "metadata_only";
export type Redacted = boolean;
export type Revision = number;
export type Id11 = string;
export type Interpreters = InterpreterReference[];
export type Id12 = string;
export type Keys = string[];
export type Environments = EnvironmentReference[];
export type LegacyEnvironment = string[];
export type ExpectedRevision1 = number;
export type Path7 = string;
export type ExpectedRevision2 = number;

export interface ProjectProtocol {
  ResearchProject: ResearchProject;
  ProjectRevision: ProjectRevision;
  SourceUnit: SourceUnit;
  FilePage: FilePage;
  ProjectGraphSlice: ProjectGraphSlice;
  ProjectLoadedFile: ProjectLoadedFile;
  ProjectExecutionReceipt: ProjectExecutionReceipt;
  RunConfiguration: RunConfiguration;
  ProjectSection: ProjectSection;
  TreeItem: TreeItem;
  TreePage: TreePage;
  ObjectItem: ObjectItem;
  ObjectPage: ObjectPage;
  SymbolRef: SymbolRef;
  SymbolPage: SymbolPage;
  ReferenceItem: ReferenceItem;
  ReferencePage: ReferencePage;
  ChangeValidation: ChangeValidation;
  ProjectFileEdit: ProjectFileEdit;
  ProjectChangeSet: ProjectChangeSet;
  ProjectChangeEditRequest: ProjectChangeEditRequest;
  ProjectChangeProposalRequest: ProjectChangeProposalRequest;
  ProjectChangeActionRequest: ProjectChangeActionRequest;
  ProjectChangePage: ProjectChangePage;
  ProjectRecoveryState: ProjectRecoveryState;
  ProjectAIRequest: ProjectAIRequest;
  ProjectContextPreview: ProjectContextPreview;
  ProjectFileInventoryItem: ProjectFileInventoryItem;
  ProjectContextManifest: ProjectContextManifest;
  ProjectReadPermission: ProjectReadPermission;
  ProjectToolReceipt: ProjectToolReceipt;
  ProjectEvidenceReceipt: ProjectEvidenceReceipt;
  RuntimeReferenceState: RuntimeReferenceState;
  InterpreterReferenceRequest: InterpreterReferenceRequest;
  EnvironmentReferenceRequest: EnvironmentReferenceRequest;
  SourceRef: SourceRef;
  TargetRef: TargetRef;
}
export interface ResearchProject {
  protocol_version: ProtocolVersion;
  id: Id;
  root: Root;
  name: Name;
  latest_revision_id: LatestRevisionId;
  source_roots: SourceRoots;
  include: Include;
  exclude: Exclude;
  run_configurations: RunConfigurations;
}
/**
 * Authored, inert launch intent reused by P2/P3 (never executed here).
 */
export interface RunConfiguration {
  id: Id1;
  name: Name1;
  kind: Kind;
  target: Target;
  cwd: Cwd;
  interpreter_ref: InterpreterRef;
  arguments: Arguments;
  environment: Environment;
  options: Options;
}
export interface Options {
  [k: string]: JsonValue;
}
export interface ProjectRevision {
  protocol_version: ProtocolVersion1;
  id: Id2;
  project_id: ProjectId;
  parent_revision_id: ParentRevisionId;
  created_at: CreatedAt;
  files_count: FilesCount;
  parsed_files: ParsedFiles;
  reused_files: ReusedFiles;
  diagnostics: Diagnostics;
}
export interface SourceUnit {
  id: Id3;
  relative_path: RelativePath;
  digest: Digest;
  analysis_id: AnalysisId;
  module_names: ModuleNames;
  status: Status;
  diagnostics: Diagnostics1;
}
export interface FilePage {
  protocol_version: ProtocolVersion2;
  items: Items;
  total: Total;
  offset: Offset;
  limit: Limit;
  project_id: ProjectId1;
  revision_id: RevisionId;
}
export interface ProjectGraphSlice {
  protocol_version: ProtocolVersion3;
  graph: SemanticGraph;
  project_id: ProjectId3;
  revision_id: RevisionId1;
  scope_id: ScopeId1;
  view: View;
  omitted_count: OmittedCount1;
}
export interface SemanticGraph {
  protocol_version: ProtocolVersion4;
  source_digest: SourceDigest;
  roots: Roots;
  blocks: Blocks;
  nodes: Nodes;
  edges: Edges;
  coverage: Coverage;
  omitted_count: OmittedCount;
}
export interface GraphBlock {
  id: Id4;
  logical_key: LogicalKey;
  kind: Kind1;
  label: Label;
  parent_id: ParentId;
  source: SourceRef | null;
  source_object_id: SourceObjectId;
  members: Members;
  runtime_coverage: RuntimeCoverage;
}
export interface SourceRef {
  path: Path;
  qualname: Qualname;
  line: Line;
  end_line: EndLine;
  digest: Digest1;
  code: Code;
  column: Column;
  end_column: EndColumn;
  project_id: ProjectId2;
  file_id: FileId;
  project_revision_id: ProjectRevisionId;
  scope_id: ScopeId;
}
export interface GraphNode {
  id: Id5;
  kind: Kind2;
  label: Label1;
  block_id: BlockId;
  logical_key: LogicalKey1;
  source: SourceRef | null;
  source_object_id: SourceObjectId1;
  ports: Ports;
  version: Version;
}
export interface GraphPort {
  id: Id6;
  name: Name2;
  direction: Direction;
}
export interface GraphEdge {
  id: Id7;
  source: Source;
  target: Target1;
  kind: Kind3;
  label: Label2;
  source_port: SourcePort;
  target_port: TargetPort;
  branch: Branch;
  provenance: Provenance;
  original_ids: OriginalIds;
  count: Count;
}
export interface GraphCoverage {
  code: Code1;
  message: Message;
  source: SourceRef | null;
  runtime: Runtime;
}
/**
 * One file the interpreter actually entered during a project run.
 *
 * Paths are root-relative and sanitized; no machine path or source body is
 * ever carried. ``file_id`` is empty for an in-root file outside the frozen
 * manifest, which keeps a coverage gap explicit instead of implying membership.
 */
export interface ProjectLoadedFile {
  path: Path1;
  file_id: FileId1;
  digest: Digest2;
  project_id: ProjectId4;
  project_revision_id: ProjectRevisionId1;
  module_name: ModuleName;
  state: State;
  coverage: Coverage1;
  count: Count1;
}
/**
 * Durable loaded-file receipt attached to a project run finish payload.
 *
 * ``complete`` means the load ledger was finalized and flushed, independent of
 * whether the user's calculation succeeded; any budget omission makes it false.
 */
export interface ProjectExecutionReceipt {
  project_id: ProjectId5;
  project_revision_id: ProjectRevisionId2;
  loaded_count: LoadedCount;
  loaded_files: LoadedFiles;
  omitted_from_summary: OmittedFromSummary;
  omitted_count: OmittedCount2;
  complete: Complete;
  coverage: Coverage2;
}
export interface Coverage2 {
  [k: string]: JsonValue;
}
/**
 * Persistent project identity; authored beside (never inside) observations.
 */
export interface ProjectSection {
  id: Id8;
  name: Name3;
  source_roots: SourceRoots1;
  include: Include1;
  exclude: Exclude1;
  run_configurations: RunConfigurations1;
}
export interface TreeItem {
  id: Id9;
  parent_id: ParentId1;
  kind: Kind4;
  label: Label3;
  path: Path2;
  file_id: FileId2;
  child_count: ChildCount;
  target: TargetRef | null;
}
export interface TargetRef {
  kind: Kind5;
  logical_key: LogicalKey2;
  object_id: ObjectId;
  block_id: BlockId1;
  analysis_id: AnalysisId1;
  run_id: RunId;
  snapshot_id: SnapshotId;
  project_id: ProjectId6;
  file_id: FileId3;
  project_revision_id: ProjectRevisionId3;
  exact_evidence: ExactEvidence;
}
export interface TreePage {
  protocol_version: ProtocolVersion5;
  project_id: ProjectId7;
  revision_id: RevisionId2;
  items: Items1;
  total: Total1;
  offset: Offset1;
  limit: Limit1;
}
export interface ObjectItem {
  target: TargetRef;
  name: Name4;
  kind: Kind6;
  line: Line1;
  end_line: EndLine1;
  type: Type;
  shape: Shape;
  probe_count: ProbeCount;
  probe_status: ProbeStatus;
  source: SourceRef;
}
export interface ObjectPage {
  protocol_version: ProtocolVersion6;
  project_id: ProjectId8;
  revision_id: RevisionId3;
  items: Items2;
  total: Total2;
  offset: Offset2;
  limit: Limit2;
}
export interface SymbolRef {
  name: Name5;
  kind: Kind7;
  scope: Scope;
  line: Line2;
  end_line: EndLine2;
  logical_key: LogicalKey3;
  source: SourceRef;
}
export interface SymbolPage {
  protocol_version: ProtocolVersion7;
  project_id: ProjectId9;
  revision_id: RevisionId4;
  items: Items3;
  total: Total3;
  offset: Offset3;
  limit: Limit3;
}
export interface ReferenceItem {
  kind: Kind8;
  name: Name6;
  logical_key: LogicalKey4;
  provenance: Provenance1;
  source: SourceRef;
  target: SourceRef | null;
  target_line: TargetLine;
}
export interface ReferencePage {
  protocol_version: ProtocolVersion8;
  project_id: ProjectId10;
  revision_id: RevisionId5;
  items: Items4;
  total: Total4;
  offset: Offset4;
  limit: Limit4;
}
export interface ChangeValidation {
  kind: Kind9;
  status: Status1;
  detail: Detail;
}
export interface ProjectFileEdit {
  protocol_version: ProtocolVersion9;
  path: Path3;
  before_digest: BeforeDigest;
  after_digest: AfterDigest;
  before_exists: BeforeExists;
  operation: Operation;
  content: Content;
  diff: Diff;
  diagnostics: Diagnostics2;
}
export interface ProjectChangeSet {
  protocol_version: ProtocolVersion10;
  id: Id10;
  project_id: ProjectId11;
  base_revision: BaseRevision;
  status: Status2;
  files: Files;
  validation: Validation;
  affected_references: AffectedReferences;
  created_at: CreatedAt1;
  accepted_revision: AcceptedRevision;
  rollback_of: RollbackOf;
}
/**
 * One requested file edit inside a reviewed proposal; content stays inert.
 */
export interface ProjectChangeEditRequest {
  path: Path4;
  content: Content1;
  operation: Operation1;
}
/**
 * POST body for creating a reviewed proposal.
 *
 * Per-file/per-set budgets (32 files, 1 MiB total) stay enforced by the change
 * engine, never by the wire model, so the same limits apply to calls that skip
 * the HTTP layer.
 */
export interface ProjectChangeProposalRequest {
  base_revision: BaseRevision1;
  edits: Edits;
}
/**
 * Review action body: the caller's expected latest project revision.
 */
export interface ProjectChangeActionRequest {
  expected_revision: ExpectedRevision;
}
/**
 * GET /{pid}/changes: the sanitized reviewed-proposal page.
 */
export interface ProjectChangePage {
  protocol_version: ProtocolVersion11;
  project_id: ProjectId12;
  revision_id: RevisionId6;
  items: Items5;
  recovery_required: RecoveryRequired;
}
/**
 * GET /{pid}/changes/recovery: a public recovery summary, no private data.
 */
export interface ProjectRecoveryState {
  protocol_version: ProtocolVersion12;
  project_id: ProjectId13;
  revision_id: RevisionId7;
  required: Required;
  change_id: ChangeId;
}
/**
 * One task-scoped project question bound to an immutable revision.
 *
 * ``analysis_id`` stays for shared-harness compatibility but is unused by
 * project work and defaults to the empty string.
 */
export interface ProjectAIRequest {
  question: Question;
  analysis_id: AnalysisId2;
  object_id: ObjectId1;
  source_object_ids: SourceObjectIds;
  run_id: RunId1;
  snapshot_id: SnapshotId1;
  skill_id: SkillId;
  policy: HarnessPolicy;
  purpose: Purpose;
  project_id: ProjectId14;
  project_revision_id: ProjectRevisionId4;
  entry_id: EntryId;
  scope_id: ScopeId2;
  file_ids: FileIds;
  scope: ScopeSelector | null;
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
export interface ScopeSelector {
  mode: Mode;
  block_id: BlockId2;
  targets: Targets;
  excluded_keys: ExcludedKeys;
}
/**
 * Typed, inert preview of the bounded initial context for one request.
 *
 * It carries only the frozen project/revision identity, the assembled chat
 * messages, a conservative token bound and the json tool descriptors. Building
 * it never contacts a model profile, sends inference or persists a task, and
 * the inventory is bounded to relative names and kinds (no source bodies).
 */
export interface ProjectContextPreview {
  project_id: ProjectId15;
  project_revision_id: ProjectRevisionId5;
  messages: Messages;
  token_bound: TokenBound;
  tools: Tools;
}
/**
 * A bounded, source-free inventory entry (relative name + kind only).
 */
export interface ProjectFileInventoryItem {
  file_id: FileId4;
  path: Path5;
  kind: Kind10;
}
/**
 * The typed, sanitized initial-context manifest assembled for one request.
 */
export interface ProjectContextManifest {
  project_id: ProjectId16;
  project_revision_id: ProjectRevisionId6;
  files_total: FilesTotal;
  inventory: Inventory;
  inventory_total: InventoryTotal;
  inventory_truncated: InventoryTruncated;
  entry: Entry;
  scope_mode: ScopeMode;
  scope_id: ScopeId3;
  permissions: Permissions;
  permission_summary: PermissionSummary;
  tools: Tools1;
  skills: Skills;
  role: Role1;
  samples_allowed: SamplesAllowed;
  omitted: Omitted;
}
export interface Entry {
  [k: string]: unknown;
}
/**
 * Permission summary: which indexed files, and which line spans, are readable.
 */
export interface ProjectReadPermission {
  file_id: FileId5;
  path: Path6;
  digest: Digest3;
  whole_file: WholeFile;
  ranges: Ranges;
}
/**
 * A versioned tool receipt: the only token a model may cite.
 */
export interface ProjectToolReceipt {
  reference: Reference;
  tool: Tool;
  project_id: ProjectId17;
  project_revision_id: ProjectRevisionId7;
  coverage: Coverage3;
  target: Target2;
}
/**
 * An evidence receipt for a sanitized snapshot observation.
 */
export interface ProjectEvidenceReceipt {
  reference: Reference1;
  snapshot_id: SnapshotId2;
  project_id: ProjectId18;
  project_revision_id: ProjectRevisionId8;
  version: Version1;
  fidelity: Fidelity;
  redacted: Redacted;
}
/**
 * Fresh, sanitized machine runtime state (never carries private values).
 */
export interface RuntimeReferenceState {
  revision: Revision;
  interpreters: Interpreters;
  environments: Environments;
  legacy_environment: LegacyEnvironment;
}
export interface InterpreterReference {
  id: Id11;
}
export interface EnvironmentReference {
  id: Id12;
  keys: Keys;
}
export interface InterpreterReferenceRequest {
  expected_revision: ExpectedRevision1;
  path: Path7;
}
export interface EnvironmentReferenceRequest {
  expected_revision: ExpectedRevision2;
  values: Values;
}
export interface Values {
  [k: string]: string;
}
