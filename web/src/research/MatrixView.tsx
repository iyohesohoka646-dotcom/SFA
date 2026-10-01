import {memo,useEffect,useMemo,useRef,useState} from 'react';
import type {SnapshotRef} from './generated';
import {client} from './client';
import {useOperation} from './operations';
import {cellColor,displayCell,numericCell,planeAxes} from './matrix-renderer';
import type {ComplexMode} from './matrix-renderer';
export interface MatrixViewProps {snapshot:SnapshotRef;selectors?:Record<string,number>[];onSelect?:(row:number,column:number)=>void;}
export const MatrixView=memo(function MatrixView({snapshot,onSelect}:MatrixViewProps){
  const shape=snapshot.descriptor.shape||[],canvas=useRef<HTMLCanvasElement>(null),container=useRef<HTMLDivElement>(null);
  const [mode,setMode]=useState<ComplexMode>('real'),[fixed,setFixed]=useState<Record<number,number>>({}),[chosen,setChosen]=useState([0,0]);
  const [region,setRegion]=useState<{values?:unknown[][];shape?:number[];reason?:string;available:boolean;snapshotId:string;selectors:Record<string,number>[]} >();
  const sliced=useOperation('slice:'+snapshot.id),axes=planeAxes(shape);
  useEffect(()=>{setFixed({});setRegion(undefined);setChosen([0,0]);},[snapshot.id]);
  const currentRegion=region?.snapshotId===snapshot.id?region:undefined;
  const values=currentRegion?.available?currentRegion.values||[]:(snapshot.sample.values as unknown[][])||[];
  const numbers=useMemo(()=>values.map(row=>row.map(value=>numericCell(value,mode))),[values,mode]);
  const finite=numbers.flat().filter((value):value is number=>value!==null&&Number.isFinite(value));
  const minimum=finite.length?Math.min(...finite):0,maximum=finite.length?Math.max(...finite):0;
  useEffect(()=>{
    const draw=()=>{
      const node=canvas.current,parent=container.current;if(!node||!parent)return;
      const width=Math.max(180,Math.min(720,parent.clientWidth-32)),height=Math.min(380,Math.max(180,width*(numbers.length||1)/Math.max(1,numbers[0]?.length||1))),ratio=Math.min(devicePixelRatio||1,2);
      node.width=Math.ceil(width*ratio);node.height=Math.ceil(height*ratio);node.style.width=width+'px';node.style.height=height+'px';
      const context=node.getContext('2d');if(!context)return;context.scale(ratio,ratio);context.clearRect(0,0,width,height);
      const rows=numbers.length,columns=numbers[0]?.length||0;if(!rows||!columns)return;
      for(let r=0;r<rows;r++)for(let c=0;c<columns;c++){context.fillStyle=cellColor(numbers[r][c],minimum,maximum);context.fillRect(c*width/columns,r*height/rows,Math.ceil(width/columns),Math.ceil(height/rows));}
      context.strokeStyle='#f1f5f7';context.lineWidth=2;context.strokeRect(chosen[1]*width/columns,chosen[0]*height/rows,width/columns,height/rows);
    };
    draw();const observer=new ResizeObserver(draw);if(container.current)observer.observe(container.current);return()=>observer.disconnect();
  },[numbers,minimum,maximum,chosen]);
  const select=(row:number,column:number)=>{setChosen([row,column]);onSelect?.(row,column);};
  const read=async()=>{const selectors=shape.map((size,axis):Record<string,number>=>axis<shape.length-2?{index:fixed[axis]||0}:{start:0,stop:Math.min(size,64)});
    const result=await sliced.run(signal=>client.slice(snapshot.id,selectors,signal));if(result){setChosen([0,0]);setRegion({...result,snapshotId:snapshot.id,selectors});}};
  if(shape.some(size=>size===0))return <p className="ri-empty" data-testid="matrix-empty">空矩阵 · {shape.join(' × ')}，没有可显示的单元。</p>;
  return <div className="ri-matrix" ref={container}>
    <div className="ri-matrix-controls">{snapshot.descriptor.dtype?.startsWith('complex')&&<label>复数显示<select aria-label="复数显示" value={mode} onChange={e=>setMode(e.target.value as ComplexMode)}><option value="real">实部</option><option value="imag">虚部</option><option value="magnitude">幅值</option></select></label>}
      {axes.fixed.map(axis=><label key={axis}>固定 axis {axis}<input type="number" aria-label={`固定 axis ${axis}`} min={0} max={Math.max(0,shape[axis]-1)} value={fixed[axis]||0} onChange={e=>{sliced.cancel();setFixed(value=>({...value,[axis]:Number(e.target.value)}));setRegion(undefined);setChosen([0,0]);}}/></label>)}
      <button onClick={()=>void read()} disabled={sliced.status==='running'}>读取此版本切片</button>{sliced.status==='running'&&<button onClick={sliced.cancel}>取消切片</button>}
    </div>
    <p className="ri-fidelity">{currentRegion?.available?'完整产物的精确切片':snapshot.fidelity==='exact'?'已保存的精确预览':snapshot.fidelity==='sampled'?'抽样预览，覆盖范围见索引':'仅元数据'} · {values.length} × {values[0]?.length||0} 个显示单元{axes.fixed.length?` · 当前预览固定轴：${axes.fixed.map(axis=>`axis ${axis}=${currentRegion?.available?currentRegion.selectors[axis].index:(snapshot.sample.fixed_axes as Record<string,number>)?.[axis]||0}`).join('，')}`:''}</p>
    {!!values.length&&<canvas ref={canvas} role="img" aria-label="矩阵热图" tabIndex={0}
      onPointerDown={e=>{const rect=e.currentTarget.getBoundingClientRect();select(Math.min(values.length-1,Math.floor((e.clientY-rect.top)/rect.height*values.length)),Math.min((values[0]?.length||1)-1,Math.floor((e.clientX-rect.left)/rect.width*(values[0]?.length||1))));}}
      onKeyDown={e=>{const directions:Record<string,number[]>={ArrowUp:[-1,0],ArrowDown:[1,0],ArrowLeft:[0,-1],ArrowRight:[0,1]};if(directions[e.key]){e.preventDefault();const change=directions[e.key];select(Math.max(0,Math.min(values.length-1,chosen[0]+change[0])),Math.max(0,Math.min(values[0].length-1,chosen[1]+change[1])));}}}/>}
    {!!values.length&&<p data-testid="matrix-cell-value">[{currentRegion?.available?(currentRegion.selectors[shape.length-2]?.start||0)+chosen[0]:(snapshot.sample.row_indices as number[])?.[chosen[0]]??chosen[0]}, {currentRegion?.available?(currentRegion.selectors[shape.length-1]?.start||0)+chosen[1]:(snapshot.sample.column_indices as number[])?.[chosen[1]]??chosen[1]}] = {mode==='real'&&snapshot.descriptor.dtype?.startsWith('complex')?displayCell(values[chosen[0]]?.[chosen[1]]):displayCell(numbers[chosen[0]]?.[chosen[1]])}</p>}
    {!values.length&&<p className="ri-empty">此值未保存数值预览。</p>}
    {(region || sliced.error)&&<p data-testid="slice-result" role="status">{sliced.error|| (region?.available?'此版本切片已读取。':'此版本未保存完整数据，或完整产物已过期。')}</p>}
    <div className="ri-statistics">{['min','max','mean','variance','finite_count','nan_count','inf_count','missing_count'].filter(key=>snapshot.statistics[key]!==undefined).map(key=><span key={key}>{key}<strong>{displayCell(snapshot.statistics[key])}</strong></span>)}</div>
    <p className="ri-fidelity">统计范围：{String(snapshot.statistics.sample_count??'未知')} / {String(snapshot.statistics.population_count??'未知')} · {snapshot.statistics.exact?'精确':'抽样或不可用'}；轴语义：{snapshot.descriptor.axes.join('，')||'未标注'}；单位：{snapshot.descriptor.unit||'未标注'}</p>
    {!!snapshot.truncation.length&&<p className="ri-fidelity">采集限制：{snapshot.truncation.join('，')}</p>}
  </div>;
});
