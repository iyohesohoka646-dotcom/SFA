/* Generated from Python ProjectSpec. Run scripts/export_schema.py; npm run types. */

export type SchemaVersion = 1;
export type Name = string;
export type Id = string;
export type Name1 = string;
export type Description = string;
export type Kind = "python" | "composite" | "decision";
export type Path = string;
export type Qualname = string;
export type Digest = string;
export type Examples = {
  [k: string]: unknown;
}[];
export type Parent = string | null;
export type Kind1 = "project" | "module" | "literal";
export type Module = string | null;
export type Pointer = string;
export type Condition = string | null;
export type Decision = string;
export type When = boolean;
export type TimeoutSeconds = number;
export type Retries = number;
export type Idempotent = boolean;
export type AllowedImports = string[];
export type Dependencies = SymbolRef[];
export type SideEffects = boolean;
export type Modules = ModuleSpec[];
export type Id1 = string;
export type Target = string;
export type Port = string;
export type Dynamic = boolean;
export type Visibility = "L1" | "L2" | "L3" | "L4";
export type Provenance = "designed" | "migrated";
export type Bindings = PortBinding[];
export type Id2 = string;
export type Module1 = string;
export type Binding = string | null;
export type Boundary = "input" | "output";
export type Kind2 = "assertion" | "metric" | "capture" | "branch_observer";
export type Expression = string;
export type Policy = "continue" | "block" | "pause" | "breakpoint";
export type Pointer1 = string;
export type Enabled = boolean;
export type LanguageVersion = 1;
export type TrueTarget = string | null;
export type FalseTarget = string | null;
export type Probes = ProbeSpec[];
export type Level = "metadata" | "summary" | "sample" | "full";
export type SensitiveFields = string[];
export type MaxBytes = number;
export type SampleItems = number;
export type RetentionDays = number;
export type Concurrency = number;

export interface ProjectSpec {
  schema_version?: SchemaVersion;
  name?: Name;
  input_schema?: InputSchema;
  modules?: Modules;
  bindings?: Bindings;
  probes?: Probes;
  capture?: CapturePolicy;
  concurrency?: Concurrency;
  metadata?: Metadata;
}
export interface InputSchema {
  [k: string]: unknown;
}
export interface ModuleSpec {
  id: Id;
  name?: Name1;
  description?: Description;
  kind?: Kind;
  symbol?: SymbolRef | null;
  contract?: Contract;
  parent?: Parent;
  outputs?: Outputs;
  condition?: Condition;
  guard?: RouteGuard | null;
  timeout_seconds?: TimeoutSeconds;
  retries?: Retries;
  idempotent?: Idempotent;
  allowed_imports?: AllowedImports;
  dependencies?: Dependencies;
  side_effects?: SideEffects;
}
export interface SymbolRef {
  path: Path;
  qualname: Qualname;
  digest?: Digest;
}
export interface Contract {
  input?: Input;
  output?: Output;
  examples?: Examples;
}
export interface Input {
  [k: string]: unknown;
}
export interface Output {
  [k: string]: unknown;
}
export interface Outputs {
  [k: string]: Source;
}
/**
 * A JSON Pointer within project input, module output or a literal value.
 */
export interface Source {
  kind: Kind1;
  module?: Module;
  pointer?: Pointer;
  value?: Value;
}
export interface Value {
  [k: string]: unknown;
}
export interface RouteGuard {
  decision: Decision;
  when: When;
}
export interface PortBinding {
  id: Id1;
  target: Target;
  port: Port;
  source: Source;
  dynamic?: Dynamic;
  visibility?: Visibility;
  provenance?: Provenance;
}
export interface ProbeSpec {
  id: Id2;
  module: Module1;
  binding?: Binding;
  boundary?: Boundary;
  kind?: Kind2;
  expression?: Expression;
  policy?: Policy;
  pointer?: Pointer1;
  enabled?: Enabled;
  language_version?: LanguageVersion;
  true_target?: TrueTarget;
  false_target?: FalseTarget;
}
export interface CapturePolicy {
  level?: Level;
  sensitive_fields?: SensitiveFields;
  max_bytes?: MaxBytes;
  sample_items?: SampleItems;
  retention_days?: RetentionDays;
}
export interface Metadata {
  [k: string]: unknown;
}
