import {memo, useEffect, useMemo, useRef, useState} from 'react';
import type {SnapshotRef} from './generated';
export const VariableList=memo(function VariableList({values,selected,onSelect}:{values:SnapshotRef[];selected:string;onSelect:(id:string)=>void}){
  const [query,setQuery]=useState(''),[top,setTop]=useState(0);const scroll=useRef<HTMLDivElement>(null);
  const filtered=useMemo(()=>values.filter(value=>(value.name+' '+value.descriptor.backend+' '+value.descriptor.dtype).toLowerCase().includes(query.toLowerCase())),[values,query]);
  useEffect(()=>{if(scroll.current)scroll.current.scrollTop=0;setTop(0);},[query]);
  const start=Math.max(0,Math.floor(top/44)-4),visible=filtered.slice(start,start+32);
  return <section className="ri-variables"><header><h2>变量</h2><span data-testid="variable-count">{values.length}</span></header>
    <input type="search" aria-label="搜索变量" placeholder="搜索名称、类型或后端" value={query} onChange={e=>setQuery(e.target.value)}/>
    <div className="ri-variable-scroll" ref={scroll} onScroll={e=>setTop(e.currentTarget.scrollTop)}>
      <div style={{height:filtered.length*44,position:'relative'}}>
        {visible.map((value,index)=><button key={value.binding_id} className={'ri-variable '+(selected===value.binding_id?'selected':'')} aria-label={`${value.name} · ${value.descriptor.dtype||value.descriptor.kind}`} style={{top:(start+index)*44}}
          onClick={()=>onSelect(value.binding_id)}><strong>{value.name}</strong><span>{value.descriptor.shape?.join(' × ')||value.descriptor.kind}</span><small>v{value.version}</small></button>)}
      </div>
      {!filtered.length&&<p className="ri-empty">{values.length?'没有匹配的变量。':'运行分析后，这里会显示实际观察到的变量。'}</p>}
    </div>
  </section>;
});
