import { describe, expect, it } from "vitest";
import { availableModels, compatibleProbes, currentProbeBlock, initialProbeParameters, probeAppliesToTarget,
  probeScopeSelector, removeLogicalProbeTarget, resolveProbeBlock, sameLogicalTarget, scopeProbeTargets, snapshotProbeTarget,
  targetOverrideKey, targetOverrideError, targetOverride, targetProbeEntries } from "../src/research/workspace/probe-configuration";
import type { AnalysisDocument, ProbeDefinition, ProbeInstance, TargetRef } from "../src/research/workspace/generated";

const target = (kind: TargetRef["kind"], key: string, block = "fn"): TargetRef => ({
  kind, logical_key: key, block_id: block, object_id: key, analysis_id: "analysis", run_id: null, snapshot_id: null, exact_evidence: false,
});
const x = target("data", "demo::f::X"), y = target("data", "demo::f::Y"), z = target("data", "demo::<module>::Z", "file");
const fn = target("function", "demo::<module>::f");
const analysis = {
  id: "analysis", path: "demo.py", objects: [x, y, z, fn].map((item) => ({ id: item.object_id, name: item.logical_key.split("::").at(-1), kind: item.kind === "function" ? "function" : "assignment", block_id: item.block_id, logical_key: item.logical_key })),
  graph: { roots: ["file"], blocks: [{ id: "file", kind: "file", label: "demo.py", logical_key: "demo", parent_id: null },
    { id: "fn", kind: "function", label: "f", logical_key: fn.logical_key, source_object_id: fn.object_id, parent_id: "file" }], nodes: [] },
} as unknown as AnalysisDocument;
const definition = (id: string, capability: ProbeDefinition["capability"], kinds: TargetRef["kind"][] = ["data"]): ProbeDefinition => ({
  id, label: id, capability, supported_targets: kinds, input_mode: "per_target", parameter_schema: {},
} as ProbeDefinition);
const views = [definition("view.auto", "view"), definition("view.controls", "view", ["control"]),
  definition("check.finite", "check"), definition("interpret.model", "interpret", ["data", "function", "file"])];
const probe = (id: string, patch: Partial<ProbeInstance> = {}): ProbeInstance => ({
  id, definition_id: "view.auto", binding: "*", enabled: true, parameters: { precision: 3 }, policy: "continue", budget_ms: 5000,
  selector: { mode: "project", block_id: null, targets: [], excluded_keys: [] }, origin: "project_default", inputs: {}, overrides: {}, ...patch,
});

const repeatedLocals = () => {
  const first = { ...fn, object_id: "function-1", block_id: "fn-1" };
  const second = { ...fn, object_id: "function-2", block_id: "fn-2" };
  const firstValue = { ...x, object_id: "x-1", block_id: "fn-1" };
  const secondValue = { ...x, object_id: "x-2", block_id: "fn-2" };
  const values = [first, second, firstValue, secondValue];
  const document = { ...analysis, objects: values.map((item, i) => ({
    id: item.object_id, name: item.logical_key.split("::").at(-1), kind: item.kind === "function" ? "function" : "assignment",
    block_id: item.block_id, logical_key: item.logical_key, line: i + 1, end_line: i + 1, column: 0,
  })), graph: { ...analysis.graph, blocks: [analysis.graph.blocks[0],
    { ...analysis.graph.blocks[1], id: "fn-1", source_object_id: first.object_id },
    { ...analysis.graph.blocks[1], id: "fn-2", source_object_id: second.object_id }],
    nodes: [firstValue, secondValue].map((item) => ({ id: item.object_id, kind: "data", logical_key: item.logical_key, block_id: item.block_id })),
  } } as AnalysisDocument;
  return { document, first, second, firstValue, secondValue };
};

