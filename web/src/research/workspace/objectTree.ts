import type { SnapshotRef } from "../generated";
import type { AnalysisDocument, GraphBlock, ProbeDefinition, ProbeInstance, ProbeOutput, SourceObject, TargetRef } from "./generated";
import { targetProbeEntries } from "./probe-configuration";
import { selectionKey, type ObjectRow } from "./selection";
import type { OccurrenceGroup } from "./sourceOccurrences";

export interface LogicalObjectGroup {
  id: string;
  logicalKey: string;
  logicalKeys: string[];
  objectIds: string[];
  objects: SourceObject[];
  name: string;
  scope: string;
}

export interface BrowserRow extends ObjectRow {
  rowKind: "folder" | "file" | "function" | "class" | "variable" | "assignment" | "evidence" | "control";
  selectable: boolean;
  group?: LogicalObjectGroup;
  historyGroupId?: string;
  objectIds?: string[];
  logicalKeys?: string[];
  source?: SourceObject;
  matchesFilter?: boolean;
  typeLabel: string;
  shapeLabel: string;
  probeCount: number;
}

const lexicalKinds = new Set(["file", "function", "class", "folder", "project"]);
const sourceOrder = (a: SourceObject, b: SourceObject) => a.line - b.line || a.column - b.column;
const pathName = (path: string) => path.replaceAll("\\", "/").replace(/\/$/, "").split("/").at(-1) || path;
function folderPath(analysis: AnalysisDocument) {
  const path = analysis.path.replaceAll("\\", "/");
  return path.slice(0, Math.max(0, path.lastIndexOf("/"))) || ".";
}
const folderId = (analysis: AnalysisDocument) => "folder:" + folderPath(analysis);

function blockIndex(analysis: AnalysisDocument) {
  return new Map(analysis.graph.blocks.map(block => [block.id, block]));
}
function lexicalBlock(id: string, blocks: Map<string, GraphBlock>): string {
  const seen = new Set<string>();
  while (id && !seen.has(id)) {
    seen.add(id);
    const block = blocks.get(id);
    if (!block || lexicalKinds.has(block.kind)) return id;
    id = block.parent_id ?? "";
  }
  return id;
}

export function logicalObjectGroups(analysis: AnalysisDocument, occurrences: OccurrenceGroup[] = []): LogicalObjectGroup[] {
  const ownership = new Map(occurrences.flatMap(group => group.object_ids.map(id => [id, group] as const)));
  const blocks = blockIndex(analysis), containers = new Map<string, Set<string>>();
  const objects = [...analysis.objects].sort(sourceOrder);
  const knownKeys = new Set(objects.map(object => object.logical_key));
  for (const node of analysis.graph.nodes)
    if (["data", "parameter"].includes(node.kind) && node.logical_key && !knownKeys.has(node.logical_key)) {
      knownKeys.add(node.logical_key);
      objects.push({ id: node.source_object_id ?? node.id, path: node.source?.path ?? analysis.path, name: node.label,
        scope: node.source?.qualname || "<module>", qualname: node.source?.qualname ? `${node.source.qualname}.${node.label}` : node.label,
        logical_key: node.logical_key, kind: "parameter", block_id: node.block_id,
        line: node.source?.line ?? 1, end_line: node.source?.end_line ?? 1, column: node.source?.column ?? 0,
        end_column: node.source?.end_column ?? 0, source_digest: analysis.source_digest, code: node.source?.code ?? "",
        inputs: [], mutation: false, provenance: "inferred" });
    }
  objects.sort(sourceOrder);
  for (const object of objects) {
    const key = object.logical_key || `${object.path}::${object.scope}::${object.name}`;
    const set = containers.get(key) ?? new Set();
    set.add(lexicalBlock(object.block_id, blocks));
    containers.set(key, set);
  }
  const result = new Map<string, LogicalObjectGroup>();
  for (const object of objects) {
    const occurrence = ownership.get(object.id);
    const key = object.logical_key || `${object.path}::${object.scope}::${object.name}`;
    const identity = occurrence?.logical_key ?? (containers.get(key)!.size > 1 && !["function", "class"].includes(object.kind)
      ? `${key}@scope:${lexicalBlock(object.block_id, blocks)}` : key);
    let group = result.get(identity);
    if (!group) {
      group = { id: "data:" + identity, logicalKey: identity, logicalKeys: [...(occurrence?.logical_keys ?? [key])],
        objectIds: [], objects: [], name: object.name, scope: occurrence?.scope ?? object.scope };
      result.set(identity, group);
    }
    group.objectIds.push(object.id);
    group.objects.push(object);
    if (!group.logicalKeys.includes(key)) group.logicalKeys.push(key);
  }
  return [...result.values()];
}

