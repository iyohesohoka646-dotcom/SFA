export type DocumentKind = 'source' | 'data' | 'graph' | 'probes' | 'tools' | 'intelligence' | 'changes' | 'context' | 'tasks' | 'terminal';
export interface WorkspaceDocument {
  id: string; kind: DocumentKind; title: string; pinned: boolean;
  reference: { analysis_id?: string; run_id?: string; snapshot_id?: string; instance_id?: string; context_id?: string; proposal_id?: string };
}
export interface Group { type: 'group'; id: string; tabs: string[]; active: string | null; minimized: boolean }
export interface Split { type: 'split'; id: string; axis: 'horizontal' | 'vertical'; ratio: number; first: LayoutNode; second: LayoutNode }
export type LayoutNode = Group | Split;
interface Preset { tree: LayoutNode; documents: Record<string, WorkspaceDocument>; explorerWidth: number }
export interface WorkspaceLayout {
  version: 1; tree: LayoutNode; documents: Record<string, WorkspaceDocument>; focused: string | null; activeGroup: string; locked: boolean;
  presets: Record<string, Preset>; explorerWidth: number;
}
export type LayoutAction =
  | { type: 'open'; document: WorkspaceDocument; group?: string; background?: boolean }
  | { type: 'close'; documentId: string }
  | { type: 'activate'; group: string; documentId: string }
  | { type: 'pin'; documentId: string; pinned: boolean }
  | { type: 'move'; documentId: string; group: string }
  | { type: 'minimize'; group: string; minimized: boolean }
  | { type: 'focus'; group: string | null }
  | { type: 'resize'; id: string; ratio: number }
  | { type: 'explorer-width'; width: number }
  | { type: 'lock'; locked: boolean }
  | { type: 'split'; group: string; axis: Split['axis'] }
  | { type: 'remove-group'; group: string }
  | { type: 'save-preset' | 'load-preset'; name: string }
  | { type: 'restore'; layout: WorkspaceLayout }
  | { type: 'reset' };

const group = (id: string): Group => ({ type: 'group', id, tabs: [], active: null, minimized: false });
export function createLayout(): WorkspaceLayout {
  return { version: 1, tree: { type: 'split', id: 'rows', axis: 'vertical', ratio: .78,
    first: { type: 'split', id: 'columns', axis: 'horizontal', ratio: .34, first: group('source'),
      second: { type: 'split', id: 'detail-width', axis: 'horizontal', ratio: .72, first: group('main'), second: group('detail') } }, second: group('bottom') },
    documents: {}, focused: null, activeGroup: 'main', locked: false, presets: {}, explorerWidth: 218 };
}
export const groups = (node: LayoutNode): Group[] => node.type === 'group' ? [node] : [...groups(node.first), ...groups(node.second)];
const map = (node: LayoutNode, fn: (node: LayoutNode) => LayoutNode): LayoutNode => fn(node.type === 'split' ? { ...node, first: map(node.first, fn), second: map(node.second, fn) } : node);
const bound = (ratio: number) => Math.max(.15, Math.min(.85, Number.isFinite(ratio) ? ratio : .5));

