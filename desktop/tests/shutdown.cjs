// The visible exit action must close its native owner and release the service.
const {_electron}=require('../../web/node_modules/playwright');
const assert=require('node:assert/strict');
const path=require('node:path');
const fs=require('node:fs');
const os=require('node:os');
(async()=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'cdaf-shutdown-'));
 const installed=process.env.CDAF_DESKTOP_TEST_EXE;
 const env={...process.env};
 if(installed)delete env.CDAF_DESKTOP_PYTHON;
 else{
  env.CDAF_DESKTOP_PYTHON=path.resolve(__dirname,'../../.work/desktop-python/python.exe');
  env.PYTHONPATH=path.resolve(__dirname,'../../src');
 }
 const app=await _electron.launch({executablePath:installed||require('electron'),args:installed?['--project',root]:[path.resolve(__dirname,'../src/main.cjs'),'--project',root],env});
 try{
  const page=await app.firstWindow();
  await page.getByRole('tree',{name:'计算对象树'}).waitFor({timeout:30000});
  const state=JSON.parse(fs.readFileSync(path.join(root,'.cdaf/studio.json'),'utf8'));
  const closing=app.waitForEvent('close',{timeout:10000});
  await page.getByRole('button',{name:'退出并停止',exact:true}).click();
  await closing;
  assert(!fs.existsSync(path.join(root,'.cdaf/studio.json')));
  await assert.rejects(fetch('http://127.0.0.1:'+state.port+'/api/v1/studio'));
 }finally{await app.close().catch(()=>{});}
})().catch(error=>{console.error(error);process.exitCode=1;});