export function logicalObjectGroup(analysis: AnalysisDocument, objectId?: string | null, logicalKey?: string, occurrences: OccurrenceGroup[] = []) {
  const groups = logicalObjectGroups(analysis, occurrences);
  return groups.find(group => objectId && group.objectIds.includes(objectId)) ??
    groups.find(group => logicalKey && group.logicalKeys.includes(logicalKey));
}

export function selectionObjectIds(analysis: AnalysisDocument | undefined, targets: TargetRef[], occurrences: OccurrenceGroup[] = []): Set<string> {
  const result = new Set<string>();
  if (!analysis) return result;
  const groups = logicalObjectGroups(analysis, occurrences);
  for (const target of targets) {
    if (target.exact_evidence) {
      if (target.object_id) result.add(target.object_id);
      continue;
    }
    const byId = target.object_id ? groups.find(group => group.objectIds.includes(target.object_id!)) : undefined;
    for (const group of byId ? [byId] : groups.filter(group => group.logicalKeys.includes(target.logical_key)))
      group.objectIds.forEach(id => result.add(id));
  }
  return result;
}

export function latestObservedSnapshot(values: SnapshotRef[]): SnapshotRef | undefined {
  return [...values].sort((a, b) => (Date.parse(b.observed_at) || 0) - (Date.parse(a.observed_at) || 0)
    || (a.binding_id === b.binding_id ? b.version - a.version : 0))[0];
}

function groupSnapshots(group: LogicalObjectGroup, values: SnapshotRef[], analysis: AnalysisDocument, ambiguousKeys: Set<string>) {
  const ambiguous = group.logicalKeys.some(key => ambiguousKeys.has(key));
  return values.filter(value => group.logicalKeys.includes(value.logical_key || value.binding_id)
    && (!value.source?.digest || value.source.digest === analysis.source_digest)
    && (!ambiguous || value.source && group.objects.some(object => object.line <= value.source!.line && value.source!.line <= object.end_line)));
}

function origin(group: LogicalObjectGroup, snapshot?: SnapshotRef) {
  return snapshot?.source ? group.objects.find(object => object.line === snapshot.source!.line && object.column === snapshot.source!.column)
    ?? group.objects.find(object => object.line === snapshot.source!.line) ?? group.objects[0] : group.objects[0];
}

function typeLabel(snapshot?: SnapshotRef) {
  if (!snapshot) return "—";
  return snapshot.descriptor.dtype ?? snapshot.descriptor.kind ?? "—";
}
function shapeLabel(snapshot?: SnapshotRef) {
  const shape = snapshot?.descriptor.shape;
  return shape?.length ? shape.join(" × ") : "—";
}

function valueDetail(type: string, shape: string, count: number) {
  return [type, shape, count ? `${count} 探针` : "0 探针"].join(" · ");
}

function targetFor(analysis: AnalysisDocument, source: SourceObject, snapshot?: SnapshotRef, exact = false, objectIds?: Set<string>): TargetRef {
  const ref = snapshot?.source ?? analysis.graph.blocks.find((block) => block.id === source.block_id)?.source ?? null;
  return { kind: ["function", "class"].includes(source.kind) ? "function" : "data", logical_key: snapshot?.logical_key || source.logical_key,
    object_id: (objectIds ? objectIds.has(source.id) : analysis.objects.some(object => object.id === source.id)) ? source.id : null,
    block_id: source.block_id, analysis_id: analysis.id, run_id: snapshot?.run_id ?? null,
    snapshot_id: snapshot?.id ?? null,
    project_id: ref?.project_id || null, file_id: ref?.file_id || null, project_revision_id: ref?.project_revision_id || null,
    exact_evidence: exact };
}

export function initialObjectExpansion(analysis: AnalysisDocument | undefined, scope: string | null): Set<string> {
  if (!analysis) return new Set();
  if (scope) return new Set([scope]);
  const roots = analysis.graph.blocks.filter(block => !block.parent_id);
  return new Set(roots.length === 1 && roots[0].kind === "file" ? [folderId(analysis)] : roots.map(block => block.id));
}