export function layoutReducer(state: WorkspaceLayout, action: LayoutAction): WorkspaceLayout {
  if (action.type === 'restore') return action.layout;
  if (action.type === 'reset') return { ...createLayout(), presets: state.presets };
  if (action.type === 'lock') return { ...state, locked: action.locked };
  if (action.type === 'explorer-width') return state.locked ? state : { ...state, explorerWidth: Math.max(170, Math.min(360, Number.isFinite(action.width) ? action.width : 218)) };
  if (action.type === 'focus') return { ...state, focused: action.group && groups(state.tree).some(g => g.id === action.group) ? action.group : null };
  if (action.type === 'resize') return state.locked ? state : { ...state, tree: map(state.tree, n => n.type === 'split' && n.id === action.id ? { ...n, ratio: bound(action.ratio) } : n) };
  if (action.type === 'minimize') return { ...state, focused: state.focused === action.group && action.minimized ? null : state.focused,
    tree: map(state.tree, n => n.type === 'group' && n.id === action.group ? { ...n, minimized: action.minimized } : n) };
  if (action.type === 'pin') {
    const doc = state.documents[action.documentId];
    return doc ? { ...state, documents: { ...state.documents, [doc.id]: { ...doc, pinned: action.pinned } } } : state;
  }
  if (action.type === 'open') {
    const existing = groups(state.tree).find(g => g.tabs.includes(action.document.id));
    const target = existing?.id ?? state.focused ?? (groups(state.tree).some(g => g.id === action.group) ? action.group! : state.activeGroup);
    const documents = { ...state.documents };
    const tree = map(state.tree, n => {
      if (n.type !== 'group' || n.id !== target) return n;
      let tabs = [...n.tabs];
      if (!existing && !action.document.pinned) {
        tabs = tabs.filter(id => {
          if (!documents[id].pinned && documents[id].kind === action.document.kind) { delete documents[id]; return false; }
          return true;
        });
      }
      if (!tabs.includes(action.document.id)) tabs.push(action.document.id);
      return { ...n, tabs, active: action.background && n.active && tabs.includes(n.active) ? n.active : action.document.id, minimized: action.background ? n.minimized : false };
    });
    if (!existing && Object.keys(documents).length >= 64) return state;
    if (!documents[action.document.id]) documents[action.document.id] = structuredClone(action.document);
    return { ...state, tree, documents, activeGroup: action.background ? state.activeGroup : target, focused: action.background ? state.focused : state.focused ? target : null };
  }
  if (action.type === 'close') {
    const documents = { ...state.documents }; delete documents[action.documentId];
    return { ...state, documents, tree: map(state.tree, n => {
      if (n.type !== 'group') return n;
      const tabs = n.tabs.filter(id => id !== action.documentId);
      return { ...n, tabs, active: n.active === action.documentId ? tabs.at(-1) ?? null : n.active };
    }) };
  }
  if (action.type === 'activate') return { ...state, activeGroup: action.group, tree: map(state.tree, n => n.type === 'group' && n.id === action.group && n.tabs.includes(action.documentId) ? { ...n, active: action.documentId, minimized: false } : n) };
  if (action.type === 'move') {
    const doc = state.documents[action.documentId];
    if (!doc || !groups(state.tree).some(g => g.id === action.group)) return state;
    const next = layoutReducer(state, { type: 'close', documentId: doc.id });
    return layoutReducer(next, { type: 'open', document: { ...doc, pinned: true }, group: action.group });
  }
  if (action.type === 'split') {
    if (state.locked || groups(state.tree).length >= 12) return state;
    let i = 1; const ids = new Set(groups(state.tree).map(g => g.id)); while (ids.has('group-' + i)) i++;
    return { ...state, tree: map(state.tree, n => n.type === 'group' && n.id === action.group ?
      { type: 'split', id: 'split-' + i, axis: action.axis, ratio: .5, first: n, second: group('group-' + i) } : n) };
  }
  if (action.type === 'remove-group') {
    if (state.locked || groups(state.tree).length <= 1) return state;
    const removed = groups(state.tree).find(g => g.id === action.group);
    if (!removed) return state;
    const remove = (node: LayoutNode): LayoutNode => {
      if (node.type === 'group') return node;
      if (node.first.type === 'group' && node.first.id === action.group) return node.second;
      if (node.second.type === 'group' && node.second.id === action.group) return node.first;
      return { ...node, first: remove(node.first), second: remove(node.second) };
    };
    let next: WorkspaceLayout = { ...state, tree: remove(state.tree), focused: null };
    const target = groups(next.tree)[0].id; next.activeGroup = target;
    for (const id of removed.tabs) next = layoutReducer(next, { type: 'open', document: state.documents[id], group: target });
    return next;
  }
  if (action.type === 'save-preset') {
    const name = action.name.trim().slice(0, 64);
    return !name || Object.keys(state.presets).length >= 16 && !state.presets[name] ? state :
      { ...state, presets: { ...state.presets, [name]: structuredClone({ tree: state.tree, documents: state.documents, explorerWidth: state.explorerWidth }) } };
  }
  if (action.type === 'load-preset') {
    const preset = state.presets[action.name];
    return preset ? { ...state, ...structuredClone(preset), focused: null, activeGroup: groups(preset.tree)[0].id } : state;
  }
  return state;
}

export function restoreLayout(raw: string | null): WorkspaceLayout {
  try {
    if (!raw || raw.length > 256 * 1024) return createLayout();
    const state = JSON.parse(raw) as WorkspaceLayout;
    if (state.version !== 1 || typeof state.documents !== 'object' || !state.documents || Object.keys(state.documents).length > 64) return createLayout();
    const ids = new Set<string>();
    function valid(node: LayoutNode, depth = 0): boolean {
      if (!node || depth > 20 || typeof node.id !== 'string' || ids.has(node.id)) return false;
      ids.add(node.id);
      if (node.type === 'split') return ['horizontal', 'vertical'].includes(node.axis) && Number.isFinite(node.ratio) && node.ratio >= .15 && node.ratio <= .85 && valid(node.first, depth + 1) && valid(node.second, depth + 1);
      return node.type === 'group' && typeof node.minimized === 'boolean' && Array.isArray(node.tabs) && node.tabs.length <= 64 && node.tabs.every(id => !!state.documents[id]) && (node.active === null || node.tabs.includes(node.active));
    }
    const kinds = ['source', 'data', 'graph', 'probes', 'tools', 'intelligence', 'changes', 'context', 'tasks', 'terminal'];
    if (!valid(state.tree) || groups(state.tree).length > 12 || !groups(state.tree).some(g => g.id === state.activeGroup)) return createLayout();
    for (const [id, doc] of Object.entries(state.documents)) if (doc.id !== id || !kinds.includes(doc.kind) || typeof doc.title !== 'string' || typeof doc.pinned !== 'boolean' || typeof doc.reference !== 'object' || !doc.reference) return createLayout();
    // Validate each saved preset independently, including its own document map.
    const presets: WorkspaceLayout['presets'] = {};
    for (const [name, preset] of Object.entries(state.presets ?? {}).slice(0, 16)) {
      const saved = restoreLayout(JSON.stringify({ version: 1, ...preset, activeGroup: groups(preset.tree)[0]?.id, locked: false, focused: null, presets: {} }));
      presets[name] = { tree: saved.tree, documents: saved.documents, explorerWidth: saved.explorerWidth };
    }
    return { ...state, focused: null, locked: !!state.locked, presets, explorerWidth: Math.max(170, Math.min(360, Number.isFinite(state.explorerWidth) ? state.explorerWidth : 218)) };
  } catch { return createLayout(); }
}
