/** Typed command client for the P3 project gateway.
 *
 * Every path is prefix-implicit: the default transport is the shared research
 * request helper, which already prepends ``/api/v1/research``. The project id is
 * always encoded explicitly into the path, so there is never a mutable ambient
 * "active project": one factory holds the transport, and ``forProject(pid)``
 * returns an immutable, project-bound view of it.
 */
import type {
  ResearchProject,
  RunConfiguration,
  RuntimeReferenceState,
} from "./generated";
import type {
  ExecutionPlan,
  TaskRecord,
  WorkbenchConfig,
} from "../workspace/generated";
import { ProjectIdentityConflict } from "./queries";

export { ProjectIdentityConflict };

/** Transport options shared with the project query client. */
export interface ProjectTransportOptions {
  method?: string;
  body?: unknown;
  signal?: AbortSignal;
}
export type ProjectTransport = <T>(
  path: string,
  options?: ProjectTransportOptions,
) => Promise<T>;

/** Legacy shared research request helper (already prefixes the API root). */
export function legacyrequest<T>(
  path: string,
  options: ProjectTransportOptions = {},
): Promise<T> {
  return import("../client").then((module) => module.request<T>(path, options));
}

/** The authored entry page returned by ``GET /projects/{pid}/entries``. */
export interface EntriesPage {
  project_id: string;
  revision_id: string | null;
  config_revision: number;
  entries: RunConfiguration[];
  candidates: RunConfiguration[];
}

/** Body of ``POST /projects/{pid}/plans`` (generated DTOs only). */
export interface PlanRequest {
  configuration_id: string;
  revision_id?: string | null;
  scope?: "compute" | "probes" | "replot";
  run_id?: string | null;
  snapshot_ids?: string[];
  instance_ids?: string[] | null;
  target_scope?: Record<string, unknown> | null;
}

/** Project-bound, immutable command view. */
export interface ProjectClient {
  readonly projectId: string;
  info(signal?: AbortSignal): Promise<ResearchProject>;
  index(
    expectedRevision: string | null,
    signal?: AbortSignal,
  ): Promise<TaskRecord>;
  task(taskId: string, signal?: AbortSignal): Promise<TaskRecord>;
  cancelTask(taskId: string, signal?: AbortSignal): Promise<TaskRecord>;
  entries(
    expectedRevision: string | null,
    signal?: AbortSignal,
  ): Promise<EntriesPage>;
  saveEntries(
    entries: RunConfiguration[],
    expectedRevision: number,
    signal?: AbortSignal,
  ): Promise<WorkbenchConfig>;
  plan(request: PlanRequest, signal?: AbortSignal): Promise<ExecutionPlan>;
  execute(planId: string, signal?: AbortSignal): Promise<TaskRecord>;
  /** Host-machine runtime is machine-scoped, never project-scoped. */
  runtime(signal?: AbortSignal): Promise<RuntimeReferenceState>;
  registerInterpreter(
    reference: string,
    path: string,
    expectedRevision: number,
    signal?: AbortSignal,
  ): Promise<RuntimeReferenceState>;
  registerEnvironment(
    reference: string,
    values: Record<string, string>,
    expectedRevision: number,
    signal?: AbortSignal,
  ): Promise<RuntimeReferenceState>;
}

export interface ProjectCommands {
  recent(signal?: AbortSignal): Promise<ResearchProject[]>;
  open(path: string, signal?: AbortSignal): Promise<ResearchProject>;
  runtime(signal?: AbortSignal): Promise<RuntimeReferenceState>;
  registerInterpreter(
    reference: string,
    path: string,
    expectedRevision: number,
    signal?: AbortSignal,
  ): Promise<RuntimeReferenceState>;
  registerEnvironment(
    reference: string,
    values: Record<string, string>,
    expectedRevision: number,
    signal?: AbortSignal,
  ): Promise<RuntimeReferenceState>;
  forProject(projectId: string): ProjectClient;
}

/** Normalised command failure; ``status`` is 0 when the transport is not HTTP. */
export function commandError(error: unknown): {
  message: string;
  status: number;
} {
  const record = error as { status?: unknown; message?: unknown } | null;
  const status = typeof record?.status === "number" ? record.status : 0;
  const raw =
    typeof record?.message === "string" ? record.message : String(error);
  return { message: raw.trim() || "Request failed", status };
}

function expectProject(
  actual: string | null | undefined,
  expected: string,
  kind: string,
): void {
  if (actual && actual !== expected)
    throw new ProjectIdentityConflict(
      `${kind} response identity ${actual} does not match ${expected}`,
    );
}

function expectRevision(
  actual: string | null | undefined,
  expected: string | null | undefined,
  kind: string,
): void {
  if (actual && expected && actual !== expected)
    throw new ProjectIdentityConflict(
      `${kind} response revision ${actual} does not match ${expected}`,
    );
}

