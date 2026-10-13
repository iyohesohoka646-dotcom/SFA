import { describe, expect, it } from "vitest";
import {
  createProjectQueries,
  hasMore,
  loadedCount,
  mergePage,
  ProjectIdentityConflict,
  type ProjectTransport,
  type TransportOptions,
} from "../src/research/projects/queries";
import {
  categoryLabel,
  edgeCategory,
  nodeShape,
  presentProjectGraph,
} from "../src/research/projects/graphPresentation";
import {
  groupObjectsByScope,
  scopeGroupKey,
  shortScope,
} from "../src/research/projects/ProjectBrowser";
import { objectScope, targetSelectionKey } from "../src/research/projects/identity";
import type {
  GraphBlock,
  GraphEdge,
  GraphNode,
  GraphPort,
  ObjectItem,
  ProjectGraphSlice,
  SemanticGraph,
  SourceRef,
  TargetRef,
} from "../src/research/projects/generated";

const source = (overrides: Partial<SourceRef> = {}): SourceRef => ({
  path: "pkg/mod.py",
  qualname: "pkg.mod.fn",
  line: 1,
  end_line: 2,
  digest: "digest",
  code: "SECRET_BODY",
  column: 0,
  end_column: 1,
  project_id: "proj",
  file_id: "file1",
  project_revision_id: "rev1",
  scope_id: "scope",
  ...overrides,
});

const port = (id: string, name: string, direction: GraphPort["direction"]): GraphPort => ({ id, name, direction });

const block = (overrides: Partial<GraphBlock> & Pick<GraphBlock, "id" | "kind">): GraphBlock => ({
  logical_key: overrides.id,
  label: overrides.id,
  parent_id: null,
  source: null,
  source_object_id: null,
  members: [],
  runtime_coverage: "supported",
  ...overrides,
});

const node = (overrides: Partial<GraphNode> & Pick<GraphNode, "id" | "kind" | "block_id">): GraphNode => ({
  label: overrides.id,
  logical_key: overrides.id,
  source: null,
  source_object_id: null,
  ports: [],
  version: 1,
  ...overrides,
});

const edge = (
  id: string,
  sourceId: string,
  targetId: string,
  kind: GraphEdge["kind"],
  label = "",
  branch: GraphEdge["branch"] = null,
): GraphEdge => ({
  id,
  source: sourceId,
  target: targetId,
  kind,
  label,
  source_port: null,
  target_port: null,
  branch,
  provenance: "inferred",
  original_ids: [id],
  count: 1,
});

// root(project) -> file -> fn(function) -> condition("if flag:") plus an
// external operation child of file guarded by a true control edge.
const compoundGraph = (): SemanticGraph => ({
  protocol_version: 4,
  source_digest: "graph-digest",
  roots: ["root"],
  omitted_count: 0,
  coverage: [],
  blocks: [
    block({ id: "root", kind: "project" }),
    block({ id: "file", kind: "file", parent_id: "root", source: source({ path: "pkg/mod.py", qualname: "" }) }),
    block({ id: "fn", kind: "function", parent_id: "file", source: source({ qualname: "pkg.mod.fn" }) }),
  ],
  nodes: [
    node({ id: "cond", kind: "condition", block_id: "fn", label: "if flag:", source: source() }),
    node({ id: "external", kind: "operation", block_id: "file", label: "external()" }),
  ],
  edges: [edge("flag", "cond", "external", "control", "flag", "true")],
});

const compoundSlice = (): ProjectGraphSlice => ({
  protocol_version: 3,
  project_id: "proj",
  revision_id: "rev1",
  scope_id: null,
  view: "code",
  omitted_count: 0,
  graph: compoundGraph(),
});

