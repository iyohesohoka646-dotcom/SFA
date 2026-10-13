const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');

test('preload exposes a folder picker without exposing general IPC',async()=>{
 const exposed={},calls=[];
 vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../src/preload.cjs'),'utf8'),{
  window:{addEventListener:()=>{}},
  require:()=>({contextBridge:{exposeInMainWorld:(name,api)=>{exposed[name]=api;}},ipcRenderer:{on:()=>{},invoke:async channel=>{calls.push(channel);return 'C:\\research';}}})
 });
 assert.equal(typeof exposed.desktopStartup.pickProjectFolder,'function','Open folder must have a native desktop picker');
 assert.equal(await exposed.desktopStartup.pickProjectFolder(),'C:\\research');
 assert.deepEqual(calls,['pick-project-folder']);
 assert.equal(exposed.desktopStartup.invoke,undefined);
});

const {createProjectFolderPicker}=require('../src/folder-picker.cjs');
function fixture(show){
 const window={isDestroyed:()=>false,webContents:{mainFrame:{}}};
 const event={sender:window.webContents,senderFrame:window.webContents.mainFrame};
 const calls=[];
 const pick=createProjectFolderPicker({dialog:{showOpenDialog:async(...args)=>{calls.push(args);return show();}},getWindow:()=>window,allowed:e=>e===event,defaultPath:()=>'/documents'});
 return {window,event,pick,calls};
}
test('directory selection is attached to the owned window and cancellation is inert',async()=>{
 let choice={canceled:true,filePaths:[]};
 const f=fixture(()=>choice);
 assert.equal(await f.pick(f.event),null);
 assert.equal(f.calls[0][0],f.window);
 assert.deepEqual(f.calls[0][1].properties,['openDirectory']);
 choice={canceled:false,filePaths:['/research/中文 project']};
 assert.equal(await f.pick(f.event),'/research/中文 project');
 await f.pick(f.event);assert.equal(f.calls[2][1].defaultPath,'/research/中文 project');
});
test('foreign and subframe requests cannot open a native directory dialog',async()=>{
 const f=fixture(()=>({canceled:false,filePaths:['/research']}));
 await assert.rejects(f.pick({sender:f.window.webContents,senderFrame:{}}),/active workbench/);
 await assert.rejects(f.pick({sender:{},senderFrame:f.window.webContents.mainFrame}),/active workbench/);
 assert.equal(f.calls.length,0);
});
test('concurrent requests share one dialog and failed dialogs can be retried',async()=>{
 let finish;
 const f=fixture(()=>new Promise(resolve=>{finish=resolve;}));
 const a=f.pick(f.event),b=f.pick(f.event);assert.equal(f.calls.length,1);
 finish({canceled:true,filePaths:[]});assert.deepEqual(await Promise.all([a,b]),[null,null]);
 const broken=fixture(()=>{throw Error('dialog failure');});
 await assert.rejects(broken.pick(broken.event),/dialog failure/);
 await assert.rejects(broken.pick(broken.event),/dialog failure/);assert.equal(broken.calls.length,2);
});
