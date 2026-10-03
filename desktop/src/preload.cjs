const {contextBridge,ipcRenderer}=require('electron');
contextBridge.exposeInMainWorld('desktopStartup',{retry:()=>ipcRenderer.invoke('retry-backend'),close:()=>ipcRenderer.invoke('close-workbench')});
const update=state=>{
 if(!state)return;
 const status=document.getElementById('startup-status');
 if(status)status.textContent=state.state==='error'?state.message:'正在启动本地科研服务…';
 const retry=document.getElementById('retry');if(retry)retry.hidden=state.state!=='error';
};
ipcRenderer.on('backend-state',(_,state)=>{
 if(document.readyState==='loading')window.addEventListener('DOMContentLoaded',()=>update(state),{once:true});else update(state);
});
// Loading/replacing a failed document can miss an event in transit. Read the
// authoritative last state after every new recovery document is ready.
window.addEventListener('DOMContentLoaded',()=>{
 if(document.getElementById('startup-status'))void ipcRenderer.invoke('backend-status').then(update).catch(()=>{});
},{once:true});
