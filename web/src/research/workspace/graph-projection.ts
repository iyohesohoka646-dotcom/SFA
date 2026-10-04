import type { GraphBlock, GraphEdge, GraphNode, GraphPort, SemanticGraph, SourceObject, TargetRef } from "./generated";
import type { SnapshotRef } from "../generated";
import { selectionKey, type Selection } from "./selection";

export type GraphView = "structure" | "data" | "execution";
export interface GraphHandle {
  id: string;
  name: string;
  direction: GraphPort["direction"];
  kind: GraphEdge["kind"];
  boundary: boolean;
  original_ids: string[];
  y?: number;
  x?: number;
  side?: "WEST" | "EAST" | "NORTH" | "SOUTH";
}
export type ProjectionNode = (GraphNode | GraphBlock) & {
  parent_id: string | null;
  plate: boolean;
  collapsed: boolean;
  handles: GraphHandle[];
  original_node_ids?: string[];
  original_object_ids?: string[];
  expression?: string;
};
export type ProjectionEdge = GraphEdge & {
  displayLabel: string;
  source_boundary: boolean;
  target_boundary: boolean;
};
export interface GraphProjection {
  nodes: ProjectionNode[];
  edges: ProjectionEdge[];
  omitted: number;
  viewOmitted: number;
}

/** Selection/probe targets use protocol keys; @scope keys belong only to grouping. */
export function graphNodeTarget(node: ProjectionNode, analysisId?: string, origin?: SourceObject, snapshot?: Pick<SnapshotRef, "logical_key" | "id" | "run_id">): TargetRef {
  const data = node as GraphNode;
  return {
    kind: node.plate ? ["function", "class"].includes(node.kind) ? "function" : node.kind === "file" ? "file" : "control" : ["data", "parameter"].includes(node.kind) ? "data" : "operation",
    logical_key: snapshot?.logical_key || origin?.logical_key || node.logical_key || node.id,
    block_id: node.plate ? node.id : origin?.block_id ?? data.block_id,
    object_id: origin?.id ?? node.source_object_id,
    snapshot_id: snapshot?.id ?? null,
    run_id: snapshot?.run_id ?? null,
    analysis_id: analysisId ?? null,
    exact_evidence: false,
  };
}

function graphParents(graph: SemanticGraph) {
  return new Map<string, string | null>([
    ...graph.blocks.map(b => [b.id, b.parent_id] as const),
    ...graph.nodes.map(n => [n.id, n.block_id] as const),
  ]);
}
function isUnder(id: string, root: string, parents: Map<string, string | null>) {
  const seen = new Set<string>();
  while (id && !seen.has(id)) {
    if (id === root) return true;
    seen.add(id);
    id = parents.get(id) ?? "";
  }
  return false;
}

/** Roots open above folded descendants, except an oversized flat root; explicit opens always win. */
export function initialCollapsed(graph: SemanticGraph, overrides: Set<string>, scope: string | null = null) {
  const parents = graphParents(graph), known = new Set(graph.blocks.map(b => b.id));
  const roots = new Set(scope && known.has(scope) ? [scope] : graph.blocks.filter(b => !b.parent_id || !known.has(b.parent_id)).map(b => b.id));
  // Count each root's default structure surface: the plate, immediate folded
  // blocks, and direct computations. A user opening a descendant must not
  // unexpectedly close its parent. This changes only the initial fold state;
  // projection still retains every hidden unit and explicit expansion is uncapped.
  const surface = new Map([...roots].map(id => [id, 1]));
  for (const block of graph.blocks) if (block.parent_id && roots.has(block.parent_id)) surface.set(block.parent_id, surface.get(block.parent_id)! + 1);
  for (const node of graph.nodes) if (roots.has(node.block_id) && node.kind !== "data" && node.kind !== "parameter") surface.set(node.block_id, surface.get(node.block_id)! + 1);
  const result = new Set<string>();
  for (const block of graph.blocks) {
    if (scope && !isUnder(block.id, scope, parents)) continue;
    if ((overrides.has(block.id) || !roots.has(block.id) || (surface.get(block.id) ?? 0) > 160) && !overrides.has("open:" + block.id)) result.add(block.id);
  }
  return result;
}

