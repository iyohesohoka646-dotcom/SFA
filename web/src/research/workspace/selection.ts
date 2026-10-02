import type {AnalysisDocument,SemanticGraph,TargetRef,GraphNode,GraphBlock,GraphEdge,ScopeSelector} from './generated';
import type {SnapshotRef} from '../generated';
export interface Selection {targets:TargetRef[];anchor:string|null}
export const selectionKey=(t:TargetRef)=>t.kind+':'+t.logical_key;
export function choose(state:Selection,target:TargetRef,order:TargetRef[],action:{toggle?:boolean;shift?:boolean;all?:boolean}):Selection{
 const key=selectionKey(target);
 if(action.all)return {targets:unique(order),anchor:key};
 if(action.shift&&state.anchor){const a=order.findIndex(t=>selectionKey(t)===state.anchor),b=order.findIndex(t=>selectionKey(t)===key);if(a>=0&&b>=0)return {targets:unique(action.toggle?[...state.targets,...order.slice(Math.min(a,b),Math.max(a,b)+1)]:order.slice(Math.min(a,b),Math.max(a,b)+1)),anchor:state.anchor};}
 if(action.toggle)return {targets:state.targets.some(t=>selectionKey(t)===key)?state.targets.filter(t=>selectionKey(t)!==key):[...state.targets,target],anchor:key};
 return {targets:[target],anchor:key};
}
export const unique=(items:TargetRef[])=>[...new Map(items.map(t=>[selectionKey(t),t])).values()];
export interface ObjectRow{id:string;parent?:string;depth:number;label:string;detail:string;target:TargetRef;block?:GraphBlock;snapshot?:SnapshotRef;objectId?:string}
export function objectRows(analysis:AnalysisDocument|undefined,values:SnapshotRef[],scope:string|null,expanded:Set<string>,query='',type='all'):ObjectRow[]{
 if(!analysis)return [];
 const blocks=analysis.graph.blocks, index=new Map(blocks.map(b=>[b.id,b]));
 const inScope=(id:string|undefined)=>{if(!scope)return true;const visited=new Set<string>();while(id&&!visited.has(id)){if(id===scope)return true;visited.add(id);id=index.get(id)?.parent_id??undefined;}return false;};
 const current=new Map(values.map(s=>[s.logical_key,s]));
 const rows:ObjectRow[]=[],objects=new Map<string,AnalysisDocument['objects']>();
 const canonical=new Map<string,AnalysisDocument['objects'][number]>();
 for(const o of [...analysis.objects].sort((a,b)=>a.line-b.line||a.column-b.column)){if(o.kind==='function'||o.kind==='class'||o.kind==='step'||o.kind==='import')continue;if(!scope&&canonical.has(o.logical_key))continue;canonical.set(o.logical_key,o);const list=objects.get(o.block_id)??[];list.push(o);objects.set(o.block_id,list);}
 const known=new Set(analysis.objects.map(o=>o.logical_key));
 const pass=(name:string,detail:string)=> (name+' '+detail).toLowerCase().includes(query.toLowerCase())&&(type==='all'||detail.includes(type));
 function visit(block:GraphBlock,depth:number){
  if(!inScope(block.id)&&scope!==block.id)return;
  const target={kind:block.kind==='function'?'function':block.kind==='file'?'file':'control',logical_key:block.logical_key,block_id:block.id,object_id:block.source_object_id,analysis_id:analysis!.id} as TargetRef;
  const children=objects.get(block.id)??[];
  const nested=blocks.filter(b=>b.parent_id===block.id);
  const matches=children.some(o=>pass(o.name,current.get(o.logical_key)?.descriptor.kind??o.kind));
  const blockMatches=pass(block.label,block.kind)||matches||query&&nested.length;
  if(!query||blockMatches)rows.push({id:block.id,depth,label:block.label,detail:block.kind,target,block,objectId:block.source_object_id??undefined});
  if(!expanded.has(block.id)&&!query)return;
  for(const child of nested)visit(child,depth+1);
  const emitted=new Set<string>();
  for(const o of children){if(emitted.has(o.logical_key))continue;emitted.add(o.logical_key);const snapshot=current.get(o.logical_key),detail=snapshot?`${snapshot.descriptor.dtype??snapshot.descriptor.kind} · ${snapshot.descriptor.shape?.join(' × ')??''} · v${snapshot.version}`:o.kind+` · L${o.line}`;
   if(!pass(o.name,detail))continue;
   rows.push({id:selectionKey({kind:'data',logical_key:o.logical_key} as TargetRef),depth:depth+1,label:o.name,detail,objectId:o.id,snapshot,target:{kind:'data',logical_key:o.logical_key,object_id:o.id,block_id:block.id,analysis_id:analysis!.id,run_id:snapshot?.run_id,snapshot_id:snapshot?.id} as TargetRef});
  }
 }
 for(const block of blocks.filter(b=>b.id===scope||!scope&&!b.parent_id))visit(block,0);
 if(!scope)for(const s of values.filter(s=>!known.has(s.logical_key))){if(pass(s.name,s.descriptor.kind))rows.push({id:s.id,depth:1,label:s.name,detail:s.descriptor.kind+' · 派生',snapshot:s,target:{kind:'data',logical_key:s.logical_key??s.binding_id,snapshot_id:s.id,run_id:s.run_id} as TargetRef});}
 return rows;
}
export type ProjectionNode=(GraphNode|GraphBlock)&{parent_id?:string|null;plate?:boolean};
export function projectGraph(graph:SemanticGraph,collapsed:Set<string>,view:'structure'|'data'|'execution',scope?:string|null){
 const parent=new Map<string,string|undefined>([...graph.blocks.map(b=>[b.id,b.parent_id??undefined] as const),...graph.nodes.map(n=>[n.id,n.block_id] as const)]);
 function under(id:string,ancestor:string){const seen=new Set<string>();while(id&&!seen.has(id)){if(id===ancestor)return true;seen.add(id);id=parent.get(id)??'';}return false;}
 const representative=(id:string)=>{let result=id,current=parent.get(id);const seen=new Set<string>();while(current&&!seen.has(current)){seen.add(current);if(collapsed.has(current)&&current!==scope)result=current;current=parent.get(current);}return result;};
 const blocks=graph.blocks.filter(b=>(!scope||under(b.id,scope))&&representative(b.id)===b.id);
 const nodes:ProjectionNode[]=[...blocks.map(b=>({...b,parent_id:b.id===scope?null:b.parent_id,plate:true})),...graph.nodes.filter(n=>(!scope||under(n.id,scope))&&representative(n.id)===n.id&&(view==='data'||n.kind!=='data')).map(n=>({...n,parent_id:n.block_id}))];
 const known=new Set(nodes.map(n=>n.id)), edges=new Map<string,GraphEdge>();
 // Structure ports bypass hidden value nodes, preserving the calculation chain.
 const hidden=new Set(graph.nodes.filter(n=>!known.has(n.id)&&representative(n.id)===n.id).map(n=>n.id));
 const candidates=[...graph.edges];
 if(view!=='data')for(const n of hidden){const ins=graph.edges.filter(e=>e.target===n&&e.kind==='data'),outs=graph.edges.filter(e=>e.source===n&&e.kind==='data');for(const a of ins)for(const b of outs)candidates.push({...b,id:a.id+'>'+b.id,source:a.source,source_port:a.source_port,original_ids:[a.id,b.id],label:a.label||b.label});}
 for(const e of candidates){if(e.kind==='contains')continue;const source=representative(e.source),target=representative(e.target);if(!known.has(source)||!known.has(target))continue;const key=source+'>'+target+':'+e.kind+':'+e.branch;if(edges.has(key)){const old=edges.get(key)!;old.count=(old.count??1)+(e.count??1);old.original_ids.push(...e.original_ids?.length?e.original_ids:[e.id]);}else edges.set(key,{...e,id:key,source,target,source_port:source===e.source?e.source_port:null,target_port:target===e.target?e.target_port:null,original_ids:e.original_ids?.length?e.original_ids:[e.id],count:e.count??1});}
 return {nodes,edges:[...edges.values()],omitted:graph.nodes.length-nodes.filter(n=>!n.plate).length};
}
export const scopeSelector=(block:string|null,targets:TargetRef[],mode:'selection'|'block'|'project'):ScopeSelector=>({mode,block_id:mode==='block'?block:null,targets:mode==='selection'?targets:[],excluded_keys:[]});
