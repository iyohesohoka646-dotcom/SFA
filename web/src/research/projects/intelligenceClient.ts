/** Typed, project-scoped client for the P4 intelligence + change gateway.
 *
 * Every call carries an explicit ``project_id`` closure: the client is created
 * for exactly one project and never reads an ambient "current project". The
 * default transport is the shared research ``request`` helper, which already
 * prefixes ``/api/v1/research``, so paths here start at ``/projects``. Requests
 * and revisions stay frozen per call; there is no mutable global identity and
 * no vendor, key or model default fabricated here.
 */
import { ProjectIdentityConflict } from "./queries";
import type { ContextRecord as WorkbenchContextRecord } from "../workspace/WorkbenchClient";
import type { TaskRecord } from "../workspace/generated";
import type {
  ProjectAIRequest,
  ProjectChangeEditRequest,
  ProjectChangePage,
  ProjectChangeSet,
  ProjectContextPreview,
  ProjectRecoveryState,
} from "./generated";

export { ProjectIdentityConflict };

/** A project context record is the shared workbench shape plus the actual
 * project/revision attribution the P4 gateway binds at execution time. */
export type ContextRecord = WorkbenchContextRecord & {
  project_id?: string;
  project_revision_id?: string;
};

export interface TransportOptions {
  method?: string;
  body?: unknown;
  signal?: AbortSignal;
}
export type ProjectIntelligenceTransport = <T>(
  path: string,
  options?: TransportOptions,
) => Promise<T>;

/** Lazy default so importing this module never touches browser globals. */
function legacyRequest<T>(
  path: string,
  options?: TransportOptions,
): Promise<T> {
  return import("../client").then((module) => module.request<T>(path, options));
}

export interface ProjectIntelligenceClient {
  readonly projectId: string;
  preview(
    request: ProjectAIRequest,
    signal?: AbortSignal,
  ): Promise<ProjectContextPreview>;
  ask(request: ProjectAIRequest, signal?: AbortSignal): Promise<TaskRecord>;
  context(id: string, signal?: AbortSignal): Promise<ContextRecord>;
  changes(signal?: AbortSignal): Promise<ProjectChangePage>;
  change(id: string, signal?: AbortSignal): Promise<ProjectChangeSet>;
  propose(
    baseRevision: string,
    edits: ProjectChangeEditRequest[],
    signal?: AbortSignal,
  ): Promise<ProjectChangeSet>;
  accept(
    id: string,
    expectedRevision: string,
    signal?: AbortSignal,
  ): Promise<TaskRecord>;
  reject(
    id: string,
    expectedRevision: string,
    signal?: AbortSignal,
  ): Promise<ProjectChangeSet>;
  rollback(
    id: string,
    expectedRevision: string,
    signal?: AbortSignal,
  ): Promise<ProjectChangeSet>;
  recovery(signal?: AbortSignal): Promise<ProjectRecoveryState>;
  recover(
    expectedRevision: string,
    signal?: AbortSignal,
  ): Promise<ProjectChangeSet>;
  task(id: string, signal?: AbortSignal): Promise<TaskRecord>;
}

export function createProjectIntelligenceClient(
  projectId: string,
  transport: ProjectIntelligenceTransport = legacyRequest,
): ProjectIntelligenceClient {
  const base = `/projects/${encodeURIComponent(projectId)}`;

  const assertInput = (request: ProjectAIRequest) => {
    if (request.project_id !== projectId)
      throw new ProjectIdentityConflict(
        `request project ${request.project_id} does not match client ${projectId}`,
      );
  };

  const client: ProjectIntelligenceClient = {
    projectId,
    preview(request, signal) {
      assertInput(request);
      return transport<ProjectContextPreview>(`${base}/intelligence/context`, {
        method: "POST",
        body: request,
        signal,
      }).then((preview) => {
        if (
          preview.project_id !== projectId ||
          preview.project_revision_id !== request.project_revision_id
        )
          throw new ProjectIdentityConflict(
            `context preview identity ${preview.project_id}@${preview.project_revision_id} does not match ${projectId}@${request.project_revision_id}`,
          );
        return preview;
      });
    },
    ask(request, signal) {
      assertInput(request);
      return transport<TaskRecord>(`${base}/intelligence`, {
        method: "POST",
        body: request,
        signal,
      }).then((task) => {
        if (task.project_id && task.project_id !== projectId)
          throw new ProjectIdentityConflict(
            `task project ${task.project_id} does not match client ${projectId}`,
          );
        return task;
      });
    },
    context(id, signal) {
      return transport<ContextRecord>(
        `${base}/intelligence/contexts/${encodeURIComponent(id)}`,
        { signal },
      ).then((record) => {
        if (record.project_id && record.project_id !== projectId)
          throw new ProjectIdentityConflict(
            `context record project ${record.project_id} does not match client ${projectId}`,
          );
        return record;
      });
    },
    changes(signal) {
      return transport<ProjectChangePage>(`${base}/changes`, { signal }).then(
        (page) => {
          if (page.project_id && page.project_id !== projectId)
            throw new ProjectIdentityConflict(
              `change page project ${page.project_id} does not match client ${projectId}`,
            );
          return page;
        },
      );
    },
    change(id, signal) {
      return transport<ProjectChangeSet>(
        `${base}/changes/${encodeURIComponent(id)}`,
        { signal },
      ).then((change) => {
        if (change.project_id && change.project_id !== projectId)
          throw new ProjectIdentityConflict(
            `change ${change.id} project ${change.project_id} does not match client ${projectId}`,
          );
        return change;
      });
    },
    propose(baseRevision, edits, signal) {
      return transport<ProjectChangeSet>(`${base}/changes`, {
        method: "POST",
        body: { base_revision: baseRevision, edits },
        signal,
      });
    },
    accept(id, expectedRevision, signal) {
      return transport<TaskRecord>(
        `${base}/changes/${encodeURIComponent(id)}/accept`,
        {
          method: "POST",
          body: { expected_revision: expectedRevision },
          signal,
        },
      );
    },
    reject(id, expectedRevision, signal) {
      return transport<ProjectChangeSet>(
        `${base}/changes/${encodeURIComponent(id)}/reject`,
        {
          method: "POST",
          body: { expected_revision: expectedRevision },
          signal,
        },
      );
    },
    rollback(id, expectedRevision, signal) {
      return transport<ProjectChangeSet>(
        `${base}/changes/${encodeURIComponent(id)}/rollback`,
        {
          method: "POST",
          body: { expected_revision: expectedRevision },
          signal,
        },
      );
    },
    recovery(signal) {
      return transport<ProjectRecoveryState>(`${base}/changes/recovery`, {
        signal,
      });
    },
    recover(expectedRevision, signal) {
      return transport<ProjectChangeSet>(`${base}/changes/recover`, {
        method: "POST",
        body: { expected_revision: expectedRevision },
        signal,
      });
    },
    task(id, signal) {
      return transport<TaskRecord>(`${base}/tasks/${encodeURIComponent(id)}`, {
        signal,
      });
    },
  };
  return Object.freeze(client);
}
