/** Controlled project canvas: an ELK-laid-out React Flow view of a graph slice.
 *
 * The component is fully controlled: selection, scope and folded state flow
 * through props/callbacks. Selection overlays never appear in layout deps, so
 * selecting a node cannot trigger a relayout. Stale ELK responses are cancelled
 * whenever the slice identity changes (the inner view is keyed by identity).
 *
 * The parent batch selection is emitted only for an explicit user box gesture:
 * programmatic (overlay) selection updates never round-trip through the parent,
 * so a selection made outside the visible graph survives in the browser.
 */
import {
  createContext,
  useContext,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
} from "react";
import {
  Background,
  BaseEdge,
  Controls,
  Handle,
  Position,
  ReactFlow,
  ReactFlowProvider,
  getSmoothStepPath,
  useNodesState,
  useReactFlow,
  type EdgeProps,
  type NodeProps,
  type NodeTypes,
  type EdgeTypes,
  type OnNodesChange,
  type EdgeMouseHandler,
} from "@xyflow/react";
import type { ProjectGraphSlice, TargetRef } from "./generated";
import { initialCollapsed } from "../workspace/graph-projection";
import {
  presentProjectGraph,
  type CanvasDirection,
  type CanvasEdge,
  type CanvasHandle,
  type CanvasNode,
  type ProjectCanvasEdgeData,
  type ProjectCanvasNodeData,
} from "./graphPresentation";
import { layoutSemantic } from "../../graph";
import { readableGraphViewport, semanticLayoutBounds } from "../../graph-semantic-layout";
import { targetSelectionKey } from "./identity";
import "./project-workspace.css";

export interface ProjectCanvasView {
  positions: Record<string, { x: number; y: number }>;
  viewport?: { x: number; y: number; zoom: number };
  collapsed: string[];
  direction?: CanvasDirection;
  focus?: boolean;
}

export interface ProjectCanvasProps {
  slice: ProjectGraphSlice;
  selected: TargetRef[];
  onSelect(target: TargetRef, event: ReactMouseEvent): void;
  onSelectionChange?(targets: TargetRef[], event?: ReactMouseEvent): void;
  onOpenSource(source: TargetRef): void;
  onEnterScope(id: string | null): void;
  onViewChange?(view: ProjectCanvasView): void;
  savedView?: ProjectCanvasView;
}

const selKey = (target: TargetRef) => targetSelectionKey(target);
const FoldContext = createContext<(id: string) => void>(() => {});

function NodeGlyph({ shape }: { shape: string }) {
  return <svg className="project-node-glyph" width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true">
    {shape === "circle" ? <circle cx="9" cy="9" r="6" /> : shape === "diamond" ? <path d="M9 2 16 9 9 16 2 9Z" /> : <rect x="3" y="3" width="12" height="12" rx="2" />}
  </svg>;
}

function handlePosition(side: string | undefined, direction: "input" | "output"): Position {
  if (side === "NORTH") return Position.Top;
  if (side === "SOUTH") return Position.Bottom;
  if (side === "WEST") return Position.Left;
  if (side === "EAST") return Position.Right;
  return direction === "input" ? Position.Left : Position.Right;
}

function placedStyle(handle: CanvasHandle) {
  return handle.x !== undefined && handle.y !== undefined
    ? { left: handle.x, top: handle.y, transform: "translate(-50%, -50%)" }
    : undefined;
}

function insideParent(position: { x: number; y: number }, node: CanvasNode, parent?: CanvasNode) {
  if (!parent) return position;
  const left = 24, top = parent.data.headerHeight + 12;
  return {
    x: Math.max(left, Math.min(position.x, Number(parent.width) - Number(node.width) - left)),
    y: Math.max(top, Math.min(position.y, Number(parent.height) - Number(node.height) - 24)),
  };
}

