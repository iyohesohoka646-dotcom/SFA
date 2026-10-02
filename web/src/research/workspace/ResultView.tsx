import {useEffect,useState} from 'react';
import type {ProbeOutput,CodeProposal} from './generated';
import {wb} from './WorkbenchClient';
import {ArtifactView} from './ArtifactView';

export function ResultView({id,onData,onProposal,onError}:{id:string;onData:(id:string)=>void;onProposal:(p:CodeProposal)=>void;onError:(s:string)=>void}){
 const [result,setResult]=useState<ProbeOutput>(),[retained,setRetained]=useState(true);
 useEffect(()=>{const abort=new AbortController();void wb.output(id).then(r=>{if(!abort.signal.aborted)setResult(r);}).catch(e=>onError(e.message));return()=>abort.abort();},[id]);
 if(!result)return <div className="wb-empty">读取探针结果…</div>;
 const summaries=Array.isArray(result.data.control_summaries)?result.data.control_summaries as Record<string,unknown>[]:[];
 const derived=typeof result.data.derived_id==='string'?result.data.derived_id:undefined;
 return <div className="wb-full-pane"><div className="wb-view-toolbar"><strong>{result.definition_id}</strong><span className={'wb-kind '+result.status}>{result.status}</span>{result.snapshot_id&&<button onClick={()=>onData(result.snapshot_id!)}>打开数据</button>}{derived&&<><button onClick={()=>void wb.derivedProposal(derived).then(onProposal).catch(e=>onError(e.message))}>生成代码提案</button><button onClick={()=>void wb.derivedRetention(derived,!retained).then(()=>setRetained(!retained)).catch(e=>onError(e.message))}>{retained?'释放保留':'保留分析'}</button></>}</div><div className="wb-scroll"><p>{result.message}</p><small>{result.execution} · {result.provenance} · {result.fidelity} · {result.duration_ms.toFixed(2)} ms</small><div className="result-targets">{result.targets.map(t=><button key={t.snapshot_id??t.logical_key} disabled={!t.snapshot_id} onClick={()=>onData(t.snapshot_id!)}>{t.logical_key.split('::').at(-1)}{t.snapshot_id?' · '+t.snapshot_id.slice(0,6):''}</button>)}</div>
 {result.artifact_id&&<ArtifactView id={result.artifact_id}/>}
 {summaries.length>0&&<table className="wb-catalog"><thead><tr><th>控制块</th><th>真 / 假</th><th>循环进入 / 调用</th><th>完整性</th></tr></thead><tbody>{summaries.map(s=><tr key={String(s.node_id)}><td>{String(s.kind)} · {String((s.source as {line?:number})?.line??'')}</td><td>{String(s.true_count)} / {String(s.false_count)}</td><td>{String(s.kind==='function'?s.activations:s.body_entries)}</td><td>{s.complete?'完整':'记录不完整'}</td></tr>)}</tbody></table>}
 {Object.entries(result.data).filter(([k,v])=>typeof v==='number'||typeof v==='boolean').length>0&&<dl className="result-metrics">{Object.entries(result.data).filter(([k,v])=>typeof v==='number'||typeof v==='boolean').map(([k,v])=><div key={k}><dt>{({calls:'调用次数',total_ms:'总耗时 ms',maximum_ms:'最长调用 ms',complete:'记录完整',complete_inputs:'完整输入',numeric_conclusion:'数值结论'} as Record<string,string>)[k]??k}</dt><dd>{typeof v==='number'?v.toLocaleString(undefined,{maximumFractionDigits:3}):v?'是':'否'}</dd></div>)}</dl>}
 <details><summary>证据与参数</summary><pre className="wb-json">{JSON.stringify(result.data,null,2)}</pre></details></div></div>;
}
