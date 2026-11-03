import { describe, expect, it } from "vitest";
import { sourceLineParts, selectedOccurrenceGroups, selectedStructureSources, type OccurrenceGroup } from "../src/research/workspace/sourceOccurrences";
import type { TargetRef, AnalysisDocument } from "../src/research/workspace/generated";

describe("lexical source display", () => {
  it("maps control blocks and computations to archived source even without object IDs", () => {
    const source = { path: "x.py", digest: "v1", line: 3, end_line: 8, column: 0, end_column: 1, qualname: "main", code: "if x:" };
    const analysis = { id: "a", path: "x.py", source_digest: "v1", objects: [], graph: { blocks: [{ id: "if", logical_key: "block", source }], nodes: [{ id: "calc", logical_key: "calc", source: { ...source, line: 4, end_line: 4 } }] } } as unknown as AnalysisDocument;
    expect(selectedStructureSources(analysis, [{ kind: "control", block_id: "if" } as TargetRef], "x.py", "v1")).toEqual([source]);
    expect(selectedStructureSources(analysis, [{ kind: "operation", logical_key: "calc" } as TargetRef], "x.py", "v1")[0].line).toBe(4);
    expect(selectedStructureSources(analysis, [{ kind: "control", block_id: "if" } as TargetRef], "x.py", "old")).toEqual([]);
  });
  it("highlights token spans with UTF-16 offsets while preserving all source text", () => {
    expect(sourceLineParts('"😀"; 值 = 1; print(值)', 1, [
      { line: 1, end_line: 1, column: 6, end_column: 7, role: "definition" },
      { line: 1, end_line: 1, column: 19, end_column: 20, role: "use" },
    ])).toEqual([{ text: '"😀"; ' }, { text: "值", role: "definition" }, { text: " = 1; print(" }, { text: "值", role: "use" }, { text: ")" }]);
  });

  it("uses object identity to separate redefined function bodies sharing old keys", () => {
    const first: OccurrenceGroup = { logical_key: "f@1::x", logical_keys: ["f::x"], object_ids: ["first"], scope: "f@1", name: "x", occurrences: [] };
    const second: OccurrenceGroup = { ...first, logical_key: "f@5::x", object_ids: ["second"], scope: "f@5" };
    const target = { kind: "data", logical_key: "f::x", object_id: "second" } as TargetRef;
    expect(selectedOccurrenceGroups([first, second], [target])).toEqual([second]);
    expect(selectedOccurrenceGroups([first, second], [{ ...target, exact_evidence: true }])).toEqual([]);
  });
});
