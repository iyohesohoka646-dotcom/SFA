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
import { targetSelectionKey } from "./identity";
import "./project-workspace.css";

export interface ProjectCanvasView {
  positions: Record<string, { x: number; y: number }>;
  viewport?: { x: number; y: number; zoom: number };
  collapsed: string[];
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

function ProjectNodeView({ data, selected }: NodeProps) {
  const info = data as ProjectCanvasNodeData;
  return (
    <div
      className={
        "project-node shape-" + info.shape +
        (selected ? " is-selected" : "") +
        (info.plate ? " is-plate plate-" + info.kind : "")
      }
    >
      <div className="project-node-header">
        <span className="project-node-category">{info.category}</span>
        <strong className="project-node-label" title={info.title}>{info.label}</strong>
      </div>
      {info.expression && (
        <code className="project-node-expression" title={info.expression}>{info.expression}</code>
      )}
      {info.collapsed && <span className="project-node-fold">Collapsed</span>}
      {info.handles.map((handle) => (
        <Handle
          key={handle.id}
          id={handle.id}
          type={handle.direction === "input" ? "target" : "source"}
          position={handlePosition(handle.side, handle.direction)}
          style={placedStyle(handle)}
          className={"project-handle handle-" + handle.direction + (handle.boundary ? " handle-boundary" : "")}
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
  const path = aligned ? points.map((p, i) => `${i ? "L" : "M"}${p.x},${p.y}`).join(" ") : smoothPath;
  return (
    <g>
      <title>{data?.title ?? props.label ?? ""}</title>
      <BaseEdge
        path={path}
        markerEnd={props.markerEnd}
        style={props.style}
        label={props.label}
        labelX={aligned && data?.route?.label ? data.route.label.x : smoothX}
        labelY={aligned && data?.route?.label ? data.route.label.y : smoothY}
        labelStyle={props.labelStyle}
        labelShowBg
        labelBgStyle={props.labelBgStyle}
        labelBgPadding={[5, 3]}
        labelBgBorderRadius={3}
        interactionWidth={0}
      />
    </g>
  );
}

const nodeTypes: NodeTypes = { project: ProjectNodeView };
const edgeTypes: EdgeTypes = { project: ProjectEdgeView };

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
  const [direction, setDirection] = useState<CanvasDirection>("RIGHT");
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
        setNodes(presentation.nodes.map((node) => {
          const bounds = layout.nodes.get(node.id);
          const saved = positions.current.get(node.id);
          const handles = bounds
            ? node.data.handles.map((handle) => {
                const point = bounds.ports.get(handle.id);
                return point ? { ...handle, x: point.x, y: point.y } : handle;
              })
            : node.data.handles;
          return {
            ...node,
            position: saved ?? (bounds ? { x: bounds.x, y: bounds.y } : node.position),
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
          requestAnimationFrame(() => flow.fitView({ padding: 0.2 }));
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
    onNodesChange(changes);
    for (const change of changes) {
      if (change.type === "position" && change.position) positions.current.set(change.id, change.position);
    }
  }, [onNodesChange]);

  const emitView = useCallback(() => {
    onViewChange?.({
      positions: Object.fromEntries(positions.current),
      viewport: flow.getViewport(),
      collapsed: [...overrides],
    });
  }, [onViewChange, flow, overrides]);

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
  const foldAll = () => setOverrides(new Set(graph.blocks.map((block) => block.id)));
  const unfoldAll = () => setOverrides(new Set(graph.blocks.map((block) => "open:" + block.id)));
  const folded = collapsed.size > 0;

  return (
    <div className="project-canvas">
      <div className="project-canvas-toolbar">
        {scope && (
          <button type="button" className="project-toolbar-button" onClick={() => onEnterScope(null)}>
            Back
          </button>
        )}
        <button type="button" className={"project-toolbar-button" + (mode === "pan" ? " is-active" : "")} onClick={() => setMode("pan")}>
          Move
        </button>
        <button type="button" className={"project-toolbar-button" + (mode === "select" ? " is-active" : "")} onClick={() => setMode("select")}>
          Select
        </button>
        <button type="button" className="project-toolbar-button" onClick={() => flow.fitView({ padding: 0.2 })}>Fit</button>
        <button type="button" className="project-toolbar-button" onClick={arrangeNow}>Arrange</button>
        <button type="button" className="project-toolbar-button" onClick={folded ? unfoldAll : foldAll}>
          {folded ? "Expand" : "Collapse"}
        </button>
        <button type="button" className="project-toolbar-button" onClick={() => setDirection((value) => value === "RIGHT" ? "DOWN" : "RIGHT")}>
          {direction === "RIGHT" ? "Right" : "Down"}
        </button>
        {presentation.omitted > 0 && <span className="project-omitted">{presentation.omitted} omitted</span>}
        {slice.omitted_count > 0 && <span className="project-omitted">{slice.omitted_count} server omitted</span>}
        {status === "pending" && <span className="project-canvas-status">Laying out&hellip;</span>}
        {status === "error" && <span className="project-canvas-error" role="alert">{message}</span>}
      </div>
      <div className="project-canvas-flow" onPointerLeave={() => setMenu(null)}>
        <ReactFlow<CanvasNode, CanvasEdge>
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          onNodesChange={changeNodes}
          onNodeClick={(event, node) => onSelect(node.data.target, event)}
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
          panOnDrag={mode === "pan"}
          selectionOnDrag={mode === "select"}
          fitView={false}
          proOptions={{ hideAttribution: true }}
        >
          <Background />
          <Controls showInteractive={false} />
        </ReactFlow>
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
