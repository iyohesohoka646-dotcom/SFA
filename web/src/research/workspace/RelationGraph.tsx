import { useResearchServices } from "./ResearchServices";
import { memo, useEffect, useMemo, useRef, useState } from "react";
import {
  Background,
  BackgroundVariant,
  BaseEdge,
  Controls,
  Handle,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  useNodesState,
  useUpdateNodeInternals,
  getSmoothStepPath,
  SelectionMode,
  type Edge,
  type EdgeProps,
  type Node,
  type NodeProps,
  MarkerType,
} from "@xyflow/react";

import type { ResearchState } from "../state";
import type { SnapshotRef } from "../generated";
import type {
  AnalysisDocument,
  TargetRef,
  ControlSummary,
  GraphBlock,
} from "./generated";
import type { WorkspaceDocument } from "./layout";
import {
  selectionKey,
  choose,
  unique,
  type Selection,
} from "./selection";
import { layoutSemantic } from "../../graph";
import { semanticDimensions, semanticLayoutBounds, readableGraphViewport, type SemanticRoute } from "../../graph-semantic-layout";
import { initialCollapsed, graphNodeTarget, selectedGraphIds, type GraphHandle } from "./graph-projection";
import { projectDisplayGraph, normalizeGraphMode, type GraphMode } from "./graph-display";
import { describeGraphData, executionOverlay, type GraphDataDescription, type NodeExecution, type EdgeExecution } from "./graph-execution";
import { logicalObjectGroups, selectionObjectIds, latestObservedSnapshot } from "./objectTree";
import type { OccurrenceGroup } from "./sourceOccurrences";
import { Icon } from "./icons";