export interface ObjectTreeOptions {
  status?: string;
  probe?: string;
  outputs?: ProbeOutput[];
  occurrences?: OccurrenceGroup[];
  probes?: ProbeInstance[];
  definitions?: ProbeDefinition[];
}

function matchedOutputs(outputs: ProbeOutput[], analysis: AnalysisDocument, row: BrowserRow) {
  return outputs.filter(output => {
    if (output.analysis_id && output.analysis_id !== analysis.id) return false;
    return output.targets.some(target =>
      (row.logicalKeys ?? [row.target.logical_key]).includes(target.logical_key)
      && (!target.object_id || (row.objectIds ?? []).includes(target.object_id))
      && (!target.analysis_id || target.analysis_id === analysis.id));
  });
}

function probeOutcome(outputs: ProbeOutput[], analysis: AnalysisDocument, row: BrowserRow, enabled?: Set<string>): "normal" | "failed" | "unknown" {
  const matched = matchedOutputs(outputs, analysis, row).filter(output => !enabled || enabled.has(output.instance_id));
  if (!matched.length) return "unknown";
  const latest = new Map<string, ProbeOutput>();
  for (const output of matched) {
    const current = latest.get(output.instance_id);
    if (!current || (Date.parse(output.created_at) || 0) >= (Date.parse(current.created_at) || 0)) latest.set(output.instance_id, output);
  }
  const statuses = [...latest.values()].map(output => output.status);
  if (statuses.some(status => status === "fail" || status === "error")) return "failed";
  return statuses.every(status => status === "pass" || status === "ready") ? "normal" : "unknown";
}

