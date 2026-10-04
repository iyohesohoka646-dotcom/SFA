import { memo, useEffect, useMemo, useRef, useState } from "react";
import type { AnalysisDocument, ProbeDefinition, ProbeOutput, WorkbenchConfig } from "./generated";
import type { SnapshotRef } from "../generated";
import { choose, selectionBlocks, selectionKey, type Selection, type ObjectRow } from "./selection";
import { buildObjectTree, initialObjectExpansion, logicalSelectionCount, selectableObjectOrder, selectionObjectIds, type BrowserRow } from "./objectTree";
import type { OccurrenceGroup } from "./sourceOccurrences";
import { Icon } from "./icons";
import { wb } from "./WorkbenchClient";
import "./object-browser.css";

function RowIcon({ kind }: { kind: BrowserRow["rowKind"] }) {
  const paths = {
    folder: "M3 6h7l2 3h9v11H3z",
    file: "M6 3h8l4 4v14H6zM14 3v5h4M9 12h6M9 16h4",
    function: "M15 3h-3l-3 18H6M5 9h10M17 12l4 4-4 4",
    class: "M5 4h14v16H5zM5 9h14M9 9v11",
    variable: "M4 4h16v16H4zM4 10h16M10 4v16",
    assignment: "M5 6h14M5 11h9M5 16h14M16 9l4 3-4 3",
    evidence: "M12 3a9 9 0 1 0 9 9M12 7v5l4 2M17 3h4v4",
    control: "M5 4h14v16H5zM9 8h6M9 12h6M9 16h3",
  };
  return <svg className={"object-kind-icon " + kind} width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[kind]} /></svg>;
}

