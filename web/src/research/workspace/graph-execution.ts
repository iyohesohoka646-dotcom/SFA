import type { OperationRecord, ValueDescriptor } from "../generated";
import type { ResearchState } from "../state";
import type { ControlSummary, GraphEdge, GraphNode, SemanticGraph, SourceRef } from "./generated";
import type { GraphProjection, ProjectionNode } from "./graph-projection";

export interface GraphDataDescription { kind: string; label: string; detail: string }
export function describeGraphData(value?: ValueDescriptor): GraphDataDescription {
  if (!value) return { kind: "unknown", label: "数据", detail: "未观测类型" };
  const type = (value.kind + " " + value.type_name).toLowerCase(), shape = value.shape;
  let kind = "object", label = "对象";
  if (/table|dataframe|series/.test(type)) { kind = "table"; label = "表格"; }
  else if (/scalar|number|boolean|float|integer/.test(type) || shape?.length === 0) { kind = "scalar"; label = "标量"; }
  else if (/str|text/.test(type)) { kind = "text"; label = "文本"; }
  else if (shape?.length === 1) { kind = "vector"; label = "向量"; }
  else if (shape?.length === 2) { kind = "matrix"; label = "矩阵"; }
  else if (shape && shape.length > 2) { kind = "tensor"; label = "张量"; }
  else if (/list|tuple|sequence/.test(type)) { kind = "sequence"; label = "序列"; }
  else if (/dict|mapping/.test(type)) { kind = "mapping"; label = "映射"; }
  return { kind, label, detail: [shape?.length ? shape.join(" × ") : "", value.dtype ?? value.type_name].filter(Boolean).join(" · ") };
}

export interface NodeExecution {
  status: string;
  count?: number;
  complete?: boolean;
  unit?: string;
  detail?: string;
}
export interface EdgeExecution {
  status: "observed" | "not_taken" | "unobserved";
  count?: number;
  complete?: boolean;
  detail?: string;
}
export interface GraphExecution {
  hasEvidence: boolean;
  nodes: Map<string, NodeExecution>;
  edges: Map<string, EdgeExecution>;
}

const pathKey = (path: string) => path.replace(/\\/g, "/");
const atSource = (a: SourceRef | null, b: SourceRef | null) => !!a && !!b && pathKey(a.path) === pathKey(b.path) && a.line === b.line;
const observed = (count: number, complete: boolean): EdgeExecution => ({ status: count > 0 ? "observed" : complete ? "not_taken" : "unobserved", count, complete });

