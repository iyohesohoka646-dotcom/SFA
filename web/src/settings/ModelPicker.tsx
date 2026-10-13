import {memo,useMemo,useState} from 'react';
export const ModelPicker=memo(function ModelPicker({models,value,onChange,required}:{models:string[];value:string;onChange:(value:string)=>void;required?:boolean}){
  const [query,setQuery]=useState('');const filtered=useMemo(()=>models.filter(model=>model.toLowerCase().includes(query.toLowerCase())),[models,query]);
  return <div className="ri-model-picker"><label>默认模型 ID<input aria-label="默认模型 ID" required={required} value={value} onChange={e=>onChange(e.target.value)} placeholder="手动填写服务支持的模型 ID"/></label>
    {models.length>0?<><label>搜索模型<input type="search" aria-label="搜索模型" value={query} onChange={e=>setQuery(e.target.value)}/></label>
      <select aria-label="发现模型" size={5} value={filtered.includes(value)?value:''} onChange={e=>onChange(e.target.value)}>{filtered.slice(0,500).map(model=><option key={model} value={model}>{model}</option>)}</select>
      <p className="ri-fidelity">{filtered.length} 个匹配；未列出的模型可手填。</p></>:<p className="ri-fidelity">暂无发现的模型，可手动填写；连接测试可读取模型列表。</p>}
  </div>;
});