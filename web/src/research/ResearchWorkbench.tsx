import {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {client, subscribeRun} from './client';
import type {ResearchInfo, RunRecord} from './client';
import {applyEvent,createState,indexSnapshot} from './state';
import {localTopology,selectVariable} from './selectors';
import {useOperation} from './operations';
import {VariableList} from './VariableList';
import {ConnectionHelp} from '../components';
import type {ObservationEvent,SnapshotRef} from './generated';
import './research.css';

export default function ResearchWorkbench(){
  const [runs,setRuns]=useState<RunRecord[]>([]),[runId,setRunId]=useState(''),[info,setInfo]=useState<ResearchInfo>();
  const [script,setScript]=useState(''),[interpreter,setInterpreter]=useState(''),[capture,setCapture]=useState('summary');
  const [state,setState]=useState(()=>createState('')),[selected,setSelected]=useState(''),[details,setDetails]=useState<SnapshotRef>();
  const [notice,setNotice]=useState('');const catalog=useOperation('catalog'),bootstrap=useOperation('bootstrap:'+runId),detail=useOperation('detail'),execution=useOperation('execution'),control=useOperation('control');
  const stateRef=useRef(state);stateRef.current=state;
  const refresh=useCallback(()=>catalog.run(signal=>client.runs(signal)).then(records=>{if(records){setRuns(records);setRunId(id=>id||records[0]?.id||'');}}),[catalog.run]);
  useEffect(()=>{void refresh();void client.info().then(value=>{setInfo(value);setInterpreter(value.interpreter);setScript(value.examples[0]?.script||'');}).catch(error=>setNotice(error.message));},[refresh]);
  useEffect(()=>{
    if(!runId)return;
    const connection=new AbortController();let pending:ObservationEvent[]=[],timer:number|undefined;
    setSelected('');setDetails(undefined);setState(createState(runId));
    const publish=()=>{timer=undefined;const batch=pending;pending=[];setState(current=>batch.reduce(applyEvent,current));};
    void bootstrap.run(signal=>client.bootstrap(runId,signal)).then(data=>{
      if(!data || connection.signal.aborted)return;
      let initial=createState(runId);for(const snapshot of data.snapshots)indexSnapshot(initial,snapshot);
      for(const operation of data.operations)initial.operations.set(operation.id,operation);
      for(const event of data.probe_events)initial=applyEvent(initial,event);
      initial.lastSequence=data.cursor;initial.status=data.run.status;initial.omittedBindings=Math.max(0,data.binding_count-data.snapshots.length);
      setState(initial);setSelected(data.snapshots[0]?.binding_id||'');
      if(['queued','running','paused'].includes(data.run.status))void subscribeRun(runId,data.cursor,event=>{
        pending.push(event);if(timer===undefined)timer=window.setTimeout(publish,32);
      },connection.signal).catch(error=>{if(!connection.signal.aborted)setNotice(error.message);});
    });
    return()=>{connection.abort();if(timer!==undefined)clearTimeout(timer);};
  },[runId,bootstrap.run]);
  const view=selectVariable(state,selected),snapshot=view?.snapshot;
  useEffect(()=>{setDetails(undefined);if(snapshot)void detail.run(signal=>client.snapshot(snapshot.id,signal)).then(value=>{if(value)setDetails(value);});return()=>detail.cancel();},[snapshot?.id,detail.run,detail.cancel]);
  const values=useMemo(()=>[...state.latest.values()],[state.lastSequence,state.topologyVersion,state.runId]);
  const topology=useMemo(()=>localTopology(state,selected,80),[state.topologyVersion,state.runId,selected]);
  const run=async()=>{const started=await execution.run(signal=>client.start({script,interpreter,mode:capture},signal));if(started){await refresh();setRunId(started.run_id);}};
  if(catalog.status==='error' && !runs.length)return <ConnectionHelp error={catalog.error||'本地服务无法连接'} retry={()=>void refresh()}/>;
  return <main className="research-app">
    <header className="ri-header"><h1>Scientific Dataflow Inspector</h1><span className="ri-local">本地科研工作台</span><div className="ri-header-actions"><button onClick={()=>{const theme=document.documentElement.dataset.theme==='light'?'dark':'light';document.documentElement.dataset.theme=theme;localStorage.setItem('cdaf-theme',theme);}}>切换主题</button><a href="?legacy=1">旧版架构</a></div></header>
    <section className="ri-toolbar"><label>分析脚本<input aria-label="分析脚本" value={script} onChange={e=>setScript(e.target.value)} placeholder="选择已有 .py 脚本"/></label><label>计算解释器<input aria-label="计算解释器" value={interpreter} onChange={e=>setInterpreter(e.target.value)}/></label>
      <label>采集<select aria-label="采集级别" value={capture} onChange={e=>setCapture(e.target.value)}><option value="metadata">元数据</option><option value="summary">摘要</option><option value="full">完整数据</option></select></label>
      <button className="ri-primary" onClick={()=>void run()} disabled={!script||!interpreter||execution.status==='running'}>{execution.status==='running'?'正在启动…':'运行分析'}</button>
      {['queued','running','paused'].includes(state.status)&&<button onClick={()=>void control.run(signal=>client.control(runId,state.status==='paused'?'resume':'cancel',signal))}>{state.status==='paused'?'继续运行':'取消运行'}</button>}
    </section>
    <div className="ri-runbar"><label>运行记录<select aria-label="运行记录" value={runId} onChange={e=>setRunId(e.target.value)}><option value="">选择运行</option>{runs.map(run=><option key={run.id} value={run.id}>{run.name} · {run.status} · {run.id.slice(0,8)}</option>)}</select></label><span role="status">{bootstrap.status==='running'?'读取记录…':state.status}</span><button onClick={()=>void refresh()}>刷新记录</button></div>
    {[notice,catalog.error,bootstrap.error,detail.error,execution.error,control.error].filter(Boolean).map((error,index)=><p className="ri-error" role="alert" key={index}>{error}</p>)}
    <div className="ri-workspace"><VariableList values={values} selected={selected} onSelect={setSelected}/>
      <section className="ri-data"><header><h2 data-testid="current-variable">{snapshot?.name||'数据观察'}</h2><span>{snapshot?`v${snapshot.version} · ${snapshot.descriptor.backend}`:''}</span></header>
        {snapshot?<><p>{snapshot.descriptor.shape?.join(' × ')||snapshot.descriptor.kind} · {snapshot.descriptor.dtype} · {snapshot.fidelity} · <span data-testid="detail-status">{details?.id===snapshot.id?'详情已就绪':'读取详情…'}</span></p><pre>{JSON.stringify((details||snapshot).sample,null,2)}</pre></>:<p className="ri-empty">打开分析脚本并运行，选择变量查看数据定义与变化。</p>}
      </section>
      <section className="ri-flow"><header><h2>局部运算链</h2><span>{topology.length} 个可见变量</span></header><div className="ri-flow-grid">{topology.map(id=><button data-testid="flow-node" key={id} onClick={()=>setSelected(id)}>{state.latest.get(id)?.name}</button>)}</div></section>
      <section className="ri-source"><header><h2>源码与来源</h2></header><p>{snapshot?.source?.path||info?.root}</p><pre>{snapshot?.source?.code||'选择变量以定位观察来源。'}</pre></section>
    </div><footer className="ri-footer">{state.omittedBindings?`${state.omittedBindings} 个变量未加载；完整证据保存在本地。`:'按需读取历史；图中的关系来自运行证据。'}<span>CLI：cdaf observe analysis.py</span></footer>
  </main>;
}
