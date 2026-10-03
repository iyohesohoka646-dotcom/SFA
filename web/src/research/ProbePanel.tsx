import {useEffect,useState} from 'react';
import type {ProbeResult,ProbeSpec,SnapshotRef} from './generated';
import {client} from './client';
import {useOperation} from './operations';
export const newProbe=(id:string,kind='finite',binding='*'):ProbeSpec=>({id,kind,binding,enabled:true,parameters:{},policy:'continue',budget_ms:50,protocol_version:1,target_keys:null,excluded_keys:[]});
export function ProbePanel({snapshot,results,definitions,onSave}:{snapshot?:SnapshotRef;results:ProbeResult[];definitions:ProbeSpec[];onSave:(probes:ProbeSpec[])=>Promise<void>}){
  const [editing,setEditing]=useState(false),[kind,setKind]=useState('finite'),[policy,setPolicy]=useState<ProbeSpec['policy']>('continue'),[parameters,setParameters]=useState('{}'),[types,setTypes]=useState<{kind:string;label:string;expensive:boolean}[]>([]),[preview,setPreview]=useState<ProbeResult>(),[notice,setNotice]=useState('');
  const operation=useOperation('probe-preview'),saving=useOperation('probe-save');
  useEffect(()=>{void client.probeTypes().then(setTypes).catch(error=>setNotice(error.message));},[]);
  const spec=()=>({...newProbe('probe-'+crypto.randomUUID(),kind,snapshot?.name||'*'),policy,parameters:JSON.parse(parameters)});
  return <section className="ri-probes"><header><h2>探针</h2><button onClick={()=>setEditing(value=>!value)} disabled={!snapshot}>添加探针</button></header><div data-testid="probe-results" className="ri-probe-results">
    {!results.length?<p className="ri-fidelity">此版本没有探针结果。</p>:results.map((result,index)=><div key={result.probe_id+'-'+index} className={'ri-probe-result '+result.status}><strong>{result.status}</strong><span>{result.message}</span><small>{result.fidelity} · {result.duration_ms.toFixed(2)} ms</small></div>)}
    </div><details><summary>已定义 {definitions.length} 个探针</summary>{definitions.map(probe=><div className="ri-probe-definition" key={probe.id}><code>{probe.binding} · {probe.kind}</code><button onClick={()=>void saving.run(async()=>{await onSave(definitions.filter(item=>item.id!==probe.id));})}>移除</button></div>)}</details>
    {editing&&<form onSubmit={e=>{e.preventDefault();void saving.run(async()=>{const configured=spec();await onSave([...definitions,configured]);setNotice('探针已保存，应用至后续运行。');setEditing(false);});}}>
      <label>探针种类<select aria-label="探针种类" value={kind} onChange={e=>setKind(e.target.value)}>{types.map(type=><option key={type.kind} value={type.kind}>{type.label}{type.expensive?'（昂贵，需显式授权）':''}</option>)}</select></label>
      <label>失败策略<select aria-label="失败策略" value={policy} onChange={e=>setPolicy(e.target.value as ProbeSpec['policy'])}><option value="continue">记录并继续</option><option value="pause">暂停</option><option value="cancel">取消</option></select></label>
      <label>JSON 参数<textarea aria-label="探针参数" value={parameters} onChange={e=>setParameters(e.target.value)} rows={3}/></label>
      <div className="ri-form-actions"><button type="button" disabled={!snapshot||operation.status==='running'} onClick={()=>void operation.run(signal=>client.preview(snapshot!.id,spec(),signal)).then(result=>{if(result)setPreview(result);})}>预演探针</button><button className="ri-primary" disabled={saving.status==='running'}>保存探针定义</button></div>
      {operation.status==='running'&&<button type="button" onClick={operation.cancel}>取消预演</button>}
      {preview&&<p data-testid="probe-preview" role="status">{preview.status} · {preview.fidelity} · {preview.message}</p>}
    </form>}
    {(operation.error||saving.error)&&<p role="alert">{operation.error||saving.error}</p>}{notice&&<p role="status">{notice}</p>}
  </section>;
}