export function buildObjectTree(
  analysis: AnalysisDocument | undefined,
  values: SnapshotRef[],
  scope: string | null,
  expanded: Set<string>,
  query = "",
  type = "all",
  histories: Map<string, SnapshotRef[]> = new Map(),
  options: ObjectTreeOptions = {},
): BrowserRow[] {
  if (!analysis) return [];
  const blocks = blockIndex(analysis), groups = logicalObjectGroups(analysis, options.occurrences);
  const probes = options.probes ?? [], definitions = options.definitions ?? [], outputs = options.outputs ?? [];
  const snapshotIds = new Set(values.map(value => value.id)), outputIndex = new Map<string, ProbeOutput[]>();
  for (const output of outputs) {
    if (output.snapshot_id && !snapshotIds.has(output.snapshot_id)) continue;
    if (output.analysis_id && output.analysis_id !== analysis.id) continue;
    for (const key of new Set(output.targets.map(target => target.logical_key))) {
      const matches = outputIndex.get(key) ?? []; matches.push(output); outputIndex.set(key, matches);
    }
  }
  const boundInstances = new Map<string, Set<string>>();
  const objectIds = new Set(analysis.objects.map(object => object.id)), valuesByKey = new Map<string, SnapshotRef[]>();
  for (const value of values) {
    const key = value.logical_key || value.binding_id;
    const list = valuesByKey.get(key) ?? [];
    list.push(value);
    valuesByKey.set(key, list);
  }
  const keyCounts = new Map<string, number>();
  groups.forEach(group => group.logicalKeys.forEach(key => keyCounts.set(key, (keyCounts.get(key) ?? 0) + 1)));
  const ambiguousKeys = new Set([...keyCounts].filter(([, count]) => count > 1).map(([key]) => key));
  function inside(id: string, ancestor: string) {
    const seen = new Set<string>();
    while (id && !seen.has(id)) {
      if (id === ancestor) return true;
      seen.add(id);
      id = blocks.get(id)?.parent_id ?? "";
    }
    return false;
  }
  const children = new Map<string, BrowserRow[]>(), roots: BrowserRow[] = [];
  const append = (row: BrowserRow, parent?: string) => {
    if (row.selectable) {
      const enabled = new Set(targetProbeEntries(probes, definitions, row.target, analysis).filter(entry => entry.enabled).map(entry => entry.probe.id));
      boundInstances.set(row.id, enabled); row.probeCount = enabled.size;
      if (row.rowKind === "variable") row.detail = valueDetail(row.typeLabel, row.shapeLabel, row.probeCount);
    }
    row.parent = parent;
    if (parent) {
      const list = children.get(parent) ?? [];
      list.push(row);
      children.set(parent, list);
    }
    else roots.push(row);
  };
  const retained = analysis.graph.blocks.filter(block => (lexicalKinds.has(block.kind) || block.id === scope)
    && (!scope || inside(block.id, scope)));
  const retainedIds = new Set(retained.map(block => block.id));
  const rootBlocks = retained.filter(block => !block.parent_id || block.id === scope);
  const syntheticFolder = !scope && rootBlocks.length === 1 && rootBlocks[0].kind === "file";
  if (syntheticFolder) append({ id: folderId(analysis), depth: 0, label: pathName(folderPath(analysis)), detail: "文件夹",
    rowKind: "folder", selectable: false, expandable: true, typeLabel: "文件夹", shapeLabel: "—", probeCount: 0,
    target: { kind: "folder", logical_key: folderPath(analysis), object_id: null, block_id: null, analysis_id: analysis.id, run_id: null, snapshot_id: null,
      project_id: null, file_id: null, project_revision_id: null, exact_evidence: false } });
  for (const block of retained) {
    let parent = block.id === scope ? undefined : lexicalBlock(block.parent_id ?? "", blocks) || undefined;
    if (parent && !retainedIds.has(parent)) parent = scope ?? undefined;
    if (!parent && syntheticFolder) parent = folderId(analysis);
    const source = analysis.objects.find(object => object.id === block.source_object_id);
    const kind = block.kind === "file" ? "file" : ["function", "class"].includes(block.kind) ? "function" : block.kind === "project" ? "project" : block.kind === "folder" ? "folder" : "control";
    const label = block.kind === "file" ? "文件" : block.kind === "function" ? "函数" : block.kind === "class" ? "类" : "代码块";
    append({ id: block.id, depth: 0, label: block.kind === "file" ? pathName(block.source?.path ?? analysis.path) : block.label,
      detail: label,
      rowKind: block.kind === "file" ? "file" : block.kind === "function" ? "function" : block.kind === "class" ? "class" : "control",
      selectable: true, expandable: true, block, source, objectId: source?.id,
      objectIds: source ? [source.id] : [], logicalKeys: [block.logical_key], typeLabel: label, shapeLabel: "—", probeCount: 0,
      target: { kind, logical_key: block.logical_key, object_id: block.source_object_id, block_id: block.id, analysis_id: analysis.id,
        run_id: null, snapshot_id: null,
        project_id: block.source?.project_id || null, file_id: block.source?.file_id || null, project_revision_id: block.source?.project_revision_id || null,
        exact_evidence: false } }, parent);
  }
  for (const group of groups) {
    if (group.objects.every(object => ["function", "class", "step"].includes(object.kind))) continue;
    if (scope && !group.objects.some(object => inside(object.block_id, scope))) continue;
    const candidates = [...group.logicalKeys.flatMap(key => valuesByKey.get(key) ?? []), ...(histories.get(group.id) ?? [])];
    const snapshots = groupSnapshots(group, candidates, analysis, ambiguousKeys);
    const snapshot = latestObservedSnapshot(snapshots), source = origin(group, snapshot);
    let parent = group.scope === "<module>" ? retained.find(block => block.kind === "file")?.id : lexicalBlock(group.objects[0].block_id, blocks);
    if (options.occurrences?.length && group.scope !== group.objects[0].scope) {
      const owner = retained.find(block => ["function", "class"].includes(block.kind) && block.source?.qualname === group.scope);
      if (owner) parent = owner.id;
    }
    if (!parent || !retainedIds.has(parent)) parent = scope ?? retained.find(block => block.kind === "file")?.id;
    const target = targetFor(analysis, source, snapshot, false, objectIds);
    const row: BrowserRow = { id: group.id, depth: 0, label: group.name,
      detail: "",
      target, objectId: source.id, objectIds: group.objectIds,
      logicalKeys: group.logicalKeys, rowKind: "variable", selectable: true, expandable: false, group, source, snapshot,
      typeLabel: typeLabel(snapshot), shapeLabel: shapeLabel(snapshot), probeCount: 0 };
    append(row, parent);
  }
  const known = new Set(groups.flatMap(group => group.logicalKeys));
  if (!scope) {
    const extra = new Map<string, SnapshotRef[]>();
    for (const snapshot of values.filter(value => !known.has(value.logical_key))) {
      const key = snapshot.logical_key || snapshot.binding_id;
      extra.set(key, [...(extra.get(key) ?? []), snapshot]);
    }
    for (const [key, snapshots] of extra) {
      const snapshot = latestObservedSnapshot(snapshots)!;
      append({ id: "runtime:" + key, depth: 0, label: snapshot.name,
        detail: valueDetail(typeLabel(snapshot), shapeLabel(snapshot), 0), snapshot, rowKind: "variable", selectable: true, expandable: false,
        typeLabel: typeLabel(snapshot), shapeLabel: shapeLabel(snapshot), probeCount: 0, logicalKeys: [key], objectIds: [],
        target: { kind: "data", logical_key: key, snapshot_id: snapshot.id, run_id: snapshot.run_id,
          object_id: null, block_id: null, analysis_id: analysis.id,
          project_id: snapshot.source?.project_id || null, file_id: snapshot.source?.file_id || null, project_revision_id: snapshot.source?.project_revision_id || null,
          exact_evidence: false } }, retained.find(block => block.kind === "file")?.id);
    }
  }
  const q = query.trim().toLowerCase();
  const typeMode = type === "variables" ? "variables" : "all";
  const probeFilter = options.probe && options.probe !== "all" ? options.probe : "all";
  const filtered = Boolean(q || typeMode !== "all" || probeFilter !== "all");
  const revealMatches = Boolean(q || probeFilter !== "all");
  const containerKinds = new Set(["folder", "file", "function", "class", "control"]);
  const matches = (row: BrowserRow) => {
    if (row.rowKind !== "variable") {
      if (containerKinds.has(row.rowKind) && typeMode === "all" && probeFilter === "all"
        && (!q || (row.label + " " + row.detail + " " + (row.group?.scope ?? "")).toLowerCase().includes(q))) return true;
      return false;
    }
    const group = row.group;
    const isImported = group ? group.objects.some(object => ["import", "step"].includes(object.kind)) : false;
    if (typeMode === "variables" && isImported) return false;
    if (q && !(row.label + " " + row.detail + " " + (group?.scope ?? "")).toLowerCase().includes(q)) return false;
    if (probeFilter !== "all") {
      const candidateOutputs = [...new Map((row.logicalKeys ?? [row.target.logical_key]).flatMap(key => outputIndex.get(key) ?? []).map(output => [output.id, output])).values()];
      if (probeOutcome(candidateOutputs, analysis, row, options.probes ? boundInstances.get(row.id) : undefined) !== probeFilter) return false;
    }
    return true;
  };
  const memo = new Map<string, boolean>();
  const subtreeMatches = (row: BrowserRow): boolean => {
    if (memo.has(row.id)) return memo.get(row.id)!;
    const pass = matches(row) || (children.get(row.id) ?? []).some(child => subtreeMatches(child));
    memo.set(row.id, pass);
    return pass;
  };
  const rows: BrowserRow[] = [];
  const visit = (row: BrowserRow, depth: number) => {
    if (filtered && !subtreeMatches(row)) return;
    rows.push({ ...row, depth, matchesFilter: matches(row) });
    const autoExpand = revealMatches && row.rowKind !== "variable";
    if (!expanded.has(row.id) && !autoExpand) return;
    const position = (item: BrowserRow) => item.rowKind === "variable" ? item.group?.objects[0] : item.source;
    const ordered = [...(children.get(row.id) ?? [])].sort((a, b) =>
      (position(a)?.line ?? a.block?.source?.line ?? Number.MAX_SAFE_INTEGER) - (position(b)?.line ?? b.block?.source?.line ?? Number.MAX_SAFE_INTEGER)
      || (position(a)?.column ?? a.block?.source?.column ?? 0) - (position(b)?.column ?? b.block?.source?.column ?? 0));
    for (const child of ordered) visit(child, depth + 1);
  };
  roots.forEach(root => visit(root, 0));
  return rows;
}

export const selectableObjectOrder = (rows: BrowserRow[]) => rows.filter(row => row.selectable).map(row => row.target);
export const logicalSelectionCount = (targets: TargetRef[]) => new Set(targets.map(selectionKey)).size;