export const ObjectBrowser = memo(function ObjectBrowser({ analysis, values, selection, onSelection, onOpen, onSource, onEnter, onBind, scope, outputs = [], config, definitions = [] }: {
  analysis?: AnalysisDocument;
  values: SnapshotRef[];
  selection: Selection;
  onSelection: (selection: Selection) => void;
  onOpen: (row: ObjectRow) => void;
  onSource: (row: ObjectRow) => void;
  onEnter: (id: string | null) => void;
  onBind: () => void;
  scope: string | null;
  outputs?: ProbeOutput[];
  config?: WorkbenchConfig;
  definitions?: ProbeDefinition[];
}) {
  const [query, setQuery] = useState(""), [type, setType] = useState("variables"), [top, setTop] = useState(0);
  const [probe, setProbe] = useState("all"), [notice, setNotice] = useState("");
  const [occurrences, setOccurrences] = useState<{ analysisId?: string; groups: OccurrenceGroup[] }>({ groups: [] });
  const expansionKey = `${analysis?.id ?? ""}:${scope ?? ""}`;
  const [expansion, setExpansion] = useState(() => ({ key: expansionKey, ids: initialObjectExpansion(analysis, scope) }));
  const expanded = expansion.key === expansionKey ? expansion.ids : initialObjectExpansion(analysis, scope);
  const [menu, setMenu] = useState<{ row: BrowserRow; x: number; y: number }>();
  const [focused, setFocused] = useState<string>();
  const viewport = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setNotice("");
  }, [analysis?.id, values[0]?.run_id]);
  useEffect(() => {
    setExpansion({ key: expansionKey, ids: initialObjectExpansion(analysis, scope) });
    setTop(0);
    setFocused(undefined);
    setMenu(undefined);
    if (viewport.current) viewport.current.scrollTop = 0;
  }, [expansionKey]);
  useEffect(() => {
    const abort = new AbortController();
    setOccurrences({ groups: [] });
    if (analysis) void wb.occurrences(analysis.id, abort.signal)
      .then(groups => { if (!abort.signal.aborted) setOccurrences({ analysisId: analysis.id, groups }); })
      .catch(error => { if (!abort.signal.aborted) setNotice(error.message); });
    return () => abort.abort();
  }, [analysis?.id]);
  const groups = occurrences.analysisId === analysis?.id ? occurrences.groups : [];
  const rows = useMemo(() => buildObjectTree(analysis, values, scope, expanded, query, type, new Map(), { probe, outputs, occurrences: groups, probes: config?.probes, definitions }),
    [analysis, values, scope, expanded, query, type, probe, outputs, groups, config?.probes, definitions]);
  const keys = useMemo(() => new Set(selection.targets.map(selectionKey)), [selection]);
  const selectedObjects = useMemo(() => selectionObjectIds(analysis, selection.targets.filter(target => !target.exact_evidence), groups), [analysis, selection, groups]);
  const selectedBlocks = useMemo(() => selectionBlocks(analysis?.graph.blocks ?? [], selection.targets), [analysis, selection]);
  const order = useMemo(() => selectableObjectOrder(rows), [rows]);
  const start = Math.max(0, Math.floor(top / 32) - 3), visible = rows.slice(start, start + 40);
  const isSelected = (row: BrowserRow) => row.selectable && (selectedBlocks.covered.has(row.block?.id ?? row.target.block_id ?? "")
    || keys.has(selectionKey(row.target)) || (row.rowKind !== "evidence" && (row.objectIds ?? []).some(id => selectedObjects.has(id))));
  const select = (row: BrowserRow, event: { ctrlKey?: boolean; metaKey?: boolean; shiftKey?: boolean }) => {
    setFocused(row.id);
    if (row.selectable) onSelection(choose(selection, row.target, order, { toggle: event.ctrlKey || event.metaKey, shift: event.shiftKey }));
  };
  const toggle = (row: BrowserRow) => {
    if (!row.expandable) return;
    setExpansion(current => {
      const ids = new Set(current.key === expansionKey ? current.ids : initialObjectExpansion(analysis, scope));
      ids.has(row.id) ? ids.delete(row.id) : ids.add(row.id);
      return { key: expansionKey, ids };
    });
  };
  const focusRow = (index: number, event: { ctrlKey?: boolean; metaKey?: boolean; shiftKey?: boolean }) => {
    const row = rows[index];
    if (!row) return;
    select(row, event);
    viewport.current?.scrollTo({ top: Math.max(0, index * 32 - 100) });
  };
  const closeMenu = (action: () => void) => { action(); setMenu(undefined); };

  return <section className="object-browser" aria-label="对象浏览器">
    <div className="wb-section-label">对象浏览器 <span>{rows.filter(row => row.rowKind === "variable").length}</span></div>
    <div className="object-filters">
      <input type="search" aria-label="搜索对象" value={query} placeholder="搜索名称或作用域" onChange={event => {
        setQuery(event.target.value); setTop(0); if (viewport.current) viewport.current.scrollTop = 0;
      }} />
    </div>
    <div className="object-filters">
      <select aria-label="对象类型" value={type} onChange={event => { setType(event.target.value); setTop(0); if (viewport.current) viewport.current.scrollTop = 0; }}><option value="variables">仅变量</option><option value="all">全部</option></select>
      <select aria-label="对象探针结果" value={probe} onChange={event => { setProbe(event.target.value); setTop(0); if (viewport.current) viewport.current.scrollTop = 0; }}><option value="all">全部</option><option value="failed">探针异常</option><option value="normal">正常</option></select>
    </div>
    <div className="object-column-headings" aria-hidden="true"><span>名称</span><span>类型</span><span>形状</span><span>探针</span></div>
    <div className="scope-breadcrumb">
      <button onClick={() => onEnter(null)}>项目</button>
      {scope && <><span>/</span><button title="返回上级范围" onClick={() => onEnter(analysis?.graph.blocks.find(block => block.id === scope)?.parent_id ?? null)}>{analysis?.graph.blocks.find(block => block.id === scope)?.label}</button></>}
    </div>
    <div role="tree" aria-label="计算对象树" aria-multiselectable="true" aria-activedescendant={focused ? "object-item:" + focused : undefined} tabIndex={0} ref={viewport} className="object-tree"
      onScroll={event => setTop(event.currentTarget.scrollTop)}
      onKeyDown={event => {
        if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "a") {
          event.preventDefault();
          const allExpanded = new Set([
            ...(analysis?.graph.blocks.map(block => block.id) ?? []),
            ...rows.filter(row => row.rowKind === "folder").map(row => row.id),
          ]);
          const allRows = buildObjectTree(analysis, values, scope, allExpanded, query, type, new Map(), { probe, outputs, occurrences: groups, probes: config?.probes, definitions });
          const matching = selectableObjectOrder(allRows.filter(row => row.matchesFilter));
          onSelection(matching.length ? choose(selection, matching[0], matching, { all: true }) : { targets: [], anchor: null });
          return;
        }
        if (!rows.length) return;
        const index = Math.max(0, rows.findIndex(row => row.id === focused || !focused && selectionKey(row.target) === selectionKey(selection.targets.at(-1) ?? order[0] ?? row.target)));
        const row = rows[index];
        if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
          event.preventDefault(); focusRow(event.key === "Home" ? 0 : event.key === "End" ? rows.length - 1 : Math.max(0, Math.min(rows.length - 1, index + (event.key === "ArrowDown" ? 1 : -1))), event);
        } else if (event.key === "ArrowRight") {
          event.preventDefault(); if (row.expandable && !expanded.has(row.id)) toggle(row); else if (rows[index + 1]?.parent === row.id) focusRow(index + 1, event);
        } else if (event.key === "ArrowLeft") {
          event.preventDefault(); if (row.expandable && expanded.has(row.id)) toggle(row); else { const parent = rows.findIndex(item => item.id === row.parent); if (parent >= 0) focusRow(parent, event); }
        } else if (event.key === " " && !row.selectable) {
          event.preventDefault(); toggle(row);
        } else if (event.key === "Enter") {
          event.preventDefault(); if (row.rowKind === "folder") toggle(row); else if (selection.targets.length <= 1) onOpen(row);
        } else if (event.key === "ContextMenu" || event.shiftKey && event.key === "F10") {
          event.preventDefault(); const bounds = viewport.current?.getBoundingClientRect(); setMenu({ row, x: bounds?.left ?? 200, y: Math.min((bounds?.top ?? 200) + (index - start) * 32, (bounds?.bottom ?? 450) - 32) });
        }
      }}>
      <div style={{ height: rows.length * 32, position: "relative" }}>
        {visible.map((row, index) => {
          const selected = isSelected(row), partial = row.block && !selected && selectedBlocks.partial.has(row.block.id);
          const open = expanded.has(row.id) || rows.some(item => item.parent === row.id);
          return <div key={row.id} id={"object-item:" + row.id} role="treeitem" aria-level={row.depth + 1} aria-selected={row.selectable ? selected : undefined} aria-expanded={row.expandable ? open : undefined}
            className={"object-row object-row-" + row.rowKind + (selected ? " selected" : "") + (partial ? " part-selected" : "") + (focused === row.id ? " tree-focused" : "")}
            style={{ top: (start + index) * 32, paddingLeft: 6 + row.depth * 10 }}
            onClick={event => select(row, event)} onDoubleClick={event => { if (!event.ctrlKey && !event.metaKey && !event.shiftKey) row.rowKind === "folder" ? toggle(row) : onOpen(row); }}
            onContextMenu={event => { event.preventDefault(); if (row.selectable && !selected) select(row, {}); setFocused(row.id); setMenu({ row, x: event.clientX, y: event.clientY }); }}>
            {row.expandable ? <button className="tree-toggle" tabIndex={-1} aria-label={(open ? "折叠 " : "展开 ") + row.label} aria-expanded={open}
              onClick={event => { event.stopPropagation(); toggle(row); }}><span className={"tree-chevron " + (open ? "open" : "")}><Icon name="chevron" size={12} /></span></button> : <span className="tree-toggle-spacer" />}
            <RowIcon kind={row.rowKind} />
            <span className="object-row-name" title={row.source?.code || row.target.logical_key}>{row.label}</span>
            <span className="object-metadata" title={row.detail}><small className="object-dtype">{row.typeLabel}</small><small className="object-shape">{row.shapeLabel}</small>{row.selectable ? <button className="object-probe-count" tabIndex={-1} aria-label={`${row.label} 的探针 (${row.probeCount})`} onClick={event => { event.stopPropagation(); if (!selected) select(row, {}); onBind(); }}>{row.probeCount}</button> : <small>—</small>}</span>
          </div>;
        })}
      </div>
      {!rows.length && <p className="object-tree-empty">{analysis ? "没有匹配的对象。" : "导入 Python 文件后查看对象。"}</p>}
    </div>
    <div className="object-selection"><span>{logicalSelectionCount(selection.targets)} 项选中</span><button disabled={!selection.targets.length} onClick={onBind}>绑定探针</button></div>
    {menu && <div className="context-backdrop" onClick={() => setMenu(undefined)}><div role="menu" className="workspace-menu object-context" style={{ left: Math.max(0, Math.min(menu.x, innerWidth - 210)), top: Math.max(0, Math.min(menu.y, innerHeight - 210)) }}>
      {menu.row.snapshot && <button role="menuitem" onClick={() => closeMenu(() => onOpen(menu.row))}>打开数据</button>}
      <button role="menuitem" onClick={() => closeMenu(() => onSource(menu.row))}>{menu.row.rowKind === "folder" ? "打开源码文件" : "定位源码"}</button>
      {menu.row.block && <button role="menuitem" onClick={() => closeMenu(() => onEnter(menu.row.id))}>进入此块</button>}
      {menu.row.expandable && <button role="menuitem" onClick={() => closeMenu(() => toggle(menu.row))}>{expanded.has(menu.row.id) ? "折叠" : "展开"}</button>}
      {menu.row.selectable && <button role="menuitem" onClick={() => closeMenu(onBind)}>绑定探针</button>}
    </div></div>}
    {notice && <small role="status" className="object-tree-notice">{notice}</small>}
  </section>;
});