describe("lexical probe overrides", () => {
  it("isolates enabled state and parameters for repeated function locals and supports restoring one owner", () => {
    const { document, firstValue, secondValue } = repeatedLocals();
    const firstKey = targetOverrideKey(firstValue, document)!;
    expect(firstKey).not.toBe(targetOverrideKey(secondValue, document));
    const configured = probe("default", { overrides: { [firstKey]: { enabled: false, parameters: { precision: 6 } } } });
    expect(targetProbeEntries([configured], views, firstValue, document)[0]).toMatchObject({ enabled: false, parameters: { precision: 6 } });
    expect(targetProbeEntries([configured], views, secondValue, document)[0]).toMatchObject({ enabled: true, parameters: { precision: 3 } });
    delete configured.overrides[firstKey];
    expect(targetOverride(configured, firstValue, document)).toBeUndefined();
  });
  it("separates repeated function targets by their own block", () => {
    const { document, first, second } = repeatedLocals();
    const firstKey = targetOverrideKey(first, document)!;
    expect(firstKey).not.toBe(targetOverrideKey(second, document));
    const configured = probe("interpret", { definition_id: "interpret.model", overrides: { [firstKey]: { enabled: false, parameters: {} } } });
    expect(targetOverride(configured, first, document)?.enabled).toBe(false);
    expect(targetOverride(configured, second, document)).toBeUndefined();
  });
  it("retains ordinary legacy keys and one lexical owner through branch blocks", () => {
    const { document, firstValue, secondValue } = repeatedLocals();
    const oneOwner = { ...document, graph: { ...document.graph,
      blocks: [...document.graph.blocks, { ...document.graph.blocks[1], id: "branch", kind: "condition", parent_id: "fn-1" }],
      nodes: document.graph.nodes.map((node) => ({ ...node, block_id: "branch" })),
    } } as AnalysisDocument;
    expect(targetOverrideKey({ ...firstValue, block_id: "branch" }, oneOwner)).toBe(x.logical_key);
    expect(targetOverrideKey(z, document)).toBe(z.logical_key);
    expect(targetOverride(probe("legacy", { overrides: { [x.logical_key]: { enabled: false, parameters: {} } } }),
      { ...secondValue, block_id: "branch" }, oneOwner)?.enabled).toBe(false);
  });
  it("does not expand a stale data selection across repeated lexical owners", () => {
    const { document, firstValue, secondValue } = repeatedLocals();
    const stale = { ...firstValue, object_id: "old-x", block_id: "old-owner" };
    expect(sameLogicalTarget(stale, firstValue, document)).toBe(false);
    expect(sameLogicalTarget(stale, secondValue, document)).toBe(false);
    const local = probe("stale", { selector: { mode: "selection", block_id: null, targets: [stale], excluded_keys: [] } });
    expect(probeAppliesToTarget(local, firstValue, document)).toBe(false);
    expect(scopeProbeTargets(document, local.selector!)).toEqual([]);
  });
  it("marks stale or raw ambiguous overrides invalid without applying them to another owner", () => {
    const { document, firstValue, secondValue } = repeatedLocals();
    const configured = probe("stale", { overrides: { [x.logical_key + "::scope:old-owner"]: { enabled: false, parameters: { precision: 6 } } } });
    expect(targetOverrideError(configured, firstValue, document)).toContain("重新绑定");
    expect(targetOverride(configured, secondValue, document)).toBeUndefined();
    expect(targetProbeEntries([configured], views, firstValue, document)[0]).toMatchObject({ enabled: false, overrideError: expect.any(String) });
    expect(targetOverrideError(configured, z, document)).toBeUndefined();
    expect(targetOverrideError(probe("raw", { overrides: { [x.logical_key]: { enabled: false, parameters: {} } } }), firstValue, document)).toContain("重新绑定");
  });
  it("maps a snapshot to its exact assignment in the corresponding analysis", () => {
    const { document, firstValue, secondValue } = repeatedLocals();
    const snapshot = { id: "saved-first", run_id: "old-run", name: "X", logical_key: x.logical_key,
      scope_id: "f:1", source: { path: "demo.py", line: 3, column: 0 } } as any;
    expect(snapshotProbeTarget(snapshot, document)).toMatchObject({ object_id: firstValue.object_id, block_id: firstValue.block_id, run_id: "old-run" });
    expect(snapshotProbeTarget({ ...snapshot, source: { ...snapshot.source, line: 4 } }, document).object_id).toBe(secondValue.object_id);
  });
});

