import {headers, ApiError} from '../api';
import type {SnapshotRef, OperationRecord, ObservationEvent, ProbeSpec} from './generated';
export interface RunRecord {id:string; name:string; script:string; interpreter:string; source_digest:string; started:string; finished:string|null;
  status:string; summary:Record<string,unknown>; environment:Record<string,unknown>; owner:number;}
export interface Bootstrap {run:RunRecord;cursor:number;binding_count:number;snapshots:SnapshotRef[];operations:OperationRecord[];probe_events:ObservationEvent[];}
export interface Experiment {name:string;script:string;interpreter:string;arguments:string[];capture:Record<string,unknown>;annotations:Record<string,unknown>;adapters:string[];probes:ProbeSpec[];}
export interface ResearchInfo {root:string;interpreter:string;examples:{id:string;name:string;script:string}[];}
export interface SourceFile {path:string;digest:string;code:string;}
export async function request<T>(path:string, options:{method?:string;body?:unknown;signal?:AbortSignal}={}):Promise<T>{
  let response:Response;
  try{response=await fetch('/api/v1/research'+path,{method:options.method||'GET', headers:headers(),signal:options.signal,
    body:options.body===undefined?undefined:JSON.stringify(options.body)});}
  catch(error){if(options.signal?.aborted)throw error;throw new ApiError('本地服务已断开，请重新打开工作台。');}
  if(!response.ok){const body=await response.json().catch(()=>({detail:response.statusText}));throw new ApiError(typeof body.detail==='string'?body.detail:JSON.stringify(body.detail),response.status);}
  return response.json();
}
export const client={
  runs:(signal?:AbortSignal)=>request<RunRecord[]>('/runs',{signal}),
  info:(signal?:AbortSignal)=>request<ResearchInfo>('/info',{signal}),
  bootstrap:(id:string,signal?:AbortSignal)=>request<Bootstrap>(`/runs/${encodeURIComponent(id)}/bootstrap`,{signal}),
  snapshot:(id:string,signal?:AbortSignal)=>request<SnapshotRef>(`/snapshots/${encodeURIComponent(id)}`,{signal}),
  source:(id:string,signal?:AbortSignal)=>request<SourceFile>(`/runs/${encodeURIComponent(id)}/source`,{signal}),
  sourcePreview:(path:string,signal?:AbortSignal)=>request<SourceFile>('/source-preview',{method:'POST',body:{path},signal}),
  experiment:(signal?:AbortSignal)=>request<Experiment|null>('/experiment',{signal}),
  saveExperiment:(definition:Experiment,signal?:AbortSignal)=>request<Experiment>('/experiment',{method:'PUT',body:definition,signal}),
  history:(runId:string,binding:string,before?:number,signal?:AbortSignal)=>request<SnapshotRef[]>(`/runs/${encodeURIComponent(runId)}/history?binding=${encodeURIComponent(binding)}${before?'&before='+before:''}`,{signal}),
  preview:(id:string,probe:ProbeSpec,signal?:AbortSignal)=>request<import('./generated').ProbeResult>(`/snapshots/${encodeURIComponent(id)}/probe-preview`,{method:'POST',body:probe,signal}),
  probeTypes:(signal?:AbortSignal)=>request<{kind:string;label:string;expensive:boolean}[]>('/probe-types',{signal}),
  eventPage:(id:string,after=0,signal?:AbortSignal)=>request<ObservationEvent[]>(`/runs/${encodeURIComponent(id)}/event-page?after=${after}&limit=200`,{signal}),
  slice:(id:string,selectors:Record<string,number>[],signal?:AbortSignal)=>request<{available:boolean;values?:unknown[][];shape?:number[];reason?:string}>(`/snapshots/${encodeURIComponent(id)}/slice`,{method:'POST',body:{selectors},signal}),
  start:(body:{script:string;interpreter:string;mode:string;arguments?:string[];probes?:ProbeSpec[];adapters?:string[]},signal?:AbortSignal)=>request<{run_id:string}>('/runs',{method:'POST',body,signal}),
  control:(id:string,action:'cancel'|'resume',signal?:AbortSignal)=>request<RunRecord>(`/runs/${encodeURIComponent(id)}/${action}`,{method:'POST',signal}),
};

export async function downloadReport(runId:string){
  const response=await fetch(`/api/v1/research/runs/${encodeURIComponent(runId)}/export/html`,{headers:headers()});
  if(!response.ok)throw new Error('报告导出失败，请重试。');
  const url=URL.createObjectURL(await response.blob()),link=document.createElement('a');link.href=url;link.download=`research-${runId}.html`;link.click();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
}

export async function subscribeRun(id:string,cursor:number,receive:(event:ObservationEvent)=>void,signal:AbortSignal){
  while(!signal.aborted){
    const response=await fetch(`/api/v1/research/runs/${encodeURIComponent(id)}/events?after=${cursor}`,{headers:{...headers(),'Last-Event-ID':String(cursor)},signal});
    if(!response.ok || !response.body)throw new ApiError('运行事件不可用，请重新连接。',response.status);
    const reader=response.body.getReader(),decoder=new TextDecoder();let buffer='';
    try{
      while(!signal.aborted){
        const {done,value}=await reader.read();if(done)return;
        buffer+=decoder.decode(value,{stream:true});
        if(buffer.length>3*1024*1024)throw new Error('运行事件超出接收预算。');
        const blocks=buffer.split('\n\n');buffer=blocks.pop()||'';
        for(const block of blocks){
          const line=block.split('\n').find(s=>s.startsWith('data: '));if(!line)continue;
          const event=JSON.parse(line.slice(6)) as ObservationEvent;
          if(event.sequence>cursor){receive(event);cursor=event.sequence;}
          if(event.kind==='run.finished')return;
        }
      }
    } finally {await reader.cancel().catch(()=>{});reader.releaseLock();}
  }
}
