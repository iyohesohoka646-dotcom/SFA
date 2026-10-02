import { useState } from 'react';
import type { AnalysisDocument, ProbeDefinition, ProbeInstance, ProbeOutput, WorkbenchConfig } from './generated';
import type { SnapshotRef } from '../generated';
import { Icon } from './icons';
import { wb } from './WorkbenchClient';

export function ProbeInspector({ config, definitions, selected, analysis, outputs, onChange, onSave, onError }: {
  config: WorkbenchConfig; definitions: ProbeDefinition[]; selected?: SnapshotRef; analysis?: AnalysisDocument; outputs: ProbeOutput[];
  onChange: (config: WorkbenchConfig) => void; onSave: () => Promise<unknown>; onError: (message: string) => void;
}) {
  const [adding, setAdding] = useState(false), [type, setType] = useState('view.matrix'), [binding, setBinding] = useState('*');
  const [editing, setEditing] = useState<string>(), [parameters, setParameters] = useState('{}'), [note, setNote] = useState(''), [verdict, setVerdict] = useState('unknown');
  const add = () => {
    const probe: ProbeInstance = { id: crypto.randomUUID(), definition_id: type, binding, enabled: true, parameters: {}, policy: 'continue', budget_ms: 5000 };
    onChange({ ...config, probes: [...config.probes, probe] }); setAdding(false);
  };
  const update = (id: string, patch: Partial<ProbeInstance>) => onChange({ ...config, probes: config.probes.map(p => p.id === id ? { ...p, ...patch } : p) });
  return <div className="wb-inspector">
    <div className="wb-view-toolbar"><strong>探针</strong><button aria-label="添加探针" onClick={() => { setBinding(selected?.name ?? '*'); setAdding(!adding); }}><Icon name="add" /></button><button onClick={() => void onSave().catch(error => onError(error.message))}>保存</button></div>
    {adding && <div className="wb-form compact"><label>类型<select aria-label="探针类型" value={type} onChange={e => setType(e.target.value)}>{definitions.map(d => <option key={d.id} value={d.id}>{d.label} · {d.capability}/{d.execution}</option>)}</select></label>
      <label>绑定<input aria-label="探针绑定" value={binding} onChange={e => setBinding(e.target.value)} list="probe-binding-list" /></label><datalist id="probe-binding-list"><option value="*" />{analysis?.objects.filter(o => o.kind === 'assignment').map(o => <option key={o.id} value={o.name} />)}</datalist>
      <button className="wb-primary" aria-label="确认添加探针" onClick={add}>添加</button></div>}
    <div className="wb-probe-list">{config.probes.map(probe => {
      const definition = definitions.find(d => d.id === probe.definition_id);
      return <div className="wb-probe-row" key={probe.id}>
        <div><input type="checkbox" aria-label={'启用 ' + probe.definition_id} checked={probe.enabled} onChange={e => update(probe.id, { enabled: e.target.checked })} /><button className="wb-probe-name" onClick={() => { setEditing(editing === probe.id ? undefined : probe.id); setParameters(JSON.stringify(probe.parameters, null, 2)); }}>{definition?.label ?? probe.definition_id}</button><button aria-label={'删除 ' + probe.definition_id} onClick={() => onChange({ ...config, probes: config.probes.filter(p => p.id !== probe.id) })}><Icon name="close" size={12} /></button></div>
        <small><span className={'wb-kind ' + definition?.capability}>{definition?.capability ?? 'unknown'}</span> {definition?.execution} · {probe.binding}</small>
        {editing === probe.id && <div className="wb-form compact"><label>绑定<input value={probe.binding} onChange={e => update(probe.id, { binding: e.target.value })} /></label><label>参数<textarea aria-label="探针参数 JSON" value={parameters} onChange={e => setParameters(e.target.value)} onBlur={() => { try { const value = JSON.parse(parameters); if (!value || Array.isArray(value) || typeof value !== 'object') throw new Error(); update(probe.id, { parameters: value }); } catch { onError('参数须为 JSON 对象'); } }} /></label><label>控制<select value={probe.policy} onChange={e => update(probe.id, { policy: e.target.value as ProbeInstance['policy'] })}><option value="continue">继续</option><option value="pause">检查异常时暂停</option><option value="cancel">检查失败时取消</option></select></label><label>预算 ms<input type="number" min="1" max="120000" value={probe.budget_ms} onChange={e => update(probe.id, { budget_ms: Number(e.target.value) })} /></label></div>}
      </div>;
    })}</div>
    <div className="wb-inspector-results"><div className="wb-section-label">{selected ? selected.name + ' · 当前版本结果' : '运行结果'}</div>
      {(selected ? outputs.filter(o => o.snapshot_id === selected.id) : outputs).slice(0, 24).map(output => <div key={output.id} data-testid="probe-output" className={'wb-output ' + output.status}><strong>{output.definition_id}<span>{output.status}</span></strong><small title={output.message}>{output.message}</small><span className="wb-output-meta">{output.execution} · {output.fidelity}</span><details><summary>结果详情</summary><pre className="wb-json">{JSON.stringify(output.data, null, 2)}</pre></details></div>)}
    </div>
    {config.probes.some(p => p.definition_id === 'check.manual') && analysis && <div className="wb-form compact"><label>人工判断<select aria-label="人工判断" value={verdict} onChange={e => setVerdict(e.target.value)}><option value="unknown">待复核</option><option value="pass">通过</option><option value="fail">不通过</option></select></label><textarea aria-label="人工判断说明" value={note} onChange={e => setNote(e.target.value)} /><button onClick={() => void wb.manual({ instance_id: config.probes.find(p => p.definition_id === 'check.manual')!.id, analysis_id: analysis.id, snapshot_id: selected?.id, note, verdict }).then(() => onError('人工结果已记录')).catch(error => onError(error.message))}>记录判断</button></div>}
  </div>;
}
