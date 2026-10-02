import {memo,useEffect,useMemo,useRef,useState} from 'react';
import type {SnapshotRef} from './generated';
import {client} from './client';
import {useOperation} from './operations';
import {cellColor,displayCell,numericCell,planeAxes} from './matrix-renderer';
import type {DataSemantics} from './workspace/generated';
import type {ComplexMode} from './matrix-renderer';
export interface MatrixViewProps {snapshot:SnapshotRef;selectors?:Record<string,number>[];onSelect?:(row:number,column:number)=>void;parameters?:Record<string,unknown>;semantics?:DataSemantics|null;}
export const MatrixView=memo(function MatrixView({snapshot,onSelect,parameters={},semantics}:MatrixViewProps){
  const shape=snapshot.descriptor.shape||[],canvas=useRef<HTMLCanvasElement>(null),container=useRef<HTMLDivElement>(null);
  const [mode,setMode]=useState<ComplexMode>('real'),[fixed,setFixed]=useState<Record<number,number>>({}),[chosen,setChosen]=useState([0,0]);
  const [scaleMode,setScaleMode]=useState(parameters.scale==='symmetric'?'zero':'range');
  const [region,setRegion]=useState<{values?:unknown[][];shape?:number[];reason?:string;available:boolean;snapshotId:string;selectors:Record<string,number>[]} >();
  const sliced=useOperation('slice:'+snapshot.id),axes=planeAxes(shape);
  useEffect(()=>{setFixed({});setRegion(undefined);setChosen([0,0]);},[snapshot.id]);
  const currentRegion=region?.snapshotId===snapshot.id?region:undefined;
  const values=currentRegion?.available?currentRegion.values||[]:(snapshot.sample.values as unknown[][])||[];
  const numbers=useMemo(()=>values.map(row=>row.map(value=>numericCell(value,mode))),[values,mode]);
  const cells=useMemo(()=>numbers.flat(),[numbers]),finite=useMemo(()=>cells.filter((value):value is number=>value!==null&&Number.isFinite(value)),[cells]);
  const lower=finite.length?Math.min(...finite):0,upper=finite.length?Math.max(...finite):0;
  const extent=Math.max(Math.abs(lower),Math.abs(upper));
  const minimum=typeof parameters.minimum==='number'?parameters.minimum:scaleMode==='zero'?-extent:lower,maximum=typeof parameters.maximum==='number'?parameters.maximum:scaleMode==='zero'?extent:upper;
  const constant=finite.length>0&&lower===upper,missing=cells.filter(v=>v===null).length,nonfinite=cells.filter(v=>v!==null&&!Number.isFinite(v)).length;
  const rowIndex=(r:number)=>currentRegion?.available?(currentRegion.selectors[Math.max(0,shape.length-2)]?.start||0)+r:(snapshot.sample.row_indices as number[])?.[r]??r;
  const columnIndex=(c:number)=>currentRegion?.available?(currentRegion.selectors[shape.length-1]?.start||0)+c:(snapshot.sample.column_indices as number[])?.[c]??c;
  const heatColor=(v:number|null)=>{
    if(v===null||!Number.isFinite(v))return cellColor(v,minimum,maximum);
    const transform=(n:number)=>parameters.scale==='log'?(n>0?Math.log(n):NaN):n;
    const a=transform(minimum),b=transform(maximum),x=transform(v),ratio=a===b?.5:Math.max(0,Math.min(1,(x-a)/(b-a)));
    if(!Number.isFinite(ratio))return '#87999c';
    if(parameters.palette==='gray'){const n=Math.round(240-200*ratio);return `rgb(${n},${n},${n})`;}
    if(parameters.palette==='sequential')return `rgb(${Math.round(230-210*ratio)},${Math.round(245-130*ratio)},${Math.round(247-125*ratio)})`;
    return cellColor(x,a,b);
  };
  useEffect(()=>{
    const draw=()=>{
      const node=canvas.current,parent=container.current;if(!node||!parent)return;
      const width=Math.max(180,Math.min(720,parent.clientWidth-32)*Number(parameters.zoom??1)),height=Math.min(380,Math.max(180,width*(numbers.length||1)/Math.max(1,numbers[0]?.length||1))),ratio=Math.min(devicePixelRatio||1,2);
      node.width=Math.ceil(width*ratio);node.height=Math.ceil(height*ratio);node.style.width=width+'px';node.style.height=height+'px';
      const context=node.getContext('2d');if(!context)return;context.scale(ratio,ratio);context.clearRect(0,0,width,height);
      const rows=numbers.length,columns=numbers[0]?.length||0;if(!rows||!columns)return;
      for(let r=0;r<rows;r++)for(let c=0;c<columns;c++){
        const x=c*width/columns,y=r*height/rows,w=width/columns,h=height/rows,value=numbers[r][c];
        context.fillStyle=heatColor(value);context.fillRect(x,y,Math.ceil(w),Math.ceil(h));
        if(value===null||!Number.isFinite(value)){
          context.save();context.beginPath();context.rect(x,y,w,h);context.clip();context.strokeStyle='rgba(255,255,255,.5)';context.lineWidth=1;
          for(let offset=-h;offset<w;offset+=12){context.beginPath();context.moveTo(x+offset,y);context.lineTo(x+offset+h,y+h);context.stroke();}context.restore();
        }
        if(parameters.show_values&&w>=38&&h>=22){context.fillStyle=value!==null&&Number.isFinite(value)&&Math.abs(value)>Math.max(Math.abs(minimum),Math.abs(maximum))*.55?'#fff':'#1d303b';context.font='11px sans-serif';context.textAlign='center';context.textBaseline='middle';context.fillText(value===null?'—':Number.isFinite(value)?value.toFixed(Number(parameters.precision??3)):String(value),x+w/2,y+h/2,w-4);}
        if(rows<=20&&columns<=20){context.strokeStyle='rgba(255,255,255,.18)';context.lineWidth=.5;context.strokeRect(x,y,w,h);}
      }
      context.strokeStyle='#f1f5f7';context.lineWidth=2;context.strokeRect(chosen[1]*width/columns,chosen[0]*height/rows,width/columns,height/rows);
    };
    draw();const observer=new ResizeObserver(draw);if(container.current)observer.observe(container.current);return()=>observer.disconnect();
  },[numbers,minimum,maximum,chosen,parameters.show_values,parameters.precision,parameters.palette,parameters.scale,parameters.zoom]);
  const select=(row:number,column:number)=>{setChosen([row,column]);onSelect?.(row,column);};
  const read=async()=>{const selectors=shape.map((size,axis):Record<string,number>=>axis<shape.length-2?{index:fixed[axis]||0}:{start:0,stop:Math.min(size,64)});
    const result=await sliced.run(signal=>client.slice(snapshot.id,selectors,signal));if(result){setChosen([0,0]);setRegion({...result,snapshotId:snapshot.id,selectors});}};
  if(shape.some(size=>size===0))return <p className="ri-empty" data-testid="matrix-empty">空矩阵 · {shape.join(' × ')}，没有可显示的单元。</p>;
  return <div className="ri-matrix" ref={container}>
    <div className="ri-matrix-controls">{snapshot.descriptor.dtype?.startsWith('complex')&&<label>复数显示<select aria-label="复数显示" value={mode} onChange={e=>setMode(e.target.value as ComplexMode)}><option value="real">实部</option><option value="imag">虚部</option><option value="magnitude">幅值</option></select></label>}
      <label>色阶<select aria-label="热图色阶" value={scaleMode} onChange={e=>setScaleMode(e.target.value)}><option value="range">显示范围</option><option value="zero">零点对称</option></select></label>
      {axes.fixed.map(axis=><label key={axis}>固定 axis {axis}<input type="number" aria-label={`固定 axis ${axis}`} min={0} max={Math.max(0,shape[axis]-1)} value={fixed[axis]||0} onChange={e=>{sliced.cancel();setFixed(value=>({...value,[axis]:Number(e.target.value)}));setRegion(undefined);setChosen([0,0]);}}/></label>)}
      <button onClick={()=>void read()} disabled={sliced.status==='running'}>读取此版本切片</button>{sliced.status==='running'&&<button onClick={sliced.cancel}>取消切片</button>}
    </div>
    {!!values.length&&<div className="ri-color-legend" data-testid="matrix-color-legend">
      <span className="ri-scale-label" title="颜色仅依据当前显示单元，不代表完整数据的范围。">{finite.length?constant&&scaleMode==='range'?`恒定值 ${displayCell(lower)}`:`线性 · ${scaleMode==='zero'?'零点对称':'显示范围'}`:'无有限数值'}</span>
      {finite.length>0&&<span className="ri-scale"><span>{displayCell(minimum)}</span><i aria-hidden="true" style={{background:minimum===maximum?heatColor(minimum):`linear-gradient(to right,${heatColor(minimum)},${heatColor(minimum/2+maximum/2)},${heatColor(maximum)})`}}/><span>{displayCell(maximum)}{snapshot.descriptor.unit?' '+snapshot.descriptor.unit:''}</span></span>}
      {!!missing&&<span><i className="ri-color-key missing"/>缺失 {missing}</span>}{!!nonfinite&&<span><i className="ri-color-key nonfinite"/>NaN / Inf {nonfinite}</span>}
      <span className="ri-sample-label">{currentRegion?.available?'精确切片':snapshot.fidelity==='sampled'?'抽样':snapshot.fidelity==='exact'?'全量已保存 / 当前预览':'预览'} · {values.length} × {values[0]?.length||0}</span>
    </div>}
    {!!values.length&&<div className="ri-matrix-axes" data-testid="matrix-axis-labels"><span>{semantics?.axes[axes.plane[0]]?.label||'行'} {rowIndex(0)} — {rowIndex(values.length-1)}{snapshot.descriptor.axes[axes.plane[0]]?' · '+snapshot.descriptor.axes[axes.plane[0]]:''}</span><span>{semantics?.axes[axes.plane[1]]?.label||'列'} {columnIndex(0)} — {columnIndex((values[0]?.length||1)-1)}{shape.length>1&&snapshot.descriptor.axes[axes.plane[1]]?' · '+snapshot.descriptor.axes[axes.plane[1]]:''}</span></div>}
    {!!values.length&&<canvas ref={canvas} role="img" aria-label="矩阵热图" tabIndex={0}
      onPointerDown={e=>{const rect=e.currentTarget.getBoundingClientRect();select(Math.min(values.length-1,Math.floor((e.clientY-rect.top)/rect.height*values.length)),Math.min((values[0]?.length||1)-1,Math.floor((e.clientX-rect.left)/rect.width*(values[0]?.length||1))));}}
      onKeyDown={e=>{const directions:Record<string,number[]>={ArrowUp:[-1,0],ArrowDown:[1,0],ArrowLeft:[0,-1],ArrowRight:[0,1]};if(directions[e.key]){e.preventDefault();const change=directions[e.key];select(Math.max(0,Math.min(values.length-1,chosen[0]+change[0])),Math.max(0,Math.min(values[0].length-1,chosen[1]+change[1])));}}}/>}
    {!!values.length&&<p data-testid="matrix-cell-value">{String(semantics?.axes[axes.plane[0]]?.coordinates[rowIndex(chosen[0])]??'')} {String(semantics?.axes[axes.plane[1]]?.coordinates[columnIndex(chosen[1])]??'')} [{rowIndex(chosen[0])}, {columnIndex(chosen[1])}] = {mode==='real'&&snapshot.descriptor.dtype?.startsWith('complex')?displayCell(values[chosen[0]]?.[chosen[1]]):displayCell(numbers[chosen[0]]?.[chosen[1]])}</p>}
    {!values.length&&<p className="ri-empty">此值未保存数值预览。</p>}
    {(region || sliced.error)&&<p data-testid="slice-result" role="status">{sliced.error|| (region?.available?'此版本切片已读取。':'此版本未保存完整数据，或完整产物已过期。')}</p>}
    <details className="ri-matrix-details"><summary>统计与采集</summary>
    <div className="ri-statistics">{['min','max','mean','variance','finite_count','nan_count','inf_count','missing_count'].filter(key=>snapshot.statistics[key]!==undefined).map(key=><span key={key}>{({min:'最小值',max:'最大值',mean:'均值',variance:'方差',finite_count:'有限值',nan_count:'NaN',inf_count:'Inf',missing_count:'缺失'} as Record<string,string>)[key]}<strong>{displayCell(snapshot.statistics[key])}</strong></span>)}</div>
    <p className="ri-fidelity">统计范围：{String(snapshot.statistics.sample_count??'未知')} / {String(snapshot.statistics.population_count??'未知')} · {snapshot.statistics.exact?'精确':'抽样或不可用'}；轴语义：{snapshot.descriptor.axes.join('，')||'未标注'}；单位：{snapshot.descriptor.unit||'未标注'}</p>
    {!!snapshot.truncation.length&&<p className="ri-fidelity">采集限制：{snapshot.truncation.join('，')}</p>}
    {!!axes.fixed.length&&<p className="ri-fidelity">固定轴：{axes.fixed.map(axis=>`axis ${axis}=${currentRegion?.available?currentRegion.selectors[axis].index:(snapshot.sample.fixed_axes as Record<string,number>)?.[axis]||0}`).join('，')}</p>}
    </details>
  </div>;
});
