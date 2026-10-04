import { describe, expect, it } from "vitest";
import { buildObjectTree } from "../src/research/workspace/objectTree";
import type { AnalysisDocument, ProbeInstance, ProbeOutput, SourceObject } from "../src/research/workspace/generated";

const object = (id: string, name: string, line: number, kind = "assignment"): SourceObject => ({
  id, name, path: "analysis.py", logical_key: `analysis.py::<module>::${name}`, scope: "<module>", qualname: name,
  block_id: "file", kind, line, end_line: line, column: 0, end_column: 5, source_digest: "digest", code: `${name} = 1`,
  inputs: [], mutation: false, provenance: "inferred",
} as SourceObject);
const doc = (): AnalysisDocument => ({ id: "analysis", path: "analysis.py", source_digest: "digest", protocol_version: 3,
  imported_at: "", diagnostics: [], relations: [], objects: [object("import", "np", 1, "import"), object("x1", "X", 2), object("x2", "X", 5), object("y", "Y", 6)],
  graph: { protocol_version: 3, source_digest: "digest", roots: ["file"], blocks: [{ id: "file", parent_id: null,
    kind: "file", label: "analysis.py", logical_key: "file", members: [], source: null, source_object_id: null, runtime_coverage: "supported" }], nodes: [], edges: [], coverage: [], omitted_count: 0 },
});
const probe = (id: string, logicalKey?: string): ProbeInstance => ({ id, definition_id: "view.auto", binding: "*", enabled: true,
  parameters: {}, policy: "continue", budget_ms: 5000, inputs: {}, origin: "local", overrides: {}, selector: {
    mode: logicalKey ? "selection" : "project", targets: logicalKey ? [{ kind: "data", logical_key: logicalKey,
      object_id: "x2", block_id: "file", analysis_id: "analysis", snapshot_id: null, run_id: null, exact_evidence: false }] : [],
    block_id: null, excluded_keys: [],
  } });
const expanded = new Set(["folder:.", "file", "data:analysis.py::<module>::X", "assignment:x1"]);

describe("compact logical workspace", () => {
  it("keeps variables as leaves even when legacy assignment and evidence nodes were expanded", () => {
    const rows = buildObjectTree(doc(), [], null, expanded);
    expect(rows.filter(row => ["assignment", "evidence"].includes(row.rowKind))).toEqual([]);
    expect(rows.filter(row => row.rowKind === "variable").map(row => [row.label, row.expandable])).toEqual([["np", false], ["X", false], ["Y", false]]);
    expect(rows.find(row => row.label === "X")?.objectIds).toEqual(["x1", "x2"]);
    expect(rows.every(row => !/未观测|处定义|观测 v|赋值/.test(row.detail))).toBe(true);
  });
  it("offers variables-only filtering without including imports as variables", () => {
    const rows = buildObjectTree(doc(), [], null, expanded, "", "variables");
    expect(rows.filter(row => row.rowKind === "variable").map(row => row.label)).toEqual(["X", "Y"]);
    expect(rows.filter(row => row.matchesFilter).every(row => row.rowKind === "variable")).toBe(true);
  });
  it("counts enabled applicable bindings independently of whether they have run", () => {
    const local = probe("local", "analysis.py::<module>::X"), global = probe("default"), off = { ...probe("off"), enabled: false };
    const rows = buildObjectTree(doc(), [], null, expanded, "", "all", new Map(), { probes: [local, global, off] });
    expect(rows.find(row => row.label === "X")?.probeCount).toBe(2);
    expect(rows.find(row => row.label === "Y")?.probeCount).toBe(1);
  });
  it("classifies only current latest probe outcomes and does not call unevaluated objects normal", () => {
    const output = (id: string, status: string, created_at: string): ProbeOutput => ({ id, instance_id: "check", created_at, status,
      targets: [{ kind: "data", logical_key: "analysis.py::<module>::X", object_id: "x2", block_id: "file", analysis_id: "analysis", snapshot_id: null, run_id: null, exact_evidence: false }],
    } as ProbeOutput);
    const options = { outputs: [output("old", "fail", "2026-10-04T01:00:00Z"), output("new", "pass", "2026-10-04T02:00:00Z")] };
    expect(buildObjectTree(doc(), [], null, expanded, "", "all", new Map(), { ...options, probe: "normal" }).filter(row => row.matchesFilter).map(row => row.label)).toEqual(["X"]);
    expect(buildObjectTree(doc(), [], null, expanded, "", "all", new Map(), { ...options, probe: "failed" }).filter(row => row.matchesFilter)).toEqual([]);
  });
});
