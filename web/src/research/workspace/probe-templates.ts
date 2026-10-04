import type { ProbeTemplate, ProbeDefinition, ScopeSelector, WorkbenchConfig, TargetRef } from "./generated";
import { initialProbeParameters } from "./probe-configuration";

/** Templates are recipes. Applying one snapshots its members into bindings. */
export function applyProbeTemplate(config: WorkbenchConfig, template: ProbeTemplate, definitions: ProbeDefinition[], selector: ScopeSelector, applicationId = crypto.randomUUID(), scopedTargets: TargetRef[] = selector.targets ?? []): WorkbenchConfig {
  if (!template.members.length) throw new Error("模板至少需要一个探针");
  const probes = template.members.map(member => {
    const definition = definitions.find(d => d.id === member.definition_id);
    if (!definition) throw new Error("模板中的探针不可用：" + member.definition_id);
    if (definition.input_mode === "joint") throw new Error("联合输入探针请在新探针中指定输入角色");
    if (selector.mode === "selection" && !selector.targets.length) throw new Error("请先选择对象");
    if (selector.mode === "selection" && !scopedTargets.some(t => definition.supported_targets.includes(t.kind)))
      throw new Error("当前范围没有兼容此探针的对象：" + definition.label);
    return {
      id: `${applicationId}:${member.id}`, definition_id: member.definition_id, binding: "*", enabled: member.enabled,
      parameters: initialProbeParameters(definition, { ...config.probe_defaults[definition.id], ...structuredClone(member.parameters) }),
      policy: "continue" as const, budget_ms: member.budget_ms, selector: structuredClone(selector), inputs: {},
      origin: selector.mode === "project" ? "project_default" as const : "local" as const, overrides: {},
      template_id: template.id, template_label: template.label, template_application_id: applicationId,
    };
  });
  if (config.probes.length + probes.length > 128) throw new Error("探针绑定数量超过 128，请清理后重试");
  return { ...config, probes: [...config.probes, ...probes] };
}

export const probeDisplayName = (probe: { template_label?: string | null; definition_id: string }, definition?: ProbeDefinition) =>
  probe.definition_id === "view.auto" && probe.template_label ? probe.template_label : definition?.label ?? probe.definition_id;