export function createProjectCommands(
  transport: ProjectTransport = legacyrequest,
): ProjectCommands {
  const call = <T>(
    path: string,
    options: ProjectTransportOptions,
  ): Promise<T> => transport<T>(path, options);
  // Every request carries an explicit signal option, even when undefined, so no
  // caller accidentally inherits an unconcelable request.
  const get = <T>(path: string, signal?: AbortSignal) =>
    call<T>(path, { method: "GET", signal });
  const send = <T>(
    path: string,
    method: string,
    body: unknown,
    signal?: AbortSignal,
  ) => call<T>(path, { method, body, signal });

  const runtime = (signal?: AbortSignal) =>
    get<RuntimeReferenceState>("/runtime", signal);

  const commands: ProjectCommands = {
    recent: (signal) => get<ResearchProject[]>("/projects", signal),
    open(path, signal) {
      const value = (path ?? "").trim();
      if (!value) throw new Error("Project folder path is required");
      return send<ResearchProject>(
        "/projects/open",
        "POST",
        { path: value },
        signal,
      ).then((project) => {
        if (!project.id)
          throw new ProjectIdentityConflict("Opened project has no id");
        return project;
      });
    },
    runtime,
    registerInterpreter: (reference, path, expectedRevision, signal) =>
      send<RuntimeReferenceState>(
        `/runtime/interpreters/${encodeURIComponent(reference)}`,
        "PUT",
        { path, expected_revision: expectedRevision },
        signal,
      ),
    registerEnvironment: (reference, values, expectedRevision, signal) =>
      send<RuntimeReferenceState>(
        `/runtime/environments/${encodeURIComponent(reference)}`,
        "PUT",
        { values, expected_revision: expectedRevision },
        signal,
      ),
    forProject(projectId) {
      if (!projectId) throw new Error("Project id is required");
      const base = `/projects/${encodeURIComponent(projectId)}`;
      const project: ProjectClient = {
        projectId,
        info(signal) {
          return get<ResearchProject>(base, signal).then((record) => {
            expectProject(record.id, projectId, "project");
            return record;
          });
        },
        index(expectedRevision, signal) {
          return send<TaskRecord>(
            `${base}/index`,
            "POST",
            { expected_revision: expectedRevision ?? null },
            signal,
          ).then((task) => {
            // The task's own revision id is the *new* revision, so only the
            // explicit project identity is comparable here.
            expectProject(task.project_id, projectId, "index task");
            return task;
          });
        },
        task(taskId, signal) {
          return get<TaskRecord>(
            `${base}/tasks/${encodeURIComponent(taskId)}`,
            signal,
          ).then((task) => {
            expectProject(task.project_id, projectId, "task");
            return task;
          });
        },
        cancelTask(taskId, signal) {
          return send<TaskRecord>(
            `${base}/tasks/${encodeURIComponent(taskId)}/cancel`,
            "POST",
            {},
            signal,
          ).then((task) => {
            expectProject(task.project_id, projectId, "task");
            return task;
          });
        },
        entries(expectedRevision, signal) {
          return get<EntriesPage>(`${base}/entries`, signal).then((page) => {
            expectProject(page.project_id, projectId, "entries");
            expectRevision(page.revision_id, expectedRevision, "entries");
            return page;
          });
        },
        saveEntries(entries, expectedRevision, signal) {
          return send<WorkbenchConfig>(
            `${base}/entries`,
            "PUT",
            { expected_revision: expectedRevision, entries },
            signal,
          ).then((config) => {
            if (config.revision !== expectedRevision + 1)
              throw new ProjectIdentityConflict(
                `entries response revision ${config.revision} does not follow ${expectedRevision}`,
              );
            return config;
          });
        },
        plan(request, signal) {
          const revision = (request.revision_id ?? "").trim();
          if (!revision)
            // An empty revision disables planning outright.
            return Promise.reject(
              new Error("A published revision is required before planning"),
            );
          return send<ExecutionPlan>(
            `${base}/plans`,
            "POST",
            {
              configuration_id: request.configuration_id,
              revision_id: revision,
              scope: request.scope ?? "compute",
              run_id: request.run_id ?? null,
              snapshot_ids: request.snapshot_ids ?? [],
              instance_ids: request.instance_ids ?? null,
              target_scope: request.target_scope ?? null,
            },
            signal,
          ).then((plan) => {
            expectProject(plan.project_id, projectId, "plan");
            expectRevision(plan.project_revision_id, revision, "plan");
            return plan;
          });
        },
        execute(planId, signal) {
          return send<TaskRecord>(
            `${base}/execute`,
            "POST",
            { plan_id: planId },
            signal,
          ).then((task) => {
            expectProject(task.project_id, projectId, "run");
            return task;
          });
        },
        runtime,
        registerInterpreter: commands.registerInterpreter,
        registerEnvironment: commands.registerEnvironment,
      };
      return Object.freeze(project);
    },
  };
  return Object.freeze(commands);
}