const graph = (): SemanticGraph => ({
  protocol_version: 4,
  source_digest: "graph-digest",
  roots: ["file"],
  omitted_count: 0,
  coverage: [],
  blocks: [
    block({ id: "file", kind: "file", source: source({ path: "pkg/mod.py", qualname: "" }) }),
    block({ id: "fn", kind: "function", parent_id: "file", source: source({ qualname: "pkg.mod.fn" }) }),
    block({ id: "peer", kind: "file", source: source({ path: "pkg/peer.py", qualname: "" }) }),
  ],
  nodes: [
    node({ id: "cond", kind: "condition", block_id: "fn", label: "x > 0", source: source() }),
    node({ id: "op", kind: "operation", block_id: "fn", label: "y = x + 1" }),
    node({ id: "call", kind: "call", block_id: "fn", label: "compute(x)" }),
    node({ id: "ret", kind: "return", block_id: "fn", label: "return y" }),
    node({ id: "data", kind: "data", block_id: "fn", label: "x", source_object_id: "obj1", ports: [port("data:in", "x", "input")] }),
    node({ id: "g", kind: "operation", block_id: "peer", label: "g()" }),
  ],
  edges: [
    edge("true", "cond", "op", "control", "true", "true"),
    edge("false", "cond", "ret", "control", "false", "false"),
    edge("call-edge", "op", "call", "call", "compute"),
    edge("arg-edge", "op", "call", "argument"),
    edge("return-edge", "call", "ret", "return", "result"),
    edge("data-edge", "data", "op", "data", "x"),
    edge("boundary", "cond", "g", "data", "shared"),
  ],
});

const slice = (overrides: Partial<ProjectGraphSlice> = {}): ProjectGraphSlice => ({
  protocol_version: 3,
  project_id: "proj",
  revision_id: "rev1",
  scope_id: null,
  view: "code",
  omitted_count: 0,
  graph: graph(),
  ...overrides,
});

// --- queries ---------------------------------------------------------------

function makeTransport(respond: (path: string, options?: TransportOptions) => unknown) {
  const calls: { path: string; options?: TransportOptions }[] = [];
  const transport: ProjectTransport = <T,>(path: string, options?: TransportOptions): Promise<T> => {
    calls.push({ path, options });
    return Promise.resolve(respond(path, options) as T);
  };
  return { calls, transport };
}

const treePage = (projectId: string, revisionId: string) => ({
  protocol_version: 1 as const,
  project_id: projectId,
  revision_id: revisionId,
  items: [],
  total: 0,
  offset: 0,
  limit: 200,
});

const sourceBody = (projectId: string, revisionId: string, fileId: string) => ({
  path: "pkg/mod.py",
  digest: "d",
  code: "print(1)",
  file_id: fileId,
  revision_id: revisionId,
  project_id: projectId,
});

describe("project queries", () => {
  it("keeps two projects independent, encodes the id, and is immutable", async () => {
    const a = makeTransport(() => treePage("p/1", "r1"));
    const b = makeTransport(() => treePage("p/2", "r1"));
    const qa = createProjectQueries("p/1", a.transport);
    const qb = createProjectQueries("p/2", b.transport);
    await qa.tree("r1");
    await qb.tree("r1");
    expect(a.calls[0].path).toBe("/projects/p%2F1/tree?revision_id=r1");
    expect(b.calls[0].path).toBe("/projects/p%2F2/tree?revision_id=r1");
    expect(Object.isFrozen(qa)).toBe(true);
    expect(qa.projectId).toBe("p/1");
    expect(qb.projectId).toBe("p/2");
  });

  it("forwards the caller AbortSignal to every transport call", async () => {
    const { calls, transport } = makeTransport((path) =>
      path.includes("/source") ? sourceBody("proj", "rev1", "file1") : treePage("proj", "rev1"),
    );
    const queries = createProjectQueries("proj", transport);
    const controller = new AbortController();
    await queries.tree("rev1", {}, controller.signal);
    await queries.source("rev1", "file1", controller.signal);
    expect(calls).toHaveLength(2);
    expect(calls[0].options?.signal).toBe(controller.signal);
    expect(calls[1].options?.signal).toBe(controller.signal);
  });

  it("rejects a page whose project or revision identity disagrees", async () => {
    const badRevision = makeTransport(() => treePage("proj", "other-revision"));
    await expect(createProjectQueries("proj", badRevision.transport).tree("rev1")).rejects.toBeInstanceOf(
      ProjectIdentityConflict,
    );
    const badProject = makeTransport(() => treePage("someone-else", "rev1"));
    await expect(createProjectQueries("proj", badProject.transport).objects("rev1")).rejects.toThrow(
      ProjectIdentityConflict,
    );
  });

  it("validates the source file id, revision and project before resolving", async () => {
    const good = makeTransport(() => sourceBody("proj", "rev1", "file1"));
    await expect(createProjectQueries("proj", good.transport).source("rev1", "file1")).resolves.toMatchObject({
      file_id: "file1",
    });
    const wrongFile = makeTransport(() => sourceBody("proj", "rev1", "file2"));
    await expect(createProjectQueries("proj", wrongFile.transport).source("rev1", "file1")).rejects.toThrow(
      ProjectIdentityConflict,
    );
  });

  it("issues no request during construction and omits undefined while keeping zero", async () => {
    const original = globalThis.fetch;
    let fetches = 0;
    globalThis.fetch = (() => {
      fetches += 1;
      return Promise.reject(new Error("unexpected fetch"));
    }) as typeof fetch;
    try {
      createProjectQueries("proj");
      await Promise.resolve();
      expect(fetches).toBe(0);
    } finally {
      globalThis.fetch = original;
    }
    const { calls, transport } = makeTransport(() => treePage("proj", "rev1"));
    await createProjectQueries("proj", transport).objects("rev1", { offset: 0, limit: undefined, file_id: "file1" });
    const path = calls[0].path;
    expect(path).toContain("offset=0");
    expect(path).not.toContain("limit=");
    expect(path).toContain("file_id=file1");
  });
});

