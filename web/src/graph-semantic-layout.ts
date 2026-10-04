import type { Edge, Node } from "@xyflow/react";
import type { ElkExtendedEdge, ElkNode, LayoutOptions } from "elkjs/lib/elk-api";

interface LayoutHandle { id: string; direction: string; name: string; boundary?: boolean; y?: number }
export interface SemanticPoint { x: number; y: number }
export interface SemanticBounds extends SemanticPoint { width: number; height: number; ports: Map<string, SemanticPoint> }
export interface SemanticRoute { points: SemanticPoint[]; label?: SemanticPoint }
export interface SemanticLayout { nodes: Map<string, SemanticBounds>; edges: Map<string, SemanticRoute> }

/** Navigation shows readable content; the explicit fit action provides overview. */
export function readableGraphViewport(bounds: { x: number; y: number; width: number; height: number }, pane: { width: number; height: number }) {
  if (pane.width <= 0 || pane.height <= 0) return undefined;
  const left = 32, top = 48, bottom = 32;
  const width = Math.max(1, pane.width - left * 2), height = Math.max(1, pane.height - top - bottom);
  const zoom = Math.min(1, Math.max(0.75, Math.min(width / bounds.width, height / bounds.height)));
  const clipped = bounds.width * zoom > width || bounds.height * zoom > height;
  // Center a small graph; crop a large one from its actual upper-left origin.
  // Keeping both axes at that origin prevents landing in a wide routing gap.
  return {
    x: left - bounds.x * zoom + (clipped ? 0 : (width - bounds.width * zoom) / 2),
    y: top - bounds.y * zoom + (clipped ? 0 : (height - bounds.height * zoom) / 2),
    zoom,
  };
}

/** Fresh world bounds from ELK, independent of React Flow's measured DOM/store. */
export function semanticLayoutBounds(nodes: readonly Node[], layout: SemanticLayout) {
  const parents = new Map(nodes.map(n => [n.id, n.parentId]));
  let left = Infinity, top = Infinity, right = -Infinity, bottom = -Infinity;
  for (const [id, bounds] of layout.nodes) {
    let x = bounds.x, y = bounds.y, parent = parents.get(id);
    const seen = new Set([id]);
    while (parent && !seen.has(parent)) {
      seen.add(parent);
      const p = layout.nodes.get(parent);
      if (!p) break;
      x += p.x; y += p.y; parent = parents.get(parent);
    }
    left = Math.min(left, x); top = Math.min(top, y);
    right = Math.max(right, x + bounds.width); bottom = Math.max(bottom, y + bounds.height);
  }
  return Number.isFinite(left) ? { x: left, y: top, width: right - left, height: bottom - top } : undefined;
}

const labelWidth = (label: string) => [...label].reduce((size, c) => size + (c.charCodeAt(0) > 255 ? 11 : 6.3), 0);
export function semanticDimensions({ label, plate, handles, collapsed = false, compact = false, expression = "", kind = "" }: { label: string; plate: boolean; handles: LayoutHandle[]; collapsed?: boolean; compact?: boolean; expression?: string; kind?: string }) {
  const inputs = handles.filter(p => p.direction === "input"), outputs = handles.filter(p => p.direction === "output");
  if (compact) {
    const width = plate ? 288 : kind === "operation" ? 240 : 208;
    const textWidth = width - (plate ? 100 : kind === "operation" ? 108 : 48);
    const lines = Math.max(1, Math.ceil(labelWidth(label) / textWidth));
    const expressionLines = expression ? Math.ceil(labelWidth(expression) / textWidth) : 0;
    return { width, height: Math.max(kind === "operation" ? 144 : 104, 66 + lines * 17 + expressionLines * 15 + Math.max(inputs.length, outputs.length) * 12) };
  }
  const columnWidth = (column: LayoutHandle[]) => column.length ? Math.min(178, Math.max(88, ...column.map(p => labelWidth(p.name)))) : 0;
  const width = Math.ceil(Math.min(440, Math.max(plate ? 300 : 228, labelWidth(label) + (plate ? 118 : 40), columnWidth(inputs) + columnWidth(outputs) + 38)));
  const height = (plate ? 64 : 62) + Math.max(inputs.length, outputs.length) * 20 + (plate && collapsed ? 30 : 28);
  return { width, height: Math.max(plate ? 118 : 92, height) };
}

const portIdentity = (nodeId: string, handleId: string) => nodeId + "::handle::" + handleId;
const layoutOptions = (direction: string): LayoutOptions => ({
  "elk.algorithm": "layered",
  "elk.direction": direction,
  "elk.hierarchyHandling": "INCLUDE_CHILDREN",
  "elk.edgeRouting": "ORTHOGONAL",
  "elk.padding": "[top=48,left=24,bottom=24,right=24]",
  "elk.spacing.nodeNode": "24",
  "elk.spacing.edgeNode": "16",
  "elk.spacing.edgeEdge": "12",
  "elk.spacing.labelNode": "10",
  "elk.layered.spacing.nodeNodeBetweenLayers": "56",
  "elk.layered.spacing.edgeNodeBetweenLayers": "20",
  "elk.layered.nodePlacement.strategy": "BRANDES_KOEPF",
  "elk.layered.nodePlacement.bk.fixedAlignment": "BALANCED",
  // Wrapping a dependency chain into rows sends later values back across the
  // earlier row. Keep causal layers monotone; pan/focus supply the overview.
  "elk.layered.wrapping.strategy": "OFF",
  "elk.aspectRatio": "1.7",
  "elk.randomSeed": "1",
  // Extra scanline compaction rejects nested loops with fixed vertical ports
  // in ELK 0.11. BK placement and orthogonal routing already compact each layer.
  // ELK 0.11's model-order comparator can read an unset modelOrder.maximum
  // in compound data graphs. Keep seeded crossing minimization and wrapping;
  // enabling either model-order option reintroduces that comparator path.
});

