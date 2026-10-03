import {
  createContext,
  Suspense,
  useContext,
  useEffect,
  useRef,
  useState,
  type Dispatch,
  type ReactNode,
} from "react";
import {
  DockviewReact,
  type DockviewApi,
  type IDockviewPanelProps,
  type IDockviewHeaderActionsProps,
  type IDockviewPanelHeaderProps,
  themeLight,
  themeDark,
  type SerializedDockview,
  type DockviewGroupPanel,
  Orientation,
} from "dockview-react";
import {
  groups,
  type LayoutAction,
  type DocumentKind,
  type WorkspaceDocument,
  type WorkspaceLayout,
  type LayoutNode,
} from "./layout";
import { Icon } from "./icons";
import "dockview/dist/styles/dockview.css";
import {RenderBoundary} from '../../runtime/RenderBoundary';
const Host = createContext<{
  layout: WorkspaceLayout;
  dispatch: Dispatch<LayoutAction>;
  render: (d: WorkspaceDocument) => ReactNode;
  onOpen: () => void;
} | null>(null);
const retainedPanels = new Set<DocumentKind>([
  "source",
  "graph",
  "probes",
  "tools",
  "intelligence",
  "changes",
  "context",
  "tasks",
  "settings",
]);
function DocumentContent({document}:{document:WorkspaceDocument}) {
  return useContext(Host)!.render(document);
}
function Panel({ api, params }: IDockviewPanelProps) {
  const host = useContext(Host)!,
    [visible, setVisible] = useState(api.isVisible);
  useEffect(() => {
    const h = api.onDidVisibilityChange((e) => setVisible(e.isVisible));
    return () => h.dispose();
  }, [api]);
  const doc = host.layout.documents[String(params.documentId ?? api.id)];
  return (
    <div
      className="workspace-document"
      role="tabpanel"
      aria-hidden={!visible}
      aria-label={doc?.title ?? "空视图"}
    >
      {(visible || (doc && retainedPanels.has(doc.kind))) &&
        (doc ? (
          <RenderBoundary view key={doc.id} onClose={()=>host.dispatch({type:'close',documentId:doc.id})}>
            <Suspense fallback={<div className="workspace-empty" role="status">打开视图…</div>}>
              <DocumentContent document={doc}/>
            </Suspense>
          </RenderBoundary>
        ) : (
          <div className="workspace-empty">
            <button onClick={host.onOpen}>
              <Icon name="add" />
              打开视图
            </button>
          </div>
        ))}
    </div>
  );
}
function Actions({ api }: IDockviewHeaderActionsProps) {
  const host = useContext(Host)!,
    id = api.id;
  return (
    <div className="workspace-pane-actions">
      <button
        className="workspace-icon-button"
        aria-label={"缩小 " + id + " 视图"}
        onClick={() =>
          host.dispatch({ type: "minimize", group: id, minimized: true })
        }
      >
        <Icon name="minimize" size={13} />
      </button>
      <button
        className="workspace-icon-button"
        aria-label={
          (host.layout.focused === id ? "还原 " : "放大 ") + id + " 视图"
        }
        onClick={() =>
          host.dispatch({
            type: "focus",
            group: host.layout.focused === id ? null : id,
          })
        }
      >
        <Icon
          name={host.layout.focused === id ? "restore" : "maximize"}
          size={13}
        />
      </button>
    </div>
  );
}
function Tab({ api }: IDockviewPanelHeaderProps) {
  const host = useContext(Host)!,
    doc = host.layout.documents[api.id];
  return (
    <div
      className="workspace-tab"
      onDoubleClick={() =>
        doc && host.dispatch({ type: "pin", documentId: doc.id, pinned: true })
      }
    >
      <span className="workspace-tab-title">
        <Icon name={doc?.kind ?? "data"} size={12} />
        <span>{doc?.title ?? "空视图"}</span>
        {doc?.pinned && <Icon name="pin" size={10} />}
      </span>
      {doc && (
        <button
          aria-label={"关闭 " + doc.title}
          onDoubleClick={(e) => e.stopPropagation()}
          onClick={(e) => {
            e.stopPropagation();
            host.dispatch({ type: "close", documentId: doc.id });
          }}
        >
          <Icon name="close" size={10} />
        </button>
      )}
    </div>
  );
}
const components = { document: Panel };
export function serializeLegacy(
  layout: WorkspaceLayout,
  width = 1100,
  height = 700,
): SerializedDockview {
  const panels: SerializedDockview["panels"] = {};
  for (const d of Object.values(layout.documents))
    panels[d.id] = {
      id: d.id,
      contentComponent: "document",
      title: d.title,
      params: { documentId: d.id },
      minimumWidth: 60,
      minimumHeight: 45,
    };
  function leaf(n: LayoutNode, size: number): any {
    if (n.type === "group") {
      const tabs = n.tabs.filter((t) => panels[t]);
      if (!tabs.length) {
        const id = "empty:" + n.id;
        panels[id] = {
          id,
          contentComponent: "document",
          title: "空视图",
          params: { documentId: id },
          minimumWidth: 60,
          minimumHeight: 45,
        };
        tabs.push(id);
      }
      return {
        type: "leaf",
        size,
        data: {
          id: n.id,
          views: tabs,
          activeView: n.active && tabs.includes(n.active) ? n.active : tabs[0],
        },
      };
    }
    const flatten = (c: LayoutNode, s: number): any[] =>
      c.type === "split" && c.axis === n.axis
        ? [
            ...flatten(c.first, s * c.ratio),
            ...flatten(c.second, s * (1 - c.ratio)),
          ]
        : [leaf(c, s)];
    return {
      type: "branch",
      size,
      data: [
        ...flatten(n.first, size * n.ratio),
        ...flatten(n.second, size * (1 - n.ratio)),
      ],
    };
  }
  const root = leaf(
    layout.tree,
    layout.tree.type === "split" && layout.tree.axis === "vertical"
      ? height
      : width,
  );
  return {
    grid: {
      root,
      height,
      width,
      orientation:
        layout.tree.type === "split" && layout.tree.axis === "vertical"
          ? Orientation.VERTICAL
          : Orientation.HORIZONTAL,
    },
    panels,
    activeGroup: layout.activeGroup,
  };
}
function mirror(json: SerializedDockview, old: WorkspaceLayout): LayoutNode {
  let i = 0;
  function visit(node: any, axis: "horizontal" | "vertical"): LayoutNode {
    if (node.type === "leaf") {
      const saved = groups(old.tree).find((g) => g.id === node.data.id);
      const tabs = (node.data.views as string[]).filter(
        (id) => old.documents[id],
      );
      return {
        type: "group",
        id: node.data.id,
        tabs,
        active: old.documents[node.data.activeView]
          ? node.data.activeView
          : (tabs[0] ?? null),
        minimized: saved?.minimized ?? false,
      };
    }
    const children = node.data as any[];
    const build = (items: any[]): LayoutNode => {
      if (items.length === 1)
        return visit(
          items[0],
          axis === "horizontal" ? "vertical" : "horizontal",
        );
      const total = items.reduce((a, n) => a + (n.size ?? 1), 0);
      return {
        type: "split",
        id: "dock-split-" + i++,
        axis,
        ratio: (items[0].size ?? 1) / total,
        first: visit(
          items[0],
          axis === "horizontal" ? "vertical" : "horizontal",
        ),
        second: build(items.slice(1)),
      };
    };
    return build(children);
  }
  return visit(
    json.grid.root,
    json.grid.orientation === Orientation.HORIZONTAL
      ? "horizontal"
      : "vertical",
  );
}
export function DockWorkspaceShell(props: {
  layout: WorkspaceLayout;
  dispatch: Dispatch<LayoutAction>;
  render: (d: WorkspaceDocument) => ReactNode;
  onOpen: () => void;
}) {
  const api = useRef<DockviewApi | null>(null),
    host = useRef<HTMLDivElement>(null),
    latest = useRef(props);
  latest.current = props;
  const updating = useRef(false),
    [ready, setReady] = useState(0),
    [restoreError, setRestoreError] = useState("");
  useEffect(() => {
    const dock = api.current;
    if (!ready || !dock) return;
    updating.current = true;
    try {
      dock.fromJSON(
        props.layout.dockview ??
          serializeLegacy(
            props.layout,
            host.current?.clientWidth,
            host.current?.clientHeight,
          ),
      );
    } catch (e) {
      setRestoreError("旧布局已保留，已恢复兼容布局");
      dock.fromJSON(serializeLegacy(props.layout));
    } finally {
      updating.current = false;
    }
  }, [ready, props.layout.dockRevision]);
  useEffect(() => {
    const dock = api.current;
    if (!ready || !dock) return;
    updating.current = true;
    try {
      const layout = props.layout;
      dock.updateOptions({ locked: layout.locked, disableDnd: layout.locked });
      for (const panel of [...dock.panels])
        if (!panel.id.startsWith("empty:") && !layout.documents[panel.id])
          dock.removePanel(panel);
      for (const group of groups(layout.tree)) {
        let dg = dock.getGroup(group.id);
        if (!dg)
          dg = dock.addGroup({
            id: group.id,
            referenceGroup: dock.activeGroup?.id ?? "main",
            direction: group.id === "bottom" ? "below" : "right",
          });
        for (const id of group.tabs) {
          const doc = layout.documents[id];
          if (!doc) continue;
          let panel = dock.getPanel(id);
          if (!panel)
            panel = dock.addPanel({
              id,
              component: "document",
              title: doc.title,
              params: { documentId: id },
              position: { referenceGroup: dg.id },
              minimumWidth: 60,
              minimumHeight: 45,
            });
          else if (panel.group.id !== dg.id)
            panel.api.moveTo({ group: dg as DockviewGroupPanel });
          panel.api.setTitle(doc.title);
        }
        const placeholder = dock.getPanel("empty:" + group.id);
        if (group.tabs.length && placeholder) dock.removePanel(placeholder);
        if (!group.tabs.length && !dock.getPanel("empty:" + group.id))
          dock.addPanel({
            id: "empty:" + group.id,
            component: "document",
            title: "空视图",
            position: { referenceGroup: group.id },
          });
        if (group.active) {
          const active = dock.getPanel(group.active);
          if (active && !active.api.isActive) active.api.setActive();
        }
        dg.api.setVisible(!group.minimized);
        const element =
          dg.model.tabsListElement.closest<HTMLElement>(".dv-groupview");
        if (element) {
          element.dataset.group = group.id;
          element.style.display = group.minimized ? "none" : "";
          element.setAttribute("aria-hidden", String(group.minimized));
        }
      }
      if (layout.focused) {
        const g = dock.getGroup(layout.focused);
        if (g && !g.api.isMaximized()) g.api.maximize();
      } else
        for (const g of dock.groups)
          if (g.api.isMaximized()) g.api.exitMaximized();
    } finally {
      updating.current = false;
    }
  }, [ready, props.layout.commandRevision]);
  useEffect(() => {
    const node = host.current;
    if (!node) return;
    const decorate = () => {
      node.querySelectorAll<HTMLElement>(".dv-sash").forEach((s, i) => {
        s.setAttribute("role", "separator");
        s.setAttribute("aria-label", "调整分屏 " + i);
        s.tabIndex = latest.current.layout.locked ? -1 : 0;
        s.onkeydown = (e) => {
          if (latest.current.layout.locked) return;
          if (e.key.startsWith("Arrow")) {
            e.preventDefault();
            const dock = api.current,
              group = dock?.activeGroup;
            if (group)
              group.api.setSize({
                width:
                  group.width +
                  (e.key === "ArrowLeft"
                    ? -25
                    : e.key === "ArrowRight"
                      ? 25
                      : 0),
                height:
                  group.height +
                  (e.key === "ArrowUp" ? -25 : e.key === "ArrowDown" ? 25 : 0),
              });
          }
        };
      });
    };
    decorate();
    const observer = new MutationObserver(decorate);
    observer.observe(node, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, [ready, props.layout.locked]);
  return (
    <Host.Provider value={props}>
      <div
        className={
          "workspace-shell dock-host " +
          (props.layout.locked ? "layout-locked" : "")
        }
        ref={host}
      >
        <DockviewReact
          theme={
            document.documentElement.dataset.theme === "dark"
              ? themeDark
              : themeLight
          }
          defaultTabComponent={Tab}
          components={components}
          rightHeaderActionsComponent={Actions}
          onReady={(e) => {
            api.current = e.api;
            let frame = 0;
            e.api.onDidLayoutChange(() => {
              if (updating.current) return;
              cancelAnimationFrame(frame);
              frame = requestAnimationFrame(() => {
                if (updating.current) return;
                const json = e.api.toJSON();
                const docs = latest.current.layout.documents;
                const present = Object.keys(json.panels).filter(
                  (id) => !id.startsWith("empty:"),
                );
                if (
                  present.length !== Object.keys(docs).length ||
                  present.some((id) => !docs[id])
                )
                  return;
                latest.current.dispatch({
                  type: "dock-state",
                  json,
                  tree: mirror(json, latest.current.layout),
                  activeGroup: e.api.activeGroup?.id ?? "main",
                });
              });
            });
            e.api.onDidRemovePanel((e) => {
              if (!updating.current && latest.current.layout.documents[e.id])
                latest.current.dispatch({ type: "close", documentId: e.id });
            });
            setReady((n) => n + 1);
          }}
        />
        {groups(props.layout.tree).some((g) => g.minimized) && (
          <div className="dock-restore-strip">
            {groups(props.layout.tree)
              .filter((g) => g.minimized)
              .map((g) => (
                <button
                  key={g.id}
                  aria-label={"恢复 " + g.id + " 视图"}
                  onClick={() =>
                    props.dispatch({
                      type: "minimize",
                      group: g.id,
                      minimized: false,
                    })
                  }
                >
                  <Icon name="restore" size={12} />
                  {g.active ? props.layout.documents[g.active]?.title : g.id}
                </button>
              ))}
          </div>
        )}
        {restoreError && <div role="status">{restoreError}</div>}
      </div>
    </Host.Provider>
  );
}
