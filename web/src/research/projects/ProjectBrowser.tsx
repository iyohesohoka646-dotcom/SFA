/** Controlled project browser: directory tree plus per-file object disclosure.
 *
 * Selection and scope live in the caller. This component owns only page caches
 * and fold state, and every fetch carries the explicit revision id. Nothing is
 * fabricated: an unread page shows a real error and a retry action.
 */
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent as ReactMouseEvent,
  type ReactNode,
} from "react";
import type {
  ObjectItem,
  ResearchProject,
  TargetRef,
  TreeItem,
} from "./generated";
import {
  hasMore,
  mergePage,
  type MergedPage,
  type ProjectQueries,
} from "./queries";
import {
  objectLexicalScope,
  objectScope,
  scopeLabel,
  targetSelectionKey,
} from "./identity";
import "./project-workspace.css";

export interface ProjectBrowserProps {
  project: ResearchProject;
  revisionId: string;
  runId?: string;
  scopeId?: string | null;
  refreshKey?: string;
  queries: ProjectQueries;
  selected: TargetRef[];
  onSelect(target: TargetRef, event: ReactMouseEvent): void;
  onSelectionChange?(targets: TargetRef[]): void;
  onOpenSource(source: TargetRef): void;
  onEnterScope(target: TargetRef): void;
}

const ROOT = "@root";
const PAGE = 200;
/** Full canonical grouping identity: project, file and complete lexical scope. */
export function scopeGroupKey(item: ObjectItem): string {
  return objectScope(item);
}

/** Short display label only; never used as the grouping identity. */
export function shortScope(scope: string): string {
  return scopeLabel(scope);
}

export interface ScopeGroup {
  key: string;
  scope: string;
  label: string;
  items: ObjectItem[];
}

/** Groups variables by their full lexical scope so nested scopes stay apart. */
export function groupObjectsByScope(items: ObjectItem[]): ScopeGroup[] {
  const groups = new Map<string, ScopeGroup>();
  for (const item of items) {
    const key = objectScope(item);
    const existing = groups.get(key);
    if (existing) existing.items.push(item);
    else {
      const scope = objectLexicalScope(item);
      groups.set(key, { key, scope, label: scopeLabel(scope), items: [item] });
    }
  }
  return [...groups.values()].map((group) => ({
    ...group,
    items: [...group.items].sort(
      (a, b) => a.line - b.line || a.name.localeCompare(b.name),
    ),
  }));
}

const selectedKey = (target: TargetRef) => targetSelectionKey(target);

