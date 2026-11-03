/** Typed, revision-explicit read client for the P3 project gateway.
 *
 * Every request carries an explicit revision id; there is no ambient "latest".
 * The default transport is the shared research request helper, which already
 * handles the ``/api/v1/research`` prefix, so paths here start at ``/projects``.
 */
import type { SourceFile } from "../client";
import type { AnalysisDocument } from "../workspace/generated";
import type {
  ObjectPage,
  ProjectGraphSlice,
  ReferencePage,
  SymbolPage,
  TreePage,
} from "./generated";

/** A project source body plus the identity metadata the gateway returns. */
export interface ProjectSourceFile extends SourceFile {
  file_id: string;
  revision_id: string;
  project_id: string;
}

export interface TransportOptions {
  method?: string;
  body?: unknown;
  signal?: AbortSignal;
}
export type ProjectTransport = <T>(path: string, options?: TransportOptions) => Promise<T>;

export class ProjectIdentityConflict extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ProjectIdentityConflict";
  }
}

export interface TreeQueryOptions {
  parent_id?: string;
  offset?: number;
  limit?: number;
}
export interface ObjectQueryOptions {
  file_id?: string;
  scope_id?: string;
  query?: string;
  kind?: string;
  probe_status?: string;
  run_id?: string;
  offset?: number;
  limit?: number;
}
export interface GraphQueryOptions {
  scope_id?: string;
  view?: "code" | "data";
  limit?: number;
}
export interface SymbolQueryOptions {
  q?: string;
  offset?: number;
  limit?: number;
}
export interface ReferenceQueryOptions {
  file_id?: string;
  symbol?: string;
  logical_key?: string;
  offset?: number;
  limit?: number;
}

type ParamValue = string | number | boolean | null | undefined;

/** Encode params, omitting absent values while preserving zero/false. */
export function encodeQuery(params: Record<string, ParamValue>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null) continue;
    search.set(key, String(value));
  }
  const encoded = search.toString();
  return encoded ? `?${encoded}` : "";
}

/** Lazy default so importing this module never touches browser globals. */
function defaultTransport<T>(path: string, options?: TransportOptions): Promise<T> {
  return import("../client").then((module) => module.request<T>(path, options));
}

interface Envelope {
  project_id: string;
  revision_id: string;
}

export interface ProjectQueries {
  readonly projectId: string;
  tree(revisionId: string, options?: TreeQueryOptions, signal?: AbortSignal): Promise<TreePage>;
  objects(revisionId: string, options?: ObjectQueryOptions, signal?: AbortSignal): Promise<ObjectPage>;
  graph(revisionId: string, options?: GraphQueryOptions, signal?: AbortSignal): Promise<ProjectGraphSlice>;
  symbols(revisionId: string, options?: SymbolQueryOptions, signal?: AbortSignal): Promise<SymbolPage>;
  references(revisionId: string, options?: ReferenceQueryOptions, signal?: AbortSignal): Promise<ReferencePage>;
  source(revisionId: string, fileId: string, signal?: AbortSignal): Promise<ProjectSourceFile>;
  analysis(revisionId: string, fileId: string, signal?: AbortSignal): Promise<AnalysisDocument>;
}

/** Client-side merge of one paged response; used for object and tree pagination. */
export interface MergedPage<T> {
  items: T[];
  total: number;
}
export function mergePage<T>(
  existing: MergedPage<T> | undefined,
  page: { items: T[]; total: number },
  append: boolean,
): MergedPage<T> {
  const items = append && existing ? [...existing.items, ...page.items] : page.items;
  return { items, total: page.total };
}
export function loadedCount<T>(page: MergedPage<T> | undefined): number {
  return page?.items.length ?? 0;
}
export function hasMore<T>(page: MergedPage<T> | undefined): boolean {
  return !!page && page.items.length < page.total;
}

export function createProjectQueries(
  projectId: string,
  transport: ProjectTransport = defaultTransport,
): ProjectQueries {
  const base = `/projects/${encodeURIComponent(projectId)}`;
  const envelope = <T extends Envelope>(page: T, revisionId: string, kind: string): T => {
    if (page.project_id !== projectId || page.revision_id !== revisionId)
      throw new ProjectIdentityConflict(
        `${kind} response identity ${page.project_id}@${page.revision_id} does not match ${projectId}@${revisionId}`,
      );
    return page;
  };

  const queries: ProjectQueries = {
    projectId,
    tree(revisionId, options = {}, signal) {
      return transport<TreePage>(
        `${base}/tree${encodeQuery({ revision_id: revisionId, ...options })}`,
        { signal },
      ).then((page) => envelope(page, revisionId, "tree"));
    },
    objects(revisionId, options = {}, signal) {
      return transport<ObjectPage>(
        `${base}/objects${encodeQuery({ revision_id: revisionId, ...options })}`,
        { signal },
      ).then((page) => envelope(page, revisionId, "objects"));
    },
    graph(revisionId, options = {}, signal) {
      return transport<ProjectGraphSlice>(
        `${base}/graph${encodeQuery({ revision_id: revisionId, ...options })}`,
        { signal },
      ).then((page) => envelope(page, revisionId, "graph"));
    },
    symbols(revisionId, options = {}, signal) {
      return transport<SymbolPage>(
        `${base}/symbols${encodeQuery({ revision_id: revisionId, ...options })}`,
        { signal },
      ).then((page) => envelope(page, revisionId, "symbols"));
    },
    references(revisionId, options = {}, signal) {
      return transport<ReferencePage>(
        `${base}/references${encodeQuery({ revision_id: revisionId, ...options })}`,
        { signal },
      ).then((page) => envelope(page, revisionId, "references"));
    },
    source(revisionId, fileId, signal) {
      return transport<ProjectSourceFile>(
        `${base}/files/${encodeURIComponent(fileId)}/source${encodeQuery({ revision_id: revisionId })}`,
        { signal },
      ).then((page) => {
        if (
          page.project_id !== projectId ||
          page.revision_id !== revisionId ||
          page.file_id !== fileId
        )
          throw new ProjectIdentityConflict(
            `source response identity does not match ${projectId}@${revisionId}#${fileId}`,
          );
        return page;
      });
    },
    analysis(revisionId, fileId, signal) {
      // AnalysisDocument has no project/revision envelope, so identity cannot be
      // validated from the payload alone; the explicit revision is still sent.
      return transport<AnalysisDocument>(
        `${base}/files/${encodeURIComponent(fileId)}/analysis${encodeQuery({ revision_id: revisionId })}`,
        { signal },
      );
    },
  };
  return Object.freeze(queries);
}
