import {memo,useMemo,useRef,useState} from 'react';
import type {AnalysisDocument,TargetRef} from './generated';
import type {SnapshotRef} from '../generated';
import {choose,objectRows,selectionKey,type Selection,type ObjectRow} from './selection';
import {Icon} from './icons';
export const ObjectBrowser=memo(function ObjectBrowser({analysis,values,selection,onSelection,onOpen,onSource,onEnter,onBind,scope}:{analysis?:AnalysisDocument;values:SnapshotRef[];selection:Selection;onSelection:(s:Selection)=>void;onOpen:(row:ObjectRow)=>void;onSource:(row:ObjectRow)=>void;onEnter:(id:string|null)=>void;onBind:()=>void;scope:string|null}){
 const [query,setQuery]=useState(''),[type,setType]=useState('all'),[closed,setClosed]=useState<Set<string>>(new Set()),[top,setTop]=useState(0),[menu,setMenu]=useState<{row:ObjectRow;x:number;y:number}>();
 const expanded=useMemo(()=>new Set(analysis?.graph.blocks.map(b=>b.id).filter(id=>!closed.has(id))),[analysis?.id,closed]);
 const rows=useMemo(()=>objectRows(analysis,values,scope,expanded,query,type),[analysis,values,scope,expanded,query,type]);
 const keys=useMemo(()=>new Set(selection.targets.map(selectionKey)),[selection]);
 const order=useMemo(()=>rows.map(r=>r.target),[rows]);
 const viewport=useRef<HTMLDivElement>(null),start=Math.max(0,Math.floor(top/32)-3),visible=rows.slice(start,start+40);
 const select=(row:ObjectRow,e:{ctrlKey?:boolean;metaKey?:boolean;shiftKey?:boolean})=>onSelection(choose(selection,row.target,order,{toggle:e.ctrlKey||e.metaKey,shift:e.shiftKey}));
 return <section className="object-browser" aria-label="对象浏览器"><div className="wb-section-label">对象浏览器 <span>{rows.length}</span></div>
 <div className="object-filters"><input type="search" aria-label="搜索对象" value={query} placeholder="搜索对象" onChange={e=>{setQuery(e.target.value);setTop(0);if(viewport.current)viewport.current.scrollTop=0;}}/><select aria-label="对象类型" value={type} onChange={e=>setType(e.target.value)}><option value="all">全部类型</option>{['matrix','table','scalar','function','condition','loop'].map(v=><option key={v}>{v}</option>)}</select></div>
 <div className="scope-breadcrumb"><button onClick={()=>onEnter(null)}>项目</button>{scope&&<><span>/</span><button onClick={()=>onEnter(analysis?.graph.blocks.find(b=>b.id===scope)?.parent_id??null)}>{analysis?.graph.blocks.find(b=>b.id===scope)?.label}</button></>}</div>
 <div role="tree" aria-label="计算对象树" aria-multiselectable="true" tabIndex={0} ref={viewport} className="object-tree" onScroll={e=>setTop(e.currentTarget.scrollTop)} onKeyDown={e=>{
 if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='a'){e.preventDefault();if(order.length)onSelection(choose(selection,order[0],order,{all:true}));return;}
 if(!rows.length)return;
 const i=Math.max(0,rows.findIndex(r=>selectionKey(r.target)===selectionKey(selection.targets.at(-1)??order[0])));
 if(e.key==='ArrowDown'||e.key==='ArrowUp'){e.preventDefault();const next=Math.max(0,Math.min(rows.length-1,i+(e.key==='ArrowDown'?1:-1)));if(rows[next]){select(rows[next],e);viewport.current?.scrollTo({top:Math.max(0,next*32-100)});}}
 if(e.key==='Enter'&&selection.targets.length===1&&rows[i]){e.preventDefault();onOpen(rows[i]);}
 if((e.key==='ContextMenu'||e.shiftKey&&e.key==='F10')&&rows[i]){e.preventDefault();setMenu({row:rows[i],x:200,y:250});}
 }}><div style={{height:rows.length*32,position:'relative'}}>{visible.map((row,i)=>{
 const selected=keys.has(selectionKey(row.target))||Boolean(row.objectId&&selection.targets.some(t=>t.object_id===row.objectId));const partial=row.block&&!selected&&selection.targets.some(t=>t.block_id===row.block!.id);
 return <div key={row.id} role="treeitem" aria-level={row.depth+1} aria-selected={selected} aria-expanded={row.block?expanded.has(row.id):undefined} className={'object-row '+(selected?'selected ':'')+(partial?'part-selected':'')} style={{top:(start+i)*32,paddingLeft:8+row.depth*12}} onClick={e=>select(row,e)} onDoubleClick={()=>onOpen(row)} onContextMenu={e=>{e.preventDefault();if(!selected)select(row,{});setMenu({row,x:e.clientX,y:e.clientY});}}>
 {row.block?<button className="tree-toggle" aria-label={(expanded.has(row.id)?'折叠 ':'展开 ')+row.label} onClick={e=>{e.stopPropagation();setClosed(old=>{const n=new Set(old);n.has(row.id)?n.delete(row.id):n.add(row.id);return n;});}}><Icon name="chevron" size={10}/></button>:<span className={'object-type '+(row.snapshot?.descriptor.kind??'data')}/>}
 <span className="object-row-name" title={row.target.logical_key}>{row.label}</span><small title={row.detail}>{row.detail}</small></div>;
 })}</div></div>
 <div className="object-selection"><span>{selection.targets.length} 项选中</span><button disabled={!selection.targets.length} onClick={onBind}>绑定探针</button></div>
 {menu&&<div className="context-backdrop" onClick={()=>setMenu(undefined)}><div role="menu" className="workspace-menu object-context" style={{left:Math.min(menu.x,innerWidth-210),top:Math.min(menu.y,innerHeight-210)}}>{menu.row.snapshot&&<button onClick={()=>onOpen(menu.row)}>打开数据</button>}<button onClick={()=>onSource(menu.row)}>定位源码</button>{menu.row.block&&<button onClick={()=>onEnter(menu.row.id)}>进入此块</button>}<button onClick={onBind}>绑定探针</button></div></div>}
 </section>;
});
