import { ParameterForm } from "./ParameterForm";
import { Icon } from "./icons";
import { wb } from "./WorkbenchClient";
import { purposeNames, implementationNames } from "./probe-taxonomy";
import type { ProbeDefinition, ProbeInstance } from "./generated";
import { probeDisplayName } from "./probe-templates";

export function ProbeBindingRow({ probe, definition, open, onToggle, onUpdate, onRemove, onError,
  parameters = probe.parameters, enabled = probe.enabled, onParameters, onEnabled, inherited, targetCount,
  enabledCount, mixedParameters, onRestore, onEditSource, modelPolicy, onModelSettings }: {
  probe: ProbeInstance;
  definition?: ProbeDefinition;
  open: boolean;
  onToggle: () => void;
  onUpdate: (patch: Partial<ProbeInstance>) => void;
  onRemove?: () => void;
  onError: (message: string) => void;
  parameters?: Record<string, unknown>;
  enabled?: boolean;
  onParameters?: (parameters: Record<string, unknown>) => void;
  onEnabled?: (enabled: boolean) => void;
  inherited?: boolean;
  targetCount?: number;
  enabledCount?: number;
  mixedParameters?: boolean;
  onRestore?: () => void;
  onEditSource?: () => void;
  modelPolicy?: { provider_id?: string; model?: string | null };
  onModelSettings?: () => void;
}) {
  const targetScoped = Boolean(onEnabled);
  const description = probe.selector?.mode === "project" ? "整个项目"
    : probe.selector?.mode === "block" ? "块范围"
    : probe.selector?.mode === "selection" ? probe.selector.targets.length + " 个目标" : probe.binding;
  return (
    <div className="wb-probe-row" data-testid="probe-binding-row">
      <div>
        <input type="checkbox" aria-label={"启用 " + probe.definition_id} checked={enabled}
          aria-checked={enabledCount !== undefined && targetCount !== undefined && enabledCount > 0 && enabledCount < targetCount ? "mixed" : enabled}
          ref={(element) => { if (element) element.indeterminate = Boolean(enabledCount && targetCount && enabledCount < targetCount); }}
          disabled={targetScoped && !probe.enabled}
          onChange={(event) => onEnabled ? onEnabled(event.target.checked) : onUpdate({ enabled: event.target.checked })} />
        <button className="wb-probe-name" aria-expanded={open} onClick={onToggle}>{probeDisplayName(probe, definition)}</button>
        {onRemove && <button aria-label={"删除 " + probe.definition_id} onClick={onRemove}><Icon name="close" size={12} /></button>}
      </div>
      <small>
        <span className={"wb-kind " + definition?.capability}>{definition ? purposeNames[definition.capability] : "不可用"}</span>{" "}
        {definition ? implementationNames[definition.execution] + " · " : ""}
        {targetScoped ? inherited ? "继承绑定" : "本地绑定" : description}
        {probe.origin === "project_default" ? " · 项目默认" : ""}
        {probe.template_label && probe.definition_id !== "view.auto" ? " · " + probe.template_label : ""}
        {targetCount && targetCount > 1 ? " · " + enabledCount + "/" + targetCount + " 个对象启用" : ""}
        {!probe.enabled ? " · 全局停用" : !enabled ? " · 此对象停用" : ""}
      </small>
      {open && <>
        {mixedParameters && <div className="probe-field-hint">对象参数不同；此处修改会应用到本范围的匹配对象。</div>}
        <ParameterForm schema={definition?.parameter_schema ?? {}} value={parameters}
          onChange={(next) => onParameters ? onParameters(next) : onUpdate({ parameters: next })}
          modelPolicy={modelPolicy} onModelSettings={onModelSettings} />
        {targetScoped ? (
          <div className="probe-local-actions">
            {onRestore && <button onClick={onRestore}>恢复绑定参数</button>}
            {onEditSource && <button onClick={onEditSource}>编辑源绑定</button>}
          </div>
        ) : (
          <div className="wb-form compact">
            <label>控制<select value={probe.policy} onChange={(event) => onUpdate({ policy: event.target.value as ProbeInstance["policy"] })}>
              <option value="continue">继续</option><option value="pause">检查异常时暂停</option><option value="cancel">检查失败时取消</option>
            </select></label>
            <label>预算 ms<input type="number" value={probe.budget_ms} min={1} max={120000}
              onChange={(event) => onUpdate({ budget_ms: Number(event.target.value) })} /></label>
            <button onClick={() => void wb.saveTemplate(crypto.randomUUID(), definition?.label ?? probe.id, probe.definition_id, probe.parameters)
              .catch((error) => onError(error.message))}>保存参数预设</button>
          </div>
        )}
      </>}
    </div>
  );
}
