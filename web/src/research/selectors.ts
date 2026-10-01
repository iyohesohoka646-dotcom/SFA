import type { ResearchState } from './state';
import type { SnapshotRef, ProbeResult } from './generated';
export interface VariableView {snapshot:SnapshotRef; probes:ProbeResult[];}
export function selectVariable(state:ResearchState, bindingId:string):VariableView|undefined {
  const snapshot=state.latest.get(bindingId);
  return snapshot?{snapshot,probes:state.probes.get(snapshot.id)||[]}:undefined;
}
export function localTopology(state:ResearchState, binding:string, maximum=80):string[] {
  const visited=new Set<string>(), pending=binding?[binding]:[...state.latest.keys()].slice(0,maximum);
  while(pending.length && visited.size<maximum) {
    const id=pending.shift()!;
    if(visited.has(id) || !state.latest.has(id)) continue;
    visited.add(id);
    pending.push(...(state.dependencies.get(id)||[]));
    for(const [target,parents] of state.dependencies) if(parents.includes(id) && !visited.has(target)) pending.push(target);
  }
  return [...visited];
}