describe("probe configuration", () => {
  it("seeds a new binding from schema and saved defaults without changing either source or an existing binding", () => {
    const source = definition("view.auto", "view");
    source.parameter_schema = { properties: { precision: { type: "integer", default: 3 }, show_coordinates: { type: "boolean", default: true }, row_labels: { type: "array", default: [] } } };
    const saved = { precision: 7, row_labels: ["A"] };
    const existing = probe("existing");
    const first = initialProbeParameters(source, saved);
    (first.row_labels as string[]).push("B");
    expect(initialProbeParameters(source, saved)).toEqual({ precision: 7, show_coordinates: true, row_labels: ["A"] });
    expect(existing.parameters.precision).toBe(3);
    expect(saved.row_labels).toEqual(["A"]);
  });
  it("uses observed shape/type only when the library has not authored a default for them", () => {
    const shape = definition("check.shape", "check");
    shape.parameter_schema = { properties: { expected: { default: [] } } };
    const snapshot = { descriptor: { shape: [2, 3], dtype: "int64" } } as any;
    expect(initialProbeParameters(shape, {}, snapshot).expected).toEqual([2, 3]);
    expect(initialProbeParameters(shape, { expected: [null, 4] }, snapshot).expected).toEqual([null, 4]);
    expect(initialProbeParameters(definition("check.dtype", "check"), {}, snapshot).expected).toBe("int64");
  });
  it("offers only compatible probes of the selected purpose, including a multi-target selection", () => {
    expect(compatibleProbes(views, "interpret", "", [x, fn]).map((item) => item.id)).toEqual(["interpret.model"]);
    expect(compatibleProbes(views, "view", "", [x]).map((item) => item.id)).toEqual(["view.auto"]);
    expect(compatibleProbes(views, "check", "view", [x])).toEqual([]);
  });
  it("resolves the current file when the workbench has no explicit block scope", () => {
    expect(currentProbeBlock(analysis)?.id).toBe("file");
    expect(currentProbeBlock(analysis, "fn")?.id).toBe("fn");
    expect(currentProbeBlock(analysis, "stale-block")?.id).toBe("file");
    expect(currentProbeBlock()).toBeUndefined();
  });
  it("allows a function or several objects to bind compatible descendant probes while keeping siblings outside scope", () => {
    const scope = { mode: "selection", block_id: null, targets: [fn], excluded_keys: [] } as const;
    const resolved = scopeProbeTargets(analysis, { ...scope, targets: [...scope.targets], excluded_keys: [] });
    expect(resolved.map((item) => item.logical_key)).toEqual(expect.arrayContaining([x.logical_key, y.logical_key, fn.logical_key]));
    expect(resolved.some((item) => item.logical_key === z.logical_key)).toBe(false);
    expect(compatibleProbes(views, "view", "", resolved).map((item) => item.id)).toContain("view.auto");
    const multi = scopeProbeTargets(analysis, { mode: "selection", block_id: null, targets: [x, z], excluded_keys: [] });
    expect(multi.map((item) => item.logical_key).sort()).toEqual([x.logical_key, z.logical_key].sort());
  });
  it("keeps selected historical versions exact and does not substitute the source/current value", () => {
    const historical = { ...x, snapshot_id: "old", exact_evidence: true };
    const current = { ...x, snapshot_id: "new", exact_evidence: true };
    const resolved = scopeProbeTargets(analysis, { mode: "selection", block_id: null, targets: [historical, current], excluded_keys: [] });
    expect(resolved.map((item) => item.snapshot_id)).toEqual(["old", "new"]);
    const pinned = probe("pinned", { selector: { mode: "selection", block_id: null, targets: [historical], excluded_keys: [] } });
    expect(probeAppliesToTarget(pinned, historical, analysis)).toBe(true);
    expect(probeAppliesToTarget(pinned, current, analysis)).toBe(false);
  });
  it("does not include a different repeated function declaration with the same legacy logical key", () => {
    const first = { ...fn, object_id: "function-1", block_id: "fn-1" };
    const second = { ...fn, object_id: "function-2", block_id: "fn-2" };
    const firstValue = { ...x, object_id: "x-1", block_id: "fn-1" };
    const secondValue = { ...x, object_id: "x-2", block_id: "fn-2" };
    const repeated = { ...analysis, objects: [first, second, firstValue, secondValue].map((item) => ({
      id: item.object_id, name: item.logical_key.split("::").at(-1), kind: item.kind === "function" ? "function" : "assignment",
      block_id: item.block_id, logical_key: item.logical_key,
    })), graph: { ...analysis.graph, blocks: [analysis.graph.blocks[0], { ...analysis.graph.blocks[1], id: "fn-1", source_object_id: first.object_id }, { ...analysis.graph.blocks[1], id: "fn-2", source_object_id: second.object_id }] } } as AnalysisDocument;
    const resolved = scopeProbeTargets(repeated, { mode: "selection", block_id: null, targets: [first], excluded_keys: [] });
    expect(resolved.map((item) => item.object_id)).toEqual(expect.arrayContaining(["function-1", "x-1"]));
    expect(resolved.some((item) => ["function-2", "x-2"].includes(item.object_id!))).toBe(false);
    const local = probe("local", { origin: "local", selector: { mode: "selection", block_id: null, targets: [firstValue], excluded_keys: [] } });
    expect(probeAppliesToTarget(local, secondValue, repeated)).toBe(false);
  });
  it("removes a saved logical variable after its final assignment changes the selected object ID", () => {
    const firstAssignment = { ...x, object_id: "x-first" };
    const finalAssignment = { ...x, object_id: "x-final" };
    const selector = { mode: "selection" as const, block_id: null, targets: [firstAssignment, y], excluded_keys: [] };
    const remaining = removeLogicalProbeTarget(selector, finalAssignment, analysis);
    expect(remaining.targets).toEqual([y]);
    expect(selector.targets).toEqual([firstAssignment, y]);
    expect(probeAppliesToTarget(probe("remaining", { selector: remaining }), finalAssignment, analysis)).toBe(false);
    expect(probeAppliesToTarget(probe("remaining", { selector: remaining }), y, analysis)).toBe(true);
  });
  it("preserves a same-name variable in another lexical block and pinned historical evidence during removal", () => {
    const sibling = { ...x, object_id: "x-sibling", block_id: "sibling" };
    const scoped = { ...analysis, graph: { ...analysis.graph, blocks: [...analysis.graph.blocks,
      { ...analysis.graph.blocks[1], id: "sibling", logical_key: "demo::<module>::sibling" }] } } as AnalysisDocument;
    const historical = { ...x, snapshot_id: "old", exact_evidence: true };
    const current = { ...x, object_id: "x-final", snapshot_id: "new" };
    const selector = { mode: "selection" as const, block_id: null, targets: [x, sibling, historical, y], excluded_keys: [] };
    expect(removeLogicalProbeTarget(selector, current, scoped).targets).toEqual([sibling, historical, y]);
  });
  it("keeps a saved function binding after formatting changes its object and block IDs", () => {
    const saved = { ...fn, object_id: "old-function", block_id: "old-block" };
    const local = probe("saved-function", { definition_id: "interpret.model", origin: "local",
      selector: { mode: "selection", block_id: null, targets: [saved], excluded_keys: [] } });
    expect(sameLogicalTarget(saved, fn, analysis)).toBe(true);
    expect(probeAppliesToTarget(local, fn, analysis)).toBe(true);
    expect(probeAppliesToTarget(local, x, analysis)).toBe(true);
    expect(probeAppliesToTarget(local, z, analysis)).toBe(false);
    const resolved = scopeProbeTargets(analysis, local.selector!);
    expect(resolved.map((item) => item.object_id).sort()).toEqual([fn.object_id, x.object_id, y.object_id].sort());
    expect(resolved.some((item) => item.object_id === saved.object_id)).toBe(false);
    expect(targetProbeEntries([local], views, fn, analysis)[0].inherited).toBe(false);
    expect(removeLogicalProbeTarget({ ...local.selector!, targets: [saved, y] }, fn, analysis).targets).toEqual([y]);
  });
  it("recovers a stale block ID through one logical-key block, including control descendants", () => {
    const control = { ...target("control", "demo::f::loop", "loop"), object_id: null };
    const child = { ...x, block_id: "loop" };
    const withControl = { ...analysis, objects: [analysis.objects[3],
      { ...analysis.objects[0], block_id: "loop" }], graph: { ...analysis.graph, blocks: [...analysis.graph.blocks,
      { ...analysis.graph.blocks[1], id: "loop", kind: "loop", logical_key: control.logical_key, source_object_id: null, parent_id: "fn" }] } } as AnalysisDocument;
    const saved = { ...control, block_id: "old-loop" };
    const local = probe("control", { selector: { mode: "selection", block_id: null, targets: [saved], excluded_keys: [] } });
    expect(probeAppliesToTarget(local, child, withControl)).toBe(true);
    expect(probeAppliesToTarget(local, z, withControl)).toBe(false);
    const resolved = scopeProbeTargets(withControl, local.selector!);
    expect(resolved.some((item) => item.logical_key === child.logical_key)).toBe(true);
    expect(resolved.every((item) => item.block_id !== saved.block_id)).toBe(true);
  });
  it("requires rebinding a stale function reference when repeated definitions share its logical key", () => {
    const first = { ...fn, object_id: "function-1", block_id: "fn-1" };
    const second = { ...fn, object_id: "function-2", block_id: "fn-2" };
    const firstValue = { ...x, object_id: "x-1", block_id: "fn-1" };
    const repeated = { ...analysis, objects: [first, second, firstValue].map((item) => ({
      id: item.object_id, name: item.logical_key.split("::").at(-1), kind: item.kind === "function" ? "function" : "assignment",
      block_id: item.block_id, logical_key: item.logical_key,
    })), graph: { ...analysis.graph, blocks: [analysis.graph.blocks[0],
      { ...analysis.graph.blocks[1], id: "fn-1", source_object_id: first.object_id },
      { ...analysis.graph.blocks[1], id: "fn-2", source_object_id: second.object_id }] } } as AnalysisDocument;
    const stale = { ...fn, object_id: "old-function", block_id: "old-block" };
    const local = probe("ambiguous", { selector: { mode: "selection", block_id: null, targets: [stale], excluded_keys: [] } });
    expect(sameLogicalTarget(stale, first, repeated)).toBe(false);
    expect(probeAppliesToTarget(local, first, repeated)).toBe(false);
    expect(probeAppliesToTarget(local, firstValue, repeated)).toBe(false);
    expect(scopeProbeTargets(repeated, local.selector!)).toEqual([]);
  });
  it("saves a stable block reference only when constructing a new block binding", () => {
    const selector = probeScopeSelector(analysis, "fn", [z], "block");
    expect(selector).toEqual({ mode: "block", block_id: "fn", excluded_keys: [], targets: [fn] });
    expect(probeScopeSelector(analysis, "fn", [z], "selection").targets).toEqual([z]);
    expect(probeScopeSelector(analysis, "fn", [z], "project").targets).toEqual([]);
  });
  it("restores a saved block scope through a unique logical block after its ID changes", () => {
    const saved = { ...fn, object_id: "old-function", block_id: "old-block" };
    const selector = { mode: "block" as const, block_id: saved.block_id, targets: [saved], excluded_keys: [] };
    const local = probe("block", { selector });
    expect(resolveProbeBlock(analysis, selector)?.id).toBe("fn");
    expect(scopeProbeTargets(analysis, selector).map((item) => item.object_id).sort()).toEqual([fn.object_id, x.object_id, y.object_id].sort());
    expect(probeAppliesToTarget(local, x, analysis)).toBe(true);
    expect(probeAppliesToTarget(local, z, analysis)).toBe(false);
    expect(selector.block_id).toBe("old-block");
  });
  it("does not recover an ambiguous stale block or silently widen a legacy block without a reference", () => {
    const selector = { mode: "block" as const, block_id: "old-block", targets: [{ ...fn, block_id: "old-block" }], excluded_keys: [] };
    const repeated = { ...analysis, graph: { ...analysis.graph, blocks: [...analysis.graph.blocks,
      { ...analysis.graph.blocks[1], id: "fn-repeat", source_object_id: "fn-repeat-object" }] } } as AnalysisDocument;
    expect(resolveProbeBlock(repeated, selector)).toBeUndefined();
    expect(scopeProbeTargets(repeated, selector)).toEqual([]);
    expect(probeAppliesToTarget(probe("ambiguous-block", { selector }), x, repeated)).toBe(false);
    const legacy = { ...selector, targets: [] };
    expect(resolveProbeBlock(analysis, legacy)).toBeUndefined();
    expect(scopeProbeTargets(analysis, legacy)).toEqual([]);
  });
  it("separates inherited/local entries and applies local parameters without modifying project defaults", () => {
    const shared = probe("shared", { overrides: { [x.logical_key]: { enabled: false, parameters: { precision: 6 } } } });
    const local = probe("local", { origin: "local", selector: { mode: "selection", block_id: null, targets: [x], excluded_keys: [] } });
    const entries = targetProbeEntries([shared, local], views, x, analysis);
    expect(entries.map((item) => [item.probe.id, item.inherited, item.enabled])).toEqual([["shared", true, false], ["local", false, true]]);
    expect(entries[0].parameters.precision).toBe(6);
    expect(targetProbeEntries([shared, local], views, y, analysis)).toHaveLength(1);
    expect(shared.parameters.precision).toBe(3);
  });
  it("reports matching descendants and mixed override states for an entire selected block", () => {
    const shared = probe("shared", { overrides: { [x.logical_key]: { enabled: false, parameters: { precision: 6 } } } });
    const entry = targetProbeEntries([shared], views, fn, analysis)[0];
    expect(entry.targets.map((item) => item.logical_key)).toEqual([x.logical_key, y.logical_key]);
    expect(entry.enabledCount).toBe(1);
    expect(entry.mixedParameters).toBe(true);
  });
  it("lists saved/default models once, including a saved default absent from discovery", () => {
    expect(availableModels({ default_model: "chosen", models: ["one", "one", "chosen", "two"] } as any)).toEqual(["chosen", "one", "two"]);
    expect(availableModels()).toEqual([]);
  });
});