function ProjectNodeView({ id, data, selected }: NodeProps) {
  const info = data as ProjectCanvasNodeData;
  const toggle = useContext(FoldContext);
  return (
    <div
      className={
        "project-node shape-" + info.shape +
        (selected ? " is-selected" : "") +
        (info.plate ? " is-plate plate-" + info.kind : "") +
        (info.plate && !info.collapsed ? " is-expanded" : " is-compact") + " kind-" + info.kind
      }
    >
      <div className="project-node-header" style={{ height: info.headerHeight }}>
        <NodeGlyph shape={info.shape} />
        <div className="project-node-heading">
          <span className="project-node-category">{info.category}</span>
          <strong className="project-node-label" title={info.title}>{info.label}</strong>
        </div>
        {info.plate && <button className="project-fold-button nodrag nopan" type="button" aria-label={`${info.collapsed ? "Expand" : "Collapse"} group ${info.label}`} aria-expanded={!info.collapsed} onClick={event => { event.stopPropagation(); toggle(id); }}>
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><path d="M3 7h8" />{info.collapsed && <path d="M7 3v8" />}</svg>
        </button>}
      </div>
      {info.collapsed && <span className="project-node-fold">{info.summary}</span>}
      {info.handles.map(handle => <span key={"name:" + handle.id} className={`project-port-label port-${handle.direction} side-${handle.side ?? "WEST"}`} title={handle.name}
        style={handle.side === "NORTH" || handle.side === "SOUTH" ? { left: handle.x, top: handle.y } : { top: handle.y }}>
        {handle.name}
      </span>)}
      {info.handles.map((handle) => (
        <Handle
          key={handle.id}
          id={handle.id}
          type={handle.direction === "input" ? "target" : "source"}
          position={handlePosition(handle.side, handle.direction)}
          style={placedStyle(handle)}
          className={"project-handle handle-" + handle.direction + (handle.boundary ? " handle-boundary" : "")}
          isConnectable={false}
          title={`${handle.direction === "input" ? "Input" : "Output"}: ${handle.name}`}
        />
      ))}
    </div>
  );
}

function ProjectEdgeView(props: EdgeProps) {
  const data = props.data as ProjectCanvasEdgeData | undefined;
  const [smoothPath, smoothX, smoothY] = getSmoothStepPath(props);
  const points = data?.route?.points ?? [];
  const aligned =
    points.length >= 2 &&
    Math.abs(points[0].x - props.sourceX) < 12 && Math.abs(points[0].y - props.sourceY) < 12 &&
    Math.abs(points[points.length - 1].x - props.targetX) < 12 && Math.abs(points[points.length - 1].y - props.targetY) < 12;
  // A whole group may move without changing its internal routing channels.
  // Translate that route; for independently moved endpoints use live handles.
  const first = points[0], last = points.at(-1);
  const dx = first ? props.sourceX - first.x : 0, dy = first ? props.sourceY - first.y : 0;
  const translated = first && last && Math.abs(props.targetX - last.x - dx) < 9 && Math.abs(props.targetY - last.y - dy) < 9;
  const routed = aligned ? points : translated ? points.map(p => ({ x: p.x + dx, y: p.y + dy })) : [];
  const path = routed.length ? roundedRoute(routed) : smoothPath;
  return (
    <g>
      <title>{data?.title ?? props.label ?? ""}</title>
      <BaseEdge
        path={path}
        markerEnd={props.markerEnd}
        style={props.style}
        label={props.label}
        labelX={routed.length && data?.route?.label ? data.route.label.x + (aligned ? 0 : dx) : smoothX}
        labelY={routed.length && data?.route?.label ? data.route.label.y + (aligned ? 0 : dy) : smoothY}
        labelStyle={props.labelStyle}
        labelShowBg
        labelBgStyle={props.labelBgStyle}
        labelBgPadding={[5, 3]}
        labelBgBorderRadius={3}
        interactionWidth={16}
      />
    </g>
  );
}

/** Small corner radii preserve ELK's orthogonal channels and avoid hard elbows. */
function roundedRoute(points: { x: number; y: number }[]) {
  let path = `M${points[0].x},${points[0].y}`;
  for (let i = 1; i < points.length - 1; i++) {
    const a = points[i - 1], b = points[i], c = points[i + 1];
    const before = Math.hypot(b.x - a.x, b.y - a.y), after = Math.hypot(c.x - b.x, c.y - b.y);
    if (!before || !after) continue;
    const radius = Math.min(7, before / 2, after / 2);
    const x = b.x - (b.x - a.x) / before * radius, y = b.y - (b.y - a.y) / before * radius;
    const u = b.x + (c.x - b.x) / after * radius, v = b.y + (c.y - b.y) / after * radius;
    path += ` L${x},${y} Q${b.x},${b.y} ${u},${v}`;
  }
  const last = points.at(-1)!;
  return path + ` L${last.x},${last.y}`;
}

const nodeTypes: NodeTypes = { project: ProjectNodeView };
const edgeTypes: EdgeTypes = { project: ProjectEdgeView };
const fitOptions = { padding: 0.2, minZoom: 0.01, maxZoom: 1.25, duration: 0 };

