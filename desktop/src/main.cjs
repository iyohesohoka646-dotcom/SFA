const {app,BrowserWindow,ipcMain}=require('electron');
const path=require('node:path');const os=require('node:os');
const {BackendController}=require('./controller.cjs');const {BackendHost}=require('./backend.cjs');
const option=name=>{const index=process.argv.indexOf(name);return index<0?undefined:process.argv[index+1];};
const project=option('--project')||path.join(app.getPath('userData'),'research');
const python=process.env.CDAF_DESKTOP_PYTHON||(app.isPackaged?path.join(process.resourcesPath,'python',process.platform==='win32'?'python.exe':'bin/python3'):path.resolve(__dirname,'../../.venv',process.platform==='win32'?'Scripts/python.exe':'bin/python'));
let window,owner,closing=false;
if(!app.requestSingleInstanceLock())app.quit();
else{
 app.on('second-instance',()=>{if(window){if(window.isMinimized())window.restore();window.focus();}});
 app.whenReady().then(()=>{
  window=new BrowserWindow({width:1600,height:1000,minWidth:900,minHeight:640,backgroundColor:'#11161a',title:'Scientific Dataflow Inspector',webPreferences:{preload:path.join(__dirname,'preload.cjs'),nodeIntegration:false,contextIsolation:true,sandbox:true}});
  window.setMenuBarVisibility(false);window.loadFile(path.join(__dirname,'startup.html'));
  window.webContents.setWindowOpenHandler(()=>({action:'deny'}));
  window.webContents.on('will-navigate',(event,url)=>{if(owner?.handle&&new URL(url).origin!==new URL(owner.handle.url).origin)event.preventDefault();});
  owner=new BackendController(()=>new BackendHost(python,project),(state,error)=>{if(window&&!window.isDestroyed())window.webContents.send('backend-state',{state,message:error?.message||''});});
  const start=async()=>{try{const handle=await owner.start();if(!closing&&handle)await window.loadURL(handle.url);}catch{} };
  ipcMain.handle('retry-backend',event=>{if(event.senderFrame.url===require('node:url').pathToFileURL(path.join(__dirname,'startup.html')).href)return start();});
  window.on('close',event=>{if(closing)return;event.preventDefault();closing=true;void owner.close().finally(()=>{window.destroy();app.quit();});});
  window.webContents.on('render-process-gone',()=>{if(!closing)window.close();});
  void start();
 });
 app.on('window-all-closed',()=>app.quit());
 app.on('before-quit',event=>{if(!closing&&owner){event.preventDefault();window?.close();}});
}
