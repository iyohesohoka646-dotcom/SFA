import { describe, expect, it } from "vitest";
import { initialCollapsed, projectGraph, graphNodeTarget, selectedGraphIds } from "../src/research/workspace/graph-projection";
import { buildObjectTree, logicalObjectGroups, selectionObjectIds } from "../src/research/workspace/objectTree";
import { choose, selectionKey } from "../src/research/workspace/selection";
import type { AnalysisDocument, GraphBlock, GraphEdge, GraphNode, SemanticGraph, TargetRef } from "../src/research/workspace/generated";

const block = (id: string, parent_id: string | null = null, kind: GraphBlock["kind"] = "function"): GraphBlock => ({
  id, parent_id, kind, label: id, logical_key: id, source: null, source_object_id: null, members: [], runtime_coverage: "supported",
});
const node = (id: string, block_id: string, kind: GraphNode["kind"] = "operation", label = id): GraphNode => ({
  id, block_id, kind, label, logical_key: id, source: null, source_object_id: null, ports: [], version: 1,
});
const edge = (id: string, source: string, target: string, kind: GraphEdge["kind"], label = "", branch: GraphEdge["branch"] = null): GraphEdge => ({
  id, source, target, kind, label, branch, source_port: null, target_port: null, original_ids: [id], count: 1, provenance: "inferred",
});
const fixture = (): SemanticGraph => ({
  protocol_version: 3, source_digest: "digest", roots: ["file"], coverage: [], omitted_count: 0,
  blocks: [block("file", null, "file"), block("fn", "file"), block("if", "fn", "condition"), block("loop", "fn", "loop")],
  nodes: [node("outer", "file"), node("condition", "if", "condition", "score > 0"), node("inside", "if"), node("counter", "loop", "loop_header", "for row in data")],
  edges: [edge("yes", "condition", "outer", "control", "true", "true"), edge("no", "condition", "outer", "control", "false", "false"), edge("x", "inside", "outer", "data", "samples"), edge("y", "inside", "outer", "data", "weights"), edge("repeat", "outer", "counter", "backedge", "next iteration")],
});

// Same semantic shape as serve_research_test.py's 1000 X{i} assignments:
// one file, 1000 operations, 1000 data values, containment/data/control edges.
const flatAssignments = (count: number): SemanticGraph => {
  const graph = { ...fixture(), blocks: [block("file", null, "file")], nodes: [] as GraphNode[], edges: [] as GraphEdge[] };
  for (let i = 0; i < count; i++) {
    const op = node("op" + i, "file", "operation", `X${i} = ${i}`), value = node("value" + i, "file", "data", "X" + i);
    op.ports = [{ id: `${op.id}:output:X${i}`, name: "X" + i, direction: "output" }];
    value.ports = [{ id: `${value.id}:input:X${i}`, name: "X" + i, direction: "input" }];
    graph.nodes.push(op, value);
    graph.edges.push(edge("contain-op" + i, "file", op.id, "contains"), edge("contain-value" + i, "file", value.id, "contains"),
      { ...edge("produce" + i, op.id, value.id, "data", "X" + i), source_port: op.ports[0].id, target_port: value.ports[0].id });
    if (i) graph.edges.push(edge("control" + i, "op" + (i - 1), op.id, "control"));
  }
  graph.blocks[0].members = graph.nodes.map(n => n.id);
  return graph;
};