describe("pagination and scope helpers", () => {
  it("merges pages by loaded item count and reports whether more remain", () => {
    type Page = { id: number };
    let merged = mergePage<Page>(undefined, { items: [{ id: 1 }, { id: 2 }], total: 5 }, false);
    expect(loadedCount(merged)).toBe(2);
    expect(hasMore(merged)).toBe(true);
    merged = mergePage(merged, { items: [{ id: 3 }, { id: 4 }], total: 5 }, true);
    expect(merged.items.map((item) => item.id)).toEqual([1, 2, 3, 4]);
    expect(loadedCount(merged)).toBe(4);
    merged = mergePage(merged, { items: [{ id: 5 }], total: 5 }, true);
    expect(loadedCount(merged)).toBe(5);
    expect(hasMore(merged)).toBe(false);
    expect(hasMore(undefined)).toBe(false);
  });

  it("keeps distinct nested scopes apart while shortening their labels", () => {
    const item = (qualname: string, name: string): ObjectItem =>
      ({
        name,
        source: source({ qualname: `${qualname}.${name}` }),
        line: 1,
        target: {
          project_id: "proj",
          file_id: "file1",
          logical_key: `proj::file1::${qualname}::${name}`,
        } as TargetRef,
      } as ObjectItem);
    const items = [item("A.fn", "x"), item("B.fn", "x"), item("A.fn", "y")];
    const groups = groupObjectsByScope(items);
    expect(groups).toHaveLength(2);
    expect(groups.map((group) => group.key)).toEqual([
      "proj::file1::A.fn",
      "proj::file1::B.fn",
    ]);
    expect(groups.every((group) => group.label === "fn")).toBe(true);
    expect(shortScope("pkg.mod.Class.run")).toBe("run");
    expect(scopeGroupKey(item("pkg.mod.Class.run", "v"))).toBe("proj::file1::pkg.mod.Class.run");
  });
});

