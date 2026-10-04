import type { SourceRef } from "../generated";
import type { TargetRef } from "./generated";

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
  return first ? { path, digest, qualname: groups[0]?.name ?? "", ...first, code: "" } : null;
}