describe("hierarchical graph projection", () => {
  it("keeps the highest root expanded and defaults every descendant block to collapsed even for small graphs", () => {
    const graph = fixture(), closed = initialCollapsed(graph, new Set());
    expect([...closed].sort()).toEqual(["fn", "if", "loop"]);
    const p = projectGraph(graph, closed, "structure");
    expect(p.nodes.map(n => n.id)).toEqual(["file", "fn", "outer"]);
    expect(p.omitted).toBeGreaterThan(0);
  });

  it("opens one level without opening nested descendants and adapts when a new block is analyzed", () => {
    const graph = fixture();
    graph.blocks.push(block("new-function", "file"));
    const closed = initialCollapsed(graph, new Set(["open:fn"]));
    expect(closed.has("fn")).toBe(false);
    expect(closed.has("if")).toBe(true);
    expect(closed.has("new-function")).toBe(true);
  });

  it("folds the actual thousand-assignment shape into one file with all 2000 units explicitly counted", () => {
    const graph = flatAssignments(1000);
    expect(graph.nodes).toHaveLength(2000); expect(graph.edges).toHaveLength(3999);
    const closed = initialCollapsed(graph, new Set());
    expect(closed.has("file")).toBe(true);
    for (const view of ["structure", "data", "execution"] as const) {
      const p = projectGraph(graph, closed, view);
      expect(p.nodes.map(n => n.id)).toEqual(["file"]);
      expect(p.nodes[0].collapsed).toBe(true);
      expect(p.omitted).toBe(2000); expect(p.viewOmitted).toBe(0);
      expect(p.edges).toHaveLength(0);
    }
    const opened = initialCollapsed(graph, new Set(["file", "open:file"]));
    expect(opened.has("file")).toBe(false);
    expect(projectGraph(graph, opened, "structure").nodes).toHaveLength(1001);
    const data = projectGraph(graph, opened, "data");
    expect(data.nodes).toHaveLength(2001); expect(data.omitted).toBe(0);
    expect(data.edges).toHaveLength(1999);
  });

  it("only applies the fallback above 160 default structure units and preserves intentional descendant expansion", () => {
    expect(initialCollapsed(flatAssignments(159), new Set()).has("file")).toBe(false);
    expect(initialCollapsed(flatAssignments(160), new Set()).has("file")).toBe(true);
    const nested = flatAssignments(1000);
    nested.blocks.push(block("fn", "file")); nested.nodes.forEach(n => { n.block_id = "fn"; });
    const normal = initialCollapsed(nested, new Set());
    expect([...normal]).toEqual(["fn"]);
    expect(projectGraph(nested, normal, "structure").nodes.map(n => n.id)).toEqual(["file", "fn"]);
    const openedChild = initialCollapsed(nested, new Set(["open:fn"]));
    expect(openedChild.has("file")).toBe(false); expect(openedChild.has("fn")).toBe(false);
    const scoped = initialCollapsed(nested, new Set(), "fn");
    expect(scoped.has("fn")).toBe(true);
    expect(projectGraph(nested, scoped, "structure", "fn")).toMatchObject({ omitted: 2000 });
    expect(projectGraph(nested, scoped, "structure", "fn").nodes.map(n => n.id)).toEqual(["fn"]);
    expect(initialCollapsed(nested, new Set(["open:fn"]), "fn").has("fn")).toBe(false);
  });

  it("retains each cross-root relationship when an oversized file is automatically folded", () => {
    const graph = flatAssignments(1000);
    graph.blocks.push(block("peer", null, "file")); graph.nodes.push(node("consume", "peer"));
    graph.edges.push(edge("outside", "value999", "consume", "data", "X999"));
    const p = projectGraph(graph, initialCollapsed(graph, new Set()), "structure");
    expect(p.nodes.map(n => n.id)).toEqual(["file", "peer", "consume"]);
    expect(p.omitted).toBe(2000);
    expect(p.edges).toHaveLength(1);
    expect(p.edges[0]).toMatchObject({ source: "file", target: "consume", kind: "data", original_ids: ["outside"], displayLabel: "X999", source_boundary: true });
    expect(p.nodes[0].handles[0]).toMatchObject({ name: "X999", boundary: true, original_ids: ["outside"] });
  });

  it("uses the entered block as the expanded root and excludes ancestors from that projection", () => {
    const graph = fixture(), closed = initialCollapsed(graph, new Set(), "fn");
    expect([...closed].sort()).toEqual(["if", "loop"]);
    const p = projectGraph(graph, closed, "structure", "fn");
    expect(p.nodes.map(n => n.id)).toEqual(["fn", "if", "loop"]);
    expect(p.nodes[0].parent_id).toBeNull();
  });

  it("keeps different boundary variables and branch conditions on different handles with their references", () => {
    const p = projectGraph(fixture(), new Set(["fn"]), "structure");
    expect(p.edges).toHaveLength(5);
    const [yes, no] = [p.edges.find(e => e.branch === "true")!, p.edges.find(e => e.branch === "false")!];
    expect(yes.displayLabel).toContain("score > 0");
    expect(yes.displayLabel).toContain("真");
    expect(no.displayLabel).toContain("假");
    expect(yes.source_port).not.toBe(no.source_port);
    const variables = p.edges.filter(e => e.kind === "data");
    expect(variables.map(e => e.displayLabel).sort()).toEqual(["samples", "weights"]);
    expect(new Set(variables.map(e => e.source_port)).size).toBe(2);
    const plate = p.nodes.find(n => n.id === "fn")!;
    expect(plate.handles.filter(h => h.direction === "output")).toHaveLength(4);
    expect(p.edges.flatMap(e => e.original_ids).sort()).toEqual(["no", "repeat", "x", "y", "yes"]);
    expect(p.edges.every(e => p.nodes.some(n => n.id === e.source && n.handles.some(h => h.id === e.source_port)) && p.nodes.some(n => n.id === e.target && n.handles.some(h => h.id === e.target_port)))).toBe(true);
  });

  it("adds data nodes only in the data view while retaining their computation dependency in structure", () => {
    const graph = fixture();
    graph.nodes = [node("a", "file"), node("value", "file", "data", "matrix"), node("b", "file")];
    graph.edges = [edge("produce", "a", "value", "data", "matrix"), edge("consume", "value", "b", "data", "matrix")];
    const structure = projectGraph(graph, new Set(), "structure"), data = projectGraph(graph, new Set(), "data");
    expect(structure.nodes.some(n => n.id === "value")).toBe(false);
    expect(data.nodes.some(n => n.id === "value")).toBe(true);
    expect(structure.edges).toHaveLength(1);
    expect(structure.edges[0]).toMatchObject({ source: "a", target: "b", original_ids: ["produce", "consume"] });
  });

  it("produces the same boundary identities and labels when edges arrive in a different order", () => {
    const a = fixture(), b = fixture(); b.edges.reverse();
    const summarize = (graph: SemanticGraph) => projectGraph(graph, new Set(["fn"]), "structure").edges.map(e => ({ id: e.id, source_port: e.source_port, target_port: e.target_port, displayLabel: e.displayLabel, original_ids: e.original_ids })).sort((x, y) => x.id.localeCompare(y.id));
    expect(summarize(a)).toEqual(summarize(b));
  });

  it("shares global/nonlocal alias selections with the tree while exact evidence remains one occurrence", () => {
    const graph = fixture();
    graph.nodes = [
      { ...node("global", "file", "data", "x"), logical_key: "file::<module>::x", source_object_id: "global-definition" },
      { ...node("write", "fn", "data", "x"), logical_key: "file::setter::x", source_object_id: "alias-write" },
    ];
    graph.edges = [];
    const analysis = { id: "analysis", path: "fixture.py", source_digest: "digest", graph, objects: graph.nodes.map((n, i) => ({ id: n.source_object_id!, logical_key: n.logical_key, path: "fixture.py", name: "x", scope: i ? "setter" : "<module>", qualname: i ? "setter.x" : "x", kind: "variable", block_id: n.block_id, line: i + 1, end_line: i + 1, column: 0, end_column: 1, source_digest: "digest", code: "x", inputs: [], mutation: false, provenance: "inferred" })), relations: [], diagnostics: [], imported_at: "", protocol_version: 3 } as AnalysisDocument;
    const metadata = [{ logical_key: "file::<module>::x", logical_keys: graph.nodes.map(n => n.logical_key), object_ids: graph.nodes.map(n => n.source_object_id!), name: "x", scope: "<module>", occurrences: [] }];
    const group = logicalObjectGroups(analysis, metadata)[0];
    expect(group.objectIds).toEqual(["global-definition", "alias-write"]);
    const targets = new Map(projectGraph(graph, new Set(), "data").nodes.filter(n => !n.plate).map(n => [n.id, graphNodeTarget(n, analysis.id, group.objects[1], { id: "latest", logical_key: group.logicalKey, run_id: "run" })]));
    expect(targets.get("write")!.logical_key).toBe("file::<module>::x");
    const originals = new Map(graph.nodes.map(n => [n.id, n.source_object_id]));
    const selected = { targets: [targets.get("write")!], anchor: null };
    expect([...selectedGraphIds(targets, selected, selectionObjectIds(analysis, selected.targets, metadata), originals)].sort()).toEqual(["global", "write"]);
    const exact = { targets: [{ ...selected.targets[0], exact_evidence: true }], anchor: null };
    expect([...selectedGraphIds(targets, exact, selectionObjectIds(analysis, exact.targets, metadata), originals)]).toEqual(["write"]);
  });

  it("submits canonical keys for variables in redefined same-name functions while retaining distinct scope identity", () => {
    const graph = fixture(), key = "fixture.py::f::x";
    graph.blocks = [block("file", null, "file"), { ...block("first-f", "file"), label: "f" }, { ...block("second-f", "file"), label: "f" }];
    graph.nodes = [
      ...["a1", "a2"].map(id => ({ ...node(id, "first-f", "data", "x"), logical_key: key, source_object_id: id })),
      ...["b1", "b2"].map(id => ({ ...node(id, "second-f", "data", "x"), logical_key: key, source_object_id: id })),
    ];
    graph.edges = [];
    const analysis = { id: "analysis", path: "fixture.py", source_digest: "digest", graph, objects: graph.nodes.map((n, i) => ({ id: n.id, logical_key: key, path: "fixture.py", name: "x", scope: "f", qualname: "f.x", kind: "variable", block_id: n.block_id, line: i + 2, end_line: i + 2, column: 0, end_column: 1, source_digest: "digest", code: "x", inputs: [], mutation: false, provenance: "inferred" })), relations: [], diagnostics: [], imported_at: "", protocol_version: 3 } as AnalysisDocument;
    const groups = logicalObjectGroups(analysis);
    expect(groups).toHaveLength(2);
    expect(groups.every(g => g.logicalKey.includes("@scope:"))).toBe(true);
    const projected = projectGraph(graph, new Set(), "data");
    const targets = new Map(projected.nodes.filter(n => !n.plate).map(n => {
      const group = groups.find(g => g.objectIds.includes(n.source_object_id!))!;
      return [n.id, graphNodeTarget(n, analysis.id, group.objects[0])] as const;
    }));
    expect([...targets.values()].every(t => t.logical_key === key)).toBe(true);
    expect(selectionKey(targets.get("a1")!)).not.toBe(selectionKey(targets.get("b1")!));
    const selected = { targets: [targets.get("a1")!], anchor: null };
    const originals = new Map(graph.nodes.map(n => [n.id, n.source_object_id]));
    expect([...selectedGraphIds(targets, selected, selectionObjectIds(analysis, selected.targets), originals)].sort()).toEqual(["a1", "a2"]);
    for (const [scope, graphId] of [["first-f", "a1"], ["second-f", "b1"]]) {
      const treeRow = buildObjectTree(analysis, [], scope, new Set([scope])).find(row => row.rowKind === "variable")!;
      expect(selectionKey(treeRow.target)).toBe(selectionKey(targets.get(graphId)!));
      const state = { targets: [targets.get(graphId)!], anchor: null };
      expect(choose(state, treeRow.target, [...targets.values()], { toggle: true }).targets).toEqual([]);
    }
  });
});