/** Counts are read from runtime receipts. Missing or truncated evidence stays unknown. */
export function executionOverlay(graph: SemanticGraph, projection: GraphProjection, state: ResearchState, summaries: ControlSummary[]): GraphExecution {
  const staticNodes = new Map(graph.nodes.map(n => [n.id, n])), known = new Set([...graph.blocks, ...graph.nodes].map(n => n.id));
  const current = (source: SourceRef | null) => !!state.runId && !!source && source.digest === graph.source_digest;
  // These are runtime receipts. Their provenance describes the source/lineage
  // mapping, not whether the statement ran or the value was captured.
  const operations = [...state.operations.values()].filter(o => o.run_id === state.runId && current(o.source));
  const snapshots = [...state.snapshots.values()].filter(s => s.run_id === state.runId && current(s.source));
  const verifiedSnapshots = snapshots.filter(s => s.provenance === "observed");
  const values = new Map(verifiedSnapshots.map(s => [s.id, s]));
  const controls = new Map(summaries.filter(c => !!state.runId && known.has(c.node_id) && (!c.source || current(c.source))).map(c => [c.node_id, c]));
  const recordsFor = (n?: GraphNode) => n ? operations.filter(o => atSource(o.source, n.source)) : [];
  const valuesFor = (n?: GraphNode) => n ? snapshots.filter(s => s.logical_key === n.logical_key && atSource(s.source, n.source)) : [];
  const controlFor = (id: string) => controls.get(id) ?? controls.get(staticNodes.get(id)?.block_id ?? "");
  const nodeReceipt = (n: ProjectionNode): NodeExecution => {
    const c = controls.get(n.id) ?? (!n.plate && ["condition", "loop_header"].includes(n.kind) ? controls.get((n as GraphNode).block_id) : undefined);
    if (c) {
      const count = c.kind === "branch" ? c.true_count + c.false_count : c.kind === "loop" ? c.body_entries : c.activations;
      return { status: c.exception_exits > 0 ? "error" : count > 0 ? "observed" : c.complete ? "not_taken" : "unobserved", count, complete: c.complete, unit: "次", detail: c.kind === "branch" ? `真 ${c.true_count} / 假 ${c.false_count}` : c.kind === "loop" ? `自然退出 ${c.natural_exits} / break ${c.break_exits}` : c.total_ms > 0 ? `累计 ${c.total_ms.toFixed(1)} ms` : undefined };
    }
    if (!n.plate && (n.kind === "data" || n.kind === "parameter")) {
      const observedValues = valuesFor(n as GraphNode);
      return observedValues.length ? { status: "observed", count: observedValues.length, complete: false, unit: "个值" } : { status: "unobserved" };
    }
    if (!n.plate && ["operation", "call", "return"].includes(n.kind)) {
      const records = recordsFor(n as GraphNode);
      return records.length ? { status: records.at(-1)!.status, count: records.length, complete: false, unit: "条记录" } : { status: "unobserved" };
    }
    if (n.plate && n.source) {
      const records = operations.filter(o => pathKey(o.source!.path) === pathKey(n.source!.path) && o.source!.line >= n.source!.line && o.source!.line <= n.source!.end_line);
      if (records.length) return { status: records.some(o => ["failed", "error"].includes(o.status)) ? "error" : "observed", count: records.length, complete: false, unit: "条记录" };
    }
    return { status: "unobserved" };
  };

  const hasValue = (id: string, n?: GraphNode) => {
    const s = values.get(id);
    return !!s && !!n && s.logical_key === n.logical_key && (n.kind === "parameter" || atSource(s.source, n.source));
  };
  const lineageReceipt = (edge: GraphEdge): EdgeExecution | undefined => {
    const a = staticNodes.get(edge.source), b = staticNodes.get(edge.target);
    if (!a || !b || !["data", "argument", "return", "merge"].includes(edge.kind)) return;
    let records: OperationRecord[] = [];
    if (["data", "parameter"].includes(a.kind)) records = recordsFor(b).filter(o => o.provenance === "observed" && o.input_snapshots.some(id => hasValue(id, a)));
    else if (["data", "parameter"].includes(b.kind)) records = recordsFor(a).filter(o => o.provenance === "observed" && o.output_snapshots.some(id => hasValue(id, b)));
    if (records.length) return observed(records.length, false);
    const targets = valuesFor(b).filter(s => s.provenance === "observed"), sources = new Set(valuesFor(a).filter(s => s.provenance === "observed").map(s => s.id));
    const links = targets.filter(s => s.parents.some(id => sources.has(id)));
    return links.length ? observed(links.length, false) : undefined;
  };
  const edgeReceipt = (e: GraphEdge): EdgeExecution => {
    const c = controlFor(e.source);
    if (c && e.branch) {
      if (c.kind === "branch" && (e.branch === "true" || e.branch === "false")) return observed(e.branch === "true" ? c.true_count : c.false_count, c.complete);
      if (c.kind === "loop" && e.branch === "body") return observed(c.body_entries, c.complete);
      if (c.kind === "loop" && e.branch === "exit") return observed(c.natural_exits, c.complete);
      if (e.branch === "exception") return observed(c.exception_exits, c.complete);
    }
    const lineage = lineageReceipt(e);
    if (lineage) return lineage;
    if (e.kind === "call") {
      const callee = controls.get(e.target);
      if (callee?.kind === "function") return { status: "unobserved", detail: `目标函数累计激活 ${callee.activations} 次；该调用位置没有独立路径计数` };
    }
    return { status: "unobserved" };
  };
  const originals = new Map(graph.edges.map(e => [e.id, e]));
  const edges = new Map(projection.edges.map(e => {
    const receipts = e.original_ids.flatMap(id => originals.has(id) ? [edgeReceipt(originals.get(id)!)] : []);
    const withCount = receipts.filter(r => r.count !== undefined);
    const receipt = receipts.length === 1 ? receipts[0] : receipts.length && withCount.length === receipts.length ? observed(Math.min(...withCount.map(r => r.count!)), withCount.every(r => r.complete)) : { status: "unobserved" as const };
    return [e.id, receipt] as const;
  }));
  return { hasEvidence: !!(operations.length || snapshots.length || controls.size), nodes: new Map(projection.nodes.map(n => [n.id, nodeReceipt(n)])), edges };
}
