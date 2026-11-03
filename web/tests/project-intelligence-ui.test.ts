import { describe, expect, it } from "vitest";
import { createProjectIntelligenceClient, ProjectIdentityConflict, type ProjectIntelligenceTransport } from "../src/research/projects/intelligenceClient";
import type { ProjectAIRequest } from "../src/research/projects/generated";

const request = (project: string, revision = "r1") => ({
  project_id: project, project_revision_id: revision,
} as ProjectAIRequest);

describe("project intelligence boundaries", () => {
  it("keeps concurrent projects and frozen revisions separate", async () => {
    const calls: Array<{path: string; body: unknown}> = [];
    const transport: ProjectIntelligenceTransport = async <T>(path: string, options?: {body?: unknown}) => {
      calls.push({path, body: options?.body});
      const body = options?.body as ProjectAIRequest;
      await Promise.resolve();
      return {project_id: body.project_id, project_revision_id: body.project_revision_id} as T;
    };
    const a = createProjectIntelligenceClient("a/b", transport);
    const b = createProjectIntelligenceClient("B", transport);
    await Promise.all([a.preview(request("a/b", "old")), b.preview(request("B", "new"))]);
    expect(calls.map(call => call.path)).toEqual(["/projects/a%2Fb/intelligence/context", "/projects/B/intelligence/context"]);
    expect(calls.map(call => (call.body as ProjectAIRequest).project_revision_id)).toEqual(["old", "new"]);
  });

  it("rejects another project's request before sending it", () => {
    let calls = 0;
    const transport: ProjectIntelligenceTransport = async <T>() => { calls++; return {} as T; };
    const client = createProjectIntelligenceClient("A", transport);
    expect(() => client.ask(request("B"))).toThrow(ProjectIdentityConflict);
    expect(calls).toBe(0);
  });

  it("rejects a stale context preview", async () => {
    const transport: ProjectIntelligenceTransport = async <T>() => ({project_id: "A", project_revision_id: "old"} as T);
    await expect(createProjectIntelligenceClient("A", transport).preview(request("A", "new"))).rejects.toThrow(ProjectIdentityConflict);
  });

  it("preserves queued acceptance and returns a new rollback proposal without applying it", async () => {
    const calls: Array<{path: string; body: unknown}> = [];
    const transport: ProjectIntelligenceTransport = async <T>(path: string, options?: {body?: unknown}) => {
      calls.push({path, body: options?.body});
      return (path.endsWith("/accept") ? {id: "task", status: "queued"} : {id: "new-proposal", status: "ready"}) as T;
    };
    const client = createProjectIntelligenceClient("A", transport);
    expect((await client.accept("change/id", "base")).status).toBe("queued");
    expect((await client.rollback("change/id", "current")).id).toBe("new-proposal");
    expect(calls).toEqual([
      {path: "/projects/A/changes/change%2Fid/accept", body: {expected_revision: "base"}},
      {path: "/projects/A/changes/change%2Fid/rollback", body: {expected_revision: "current"}},
    ]);
  });

  it("forwards cancellation and encodes context identity", async () => {
    const abort = new AbortController();
    const transport: ProjectIntelligenceTransport = async <T>(path, options) => {
      expect(path).toBe("/projects/A/intelligence/contexts/context%2Fid");
      expect(options?.signal).toBe(abort.signal);
      return {project_id: "A", project_revision_id: "r1"} as T;
    };
    await createProjectIntelligenceClient("A", transport).context("context/id", abort.signal);
  });
});
