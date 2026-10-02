import { useEffect, useReducer } from 'react';
import { createLayout, layoutReducer, restoreLayout, type LayoutAction, type WorkspaceLayout } from './layout';

export function useWorkspace(storageKey: string) {
  const [state, dispatch] = useReducer((state: { key: string; layout: WorkspaceLayout }, action: LayoutAction | { type: 'hydrate'; key: string; raw: string | null }) =>
    action.type === 'hydrate' ? { key: action.key, layout: restoreLayout(action.raw) } : { ...state, layout: layoutReducer(state.layout, action) }, storageKey,
    key => { try { return { key, layout: restoreLayout(localStorage.getItem(key)) }; } catch { return { key, layout: createLayout() }; } });
  useEffect(() => {
    if (state.key !== storageKey) {
      let raw = null; try { raw = localStorage.getItem(storageKey); } catch { /* memory-only layout */ }
      dispatch({ type: 'hydrate', key: storageKey, raw }); return;
    }
    try { localStorage.setItem(storageKey, JSON.stringify(state.layout)); } catch { /* restricted browser storage keeps the current in-memory workspace */ }
  }, [storageKey, state]);
  return { layout: state.layout, dispatch };
}