import { createState, indexSnapshot } from "../state";
import "./graph.css";
const names: Record<string, string> = {
  function: "Function", class: "Class", condition: "If", loop: "Loop", file: "File",
  operation: "Compute", parameter: "Input", data: "Variable", return: "Return", merge: "Merge", call: "Call",
  entry: "Entry", exit: "Exit", loop_header: "Loop", try: "Try", unknown: "Dynamic", folder: "Folder",
  project: "Project", stream: "Stream", with: "With",
};
const glyphs: Record<string, string> = { function: "ƒ", class: "{}", condition: "?", loop: "↻", loop_header: "↻", operation: "∑", call: "ƒ()", return: "↵", merge: "⋈", entry: "▶", exit: "◼", unknown: "…", scalar: "σ", vector: "[ ]", matrix: "▦", tensor: "▧", table: "▤", text: "Aa", sequence: "≡", mapping: "{ }", object: "◈", data: "▦", parameter: "in" };
function GraphGlyph({ kind }: { kind: string }) {
  return <span className={"graph-glyph glyph-" + kind} aria-hidden="true">{glyphs[kind] ?? <Icon name={kind === "file" ? "source" : "graph"} size={16} />}</span>;
}
function GraphPorts({ handles, plate }: { handles: GraphHandle[]; plate: boolean }) {
  const rows = new Map<string, number>();
  return handles.map(p => {
    const row = rows.get(p.direction) ?? 0;
    rows.set(p.direction, row + 1);
    const y = p.y ?? 48 + row * 16;
    const vertical = p.side === "NORTH" || p.side === "SOUTH";
    return <div className={"graph-port port-" + p.direction + " relationship-" + p.kind + (vertical ? " vertical-port" : "") + (p.boundary ? " boundary-port" : "")} key={p.id} style={vertical ? { left: p.x, top: p.y, right: "auto" } : { top: y }} title={p.name + (p.original_ids.length ? ` · ${p.original_ids.length} references` : "")}>
      <Handle id={p.id} type={p.direction === "input" ? "target" : "source"} position={vertical ? p.side === "NORTH" ? Position.Top : Position.Bottom : p.direction === "input" ? Position.Left : Position.Right} />
      <span className="graph-port-label">{p.name}</span>
    </div>;
  });
}
const executionNames: Record<string, string> = { observed: "run", running: "running", started: "running", completed: "done", failed: "failed", error: "error", cancelled: "cancelled" };
function NodeReceipt({ receipt, plate = false }: { receipt?: NodeExecution; plate?: boolean }) {
  if (!receipt || ["unobserved", "not_taken"].includes(receipt.status)) return null;
  return <div className={"graph-node-receipt" + (plate ? " plate-counter" : "")}>
    <span className="graph-execution-state">{executionNames[receipt.status] ?? receipt.status}</span>
    {receipt.count !== undefined && (receipt.count > 0 || receipt.complete) && <span>{receipt.complete ? "" : "≥"}{receipt.count}×</span>}
  </div>;
}
function SemanticNode({ id, data }: NodeProps) {
  const handles = (data.handles ?? []) as GraphHandle[], badge = data.badge as GraphDataDescription | undefined, receipt = data.receipt as NodeExecution | undefined;
  const update = useUpdateNodeInternals();
  useEffect(() => update(id), [id, handles, update]);
  return (
    <div
      className={"semantic-node kind-" + data.kind + " execution-" + (receipt?.status ?? "static") + (badge ? " data-shape-" + badge.kind : "") + (data.searchMatch ? " graph-search-match" : "")}
      data-testid="relation-node"
    >
      {data.kind === "operation" && <svg className="graph-compute-outline" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true"><polygon points="1,50 50,1 99,50 50,99" /></svg>}
      <div className="semantic-heading graph-node-drag-handle">
        <GraphGlyph kind={badge?.kind ?? String(data.kind)} />
        <div><small>{badge ? badge.kind === "unknown" ? "Variable" : badge.kind : names[String(data.kind)] ?? String(data.kind)}</small><strong title={String(data.label)}>{String(data.label)}</strong>{Boolean(data.expression) && <code className="graph-expression">{String(data.expression)}</code>}</div>
        {Boolean(data.pinned) && <span className="graph-pin"><Icon name="pin" size={12} /></span>}
      </div>
      <GraphPorts handles={handles} plate={false} />
      <div className="graph-node-footer">{badge && <small className="graph-data-detail" title={badge.detail}>{badge.detail}</small>}<NodeReceipt receipt={receipt} /></div>
    </div>
  );
}
function BlockNode({ id, data }: NodeProps) {
  const handles = (data.handles ?? []) as GraphHandle[], receipt = data.receipt as NodeExecution | undefined;
  const update = useUpdateNodeInternals();
  useEffect(() => update(id), [id, handles, update]);
  return (
    <div
      data-testid="relation-node"
      className={"semantic-plate kind-" + data.kind + (data.collapsed ? " is-collapsed" : " is-expanded") + " execution-" + (receipt?.status ?? "static") + (data.searchMatch ? " graph-search-match" : "") + (data.partial ? " graph-partial-selection" : "")}
    >
      <header className="graph-node-drag-handle">
        <GraphGlyph kind={String(data.kind)} />
        <strong title={String(data.label)}>{String(data.label)}</strong>
        <small>{names[String(data.kind)]}</small>
        {Boolean(data.pinned) && <span className="graph-pin"><Icon name="pin" size={12} /></span>}
        <button
          className="nodrag nopan"
          aria-label={(data.collapsed ? "Expand " : "Collapse ") + data.label}
          onClick={(e) => {
            e.stopPropagation();
            (data.collapse as () => void)();
          }}
        >
          <Icon name="chevron" size={12} />
        </button>
      </header>
      <GraphPorts handles={handles} plate />
      {Boolean(data.collapsed) && (
        <span className="plate-summary">{String(data.members)} units</span>
      )}
      <NodeReceipt receipt={receipt} plate />
    </div>
  );
}
const nodeTypes = { semantic: SemanticNode, plate: BlockNode };
function SemanticEdge(props: EdgeProps) {
  const route = props.data?.route as SemanticRoute | undefined;
  const first = route?.points[0], last = route?.points.at(-1);
  const routed = first && last && Math.abs(first.x - props.sourceX) < 9 && Math.abs(first.y - props.sourceY) < 9 && Math.abs(last.x - props.targetX) < 9 && Math.abs(last.y - props.targetY) < 9;
  const smooth = getSmoothStepPath(props);
  const points = routed ? [{ x: props.sourceX, y: props.sourceY }, ...route!.points.slice(1, -1), { x: props.targetX, y: props.targetY }] : [];
  const path = routed ? points.map((p, i) => `${i ? "L" : "M"}${p.x},${p.y}`).join(" ") : smooth[0];
  return <g><title>{String(props.data?.description ?? props.label ?? "")}</title><BaseEdge path={path} markerEnd={props.markerEnd} style={props.style} label={props.label} labelX={routed && route?.label ? route.label.x : smooth[1]} labelY={routed && route?.label ? route.label.y : smooth[2]} labelStyle={props.labelStyle} labelShowBg labelBgStyle={props.labelBgStyle} labelBgPadding={[5, 3]} labelBgBorderRadius={3} interactionWidth={0} /></g>;
}
const edgeTypes = { semantic: SemanticEdge };
const emptyOccurrences: OccurrenceGroup[] = [];
const edgeColors: Record<string, string> = {
  data: "#237767",
  control: "#956b22",
  call: "#6658a4",
  argument: "#6658a4",
  return: "#47769b",
  merge: "#956b22",
  backedge: "#a15736",
  block: "#687a8a",
};
function GraphInner({
  document,
  state,
  analysis,
  selection,
  onSelection,
  scope,
  onEnter,
  onOpen,
  onSource,
  onBind,
  onError,
}: {
  document: WorkspaceDocument;
  state: ResearchState;
  analysis?: AnalysisDocument;
  selection: Selection;
  onSelection: (s: Selection) => void;
  scope: string | null;
  onEnter: (id: string | null) => void;
  onOpen: (t: TargetRef) => void;
  onSource: (t: TargetRef) => void;
  onBind: () => void;
  onError: (s: string) => void;
}) {
  const { research: { request }, workbench: wb } = useResearchServices();
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]),
    [edges, setEdges] = useState<Edge[]>([]),
    [closed, setClosed] = useState<{ key: string; values: Set<string> }>({ key: "", values: new Set() }),
    [view, setView] = useState<GraphMode>("code"),
    [showExecution, setShowExecution] = useState(false),
    [detailId, setDetailId] = useState<string>(),
    [dim, setDim] = useState(false),
    [query, setQuery] = useState(""),
    [direction, setDirection] = useState("RIGHT"),
    [arrange, setArrange] = useState(0),
    [time, setTime] = useState(0),
    [layoutState, setLayoutState] = useState<{ key: string; status: "pending" | "ready" | "error" }>({ key: "", status: "pending" }),
    [controls, setControls] = useState<ControlSummary[]>([]),
    [menu, setMenu] = useState<{ x: number; y: number; id?: string; target: TargetRef }>(),
    [settingsOpen, setSettingsOpen] = useState(false),
    [interaction, setInteraction] = useState<"pan" | "select">("pan"),
    [pinsRevision, setPinsRevision] = useState(0);
  const [occurrences, setOccurrences] = useState<{ analysisId?: string; groups: OccurrenceGroup[] }>({ groups: [] });
  useEffect(() => {
    const abort = new AbortController();
    setOccurrences({ groups: [] });
    if (analysis) void wb.occurrences(analysis.id, abort.signal)
      .then(groups => { if (!abort.signal.aborted) setOccurrences({ analysisId: analysis.id, groups }); })
      .catch(error => { if (!abort.signal.aborted) onError("源码关系不可读取：" + error.message); });
    return () => abort.abort();
  }, [analysis?.id]);
  const occurrenceGroups = occurrences.analysisId === analysis?.id ? occurrences.groups : emptyOccurrences;
  const settingsRef = useRef<HTMLElement>(null), settingsButton = useRef<HTMLButtonElement>(null), canvasRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!settingsOpen) return;
    const close = (e: PointerEvent) => { if (e.target instanceof Element && !settingsRef.current?.contains(e.target) && !settingsButton.current?.contains(e.target)) setSettingsOpen(false); };
    window.addEventListener("pointerdown", close);
    return () => window.removeEventListener("pointerdown", close);
  }, [settingsOpen]);
  useEffect(() => {
    const apply = () => {
      try {
        const s = JSON.parse(
          localStorage.getItem("cdaf-graph-settings") ?? "{}",
        );
        setDim(s.dim_unrelated ?? false);
        if (["RIGHT", "DOWN"].includes(s.direction)) setDirection(s.direction);
        setView(normalizeGraphMode(s.view));
      } catch {
        onError("图设置不可读取");
      }
    };
    apply();
    window.addEventListener("cdaf-preferences-changed", apply);
    return () => window.removeEventListener("cdaf-preferences-changed", apply);
  }, []);
  const [relations, setRelations] = useState(
    new Set(["data", "control", "call", "block"]),
  );
  const flow = useReactFlow(),
    positions = useRef(new Map<string, { x: number; y: number }>()),
    fittedNavigation = useRef<string | undefined>(undefined),
    generation = useRef(0);
  const graph = analysis?.graph,
    pinned = useRef(new Set<string>()),
    positionKey = "cdaf-graph-positions:v2:" + analysis?.id + ":" + view + ":" + (scope ?? "root");
  useEffect(() => {
    try {
      const saved = JSON.parse(
        localStorage.getItem(positionKey) ?? (!scope ? localStorage.getItem("cdaf-graph-positions:" + analysis?.id) : null) ?? "{}",
      ) as Record<string, { x: number; y: number }>;
      positions.current = new Map(
        Object.entries(saved).filter(
          ([, p]) => Number.isFinite(p.x) && Number.isFinite(p.y),
        ),
      );
      pinned.current = new Set(positions.current.keys());
    } catch {
      onError("图位置记录不可读取");
    }
    fittedNavigation.current = undefined;
  }, [positionKey]);
  const preference = (key: string, value: unknown) => {
    try { localStorage.setItem("cdaf-graph-settings", JSON.stringify({ ...JSON.parse(localStorage.getItem("cdaf-graph-settings") ?? "{}"), [key]: value })); }
    catch { onError("图设置不可保存"); }
  };
  const persistPositions = () =>
    localStorage.setItem(
      positionKey,
      JSON.stringify(
        Object.fromEntries(
          [...positions.current].filter(([id]) => pinned.current.has(id)),
        ),
      ),
    );
  const foldKey = (analysis?.id ?? "") + ":" + (graph?.source_digest ?? "") + ":" + (scope ?? "root");
  const collapsed = useMemo(
    () => graph ? initialCollapsed(graph, closed.key === foldKey ? closed.values : new Set(), scope) : new Set<string>(),
    [closed, graph, scope, foldKey],
  );
  const projection = useMemo(
    () =>
      graph
        ? projectDisplayGraph(graph, collapsed, view, scope, analysis, occurrenceGroups)
        : { nodes: [], edges: [], omitted: 0, viewOmitted: 0 },
    [graph, collapsed, view, scope, occurrenceGroups],
  );
  const groups = useMemo(() => analysis ? logicalObjectGroups(analysis, occurrenceGroups) : [], [analysis, occurrenceGroups]);
  const groupByObject = useMemo(() => new Map(groups.flatMap(g => g.objectIds.map(id => [id, g] as const))), [groups]);
  const valuesByGroup = useMemo(() => {
    const indexed = new Map<string, SnapshotRef[]>();
    // Runtime snapshots are captured values; provenance describes their lineage.
    for (const s of state.latest.values()) if (s.run_id === state.runId && (!s.source?.digest || s.source.digest === analysis?.source_digest)) indexed.set(s.logical_key, [...(indexed.get(s.logical_key) ?? []), s]);
    return new Map(groups.map(g => {
      const ambiguous = g.logicalKey.includes("@scope:");
      const values = g.logicalKeys.flatMap(key => indexed.get(key) ?? []).filter(s => !ambiguous || s.source && g.objects.some(o => o.line <= s.source!.line && s.source!.line <= o.end_line));
      return [g.id, latestObservedSnapshot(values)] as const;
    }));
  }, [groups, state.runId, state.latest, state.lastSequence, analysis?.source_digest]);
  const originsByGroup = useMemo(() => {
    const selectedMembers = new Map(selection.targets.filter(t => !t.exact_evidence && t.kind === "data" && t.object_id).flatMap(t => {
      const group = groupByObject.get(t.object_id!); return group ? [[group.id, t.object_id!] as const] : [];
    }));
    return new Map(groups.map(g => {
      const snapshot = valuesByGroup.get(g.id), selectedMember = selectedMembers.get(g.id);
      const origin = (selectedMember ? g.objects.find(o => o.id === selectedMember) : snapshot?.source ? g.objects.find(o => o.line === snapshot.source!.line && o.column === snapshot.source!.column) ?? g.objects.find(o => o.line === snapshot.source!.line) : undefined) ?? g.objects[0];
      return [g.id, origin] as const;
    }));
  }, [selection, groups, groupByObject, valuesByGroup]);
  const semanticById = useMemo(() => new Map(projection.nodes.map(n => [n.id, n])), [projection]);
  const targets = useMemo(
    () =>
      new Map(
        projection.nodes.map((n) => {
          const group = !n.plate && ["data", "parameter"].includes(n.kind) ? groupByObject.get(n.source_object_id ?? n.id) ?? groups.find(g => g.logicalKeys.includes(n.logical_key)) : undefined;
          const snapshot = group ? valuesByGroup.get(group.id) : undefined;
          const origin = group && originsByGroup.get(group.id);
          return [n.id, graphNodeTarget(n, analysis?.id, origin, snapshot)];
        }),
      ),
    [projection, groups, groupByObject, valuesByGroup, originsByGroup, analysis?.id],
  );
  const selectedKeys = useMemo(
    () => new Set(selection.targets.map(selectionKey)),
    [selection],
  );
  const selectedObjects = useMemo(
    () =>
      selectionObjectIds(analysis, selection.targets, occurrenceGroups),
    [analysis, selection, occurrenceGroups],
  );
  const selectedIds = useMemo(
    () => {
      const ids = selectedGraphIds(targets, selection, selectedObjects, new Map(projection.nodes.map(n => [n.id, n.source_object_id])));
      for (const node of projection.nodes) if (node.original_object_ids?.some(id => selectedObjects.has(id))) ids.add(node.id);
      return ids;
    },
    [targets, selection, selectedObjects, projection],
  );
  const selectedBlocks = useMemo(() => {
    const parents = new Map(
        graph?.blocks.map((b) => [b.id, b.parent_id]) ?? [],
      ),
      ids = new Set<string>();
    for (const t of selection.targets) {
      let id: string | undefined = t.block_id ?? undefined;
      while (id && !ids.has(id)) {
        ids.add(id);
        id = parents.get(id) ?? undefined;
      }
    }
    return ids;
  }, [graph, selection]);
  const direct = useMemo(
    () =>
      new Set(
        projection.edges
          .filter((e) => selectedIds.has(e.source) || selectedIds.has(e.target))
          .flatMap((e) => [e.source, e.target]),
      ),
    [projection, selectedIds],
  );
  useEffect(() => {
    setControls([]);
    if (!showExecution || !state.runId) return;
    let live = true;
    const load = () =>
      request<{ summaries: ControlSummary[] }>(
        "/runs/" + encodeURIComponent(state.runId) + "/controls",
      )
        .then((c) => {
          if (live) setControls(c.summaries);
        })
        .catch((e) => {
          if (live) onError(e.message);
        });
    void load();
    const timer = ["queued", "running", "paused"].includes(state.status) ? setInterval(() => void load(), 1000) : undefined;
    return () => {
      live = false;
      if (timer) clearInterval(timer);
    };
  }, [state.runId, state.status, showExecution, analysis?.id]);
  const execution = useMemo(() => graph ? executionOverlay(graph, projection, state, controls) : { hasEvidence: false, nodes: new Map<string, NodeExecution>(), edges: new Map<string, EdgeExecution>() }, [graph, projection, state.runId, state.lastSequence, state.operations, state.snapshots, controls]);
  const toggle = (id: string) =>
    setClosed((old) => {
      const n = new Set(old.key === foldKey ? old.values : []);
      if (collapsed.has(id)) {
        n.delete(id);
        n.add("open:" + id);
      } else {
        n.add(id);
        n.delete("open:" + id);
      }
      return { key: foldKey, values: n };
    });
  const structuralKey =
    projection.nodes.map((n) => n.id).join("|") +
    projection.edges.map((e) => e.id).join("|") +
    direction +
    view +
    foldKey +
    projection.nodes.map(n => String(n.collapsed)).join("|") +
    arrange +
    (scope ?? "") +
    String(flow.viewportInitialized);
  // Scope and mode switches are explicit navigation. A cancelled layout never
  // consumes this request; selection, folding, and observations keep the camera.
  const navigationKey = foldKey + ":" + view;
  const layoutReady = layoutState.key === structuralKey && layoutState.status === "ready";
  useEffect(() => {
    const version = ++generation.current,
      started = performance.now(),
      ids = new Set(projection.nodes.map((n) => n.id));
    const seed: Node[] = projection.nodes.map((n, i) => {
      const block = n as GraphBlock,
        parent = n.parent_id && ids.has(n.parent_id) ? n.parent_id : undefined;
      const group = groupByObject.get(n.source_object_id ?? n.id) ?? groups.find(g => g.logicalKeys.includes(n.logical_key)), snapshot = group && valuesByGroup.get(group.id);
      const badge = !n.plate && ["data", "parameter"].includes(n.kind) ? describeGraphData(snapshot?.descriptor) : undefined;
      return {
        id: n.id,
        type: n.plate ? "plate" : "semantic",
        parentId: parent,
        expandParent: Boolean(parent),
        dragHandle: n.plate && !n.collapsed ? ".graph-node-drag-handle" : undefined,
        selectable: true,
        zIndex: n.plate ? 0 : 2,
        position: positions.current.get(n.id) ?? { x: i * 200, y: 0 },
        style: {
          ...semanticDimensions({ plate: n.plate, label: n.label, handles: n.handles, collapsed: n.collapsed, compact: true, kind: n.kind, expression: n.expression }),
          pointerEvents: "auto",
        },
        data: {
          label: n.label,
          expression: n.expression,
          compact: true,
          kind: n.kind,
          handles: n.handles,
          badge: badge ? { ...badge, detail: snapshot ? badge.detail : "" } : undefined,
          pinned: pinned.current.has(n.id),
          members: block.members?.length ?? 0,
          collapsed: n.collapsed,
          collapse: () => toggle(n.id),
        },
        ariaLabel: `${names[n.kind] ?? n.kind} ${n.label}${n.plate ? n.collapsed ? ", collapsed" : ", expanded" : ""}`,
      };
    });
    const lines: Edge[] = projection.edges.map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      sourceHandle: e.source_port ?? undefined,
      targetHandle: e.target_port ?? undefined,
      type: "semantic",
      selectable: false,
      focusable: false,
      interactionWidth: 0,
      label: e.displayLabel,
      markerEnd: { type: MarkerType.ArrowClosed, width: 12, height: 12 },
      data: { kind: e.kind, original_ids: e.original_ids, baseLabel: e.displayLabel, relationshipCount: e.count, description: `${e.displayLabel || names[e.kind] || e.kind}: ${e.original_ids.length} source relationships (${e.provenance})` },
      style: {
        stroke: edgeColors[e.kind] ?? "#647b84",
        strokeDasharray:
          e.kind === "data" ? undefined : e.kind === "backedge" ? "3 3" : "7 4",
      },
      labelStyle: { fontSize: 11, fill: "var(--ri-text)" },
      labelBgStyle: { fill: "var(--ri-panel)", fillOpacity: 0.94 },
    }));
    setTime(0);
    setLayoutState({ key: structuralKey, status: "pending" });
    void layoutSemantic(seed, lines, direction)
      .then(async (layout) => {
        if (version !== generation.current) return;
        // Pinned/manual child coordinates can extend the bounds of their
        // container. Grow ancestors before React Flow applies parent extents.
        for (const n of seed) {
          const p = layout.nodes.get(n.id), saved = positions.current.get(n.id);
          if (p && saved) { p.x = saved.x; p.y = saved.y; }
        }
        for (const n of [...seed].reverse()) {
          const p = layout.nodes.get(n.id), parent = n.parentId ? layout.nodes.get(n.parentId) : undefined;
          if (p && parent) { parent.width = Math.max(parent.width, p.x + p.width + 30); parent.height = Math.max(parent.height, p.y + p.height + 30); }
        }
        if (fittedNavigation.current !== navigationKey) {
          const bounds = semanticLayoutBounds(seed, layout);
          if (bounds && flow.viewportInitialized) {
            const viewport = readableGraphViewport(bounds, { width: canvasRef.current?.clientWidth ?? 0, height: canvasRef.current?.clientHeight ?? 0 });
            if (viewport) {
              // Fresh ELK bounds and actual pane size avoid stale measurements;
              // large graphs begin with readable content, with overview explicit.
              const fitted = await flow.setViewport(viewport, { duration: 0 });
              if (version !== generation.current) return;
              if (fitted) fittedNavigation.current = navigationKey;
            }
          }
        }
        if (version !== generation.current) return;
        setNodes(
          seed.map((n) => {
            const p = layout.nodes.get(n.id);
            return p
              ? {
                  ...n,
                  position: positions.current.get(n.id) ?? { x: p.x, y: p.y },
                  width: p.width,
                  height: p.height,
                  style: { ...n.style, width: p.width, height: p.height },
                  data: { ...n.data, handles: (n.data.handles as GraphHandle[]).map(h => ({ ...h, x: p.ports.get(h.id)?.x, y: p.ports.get(h.id)?.y ?? h.y, side: direction === "DOWN" ? h.direction === "input" ? "NORTH" : "SOUTH" : h.direction === "input" ? "WEST" : "EAST" })) },
                }
              : n;
          }),
        );
        setEdges(lines.map(e => ({ ...e, data: { ...e.data, route: layout.edges.get(e.id) } })));
        setTime(performance.now() - started);
        setLayoutState({ key: structuralKey, status: "ready" });
      })
      .catch((e) => {
        if (version === generation.current) {
          setLayoutState({ key: structuralKey, status: "error" });
          onError("布局失败：" + e.message);
        }
      });
    return () => {
      generation.current++;
    };
  }, [structuralKey]);
  useEffect(() => {
    if (!layoutReady) return;
    const normalizedQuery = query.trim().toLowerCase();
    setNodes((current) =>
      current.map((n) => {
        const selected = selectedIds.has(n.id), partial = n.type === "plate" && selectedBlocks.has(n.id) && !selected;
        const semantic = semanticById.get(n.id), isData = semantic && !semantic.plate && ["data", "parameter"].includes(semantic.kind), group = isData ? groupByObject.get(semantic.source_object_id ?? semantic.id) ?? groups.find(g => g.logicalKeys.includes(semantic.logical_key)) : undefined, snapshot = group && valuesByGroup.get(group.id);
        const badge = isData ? describeGraphData(snapshot?.descriptor) : undefined;
        return {
          ...n,
          selected,
          hidden: false,
          style: {
            ...n.style,
            opacity:
              normalizedQuery && !String(n.data.label).toLowerCase().includes(normalizedQuery) && !direct.has(n.id) && n.type !== "plate" ? 0.38 : dim && selection.targets.length && !selected && !partial && !direct.has(n.id) ? 0.34 : 1,
          },
          data: {
            ...n.data,
            receipt: showExecution ? execution.nodes.get(n.id) : undefined,
            badge: badge ? { ...badge, detail: snapshot ? badge.detail : "" } : undefined,
            partial,
            searchMatch: normalizedQuery.length > 0 && String(n.data.label).toLowerCase().includes(normalizedQuery),
            pinned: pinned.current.has(n.id),
          },
        };
      }),
    );
    setEdges((current) =>
      current.map((e) => {
        const kind = String(e.data?.kind),
          category = ["argument", "return"].includes(kind)
            ? "call"
            : ["backedge", "merge"].includes(kind)
              ? "control"
              : kind,
          active = selectedIds.has(e.source) || selectedIds.has(e.target),
          receipt = showExecution ? execution.edges.get(e.id) : undefined;
        const label = String(e.data?.baseLabel ?? "") + (receipt?.count ? ` · ${receipt.complete ? "" : "≥"}${receipt.count}×` : "");
        return {
          ...e,
          hidden: !relations.has(category),
          label,
          data: { ...e.data, execution: receipt?.status },
          style: {
            ...e.style,
            strokeWidth: active ? 2.8 : receipt?.status === "observed" ? 2.4 : 1.4,
            strokeDasharray: kind === "backedge" ? "3 3" : kind === "call" ? "7 4" : undefined,
            opacity: dim && selection.targets.length && !active ? 0.3 : 1,
          },
        };
      }),
    );
  }, [
    selectedIds,
    selectedBlocks,
    direct,
    dim,
    query,
    relations,
    view,
    showExecution,
    execution,
    pinsRevision,
    valuesByGroup,
    structuralKey,
    layoutReady,
    state.lastSequence,
  ]);
  return (
    <div
      className="wb-graph-pane"
      data-graph-view={view}
      data-interaction={interaction}
      data-layout-state={layoutState.key === structuralKey ? layoutState.status : "pending"}
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Escape") { setMenu(undefined); setSettingsOpen(false); }
        if (
          (e.ctrlKey || e.metaKey) &&
          e.key.toLowerCase() === "a" &&
          !(e.target instanceof HTMLInputElement)
        ) {
          e.preventDefault();
          onSelection({ targets: unique([...targets.values()]), anchor: null });
        }
        if (e.key === "ContextMenu" || (e.shiftKey && e.key === "F10")) {
          const target = selection.targets[0];
          if (target) {
            e.preventDefault();
            setMenu({ x: 400, y: 250, id: [...selectedIds][0], target });
          }
        }
      }}
    >
      <div className="wb-view-toolbar graph-toolbar">
        <strong>Relations</strong>
        <select aria-label="关系图视图" value={view} onChange={e => { setView(normalizeGraphMode(e.target.value)); preference("view", e.target.value); }}>
          <option value="code">Code</option><option value="data">Data</option>
        </select>
        <button aria-label="返回上级块" disabled={!scope} onClick={() => onEnter(graph?.blocks.find(b => b.id === scope)?.parent_id ?? null)}>Back</button>
        <button aria-label="总览" disabled={!scope} onClick={() => onEnter(null)}>Root</button>
        <input type="search" aria-label="搜索计算对象" placeholder="Find" value={query} onChange={e => setQuery(e.target.value)} />
        <div className="graph-interaction-switch" role="group" aria-label="画布操作">
          <button aria-label="平移" aria-pressed={interaction === "pan"} title="Drag canvas; Shift to box-select. Blocks always drag." onClick={() => setInteraction("pan")}>Move canvas</button>
          <button aria-label="框选" aria-pressed={interaction === "select"} title="Drag empty canvas to box-select; Space to pan. Blocks always drag." onClick={() => setInteraction("select")}>Box select</button>
        </div>
        <button aria-label="自动对齐排线" disabled={!layoutReady || !projection.nodes.length} onClick={() => {
          for (const n of projection.nodes) if (!pinned.current.has(n.id)) positions.current.delete(n.id);
          fittedNavigation.current = undefined; setArrange(n => n + 1);
        }}>Arrange</button>
        <button aria-label="适应画布" disabled={!layoutReady || !projection.nodes.length} onClick={() => void flow.fitView({ padding: 0.12, minZoom: 0.01, maxZoom: 1, duration: 0 })}>Fit</button>
        <button aria-label="布局与关系" ref={settingsButton} className={settingsOpen ? "is-active" : ""} aria-expanded={settingsOpen} aria-controls={document.id + "-graph-settings"} onClick={() => setSettingsOpen(open => !open)}>Options</button>
      </div>
      <div ref={canvasRef} className="wb-graph-canvas" aria-busy={layoutState.key !== structuralKey || layoutState.status === "pending"}>
        {settingsOpen && <aside ref={settingsRef} id={document.id + "-graph-settings"} className="graph-settings" role="dialog" aria-label="布局与关系">
          <header><strong>Display</strong><button aria-label="关闭布局与关系" onClick={() => { setSettingsOpen(false); settingsButton.current?.focus(); }}><Icon name="close" size={14} /></button></header>
          <fieldset><legend>Relations</legend>
            <label><input type="checkbox" checked={dim} aria-label="淡化无关对象" onChange={e => { setDim(e.target.checked); preference("dim_unrelated", e.target.checked); }} />Dim unrelated</label>
            <label><input type="checkbox" checked={showExecution} aria-label="运行证据" onChange={e => setShowExecution(e.target.checked)} />Run evidence</label>
            <div className="graph-relationship-filters">{(view === "data" ? ["data"] : ["data", "control", "call", "block"]).map(k => <label key={k}>
              <input type="checkbox" checked={relations.has(k)} onChange={() => setRelations(old => { const next = new Set(old); next.has(k) ? next.delete(k) : next.add(k); return next; })} />
              {{ data: "Dependencies", control: "Guards", call: "Calls", block: "Blocks" }[k]}
            </label>)}</div>
          </fieldset>
          <fieldset><legend>Layout</legend><label>Direction<select aria-label="布局方向" value={direction} onChange={e => { setDirection(e.target.value); preference("direction", e.target.value); }}>
            <option value="RIGHT">Left → right</option><option value="DOWN">Top → bottom</option></select></label>
            <button aria-label="整理全部" disabled={!projection.nodes.length} onClick={() => { positions.current.clear(); pinned.current.clear(); persistPositions(); fittedNavigation.current = undefined; setArrange(n => n + 1); }}>Reset positions &amp; arrange</button>
          </fieldset>
          <fieldset><legend>Blocks</legend><div className="graph-settings-actions">
            <button aria-label="默认折叠" disabled={!graph?.blocks.length} onClick={() => setClosed({ key: foldKey, values: new Set() })}>Default</button>
            <button aria-label="展开一层" disabled={!projection.nodes.some(n => n.plate && n.collapsed)} onClick={() => setClosed(old => {
              const values = new Set(old.key === foldKey ? old.values : []); for (const n of projection.nodes) if (n.plate && n.collapsed) { values.delete(n.id); values.add("open:" + n.id); } return { key: foldKey, values };
            })}>Expand level</button>
            <button aria-label="折叠全部" disabled={!graph?.blocks.length} onClick={() => setClosed({ key: foldKey, values: new Set(graph?.blocks.map(b => b.id)) })}>Collapse all</button>
            <button aria-label="展开全部" disabled={!collapsed.size} onClick={() => setClosed({ key: foldKey, values: new Set(graph?.blocks.map(b => "open:" + b.id)) })}>Expand all</button>
          </div></fieldset>
        </aside>}
        {!graph && <div className="graph-empty">Import a Python file</div>}
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          onNodesChange={onNodesChange}
          nodesConnectable={false}
          nodesDraggable
          minZoom={0.01}
          maxZoom={2}
          onlyRenderVisibleElements
          selectionOnDrag={interaction === "select"}
          selectionKeyCode="Shift"
          selectionMode={SelectionMode.Partial}
          panActivationKeyCode="Space"
          panOnDrag={interaction === "pan" ? [0, 1] : [1]}
          selectNodesOnDrag={false}
          elevateNodesOnSelect={false}
          autoPanOnNodeFocus={false}
          autoPanOnSelection={false}
          zoomOnDoubleClick={false}
          deleteKeyCode={null}
          multiSelectionKeyCode={["Control", "Meta"]}
          proOptions={{ hideAttribution: true }}
          onPaneClick={() => { setMenu(undefined); onSelection({ targets: [], anchor: null }); }}
          onNodeClick={(e, n) => {
            const t = targets.get(n.id);
            if (t)
              onSelection(
                choose(selection, t, [...targets.values()], {
                  toggle: e.ctrlKey || e.metaKey,
                  shift: e.shiftKey,
                }),
              );
          }}
          onSelectionEnd={() => {
            const selected = flow
              .getNodes()
              .filter((n) => n.selected && n.selectable !== false)
              .flatMap((n) => (targets.get(n.id) ? [targets.get(n.id)!] : []));
            if (selected.length)
              onSelection({ targets: unique(selected), anchor: null });
          }}
          onNodeContextMenu={(e, n) => {
            e.preventDefault();
            const t = targets.get(n.id);
            if (t) {
              if (!selectedKeys.has(selectionKey(t)))
                onSelection({ targets: [t], anchor: selectionKey(t) });
              setMenu({ x: e.clientX, y: e.clientY, id: n.id, target: t });
            }
          }}
          onNodeDragStop={(_, n) => {
            positions.current.set(n.id, n.position);
            if (pinned.current.has(n.id)) persistPositions();
          }}
        >
          <Background variant={BackgroundVariant.Lines} gap={16} size={0.5} color="var(--line)" />
          <Controls showInteractive={false} fitViewOptions={{ padding: 0.18, minZoom: 0.01, maxZoom: 1.25, duration: 0 }} />
        </ReactFlow>
      </div>
      <div className="wb-graph-legend">
        {view === "data" ? <span style={{ color: edgeColors.data }}>Variable dependencies</span> : <><span style={{ color: edgeColors.data }}>Data</span><span style={{ color: edgeColors.control }}>Guard</span><span style={{ color: edgeColors.call }}>Call</span><span style={{ color: edgeColors.backedge }}>Loop</span></>}
        {showExecution && <span>Run evidence</span>}
        <span data-testid="graph-layout-metric">{projection.nodes.length} nodes · {projection.omitted} folded · {!layoutReady ? layoutState.status === "error" ? "Layout error" : "Arranging…" : `${time.toFixed(0)} ms`}</span>
      </div>
      {detailId && (() => { const node = semanticById.get(detailId); if (!node) return null; return <aside className="graph-detail" role="dialog" aria-label="计算详情">
        <header><strong>{node.label}</strong><button aria-label="关闭计算详情" onClick={() => setDetailId(undefined)}><Icon name="close" size={14} /></button></header>
        <dl><div><dt>Kind</dt><dd>{names[node.kind] ?? node.kind}</dd></div><div><dt>Source</dt><dd>{node.source?.path.split(/[\\/]/).at(-1)}{node.source ? `:${node.source.line}` : ""}</dd></div></dl>
        {node.source?.code && <pre>{node.source.code}</pre>}
        <button onClick={() => { const target = targets.get(node.id); if (target) onSource(target); }}>Open source</button>
      </aside>; })()}
      {menu && (
        <div className="context-backdrop" onClick={() => setMenu(undefined)}>
          <div
            role="menu"
            className="workspace-menu object-context"
            style={{
              left: Math.min(menu.x, innerWidth - 210),
              top: Math.min(menu.y, innerHeight - 210),
            }}
          >
            <button
              disabled={!menu.target.snapshot_id}
              onClick={() => onOpen(menu.target)}
            >
              Open data
            </button>
            <button onClick={() => onSource(menu.target)}>Open source</button>
            {menu.target.kind !== "data" && menu.target.block_id && (
              <button onClick={() => onEnter(menu.target.block_id!)}>
                Enter block
              </button>
            )}
            <button onClick={() => menu.id && setDetailId(menu.id)}>Details</button>
            <button onClick={onBind}>Bind probe</button>
            <button
              disabled={!menu.id}
              onClick={() => {
                const n = flow.getNodes().find((n) => n.id === menu.id);
                if (n) {
                  if (pinned.current.has(n.id)) pinned.current.delete(n.id);
                  else {
                    pinned.current.add(n.id);
                    positions.current.set(n.id, n.position);
                  }
                  persistPositions();
                  setPinsRevision(n => n + 1);
                }
              }}
            >
              {pinned.current.has(menu.id ?? "")
                ? "Unpin"
                : "Pin"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
export const RelationGraph = memo(function RelationGraph(
  props: Parameters<typeof GraphInner>[0],
) {
  const { research: { client }, workbench: wb } = useResearchServices();
  const [historical, setHistorical] = useState<{
      analysis: AnalysisDocument;
      state: ResearchState;
    }>(),
    [error, setError] = useState("");
  const run = props.document.reference.run_id;
  const liveState = useRef(props.state);
  liveState.current = props.state;
  useEffect(() => {
    setHistorical(undefined);
    setError("");
    if (!run) return;
    const abort = new AbortController();
    void Promise.all([
      wb.runAnalysis(run, abort.signal),
      client.bootstrap(run, abort.signal),
    ])
      .then(([analysis, boot]) => {
        if (abort.signal.aborted) return;
        const state = createState(run);
        const parents = new Map(Object.entries(boot.parent_bindings));
        for (const s of boot.snapshots) indexSnapshot(state, s, parents);
        for (const o of boot.operations) state.operations.set(o.id, o);
        state.status = boot.run.status;
        state.summary = boot.run.summary;
        state.lastSequence = boot.cursor;
        const current = liveState.current;
        setHistorical({ analysis, state: current.runId === run && current.lastSequence >= state.lastSequence ? current : state });
      })
      .catch((e) => {
        if (!abort.signal.aborted) setError(e.message);
      });
    return () => abort.abort();
  }, [run, props.document.reference.analysis_id]);
  useEffect(() => {
    if (run && props.state.runId === run)
      setHistorical(current => current && props.state.lastSequence >= current.state.lastSequence && current.state !== props.state
        ? { ...current, state: props.state } : current);
  }, [run, props.state]);
  if (run && error)
    return (
      <div className="wb-empty" role="alert">
        此运行的计算结构不可用：{error}
      </div>
    );
  if (run && !historical)
    return <div className="wb-empty">读取运行的计算结构…</div>;
  const analysis = run ? historical?.analysis : props.analysis,
    state = run && (run !== props.state.runId || props.state.lastSequence < historical!.state.lastSequence) ? historical!.state : props.state;
  const scope = analysis?.graph.blocks.some((b) => b.id === props.scope)
    ? props.scope
    : null;
  return (
    <ReactFlowProvider>
      <GraphInner {...props} analysis={analysis} state={state} scope={scope} />
    </ReactFlowProvider>
  );
});
