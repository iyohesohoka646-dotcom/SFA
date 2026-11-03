import { describe, expect, it } from "vitest";
import type { AnalysisDocument, GraphBlock, SourceObject } from "../src/research/workspace/generated";
import type { SnapshotRef } from "../src/research/generated";
import { buildObjectTree, initialObjectExpansion, selectionObjectIds, selectableObjectOrder } from "../src/research/workspace/objectTree";

const path = "D:\\lab\\analysis.py";
const key = (scope: string, name: string) => `${path}::${scope}::${name}`;
function object(id: string, name: string, line: number, scope = "<module>", block_id = "file", kind: SourceObject["kind"] = "assignment"): SourceObject {
  return { id, name, line, scope, block_id, kind, path, qualname: scope === "<module>" ? name : `${scope}.${name}`,
    logical_key: key(scope, name), end_line: line, column: 0, end_column: 8, source_digest: "digest", code: `${name} = 1`, inputs: [], mutation: false, provenance: "inferred" };
}
function block(id: string, kind: GraphBlock["kind"], label: string, line: number, parent_id: string | null = null, scope = "<module>", source_object_id: string | null = null): GraphBlock {
  return { id, kind, label, parent_id, source_object_id, logical_key: key(scope, label), members: [], runtime_coverage: "supported",
    source: { path, digest: "digest", qualname: scope, line, end_line: line + 10, column: 0, end_column: 0, code: "" } };
}
function analysis(objects: SourceObject[], blocks: GraphBlock[]): AnalysisDocument {
  return { id: "analysis", path, source_digest: "digest", protocol_version: 3, objects, relations: [], diagnostics: [], imported_at: "",
    graph: { protocol_version: 3, source_digest: "digest", roots: ["file"], blocks, nodes: [], edges: [], coverage: [], omitted_count: 0 } };
}
function snapshot(id: string, version: number, line: number, observed_at: string): SnapshotRef {
  return { id, run_id: "run", binding_id: "main:x", scope_id: "main", name: "x", logical_key: key("<module>", "x"), version, observed_at,
    source: { path, digest: "digest", qualname: "", line, end_line: line, column: 0, end_column: 5, code: "x = 1" },
    descriptor: { schema_version: 1, kind: "scalar", backend: "python", type_name: "int", shape: null, dtype: null, nbytes: null, device: null, axes: [], unit: null, capabilities: [], metadata: {} },
    operation_id: null, parents: [], provenance: "observed", fidelity: "full", sample: { values: [[version]] }, statistics: {}, truncation: {}, redacted: false, artifact_ref: null, coverage: {} } as SnapshotRef;
}

