/** Pure projection of a project graph slice into React Flow nodes and edges.
 *
 * This module never reads source bodies or docstrings: node labels come from
 * short block/node labels, file basenames, or the trailing qualname segment.
 * It preserves compound parenting and real dimensions so the ELK layout sees
 * style.width/height and parentId, and it resolves folded predicates back to
 * their original condition nodes instead of the collapsed plate.
 */
import { MarkerType, type Edge, type Node } from "@xyflow/react";
import type { ProjectGraphSlice, TargetRef } from "./generated";
import {
  projectGraph,
  type GraphHandle,
  type ProjectionEdge,
  type ProjectionNode,
} from "../workspace/graph-projection";
import { semanticDimensions } from "../../graph-semantic-layout";

export type CanvasShape = "circle" | "diamond" | "rounded" | "plate";
export type CanvasDirection = "RIGHT" | "DOWN";

export interface CanvasHandle {
  id: string;
  name: string;
  direction: "input" | "output";
  kind: string;
  boundary: boolean;
  original_ids: string[];
  side?: "WEST" | "EAST" | "NORTH" | "SOUTH";
  x?: number;
  y?: number;
}

export interface CanvasRoute {
  points: { x: number; y: number }[];
  label?: { x: number; y: number };
}

export type ProjectCanvasNodeData = {
  kind: string;
  category: string;
  label: string;
  expression: string;
  title: string;
  shape: CanvasShape;
  plate: boolean;
  collapsed: boolean;
  handles: CanvasHandle[];
  target: TargetRef;
  summary: string;
  memberCount: number;
  headerHeight: number;
};

export type ProjectCanvasEdgeData = {
  category: string;
  title: string;
  provenance: string;
  count: number;
  condition: string;
  original_ids: string[];
  route?: CanvasRoute;
  sourceLabel: string;
  targetLabel: string;
};

export type CanvasNode = Node<ProjectCanvasNodeData, "project">;
export type CanvasEdge = Edge<ProjectCanvasEdgeData, "project">;

export interface ProjectCanvasPresentation {
  nodes: CanvasNode[];
  edges: CanvasEdge[];
  layoutKey: string;
  omitted: number;
  viewOmitted: number;
}

const CATEGORY: Record<string, string> = {
  file: "File",
  function: "Function",
  class: "Class",
  folder: "Folder",
  project: "Project",
  stream: "Stream",
  with: "With",
  try: "Try",
  condition: "If",
  loop: "Loop",
  loop_header: "Loop",
  operation: "Compute",
  call: "Call",
  merge: "Merge",
  return: "Return",
  data: "Data",
  parameter: "Input",
  entry: "Entry",
  exit: "Exit",
  unknown: "Dynamic",
};

const HANDLE_NAME: Record<string, string> = {
  data: "Data",
  call: "Call",
  return: "Return",
  argument: "Argument",
  merge: "Merge",
  control: "Control",
  backedge: "Repeat",
  block: "Block",
};

const PLATE_KINDS = new Set(["file", "function", "class", "folder", "project", "stream", "with", "try", "block"]);

export function nodeShape(kind: string, plate: boolean): CanvasShape {
  if (plate || PLATE_KINDS.has(kind)) return "plate";
  if (kind === "condition" || kind === "loop_header") return "circle";
  if (kind === "operation" || kind === "call" || kind === "merge") return "diamond";
  return "rounded";
}

export function categoryLabel(kind: string): string {
  return CATEGORY[kind] ?? "Node";
}

/** Compact English edge category; branch overrides kind for conditions. */
export function edgeCategory(edge: { kind: string; branch: string | null }): string {
  switch (edge.branch) {
    case "true":
      return "True";
    case "false":
      return "False";
    case "body":
      return "Body";
    case "exit":
      return "Exit";
    case "exception":
      return "Exception";
    default:
      break;
  }
  switch (edge.kind) {
    case "call":
      return "Call";
    case "return":
      return "Return";
    case "argument":
      return "Argument";
    case "merge":
      return "Merge";
    case "control":
      return "Control";
    case "backedge":
      return "Repeat";
    default:
      return "Data";
  }
}

const collapse = (text: string, maximum = 48) => {
  const clean = text.replace(/\s+/g, " ").trim();
  return clean.length > maximum ? clean.slice(0, maximum - 1) + "\u2026" : clean;
};
const basename = (path: string) => path.replaceAll("\\", "/").replace(/\/$/, "").split("/").at(-1) || path;
const shortQualname = (qualname: string) => qualname.split(/::|\./).filter(Boolean).at(-1) || qualname;

function nodeLabel(node: ProjectionNode): string {
  if (node.kind === "file") return basename(node.source?.path || node.label);
  if (node.kind === "function" || node.kind === "class") return shortQualname(node.source?.qualname || node.label);
  return collapse(node.label);
}

