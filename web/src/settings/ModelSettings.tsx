import {useEffect,useRef,useState} from 'react';
import {models,newProfile} from './client';
import type {ConnectionResult,ProviderProfile,PublicProviderProfile} from './client';
import {ProviderForm} from './ProviderForm';
import {useOperation} from '../research/operations';
import './settings.css';

export function ModelSettings({visible,onClose}:{visible:boolean;onClose:()=>void}){
  const [profiles,setProfiles]=useState<PublicProviderProfile[]>([]),[draft,setDraft]=useState<ProviderProfile>(()=>({...newProfile(),id:'offline',protocol:'offline',base_url:'',models:['rules'],default_model:'rules'}));
  const [available,setAvailable]=useState(false),[result,setResult]=useState<ConnectionResult>(),[notice,setNotice]=useState('');
  const loading=useOperation('models-list'),saving=useOperation('models-save'),connection=useOperation('model-connection'),cancelling=useOperation('model-cancel');const token=useRef('');
  useEffect(()=>{if(visible)void loading.run(async signal=>{const [list,vault]=await Promise.all([models.list(signal),models.vault(signal)]);return {list,vault};}).then(value=>{if(value){setProfiles(value.list);setAvailable(value.vault.available);}});},[visible,loading.run]);
  const choose=(profile:PublicProviderProfile)=>{if(connection.status==='running')void models.cancel(token.current);connection.cancel();setResult(undefined);setNotice('');const {configured:_,...fields}=profile;setDraft(fields);};
  const save=(profile:ProviderProfile,secret?:string)=>void saving.run(signal=>models.save(profile,secret,signal)).then(value=>{if(value){setProfiles(current=>[...current.filter(p=>p.id!==value.id),value]);const {configured:_,...fields}=value;setDraft(fields);setNotice('模型配置已保存。Web、桌面与 CLI 共用此配置。');}});
  const test=(inference:boolean)=>{token.current=crypto.randomUUID();setResult(undefined);void connection.run(signal=>models.test(draft.id,{inference,model:draft.default_model,operation_id:token.current},signal)).then(value=>{if(value){setResult(value);if(value.models.length)setDraft(current=>({...current,models:value.models}));}});};
  const cancel=()=>void cancelling.run(async()=>{const cancelled=await models.cancel(token.current);connection.cancel();setResult({status:'cancelled',operation_id:token.current,message:cancelled.cancelled?'模型请求已取消。':'查看请求已取消；服务任务已结束或尚未启动。',models:[],inference:false,usage:{},duration_ms:0,requests:0});});
  return <aside className="ri-model-settings" hidden={!visible} aria-label="模型设置">
    <header><h2>模型设置</h2><button onClick={onClose} aria-label="关闭模型设置">关闭</button></header><p className="ri-fidelity">基础分析、数据视图和探针在离线模式下可用。模型请求独立执行，可关闭此面板继续查看数据。</p>
    <div className="ri-model-actions"><label>已配置服务<select aria-label="已配置模型服务" value={profiles.some(p=>p.id===draft.id)?draft.id:''} onChange={e=>{const p=profiles.find(p=>p.id===e.target.value);if(p)choose(p);}}><option value="">新服务</option>{profiles.map(p=><option key={p.id} value={p.id}>{p.id} · {p.configured?'已配置凭据／离线':'未配置凭据'}</option>)}</select></label><button onClick={()=>{if(connection.status==='running')void models.cancel(token.current);connection.cancel();setDraft(newProfile());setResult(undefined);setNotice('');}}>新增模型服务</button></div>
    <ProviderForm profile={draft} available={available} saving={saving.status==='running'} onChange={setDraft} onSave={save}/>
    <div className="ri-model-actions"><button disabled={!profiles.some(p=>p.id===draft.id)||connection.status==='running'} onClick={()=>test(false)}>连接测试（不推理）</button><button disabled={!profiles.some(p=>p.id===draft.id)||connection.status==='running'} onClick={()=>test(true)}>推理测试（发送测试文本）</button></div>
    {connection.status==='running'&&<p role="status">正在连接模型… <button onClick={cancel} disabled={cancelling.status==='running'}>取消模型请求</button></p>}
    {result&&<div data-testid="connection-result" role="status"><strong>{result.status}</strong><p>{result.message}</p><small>{result.duration_ms.toFixed(1)} ms · {result.requests} 次请求 · {JSON.stringify(result.usage)}</small></div>}
    {notice&&<p role="status">{notice}</p>}{[loading.error,saving.error,connection.error,cancelling.error].filter(Boolean).map((error,index)=><p key={index} role="alert">{error}</p>)}
  </aside>;
}
