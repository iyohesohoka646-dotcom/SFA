/** Compact display projections. The archived semantic graph remains unchanged. */
import type { AnalysisDocument, GraphBlock, GraphEdge, GraphNode, SemanticGraph } from "./generated";
import type { GraphHandle, GraphProjection, ProjectionEdge, ProjectionNode } from "./graph-projection";
import { logicalObjectGroups } from "./objectTree";
import type { OccurrenceGroup } from "./sourceOccurrences";

export type GraphMode = "code" | "data";
export const normalizeGraphMode = (value: unknown): GraphMode => value === "data" ? "data" : "code";
const short = (s: string) => s.replace(/\s+/g, " ").trim();
const latin = (s: string, fallback: string) => /[\u3400-\u9fff]/.test(s) ? fallback : short(s);
const values = new Set(["data", "parameter"]);
const containers = new Set(["file", "function", "class", "folder", "project"]);

export function graphCaption(node: GraphNode | GraphBlock): string {
  if (node.kind === "file") return latin(node.source?.path.split(/[\\/]/).at(-1) || node.label, "File");
  if (values.has(node.kind) || ["function", "class", "folder", "project"].includes(node.kind)) return latin(node.label, node.kind === "data" ? "value" : node.kind);
  if (["condition", "loop", "loop_header"].includes(node.kind)) return latin(node.label, node.kind === "condition" ? "if condition" : "loop");
  if (node.kind === "with" || node.kind === "try") return node.kind;
  const outputs = "ports" in node ? node.ports.filter(p => p.direction === "output").map(p => p.name) : [];
  if (outputs.length) return latin([...new Set(outputs)].join(", "), "value");
  const assignment = node.label.match(/^\s*([\w., ]+)(?:\[[^\]]*\])?\s*(?:\+|-|\*|\/)?=(?!=)/u);
  if (assignment) return latin(assignment[1], "value");
  const call = node.label.match(/([\w.]+)\s*\(/u);
  if (call) return latin(call[1], "call");
  return node.kind === "return" ? "return" : latin(node.label, node.kind);
}

