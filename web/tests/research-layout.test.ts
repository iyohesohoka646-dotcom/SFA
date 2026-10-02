import { describe, expect, it } from 'vitest';
import { createLayout, groups, layoutReducer, restoreLayout, type WorkspaceDocument } from '../src/research/workspace/layout';

const data = (id: string, pinned = false): WorkspaceDocument => ({ id, kind: 'data', title: id, pinned, reference: { snapshot_id: id, run_id: 'run1' } });
it('restores narrow Dockview ratios without discarding documents',()=>{
 const state=layoutReducer(createLayout(),{type:'open',document:data('preserved'),group:'main'});
 if(state.tree.type==='split')state.tree.ratio=.95;
 expect(restoreLayout(JSON.stringify(state)).documents.preserved).toBeDefined();
});
it('rejects a queued Dockview snapshot from before a document replacement',()=>{
 let state=layoutReducer(createLayout(),{type:'open',document:data('old'),group:'main'});const stale=state.tree;
 state=layoutReducer(state,{type:'open',document:data('new'),group:'main'});
 state=layoutReducer(state,{type:'dock-state',tree:stale,json:{panels:{},grid:{}} as any,activeGroup:'main'});
 expect(groups(state.tree).find(g=>g.id==='main')!.tabs).toEqual(['new']);
});

describe('scientific document geometry and immutable references', () => {
  it('background import cannot take focus from a user-opened tool', () => {
    let state = layoutReducer(createLayout(), { type: 'open', document: { ...data('assistant'), kind: 'intelligence' }, group: 'main' });
    state = layoutReducer(state, { type: 'open', document: { ...data('source'), kind: 'source' }, group: 'source', background: true });
    expect(state.activeGroup).toBe('main');
  });
  it('stores the explorer width in a named layout and locks its separator', () => {
    let state = layoutReducer(createLayout(), { type: 'explorer-width', width: 270 });
    state = layoutReducer(state, { type: 'save-preset', name: '宽对象栏' });
    state = layoutReducer(state, { type: 'explorer-width', width: 200 });
    state = layoutReducer(state, { type: 'load-preset', name: '宽对象栏' });
    expect(state.explorerWidth).toBe(270);
    state = layoutReducer(state, { type: 'lock', locked: true });
    expect(layoutReducer(state, { type: 'explorer-width', width: 300 }).explorerWidth).toBe(270);
  });
  it('bounds both axes and preserves geometry while locked', () => {
    let state = createLayout();
    state = layoutReducer(state, { type: 'resize', id: 'columns', ratio: 10 });
    expect(state.tree.type === 'split' ? state.tree.first.type : '').toBe('split');
    const before = JSON.stringify(state.tree);
    state = layoutReducer(state, { type: 'lock', locked: true });
    state = layoutReducer(state, { type: 'resize', id: 'columns', ratio: .3 });
    expect(JSON.stringify(state.tree)).toBe(before);
  });
  it('minimizes and restores without closing a document', () => {
    let state = layoutReducer(createLayout(), { type: 'open', document: data('s1'), group: 'main' });
    state = layoutReducer(state, { type: 'minimize', group: 'main', minimized: true });
    expect(groups(state.tree).find(g => g.id === 'main')?.minimized).toBe(true);
    expect(state.documents.s1.reference.snapshot_id).toBe('s1');
    state = layoutReducer(state, { type: 'minimize', group: 'main', minimized: false });
    expect(groups(state.tree).find(g => g.id === 'main')?.active).toBe('s1');
  });
  it('new tabs and closing locked documents retain every slot and dimension', () => {
    let state = layoutReducer(createLayout(), { type: 'lock', locked: true });
    const before = groups(state.tree).map(g => g.id);
    state = layoutReducer(state, { type: 'open', document: data('s1'), group: 'does-not-exist' });
    state = layoutReducer(state, { type: 'close', documentId: 's1' });
    expect(groups(state.tree).map(g => g.id)).toEqual(before);
    expect(groups(state.tree).every(g => g.tabs.length === 0)).toBe(true);
    state = layoutReducer(state, { type: 'split', group: 'main', axis: 'vertical' });
    expect(groups(state.tree).map(g => g.id)).toEqual(before);
  });
  it('temporary focus leaves the saved geometry unchanged', () => {
    let state = createLayout();
    const tree = JSON.stringify(state.tree);
    state = layoutReducer(state, { type: 'focus', group: 'main' });
    expect(state.focused).toBe('main');
    state = layoutReducer(state, { type: 'focus', group: null });
    expect(JSON.stringify(state.tree)).toBe(tree);
  });
  it('a late preview cannot replace a pinned snapshot or a different run', () => {
    let state = layoutReducer(createLayout(), { type: 'open', document: data('s1', true), group: 'main' });
    state = layoutReducer(state, { type: 'open', document: data('s2'), group: 'main' });
    state = layoutReducer(state, { type: 'open', document: data('s3'), group: 'main' });
    expect(state.documents.s1.reference.snapshot_id).toBe('s1');
    expect(state.documents.s2).toBeUndefined();
    expect(groups(state.tree).find(g => g.id === 'main')?.tabs).toEqual(['s1', 's3']);
    state = layoutReducer(state, { type: 'open', document: { ...data('s1'), reference: { snapshot_id: 'WRONG', run_id: 'run2' } }, group: 'main' });
    expect(state.documents.s1.reference.run_id).toBe('run1');
  });
  it('persists named layouts and rejects incompatible or malformed trees', () => {
    let state = createLayout();
    state = layoutReducer(state, { type: 'save-preset', name: '对比' });
    state = layoutReducer(state, { type: 'resize', id: 'rows', ratio: .6 });
    state = layoutReducer(state, { type: 'load-preset', name: '对比' });
    expect(state.tree.type === 'split' && state.tree.ratio).toBe(.78);
    expect(restoreLayout(JSON.stringify(state))).toEqual(state);
    expect(restoreLayout('{"version":99}')?.version).toBe(1);
    expect(restoreLayout('{"version":1,"tree":{}}')?.documents).toEqual({});
  });
});
it('background source replacement keeps a valid active tab and persisted lock', () => {
  let layout = layoutReducer(createLayout(), { type: 'open', group: 'source', document: { id: 'old', kind: 'source', title: 'old', pinned: false, reference: {} } });
  layout = layoutReducer(layout, { type: 'lock', locked: true });
  layout = layoutReducer(layout, { type: 'open', group: 'source', background: true, document: { id: 'new', kind: 'source', title: 'new', pinned: false, reference: {} } });
  expect(groups(layout.tree).find(g => g.id === 'source')?.active).toBe('new');
  expect(restoreLayout(JSON.stringify(layout)).locked).toBe(true);
});