const concise = (text: string, maximum = 34) => text.replace(/\s+/g, " ").trim().length > maximum ? text.replace(/\s+/g, " ").trim().slice(0, maximum - 1) + "…" : text.replace(/\s+/g, " ").trim();
export function relationshipLabel(edge: GraphEdge, items: ReadonlyMap<string, GraphBlock | GraphNode>) {
  const source = items.get(edge.source), target = items.get(edge.target);
  const condition = source?.kind === "condition" || source?.kind === "loop_header" || source?.kind === "loop" ? concise(source.label, 26) : "";
  if (edge.branch === "true" || edge.branch === "false") return (condition ? condition + " · " : "条件 · ") + (edge.branch === "true" ? "真" : "假");
  if (edge.branch === "body") return (condition ? condition + " · " : "") + "循环体";
  if (edge.branch === "exit") return "退出循环";
  if (edge.branch === "exception") return "异常路径";
  const label = concise(edge.label);
  if (edge.kind === "call") return "调用 " + (label || concise(target?.label ?? "函数"));
  if (edge.kind === "argument") return "传入 " + (label || "参数");
  if (edge.kind === "return") return "返回 " + (label && label !== "result" ? label : "结果");
  if (edge.kind === "backedge") return label && label !== "next iteration" ? "回边 " + label : "下一轮";
  if (edge.kind === "merge") return "合流" + (label ? " " + label : "");
  if (edge.kind === "control") return label && !["true", "false", "body", "exit"].includes(label) ? label : "控制顺序";
  if (edge.kind === "block") return label || "块间关系";
  return label || concise((source?.kind === "data" ? source.label : target?.kind === "data" ? target.label : "数据"));
}

