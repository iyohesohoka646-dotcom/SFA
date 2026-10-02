import type {
  AnalysisDocument,
  SemanticGraph,
  TargetRef,
  GraphNode,
  GraphBlock,
  GraphEdge,
  ScopeSelector,
} from "./generated";
import type { SnapshotRef } from "../generated";
export interface Selection {
  targets: TargetRef[];
  anchor: string | null;
}
export const selectionKey = (t: TargetRef) =>
  t.kind +
  ":" +
  t.logical_key +
  (t.exact_evidence && t.snapshot_id ? ":" + t.snapshot_id : "");
export function choose(
  state: Selection,
  target: TargetRef,
  order: TargetRef[],
  action: { toggle?: boolean; shift?: boolean; all?: boolean },
): Selection {
  const key = selectionKey(target);
  if (action.all) return { targets: unique(order), anchor: key };
  if (action.shift && state.anchor) {
    const a = order.findIndex((t) => selectionKey(t) === state.anchor),
      b = order.findIndex((t) => selectionKey(t) === key);
    if (a >= 0 && b >= 0)
      return {
        targets: unique(
          action.toggle
            ? [
                ...state.targets,
                ...order.slice(Math.min(a, b), Math.max(a, b) + 1),
              ]
            : order.slice(Math.min(a, b), Math.max(a, b) + 1),
        ),
        anchor: state.anchor,
      };
  }
  if (action.toggle)
    return {
      targets: state.targets.some((t) => selectionKey(t) === key)
        ? state.targets.filter((t) => selectionKey(t) !== key)
        : [...state.targets, target],
      anchor: key,
    };
  return { targets: [target], anchor: key };
}
export const unique = (items: TargetRef[]) => [
  ...new Map(items.map((t) => [selectionKey(t), t])).values(),
];
export interface ObjectRow {
  id: string;
  parent?: string;
  depth: number;
  label: string;
  detail: string;
  target: TargetRef;
  block?: GraphBlock;
  snapshot?: SnapshotRef;
  objectId?: string;
  expandable?: boolean;
}
export function objectRows(
  analysis: AnalysisDocument | undefined,
  values: SnapshotRef[],
  scope: string | null,
  expanded: Set<string>,
  query = "",
  type = "all",
  histories: Map<string, SnapshotRef[]> = new Map(),
): ObjectRow[] {
  if (!analysis) return [];
  const blocks = analysis.graph.blocks,
    index = new Map(blocks.map((b) => [b.id, b]));
  const inScope = (id: string | undefined) => {
    if (!scope) return true;
    const visited = new Set<string>();
    while (id && !visited.has(id)) {
      if (id === scope) return true;
      visited.add(id);
      id = index.get(id)?.parent_id ?? undefined;
    }
    return false;
  };
  const current = new Map(values.map((s) => [s.logical_key, s]));
  const rows: ObjectRow[] = [],
    objects = new Map<string, AnalysisDocument["objects"]>();
  const canonical = new Map<string, AnalysisDocument["objects"][number]>();
  for (const o of [...analysis.objects].sort(
    (a, b) => a.line - b.line || a.column - b.column,
  )) {
    if (
      o.kind === "function" ||
      o.kind === "class" ||
      o.kind === "step" ||
      o.kind === "import"
    )
      continue;
    if (!scope && canonical.has(o.logical_key)) continue;
    canonical.set(o.logical_key, o);
    const list = objects.get(o.block_id) ?? [];
    list.push(o);
    objects.set(o.block_id, list);
  }
  for (const n of analysis.graph.nodes)
    if (
      (n.kind === "parameter" || n.kind === "data") &&
      n.logical_key &&
      !canonical.has(n.logical_key)
    ) {
      const o = {
        id: n.source_object_id ?? n.id,
        logical_key: n.logical_key,
        name: n.label,
        kind: "parameter",
        block_id: n.block_id,
        line: n.source?.line ?? 1,
        column: n.source?.column ?? 0,
      } as AnalysisDocument["objects"][number];
      canonical.set(o.logical_key, o);
      const list = objects.get(o.block_id) ?? [];
      list.push(o);
      objects.set(o.block_id, list);
    }
  const known = new Set(canonical.keys());
  const pass = (name: string, detail: string, kind = detail) =>
    (name + " " + detail).toLowerCase().includes(query.toLowerCase()) &&
    (type === "all" || kind === type || detail.includes(type));
  function visit(block: GraphBlock, depth: number) {
    if (!inScope(block.id) && scope !== block.id) return;
    const target = {
      kind:
        block.kind === "function" || block.kind === "class"
          ? "function"
          : block.kind === "file"
            ? "file"
            : "control",
      logical_key: block.logical_key,
      block_id: block.id,
      object_id: block.source_object_id,
      analysis_id: analysis!.id,
    } as TargetRef;
    const children = objects.get(block.id) ?? [];
    const nested = blocks.filter((b) => b.parent_id === block.id);
    const matches = children.some((o) =>
      pass(o.name, current.get(o.logical_key)?.descriptor.kind ?? o.kind),
    );
    const blockMatches =
      pass(block.label, block.kind) || matches || (query && nested.length);
    if (!query || blockMatches)
      rows.push({
        id: block.id,
        depth,
        label: block.label,
        detail: block.kind,
        target,
        block,
        objectId: block.source_object_id ?? undefined,
      });
    if (!expanded.has(block.id) && !query) return;
    for (const child of nested) visit(child, depth + 1);
    const emitted = new Set<string>();
    for (const o of children) {
      if (emitted.has(o.logical_key)) continue;
      emitted.add(o.logical_key);
      const snapshot = current.get(o.logical_key),
        origin = snapshot?.source
          ? (analysis!.objects.find(
              (a) =>
                a.logical_key === o.logical_key &&
                a.line === snapshot.source?.line,
            ) ?? o)
          : o,
        detail = snapshot
          ? `${snapshot.descriptor.dtype ?? snapshot.descriptor.kind} · ${snapshot.descriptor.shape?.join(" × ") ?? ""} · v${snapshot.version}`
          : o.kind + ` · L${o.line}`;
      if (!pass(o.name, detail, snapshot?.descriptor.kind ?? o.kind)) continue;
      const rowId = selectionKey({
        kind: "data",
        logical_key: o.logical_key,
      } as TargetRef);
      rows.push({
        id: rowId,
        depth: depth + 1,
        label: o.name,
        detail,
        objectId: origin.id,
        snapshot,
        expandable: !!snapshot,
        target: {
          kind: "data",
          logical_key: o.logical_key,
          object_id: origin.id,
          block_id: origin.block_id ?? block.id,
          analysis_id: analysis!.id,
          run_id: snapshot?.run_id,
          snapshot_id: snapshot?.id,
        } as TargetRef,
      });
      if (expanded.has(rowId)) {
        const versions =
          histories.get(rowId) ??
          values.filter((v) => v.logical_key === o.logical_key);
        for (const v of versions) {
          const versionOrigin =
            analysis!.objects.find(
              (a) =>
                a.logical_key === o.logical_key && a.line === v.source?.line,
            ) ?? origin;
          const ref = {
            kind: "data",
            logical_key: o.logical_key,
            object_id: versionOrigin.id,
            block_id: versionOrigin.block_id ?? block.id,
            analysis_id: analysis!.id,
            run_id: v.run_id,
            snapshot_id: v.id,
            exact_evidence: true,
          } as TargetRef;
          rows.push({
            id: "evidence:" + v.id,
            parent: rowId,
            depth: depth + 2,
            label: "v" + v.version,
            detail:
              v.scope_id === "main"
                ? "L" + (v.source?.line ?? o.line)
                : v.scope_id,
            snapshot: v,
            objectId: versionOrigin.id,
            target: ref,
          });
        }
      }
    }
  }
  for (const block of blocks.filter(
    (b) => b.id === scope || (!scope && !b.parent_id),
  ))
    visit(block, 0);
  if (!scope)
    for (const s of values.filter((s) => !known.has(s.logical_key))) {
      if (pass(s.name, s.descriptor.kind))
        rows.push({
          id: s.id,
          depth: 1,
          label: s.name,
          detail:
            s.descriptor.kind +
            " · v" +
            s.version +
            (s.scope_id === "derived" ? " · 派生" : ""),
          snapshot: s,
          target: {
            kind: "data",
            logical_key: s.logical_key || s.binding_id,
            snapshot_id: s.id,
            run_id: s.run_id,
          } as TargetRef,
        });
    }
  return rows;
}
export type ProjectionNode = (GraphNode | GraphBlock) & {
  parent_id?: string | null;
  plate?: boolean;
};
export function projectGraph(
  graph: SemanticGraph,
  collapsed: Set<string>,
  view: "structure" | "data" | "execution",
  scope?: string | null,
) {
  const parent = new Map<string, string | undefined>([
    ...graph.blocks.map((b) => [b.id, b.parent_id ?? undefined] as const),
    ...graph.nodes.map((n) => [n.id, n.block_id] as const),
  ]);
  function under(id: string, ancestor: string) {
    const seen = new Set<string>();
    while (id && !seen.has(id)) {
      if (id === ancestor) return true;
      seen.add(id);
      id = parent.get(id) ?? "";
    }
    return false;
  }
  const representative = (id: string) => {
    let result = id,
      current = parent.get(id);
    const seen = new Set<string>();
    while (current && !seen.has(current)) {
      seen.add(current);
      if (collapsed.has(current) && current !== scope) result = current;
      current = parent.get(current);
    }
    return result;
  };
  const blocks = graph.blocks.filter(
    (b) => (!scope || under(b.id, scope)) && representative(b.id) === b.id,
  );
  const nodes: ProjectionNode[] = [
    ...blocks.map((b) => ({
      ...b,
      parent_id: b.id === scope ? null : b.parent_id,
      plate: true,
    })),
    ...graph.nodes
      .filter(
        (n) =>
          (!scope || under(n.id, scope)) &&
          representative(n.id) === n.id &&
          (view === "data" || n.kind !== "data"),
      )
      .map((n) => ({ ...n, parent_id: n.block_id })),
  ];
  const known = new Set(nodes.map((n) => n.id)),
    edges = new Map<string, GraphEdge>();
  // Structure ports bypass hidden value nodes, preserving the calculation chain.
  const hidden = new Set(
    graph.nodes
      .filter((n) => !known.has(n.id) && representative(n.id) === n.id)
      .map((n) => n.id),
  );
  const candidates = [...graph.edges];
  const incoming = new Map<string, GraphEdge[]>(),
    outgoing = new Map<string, GraphEdge[]>();
  for (const e of graph.edges)
    if (e.kind === "data") {
      incoming.set(e.target, [...(incoming.get(e.target) ?? []), e]);
      outgoing.set(e.source, [...(outgoing.get(e.source) ?? []), e]);
    }
  if (view !== "data")
    for (const n of hidden) {
      const ins = incoming.get(n) ?? [],
        outs = outgoing.get(n) ?? [];
      for (const a of ins)
        for (const b of outs)
          candidates.push({
            ...b,
            id: a.id + ">" + b.id,
            source: a.source,
            source_port: a.source_port,
            original_ids: [a.id, b.id],
            label: a.label || b.label,
          });
    }
  for (const e of candidates) {
    if (e.kind === "contains") continue;
    const source = representative(e.source),
      target = representative(e.target);
    if (
      !known.has(source) ||
      !known.has(target) ||
      (source === target && e.source !== e.target)
    )
      continue;
    const key = source + ">" + target + ":" + e.kind + ":" + e.branch;
    if (edges.has(key)) {
      const old = edges.get(key)!;
      old.count = (old.count ?? 1) + (e.count ?? 1);
      old.original_ids.push(
        ...(e.original_ids?.length ? e.original_ids : [e.id]),
      );
    } else
      edges.set(key, {
        ...e,
        id: key,
        source,
        target,
        source_port: source === e.source ? e.source_port : null,
        target_port: target === e.target ? e.target_port : null,
        original_ids: e.original_ids?.length ? e.original_ids : [e.id],
        count: e.count ?? 1,
      });
  }
  return {
    nodes,
    edges: [...edges.values()],
    omitted: graph.nodes.length - nodes.filter((n) => !n.plate).length,
  };
}
export const scopeSelector = (
  block: string | null,
  targets: TargetRef[],
  mode: "selection" | "block" | "project",
): ScopeSelector => ({
  mode,
  block_id: mode === "block" ? block : null,
  targets: mode === "selection" ? targets : [],
  excluded_keys: [],
});

