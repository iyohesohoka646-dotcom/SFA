import { memo, useEffect, useMemo, useRef, useState } from 'react';
import { Background, Controls, Handle, Position, ReactFlow, ReactFlowProvider, useReactFlow, useNodesState, type Edge, type Node, type NodeProps } from '@xyflow/react';
import { client } from '../client';
import { createState, indexSnapshot, type ResearchState } from '../state';
import type { SnapshotRef } from '../generated';
import { layoutResearch } from '../../graph';
import { wb } from './WorkbenchClient';
import type { AnalysisDocument } from './generated';
import type { WorkspaceDocument } from './layout';

function RelationNode({ data }: NodeProps) {
  return <div className={'relation-node ' + String(data.emphasis ?? '')} data-testid="relation-node"><Handle type="target" position={Position.Left} /><strong>{String(data.name)}</strong><small>{String(data.detail)}</small>{Boolean(data.group) && <button onClick={() => (data.expand as () => void)()}>展开</button>}<Handle type="source" position={Position.Right} /></div>;
}
const nodeTypes = { relation: RelationNode };
interface Item { id: string; name: string; scope: string; detail: string; snapshot?: SnapshotRef; objectId?: string }

function GraphInner({ document, state, analysis, selected, onSelect, onObject, onError }: {
  document: WorkspaceDocument; state: ResearchState; analysis?: AnalysisDocument; selected: string;
  onSelect: (value: SnapshotRef) => void; onObject: (id: string) => void; onError: (message: string) => void;
}) {
  const [historical, setHistorical] = useState<ResearchState>(), [oldAnalysis, setOldAnalysis] = useState<AnalysisDocument>();
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]), [edges, setEdges] = useState<Edge[]>([]), [query, setQuery] = useState('');
  const [focus, setFocus] = useState<string | null>(null), [expanded, setExpanded] = useState<Set<string>>(() => new Set());
  const [layoutTime, setLayoutTime] = useState(0), [layoutError, setLayoutError] = useState('');
  const flow = useReactFlow();
  const positions = useRef(new Map<string, { x: number; y: number }>());
  const storageKey = 'cdaf-relation-positions:' + (document.reference.run_id ?? document.reference.analysis_id);
  useEffect(() => {
    try { const saved = JSON.parse(localStorage.getItem(storageKey) ?? '{}'); for (const [id, point] of Object.entries(saved).slice(0, 512)) { const p = point as { x: number; y: number }; if (Number.isFinite(p.x) && Number.isFinite(p.y)) positions.current.set(id, p); } } catch { /* fresh positions */ }
  }, [storageKey]);
  useEffect(() => {
    const abort = new AbortController(), run = document.reference.run_id;
    if (run && run !== state.runId) void client.bootstrap(run, abort.signal).then(data => {
      const next = createState(run); const parents = new Map(Object.entries(data.parent_bindings));
      for (const value of data.snapshots) indexSnapshot(next, value, parents);
      next.status = data.run.status; setHistorical(next);
    }).catch(error => { if (!abort.signal.aborted) onError(error.message); });
    if (!run && document.reference.analysis_id && analysis?.id !== document.reference.analysis_id) void wb.analysis(document.reference.analysis_id, abort.signal).then(setOldAnalysis).catch(error => { if (!abort.signal.aborted) onError(error.message); });
    return () => abort.abort();
  }, [document.id]);
  const current = document.reference.run_id === state.runId ? state : historical;
  const source = analysis?.id === document.reference.analysis_id ? analysis : oldAnalysis;
  const topology = current?.topologyVersion ?? 0;
  const model = useMemo(() => {
    const items: Item[] = document.reference.run_id ? [...(current?.latest.values() ?? [])].map(s => ({ id: s.binding_id, name: s.name,
      scope: s.scope_id.split(':')[0], detail: `${s.descriptor.shape?.join(' × ') ?? s.descriptor.kind} · v${s.version}`, snapshot: s })) :
      (source?.objects ?? []).filter(o => o.kind !== 'parameter').map(o => ({ id: o.id, name: o.qualname, scope: o.scope, detail: `${o.kind} · L${o.line}`, objectId: o.id }));
    const relations = document.reference.run_id ? items.flatMap(item => (current?.dependencies.get(item.id) ?? []).map(parent => ({ source: parent, target: item.id, provenance: item.snapshot?.provenance ?? 'unknown' }))) : (source?.relations ?? []);
    return { items, relations };
  }, [current?.runId, topology, source?.id]);
  useEffect(() => setFocus(null), [selected]);
  const chosen = focus ?? selected;
  const direct = useMemo(() => ({ incoming: new Set(model.relations.filter(r => r.target === chosen).map(r => r.source)), outgoing: new Set(model.relations.filter(r => r.source === chosen).map(r => r.target)) }), [model, chosen]);
  const projection = useMemo(() => {
    const buckets = new Map<string, Item[]>(), mapping = new Map<string, string>(), visible: Item[] = [];
    for (const item of model.items) {
      const bucket = model.items.length > 180 ? item.scope + ' / ' + (item.name.match(/^(.*?)[\d_]+$/)?.[1] || item.scope) : item.scope;
      const bucketItems = buckets.get(bucket) ?? []; bucketItems.push(item); buckets.set(bucket, bucketItems);
    }
    for (const [bucket, items] of buckets) {
      const filtered = query ? items.filter(i => i.name.toLowerCase().includes(query.toLowerCase()) || i.id === chosen || direct.incoming.has(i.id) || direct.outgoing.has(i.id)) : items;
      if (!filtered.length) continue;
      const collapsed = !query && items.length > 40 && !expanded.has(bucket);
      if (collapsed) {
        const id = 'group:' + bucket;
        const adjacent = filtered.filter(i => i.id === chosen || direct.incoming.has(i.id) || direct.outgoing.has(i.id));
        visible.push(...adjacent.slice(0, 40));
        for (const item of adjacent) mapping.set(item.id, item.id);
        visible.push({ id, name: bucket.replace('<module> / ', ''), scope: bucket, detail: `${items.length} 个对象 · 折叠` });
        for (const item of items) if (!mapping.has(item.id)) mapping.set(item.id, id);
      } else for (const item of filtered.slice(0, 160 - visible.length)) { visible.push(item); mapping.set(item.id, item.id); }
    }
    const relations = new Map<string, { source: string; target: string; provenance: string }>();
    for (const relation of model.relations) { const source = mapping.get(relation.source), target = mapping.get(relation.target); if (source && target && source !== target) relations.set(source + '>' + target, { ...relation, source, target }); }
    return { items: visible.slice(0, 160), relations: [...relations.values()].slice(0, 512), total: model.items.length };
  }, [model, expanded, query, model.items.length > 180 ? chosen : '']);
  const key = projection.items.map(i => i.id).join('|') + projection.relations.map(r => r.source + '>' + r.target).join('|');
  useEffect(() => {
    let live = true; const started = performance.now();
    const seed: Node[] = projection.items.map((item, index) => ({ id: item.id, type: 'relation', position: positions.current.get(item.id) ?? { x: index % 5 * 190, y: Math.floor(index / 5) * 90 },
      data: { name: item.name, detail: item.detail, group: item.id.startsWith('group:'), expand: () => setExpanded(old => new Set([...old, item.scope])) }, ariaLabel: item.name }));
    const lines: Edge[] = projection.relations.map(r => ({ id: r.source + '>' + r.target, source: r.source, target: r.target, type: 'smoothstep', data: { provenance: r.provenance },
      ariaLabel: r.provenance + ' · ' + r.source + ' → ' + r.target, style: { stroke: '#78969c', strokeWidth: 1.2, strokeDasharray: r.provenance === 'observed' ? undefined : '5 4' } }));
    setNodes(seed); setEdges(lines); setLayoutError('');
    void layoutResearch(seed, lines).then(points => { if (!live) return; setNodes(current => current.map(node => ({ ...node, position: positions.current.get(node.id) ?? points.get(node.id) ?? node.position }))); setLayoutTime(performance.now() - started);
      requestAnimationFrame(() => requestAnimationFrame(() => { if (live) void flow.fitView({ padding: .2, maxZoom: 1.25, duration: 0 }); }));
    }).catch(error => { if (live) setLayoutError(error.message); });
    return () => { live = false; };
  }, [key]);
  useEffect(() => {
    setNodes(current => current.map(node => ({ ...node, data: { ...node.data, emphasis: !chosen ? '' : node.id === chosen ? 'relation-focus' : direct.incoming.has(node.id) ? 'relation-parent' : direct.outgoing.has(node.id) ? 'relation-consumer' : 'relation-muted' } })));
    setEdges(current => current.map(edge => ({ ...edge, style: { ...edge.style, stroke: edge.target === chosen ? '#167760' : edge.source === chosen ? '#356caa' : '#78969c', strokeWidth: edge.source === chosen || edge.target === chosen ? 2.2 : 1.2, opacity: chosen && edge.source !== chosen && edge.target !== chosen ? .45 : 1 } })));
  }, [chosen, key]);
  return <div className="wb-graph-pane"><div className="wb-view-toolbar"><strong>计算关系图</strong><input type="search" aria-label="搜索计算对象" placeholder="搜索对象" value={query} onChange={e => setQuery(e.target.value)} /><button onClick={() => { setFocus(''); setExpanded(new Set()); setQuery(''); }}>总览</button><button onClick={() => void flow.fitView({ padding: .2, duration: 0 })}>适应画布</button></div>
    <div className="wb-graph-canvas"><ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} onNodesChange={onNodesChange} nodesConnectable={false} minZoom={.02} maxZoom={2} proOptions={{ hideAttribution: true }} onNodeClick={(_, node) => { if (node.id.startsWith('group:')) return; setFocus(node.id); const item = model.items.find(i => i.id === node.id); if (item?.snapshot) onSelect(item.snapshot); if (item?.objectId) onObject(item.objectId); }}
      onNodeDragStop={(_, node) => { positions.current.set(node.id, node.position); try { localStorage.setItem(storageKey, JSON.stringify(Object.fromEntries(positions.current))); } catch { /* in-memory position */ } }}><Background color="#dfe7e9" gap={22} /><Controls showInteractive={false} /></ReactFlow></div>
    <div className="wb-graph-legend"><span className="legend-parent">直接输入</span><span className="legend-consumer">直接下游</span><span>实线：观察 · 虚线：推断</span><span data-testid="graph-layout-metric">{projection.items.length}/{projection.total} · 布局 {layoutTime.toFixed(0)} ms</span></div>
    {layoutError && <div role="alert">{layoutError}</div>}
  </div>;
}
export const RelationGraph = memo(function RelationGraph(props: Parameters<typeof GraphInner>[0]) { return <ReactFlowProvider><GraphInner {...props} /></ReactFlowProvider>; });
