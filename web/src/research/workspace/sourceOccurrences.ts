import type { SourceRef } from "../generated";
import type { TargetRef, AnalysisDocument } from "./generated";

/** Block/operation selection has a source range even without a variable token. */
export function selectedStructureSources(analysis: AnalysisDocument | undefined, targets: TargetRef[], path: string, digest: string): SourceRef[] {
  if (!analysis || analysis.source_digest !== digest || analysis.path !== path) return [];
  return targets.filter(t => t.kind !== "data" && (!t.analysis_id || t.analysis_id === analysis.id)).flatMap(t => {
    const item = t.kind === "operation" ? analysis.graph.nodes.find(n => Boolean(t.logical_key && n.logical_key === t.logical_key || t.object_id && (n.id === t.object_id || n.source_object_id === t.object_id)))
      : analysis.graph.blocks.find(b => Boolean(t.block_id && b.id === t.block_id || t.object_id && b.source_object_id === t.object_id || t.logical_key && b.logical_key === t.logical_key));
    if (item?.source) return [item.source];
    const object = analysis.objects.find(o => o.id === t.object_id);
    return object ? [{ path: object.path, digest: object.source_digest, qualname: object.qualname, line: object.line, end_line: object.end_line,
      column: object.column, end_column: object.end_column, code: object.code,
      project_id: t.project_id ?? "", file_id: t.file_id ?? "", project_revision_id: t.project_revision_id ?? "", scope_id: "" }] : [];
  });
}

export interface SourceOccurrence {
  line: number;
  end_line: number;
  column: number;
  end_column: number;
  role: "definition" | "use";
}

export interface OccurrenceGroup {
  logical_key: string;
  logical_keys: string[];
  object_ids: string[];
  name: string;
  scope: string;
  occurrences: SourceOccurrence[];
}

export function selectedOccurrenceGroups(
  groups: OccurrenceGroup[],
  targets: TargetRef[],
): OccurrenceGroup[] {
  const result = new Set<OccurrenceGroup>();
  for (const target of targets) {
    if (target.exact_evidence || target.kind !== "data") continue;
    // Original IDs disambiguate old analyses that reused a qualified name for
    // separate definitions of the same function.
    const byId = target.object_id
      ? groups.filter(group => group.object_ids.includes(target.object_id!))
      : [];
    for (const group of byId.length ? byId : groups.filter(group => group.logical_keys.includes(target.logical_key)))
      result.add(group);
  }
  return [...result];
}

export interface SourcePart {
  text: string;
  role?: SourceOccurrence["role"];
}

export function sourceLineParts(text: string, line: number, occurrences: SourceOccurrence[]): SourcePart[] {
  const spans = occurrences.filter(span => span.line <= line && line <= span.end_line)
    .map(span => ({ start: span.line === line ? span.column : 0,
      end: span.end_line === line ? span.end_column : text.length, role: span.role }))
    .filter(span => span.start < span.end)
    .sort((a, b) => a.start - b.start || a.end - b.end);
  if (!spans.length) return [{ text: text || " " }];
  const result: SourcePart[] = [];
  let offset = 0;
  for (const span of spans) {
    const start = Math.max(offset, span.start), end = Math.min(text.length, span.end);
    if (end <= start) continue;
    if (start > offset) result.push({ text: text.slice(offset, start) });
    result.push({ text: text.slice(start, end), role: span.role });
    offset = end;
  }
  if (offset < text.length) result.push({ text: text.slice(offset) });
  return result;
}

export function sourceFocus(
  selection: SourceRef | null | undefined,
  groups: OccurrenceGroup[],
  path: string,
  digest: string,
): SourceRef | null {
  if (selection?.digest === digest) return selection;
  const first = groups.flatMap(group => group.occurrences).sort((a, b) => a.line - b.line || a.column - b.column)[0];
  return first ? { path, digest, qualname: groups[0]?.name ?? "", ...first, code: "",
    project_id: "", file_id: "", project_revision_id: "", scope_id: "" } : null;
}