describe("object scope and selection identity", () => {
  it("groups real-API module globals by canonical module scope", () => {
    const globalItem = (name: string): ObjectItem =>
      ({
        name,
        source: source({ qualname: name }),
        line: 1,
        target: {
          project_id: "proj",
          file_id: "file1",
          logical_key: `proj::file1::<module>::${name}`,
        } as TargetRef,
      } as ObjectItem);
    const items = [globalItem("value_000"), globalItem("value_001")];
    expect(objectScope(items[0])).toBe("proj::file1::<module>");
    expect(objectScope(items[1])).toBe("proj::file1::<module>");
    expect(groupObjectsByScope(items)).toHaveLength(1);
  });

  it("shares one selection key for data targets across assignment ids", () => {
    const base = {
      kind: "data",
      project_id: "proj",
      file_id: "file1",
      logical_key: "proj::file1::fn::x",
      object_id: "1",
    } as TargetRef;
    const other = { ...base, object_id: "2" } as TargetRef;
    expect(targetSelectionKey(base)).toBe(targetSelectionKey(other));
  });

  it("distinguishes selection keys across files, projects and exact evidence", () => {
    const base = {
      kind: "data",
      project_id: "proj",
      file_id: "file1",
      logical_key: "proj::file1::fn::x",
      object_id: "1",
    } as TargetRef;
    expect(targetSelectionKey(base)).not.toBe(targetSelectionKey({ ...base, file_id: "file2" } as TargetRef));
    expect(targetSelectionKey(base)).not.toBe(targetSelectionKey({ ...base, project_id: "p2" } as TargetRef));
    const snapshot = { ...base, exact_evidence: true, snapshot_id: "s1", run_id: "r1" } as TargetRef;
    const otherRun = { ...base, exact_evidence: true, snapshot_id: "s1", run_id: "r2" } as TargetRef;
    expect(targetSelectionKey(snapshot)).not.toBe(targetSelectionKey(otherRun));
  });
});

// --- pure graph presentation ----------------------------------------------

