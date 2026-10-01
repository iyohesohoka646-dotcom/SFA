import ELK from 'elkjs/lib/elk-api';
import workerUrl from 'elkjs/lib/elk-worker.min.js?url';
import type { Node, Edge } from '@xyflow/react';
import type { ProjectSpec } from './generated';

// The bundled fake-worker API expects a document; a dedicated worker uses ELK's
// own message protocol through the small API wrapper instead.
let elk:InstanceType<typeof ELK>|undefined;
export type Point = { x: number; y: number };
export type View = { positions: Record<string, Point>; collapsed: string[]; theme: string };

export async function layoutResearch(nodes:Node[],edges:Edge[]):Promise<Map<string,Point>>{
  elk??=new ELK({workerFactory:()=>new Worker(workerUrl)});
  const graph=await elk.layout({id:'research',layoutOptions:{'elk.algorithm':'layered','elk.direction':'RIGHT','elk.spacing.nodeNode':'30','elk.layered.spacing.nodeNodeBetweenLayers':'44'},
    children:nodes.map(node=>({id:node.id,width:148,height:62})),edges:edges.map(edge=>({id:edge.id,sources:[edge.source],targets:[edge.target]}))});
  return new Map(graph.children?.map(node=>[node.id,{x:node.x||0,y:node.y||0}])||[]);
}

export async function layoutGraph(project: ProjectSpec, view: View): Promise<{ nodes: Node[]; edges: Edge[]; elapsed: number }> {
  elk??=new ELK({ workerFactory: () => new Worker(workerUrl) });
  const started = performance.now();
  const modules = project.modules || [];
  const index = new Map(modules.map(m => [m.id, m]));
  const collapsed = new Set(view.collapsed);
  function visibleAncestor(id: string): string {
    let current = index.get(id); let result = id; const visited = new Set<string>();
    while (current?.parent && !visited.has(current.id)) {
      visited.add(current.id); if (collapsed.has(current.parent)) result = current.parent;
      current = index.get(current.parent);
    }
    return result;
  }
  const visible = modules.filter(m => visibleAncestor(m.id) === m.id);
  const logicalEdges = (project.bindings || []).filter(b => b.source.kind === 'module' && b.source.module && index.has(b.source.module) && index.has(b.target));
  const children = visible.map(m => ({ id: m.id, width: 248, height: 128 + Math.max(0, Object.keys(m.contract?.input?.properties || {}).length - 2) * 20,
    ports: [{ id: m.id + ':out', properties: { side: 'EAST' } }, ...Object.keys(m.contract?.input?.properties || {}).map(p => ({ id: m.id + ':in:' + p, properties: { side: 'WEST' } }))],
    layoutOptions: { 'elk.portConstraints': 'FIXED_SIDE' } }));
  const edgesForLayout = logicalEdges.map(b => ({ id: b.id, sources: [visibleAncestor(b.source.module!)], targets: [visibleAncestor(b.target)] })).filter(e => e.sources[0] !== e.targets[0]);
  const graph = await elk.layout({ id: 'root', layoutOptions: { 'elk.algorithm': 'layered', 'elk.direction': 'RIGHT', 'elk.spacing.nodeNode': '62', 'elk.layered.spacing.nodeNodeBetweenLayers': '95', 'elk.edgeRouting': 'ORTHOGONAL', 'elk.padding': '[top=36,left=36,bottom=36,right=36]' }, children, edges: edgesForLayout });
  const coordinates = new Map(graph.children?.map(c => [c.id, { x: c.x || 0, y: c.y || 0 }]));
  const nodes: Node[] = visible.map(m => ({ id: m.id, type: 'module', position: view.positions[m.id] || coordinates.get(m.id) || { x: 0, y: 0 },
    data: { module: m, collapsed: collapsed.has(m.id), parentName: m.parent ? index.get(m.parent)?.name || m.parent : null }, ariaLabel: `${m.name || m.id}, ${m.kind} module`, dragHandle: '.node-heading' }));
  const edges: Edge[] = logicalEdges.flatMap(b => {
    const source = visibleAncestor(b.source.module!); const target = visibleAncestor(b.target);
    if (source === target) return [];
    const targetModule = index.get(target);
    return [{ id: b.id, source, target, sourceHandle: 'out', targetHandle: target === b.target ? b.port : Object.keys(targetModule?.contract?.input?.properties || {})[0], label: b.port, type: 'smoothstep',
      data: { binding: b, relation: b.provenance || 'designed' }, ariaLabel: `${source} to ${target}: ${b.port}`, style: { strokeWidth: 1.5 }, labelStyle: { fill: 'var(--muted)', fontSize: 10 }, labelBgStyle: { fill: 'var(--canvas)' }, labelBgPadding: [5, 4] as [number,number] }];
  });
  return { nodes, edges, elapsed: performance.now() - started };
}

export function reachable(edges: Edge[], start: string, direction: 'upstream' | 'downstream' | 'both'): Set<string> {
  const found = new Set([start]); const pending = [start];
  while (pending.length) {
    const current = pending.shift()!;
    for (const edge of edges) {
      const next = direction !== 'upstream' && edge.source === current ? edge.target : direction !== 'downstream' && edge.target === current ? edge.source : null;
      if (next && !found.has(next)) { found.add(next); pending.push(next); }
    }
  }
  return found;
}