function nodeExpression(node: ProjectionNode): string {
  if (node.kind !== "condition" && node.kind !== "loop_header") return "";
  return collapse(node.label, 240);
}

function nodeTarget(node: ProjectionNode, slice: ProjectGraphSlice): TargetRef {
  const source = node.source;
  const kind: TargetRef["kind"] = node.plate
    ? node.kind === "file"
      ? "file"
      : node.kind === "function" || node.kind === "class"
        ? "function"
        : node.kind === "folder"
          ? "folder"
          : node.kind === "project"
            ? "project"
            : "control"
    : node.kind === "data" || node.kind === "parameter"
      ? "data"
      : "operation";
  return {
    kind,
    logical_key: node.logical_key || node.id,
    object_id: node.source_object_id ?? null,
    block_id: node.plate ? node.id : ((node as { block_id?: string | null }).block_id ?? node.id),
    analysis_id: null,
    run_id: null,
    snapshot_id: null,
    project_id: source?.project_id || slice.project_id,
    file_id: source?.file_id || null,
    project_revision_id: source?.project_revision_id || slice.revision_id,
    exact_evidence: false,
  };
}

function depthOf(nodes: ProjectionNode[]): Map<string, number> {
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const depth = new Map<string, number>();
  const walk = (id: string): number => {
    if (depth.has(id)) return depth.get(id)!;
    const node = byId.get(id);
    const parent = node?.parent_id;
    const value = node && parent && byId.has(parent) ? walk(parent) + 1 : 0;
    depth.set(id, value);
    return value;
  };
  for (const node of nodes) walk(node.id);
  return depth;
}