function CanvasInner({
  slice,
  selected,
  onSelect,
  onSelectionChange,
  onOpenSource,
  onEnterScope,
  onViewChange,
  savedView,
  identity,
}: ProjectCanvasProps & { identity: string }) {
  const flow = useReactFlow();
  const [nodes, setNodes, onNodesChange] = useNodesState<CanvasNode>([]);
  const [edges, setEdges] = useState<CanvasEdge[]>([]);
  const [overrides, setOverrides] = useState<Set<string>>(() => new Set(savedView?.collapsed ?? []));
  const [direction, setDirection] = useState<CanvasDirection>(savedView?.direction ?? "RIGHT");
  const [focus, setFocus] = useState(savedView?.focus ?? false);
  const [relationId, setRelationId] = useState<string | null>(null);
  const [hoverId, setHoverId] = useState<string | null>(null);
  const [mode, setMode] = useState<"pan" | "select">("pan");
  const [arrange, setArrange] = useState(0);
  const [status, setStatus] = useState<"pending" | "ready" | "error">("pending");
  const [message, setMessage] = useState("");
  const [menu, setMenu] = useState<{ x: number; y: number; target: TargetRef } | null>(null);
  const positions = useRef(new Map(Object.entries(savedView?.positions ?? {})));
  const fitted = useRef(savedView?.viewport ? identity : "");
  const latest = useRef<CanvasNode[]>(nodes);
  latest.current = nodes;
  const boxGesture = useRef(false);
  const pane = useRef<HTMLDivElement>(null);

  const scope = slice.scope_id;
  const graph = slice.graph;

  const selection = useMemo(() => new Set(selected.map(selKey)), [selected]);
  const selectionRef = useRef(selection);
  selectionRef.current = selection;

  useEffect(() => {
    if (savedView?.viewport) flow.setViewport(savedView.viewport);
  }, [flow, savedView]);

  const collapsed = useMemo(() => initialCollapsed(graph, overrides, scope), [graph, overrides, scope]);
  const presentation = useMemo(
    () => presentProjectGraph(slice, collapsed, direction),
    [slice, collapsed, direction],
  );

  useEffect(() => {
    let cancelled = false;
    setStatus("pending");
    setMessage("");
    const run = async () => {
      try {
        const layout = await layoutSemantic(presentation.nodes, presentation.edges, direction);
        if (cancelled) return;
        const measured = new Map(presentation.nodes.map(node => {
          const bounds = layout.nodes.get(node.id);
          return [node.id, { ...node, width: bounds?.width ?? node.width, height: bounds?.height ?? node.height }];
        }));
        setNodes(presentation.nodes.map((node) => {
          const bounds = layout.nodes.get(node.id);
          const manual = positions.current.get(node.id);
          const saved = manual ? insideParent(manual, measured.get(node.id)!, measured.get(node.parentId ?? "")) : undefined;
          if (saved) positions.current.set(node.id, saved);
          const handles = bounds
            ? node.data.handles.map((handle) => {
                const point = bounds.ports.get(handle.id);
                return point ? { ...handle, x: point.x, y: point.y, side: direction === "DOWN" ? handle.direction === "input" ? "NORTH" as const : "SOUTH" as const : handle.direction === "input" ? "WEST" as const : "EAST" as const } : handle;
              })
            : node.data.handles;
          return {
            ...node,
            position: saved ?? (bounds ? { x: bounds.x, y: bounds.y } : node.position),
            width: bounds?.width ?? node.width,
            height: bounds?.height ?? node.height,
            style: bounds ? { ...node.style, width: bounds.width, height: bounds.height } : node.style,
            selected: selectionRef.current.has(selKey(node.data.target)),
            data: { ...node.data, handles },
          };
        }));
        setEdges(presentation.edges.map((edge) => ({
          ...edge,
          data: { ...(edge.data as ProjectCanvasEdgeData), route: layout.edges.get(edge.id) },
        })));
        setStatus("ready");
        if (fitted.current !== identity) {
          fitted.current = identity;
          requestAnimationFrame(() => {
            const bounds = semanticLayoutBounds(presentation.nodes, layout);
            const box = pane.current?.getBoundingClientRect();
            const viewport = bounds && box ? readableGraphViewport(bounds, box) : undefined;
            if (viewport) flow.setViewport(viewport);
          });
        }
      } catch (error) {
        if (cancelled) return;
        setStatus("error");
        setMessage(error instanceof Error ? error.message : "layout failed");
      }
    };
    void run();
    return () => { cancelled = true; };
    // Selection is intentionally excluded: it must never cause a relayout.
  }, [presentation, direction, arrange, identity, flow, setNodes]);

  // Controlled selection overlay sync. Programmatic selection updates are a
  // one-way projection of the `selected` prop and never notify the parent.
  useEffect(() => {
    setNodes((current) => current.map((node) => ({ ...node, selected: selection.has(selKey(node.data.target)) })));
  }, [selection, setNodes]);

  const changeNodes = useCallback<OnNodesChange<CanvasNode>>((changes) => {
    const byId = new Map(latest.current.map(node => [node.id, node]));
    const constrained = changes.map(change => {
      if (change.type !== "position" || !change.position) return change;
      const node = byId.get(change.id);
      return node ? { ...change, position: insideParent(change.position, node, byId.get(node.parentId ?? "")) } : change;
    });
    onNodesChange(constrained);
    for (const change of constrained) {
      if (change.type === "position" && change.position) positions.current.set(change.id, change.position);
    }
  }, [onNodesChange]);

  const emitView = useCallback(() => {
    onViewChange?.({
      positions: Object.fromEntries(positions.current),
      viewport: flow.getViewport(),
      collapsed: [...overrides],
      direction,
      focus,
    });
  }, [onViewChange, flow, overrides, direction, focus]);
  const emitRef = useRef(emitView);
  emitRef.current = emitView;
  useEffect(() => {
    if (status !== "ready") return;
    const frame = requestAnimationFrame(() => emitRef.current());
    return () => cancelAnimationFrame(frame);
  }, [status, overrides, direction, arrange, focus]);

  // A box gesture is the only user action that replaces the whole selection
  // set, so it is the only place a batch change is reported. The frame wait
  // reads the committed controlled nodes instead of the pointer-up snapshot.
  const emitBoxSelection = useCallback(
    (event: ReactMouseEvent) => {
      if (!boxGesture.current) return;
      boxGesture.current = false;
      requestAnimationFrame(() => {
        onSelectionChange?.(
          latest.current.filter((node) => node.selected).map((node) => node.data.target),
          event,
        );
      });
    },
    [onSelectionChange],
  );

  const arrangeNow = () => { positions.current = new Map(); setArrange((value) => value + 1); };
  const foldAll = () => setOverrides(new Set());
  const expandLevel = () => setOverrides(current => {
    const next = new Set(current);
    for (const node of presentation.nodes) if (node.data.plate && node.data.collapsed) {
      next.delete(node.id); next.add("open:" + node.id);
    }
    return next;
  });
  const folded = collapsed.size > 0;
  const toggleFold = useCallback((id: string) => {
    setOverrides(current => {
      const next = new Set(current);
      next.delete(id); next.delete("open:" + id);
      next.add(collapsed.has(id) ? "open:" + id : id);
      return next;
    });
  }, [collapsed]);
  const activeRelation = edges.find(edge => edge.id === relationId);
  const activeEdge = edges.find(edge => edge.id === (hoverId ?? relationId));
  const activeIds = activeEdge ? new Set([activeEdge.source, activeEdge.target]) : new Set(nodes.filter(node => selection.has(selKey(node.data.target))).map(node => node.id));
  const related = new Set<string>();
  const adjacent = new Set(activeIds);
  for (const edge of edges) if (activeEdge ? edge.id === activeEdge.id : activeIds.has(edge.source) || activeIds.has(edge.target)) {
    related.add(edge.id); adjacent.add(edge.source); adjacent.add(edge.target);
  }
  const displayEdges = edges.map(edge => ({ ...edge, className: edge.className + (related.has(edge.id) ? " is-related-edge" : focus && activeIds.size ? " is-muted-edge" : "") }));
  const displayNodes = nodes.map(node => ({ ...node, className: focus && activeIds.size && !adjacent.has(node.id) && !node.data.plate ? "is-muted-node" : undefined }));
  const selectEdge: EdgeMouseHandler<CanvasEdge> = (_event, edge) => setRelationId(edge.id);

  return (
    <div className="project-canvas" data-interaction={mode}>
      <div className="project-canvas-toolbar">
        <button type="button" title="Drag the background to move; drag a node header to reposition" aria-pressed={mode === "pan"} className={"project-toolbar-button" + (mode === "pan" ? " is-active" : "")} onClick={() => setMode("pan")}>
          Move
        </button>
        <button type="button" title="Drag the background to select a region" aria-pressed={mode === "select"} className={"project-toolbar-button" + (mode === "select" ? " is-active" : "")} onClick={() => setMode("select")}>
          Select
        </button>
        <button type="button" className="project-toolbar-button" onClick={() => flow.fitView(fitOptions)}>Fit</button>
        <button type="button" title="Align blocks and route connections automatically" className="project-toolbar-button" onClick={arrangeNow} disabled={status === "pending"}>Arrange</button>
        <button type="button" className="project-toolbar-button" title="Expand the next visible level" disabled={!folded} onClick={expandLevel}>Expand</button>
        <button type="button" className="project-toolbar-button" title="Return to the folded overview" onClick={foldAll}>Collapse</button>
        <button type="button" className={"project-toolbar-button" + (focus ? " is-active" : "")} aria-pressed={focus} title="Dim unrelated nodes and connections" onClick={() => setFocus(value => !value)}>Focus</button>
        <button type="button" className="project-toolbar-button" onClick={() => setDirection((value) => value === "RIGHT" ? "DOWN" : "RIGHT")}>
          {direction === "RIGHT" ? "Right" : "Down"}
        </button>
        {presentation.omitted > 0 && <span className="project-omitted">{presentation.omitted} folded</span>}
        {slice.omitted_count > 0 && <span className="project-omitted">{slice.omitted_count} server omitted</span>}
        {status === "pending" && <span className="project-canvas-status">Laying out&hellip;</span>}
        {status === "error" && <span className="project-canvas-error" role="alert">{message}</span>}
      </div>
      <div className="project-canvas-flow" ref={pane} onPointerLeave={() => setMenu(null)}>
        <FoldContext.Provider value={toggleFold}>
        <ReactFlow<CanvasNode, CanvasEdge>
          nodes={displayNodes}
          edges={displayEdges}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          onNodesChange={changeNodes}
          onNodeClick={(event, node) => { setRelationId(null); onSelect(node.data.target, event); }}
          onPaneClick={() => { setRelationId(null); setMenu(null); }}
          onEdgeClick={selectEdge}
          onEdgeMouseEnter={(_event, edge) => setHoverId(edge.id)}
          onEdgeMouseLeave={() => setHoverId(null)}
          onNodeDoubleClick={(_event, node) => onOpenSource(node.data.target)}
          onNodeContextMenu={(event, node) => {
            event.preventDefault();
            setMenu({ x: event.clientX, y: event.clientY, target: node.data.target });
          }}
          onNodeDragStop={() => emitView()}
          onMoveEnd={() => emitView()}
          onSelectionStart={() => { boxGesture.current = true; }}
          onSelectionEnd={emitBoxSelection}
          nodesDraggable
          nodesConnectable={false}
          snapToGrid
          snapGrid={[16, 16]}
          panOnDrag={mode === "pan"}
          selectionOnDrag={mode === "select"}
          fitView={false}
          minZoom={0.01}
          proOptions={{ hideAttribution: true }}
        >
          <Background gap={16} size={1} color="var(--project-grid)" />
          <Controls showInteractive={false} fitViewOptions={fitOptions} />
        </ReactFlow>
        </FoldContext.Provider>
        <div className="project-graph-legend" aria-label="Relationship legend"><span className="legend-data">Data</span><span className="legend-call">Call</span><span className="legend-control">Control</span></div>
        {activeRelation && <aside className="project-relation-detail" aria-label="Relationship details">
          <button type="button" aria-label="Close relationship details" onClick={() => setRelationId(null)}>×</button>
          <strong>{activeRelation.data?.sourceLabel} → {activeRelation.data?.targetLabel}</strong>
          <span>{activeRelation.data?.title}</span>
          <small>{activeRelation.data?.provenance} · {activeRelation.data?.count} relation{activeRelation.data?.count === 1 ? "" : "s"}</small>
        </aside>}
        {menu && (
          <div className="project-context-menu" style={{ left: menu.x, top: menu.y }} role="menu">
            <button type="button" role="menuitem" onClick={(event) => { onSelect(menu.target, event); setMenu(null); }}>Select</button>
            <button type="button" role="menuitem" onClick={() => { onOpenSource(menu.target); setMenu(null); }}>Open source</button>
            {menu.target.block_id && (
              <button type="button" role="menuitem" onClick={() => { onEnterScope(menu.target.block_id); setMenu(null); }}>Enter group</button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export default function ProjectCanvas(props: ProjectCanvasProps) {
  const identity = `${props.slice.project_id}:${props.slice.revision_id}:${props.slice.scope_id ?? "root"}:${props.slice.view}`;
  return (
    <ReactFlowProvider>
      <CanvasInner key={identity} identity={identity} {...props} />
    </ReactFlowProvider>
  );
}
