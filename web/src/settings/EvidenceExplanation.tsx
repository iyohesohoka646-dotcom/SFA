import {useEffect,useRef,useState} from 'react';
import {models} from './client';
import type {PublicProviderProfile} from './client';
import {request} from '../research/client';
import {useOperation} from '../research/operations';
import type {Explanation,OperationRecord} from '../research/generated';

export function EvidenceExplanation({operation}:{operation:OperationRecord}){
  const [profiles,setProfiles]=useState<PublicProviderProfile[]>([]),[provider,setProvider]=useState('offline'),[model,setModel]=useState('rules'),[samples,setSamples]=useState(false);
  const [context,setContext]=useState<unknown>(),[reply,setReply]=useState<Explanation>();
  const scope=useOperation('explanation-scope-'+operation.id),explanation=useOperation('explanation-'+operation.id),cancel=useOperation('explanation-cancel');
  const token=useRef('');
  useEffect(()=>{const abort=new AbortController();void models.list(abort.signal).then(setProfiles).catch(()=>{});return()=>abort.abort();},[operation.id]);
  useEffect(()=>{setContext(undefined);setReply(undefined);},[operation.id,samples]);
  const select=(id:string)=>{explanation.cancel();setReply(undefined);setProvider(id);setModel(profiles.find(p=>p.id===id)?.default_model||'');};
  const preview=()=>void scope.run(signal=>request<unknown>(`/operations/${encodeURIComponent(operation.id)}/explanation-context?include_sample=${samples}`,{signal})).then(value=>{if(value)setContext(value);});
  const generate=()=>{token.current=crypto.randomUUID();setReply(undefined);void explanation.run(signal=>request<Explanation>(`/operations/${encodeURIComponent(operation.id)}/explain`,{method:'POST',body:{provider_id:provider,model,include_sample:samples,operation_id:token.current},signal})).then(value=>{if(value)setReply(value);});};
  return <details className="ri-explanation"><summary>自然语言解释与发送范围</summary>
    <p className="ri-fidelity">使用选中表达式、输入输出形状与脱敏摘要。样例默认关闭；完整数据不发送。离线规则不访问模型服务。</p>
    <label>服务<select aria-label="解释模型服务" value={provider} onChange={e=>select(e.target.value)}><option value="offline">offline · 数学规则</option>{profiles.filter(p=>p.id!=='offline').map(p=><option key={p.id} value={p.id}>{p.id}</option>)}</select></label>
    <label>模型 ID<input aria-label="解释模型 ID" value={model} onChange={e=>setModel(e.target.value)} list="explanation-models"/></label>
    <datalist id="explanation-models">{profiles.find(p=>p.id===provider)?.models.slice(0,500).map(id=><option key={id} value={id}/>)}</datalist>
    <label><input type="checkbox" checked={samples} onChange={e=>setSamples(e.target.checked)} aria-label="包含脱敏样例"/> 包含脱敏样例</label>
    <div className="ri-model-actions"><button onClick={preview} disabled={scope.status==='running'}>查看解释发送内容</button><button onClick={generate} disabled={!model||explanation.status==='running'}>{provider==='offline'?'生成离线解释':'生成模型解释'}</button>
      {explanation.status==='running'&&<button onClick={()=>void cancel.run(async()=>{await models.cancel(token.current);explanation.cancel();})} disabled={cancel.status==='running'}>取消解释请求</button>}</div>
    <small data-testid="explanation-status">{explanation.status}</small>
    {context!==undefined&&<pre className="ri-context" data-testid="explanation-context">{JSON.stringify(context,null,2)}</pre>}
    {reply&&<div data-testid="model-explanation"><strong>{reply.origin==='model'?'模型文本尚未人工验证':'数学规则解释'}</strong><p>{reply.text}</p><small>{reply.uncertainty.join('；')} · 用量 {JSON.stringify(reply.usage)} · 发送范围 {JSON.stringify(reply.sent_scope)}</small><details><summary>引用的运行证据</summary><pre>{reply.evidence.join('\n')}</pre></details></div>}
    {[scope.error,explanation.error,cancel.error].filter(Boolean).map((error,index)=><p key={index} role="alert">{error}</p>)}
  </details>;
}