export default function ProjectBrowser({
  project,
  revisionId,
  runId,
  scopeId,
  refreshKey,
  queries,
  selected,
  onSelect,
  onSelectionChange,
  onOpenSource,
  onEnterScope,
}: ProjectBrowserProps) {
  const [treePages, setTreePages] = useState<Map<string, MergedPage<TreeItem>>>(
    new Map(),
  );
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [scopeExpanded, setScopeExpanded] = useState<Set<string>>(new Set());
  const [objects, setObjects] = useState<Map<string, MergedPage<ObjectItem>>>(
    new Map(),
  );
  const [kindFilter, setKindFilter] = useState<"variables" | "all">(
    "variables",
  );
  const [statusFilter, setStatusFilter] = useState<"all" | "normal" | "failed">(
    "all",
  );
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const treeAbort = useRef<AbortController | null>(null);
  const objectAbort = useRef<AbortController | null>(null);
  const inflight = useRef(new Set<string>());
  const anchor = useRef<string | undefined>(undefined);
  const [menuTarget, setMenuTarget] = useState<{
    target: TargetRef;
    x: number;
    y: number;
  }>();
  const [selectingAll, setSelectingAll] = useState(false);

  const chooseObject = (target: TargetRef, event: ReactMouseEvent) => {
    const order = [...objects.values()].flatMap((page) =>
      page.items.map((item) => item.target),
    );
    const key = selectedKey(target),
      a = order.findIndex((item) => selectedKey(item) === anchor.current),
      b = order.findIndex((item) => selectedKey(item) === key);
    if (event.shiftKey && onSelectionChange && a >= 0 && b >= 0) {
      const range = order.slice(Math.min(a, b), Math.max(a, b) + 1);
      onSelectionChange([
        ...new Map(
          [...(event.ctrlKey || event.metaKey ? selected : []), ...range].map(
            (item) => [selectedKey(item), item],
          ),
        ).values(),
      ]);
    } else {
      anchor.current = key;
      onSelect(target, event);
    }
  };
  const selectAll = async () => {
    if (!onSelectionChange || selectingAll) return;
    const controller = objectAbort.current;
    if (!controller) return;
    setSelectingAll(true);
    try {
      const found: TargetRef[] = [];
      let offset = 0;
      while (!controller.signal.aborted) {
        const page = await queries.objects(
          revisionId,
          {
            run_id: runId,
            scope_id: scopeId || undefined,
            kind: kindFilter,
            probe_status: statusFilter,
            offset,
            limit: 1000,
          },
          controller.signal,
        );
        found.push(...page.items.map((item) => item.target));
        offset += page.items.length;
        if (offset >= page.total || !page.items.length) break;
      }
      if (!controller.signal.aborted) onSelectionChange(found);
    } catch (cause) {
      if (!controller.signal.aborted) setError((cause as Error).message);
    } finally {
      setSelectingAll(false);
    }
  };

  const selection = useMemo(
    () => new Set(selected.map(selectedKey)),
    [selected],
  );
  const itemsById = useMemo(() => {
    const map = new Map<string, TreeItem>();
    for (const page of treePages.values())
      for (const item of page.items) map.set(item.id, item);
    return map;
  }, [treePages]);

  const loadTree = useCallback(
    async (parentId: string | null, offset: number) => {
      const controller = treeAbort.current;
      if (!controller) return;
      try {
        const page = await queries.tree(
          revisionId,
          parentId
            ? { parent_id: parentId, offset, limit: PAGE }
            : { offset, limit: PAGE },
          controller.signal,
        );
        if (controller.signal.aborted) return;
        const key = parentId ?? ROOT;
        setTreePages((current) =>
          new Map(current).set(
            key,
            mergePage(current.get(key), page, offset > 0),
          ),
        );
      } catch (cause) {
        if (!controller.signal.aborted)
          setError(cause instanceof Error ? cause.message : "无法读取目录");
      }
    },
    [queries, revisionId],
  );

  // Tree reset for a new project/revision (and explicit refresh).
  useEffect(() => {
    treeAbort.current?.abort();
    const controller = new AbortController();
    treeAbort.current = controller;
    setTreePages(new Map());
    setExpanded(new Set());
    setScopeExpanded(new Set());
    setError("");
    void (async () => {
      try {
        const page = await queries.tree(
          revisionId,
          { offset: 0, limit: PAGE },
          controller.signal,
        );
        if (controller.signal.aborted) return;
        setTreePages((current) =>
          new Map(current).set(ROOT, mergePage(current.get(ROOT), page, false)),
        );
        const projectRoot =
          page.items.find((item) => item.kind === "project") ??
          page.items.find((item) => item.kind === "folder");
        if (!projectRoot) return;
        setExpanded(new Set([projectRoot.id]));
        const children = await queries.tree(
          revisionId,
          { parent_id: projectRoot.id, offset: 0, limit: PAGE },
          controller.signal,
        );
        if (controller.signal.aborted) return;
        setTreePages((current) =>
          new Map(current).set(
            projectRoot.id,
            mergePage(current.get(projectRoot.id), children, false),
          ),
        );
      } catch (cause) {
        if (!controller.signal.aborted)
          setError(cause instanceof Error ? cause.message : "无法读取目录");
      }
    })();
    return () => controller.abort();
  }, [project.id, revisionId, queries, refresh]);

  // A filter change invalidates every pending object response.
  useEffect(() => {
    objectAbort.current?.abort();
    const controller = new AbortController();
    objectAbort.current = controller;
    inflight.current = new Set();
    setObjects(new Map());
    return () => controller.abort();
  }, [
    kindFilter,
    statusFilter,
    project.id,
    revisionId,
    runId,
    scopeId,
    refreshKey,
  ]);

  const loadObjects = useCallback(
    async (fileId: string, offset: number) => {
      const controller = objectAbort.current;
      if (!controller) return;
      const key = `${fileId}:${kindFilter}:${statusFilter}`;
      if (inflight.current.has(key)) return;
      inflight.current.add(key);
      try {
        const page = await queries.objects(
          revisionId,
          {
            file_id: fileId,
            run_id: runId,
            scope_id: scopeId || undefined,
            kind: kindFilter === "variables" ? "variables" : "all",
            probe_status: statusFilter,
            offset,
            limit: PAGE,
          },
          controller.signal,
        );
        if (controller.signal.aborted) return;
        setObjects((current) =>
          new Map(current).set(
            fileId,
            mergePage(current.get(fileId), page, offset > 0),
          ),
        );
      } catch (cause) {
        if (!controller.signal.aborted)
          setError(cause instanceof Error ? cause.message : "无法读取对象");
      } finally {
        inflight.current.delete(key);
      }
    },
    [queries, revisionId, runId, scopeId, kindFilter, statusFilter],
  );

  useEffect(() => {
    for (const id of expanded) {
      const item = itemsById.get(id);
      const fileId = item?.kind === "file" ? item.file_id : null;
      if (fileId && !objects.has(fileId)) void loadObjects(fileId, 0);
    }
  }, [expanded, itemsById, objects, loadObjects]);

  const toggle = useCallback(
    (item: TreeItem) => {
      if (expanded.has(item.id)) {
        setExpanded((current) => {
          const next = new Set(current);
          next.delete(item.id);
          return next;
        });
        return;
      }
      setExpanded((current) => new Set(current).add(item.id));
      if (!treePages.has(item.id) && item.child_count > 0)
        void loadTree(item.id, 0);
    },
    [expanded, treePages, loadTree],
  );

  const openSource = useCallback(
    (target: TargetRef | null) => {
      if (target) onOpenSource(target);
    },
    [onOpenSource],
  );

  const renderItems = (items: TreeItem[], depth: number): ReactNode =>
    items.map((item) => {
      const fileId = item.kind === "file" ? item.file_id : null;
      const childPage = treePages.get(item.id);
      const isOpen = expanded.has(item.id);
      const isSelected = item.target
        ? selection.has(selectedKey(item.target))
        : false;
      const canExpand = item.kind === "file" || item.child_count > 0;
      return (
        <div key={item.id} className="project-tree-branch">
          <div
            className={"project-tree-row" + (isSelected ? " is-selected" : "")}
            role="treeitem"
            data-target-key={item.target ? selectedKey(item.target) : undefined}
            aria-expanded={canExpand ? isOpen : undefined}
            aria-selected={isSelected}
            aria-level={depth + 1}
          >
            {canExpand ? (
              <button
                type="button"
                className="project-tree-disclosure"
                aria-label={(isOpen ? "Collapse " : "Expand ") + item.label}
                aria-expanded={isOpen}
                onClick={(event) => {
                  event.stopPropagation();
                  toggle(item);
                }}
              >
                {isOpen ? "▾" : "▸"}
              </button>
            ) : (
              <span className="project-tree-disclosure" aria-hidden="true" />
            )}
            <span
              className="project-tree-label"
              tabIndex={0}
              onClick={(event: ReactMouseEvent) => {
                if (item.target) onSelect(item.target, event);
              }}
              onDoubleClick={() => openSource(item.target)}
              onKeyDown={(event: ReactKeyboardEvent) => {
                if (event.key === "Enter" && item.target)
                  openSource(item.target);
              }}
            >
              {item.label}
            </span>
            <span className="project-tree-meta">{item.kind}</span>
          </div>
          {isOpen && fileId && renderObjects(fileId)}
          {isOpen &&
            !fileId &&
            childPage &&
            renderItems(childPage.items, depth + 1)}
          {isOpen && !fileId && childPage && hasMore(childPage) && (
            <button
              type="button"
              className="project-toolbar-button"
              onClick={() => void loadTree(item.id, childPage.items.length)}
            >
              Load more ({childPage.total - childPage.items.length})
            </button>
          )}
        </div>
      );
    });

  const renderObjects = (fileId: string) => {
    const page = objects.get(fileId);
    if (!page) return <div className="project-empty">Loading…</div>;
    const groups = groupObjectsByScope(page.items);
    return (
      <div className="project-object-list">
        {groups.length === 0 && <div className="project-empty">No objects</div>}
        {groups.map((group) => (
          <div className="project-object-group" key={group.key}>
            <header>
              <button
                type="button"
                className="project-tree-disclosure"
                aria-expanded={scopeExpanded.has(group.key)}
                aria-label={
                  (scopeExpanded.has(group.key) ? "Collapse " : "Expand ") +
                  group.label
                }
                onClick={() =>
                  setScopeExpanded((current) => {
                    const next = new Set(current);
                    if (next.has(group.key)) next.delete(group.key);
                    else next.add(group.key);
                    return next;
                  })
                }
              >
                {scopeExpanded.has(group.key) ? "▾" : "▸"}
              </button>
              <span className="project-object-name" title={group.scope}>
                {group.label}
              </span>
              <span className="project-object-detail">
                {group.items.length} values
              </span>
            </header>
            {scopeExpanded.has(group.key) &&
              group.items.map((item) => {
                const isSelected = selection.has(selectedKey(item.target));
                const shape = item.shape?.length ? item.shape.join(" × ") : "—";
                return (
                  <div
                    className={
                      "project-object-row" + (isSelected ? " is-selected" : "")
                    }
                    key={item.target.object_id ?? item.name + item.line}
                    role="treeitem"
                    data-target-key={selectedKey(item.target)}
                    tabIndex={0}
                    aria-selected={isSelected}
                    onClick={(event) => chooseObject(item.target, event)}
                    onDoubleClick={() => openSource(item.target)}
                    onKeyDown={(event: ReactKeyboardEvent) => {
                      if (event.key === "Enter") openSource(item.target);
                    }}
                  >
                    <span className="project-object-name">{item.name}</span>
                    <span className="project-object-detail">
                      {item.type ?? "—"}
                    </span>
                    <span className="project-object-detail">{shape}</span>
                    <span className="project-object-detail">
                      {item.probe_count} probes
                    </span>
                  </div>
                );
              })}
          </div>
        ))}
        {hasMore(page) && (
          <button
            type="button"
            className="project-toolbar-button"
            onClick={() => void loadObjects(fileId, page.items.length)}
          >
            Load more ({page.total - page.items.length})
          </button>
        )}
      </div>
    );
  };

  const root = treePages.get(ROOT);
  return (
    <div
      className="project-browser"
      onKeyDown={(event) => {
        if (
          (event.ctrlKey || event.metaKey) &&
          event.key.toLowerCase() === "a" &&
          !(
            event.target instanceof Element &&
            event.target.closest("input,textarea,select")
          )
        ) {
          event.preventDefault();
          void selectAll();
        }
      }}
      onContextMenu={(event) => {
        const row = (event.target as Element).closest("[data-target-key]");
        const key = row?.getAttribute("data-target-key");
        const object = [...objects.values()]
          .flatMap((page) => page.items)
          .find((item) => selectedKey(item.target) === key);
        const tree = [...itemsById.values()].find(
          (item) => item.target && selectedKey(item.target) === key,
        );
        const target = object?.target ?? tree?.target;
        if (target) {
          event.preventDefault();
          setMenuTarget({ target, x: event.clientX, y: event.clientY });
        }
      }}
    >
      <div className="project-browser-toolbar">
        <span className="project-tree-meta">{project.name}</span>
        {selectingAll && <span role="status">正在全选…</span>}
        <button
          type="button"
          className={
            "project-toolbar-button" +
            (kindFilter === "variables" ? " is-active" : "")
          }
          onClick={() => setKindFilter("variables")}
        >
          仅变量
        </button>
        <button
          type="button"
          className={
            "project-toolbar-button" +
            (kindFilter === "all" ? " is-active" : "")
          }
          onClick={() => setKindFilter("all")}
        >
          全部
        </button>
        {(["all", "normal", "failed"] as const).map((status) => (
          <button
            key={status}
            type="button"
            className={
              "project-toolbar-button" +
              (statusFilter === status ? " is-active" : "")
            }
            onClick={() => setStatusFilter(status)}
          >
            {status === "all"
              ? "全部状态"
              : status === "normal"
                ? "正常"
                : "失败"}
          </button>
        ))}
        <button
          type="button"
          className="project-toolbar-button"
          onClick={() => setRefresh((value) => value + 1)}
        >
          刷新
        </button>
      </div>
      {error && (
        <div className="project-error" role="alert">
          {error}
          <button
            type="button"
            className="project-toolbar-button"
            onClick={() => setRefresh((value) => value + 1)}
          >
            Retry
          </button>
        </div>
      )}
      <div className="project-browser-body">
        <div
          className="project-browser-tree"
          role="tree"
          aria-label="Project files"
        >
          {root ? (
            renderItems(root.items, 0)
          ) : (
            <div className="project-empty">Loading…</div>
          )}
        </div>
      </div>
      {menuTarget && (
        <div
          className="project-context-menu"
          role="menu"
          style={{
            position: "fixed",
            left: menuTarget.x,
            top: menuTarget.y,
            zIndex: 80,
          }}
          onMouseLeave={() => setMenuTarget(undefined)}
        >
          <button
            role="menuitem"
            onClick={() => {
              onOpenSource(menuTarget.target);
              setMenuTarget(undefined);
            }}
          >
            打开
          </button>
          {menuTarget.target.kind !== "data" && (
            <button
              role="menuitem"
              onClick={() => {
                onEnterScope(menuTarget.target);
                setMenuTarget(undefined);
              }}
            >
              进入此块
            </button>
          )}
          <button role="menuitem" onClick={() => setMenuTarget(undefined)}>
            关闭
          </button>
        </div>
      )}
    </div>
  );
}
