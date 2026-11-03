import { useState } from "react";
import type { ProbeTemplate, ProbeTemplateMember, ProbeDefinition, WorkbenchConfig } from "./generated";
import { ParameterForm } from "./ParameterForm";
import { initialProbeParameters } from "./probe-configuration";

export function ProbeTemplateLibrary({ config, definitions, onChange, onSave, onError, onModelSettings }: {
  config: WorkbenchConfig; definitions: ProbeDefinition[]; onChange: (c: WorkbenchConfig) => void;
  onSave: () => Promise<unknown>; onError: (s: string) => void; onModelSettings?: () => void;
}) {
  const [draft, setDraft] = useState<Omit<ProbeTemplate, "members"> & { members: ProbeTemplateMember[] }>(), [editingMember, setEditingMember] = useState<string>(), [choice, setChoice] = useState("view.table"), [notice, setNotice] = useState("");
  const choices = definitions.filter(d => d.input_mode !== "joint");
  const save = () => {
    if (!draft?.label.trim() || !draft.members.length) { onError("填写模板名称，并添加至少一个探针"); return; }
    onChange({ ...config, probe_templates: [...config.probe_templates.filter(t => t.id !== draft.id), { ...draft, label: draft.label.trim(), version: draft.version + 1 } as ProbeTemplate] });
    void onSave().then(() => { setDraft(undefined); setNotice("模板已保存，已有绑定保持原参数。"); }).catch(e => onError(e.message));
  };
  return <div className="probe-template-library">
    <div className="wb-view-toolbar"><strong>探针模板</strong><button aria-label="新建探针模板" onClick={() => { setDraft({ id: crypto.randomUUID(), label: "", version: 1, members: [] }); setNotice(""); }}>新建模板</button></div>
    <div className="template-list">{config.probe_templates.map(template => <div key={template.id} className="template-row">
      <span><strong>{template.label}</strong><small>{template.members.map(m => definitions.find(d => d.id === m.definition_id)?.label ?? m.definition_id).join(" · ")}</small></span>
      <button aria-label={"编辑模板 " + template.label} onClick={() => { setDraft(structuredClone(template)); setEditingMember(undefined); setNotice(""); }}>编辑</button>
      <button aria-label={"删除模板 " + template.label} onClick={() => {
        onChange({ ...config, probe_templates: config.probe_templates.filter(t => t.id !== template.id) });
        void onSave().then(() => setNotice("模板已删除，已应用的绑定仍可独立管理。")).catch(e => onError(e.message));
      }}>删除</button>
    </div>)}</div>
    {draft && <div className="template-editor wb-form compact">
      <label>模板名称<input aria-label="模板名称" maxLength={128} value={draft.label} onChange={e => setDraft({ ...draft, label: e.target.value })} /></label>
      {draft.members.map(member => {
        const d = definitions.find(d => d.id === member.definition_id);
        return <section className="template-member" key={member.id}>
          <div><button aria-expanded={editingMember === member.id} onClick={() => setEditingMember(editingMember === member.id ? undefined : member.id)}>{d?.label ?? member.definition_id}</button>
            <button aria-label={"移除模板成员 " + (d?.label ?? member.definition_id)} onClick={() => setDraft({ ...draft, members: draft.members.filter(m => m.id !== member.id) })}>移除</button></div>
          {editingMember === member.id && d && <ParameterForm schema={d.parameter_schema} value={initialProbeParameters(d, member.parameters)}
            onChange={parameters => setDraft({ ...draft, members: draft.members.map(m => m.id === member.id ? { ...m, parameters } : m) })}
            modelPolicy={config.harness.find(p => p.role === "probe")} onModelSettings={onModelSettings} />}
        </section>;
      })}
      <div className="template-member-add"><select aria-label="模板成员探针" value={choice} onChange={e => setChoice(e.target.value)}>{choices.map(d => <option value={d.id} key={d.id}>{d.label}</option>)}</select>
        <button disabled={draft.members.length >= 32} onClick={() => { const d = choices.find(d => d.id === choice); if (!d) return;
          const id = crypto.randomUUID(); setDraft({ ...draft, members: [...draft.members, { id, definition_id: d.id, parameters: initialProbeParameters(d, config.probe_defaults[d.id]), enabled: true, budget_ms: d.tool_id ? 30000 : 5000 }] }); setEditingMember(id);
        }}>加入模板</button></div>
      <div className="template-actions"><button className="wb-primary" disabled={!draft.label.trim() || !draft.members.length} onClick={save}>保存模板</button><button onClick={() => setDraft(undefined)}>取消</button></div>
    </div>}
    {notice && <p role="status">{notice}</p>}
  </div>;
}
