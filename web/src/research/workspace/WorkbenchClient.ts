import { headers } from "../../api";
import { request } from "../client";
import type {
  AnalysisDocument,
  CodeProposal,
  ExecutionPlan,
  HarnessRequest,
  ProbeDefinition,
  ProbeOutput,
  TaskRecord,
  WorkbenchConfig,
  ScopeSelector,
  ProbeInstance,
  ProbeResource,
  DataSemantics,
} from "./generated";

const call = <T>(
  path: string,
  body?: unknown,
  signal?: AbortSignal,
  method = body === undefined ? "GET" : "POST",
) => request<T>("/workbench" + path, { method, body, signal });
export interface PublicTool {
  id: string;
  label: string;
  package: string;
  url: string;
  adapter_status: string;
  format: string;
  available: boolean;
  version: string | null;
  interpreter: string | null;
  enabled: boolean;
  managed: boolean;
}
export interface ContextRecord {
  id: string;
  status: string;
  answer: string;
  message?: string;
  citations: string[];
  provenance: string;
  policy: HarnessRequest["policy"];
  budget_method: string;
  calls: {
    step: number;
    messages: { role: string; content: string }[];
    response?: string;
    status?: string;
    input_token_bound: number;
    usage?: Record<string, number>;
    requests?: number;
    duration_ms?: number;
  }[];
  tools: { step: number; name: string; arguments: unknown; output: unknown }[];
}
export interface SkillRecord {
  id: string;
  title: string;
  version: string;
  truncated: boolean;
}
export interface Preferences {
  values: Record<string, Record<string, string | number | boolean>>;
  sources: Record<string, string>;
  user_revision: number;
  project_revision: number;
}
export const wb = {
  preferences: () => call<Preferences>("/settings"),
  savePreferences: (
    scope: string,
    values: Preferences["values"],
    expected_revision: number,
  ) =>
    call<Preferences>(
      "/settings",
      { scope, values, expected_revision },
      undefined,
      "PUT",
    ),
  resetPreferences: (scope: string, group: string, expected_revision: number) =>
    call<Preferences>("/settings/reset", { scope, group, expected_revision }),
  analyses: (signal?: AbortSignal) =>
    call<AnalysisDocument[]>("/analyses", undefined, signal),
  analysis: (id: string, signal?: AbortSignal) =>
    call<AnalysisDocument>(
      "/analyses/" + encodeURIComponent(id),
      undefined,
      signal,
    ),
  runAnalysis: (id: string, signal?: AbortSignal) =>
    call<AnalysisDocument>(
      "/runs/" + encodeURIComponent(id) + "/analysis",
      undefined,
      signal,
    ),
  source: (id: string, signal?: AbortSignal) =>
    call<import("../client").SourceFile>(
      "/analyses/" + encodeURIComponent(id) + "/source",
      undefined,
      signal,
    ),
  importSource: (path: string, signal?: AbortSignal) =>
    call<AnalysisDocument>("/analyses", { path }, signal),
  configuration: (signal?: AbortSignal) =>
    call<WorkbenchConfig>("/configuration", undefined, signal),
  configure: (config: WorkbenchConfig, signal?: AbortSignal) =>
    call<WorkbenchConfig>(
      "/configuration",
      { config, expected_revision: config.revision },
      signal,
      "PUT",
    ),
  presenters: (id: string, signal?: AbortSignal) =>
    call<ProbeInstance[]>(
      "/snapshots/" + encodeURIComponent(id) + "/presenters",
      undefined,
      signal,
    ),
  semantics: (id: string, signal?: AbortSignal) =>
    call<DataSemantics | null>(
      "/snapshots/" + encodeURIComponent(id) + "/semantics",
      undefined,
      signal,
    ),
  saveSemantics: (id: string, semantics: DataSemantics) =>
    call<DataSemantics>(
      "/snapshots/" + encodeURIComponent(id) + "/semantics",
      { semantics, expected_revision: semantics.revision },
      undefined,
      "PUT",
    ),
  templates: () =>
    call<
      {
        id: string;
        label: string;
        definition_id: string;
        parameters: Record<string, unknown>;
      }[]
    >("/templates"),
  saveTemplate: (
    id: string,
    label: string,
    definition_id: string,
    parameters: Record<string, unknown>,
  ) => call("/templates", { id, label, definition_id, parameters }),
  resources: () => call<ProbeResource[]>("/resources"),
  importResource: (body: unknown) => call<ProbeResource>("/resources", body),
  resourceAction: (
    id: string,
    action: "enable" | "disable",
    expected_digest?: string | null,
  ) =>
    call<ProbeResource>("/resources/" + encodeURIComponent(id) + "/" + action, {
      expected_digest,
    }),
  resourceDraft: (id: string) =>
    call<ProbeResource>("/resources/" + encodeURIComponent(id) + "/draft"),
  expire: () =>
    call<{ artifacts_deleted: number; history_preserved: boolean }>(
      "/storage/expire",
      {},
    ),
  derived: (id: string) =>
    call<{ retained: boolean }>("/derived/" + encodeURIComponent(id)),
  derivedRetention: (id: string, retained: boolean) =>
    call("/derived/" + encodeURIComponent(id) + "/retention", { retained }),
  derivedProposal: (id: string) =>
    call<CodeProposal>("/derived/" + encodeURIComponent(id) + "/proposal", {}),
  describeTool: (id: string) =>
    call<TaskRecord>("/tools/" + encodeURIComponent(id) + "/describe", {}),
  definitions: (signal?: AbortSignal) =>
    call<ProbeDefinition[]>("/probe-definitions", undefined, signal),
  plan: (
    analysis_id: string,
    signal?: AbortSignal,
    target_scope?: ScopeSelector,
  ) => call<ExecutionPlan>("/plans", { analysis_id, target_scope }, signal),
  execute: (plan_id: string, signal?: AbortSignal) =>
    call<TaskRecord>("/execute", { plan_id }, signal),
  evaluate: (
    run_id: string,
    snapshot_ids: string[],
    instance_ids?: string[],
    target_scope?: ScopeSelector,
  ) =>
    call<TaskRecord>("/evaluate", {
      run_id,
      snapshot_ids,
      instance_ids,
      target_scope,
    }),
  replot: (
    run_id: string,
    snapshot_ids: string[],
    instance_ids?: string[],
    target_scope?: ScopeSelector,
  ) =>
    call<TaskRecord>("/replot", {
      run_id,
      snapshot_ids,
      instance_ids,
      target_scope,
    }),
  tasks: (signal?: AbortSignal) =>
    call<TaskRecord[]>("/tasks", undefined, signal),
  task: (id: string, signal?: AbortSignal) =>
    call<TaskRecord>("/tasks/" + encodeURIComponent(id), undefined, signal),
  cancel: (id: string) =>
    call<TaskRecord>("/tasks/" + encodeURIComponent(id) + "/cancel", {}),
  output: (id: string) =>
    call<ProbeOutput>("/outputs/" + encodeURIComponent(id)),
  outputs: (
    query: { task_id?: string; run_id?: string; snapshot_id?: string; before?: string },
    signal?: AbortSignal,
  ) =>
    call<ProbeOutput[]>(
      "/outputs?" + new URLSearchParams(query).toString(),
      undefined,
      signal,
    ),
  relationships: (snapshotId: string, signal?: AbortSignal) =>
    call<ProbeOutput>(
      "/relationships/" + encodeURIComponent(snapshotId),
      undefined,
      signal,
    ),
  tools: (signal?: AbortSignal) =>
    call<PublicTool[]>("/tools", undefined, signal),
  scanTools: (interpreter: string) =>
    call<TaskRecord>("/tools/scan", { interpreter }),
  installTool: (id: string) =>
    call<TaskRecord>("/tools/" + encodeURIComponent(id) + "/install", {}),
  removeTool: (id: string) =>
    call<TaskRecord>("/tools/" + encodeURIComponent(id) + "/remove", {}),
  disableTool: (id: string, disabled: boolean) =>
    call<PublicTool[]>("/tools/" + encodeURIComponent(id) + "/disable", {
      disabled,
    }),
  ask: (body: HarnessRequest) => call<TaskRecord>("/intelligence", body),
  contexts: (signal?: AbortSignal) =>
    call<Omit<ContextRecord, "calls" | "tools">[]>(
      "/contexts",
      undefined,
      signal,
    ),
  context: (id: string, signal?: AbortSignal) =>
    call<ContextRecord>(
      "/contexts/" + encodeURIComponent(id),
      undefined,
      signal,
    ),
  skills: (signal?: AbortSignal) =>
    call<SkillRecord[]>("/skills", undefined, signal),
  registerSkill: (path: string) => call<SkillRecord>("/skills", { path }),
  manual: (body: {
    instance_id: string;
    analysis_id: string;
    snapshot_id?: string;
    note: string;
    verdict: string;
  }) => call<ProbeOutput>("/manual-results", body),
  changes: (signal?: AbortSignal) =>
    call<CodeProposal[]>("/changes", undefined, signal),
  propose: (
    analysis_id: string,
    object_id: string | null,
    candidate: string,
    relative_path?: string,
  ) =>
    call<CodeProposal>("/changes", {
      analysis_id,
      object_id,
      candidate,
      relative_path,
    }),
  change: (id: string, action: "validate" | "accept" | "reject" | "rollback") =>
    call<CodeProposal>("/changes/" + encodeURIComponent(id) + "/" + action, {}),
  validation: (id: string, run_id: string, output_ids: string[]) =>
    call<CodeProposal>("/changes/" + encodeURIComponent(id) + "/validation", {
      run_id,
      output_ids,
    }),
  artifact: async (id: string, signal?: AbortSignal) => {
    const response = await fetch(
      "/api/v1/research/workbench/artifacts/" + encodeURIComponent(id),
      { headers: headers(), signal },
    );
    if (!response.ok) throw new Error("绘图产物不可用");
    return response.blob();
  },
};