describe("project graph presentation", () => {
  it("assigns control, operation and data shapes plus distinct plates", () => {
    const presentation = presentProjectGraph(slice(), new Set());
    const shape = (id: string) => presentation.nodes.find((n) => n.id === id)?.data.shape;
    expect(shape("cond")).toBe("circle");
    expect(shape("op")).toBe("diamond");
    expect(shape("call")).toBe("diamond");
    expect(shape("file")).toBe("plate");
    expect(shape("fn")).toBe("plate");
    const dataView = presentProjectGraph(slice({ view: "data" }), new Set());
    expect(dataView.nodes.find((n) => n.id === "data")?.data.shape).toBe("rounded");
    expect(nodeShape("loop_header", false)).toBe("circle");
    expect(nodeShape("merge", false)).toBe("diamond");
  });

  it("labels system categories in English and retains the condition expression", () => {
    expect(categoryLabel("condition")).toBe("If");
    expect(categoryLabel("data")).toBe("Data");
    expect(edgeCategory({ kind: "call", branch: null })).toBe("Call");
    expect(edgeCategory({ kind: "return", branch: null })).toBe("Return");
    expect(edgeCategory({ kind: "control", branch: "true" })).toBe("True");
    expect(edgeCategory({ kind: "control", branch: "false" })).toBe("False");
    const presentation = presentProjectGraph(slice(), new Set());
    const categories = new Set(presentation.edges.map((e) => e.data?.category));
    for (const expected of ["Data", "Call", "Return", "True", "False"]) expect(categories.has(expected)).toBe(true);
    const trueEdge = presentation.edges.find((e) => e.data?.original_ids.includes("true"))!;
    expect(trueEdge.data?.condition).toBe("x > 0");
    expect(trueEdge.data?.title).toContain("x > 0");
    expect(presentation.nodes.find((n) => n.id === "fn")!.data.label).toBe("fn");
    expect(presentation.nodes.some((n) => (n.data.handles).some((h) => /[　-鿿]/.test(h.name)))).toBe(false);
  });

  it("preserves compound parents, real dimensions, order, identity and no source body", () => {
    const presentation = presentProjectGraph(compoundSlice(), new Set());
    const byId = new Map(presentation.nodes.map((n) => [n.id, n]));
    expect(byId.get("file")!.parentId).toBe("root");
    expect(byId.get("fn")!.parentId).toBe("file");
    expect(byId.get("cond")!.parentId).toBe("fn");
    expect(byId.get("external")!.parentId).toBe("file");
    for (const n of presentation.nodes) {
      expect(n.style?.width).toBe(n.width);
      expect(n.style?.height).toBe(n.height);
      if (n.parentId) expect(byId.has(n.parentId)).toBe(true);
    }
    const index = new Map(presentation.nodes.map((n, i) => [n.id, i]));
    expect(index.get("root")!).toBeLessThan(index.get("file")!);
    expect(index.get("file")!).toBeLessThan(index.get("fn")!);
    expect(index.get("fn")!).toBeLessThan(index.get("cond")!);
    const condTarget = byId.get("cond")!.data.target as TargetRef;
    expect(condTarget.project_id).toBe("proj");
    expect(condTarget.file_id).toBe("file1");
    expect(condTarget.project_revision_id).toBe("rev1");
    expect(JSON.stringify(presentation)).not.toContain("SECRET_BODY");
    const base = presentProjectGraph(compoundSlice(), new Set(), "RIGHT");
    expect(presentProjectGraph(compoundSlice(), new Set(), "RIGHT").layoutKey).toBe(base.layoutKey);
    expect(presentProjectGraph(compoundSlice(), new Set(["fn"]), "RIGHT").layoutKey).not.toBe(base.layoutKey);
    expect(presentProjectGraph(compoundSlice(), new Set(), "DOWN").layoutKey).not.toBe(base.layoutKey);
  });

  it("keeps boundary ports and original references when folding, with no dangling edges", () => {
    const folded = presentProjectGraph(slice(), new Set(["fn"]));
    const boundaryEdge = folded.edges.find((e) => e.source === "fn" && e.target === "g")!;
    expect(boundaryEdge).toBeDefined();
    expect(boundaryEdge.data?.original_ids).toContain("boundary");
    expect(boundaryEdge.data?.category).toBe("Data");
    const fn = folded.nodes.find((n) => n.id === "fn")!;
    expect(fn.data.handles.some((h) => h.boundary && h.original_ids.includes("boundary"))).toBe(true);
    expect(folded.edges.some((e) => (e.data?.original_ids ?? []).includes("call-edge"))).toBe(false);
    for (const collapsed of [new Set<string>(), new Set(["fn"]), new Set(["file"])]) {
      const presentation = presentProjectGraph(slice(), collapsed);
      const byId = new Map(presentation.nodes.map((n) => [n.id, n]));
      for (const e of presentation.edges) {
        const from = byId.get(e.source);
        const to = byId.get(e.target);
        expect(from).toBeDefined();
        expect(to).toBeDefined();
        expect(from!.data.handles.some((h) => h.id === e.sourceHandle)).toBe(true);
        expect(to!.data.handles.some((h) => h.id === e.targetHandle)).toBe(true);
      }
    }
  });

  it("keeps the original predicate on a collapsed condition edge", () => {
    const folded = presentProjectGraph(compoundSlice(), new Set(["fn"]));
    const edge = folded.edges.find((e) => e.source === "fn" && e.target === "external")!;
    expect(edge).toBeDefined();
    expect(edge.data?.category).toBe("True");
    expect(edge.data?.condition).toContain("flag");
    expect(edge.data?.title).toContain("flag");
    expect(folded.nodes.some((n) => n.id === "cond")).toBe(false);
  });
});


it("server-scoped file slices accept opaque file identity without refiltering",()=>{
 const s=compoundSlice();s.scope_id="opaque-file-identity";s.graph.blocks=s.graph.blocks.filter(b=>b.id!=="root");s.graph.blocks[0].parent_id=null;s.graph.roots=["file"];
 const p=presentProjectGraph(s,new Set());expect(p.nodes.some(n=>n.id==="cond")).toBe(true);
});
it("server-scoped slices preserve external boundary roots",()=>{
 const s=compoundSlice();s.scope_id="file";s.graph.blocks=s.graph.blocks.filter(b=>b.id!=="root");s.graph.blocks[0].parent_id=null;
 s.graph.blocks.push(block({id:"outside",kind:"file"}));s.graph.roots=["file","outside"];s.graph.edges.push(edge("call","fn","outside","call","double"));
 const p=presentProjectGraph(s,new Set());expect(p.nodes.some(n=>n.id==="outside")).toBe(true);expect(p.edges.some(e=>e.target==="outside")).toBe(true);
});
