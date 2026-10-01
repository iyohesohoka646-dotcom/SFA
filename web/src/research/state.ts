import type { ObservationEvent, SnapshotRef, OperationRecord, ProbeResult } from './generated';

export interface ResearchState {
  runId: string; lastSequence: number; topologyVersion: number;
  latest: Map<string, SnapshotRef>; snapshots: Map<string, SnapshotRef>;
  operations: Map<string, OperationRecord>; probes: Map<string, ProbeResult[]>;
  dependencies: Map<string, string[]>; timeline: ObservationEvent[];
  status: string; omittedBindings: number;
}
export const createState = (runId: string): ResearchState => ({runId,lastSequence:0,topologyVersion:0,latest:new Map(),snapshots:new Map(),
  operations:new Map(),probes:new Map(),dependencies:new Map(),timeline:[],status:'queued',omittedBindings:0});

function bound<K,V>(map: Map<K,V>, maximum: number) {
  while (map.size>maximum) map.delete(map.keys().next().value!);
}

/** Incremental index; published snapshots are immutable wire values. */
export function indexSnapshot(state: ResearchState, snapshot: SnapshotRef) {
  const current = state.latest.get(snapshot.binding_id);
  state.snapshots.set(snapshot.id,snapshot);
  if (!current || snapshot.version>current.version) {
    const parents = (snapshot.parents || []).map(id=>state.snapshots.get(id)?.binding_id).filter((s):s is string=>!!s);
    const dependencies = [...new Set(parents)].sort();
    if (!current || dependencies.join('\0')!==(state.dependencies.get(snapshot.binding_id)||[]).join('\0')) state.topologyVersion++;
    state.latest.set(snapshot.binding_id,snapshot);
    state.dependencies.set(snapshot.binding_id,dependencies);
  }
  while (state.latest.size>2048) {
    const first=state.latest.keys().next().value!;
    state.latest.delete(first); state.dependencies.delete(first); state.omittedBindings++;
  }
  while (state.snapshots.size>4096) {
    const id=state.snapshots.keys().next().value!;
    const old=state.snapshots.get(id)!;
    state.snapshots.delete(id);
    if (state.latest.get(old.binding_id)?.id===id) state.snapshots.set(id,old);
  }
  return state;
}

export function applyEvent(state: ResearchState, event: ObservationEvent): ResearchState {
  if (event.run_id!==state.runId || event.sequence<=state.lastSequence) return state;
  if (event.kind==='value.observed' && event.payload.snapshot) indexSnapshot(state,event.payload.snapshot as unknown as SnapshotRef);
  if (event.kind.startsWith('operation.') && event.payload.operation) {
    const operation=event.payload.operation as unknown as OperationRecord;
    state.operations.set(operation.id,operation); bound(state.operations,512);
  }
  if (event.kind==='probe.evaluated' && event.snapshot_id && event.payload.result) {
    const results=[...(state.probes.get(event.snapshot_id)||[]),event.payload.result as unknown as ProbeResult].slice(-128);
    state.probes.set(event.snapshot_id,results); bound(state.probes,2048);
  }
  const status=event.kind==='run.finished'?String(event.payload.status):event.kind==='control.paused'?'paused':
    ['control.resumed','run.started'].includes(event.kind)?'running':state.status;
  return {...state,lastSequence:event.sequence,status,timeline:[...state.timeline.slice(-511),event]};
}