/** Pure ELK input construction, shared by the browser worker and native probes. */
export function buildSemanticLayout(nodes: Node[], edges: Edge[], direction = "RIGHT"): ElkNode {
  const all = new Map<string, ElkNode>(), handlesById = new Map<string, Set<string>>();
  for (const n of nodes) {
    const width = Number(n.style?.width ?? 228), height = Number(n.style?.height ?? 92);
    const handles = (n.data.handles ?? []) as LayoutHandle[];
    const columnRows = new Map<string, number>();
    const ports = handles.map(p => {
      const row = columnRows.get(p.direction) ?? 0;
      columnRows.set(p.direction, row + 1);
      const count = handles.filter(h => h.direction === p.direction).length;
      const y = p.y ?? (n.data.compact ? height / 2 + (row - (count - 1) / 2) * 16 : (n.type === "plate" ? 64 : 62) + row * 20 + 10);
      const vertical = direction === "DOWN";
      const side = vertical ? p.direction === "input" ? "NORTH" : "SOUTH" : p.direction === "input" ? "WEST" : "EAST";
      return {
        id: portIdentity(n.id, p.id), x: vertical ? width / 2 + (row - (count - 1) / 2) * 16 - 4 : p.direction === "input" ? -4 : width - 4,
        y: vertical ? p.direction === "input" ? -4 : height - 4 : y - 4, width: 8, height: 8,
        layoutOptions: { "elk.port.side": side, "elk.port.index": String(row) },
      };
    });
    handlesById.set(n.id, new Set(handles.map(p => p.id)));
    all.set(n.id, { id: n.id, width, height, children: [], ports, layoutOptions: { ...layoutOptions(direction), "elk.portConstraints": "FIXED_POS" } });
  }
  const roots: ElkNode[] = [];
  for (const n of nodes) {
    const item = all.get(n.id)!;
    if (n.parentId && all.has(n.parentId)) all.get(n.parentId)!.children!.push(item);
    else roots.push(item);
  }
  for (const item of all.values()) {
    if (!item.children?.length) delete item.children;
    else {
      // Compound sizes are computed from their children; ELK places their
      // perimeter ports and the renderer consumes those actual positions.
      item.layoutOptions!["elk.portConstraints"] = "FIXED_SIDE";
      item.ports?.forEach(p => { delete p.x; delete p.y; });
    }
  }
  const endpoint = (id: string, handle: string | null | undefined) => handle && handlesById.get(id)?.has(handle) ? portIdentity(id, handle) : id;
  return {
    id: "semantic", layoutOptions: layoutOptions(direction), children: roots,
    edges: edges.filter(e => all.has(e.source) && all.has(e.target)).map(e => {
      const label = typeof e.label === "string" ? e.label : "";
      return {
        id: e.id, sources: [endpoint(e.source, e.sourceHandle)], targets: [endpoint(e.target, e.targetHandle)],
        labels: label ? [{ text: label, width: Math.min(270, labelWidth(label) + 40), height: 18, layoutOptions: { "elk.edgeLabels.placement": "CENTER", "elk.edgeLabels.inline": "true" } }] : [],
      };
    }),
  };
}

export function readSemanticLayout(graph: ElkNode): SemanticLayout {
  const nodes = new Map<string, SemanticBounds>(), absolute = new Map<string, SemanticPoint>([[graph.id, { x: 0, y: 0 }]]);
  const ownedEdges: { edge: ElkExtendedEdge; owner: string }[] = [];
  const visit = (item: ElkNode, origin: SemanticPoint, root = false) => {
    const offset = { x: origin.x + (item.x ?? 0), y: origin.y + (item.y ?? 0) };
    absolute.set(item.id, root ? origin : offset);
    if (!root) nodes.set(item.id, {
      x: item.x ?? 0, y: item.y ?? 0, width: item.width ?? 228, height: item.height ?? 92,
      ports: new Map(item.ports?.map(p => [p.id.slice(item.id.length + "::handle::".length), { x: (p.x ?? 0) + (p.width ?? 8) / 2, y: (p.y ?? 0) + (p.height ?? 8) / 2 }]) ?? []),
    });
    for (const edge of item.edges ?? []) ownedEdges.push({ edge, owner: item.id });
    for (const child of item.children ?? []) visit(child, root ? origin : offset);
  };
  visit(graph, { x: 0, y: 0 }, true);
  const edges = new Map<string, SemanticRoute>();
  for (const { edge, owner } of ownedEdges) {
    const origin = absolute.get(edge.container ?? owner) ?? { x: 0, y: 0 };
    const points = (edge.sections ?? []).flatMap(section => [section.startPoint, ...(section.bendPoints ?? []), section.endPoint].map(p => ({ x: p.x + origin.x, y: p.y + origin.y })));
    if (!points.length) continue;
    const label = edge.labels?.find(l => l.x !== undefined && l.y !== undefined);
    edges.set(edge.id, { points, label: label ? { x: origin.x + label.x! + (label.width ?? 0) / 2, y: origin.y + label.y! + (label.height ?? 0) / 2 } : undefined });
  }
  return { nodes, edges };
}
