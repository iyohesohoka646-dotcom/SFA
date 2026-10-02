import { describe, expect, it } from 'vitest';
import { createLayout, groups, layoutReducer, restoreLayout, type WorkspaceDocument } from '../src/research/workspace/layout';

const data = (id: string, pinned = false): WorkspaceDocument => ({ id, kind: 'data', title: id, pinned, reference: { snapshot_id: id, run_id: 'run1' } });

describe('scientific document geometry and immutable references', () => {
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
