import {useEffect,useState} from 'react';
import type {ProviderProfile} from './client';
import {ModelPicker} from './ModelPicker';

export function ProviderForm({profile,available,saving,onChange,onSave}:{profile:ProviderProfile;available:boolean;saving:boolean;onChange:(profile:ProviderProfile)=>void;onSave:(profile:ProviderProfile,secret?:string)=>void}){
  const [mode,setMode]=useState('none'),[environment,setEnvironment]=useState(''),[secret,setSecret]=useState('');
  useEffect(()=>{setMode(profile.credential_ref?.startsWith('env:')?'environment':profile.credential_ref?'keep':'none');setEnvironment(profile.credential_ref?.startsWith('env:')?profile.credential_ref.slice(4):'');setSecret('');},[profile.id,profile.credential_ref]);
  const change=(field:keyof ProviderProfile,value:unknown)=>onChange({...profile,[field]:value});
  return <form className="ri-provider-form" onSubmit={e=>{e.preventDefault();const configured={...profile,credential_ref:mode==='environment'?'env:'+environment:mode==='keep'?profile.credential_ref:null};onSave(configured,mode==='keyring'?secret:undefined);}}>
    <label>模型服务 ID<input aria-label="模型服务 ID" required maxLength={64} value={profile.id} onChange={e=>change('id',e.target.value)} placeholder="例如 deepseek 或 local"/></label>
    <label>模型协议<select aria-label="模型协议" value={profile.protocol} onChange={e=>change('protocol',e.target.value)}><option value="openai-compatible">OpenAI-compatible · DeepSeek／本地服务</option><option value="anthropic">Anthropic Messages</option><option value="offline">离线规则</option></select></label>
    {profile.protocol!=='offline'&&<><label>服务地址<input aria-label="服务地址" required value={profile.base_url} onChange={e=>change('base_url',e.target.value)} placeholder="https://api.deepseek.com/v1"/></label>
      <label>凭据方式<select aria-label="凭据方式" value={mode} onChange={e=>setMode(e.target.value)}><option value="none">无需密钥的本地服务</option><option value="environment">环境变量引用</option><option value="keyring" disabled={!available}>系统凭据库{available?'':'（不可用）'}</option>{profile.credential_ref&&<option value="keep">保留当前凭据引用</option>}</select></label>
      {mode==='environment'&&<label>凭据环境变量<input aria-label="凭据环境变量" required value={environment} onChange={e=>setEnvironment(e.target.value)} placeholder="填变量名，密钥不填在这里"/></label>}
      {mode==='keyring'&&<label>模型密钥<input type="password" autoComplete="new-password" aria-label="模型密钥" required value={secret} onChange={e=>setSecret(e.target.value)}/></label>}
      {!available&&<p className="ri-fidelity">系统凭据库不可用。可使用已有环境变量引用；软件不会保存明文密钥。</p>}
      <ModelPicker models={profile.models} value={profile.default_model} onChange={value=>change('default_model',value)}/>
      <label>请求超时（秒）<input type="number" aria-label="模型超时" min={1} max={300} value={profile.timeout_seconds} onChange={e=>change('timeout_seconds',Number(e.target.value))}/></label>
    </>}
    <button className="ri-primary" disabled={saving||profile.id==='offline'}>{saving?'保存中…':'保存模型配置'}</button>
  </form>;
}
