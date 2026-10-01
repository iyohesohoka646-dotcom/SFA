import {useCallback,useEffect,useMemo,useRef,useState} from 'react';
import {client,subscribeRun,downloadReport} from './client';
import type {ResearchInfo,RunRecord,SourceFile} from './client';
import {applyEvent,createState,indexSnapshot} from './state';
import {selectVariable} from './selectors';
import {useOperation} from './operations';
import {VariableList} from './VariableList';
import {SourcePane} from './SourcePane';
import {MatrixView} from './MatrixView';
import {TableView} from './TableView';
import {LocalFlow,OperationView} from './OperationView';
import {ProbePanel,newProbe} from './ProbePanel';
import {RunTimeline} from './RunTimeline';
import {ConnectionHelp} from '../components';
import {renderers} from './renderer-registry';
import {displayCell} from './matrix-renderer';
import {parseArguments,formatArguments} from './arguments';
import {ModelSettings} from '../settings/ModelSettings';
import type {ObservationEvent,SnapshotRef,ProbeSpec} from './generated';
import './research.css';

export default function ResearchWorkbench(){
  const [runs,setRuns]=useState<RunRecord[]>([]),[runId,setRunId]=useState(''),[info,setInfo]=useState<ResearchInfo>();
  const [script,setScript]=useState(''),[interpreter,setInterpreter]=useState(''),[capture,setCapture]=useState('summary'),[arguments_,setArguments]=useState(''),[adapters,setAdapters]=useState('');
  const [state,setState]=useState(()=>createState('')),[selected,setSelected]=useState(''),[details,setDetails]=useState<SnapshotRef>(),[historyValue,setHistoryValue]=useState<SnapshotRef>();
  const [definitions,setDefinitions]=useState<ProbeSpec[]>([newProbe('default-finite')]),[history,setHistory]=useState<SnapshotRef[]>([]),[showHistory,setShowHistory]=useState(false);
  const [file,setFile]=useState<SourceFile>(),[previewSource,setPreviewSource]=useState<SourceFile>(),[notice,setNotice]=useState('');
  const edited=useRef(new Set<string>());
  const [showModels,setShowModels]=useState(false);
  const markEdit=(event:React.FormEvent<HTMLElement>)=>{const name=(event.target as HTMLElement).getAttribute('aria-label');if(name){edited.current.add(name);if(name==='示例选择'){edited.current.add('分析脚本');edited.current.add('脚本参数');}}};
  const catalog=useOperation('catalog'),bootstrap=useOperation('bootstrap:'+runId),detail=useOperation('detail'),execution=useOperation('execution'),control=useOperation('control'),source=useOperation('source:'+runId),preview=useOperation('source-preview'),historyLoad=useOperation('history:'+runId),exporting=useOperation('export');
  const refresh=useCallback(()=>catalog.run(signal=>client.runs(signal)).then(records=>{if(records){setRuns(records);setRunId(id=>id||records[0]?.id||'');}}),[catalog.run]);
  useEffect(()=>{const pending=new AbortController();void refresh();void Promise.all([client.info(pending.signal),client.experiment(pending.signal)]).then(([value,configured])=>{
    if(pending.signal.aborted)return;setInfo(value);
    if(!edited.current.has('计算解释器'))setInterpreter(configured?.interpreter||value.interpreter);
    if(!edited.current.has('分析脚本'))setScript(configured?.script||value.examples[0]?.script||'');
    if(configured){if(!edited.current.has('probes'))setDefinitions(configured.probes);
      if(!edited.current.has('采集级别'))setCapture(String(configured.capture.level||'summary'));
      if(!edited.current.has('脚本参数'))setArguments(formatArguments(configured.arguments));
      if(!edited.current.has('已安装适配器'))setAdapters(configured.adapters.join(','));}
  }).catch(error=>{if(!pending.signal.aborted)setNotice(error.message);});return()=>pending.abort();},[refresh]);
  useEffect(()=>{
    if(!runId)return;const connection=new AbortController();let pending:ObservationEvent[]=[],timer:number|undefined;
    setSelected('');setDetails(undefined);setHistoryValue(undefined);setHistory([]);setShowHistory(false);setFile(undefined);setPreviewSource(undefined);setState(createState(runId));
    const publish=()=>{timer=undefined;const batch=pending;pending=[];setState(current=>batch.reduce(applyEvent,current));if(batch.some(event=>event.kind==='run.finished'))void refresh();};
    void source.run(signal=>client.source(runId,signal)).then(value=>{if(value&&!connection.signal.aborted)setFile(value);});
    void bootstrap.run(signal=>client.bootstrap(runId,signal)).then(data=>{
      if(!data||connection.signal.aborted)return;let initial=createState(runId);
      for(const snapshot of data.snapshots)indexSnapshot(initial,snapshot);for(const operation of data.operations)initial.operations.set(operation.id,operation);
      for(const event of data.probe_events)initial=applyEvent(initial,event);
      initial.lastSequence=data.cursor;initial.status=data.run.status;initial.summary=data.run.summary;initial.omittedBindings=Math.max(0,data.binding_count-data.snapshots.length);
      setState(initial);setSelected(data.snapshots[0]?.binding_id||'');
      if(['queued','running','paused'].includes(data.run.status))void subscribeRun(runId,data.cursor,event=>{pending.push(event);if(timer===undefined)timer=window.setTimeout(publish,32);},connection.signal).catch(error=>{if(!connection.signal.aborted)setNotice(error.message);});
    });
    return()=>{connection.abort();if(timer!==undefined)clearTimeout(timer);};
  },[runId,bootstrap.run,source.run,refresh]);
  const current=selectVariable(state,selected)?.snapshot,snapshot=historyValue||current;
  useEffect(()=>{setDetails(undefined);if(snapshot)void detail.run(signal=>client.snapshot(snapshot.id,signal)).then(value=>{if(value)setDetails(value);});return()=>detail.cancel();},[snapshot?.id,detail.run,detail.cancel]);
  const values=useMemo(()=>[...state.latest.values()],[state.lastSequence,state.topologyVersion,state.runId]),actual=details?.id===snapshot?.id?details:snapshot;
  const select=useCallback((id:string)=>{setSelected(id);setHistoryValue(undefined);setHistory([]);setShowHistory(false);setPreviewSource(undefined);},[]);
  const loadHistory=()=>{setShowHistory(true);void historyLoad.run(signal=>client.history(runId,selected,undefined,signal)).then(value=>{if(value)setHistory(value);});};
  const showSnapshot=(id:string)=>void historyLoad.run(signal=>client.snapshot(id,signal)).then(value=>{if(value){setSelected(value.binding_id);setHistoryValue(value);setPreviewSource(undefined);}});
  const saveProbes=async(probes:ProbeSpec[])=>{
    edited.current.add('probes');
    await client.saveExperiment({name:script.split(/[\\/]/).at(-1)||'Analysis',script,interpreter,arguments:parseArguments(arguments_),capture:{level:capture},annotations:{},adapters:adapters.split(',').map(item=>item.trim()).filter(Boolean),probes});setDefinitions(probes);
  };
  const run=async()=>{setNotice('');const started=await execution.run(signal=>client.start({script,interpreter,mode:capture,arguments:parseArguments(arguments_),probes:definitions,adapters:adapters.split(',').map(item=>item.trim()).filter(Boolean)},signal));if(started){setRunId(started.run_id);await refresh();}};
  const operation=actual?.operation_id?state.operations.get(actual.operation_id):undefined,custom=actual?renderers.resolve(actual.descriptor):undefined,Custom=custom?.Component;
  if(catalog.status==='error'&&!runs.length)return <ConnectionHelp error={catalog.error||'本地服务无法连接'} retry={()=>void refresh()}/>;
  return <main className="research-app">
    <header className="ri-header"><h1>Scientific Dataflow Inspector</h1><span className="ri-local">本地科研工作台</span><div className="ri-header-actions"><button onClick={()=>setShowModels(value=>!value)}>模型设置</button><button onClick={()=>{const theme=document.documentElement.dataset.theme==='light'?'dark':'light';document.documentElement.dataset.theme=theme;localStorage.setItem('cdaf-theme',theme);}}>切换主题</button><a href="?legacy=1">旧版架构</a></div></header>
    <section className="ri-toolbar" onChangeCapture={markEdit}><label>分析脚本<input aria-label="分析脚本" value={script} onChange={e=>setScript(e.target.value)} placeholder="已有 .py 脚本路径"/></label><button onClick={()=>void preview.run(signal=>client.sourcePreview(script,signal)).then(value=>{if(value){setPreviewSource(value);setSelected('');}})} disabled={preview.status==='running'||!script}>打开代码</button><label>计算解释器<input aria-label="计算解释器" value={interpreter} onChange={e=>setInterpreter(e.target.value)}/></label>
      <label>采集<select aria-label="采集级别" value={capture} onChange={e=>setCapture(e.target.value)}><option value="metadata">元数据</option><option value="summary">摘要</option><option value="full">完整数据</option></select></label><button className="ri-primary" onClick={()=>void run()} disabled={!script||!interpreter||execution.status==='running'}>{execution.status==='running'?'正在启动…':'运行分析'}</button>
      {['queued','running','paused'].includes(state.status)&&<button onClick={()=>void control.run(signal=>client.control(runId,state.status==='paused'?'resume':'cancel',signal))}>{state.status==='paused'?'继续运行':'取消运行'}</button>}
    </section>
    <details className="ri-run-options" onChangeCapture={markEdit}><summary>示例、脚本参数与扩展适配器</summary><div><label>示例选择<select aria-label="示例选择" onChange={e=>{const example=info?.examples.find(item=>item.id===e.target.value);if(example){setScript(example.script);setArguments('');}}}><option value="">使用自己的脚本</option>{info?.examples.map(example=><option value={example.id} key={example.id}>{example.name}</option>)}</select></label><label>脚本参数<input aria-label="脚本参数" value={arguments_} onChange={e=>setArguments(e.target.value)} placeholder="--failure nan"/></label><label>已安装适配器<input aria-label="已安装适配器" value={adapters} onChange={e=>setAdapters(e.target.value)} placeholder="显式 entrypoint 名称，以逗号分隔"/></label></div></details>
    <div className="ri-runbar"><label>运行记录<select aria-label="运行记录" value={runId} onChange={e=>setRunId(e.target.value)}><option value="">选择运行</option>{runs.map(run=><option key={run.id} value={run.id}>{run.name} · {run.status} · {run.id.slice(0,8)}</option>)}</select></label><span data-testid="run-status">{bootstrap.status==='running'?'读取记录…':state.status}</span><span data-testid="quality-status">{String(state.summary.quality||'尚无质量结果')}</span><button onClick={()=>void refresh()}>刷新记录</button><button disabled={!runId||exporting.status==='running'} onClick={()=>void exporting.run(()=>downloadReport(runId))}>导出离线报告</button></div>
    {[notice,catalog.error,bootstrap.error,detail.error,execution.error,control.error,source.error,preview.error,historyLoad.error,exporting.error].filter(Boolean).map((error,index)=><p className="ri-error" role="alert" key={index}>{error}</p>)}
    <div className="ri-workspace"><div className="ri-left ri-column"><SourcePane file={previewSource||file} selection={!previewSource?actual?.source:null}/><VariableList values={values} selected={selected} onSelect={select}/></div>
      <section className="ri-data"><header><h2 data-testid="current-variable">{snapshot?.name||'数据观察'}</h2><span>{snapshot?`v${snapshot.version} · ${snapshot.descriptor.backend}`:''}</span></header>
      {actual?<><p data-testid="matrix-definition">{actual.descriptor.shape?.join(' × ')||actual.descriptor.kind} · {actual.descriptor.dtype} · {actual.fidelity} · <span data-testid="detail-status">{details?.id===snapshot?.id?'详情已就绪':'读取详情…'}</span></p>
        <div className="ri-history-controls"><button onClick={loadHistory}>查看变量历史</button>{historyValue&&<button onClick={()=>setHistoryValue(undefined)}>返回最新版本</button>}{showHistory&&history.map(value=><button key={value.id} onClick={()=>{setHistoryValue(value);setPreviewSource(undefined);}}>版本 {value.version}</button>)}</div>
        {Custom?<Custom snapshot={actual}/>:actual.descriptor.kind==='table'?<TableView snapshot={actual}/>:['matrix','tensor','array'].includes(actual.descriptor.kind)?<MatrixView snapshot={actual}/>:<div className="ri-scalar"><p>{actual.descriptor.type_name}</p><pre>{displayCell(actual.sample.values||'此类型未提供数值预览。')}</pre></div>}
        <OperationView operation={operation} snapshots={state.snapshots}/>
      </>:<p className="ri-empty">打开脚本并运行，选择变量查看定义、数据和运算。</p>}</section>
      <div className="ri-right ri-column"><LocalFlow state={state} selected={selected} onSelect={select}/><ProbePanel snapshot={actual} results={actual?state.probes.get(actual.id)||[]:[]} definitions={definitions} onSave={saveProbes}/><RunTimeline runId={runId} live={state.timeline} onSnapshot={showSnapshot}/></div>
    </div><footer className="ri-footer">{state.omittedBindings?`${state.omittedBindings} 个变量未加载；完整证据保存在本地。`:'源码与运行记录绑定版本；历史查看不会重新执行代码。'}<span>CLI：cdaf observe analysis.py</span></footer><ModelSettings visible={showModels} onClose={()=>setShowModels(false)}/>
  </main>;
}
