import {memo,useEffect,useMemo,useRef} from 'react';
import type {SourceFile} from './client';
import type {SourceRef} from './generated';
export const SourcePane=memo(function SourcePane({file,selection}:{file?:SourceFile;selection?:SourceRef|null}){
  const lines=useMemo(()=>file?.code.split('\n')||[],[file?.digest,file?.code]);
  const line=selection?.line||1,start=Math.max(0,line-25),end=Math.min(lines.length,start+110);const selected=useRef<HTMLDivElement>(null),code=useRef<HTMLDivElement>(null);
  useEffect(()=>{if(selected.current&&code.current)code.current.scrollTop=selected.current.offsetTop-code.current.clientHeight/2;},[line,file?.digest]);
  return <section className="ri-source"><header><h2>源码与定义</h2><span>{selection?.line?`第 ${line} 行`:''}</span></header>
    <p className="ri-source-path" title={file?.path}>{file?.path||'打开代码，或者选择运行记录。'}</p>
    {selection?.code&&<pre data-testid="source-selection" className="ri-source-selection">{selection.code}</pre>}
    {!lines.length?<p className="ri-empty">源码预览只读；运行证据绑定当时的源码摘要。</p>:<div className="ri-code" ref={code} role="region" aria-label="分析源码" tabIndex={0}>
      {start>0&&<p className="ri-code-context">前 {start} 行折叠</p>}
      {lines.slice(start,end).map((text,index)=>{const number=start+index+1,active=number>=line&&number<=(selection?.end_line||line);return <div key={number} ref={number===line?selected:undefined} className={active?'active':''} aria-label={`源码第 ${number} 行`}><span>{number}</span><code>{text||' '}</code></div>;})}
      {end<lines.length&&<p className="ri-code-context">其余 {lines.length-end} 行折叠</p>}
    </div>}
  </section>;
});