/** A fold changes endpoints, never the relation category, condition, or evidence references. */
export function projectGraph(graph: SemanticGraph, collapsed: Set<string>, view: GraphView, scope: string | null = null): GraphProjection {
  const parents = graphParents(graph), items = new Map<string, GraphBlock | GraphNode>([...graph.blocks, ...graph.nodes].map(n => [n.id, n]));
  const inScope = (id: string) => !scope || isUnder(id, scope, parents);
  const representative = (id: string) => {
    let result = id, current = parents.get(id);
    const seen = new Set<string>();
    while (current && !seen.has(current) && inScope(current)) {
      seen.add(current);
      if (collapsed.has(current)) result = current;
      current = parents.get(current);
    }
    return result;
  };
  const depth = (id: string) => {
    let n = 0, parent = parents.get(id); const seen = new Set<string>();
    while (parent && !seen.has(parent)) { seen.add(parent); n++; parent = parents.get(parent); }
    return n;
  };
  const blocks = graph.blocks.filter(b => inScope(b.id) && representative(b.id) === b.id).sort((a, b) => depth(a.id) - depth(b.id) || (a.source?.line ?? 0) - (b.source?.line ?? 0) || a.id.localeCompare(b.id));
  const viewHidden = new Set(graph.nodes.filter(n => inScope(n.id) && representative(n.id) === n.id && view !== "data" && (n.kind === "data" || n.kind === "parameter")).map(n => n.id));
  const nodes: ProjectionNode[] = [
    ...blocks.map(b => ({ ...b, parent_id: b.id === scope ? null : b.parent_id, plate: true, collapsed: collapsed.has(b.id), handles: [] })),
    ...graph.nodes.filter(n => inScope(n.id) && representative(n.id) === n.id && !viewHidden.has(n.id)).map(n => ({ ...n, parent_id: n.block_id, plate: false, collapsed: false, handles: n.ports.map(p => ({ ...p, kind: "data" as const, boundary: false, original_ids: [] })) })),
  ];
  const known = new Map(nodes.map(n => [n.id, n]));
  const lineage = new Set<GraphEdge["kind"]>(["data", "argument", "return", "merge", "backedge"]);
  const outgoing = new Map<string, GraphEdge[]>();
  const orderedEdges = [...graph.edges].sort((a, b) => a.id.localeCompare(b.id));
  for (const e of orderedEdges) if (lineage.has(e.kind)) outgoing.set(e.source, [...(outgoing.get(e.source) ?? []), e]);
  const candidates: GraphEdge[] = [];
  for (const first of orderedEdges) {
    if (first.kind === "contains" || !known.has(representative(first.source))) continue;
    const walk = (e: GraphEdge, seen: Set<string>) => {
      if (!viewHidden.has(e.target)) { candidates.push(e); return; }
      if (!lineage.has(e.kind) || seen.has(e.target)) return;
      const nextSeen = new Set(seen).add(e.target);
      for (const next of outgoing.get(e.target) ?? []) walk({
        ...next, id: e.id + ">" + next.id, source: e.source, source_port: e.source_port,
        kind: e.kind === "data" ? next.kind : e.kind, branch: e.branch ?? next.branch,
        label: e.label || next.label, provenance: e.provenance === next.provenance ? e.provenance : "inferred",
        original_ids: [...(e.original_ids.length ? e.original_ids : [e.id]), ...(next.original_ids.length ? next.original_ids : [next.id])],
      }, nextSeen);
    };
    walk(first, new Set());
  }
  const grouped = new Map<string, ProjectionEdge>();
  for (const e of candidates) {
    const source = representative(e.source), target = representative(e.target);
    if (!known.has(source) || !known.has(target) || (source === target && e.source !== e.target)) continue;
    // Include the original endpoints/ports and label so unrelated variables and
    // call sites do not become one anonymous connection at a collapsed plate.
    const signature = JSON.stringify([source, target, e.kind, e.branch, e.label, e.source, e.target, e.source_port, e.target_port, e.provenance]);
    const existing = grouped.get(signature);
    if (existing) {
      existing.count += e.count;
      existing.original_ids = [...new Set([...existing.original_ids, ...e.original_ids])];
      continue;
    }
    grouped.set(signature, {
      ...e, id: "relation:" + encodeURIComponent(signature), source, target,
      source_boundary: source !== e.source, target_boundary: target !== e.target,
      displayLabel: relationshipLabel(e, items), original_ids: [...(e.original_ids.length ? e.original_ids : [e.id])], count: e.count || 1,
    });
  }
  const edges = [...grouped.values()].sort((a, b) => a.id.localeCompare(b.id));
  const attach = (n: ProjectionNode, e: ProjectionEdge, direction: GraphPort["direction"]) => {
    const requested = direction === "input" ? e.target_port : e.source_port, boundary = direction === "input" ? e.target_boundary : e.source_boundary;
    const original = !boundary && !n.plate ? n.handles.find(h => h.id === requested && h.direction === direction) : undefined;
    if (original) { original.original_ids = [...new Set([...original.original_ids, ...e.original_ids])]; return original.id; }
    const id = direction + ":" + e.id;
    n.handles.push({ id, name: e.displayLabel, direction, kind: e.kind, boundary: true, original_ids: e.original_ids });
    return id;
  };
  for (const e of edges) {
    e.source_port = attach(known.get(e.source)!, e, "output");
    e.target_port = attach(known.get(e.target)!, e, "input");
  }
  return {
    nodes, edges,
    omitted: graph.nodes.filter(n => inScope(n.id) && representative(n.id) !== n.id).length + graph.blocks.filter(b => inScope(b.id) && representative(b.id) !== b.id).length,
    viewOmitted: viewHidden.size,
  };
}

export function selectedGraphIds(targets: ReadonlyMap<string, TargetRef>, selection: Selection, objectIds: ReadonlySet<string>, originalObjectIds?: ReadonlyMap<string, string | null>) {
  const selected = new Set<string>(), keys = new Set(selection.targets.filter(t => !t.exact_evidence).map(selectionKey));
  for (const [id, target] of targets) {
    const objectId = originalObjectIds?.has(id) ? originalObjectIds.get(id) : target.object_id;
    if (keys.has(selectionKey(target)) || (objectId && objectIds.has(objectId))) selected.add(id);
    if (selection.targets.some(t => t.exact_evidence && !t.object_id && t.snapshot_id && t.snapshot_id === target.snapshot_id && t.logical_key === target.logical_key)) selected.add(id);
  }
  return selected;
}
