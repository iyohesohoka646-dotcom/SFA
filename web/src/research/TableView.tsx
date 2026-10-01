import {memo,useMemo,useState} from 'react';
import type {SnapshotRef} from './generated';
import {displayCell} from './matrix-renderer';
export const TableView=memo(function TableView({snapshot}:{snapshot:SnapshotRef}){
  const [top,setTop]=useState(0),values=(snapshot.sample.values as unknown[][])||[],columns=(snapshot.sample.columns as unknown[])||[],index=(snapshot.sample.index as unknown[])||[];
  const start=Math.max(0,Math.floor(top/32)-2),shown=useMemo(()=>values.slice(start,start+20),[values,start]);
  return <div className="ri-table-view"><p className="ri-fidelity">{snapshot.fidelity==='exact'?'精确预览':'抽样预览'} · {values.length} 行 · 行索引可重复；行号和标签分别显示</p>
    <div className="ri-table-scroll" onScroll={e=>setTop(e.currentTarget.scrollTop)}><table aria-label="数据表预览"><thead><tr><th>行号</th><th>索引</th>{columns.map((column,i)=><th key={i}>{displayCell(column)}</th>)}</tr></thead><tbody>
      {start>0&&<tr aria-hidden="true"><td colSpan={columns.length+2} style={{height:start*32}}/></tr>}
      {shown.map((row,i)=><tr key={start+i}><td>{(snapshot.sample.row_indices as number[])?.[start+i]??start+i}</td><th>{displayCell(index[start+i])}</th>{row.map((value,c)=><td key={c}>{displayCell(value)}</td>)}</tr>)}
      {start+shown.length<values.length&&<tr aria-hidden="true"><td colSpan={columns.length+2} style={{height:(values.length-start-shown.length)*32}}/></tr>}
    </tbody></table></div>
    <p className="ri-fidelity">列类型：{((snapshot.descriptor.metadata.columns as {name:unknown;dtype:string}[])||[]).slice(0,32).map(column=>`${displayCell(column.name)}: ${column.dtype}`).join('；')}</p>
    {!!snapshot.redacted.length&&<p className="ri-fidelity">已脱敏：{snapshot.redacted.join('，')}</p>}
  </div>;
});
