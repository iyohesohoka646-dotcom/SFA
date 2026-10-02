import { useEffect, useReducer } from "react";
import {
  createLayout,
  layoutReducer,
  restoreLayout,
  type LayoutAction,
  type WorkspaceLayout,
} from "./layout";

export function readStoredLayout(
  key: string,
  storage: Pick<Storage, "getItem" | "setItem">,
): WorkspaceLayout {
  const raw = storage.getItem(key);
  let legacy = false;
  try {
    legacy = Boolean(raw && !JSON.parse(raw).dockview);
  } catch {
    legacy = Boolean(raw);
  }
  const layout = restoreLayout(raw, () => {
    legacy = true;
  });
  if (raw && legacy && !storage.getItem(key + ":pre-dockview-backup"))
    storage.setItem(key + ":pre-dockview-backup", raw);
  return layout;
}

export function useWorkspace(storageKey: string) {
  const [state, dispatch] = useReducer(
    (
      state: { key: string; layout: WorkspaceLayout },
      action:
        | LayoutAction
        | { type: "hydrate"; key: string; raw: string | null },
    ) =>
      action.type === "hydrate"
        ? { key: action.key, layout: restoreLayout(action.raw) }
        : { ...state, layout: layoutReducer(state.layout, action) },
    storageKey,
    (key) => {
      try {
        return { key, layout: readStoredLayout(key, localStorage) };
      } catch {
        return { key, layout: createLayout() };
      }
    },
  );
  useEffect(() => {
    if (state.key !== storageKey) {
      let raw = null;
      try {
        raw = JSON.stringify(readStoredLayout(storageKey, localStorage));
      } catch {
        /* memory-only layout */
      }
      dispatch({ type: "hydrate", key: storageKey, raw });
      return;
    }
    try {
      localStorage.setItem(storageKey, JSON.stringify(state.layout));
    } catch {
      /* restricted browser storage keeps the current in-memory workspace */
    }
  }, [storageKey, state]);
  const recoverLayout = () => {
    const raw = localStorage.getItem(storageKey + ":pre-dockview-backup");
    if (!raw) throw new Error("没有布局备份");
    let invalid = false;
    const layout = restoreLayout(raw, () => {
      invalid = true;
    });
    if (invalid) throw new Error("旧布局无法自动转换，原始备份仍保留");
    dispatch({ type: "restore", layout });
  };
  let hasLayoutBackup = false;
  try {
    hasLayoutBackup = Boolean(
      localStorage.getItem(storageKey + ":pre-dockview-backup"),
    );
  } catch {}
  return {
    layout: state.layout,
    dispatch,
    recoverLayout,
    hasLayoutBackup,
    ready: state.key === storageKey,
  };
}
