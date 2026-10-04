import { describe, expect, it } from "vitest";
import { createState } from "../src/research/state";
import { describeGraphData, executionOverlay } from "../src/research/workspace/graph-execution";
import { projectGraph } from "../src/research/workspace/graph-projection";
import type { ControlSummary, SemanticGraph } from "../src/research/workspace/generated";
import type { SnapshotRef, ValueDescriptor } from "../src/research/generated";

const source = { path: "analysis.py", digest: "current", line: 2, end_line: 2, column: 0, end_column: 8, qualname: "", code: "if x > 0:" };
const graph: SemanticGraph = {
  protocol_version: 3, source_digest: "current", roots: ["file"], omitted_count: 0, coverage: [],
  blocks: [{ id: "file", kind: "file", label: "analysis.py", logical_key: "file", source: null, parent_id: null, source_object_id: null, members: [], runtime_coverage: "supported" }, { id: "branch", kind: "condition", label: "if x > 0", logical_key: "branch", source, parent_id: "file", source_object_id: null, members: [], runtime_coverage: "supported" }],
  nodes: [{ id: "test", kind: "condition", label: "x > 0", logical_key: "test", block_id: "branch", source, source_object_id: null, ports: [], version: 1 }, { id: "yes", kind: "operation", label: "output = x", logical_key: "yes", block_id: "branch", source: { ...source, line: 3, end_line: 3 }, source_object_id: null, ports: [], version: 1 }, { id: "no", kind: "operation", label: "output = 0", logical_key: "no", block_id: "branch", source: { ...source, line: 5, end_line: 5 }, source_object_id: null, ports: [], version: 1 }],
  edges: ["true", "false"].map((branch, i) => ({ id: "edge" + i, source: "test", target: i ? "no" : "yes", kind: "control", label: branch, branch: branch as "true" | "false", source_port: null, target_port: null, provenance: "inferred", original_ids: ["edge" + i], count: 1 })),
};
const summary = (complete: boolean): ControlSummary => ({ node_id: "branch", kind: "branch", source, true_count: 3, false_count: 0, body_entries: 0, activations: 0, natural_exits: 0, break_exits: 0, nonlocal_exits: 0, exception_exits: 0, complete, revision: 1, activation_samples: [], omitted_activations: 0, total_ms: 0, minimum_ms: 0, maximum_ms: 0, timing: "" });