export function presentProjectGraph(
  slice: ProjectGraphSlice,
  collapsed: ReadonlySet<string>,
  direction: CanvasDirection = "RIGHT",
): ProjectCanvasPresentation {
  const graph = slice.graph;
  const view = slice.view === "data" ? "data" : "structure";
  const projection = projectGraph(graph, new Set(collapsed), view, null);

  const ordered = [...projection.nodes];
  const depth = depthOf(ordered);
  ordered.sort((a, b) => (depth.get(a.id) ?? 0) - (depth.get(b.id) ?? 0) || a.id.localeCompare(b.id));
  const visible = new Set(ordered.map((node) => node.id));

  const originalNodes = new Map(graph.nodes.map((node) => [node.id, node]));
  const originalBlocks = new Map(graph.blocks.map((entry) => [entry.id, entry]));
  const originalEdges = new Map(graph.edges.map((entry) => [entry.id, entry]));
  const projectionSource = new Map(ordered.map((node) => [node.id, node]));

  const conditionFor = (edge: ProjectionEdge): string => {
    const ids = edge.original_ids.length ? edge.original_ids : [edge.id];
    for (const id of ids) {
      const original = originalEdges.get(id);
      if (!original) continue;
      const owner = originalNodes.get(original.source) ?? originalBlocks.get(original.source);
      if (owner && (owner.kind === "condition" || owner.kind === "loop_header")) return collapse(owner.label, 240);
    }
    const source = projectionSource.get(edge.source);
    if (source && (source.kind === "condition" || source.kind === "loop_header")) return collapse(source.label, 240);
    return "";
  };

  const handleIds = new Map<string, Set<string>>(
    ordered.map((node) => [node.id, new Set(node.handles.map((handle: GraphHandle) => handle.id))]),
  );

  const handleNames = new Map<string, string>();
  const edges: CanvasEdge[] = [];
  for (const edge of projection.edges as ProjectionEdge[]) {
    const sourceHandles = handleIds.get(edge.source);
    const targetHandles = handleIds.get(edge.target);
    if (!sourceHandles || !targetHandles) continue;
    const sourceHandle = edge.source_port && sourceHandles.has(edge.source_port) ? edge.source_port : undefined;
    const targetHandle = edge.target_port && targetHandles.has(edge.target_port) ? edge.target_port : undefined;
    if (!sourceHandle || !targetHandle) continue;
    const category = edgeCategory(edge);
    const condition = conditionFor(edge);
    const sourceNode = projectionSource.get(edge.source)!;
    const targetNode = projectionSource.get(edge.target)!;
    const originalData = edge.original_ids.flatMap(id => {
      const original = originalEdges.get(id);
      return original ? [originalNodes.get(original.source), originalNodes.get(original.target)] : [];
    }).find(node => node?.kind === "data" || node?.kind === "parameter");
    const variable = originalData?.label || (sourceNode.kind === "data" || sourceNode.kind === "parameter" ? sourceNode.label
      : targetNode.kind === "data" || targetNode.kind === "parameter" ? targetNode.label : "");
    const name = condition ? `${category} · ${condition}` : collapse(edge.label || variable || category, 64);
    const title = `${category} · ${name}`;
    handleNames.set(edge.source + "::" + sourceHandle, name);
    handleNames.set(edge.target + "::" + targetHandle, name);
    const family = ["control", "merge", "backedge"].includes(edge.kind) ? "control"
      : ["call", "argument"].includes(edge.kind) ? "call" : edge.kind === "return" ? "return" : "data";
    const color = `var(--project-relation-${family})`;
    edges.push({
      id: edge.id,
      type: "project",
      source: edge.source,
      target: edge.target,
      sourceHandle,
      targetHandle,
      // Named rows carry ordinary data labels; reserve canvas labels for
      // decisions, where hiding the branch would change the visible meaning.
      label: condition ? collapse(`${category} · ${condition}`, 40) : undefined,
      className: `project-relation relation-${family}`,
      style: { stroke: color, strokeWidth: 1.5, ...(family === "control" ? { strokeDasharray: "5 4" } : {}) },
      markerEnd: { type: MarkerType.ArrowClosed, color, width: 16, height: 16 },
      labelStyle: { fill: "var(--project-text)", fontSize: 10 },
      labelBgStyle: { fill: "var(--project-surface)" },
      data: {
        category,
        title,
        provenance: edge.provenance,
        count: edge.count || edge.original_ids.length || 1,
        condition,
        original_ids: [...edge.original_ids],
        sourceLabel: nodeLabel(projectionSource.get(edge.source)!),
        targetLabel: nodeLabel(projectionSource.get(edge.target)!),
      },
    });
  }

  const memberCounts = new Map<string, number>();
  for (const node of graph.nodes) {
    let parent: string | null = node.block_id;
    const seen = new Set<string>();
    while (parent && !seen.has(parent)) {
      seen.add(parent);
      memberCounts.set(parent, (memberCounts.get(parent) ?? 0) + 1);
      parent = originalBlocks.get(parent)?.parent_id ?? null;
    }
  }
  const nodes: CanvasNode[] = ordered.map((node) => {
    const label = nodeLabel(node);
    const shape = nodeShape(node.kind, node.plate);
    const handles: CanvasHandle[] = node.handles.map((handle: GraphHandle) => ({
      id: handle.id,
      name: !handle.boundary ? handle.name : handleNames.get(node.id + "::" + handle.id) ?? HANDLE_NAME[handle.kind] ?? "Link",
      direction: handle.direction,
      kind: handle.kind,
      boundary: handle.boundary,
      original_ids: [...handle.original_ids],
      side: handle.side,
    }));
    const expression = nodeExpression(node);
    const dimensions = semanticDimensions({
      label,
      plate: node.plate,
      handles,
      collapsed: node.collapsed,
      kind: node.kind,
      expression,
    });
    // The project canvas uses compact entity-like connection rows. Measure
    // the wrapped header separately so text and ports never share a row.
    dimensions.width = node.plate ? 300 : 260;
    const labelLines = Math.min(4, Math.max(1, Math.ceil([...label].reduce((w, c) => w + (c.charCodeAt(0) > 255 ? 12 : 7), 0) / (dimensions.width - 88))));
    const headerHeight = Math.max(50, 24 + labelLines * 16);
    const portCount = Math.max(handles.filter(h => h.direction === "input").length, handles.filter(h => h.direction === "output").length);
    dimensions.height = headerHeight + portCount * 22 + (node.collapsed ? 30 : 12);
    const rows = { input: 0, output: 0 };
    handles.forEach(handle => { handle.y = headerHeight + rows[handle.direction]++ * 22 + 11; });
    const parent = node.parent_id && visible.has(node.parent_id) ? node.parent_id : undefined;
    return {
      id: node.id,
      type: "project",
      position: { x: 0, y: 0 },
      parentId: parent,
      width: dimensions.width,
      height: dimensions.height,
      style: { width: dimensions.width, height: dimensions.height },
      draggable: true,
      dragHandle: ".project-node-header",
      connectable: false,
      ariaLabel: `${categoryLabel(node.kind)} ${label}`,
      data: {
        kind: node.kind,
        category: categoryLabel(node.kind),
        label,
        expression,
        title: collapse(node.label, 240),
        shape,
        plate: node.plate,
        collapsed: node.collapsed,
        handles,
        target: nodeTarget(node, slice),
        memberCount: memberCounts.get(node.id) ?? 0,
        summary: `${memberCounts.get(node.id) ?? 0} units`,
        headerHeight,
      },
    };
  });

  const folds = [...collapsed].sort();
  const layoutKey = JSON.stringify([
    slice.project_id,
    slice.revision_id,
    slice.scope_id,
    graph.source_digest,
    view,
    direction,
    folds,
  ]);
  return { nodes, edges, layoutKey, omitted: projection.omitted, viewOmitted: projection.viewOmitted };
}
