import { memo, useEffect, useMemo, useRef, useState } from "react";
import type { AnalysisDocument, TargetRef } from "./generated";
import type { SnapshotRef } from "../generated";
import {
  choose,
  selectionBlocks,
  objectRows,
  selectionKey,
  type Selection,
  type ObjectRow,
} from "./selection";
import { Icon } from "./icons";
import { client } from "../client";
import type { ProbeOutput } from "./generated";
export const ObjectBrowser = memo(function ObjectBrowser({
  analysis,
  values,
  selection,
  onSelection,
  onOpen,
  onSource,
  onEnter,
  onBind,
  scope,
  outputs = [],
}: {
  analysis?: AnalysisDocument;
  values: SnapshotRef[];
  selection: Selection;
  onSelection: (s: Selection) => void;
  onOpen: (row: ObjectRow) => void;
  onSource: (row: ObjectRow) => void;
  onEnter: (id: string | null) => void;
  onBind: () => void;
  scope: string | null;
  outputs?: ProbeOutput[];
}) {
  const [query, setQuery] = useState(""),
    [type, setType] = useState("all"),
    [closed, setClosed] = useState<Set<string>>(new Set()),
    [top, setTop] = useState(0),
    [menu, setMenu] = useState<{ row: ObjectRow; x: number; y: number }>();
  const [expandedData, setExpandedData] = useState<Set<string>>(new Set()),
    [histories, setHistories] = useState<Map<string, SnapshotRef[]>>(new Map()),
    [notice, setNotice] = useState(""),
    [status, setStatus] = useState("all"),
    [probe, setProbe] = useState("all");
  const version = useRef(0);
  useEffect(() => {
    version.current++;
    setHistories(new Map());
    setExpandedData(new Set());
  }, [analysis?.id, values[0]?.run_id]);
  const expanded = useMemo(
    () =>
      new Set([
        ...(analysis?.graph.blocks
          .map((b) => b.id)
          .filter((id) => !closed.has(id)) ?? []),
        ...expandedData,
      ]),
    [analysis?.id, closed, expandedData],
  );
  const rows = useMemo(
    () =>
      objectRows(
        analysis,
        values,
        scope,
        expanded,
        query,
        type,
        histories,
      ).filter(
        (r) =>
          r.block ||
          ((status === "all" ||
            (status === "observed" && !!r.snapshot) ||
            (status === "unobserved" && !r.snapshot)) &&
            (probe === "all" ||
              outputs.some(
                (o) =>
                  o.targets.some(
                    (t) => t.logical_key === r.target.logical_key,
                  ) &&
                  (probe === "bound" || ["fail", "error"].includes(o.status)),
              ))),
      ),
    [
      analysis,
      values,
      scope,
      expanded,
      query,
      type,
      histories,
      status,
      probe,
      outputs,
    ],
  );
  const keys = useMemo(
    () => new Set(selection.targets.map(selectionKey)),
    [selection],
  );
  const selectedObjects = useMemo(
    () =>
      new Set(
        selection.targets
          .filter((t) => !t.exact_evidence)
          .flatMap((t) => (t.object_id ? [t.object_id] : [])),
      ),
    [selection],
  );
  const selectedBlocks = useMemo(()=>selectionBlocks(analysis?.graph.blocks??[],selection.targets),[analysis,selection]);
  const order = useMemo(() => rows.map((r) => r.target), [rows]);
  const viewport = useRef<HTMLDivElement>(null),
    start = Math.max(0, Math.floor(top / 32) - 3),
    visible = rows.slice(start, start + 40);
  const select = (
    row: ObjectRow,
    e: { ctrlKey?: boolean; metaKey?: boolean; shiftKey?: boolean },
  ) =>
    onSelection(
      choose(selection, row.target, order, {
        toggle: e.ctrlKey || e.metaKey,
        shift: e.shiftKey,
      }),
    );
  return (
    <section className="object-browser" aria-label="对象浏览器">
      <div className="wb-section-label">
        对象浏览器 <span>{rows.length}</span>
      </div>
      <div className="object-filters">
        <input
          type="search"
          aria-label="搜索对象"
          value={query}
          placeholder="搜索对象"
          onChange={(e) => {
            setQuery(e.target.value);
            setTop(0);
            if (viewport.current) viewport.current.scrollTop = 0;
          }}
        />
        <select
          aria-label="对象类型"
          value={type}
          onChange={(e) => setType(e.target.value)}
        >
          <option value="all">全部类型</option>
          {["matrix", "table", "scalar", "function", "condition", "loop"].map(
            (v) => (
              <option key={v}>{v}</option>
            ),
          )}
        </select>
      </div>
      <div className="object-filters">
        <select
          aria-label="对象证据状态"
          value={status}
          onChange={(e) => setStatus(e.target.value)}
        >
          <option value="all">全部证据</option>
          <option value="observed">已观测</option>
          <option value="unobserved">未观测</option>
        </select>
        <select
          aria-label="对象探针结果"
          value={probe}
          onChange={(e) => setProbe(e.target.value)}
        >
          <option value="all">全部结果</option>
          <option value="bound">有探针结果</option>
          <option value="failed">检查异常</option>
        </select>
      </div>
      <div className="scope-breadcrumb">
        <button onClick={() => onEnter(null)}>项目</button>
        {scope && (
          <>
            <span>/</span>
            <button
              onClick={() =>
                onEnter(
                  analysis?.graph.blocks.find((b) => b.id === scope)
                    ?.parent_id ?? null,
                )
              }
            >
              {analysis?.graph.blocks.find((b) => b.id === scope)?.label}
            </button>
          </>
        )}
      </div>
      <div
        role="tree"
        aria-label="计算对象树"
        aria-multiselectable="true"
        tabIndex={0}
        ref={viewport}
        className="object-tree"
        onScroll={(e) => setTop(e.currentTarget.scrollTop)}
        onKeyDown={(e) => {
          if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "a") {
            e.preventDefault();
            if (order.length)
              onSelection(choose(selection, order[0], order, { all: true }));
            return;
          }
          if (!rows.length) return;
          const i = Math.max(
            0,
            rows.findIndex(
              (r) =>
                selectionKey(r.target) ===
                selectionKey(selection.targets.at(-1) ?? order[0]),
            ),
          );
          if (e.key === "ArrowDown" || e.key === "ArrowUp") {
            e.preventDefault();
            const next = Math.max(
              0,
              Math.min(rows.length - 1, i + (e.key === "ArrowDown" ? 1 : -1)),
            );
            if (rows[next]) {
              select(rows[next], e);
              viewport.current?.scrollTo({ top: Math.max(0, next * 32 - 100) });
            }
          }
          if (e.key === "Enter" && selection.targets.length === 1 && rows[i]) {
            e.preventDefault();
            onOpen(rows[i]);
          }
          if (
            (e.key === "ContextMenu" || (e.shiftKey && e.key === "F10")) &&
            rows[i]
          ) {
            e.preventDefault();
            setMenu({ row: rows[i], x: 200, y: 250 });
          }
        }}
      >
        <div style={{ height: rows.length * 32, position: "relative" }}>
          {visible.map((row, i) => {
            const selected =
              selectedBlocks.covered.has(row.block?.id??row.target.block_id??'') || keys.has(selectionKey(row.target)) ||
              Boolean(row.objectId && selectedObjects.has(row.objectId));
            const partial =
              row.block &&
              !selected &&
              selectedBlocks.partial.has(row.block!.id);
            return (
              <div
                key={row.id}
                role="treeitem"
                aria-level={row.depth + 1}
                aria-selected={selected}
                aria-expanded={
                  row.block || row.expandable ? expanded.has(row.id) : undefined
                }
                className={
                  "object-row " +
                  (selected ? "selected " : "") +
                  (partial ? "part-selected" : "")
                }
                style={{
                  top: (start + i) * 32,
                  paddingLeft: 8 + row.depth * 12,
                }}
                onClick={(e) => select(row, e)}
                onDoubleClick={() => onOpen(row)}
                onContextMenu={(e) => {
                  e.preventDefault();
                  if (!selected) select(row, {});
                  setMenu({ row, x: e.clientX, y: e.clientY });
                }}
              >
                {row.block || row.expandable ? (
                  <button
                    className="tree-toggle"
                    aria-label={
                      (expanded.has(row.id) ? "折叠 " : "展开 ") + row.label
                    }
                    onClick={(e) => {
                      e.stopPropagation();
                      if (row.expandable) {
                        setExpandedData((old) => {
                          const n = new Set(old);
                          n.has(row.id) ? n.delete(row.id) : n.add(row.id);
                          return n;
                        });
                        if (!histories.has(row.id) && row.snapshot) {
                          const v = version.current;
                          void client
                            .history(
                              row.snapshot.run_id,
                              row.snapshot.binding_id,
                            )
                            .then((h) => {
                              if (v === version.current)
                                setHistories(
                                  (old) => new Map([...old, [row.id, h]]),
                                );
                            })
                            .catch((e) => {
                              if (v === version.current) setNotice(e.message);
                            });
                        }
                        return;
                      }
                      setClosed((old) => {
                        const n = new Set(old);
                        n.has(row.id) ? n.delete(row.id) : n.add(row.id);
                        return n;
                      });
                    }}
                  >
                    <Icon name="chevron" size={10} />
                  </button>
                ) : (
                  <span
                    className={
                      "object-type " + (row.snapshot?.descriptor.kind ?? "data")
                    }
                  />
                )}
                <span
                  className="object-row-name"
                  title={row.target.logical_key}
                >
                  {row.label}
                </span>
                <small title={row.detail}>{row.detail}</small>
              </div>
            );
          })}
        </div>
      </div>
      <div className="object-selection">
        <span>{selection.targets.length} 项选中</span>
        <button disabled={!selection.targets.length} onClick={onBind}>
          绑定探针
        </button>
      </div>
      {menu && (
        <div className="context-backdrop" onClick={() => setMenu(undefined)}>
          <div
            role="menu"
            className="workspace-menu object-context"
            style={{
              left: Math.min(menu.x, innerWidth - 210),
              top: Math.min(menu.y, innerHeight - 210),
            }}
          >
            {menu.row.snapshot && (
              <button onClick={() => onOpen(menu.row)}>打开数据</button>
            )}
            <button onClick={() => onSource(menu.row)}>定位源码</button>
            {menu.row.block && (
              <button onClick={() => onEnter(menu.row.id)}>进入此块</button>
            )}
            <button onClick={onBind}>绑定探针</button>
          </div>
        </div>
      )}
      {notice && <small role="status">{notice}</small>}
    </section>
  );
});
