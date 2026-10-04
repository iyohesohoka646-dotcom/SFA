import { describe, expect, it } from "vitest";
import { applyProbeTemplate } from "../src/research/workspace/probe-templates";
import type { ProbeDefinition, ProbeTemplate, WorkbenchConfig, ScopeSelector } from "../src/research/workspace/generated";
const definitions = [{ id: "view.table", capability: "view", supported_targets: ["data"], input_mode: "per_target", parameter_schema: { properties: { precision: { default: 3 } } } }] as ProbeDefinition[];
const template = { id: "pair", label: "Tables", version: 1, members: [{ id: "values", definition_id: "view.table", parameters: { precision: 5 }, enabled: true, budget_ms: 5000 }] } as ProbeTemplate;
const config = { probes: [], probe_defaults: { "view.table": { precision: 7 } } } as unknown as WorkbenchConfig;
describe("probe recipe application", () => {
  it("freezes template parameters into independently configurable bindings", () => {
    const scope = { mode: "selection", targets: [{ kind: "data", logical_key: "X" }] } as ScopeSelector;
    const next = applyProbeTemplate(config, template, definitions, scope, "app");
    expect(next.probes[0]).toMatchObject({ definition_id: "view.table", template_id: "pair", template_label: "Tables", template_application_id: "app", parameters: { precision: 5 }, selector: scope });
    template.members[0].parameters.precision = 9;
    expect(next.probes[0].parameters.precision).toBe(5);
    expect(config.probes).toEqual([]);
    template.members[0].parameters.precision = 5;
  });
  it("rejects an unavailable definition and missing joint input instead of partially applying", () => {
    expect(() => applyProbeTemplate(config, { ...template, members: [{ ...template.members[0], definition_id: "missing" }] }, definitions, { mode: "project" } as ScopeSelector, "id")).toThrow();
    expect(() => applyProbeTemplate(config, template, [{ ...definitions[0], input_mode: "joint" }], { mode: "project" } as ScopeSelector, "id")).toThrow();
  });
  it("applies data members to compatible descendants of a selected file while retaining its range", () => {
    const scope = { mode: "selection", targets: [{ kind: "file", logical_key: "analysis.py" }] } as ScopeSelector;
    const descendants = [{ kind: "file", logical_key: "analysis.py" }, { kind: "data", logical_key: "X" }] as ScopeSelector["targets"];
    const next = applyProbeTemplate(config, template, definitions, scope, "file-app", descendants);
    expect(next.probes[0].selector).toEqual(scope);
    expect(() => applyProbeTemplate(config, template, definitions, scope, "empty-app", scope.targets)).toThrow("没有兼容");
  });
});
