import {useEffect,useRef,useState} from 'react';
import type {ObservationEvent} from './generated';
import {client} from './client';
import {useOperation} from './operations';
export function RunTimeline({runId,live,onSnapshot}:{runId:string;live:ObservationEvent[];onSnapshot:(id:string)=>void}){
  const [open,setOpen]=useState(false),[events,setEvents]=useState<ObservationEvent[]>([]),[cursor,setCursor]=useState(0),[top,setTop]=useState(0),[kind,setKind]=useState(''),[block,setBlock]=useState(''),[after,setAfter]=useState('');const loading=useOperation('timeline:'+runId),scroll=useRef<HTMLDivElement>(null);
  useEffect(()=>{setEvents([]);setCursor(0);setTop(0);},[runId]);
  const load=()=>void loading.run(signal=>client.eventPage(runId,cursor,signal)).then(page=>{if(page){setEvents(page);setCursor(page.at(-1)?.sequence||cursor);setTop(0);if(scroll.current)scroll.current.scrollTop=0;}});
  const raw=open?events:live.slice(-64);const shown=raw.filter(e=>(!kind||e.kind.startsWith(kind))&&(!block||JSON.stringify(e.payload).includes(block))&&(!after||e.timestamp>=after));
  const start=Math.max(0,Math.floor(top/32)-2);
  return <section className="ri-timeline"><header><h2>时间线</h2><button disabled={!runId} onClick={()=>{setOpen(value=>!value);setTop(0);if(scroll.current)scroll.current.scrollTop=0;if(!open&&!events.length)load();}}>{open?'最近事件':'读取历史事件'}</button></header><div className="event-filters"><select aria-label="事件类型" value={kind} onChange={e=>setKind(e.target.value)}><option value="">全部类型</option>{['value','operation','control','probe','run'].map(k=><option key={k}>{k}</option>)}</select><input aria-label="事件块" placeholder="块名称或 ID" value={block} onChange={e=>setBlock(e.target.value)}/><input aria-label="事件起始时间" placeholder="ISO 时间" value={after} onChange={e=>setAfter(e.target.value)}/></div><div className="ri-timeline-scroll" ref={scroll} onScroll={e=>setTop(e.currentTarget.scrollTop)}>
    <div style={{height:shown.length*32,position:'relative'}}>{shown.slice(start,start+14).map((event,index)=><div className="ri-event" style={{position:'absolute',top:(start+index)*32,height:32,width:'100%'}} key={event.sequence}><small>{event.sequence}</small><span>{event.kind}{event.kind==='control.summary'?' · 累计摘要':event.kind==='control.details'?' · 有界明细':''}</span>{event.snapshot_id&&<button onClick={()=>onSnapshot(event.snapshot_id!)}>查看此版本</button>}</div>)}</div>
    {!shown.length&&<p className="ri-empty">事件保存在本地，历史按页读取。</p>}
  </div>{open&&<button onClick={load} disabled={loading.status==='running'}>下一页事件</button>}{loading.error&&<p role="alert">{loading.error}</p>}</section>;
}
