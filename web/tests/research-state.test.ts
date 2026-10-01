import { describe, expect, test } from 'vitest';
import { applyEvent, createState } from '../src/research/state';
import { selectVariable, localTopology } from '../src/research/selectors';
import { OperationController } from '../src/research/operations';

const snapshot = (i: number, version = 1) => ({id: `s${i}-${version}`, run_id: 'r', name: `X${i}`, binding_id: `main:X${i}`, scope_id: 'main', version,
  descriptor: {schema_version: 1 as const, kind: 'matrix', backend: 'fixture', type_name: 'Matrix', shape: [4,4], capabilities: ['preview'], axes: [], metadata: {}},
  observed_at: '', source: null, operation_id: null, parents: [], provenance: 'observed' as const, fidelity: 'exact' as const,
  sample: {values: [[version]]}, statistics: {}, truncation: [], redacted: [], artifact_ref: null, coverage: {}});
const event = (i: number, sequence: number, version = 1) => ({schema_version: 1 as const, run_id: 'r', sequence, kind: 'value.observed', timestamp: '',
  snapshot_id: `s${i}-${version}`, operation_id: null, source: null, payload: {snapshot: snapshot(i, version)}});

describe('research-state', () => {
  test('keeps data samples out of metadata and timeline caches without changing wire evidence',()=>{
    const observed=event(0,1);
    let state=applyEvent(createState('r'),observed);
    expect(state.snapshots.get('s0-1')?.sample).toEqual({});
    expect(state.latest.get('main:X0')?.sample).toEqual({});
    expect((state.timeline[0].payload.snapshot as any).sample).toEqual({});
    expect(observed.payload.snapshot.sample).toEqual({values:[[1]]});
  });
  test('deduplicates continuation and rejects events from another run', () => {
    let state = createState('r');
    state = applyEvent(state, event(0, 1));
    expect(applyEvent(state, event(0, 1))).toBe(state);
    expect(applyEvent(state, {...event(1, 2), run_id: 'other'})).toBe(state);
    expect(state.latest.size).toBe(1);
  });

  test('numeric updates preserve topology and bound all history caches', () => {
    let state = createState('r');
    for (let i = 0; i < 10000; i++) state = applyEvent(state, event(i % 1000, i+1, Math.floor(i/1000)+1));
    expect(state.latest.size).toBe(1000);
    expect(state.timeline.length).toBeLessThanOrEqual(512);
    expect(state.snapshots.size).toBeLessThanOrEqual(4096);
    expect(state.topologyVersion).toBe(1000);
    expect(selectVariable(state, 'main:X7')?.snapshot.version).toBe(10);
    expect(localTopology(state, 'main:X7', 80).length).toBeLessThanOrEqual(80);
  });

  test('older versions cannot replace latest values during bootstrap replay', () => {
    let state = createState('r');
    state = applyEvent(state, event(0, 1, 4));
    state = applyEvent(state, event(0, 2, 2));
    expect(selectVariable(state, 'main:X0')?.snapshot.version).toBe(4);
  });

  test('late selection response is discarded and requests cancel independently', async () => {
    const selection = new OperationController();
    const model = new OperationController();
    let finishOld: (value: string) => void = () => {};
    const old = selection.run(() => new Promise<string>(resolve => { finishOld = resolve; }));
    const slow = model.run(() => new Promise<string>(() => {}));
    expect(await selection.run(async () => 'new-variable')).toBe('new-variable');
    finishOld('old-variable');
    expect(await old).toBeUndefined();
    expect(selection.state.value).toBe('new-variable');
    expect(model.state.status).toBe('running');
    model.cancel();
    expect(await slow).toBeUndefined();
    expect(selection.state.value).toBe('new-variable');
  });
});