export function initialCollapsed(graph: SemanticGraph, closed: Set<string>) {
  const result = new Set(closed);
  if (graph.nodes.length <= 350) return result;
  const functions = graph.blocks.filter((b) => b.kind === "function");
  const counts = new Map<string, number>();
  for (const n of graph.nodes)
    counts.set(n.block_id, (counts.get(n.block_id) ?? 0) + 1);
  for (const b of graph.blocks)
    if (
      (b.kind === "function" ||
        (b.kind === "file" && (counts.get(b.id) ?? 0) > 350) ||
        (!functions.length && !b.parent_id)) &&
      !closed.has("open:" + b.id)
    )
      result.add(b.id);
  return result;
}

export function selectionBlocks(
  blocks: Pick<GraphBlock, "id" | "parent_id">[],
  targets: TargetRef[],
) {
  const parents = new Map(blocks.map((b) => [b.id, b.parent_id]));
  const partial = new Set<string>(),
    covered = new Set<string>();
  const roots = new Set(
    targets
      .filter((t) => ["function", "file", "control"].includes(t.kind))
      .flatMap((t) => (t.block_id ? [t.block_id] : [])),
  );
  for (const t of targets) {
    let id: string | undefined = t.block_id ?? undefined;
    const seen = new Set<string>();
    while (id && !seen.has(id)) {
      seen.add(id);
      partial.add(id);
      id = parents.get(id) ?? undefined;
    }
  }
  for (const b of blocks) {
    let id: string | undefined = b.id;
    const seen = new Set<string>();
    while (id && !seen.has(id)) {
      if (roots.has(id)) {
        covered.add(b.id);
        break;
      }
      seen.add(id);
      id = parents.get(id) ?? undefined;
    }
  }
  return { partial, covered };
}
