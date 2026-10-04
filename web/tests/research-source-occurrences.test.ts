import { describe, expect, it } from "vitest";
import { sourceLineParts, selectedOccurrenceGroups, type OccurrenceGroup } from "../src/research/workspace/sourceOccurrences";
import type { TargetRef } from "../src/research/workspace/generated";

describe("lexical source display", () => {
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
