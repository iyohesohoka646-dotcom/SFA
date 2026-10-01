const {contextBridge,ipcRenderer}=require('electron');
contextBridge.exposeInMainWorld('desktopStartup',{retry:()=>ipcRenderer.invoke('retry-backend'),terminal:()=>ipcRenderer.invoke('open-terminal')});
ipcRenderer.on('backend-state',(_,state)=>{
 const update=()=>{const status=document.getElementById('startup-status');if(status)status.textContent=state.state==='error'?state.message:'正在启动本地科研服务…';const retry=document.getElementById('retry');if(retry)retry.hidden=state.state!=='error';};
 if(document.readyState==='loading')window.addEventListener('DOMContentLoaded',update,{once:true});else update();
});
