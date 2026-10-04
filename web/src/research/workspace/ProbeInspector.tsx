import { useEffect, useMemo, useState } from "react";
import type { AnalysisDocument, ProbeDefinition, ProbeInstance, ProbeOutput, WorkbenchConfig, TargetRef } from "./generated";
import type { SnapshotRef } from "../generated";
import { Icon } from "./icons";
import { wb } from "./WorkbenchClient";
import { ParameterForm } from "./ParameterForm";
import { ProbeBindingRow } from "./ProbeBindingRow";
import { purposeNames, targetNames } from "./probe-taxonomy";
import { scopeSelector, selectionKey, type Selection } from "./selection";
import { compatibleProbes, currentProbeBlock, initialProbeParameters, probeScopeSelector, probeTargetLabel, removeLogicalProbeTarget, scopeProbeTargets, targetOverrideKey, targetProbeEntries } from "./probe-configuration";
import { applyProbeTemplate } from "./probe-templates";
import "./probe-management.css";

export function ProbeInspector({ config, definitions, selected, analysis, outputs, onChange, onSave, onError,
  onRecorded, selection, blockScope, requested, onRequestedHandled, onModelSettings }: {
  config: WorkbenchConfig;
  definitions: ProbeDefinition[];
  selected?: SnapshotRef;
  analysis?: AnalysisDocument;
  outputs: ProbeOutput[];
  onChange: (config: WorkbenchConfig) => void;
  onSave: () => Promise<unknown>;
  onError: (message: string) => void;
  onRecorded: (output: ProbeOutput) => void;
  selection?: Selection;
  blockScope?: string | null;
  requested?: string;
  onRequestedHandled?: () => void;
  onModelSettings?: () => void;
}) {
  const [tab, setTab] = useState<"inspect" | "apply" | "templates">("inspect");
  const [templateId, setTemplateId] = useState("");
  const [adding, setAdding] = useState(false), [type, setType] = useState("view.matrix");
  const [range, setRange] = useState<"selection" | "project">("selection");
  const [purpose, setPurpose] = useState("all"), [query, setQuery] = useState("");
  const [editing, setEditing] = useState<string>(), [params, setParams] = useState<Record<string, unknown>>({});
  const [note, setNote] = useState(""), [verdict, setVerdict] = useState("unknown");
  const [roles, setRoles] = useState<Record<string, string>>({});
  const [expanded, setExpanded] = useState(new Set<string>()), [globalOpen, setGlobalOpen] = useState(false);
  const [templates, setTemplates] = useState<{ id: string; label: string; definition_id: string; parameters: Record<string, unknown> }[]>([]);
  useEffect(() => {
    void wb.templates().then(setTemplates).catch((error) => onError(error.message));
  }, []);
  const targets = selection?.targets ?? [];
  const currentBlock = currentProbeBlock(analysis, blockScope);
  const modelPolicy = config.harness.find((policy) => policy.role === "probe");
  const defaultsFor = (definition: ProbeDefinition) => initialProbeParameters(definition, config.probe_defaults?.[definition.id], selected);
  const prospectiveScope = probeScopeSelector(analysis, currentBlock?.id ?? null, targets, range);
  const scopedTargets = scopeProbeTargets(analysis, prospectiveScope);
  const compatible = compatibleProbes(definitions, purpose, query, scopedTargets).filter(d => d.id !== "view.auto");
  const definition = compatible.find((item) => item.id === type) ?? compatible[0];
  const roleTargets = scopedTargets;
  const displayTargets = targets;
  const groups = useMemo(() => displayTargets.map((target) => ({
    target, entries: targetProbeEntries(config.probes, definitions, target, analysis),
  })), [config.probes, definitions, analysis, selection, currentBlock]);
  useEffect(() => {
    if (displayTargets.length === 1) setExpanded((current) => new Set([...current, selectionKey(displayTargets[0])]));
  }, [selection, currentBlock?.id]);
  useEffect(() => {
    if (adding && definition && definition.id !== type) {
      setType(definition.id);
      setParams(defaultsFor(definition));
      setRoles({});
    }
  }, [adding, definition?.id, type]);
  useEffect(() => {
    if (!requested) return;
    const chosen = definitions.find((item) => item.id === requested);
    if (!chosen) { onError("探针定义不可用，请刷新探针库"); onRequestedHandled?.(); return; }
    setPurpose(chosen.capability);
    setQuery("");
    setRange(targets.length ? "selection" : "project");
    setType(chosen.id);
    setAdding(true);
    setTab("apply");
    setParams(defaultsFor(chosen));
    setRoles({});
    onRequestedHandled?.();
  }, [requested]);
  const update = (id: string, patch: Partial<ProbeInstance>) => onChange({
    ...config, probes: config.probes.map((probe) => probe.id === id ? { ...probe, ...patch } : probe),
  });
  const remove = (id: string) => onChange({ ...config, probes: config.probes.filter((probe) => probe.id !== id) });
  const startAdding = () => {
    const nextRange = targets.length ? "selection" : "project";
    const choices = compatibleProbes(definitions, purpose, query, scopeProbeTargets(analysis, probeScopeSelector(analysis, currentBlock?.id ?? null, targets, nextRange))).filter(d => d.id !== "view.auto");
    const chosen = choices.find((item) => item.id === type) ?? choices[0];
    setRange(nextRange);
    if (chosen) { setType(chosen.id); setParams(defaultsFor(chosen)); }
    setRoles({});
    setAdding(true);
    setTab("apply");
  };
  const add = () => {
    if (!definition) return;
    const inputs: Record<string, TargetRef> = {};
    if (definition.input_mode === "joint") {
      for (const [index, role] of definition.input_roles.entries()) {
        const eligible = roleTargets.filter((target) => role.supported_targets.includes(target.kind));
        const target = eligible.find((item) => selectionKey(item) === roles[role.name]) ?? eligible[index];
        if (!target && role.required) { onError("请选择联合输入：" + role.name); return; }
        if (target) inputs[role.name] = target;
      }
    }
    const instance: ProbeInstance = {
      id: crypto.randomUUID(), definition_id: definition.id, binding: "*", enabled: true,
      parameters: params, policy: "continue", budget_ms: definition.tool_id ? 30000 : 5000,
      selector: definition.input_mode === "joint" ? scopeSelector(null, Object.values(inputs), "selection") : prospectiveScope,
      inputs, origin: range === "project" && definition.input_mode !== "joint" ? "project_default" : "local", overrides: {},
      template_id: null, template_label: null, template_application_id: null,
    };
    onChange({ ...config, probes: [...config.probes, instance] });
    setAdding(false);
    setTab("inspect");
    const first = displayTargets.find((target) => targetProbeEntries([instance], definitions, target, analysis).length);
    if (first) {
      setExpanded((current) => new Set([...current, selectionKey(first)]));
      setEditing(selectionKey(first) + "::" + instance.id);
    } else { setGlobalOpen(true); setEditing(instance.id); }
  };
  const manualProbe = config.probes.find(probe => probe.id === editing?.split("::").at(-1)
    && definitions.find(d => d.id === probe.definition_id)?.execution === "manual");
  return (
    <div className="wb-inspector">
      <div className="wb-view-toolbar">
        <strong>探针台</strong>
        <button aria-label="添加探针" onClick={() => adding ? setAdding(false) : startAdding()}><Icon name="add" /></button>
        <button onClick={() => void onSave().catch((error) => onError(error.message))}>保存</button>
      </div>
      <div className="wb-local-tabs" role="tablist" aria-label="探针台模式">
        {([["inspect", "选中对象"], ["apply", "新探针"], ["templates", "应用模板"]] as const).map(([id, label]) =>
          <button key={id} role="tab" aria-selected={tab === id} onClick={() => { setTab(id); if (id === "apply") startAdding(); if (id === "templates" && !targets.length) setRange("project"); }}>{label}</button>)}
      </div>
      {tab === "inspect" && <div className="probe-object-list">
        {!groups.length && <div className="probe-empty">选择对象后查看绑定</div>}
        {groups.map(({ target, entries }) => {
          const key = selectionKey(target), label = probeTargetLabel(target, analysis);
          return (
            <details key={key} className="probe-object-section" open={expanded.has(key)} onToggle={(event) => {
              const open = event.currentTarget.open;
              setExpanded((current) => { const next = new Set(current); if (open) next.add(key); else next.delete(key); return next; });
            }}>
              <summary>{label}<small>{targetNames[target.kind]} · {entries.length} 个探针{target.exact_evidence ? " · 历史版本" : ""}</small></summary>
              {expanded.has(key) && <div className="wb-probe-list">
                {([true, false] as const).map((inherited) => {
                  const list = entries.filter((entry) => Boolean(entry.inherited) === inherited);
                  return list.length ? <div key={String(inherited)}>
                    <div className="wb-section-label">{inherited ? "继承与项目默认" : "本地绑定"}</div>
                    {list.map((entry) => {
                      const { probe } = entry, rowKey = key + "::" + probe.id;
                      const overrideKeys = entry.targets.map((item) => targetOverrideKey(item, analysis)).filter((item): item is string => Boolean(item));
                      const hasOverrides = overrideKeys.some((item) => item in probe.overrides);
                      const override = (patch: { enabled?: boolean; parameters?: Record<string, unknown> }) => {
                        if (entry.overrideError) { onError(entry.overrideError); return; }
                        const next = { ...probe.overrides };
                        for (const item of overrideKeys) next[item] = {
                          enabled: patch.enabled ?? next[item]?.enabled ?? null,
                          parameters: patch.parameters ? { ...next[item]?.parameters, ...patch.parameters } : next[item]?.parameters ?? {},
                        };
                        update(probe.id, { overrides: next });
                      };
                      const removeLocal = !inherited ? () => {
                        const known = definitions.find((item) => item.id === probe.definition_id);
                        if (known?.input_mode !== "joint" && probe.selector?.mode === "selection" && probe.selector.targets.length > 1) {
                          const selector = removeLogicalProbeTarget(probe.selector, target, analysis);
                          if (selector.targets.length) update(probe.id, { selector });
                          else remove(probe.id);
                        } else remove(probe.id);
                      } : undefined;
                      return <div key={rowKey}>{entry.overrideError && <div role="alert" className="probe-field-hint">{entry.overrideError}</div>}<ProbeBindingRow probe={probe} definition={definitions.find((item) => item.id === probe.definition_id)}
                        open={editing === rowKey} onToggle={() => setEditing(editing === rowKey ? undefined : rowKey)}
                        onUpdate={(patch) => update(probe.id, patch)} onRemove={removeLocal} onError={onError}
                        parameters={entry.parameters} enabled={entry.enabled} onParameters={(parameters) => override({ parameters })}
                        onEnabled={(enabled) => override({ enabled })} inherited={Boolean(entry.inherited)}
                        targetCount={entry.targets.length} enabledCount={entry.enabledCount} mixedParameters={entry.mixedParameters}
                        onRestore={hasOverrides ? () => { const next = { ...probe.overrides }; overrideKeys.forEach((item) => delete next[item]); update(probe.id, { overrides: next }); } : undefined}
                        onEditSource={() => { setGlobalOpen(true); setEditing(probe.id); }} modelPolicy={modelPolicy} onModelSettings={onModelSettings} /></div>;
                    })}
                  </div> : null;
                })}
                {!entries.length && <div className="probe-empty">此对象没有绑定探针。</div>}
              </div>}
            </details>
          );
        })}
      </div>}
      {tab === "inspect" && globalOpen && config.probes.some(probe => probe.id === editing) && <details className="probe-project-bindings" open onToggle={(event) => setGlobalOpen(event.currentTarget.open)}>
        <summary>编辑源绑定</summary>
        <div className="wb-probe-list">
          {config.probes.filter(probe => probe.id === editing).map(probe => <ProbeBindingRow key={probe.id} probe={probe} definition={definitions.find(item => item.id === probe.definition_id)}
            open onToggle={() => setGlobalOpen(false)} onUpdate={patch => update(probe.id, patch)} onRemove={() => { remove(probe.id); setGlobalOpen(false); }} onError={onError}
            modelPolicy={modelPolicy} onModelSettings={onModelSettings} />)}
        </div>
      </details>}
      {tab === "apply" && <section className="probe-new-section">
        <div className="wb-view-toolbar"><strong>应用新探针</strong></div>
        {!adding ? <button onClick={startAdding}>添加探针绑定</button> : <div className="probe-binding-form">
          <div className="wb-form compact">
            <label>作用范围<select aria-label="探针绑定范围" value={range} onChange={(event) => setRange(event.target.value as typeof range)}>
              <option value="selection" disabled={!targets.length}>当前选择 ({targets.length})</option>
              <option value="project">整个项目</option>
            </select></label>
            <label>功能用途<select aria-label="新探针用途" value={purpose} onChange={(event) => setPurpose(event.target.value)}>
              <option value="all">全部用途</option>{Object.entries(purposeNames).map(([id, label]) => <option key={id} value={id}>{label}</option>)}
            </select></label>
            <input type="search" aria-label="搜索兼容探针" placeholder="搜索兼容探针" value={query} onChange={(event) => setQuery(event.target.value)} />
            <label>探针<select aria-label="探针类型" value={definition?.id ?? ""} disabled={!compatible.length} onChange={(event) => {
              const chosen = compatible.find((item) => item.id === event.target.value);
              if (chosen) { setType(chosen.id); setParams(defaultsFor(chosen)); setRoles({}); }
            }}>
              {!compatible.length && <option value="">此范围没有兼容探针</option>}
              {Object.entries(purposeNames).map(([id, label]) => {
                const choices = compatible.filter((item) => item.capability === id);
                if (!choices.length) return null;
                return purpose !== "all" ? choices.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)
                  : <optgroup label={label} key={id}>{choices.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</optgroup>;
              })}
            </select></label>
            {range === "selection" && <div className="probe-target-summary">{targets.slice(0, 8).map((target) => <span key={selectionKey(target)}>{probeTargetLabel(target, analysis)}</span>)}{targets.length > 8 && <span>另 {targets.length - 8} 个对象</span>}</div>}
            {definition?.input_mode === "joint" && definition.input_roles.map((role, index) => {
              const eligible = roleTargets.filter((target) => role.supported_targets.includes(target.kind));
              return <label key={role.name}>{({ left: "左侧输入", right: "右侧输入", input: "输入" } as Record<string, string>)[role.name] || role.name}
                <select aria-label={"输入角色 " + role.name} value={roles[role.name] ?? (eligible[index] ? selectionKey(eligible[index]) : "")}
                  onChange={(event) => setRoles({ ...roles, [role.name]: event.target.value })}>
                  <option value="">选择输入</option>{eligible.map((target) => <option key={selectionKey(target)} value={selectionKey(target)}>{probeTargetLabel(target, analysis)}{target.snapshot_id ? " · 已保存" : " · 下次运行"}</option>)}
                </select>
              </label>;
            })}
          </div>
          {templates.some((template) => template.definition_id === definition?.id) && <select aria-label="探针参数模板" onChange={(event) => {
            const template = templates.find((item) => item.id === event.target.value);
            if (template && definition) setParams({ ...defaultsFor(definition), ...template.parameters });
          }}><option value="">选择参数预设</option>{templates.filter((template) => template.definition_id === definition?.id).map((template) => <option key={template.id} value={template.id}>{template.label}</option>)}</select>}
          {definition && <ParameterForm key={definition.id} schema={definition.parameter_schema} value={params} onChange={setParams} modelPolicy={modelPolicy} onModelSettings={onModelSettings} />}
          <button className="wb-primary" aria-label="确认添加探针" disabled={!definition || range === "selection" && !targets.length} onClick={add}>保存绑定</button>
        </div>}
      </section>}
      {tab === "templates" && <section className="probe-new-section wb-form compact">
        <label>作用范围<select aria-label="模板应用范围" value={range === "project" ? "project" : "selection"} onChange={e => setRange(e.target.value as "project" | "selection")}>
          <option value="selection" disabled={!targets.length}>当前选择 ({targets.length})</option><option value="project">整个项目</option>
        </select></label>
        <label>探针模板<select aria-label="应用探针模板" value={templateId || config.probe_templates[0]?.id || ""} onChange={e => setTemplateId(e.target.value)}>
          {!config.probe_templates.length && <option value="">请先在探针库创建模板</option>}
          {config.probe_templates.map(t => <option key={t.id} value={t.id}>{t.label} · {t.members.length} 个探针</option>)}
        </select></label>
        {(config.probe_templates.find(t => t.id === templateId) ?? config.probe_templates[0])?.members.map(m => <div key={m.id} className="template-member-preview">{definitions.find(d => d.id === m.definition_id)?.label ?? m.definition_id}</div>)}
        <button className="wb-primary" disabled={!config.probe_templates.length || range !== "project" && !targets.length} onClick={() => {
          const template = config.probe_templates.find(t => t.id === templateId) ?? config.probe_templates[0];
          if (!template) return;
          try {
            const selector = probeScopeSelector(analysis, null, targets, range === "project" ? "project" : "selection");
            onChange(applyProbeTemplate(config, template, definitions, selector, undefined, scopeProbeTargets(analysis, selector)));
            setTab("inspect");
          }
          catch (error) { onError((error as Error).message); }
        }}>应用模板</button>
      </section>}
      {tab === "inspect" && manualProbe && <details className="probe-manual-entry"><summary>记录判断</summary><div className="wb-form compact">
        <textarea aria-label="人工判断记录" value={note} onChange={(event) => setNote(event.target.value)} />
        <select aria-label="人工判断结果" value={verdict} onChange={(event) => setVerdict(event.target.value)}><option value="unknown">待判断</option><option value="pass">通过</option><option value="fail">失败</option></select>
        <button disabled={!analysis || !note} onClick={() => void wb.manual({ instance_id: manualProbe.id, analysis_id: analysis!.id, snapshot_id: selected?.id, note, verdict }).then(onRecorded).catch((error) => onError(error.message))}>记录判断</button>
      </div></details>}
    </div>
  );
}