describe("evidence-led graph execution", () => {
  it("does not invent completed nodes or traveled paths when no run is attached", () => {
    const projection = projectGraph(graph, new Set(), "execution");
    const overlay = executionOverlay(graph, projection, createState(""), []);
    expect(overlay.hasEvidence).toBe(false);
    expect([...overlay.nodes.values()].every(n => n.status === "unobserved" && n.count === undefined)).toBe(true);
    expect([...overlay.edges.values()].every(e => e.status === "unobserved" && e.count === undefined)).toBe(true);
  });

  it("uses real branch counters and distinguishes complete zero from an incomplete observation", () => {
    const projection = projectGraph(graph, new Set(), "execution"), state = createState("run");
    const complete = executionOverlay(graph, projection, state, [summary(true)]);
    expect(complete.hasEvidence).toBe(true);
    expect(complete.nodes.get("branch")).toMatchObject({ count: 3, complete: true });
    expect(complete.edges.get(projection.edges.find(e => e.branch === "true")!.id)).toMatchObject({ status: "observed", count: 3, complete: true });
    expect(complete.edges.get(projection.edges.find(e => e.branch === "false")!.id)).toMatchObject({ status: "not_taken", count: 0, complete: true });
    const partial = executionOverlay(graph, projection, state, [summary(false)]);
    expect(partial.edges.get(projection.edges.find(e => e.branch === "false")!.id)).toMatchObject({ status: "unobserved", count: 0, complete: false });
  });

  it("rejects previous-source execution records", () => {
    const state = createState("run");
    state.operations.set("old", { id: "old", run_id: "run", label: "output = x", source: { ...source, digest: "old", line: 3 }, scope_id: "main", iteration: 0, input_snapshots: [], output_snapshots: [], kind: "assignment", status: "completed", duration_ms: 1, parameters: {}, provenance: "observed" });
    const projection = projectGraph(graph, new Set(), "execution");
    const overlay = executionOverlay(graph, projection, state, [{ ...summary(true), source: { ...source, digest: "old" } }]);
    expect(overlay.hasEvidence).toBe(false);
    expect(overlay.nodes.get("yes")!.status).toBe("unobserved");
  });

  it.each(["inferred", "unknown"] as const)("shows captured %s values and completed statements without upgrading inferred dependencies", provenance => {
    const outputSource = { ...source, line: 3, end_line: 3 };
    const fixture: SemanticGraph = { ...graph, nodes: [...graph.nodes, { ...graph.nodes[1], id: "value", kind: "data", logical_key: "output", label: "output" }],
      edges: [{ ...graph.edges[0], id: "lineage", source: "yes", target: "value", kind: "data", branch: null, original_ids: ["lineage"] }] };
    const state = createState("run");
    const value: SnapshotRef = { id: "captured", run_id: "run", binding_id: "main:output", logical_key: "output", scope_id: "main", name: "output", version: 1,
      source: outputSource, observed_at: "2026-10-04T00:00:00Z", provenance, coverage: { mode: "auto", binding: "observed", dependency: "inferred" },
      descriptor: { schema_version: 1, kind: "scalar", backend: "python", type_name: "int", shape: [], dtype: null, nbytes: null, device: null, axes: [], unit: null, capabilities: [], metadata: {} },
      operation_id: "step", parents: [], fidelity: "exact", sample: {}, statistics: {}, truncation: [], redacted: [], artifact_ref: null };
    state.snapshots.set(value.id, value);
    state.operations.set("step", { id: "step", run_id: "run", label: "output = x", source: outputSource, scope_id: "main", iteration: 1,
      input_snapshots: [], output_snapshots: [value.id], kind: "assignment", status: "completed", duration_ms: 1, parameters: { timing: "statement-only" }, provenance: "inferred" });
    const projection = projectGraph(fixture, new Set(), "data"), overlay = executionOverlay(fixture, projection, state, []);
    expect(overlay.hasEvidence).toBe(true);
    expect(overlay.nodes.get("yes")).toMatchObject({ status: "completed", count: 1 });
    expect(overlay.nodes.get("value")).toMatchObject({ status: "observed", count: 1 });
    expect(overlay.edges.get(projection.edges[0].id)).toMatchObject({ status: "unobserved" });
    expect(overlay.edges.get(projection.edges[0].id)?.count).toBeUndefined();
  });

  it("does not assign aggregate callee activations to a particular static call position", () => {
    const fixture: SemanticGraph = { ...graph, blocks: [...graph.blocks, { ...graph.blocks[1], id: "callee", kind: "function", label: "normalize" }], nodes: [...graph.nodes, { ...graph.nodes[1], id: "call-site", kind: "call", label: "normalize(x)" }], edges: [...graph.edges, { ...graph.edges[0], id: "call-edge", source: "call-site", target: "callee", kind: "call", label: "normalize", branch: null, original_ids: ["call-edge"] }] };
    const projection = projectGraph(fixture, new Set(), "execution");
    const overlay = executionOverlay(fixture, projection, createState("run"), [{ ...summary(true), node_id: "callee", kind: "function", activations: 2 }]);
    expect(overlay.nodes.get("callee")).toMatchObject({ status: "observed", count: 2 });
    const call = overlay.edges.get(projection.edges.find(e => e.kind === "call")!.id)!;
    expect(call.status).toBe("unobserved");
    expect(call.count).toBeUndefined();
    expect(call.detail).toContain("累计激活 2 次");
  });

  it("labels observed data with its real shape and keeps static unknown values explicit", () => {
    const descriptor = (kind: string, shape: number[] | null): ValueDescriptor => ({ schema_version: 1, kind, shape, backend: "numpy", type_name: "ndarray", dtype: "float64", nbytes: 48, device: null, axes: [], unit: null, capabilities: [], metadata: {} });
    expect(describeGraphData(descriptor("array", [3, 2]))).toMatchObject({ kind: "matrix", label: "矩阵", detail: "3 × 2 · float64" });
    expect(describeGraphData(descriptor("scalar", []))).toMatchObject({ kind: "scalar", label: "标量" });
    expect(describeGraphData(descriptor("table", [3, 2]))).toMatchObject({ kind: "table", label: "表格" });
    expect(describeGraphData(undefined)).toMatchObject({ kind: "unknown", label: "数据", detail: "未观测类型" });
  });
});
