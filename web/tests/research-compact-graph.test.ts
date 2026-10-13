import { describe, expect, it } from "vitest";
import { projectDisplayGraph, graphCaption, graphExpression, normalizeGraphMode } from "../src/research/workspace/graph-display";
import type { GraphBlock, GraphEdge, GraphNode, SemanticGraph } from "../src/research/workspace/generated";
const block = (id: string, parent_id: string | null = null, kind = "file"): GraphBlock => ({ id, parent_id, kind,
  label: id + ".py", logical_key: id, source: null, source_object_id: null, members: [], runtime_coverage: "supported" } as GraphBlock);
const node = (id: string, kind: string, label: string, logical_key = id, block_id = "file"): GraphNode => ({ id, kind, label, logical_key,
  block_id, source: null, source_object_id: id, ports: [], version: 1 } as GraphNode);
const edge = (id: string, source: string, target: string, kind = "data", branch = null): GraphEdge => ({ id, source, target, kind,
  label: "", branch, original_ids: [id], count: 1, source_port: null, target_port: null, provenance: "inferred" } as GraphEdge);
const fixture = (): SemanticGraph => ({ protocol_version: 3, source_digest: "digest", roots: ["file"], omitted_count: 0, coverage: [],
  blocks: [block("file")], nodes: [node("doc", "operation", '"""Long explanation of covariance and PCA"""'),
    node("x1", "data", "X", "module:X"), node("x2", "data", "X", "module:X"), node("mu", "data", "mu"), node("z", "data", "Z"),
    node("a", "operation", "mu = X.mean(axis=0)"), node("b", "operation", "Z = X - mu")],
  edges: [edge("d1", "x1", "a"), edge("d2", "a", "mu"), edge("d3", "mu", "b"), edge("d4", "x2", "b"), edge("d5", "b", "z"), edge("flow", "a", "b", "control")],
});
describe("two concise graph surfaces", () => {
  it("migrates legacy graph modes to Code without a third graph mode", () => {
    expect(["structure", "execution", "code", "data", "wrong"].map(normalizeGraphMode)).toEqual(["code", "code", "code", "data", "code"]);
  });
  it("shows logical variables only in Data, contracting computation paths and repeated definitions", () => {
    const p = projectDisplayGraph(fixture(), new Set(), "data");
    expect(p.nodes.filter(n => !n.plate).map(n => n.label).sort()).toEqual(["X", "Z", "mu"]);
    const labels = new Map(p.nodes.map(n => [n.id, n.label]));
    expect(p.edges.map(e => `${labels.get(e.source)}>${labels.get(e.target)}`).sort()).toEqual(["X>Z", "X>mu", "mu>Z"]);
    expect(p.edges.flatMap(e => e.original_ids)).toContain("d5");
    expect(p.edges.every(e => e.kind === "data")).toBe(true);
  });
  it("keeps Code flow compact and excludes docstrings and variable relationship lines", () => {
    const p = projectDisplayGraph(fixture(), new Set(), "code");
    expect(p.nodes.filter(n => !n.plate).map(n => n.id)).toEqual(["a", "b"]);
    expect(p.edges).toHaveLength(1);
    expect(p.edges[0].displayLabel).toBe("");
    expect(p.nodes.every(n => n.label.length <= 40 && !n.label.includes("axis=0"))).toBe(true);
  });
  it("keeps local variables with the same name in different functions separate", () => {
    const g = fixture(); g.blocks.push(block("fn", "file", "function"));
    g.nodes.push(node("local", "data", "X", "function:X", "fn"));
    const p = projectDisplayGraph(g, new Set(), "data");
    expect(p.nodes.filter(n => n.label === "X")).toHaveLength(2);
  });
  it("coalesces equal folded boundary relations, retaining all original references and one shared port", () => {
    const g = fixture(); g.blocks.push(block("fn", "file", "function"));
    g.nodes.push(node("c", "operation", "f()", "fn:c", "fn"));
    g.edges.push(edge("c1", "a", "c", "data"), edge("c2", "b", "c", "data"));
    const p = projectDisplayGraph(g, new Set(["fn"]), "code");
    const fn = p.nodes.find(n => n.id === "fn")!;
    expect(fn.handles.filter(h => h.direction === "input")).toHaveLength(1);
    expect(fn.handles[0].original_ids.sort()).toEqual(["c1", "c2"]);
  });
  it("keeps real process dependencies and does not invent order between unrelated calls", () => {
    const g = fixture(); g.nodes.push(node("c", "call", "q = external()"));
    g.edges.push(edge("text-order", "b", "c", "control"));
    const p = projectDisplayGraph(g, new Set(), "code");
    expect(p.edges.some(e => e.source === "b" && e.target === "c")).toBe(false);
    expect(p.edges.find(e => e.source === "a" && e.target === "b")).toMatchObject({ kind: "data", label: "" });
    expect(p.edges.flatMap(e => e.original_ids)).toContain("d3");
    expect(p.nodes.find(n => n.id === "b")!.expression).toBe("X - mu");
  });
  it("retains long conditions and visible math rather than truncating the computation", () => {
    const text = "options.failure == 'constant' and options.iteration_limit > 100";
    expect(graphCaption(node("n", "condition", text))).toBe(text);
    expect(graphExpression(node("n", "operation", "C = Z.T @ Z / (X.shape[0] - 1)"))).toBe("Z.T @ Z / (X.shape[0] - 1)");
  });
  it("shows independent computations guarded by a branch, preserving original source relations", () => {
    const g = fixture(); g.blocks.push(block("if", "file", "condition"));
    g.nodes.push(node("predicate", "condition", "X.size > 0", "pred", "if"), node("entry", "entry", "true", "entry", "if"), node("one", "operation", "a = 1", "one", "if"), node("two", "operation", "b = 2", "two", "if"));
    g.edges.push(edge("guard", "predicate", "entry", "control", "true" as never), edge("first", "entry", "one", "control"), edge("next", "one", "two", "control"));
    const p = projectDisplayGraph(g, new Set(), "code");
    expect(p.edges.filter(e => e.source === "predicate").map(e => e.target).sort()).toEqual(["one", "two"]);
    expect(p.edges.some(e => e.source === "one" && e.target === "two")).toBe(false);
    expect(p.edges.filter(e => e.source === "predicate").every(e => e.displayLabel === "true")).toBe(true);
  });
  it("uses compact English captions and retains exact non-English source only in the source/details surface", () => {
    expect(graphCaption(node("n", "operation", "scores = Z @ components[:, -3:]"))).toBe("scores");
    expect(graphCaption(node("n", "operation", "print(结果)"))).toBe("print");
    expect(graphCaption(node("n", "condition", "if 结果 > 0"))).not.toMatch(/[\u3400-\u9fff]/);
  });
});
