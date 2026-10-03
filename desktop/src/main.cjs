const {app, BrowserWindow, ipcMain, dialog}=require('electron');
const path=require('node:path');
const fs=require('node:fs');
const {pathToFileURL}=require('node:url');
const {BackendController}=require('./controller.cjs');
const {BackendHost}=require('./backend.cjs');
const option=name=>{const i=process.argv.indexOf(name);return i<0?undefined:process.argv[i+1];};
const project=option('--project')||path.join(app.getPath('userData'),'research');
const python=process.env.CDAF_DESKTOP_PYTHON||(app.isPackaged?path.join(process.resourcesPath,'python',process.platform==='win32'?'python.exe':'bin/python3'):path.resolve(__dirname,'../../.venv',process.platform==='win32'?'Scripts/python.exe':'bin/python'));
const startup=path.join(__dirname,'startup.html');
let window, owner, closing=false, recovery;
let backendState={state:'starting',message:''};

function record(message){
  try{
    const file=path.join(app.getPath('userData'),'desktop.log');
    if(fs.existsSync(file)&&fs.statSync(file).size>262144) fs.renameSync(file,file+'.previous');
    const clean=String(message).replace(/#session=[^\s]+/g,'#session=[redacted]').slice(0,4000);
    fs.appendFileSync(file,new Date().toISOString()+' '+clean+'\n');
  }catch{}
}
function publish(state,error){
  backendState={state,message:error?.message||''};
  if(window&&!window.isDestroyed()) window.webContents.send('backend-state',backendState);
}
function createOwner(){return new BackendController(()=>new BackendHost(python,project),publish);}
async function showFailure(error){
  if(closing||!window||window.isDestroyed()) return;
  record(error.message);
  try{
    await window.loadFile(startup);
    publish('error',error);
  }catch(failure){record(failure.message);dialog.showErrorBox('Scientific Dataflow Inspector', '启动页面未能显示。请查看用户目录中的 desktop.log。');}
}
async function start(){
  if(recovery) return recovery;
  recovery=(async()=>{
    try{
      // Renderer loss cannot reuse a stale ready URL after the browser lease ends.
      if(owner?.state==='ready'||owner?.closed){await owner.close();owner=createOwner();}
      if(!owner) owner=createOwner();
      const handle=await owner.start();
      if(!closing&&handle) await window.loadURL(handle.url);
    }catch(error){await showFailure(error);}
  })();
  try{await recovery;}finally{recovery=undefined;}
}
function permitted(event){
  const url=event.senderFrame?.url;
  if(url===pathToFileURL(startup).href) return true;
  try{return !!owner?.handle&&new URL(url).origin===new URL(owner.handle.url).origin;}catch{return false;}
}
if(!app.requestSingleInstanceLock()) app.quit();
else{
  app.on('second-instance',()=>{if(window){if(window.isMinimized())window.restore();window.focus();}});
  app.whenReady().then(async()=>{
    window=new BrowserWindow({width:1600,height:1000,minWidth:900,minHeight:640,backgroundColor:'#11161a',title:'Scientific Dataflow Inspector',webPreferences:{preload:path.join(__dirname,'preload.cjs'),nodeIntegration:false,contextIsolation:true,sandbox:true}});
    window.setMenuBarVisibility(false);
    window.webContents.setWindowOpenHandler(()=>({action:'deny'}));
    window.webContents.on('will-navigate',(event,url)=>{if(owner?.handle&&new URL(url).origin!==new URL(owner.handle.url).origin)event.preventDefault();});
    ipcMain.handle('retry-backend',event=>permitted(event)?start():undefined);
    ipcMain.handle('backend-status',event=>permitted(event)?backendState:undefined);
    ipcMain.handle('close-workbench',event=>{if(permitted(event))window.close();});
    window.on('close',event=>{
      if(closing)return;
      event.preventDefault();closing=true;
      void (owner?.close()||Promise.resolve()).finally(()=>{window.destroy();app.quit();});
    });
    window.webContents.on('render-process-gone',(_event,details)=>{
      if(!closing) void showFailure(Error('渲染进程已停止（'+details.reason+'）。请重试打开工作台。'));
    });
    window.webContents.on('did-fail-load',(_event,code,description,url,isMain)=>{
      if(isMain && code!==-3 && !closing && !recovery && url!==pathToFileURL(startup).href)
        void showFailure(Error('工作台页面未能加载（'+description+'）。请重试连接本地服务。'));
    });
    await window.loadFile(startup);
    await start();
  }).catch(error=>showFailure(error));
  app.on('window-all-closed',()=>app.quit());
  app.on('before-quit',event=>{if(!closing&&window){event.preventDefault();window.close();}});
}
