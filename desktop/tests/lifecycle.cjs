const { _electron:electron }=require('../../web/node_modules/playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');const path=require('node:path');const os=require('node:os');
(async()=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'cdaf-desktop-'));
 const installed=process.env.CDAF_DESKTOP_TEST_EXE;
 const environment={...process.env};
 if(installed)delete environment.CDAF_DESKTOP_PYTHON;
 else environment.CDAF_DESKTOP_PYTHON=path.resolve(__dirname,'../../.work/desktop-python/python.exe');
 const app=await electron.launch({executablePath:installed||require('electron'),args:installed?['--project',root]:[path.resolve(__dirname,'../src/main.cjs'),'--project',root],env:environment,timeout:30000});
 try{
  const window=await app.firstWindow();
  await window.getByRole('button',{name:'运行分析',exact:true}).waitFor({timeout:30000});
  await window.getByRole('button',{name:'打开终端',exact:true}).waitFor({timeout:5000});
  const record=JSON.parse(fs.readFileSync(path.join(root,'.cdaf/studio.json'),'utf8'));
  await window.screenshot({path:path.resolve(__dirname,'../../docs/assets/research-desktop.png')});
  const closed=app.waitForEvent('close');await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].close());await closed;
  assert.equal(fs.existsSync(path.join(root,'.cdaf/studio.json')),false);
  await assert.rejects(fetch(`http://127.0.0.1:${record.port}/api/v1/studio`));
  fs.writeFileSync(path.resolve(__dirname,'../../docs/assets/research-desktop-validation.json'),JSON.stringify({platform:process.platform,installed:!!installed,window_close:true,port_released:true,backend_pid:record.pid},null,2));
 }finally{await app.close().catch(()=>{});}
})().catch(error=>{console.error(error);process.exitCode=1;});
