import {memo,useEffect,useMemo,useState} from 'react';
import {ReactFlow,Controls,Handle,Position,useReactFlow} from '@xyflow/react';
import type {Node,Edge,NodeProps} from '@xyflow/react';
import type {ResearchState} from './state';
import type {OperationRecord,SnapshotRef} from './generated';
import {explainOperation} from './explanation-templates';
import {localTopology} from './selectors';
import {layoutResearch} from '../graph';
import {EvidenceExplanation} from '../settings/EvidenceExplanation';

function ValueNode({data}:NodeProps){return <div className="ri-value-node" data-testid="flow-node"><Handle type="target" position={Position.Left}/><strong>{String(data.name)}</strong><small>{String(data.shape)}</small><Handle type="source" position={Position.Right}/></div>;}
const nodeTypes={value:ValueNode};
export const OperationView=memo(function OperationView({operation,snapshots,model=true}:{operation?:OperationRecord;snapshots:Map<string,SnapshotRef>;model?:boolean}){
  if(!operation)return <p className="ri-empty">选择有来源记录的变量，查看表达式及其输入输出。</p>;
  const values=[...operation.input_snapshots,...operation.output_snapshots].map(id=>snapshots.get(id)).filter((value):value is SnapshotRef=>!!value);
  const explanation=explainOperation(operation,values.map(value=>value.descriptor));
  return <div className="ri-operation"><code>{operation.label}</code><p data-testid="operation-explanation">{explanation.text}</p><div className="ri-io"><span>输入 {operation.input_snapshots.map(id=>snapshots.get(id)?.name||id.slice(0,8)).join('，')||'未观察'}</span><span>输出 {operation.output_snapshots.map(id=>snapshots.get(id)?.name||id.slice(0,8)).join('，')||'未观察'}</span></div><small>{operation.duration_ms?.toFixed(2)||'未知'} ms · {operation.provenance} · {explanation.uncertainty.join('；')}</small>{model&&<EvidenceExplanation key={operation.id} operation={operation}/>}</div>;
});

export const LocalFlow=memo(function LocalFlow({state,selected,onSelect}:{state:ResearchState;selected:string;onSelect:(id:string)=>void}){
  const [nodes,setNodes]=useState<Node[]>([]),[edges,setEdges]=useState<Edge[]>([]),[expanded,setExpanded]=useState(false),[error,setError]=useState('');
  const flow=useReactFlow();
  const all=useMemo(()=>localTopology(state,selected,80),[state.topologyVersion,state.runId,selected]);
  const ids=useMemo(()=>expanded?all:all.filter(id=>id===selected||(state.dependencies.get(selected)||[]).includes(id)||(state.dependencies.get(id)||[]).includes(selected)).slice(0,80),[all,expanded,state.topologyVersion,selected]);
  const key=state.runId+'|'+ids.join('\0')+'|'+state.topologyVersion;
  useEffect(()=>{
    let active=true;const seed=ids.map((id,index)=>({id,type:'value',position:{x:(index%4)*180,y:Math.floor(index/4)*96},data:{name:state.latest.get(id)?.name||id,shape:state.latest.get(id)?.descriptor.shape?.join(' × ')||'metadata'},ariaLabel:state.latest.get(id)?.name||id}));
    const connections=ids.flatMap(target=>(state.dependencies.get(target)||[]).filter(source=>ids.includes(source)).map(source=>({id:source+'>'+target,source,target,type:'smoothstep',style:{stroke:'#7be0c2',strokeDasharray:'4 4'},ariaLabel:'推断的变量依赖'})));
    setNodes(seed);setEdges(connections);
    void layoutResearch(seed,connections).then(positions=>{if(active){setNodes(current=>current.map(node=>({...node,position:positions.get(node.id)||node.position})));requestAnimationFrame(()=>requestAnimationFrame(()=>{if(active)void flow.fitView({padding:.18,minZoom:.01,maxZoom:1.3,duration:0});}));}}).catch(error=>{if(active)setError(error.message);});
    return()=>{active=false;};
  },[key]);
  useEffect(()=>{setNodes(current=>{
    let changed=false;const next=current.map(node=>{const value=state.latest.get(node.id),name=value?.name||node.id,shape=value?.descriptor.shape?.join(' × ')||'metadata';
      if(node.data.name===name&&node.data.shape===shape)return node;changed=true;return {...node,data:{...node.data,name,shape}};});
    return changed?next:current;
  });},[state.lastSequence]);
  return <section className="ri-flow"><header><h2>局部数据流</h2><button onClick={()=>setExpanded(value=>!value)}>{expanded?'仅直接相邻':'展开运算链'}</button><span>{ids.length} / 80</span></header>
    <div className="ri-flow-canvas"><ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView fitViewOptions={{padding:.18,minZoom:.01,maxZoom:1.3}} minZoom={.01} maxZoom={2}
      onNodeClick={(_,node)=>onSelect(node.id)} onNodesChange={()=>{}} nodesDraggable={false} nodesConnectable={false} proOptions={{hideAttribution:true}}><Controls showInteractive={false}/></ReactFlow></div>
    <p className="ri-fidelity">箭头表示记录中的变量依赖；推断关系使用虚线。最多显示 80 个变量。</p>{error&&<p role="alert">布局失败，保留基础位置：{error}</p>}
  </section>;
});