const isDocstring = (n: GraphNode) => n.kind === "operation" && /^\s*(?:[ru]|br|rb)?['"]/i.test(n.label);

/** Source-grounded expression, separate from output names; no generated prose. */
export function graphExpression(node: GraphNode): string {
  if (!["operation", "call"].includes(node.kind)) return "";
  const text = short(node.label);
  const rhs = text.replace(/^\s*[\w., ]+(?:\[[^\]]*\])?\s*(?:\+|-|\*|\/)?=(?!=)\s*/u, "");
  if (/[\u3400-\u9fff]/.test(rhs)) return "";
  // Call arguments stay in Details. Arithmetic/indexing operators stay visible.
  return node.kind === "call" ? (rhs.match(/^([\w.]+)\s*\(/)?.[1] ?? rhs) + "(…)" : rhs;
}

export function projectDisplayGraph(graph: SemanticGraph, collapsed: Set<string>, mode: GraphMode, scope: string | null = null,
  analysis?: AnalysisDocument, occurrences: OccurrenceGroup[] = []): GraphProjection {
  const blocks = new Map(graph.blocks.map(b => [b.id, b]));
  const all = new Map<string, GraphBlock | GraphNode>([...graph.blocks, ...graph.nodes].map(n => [n.id, n]));
  const parents = new Map<string, string | null>([...graph.blocks.map(b => [b.id, b.parent_id] as const), ...graph.nodes.map(n => [n.id, n.block_id] as const)]);
  const under = (id: string, root: string) => { const visited = new Set<string>(); while (id && !visited.has(id)) { if (id === root) return true; visited.add(id); id = parents.get(id) ?? ""; } return false; };
  const inScope = (id: string) => !scope || under(id, scope);
  const lexical = (id: string | null): string | null => { const visited = new Set<string>(); while (id && !visited.has(id)) { visited.add(id); const b = blocks.get(id); if (!b || containers.has(b.kind) || id === scope) return id; id = b.parent_id; } return null; };
  const representative = (id: string) => {
    let result = id, parent = parents.get(id); const seen = new Set<string>();
    while (parent && !seen.has(parent) && inScope(parent)) {
      seen.add(parent); if (collapsed.has(parent) && (mode === "code" || containers.has(blocks.get(parent)?.kind ?? "") || parent === scope)) result = parent;
      parent = parents.get(parent);
    }
    return result;
  };
  const depth = (id: string) => { let parent = parents.get(id), d = 0; const seen = new Set<string>(); while (parent && !seen.has(parent)) { seen.add(parent); d++; parent = parents.get(parent); } return d; };
  const visibleBlocks = graph.blocks.filter(b => inScope(b.id) && representative(b.id) === b.id && (mode === "code" || containers.has(b.kind) || b.id === scope))
    .sort((a, b) => depth(a.id) - depth(b.id) || (a.source?.line ?? 0) - (b.source?.line ?? 0));
  const nodes: ProjectionNode[] = visibleBlocks.map(b => ({ ...b, label: graphCaption(b), parent_id: b.id === scope ? null : mode === "data" ? lexical(b.parent_id) : b.parent_id,
    plate: true, collapsed: collapsed.has(b.id), handles: [] }));
  const nodeRepresentative = new Map<string, string>();
  const groupIds = new Map<string, string>(), origins = new Map<string, string[]>();
  const sourceObjects = new Map(analysis?.objects.map(o => [o.id, o]) ?? []);
  if (analysis) for (const g of logicalObjectGroups(analysis, occurrences)) for (const id of g.objectIds) { groupIds.set(id, g.id); origins.set(g.id, g.objectIds); }
  const dataGroups = new Map<string, ProjectionNode>();
  for (const n of graph.nodes) {
    if (!inScope(n.id)) continue;
    const parent = representative(n.id);
    if (parent !== n.id) { nodeRepresentative.set(n.id, parent); continue; }
    if (mode === "data") {
      if (!values.has(n.kind)) continue;
      const sourceObject = n.source_object_id ? sourceObjects.get(n.source_object_id) : undefined;
      if (sourceObject?.kind === "import") continue;
      const owner = lexical(n.block_id);
      const key = groupIds.get(n.source_object_id ?? n.id) ?? `${owner}:${n.logical_key || n.label}`;
      const current = dataGroups.get(key);
      if (current) { nodeRepresentative.set(n.id, current.id); current.original_node_ids!.push(n.id); continue; }
      const item: ProjectionNode = { ...n, label: graphCaption(n), parent_id: owner, plate: false, collapsed: false, handles: [],
        original_node_ids: [n.id], original_object_ids: origins.get(key) ?? (n.source_object_id ? [n.source_object_id] : []) };
      dataGroups.set(key, item); nodeRepresentative.set(n.id, item.id); nodes.push(item);
    } else if (!values.has(n.kind) && !["entry", "exit", "merge"].includes(n.kind) && !isDocstring(n)) {
      const item: ProjectionNode = { ...n, label: graphCaption(n), expression: graphExpression(n), parent_id: n.block_id, plate: false, collapsed: false, handles: [], original_node_ids: [n.id] };
      nodeRepresentative.set(n.id, n.id); nodes.push(item);
    }
  }
  visibleBlocks.forEach(b => nodeRepresentative.set(b.id, b.id));
  const known = new Map(nodes.map(n => [n.id, n]));
  const allowed = mode === "code" ? new Set(["data", "argument", "merge", "call", "return", "backedge", "block"]) : new Set(["data", "argument", "return", "merge", "backedge"]);
  const outgoing = new Map<string, GraphEdge[]>();
  for (const e of graph.edges) if (allowed.has(e.kind)) {
    const list = outgoing.get(e.source) ?? []; list.push(e); outgoing.set(e.source, list);
  }
  const grouped = new Map<string, ProjectionEdge>();
  for (const [start, source] of nodeRepresentative) {
    if (!known.has(source)) continue;
    const queue = (outgoing.get(start) ?? []).map(e => ({ edge: e, ids: e.original_ids.length ? e.original_ids : [e.id], branch: e.branch }));
    const visited = new Set<string>();
    for (let i = 0; i < queue.length; i++) {
      const path = queue[i], e = path.edge;
      if (!inScope(e.target)) continue;
      const target = nodeRepresentative.get(e.target);
      if (target && known.has(target)) {
        if (source === target) continue;
        const condition = all.get(start);
        const branch = path.branch;
        const label = mode === "data" ? "" : branch === "true" || branch === "false" ? branch
          : branch === "body" ? "body" : branch === "exit" ? "exit" : branch === "exception" ? "exception" : e.kind === "backedge" ? "repeat" : e.kind === "call" ? "call" : e.kind === "return" ? "return" : e.label;
        const kind = mode === "data" || ["data", "argument", "merge"].includes(e.kind) ? "data" : e.kind;
        const signature = JSON.stringify([source, target, kind, branch, label]);
        const existing = grouped.get(signature);
        if (existing) existing.original_ids = [...new Set([...existing.original_ids, ...path.ids])];
        else grouped.set(signature, { ...e, id: "display:" + encodeURIComponent(signature), source, target, kind, branch, label,
          displayLabel: label, original_ids: [...new Set(path.ids)], count: 1, source_port: null, target_port: null,
          source_boundary: source !== start, target_boundary: target !== e.target });
        continue;
      }
      if (visited.has(e.target)) continue;
      visited.add(e.target);
      for (const next of outgoing.get(e.target) ?? []) queue.push({ edge: next, ids: [...path.ids, ...(next.original_ids.length ? next.original_ids : [next.id])], branch: path.branch ?? next.branch });
    }
  }
  if (mode === "code") {
    // Control dependence: a branch guards its computations. The CFG's plain
    // next-statement edges are deliberately not a display relation.
    const flow = new Map<string, GraphEdge[]>();
    for (const e of graph.edges.filter(e => e.kind === "control")) flow.set(e.source, [...(flow.get(e.source) ?? []), e]);
    for (const first of graph.edges.filter(e => e.kind === "control" && e.branch)) {
      const source = nodeRepresentative.get(first.source), predicate = all.get(first.source);
      if (!source || !known.has(source)) continue;
      const owner = parents.get(first.source), seen = new Set<string>();
      const queue = [{ edge: first, ids: [first.id] }];
      for (let i = 0; i < queue.length; i++) {
        const { edge, ids } = queue[i], raw = all.get(edge.target);
        if (seen.has(edge.target) || !inScope(edge.target) || owner && !under(edge.target, owner) || raw?.kind === "exit") continue;
        seen.add(edge.target);
        const target = nodeRepresentative.get(edge.target);
        if (target && known.has(target) && target !== source) {
          const label = first.branch === "true" || first.branch === "false" ? first.branch : first.branch ?? "";
          const signature = JSON.stringify([source, target, "control", first.branch, label]);
          grouped.set(signature, { ...first, id: "display:" + encodeURIComponent(signature), source, target, kind: "control", label, displayLabel: label,
            original_ids: ids, count: 1, source_port: null, target_port: null, source_boundary: source !== first.source, target_boundary: target !== edge.target });
        }
        // An inner predicate introduces its own guard; do not flatten guards.
        if (raw?.kind === "condition" || raw?.kind === "loop_header") continue;
        for (const next of flow.get(edge.target) ?? []) queue.push({ edge: next, ids: [...ids, next.id] });
      }
    }
  }
  const edges = [...grouped.values()].sort((a, b) => a.id.localeCompare(b.id));
  const attach = (n: ProjectionNode, e: ProjectionEdge, direction: GraphHandle["direction"]) => {
    const name = e.displayLabel;
    const id = `${direction}:${e.kind}:${name}`;
    const port = n.handles.find(p => p.id === id);
    if (port) port.original_ids = [...new Set([...port.original_ids, ...e.original_ids])];
    else n.handles.push({ id, name, direction, kind: e.kind, boundary: direction === "input" ? e.target_boundary : e.source_boundary, original_ids: [...e.original_ids] });
    return id;
  };
  for (const e of edges) { e.source_port = attach(known.get(e.source)!, e, "output"); e.target_port = attach(known.get(e.target)!, e, "input"); }
  return { nodes, edges,
    omitted: [...graph.blocks, ...graph.nodes].filter(n => inScope(n.id) && representative(n.id) !== n.id).length,
    viewOmitted: graph.nodes.filter(n => inScope(n.id) && representative(n.id) === n.id && !nodeRepresentative.has(n.id)).length };
}
