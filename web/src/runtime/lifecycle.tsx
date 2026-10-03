import {useEffect,useState} from 'react';
import {createPortal} from 'react-dom';
import {headers} from '../api';

export function ServiceControl(){
 const [owned,setOwned]=useState(false);const [stopped,setStopped]=useState(false);
 useEffect(()=>{
  const controller=new AbortController();let lease:string|undefined;let closed=false;
  const release=()=>{closed=true;controller.abort();if(lease)void fetch('/api/v1/lifecycle/leases/'+lease,{method:'DELETE',headers:headers(),keepalive:true}).catch(()=>{});};
  const connect=async()=>{
   try{
    const state=await fetch('/api/v1/lifecycle',{headers:headers(),signal:controller.signal});
    if(!state.ok)return;
    const status=await state.json();setOwned(status.owned);
    if(!status.owned)return;
    const response=await fetch('/api/v1/lifecycle/leases',{method:'POST',headers:headers(),body:JSON.stringify({client_id:crypto.randomUUID()}),signal:controller.signal});
    if(!response.ok)throw Error('Lease is unavailable');lease=(await response.json()).id;
    while(!closed){
     try{
      const stream=await fetch('/api/v1/lifecycle/leases/'+lease+'/events',{headers:headers(),signal:controller.signal});
      if(!stream.ok||!stream.body)break;
      const reader=stream.body.getReader();while(!closed&&!(await reader.read()).done){}
     }catch{if(closed)break;}
     if(!closed)await new Promise(resolve=>setTimeout(resolve,400));
    }
   }catch{if(!closed)setOwned(false);}
  };
  void connect();window.addEventListener('pagehide',release);
  return ()=>{window.removeEventListener('pagehide',release);release();};
 },[]);
 const desktop=(window as Window & {desktopStartup?:{close:()=>Promise<unknown>}}).desktopStartup;
 if(!owned&&!desktop)return null;
 const button=<button disabled={stopped} onClick={async()=>{setStopped(true);try{if(desktop){await desktop.close();return;}const response=await fetch('/api/v1/studio/shutdown',{method:'POST',headers:headers()});if(!response.ok)setStopped(false);}catch{setStopped(false);} }}> {stopped?'正在停止…':'退出并停止'} </button>;
 const target=document.querySelector('.ri-header-actions');
 const controls=<>{desktop&&<button onClick={()=>window.dispatchEvent(new Event('cdaf-open-terminal'))}>打开终端</button>}{owned&&button}</>;
 return target?createPortal(controls,target):<div className="service-control">{controls}</div>;
}