describe("source-ordered object explorer", () => {
  it("shows a folder, its file and objects in source order without control plates", () => {
    const doc = analysis([
      object("first", "first", 1), object("fn-object", "calculate", 3, "<module>", "fn", "function"),
      object("inside", "inside", 4, "calculate", "fn"), object("last", "last", 8, "<module>", "condition"),
    ], [block("file", "file", "analysis.py", 1), block("fn", "function", "calculate", 3, "file", "calculate", "fn-object"), block("condition", "condition", "if flag", 7, "file")]);
    const rows = buildObjectTree(doc, [], null, new Set(["folder:D:/lab", "file"]));
    expect(rows.map(row => [row.label, row.depth])).toEqual([["lab", 0], ["analysis.py", 1], ["first", 2], ["calculate", 2], ["last", 2]]);
  });

  it("groups repeated assignments across condition blocks while preserving shadowed scopes", () => {
    const doc = analysis([object("outer-a", "x", 1), object("outer-b", "x", 3, "<module>", "condition"),
      object("fn-object", "f", 5, "<module>", "fn", "function"), object("inner-a", "x", 6, "f", "fn"), object("inner-b", "x", 8, "f", "inner-condition")],
      [block("file", "file", "analysis.py", 1), block("condition", "condition", "if flag", 2, "file"), block("fn", "function", "f", 5, "file", "f", "fn-object"), block("inner-condition", "condition", "if flag", 7, "fn", "f")]);
    const rows = buildObjectTree(doc, [], "fn", new Set(["fn"]));
    expect(rows.filter(row => row.label === "x")).toHaveLength(1);
    expect(rows.find(row => row.label === "x")?.target.logical_key).toBe(key("f", "x"));
  });

  it("uses the newest observed value instead of array order or a later unexecuted assignment", () => {
    const doc = analysis([object("a", "x", 1), object("b", "x", 3), object("unexecuted", "x", 9)], [block("file", "file", "analysis.py", 1)]);
    const values = [snapshot("latest", 4, 3, "2026-10-04T02:00:00Z"), snapshot("old", 2, 1, "2026-10-04T01:00:00Z")];
    const rows = buildObjectTree(doc, values, null, new Set(["folder:D:/lab", "file"]));
    const row = rows.find(row => row.label === "x");
    expect(row?.snapshot?.id).toBe("latest");
    expect(row?.objectId).toBe("b");
    expect(row?.snapshot?.version).toBe(4);
    expect(row?.objectIds).toHaveLength(3);
    expect(row?.detail).not.toMatch(/观测|定义/);
  });

  it("keeps a logical variable at its first definition when later observations arrive", () => {
    const doc = analysis([object("x-first", "x", 1), object("y", "y", 2), object("x-last", "x", 9)], [block("file", "file", "analysis.py", 1)]);
    const rows = buildObjectTree(doc, [snapshot("last", 3, 9, "2026-10-04T02:00:00Z")], null, new Set(["folder:D:/lab", "file"]));
    expect(rows.filter(row => row.rowKind === "variable").map(row => row.label)).toEqual(["x", "y"]);
  });

  it("starts every descendant collapsed and starts a newly focused block with only its root open", () => {
    const doc = analysis([object("fn-object", "f", 2, "<module>", "fn", "function"), object("x", "x", 3, "f", "fn")],
      [block("file", "file", "analysis.py", 1), block("fn", "function", "f", 2, "file", "f", "fn-object")]);
    const rootRows = buildObjectTree(doc, [], null, initialObjectExpansion(doc, null));
    expect(rootRows.map(row => row.label)).toEqual(["lab", "analysis.py"]);
    const focusedRows = buildObjectTree(doc, [], "fn", initialObjectExpansion(doc, "fn"));
    expect(focusedRows.map(row => row.label)).toEqual(["f", "x"]);
    expect(initialObjectExpansion(doc, "fn").has("data:" + key("f", "x"))).toBe(false);
  });

  it("lets search reveal a closed file and function without expanding assignment history", () => {
    const doc = analysis([object("fn-object", "f", 2, "<module>", "fn", "function"), object("x", "needle", 3, "f", "fn")],
      [block("file", "file", "analysis.py", 1), block("fn", "function", "f", 2, "file", "f", "fn-object")]);
    expect(buildObjectTree(doc, [], null, initialObjectExpansion(doc, null), "needle").map(row => row.label)).toEqual(["lab", "analysis.py", "f", "needle"]);
  });

  it("keeps one selectable variable while older observations remain available to the data history", () => {
    const doc = analysis([object("x-a", "x", 1), object("x-b", "x", 3)], [block("file", "file", "analysis.py", 1)]);
    const history = [snapshot("a1", 1, 1, "2026-10-04T00:01:00Z"), snapshot("b2", 2, 3, "2026-10-04T00:02:00Z"), snapshot("b3", 3, 3, "2026-10-04T00:03:00Z")];
    const expanded = new Set(["folder:D:/lab", "file", "data:" + key("<module>", "x"), "assignment:x-b"]);
    const rows = buildObjectTree(doc, [history[2]], null, expanded, "", "all", new Map([["data:" + key("<module>", "x"), history]]));
    expect(rows.filter(row => ["assignment", "evidence"].includes(row.rowKind))).toEqual([]);
    expect(rows.find(row => row.label === "x")?.snapshot?.id).toBe("b3");
    expect(rows.find(row => row.label === "x")?.expandable).toBe(false);
    expect(selectableObjectOrder(rows).map(target => target.object_id)).toEqual([null, "x-b"]);
  });

  it("highlights every same-scope assignment without selecting a shadowed function variable", () => {
    const doc = analysis([object("outer-a", "x", 1), object("outer-b", "x", 3), object("inner", "x", 6, "f", "fn")],
      [block("file", "file", "analysis.py", 1), block("fn", "function", "f", 5, "file", "f")]);
    const rows = buildObjectTree(doc, [], null, new Set(["folder:D:/lab", "file"]));
    const target = rows.find(row => row.label === "x")!.target;
    expect([...selectionObjectIds(doc, [target])]).toEqual(["outer-a", "outer-b"]);
    expect([...selectionObjectIds(doc, [{ ...target, exact_evidence: true, object_id: "outer-a" }])]).toEqual(["outer-a"]);
  });
});
