// Real renderer + backend failure: an immediately missing runtime must stay visible.
const {_electron,chromium}=require('../../web/node_modules/playwright');
const assert=require('node:assert/strict');
const path=require('node:path');
const fs=require('node:fs');
const os=require('node:os');
(async()=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'cdaf-startup-error-'));
 const app=await _electron.launch({executablePath:require('electron'),args:[path.resolve(__dirname,'../src/main.cjs'),'--project',root],env:{...process.env,CDAF_DESKTOP_PYTHON:path.join(root,'missing-python.exe')}});
 try{
  const started=Date.now();
  const page=await app.firstWindow();
  await page.getByRole('button',{name:'重试',exact:true}).waitFor({timeout:10000});
  assert(Date.now()-started<5000,'A missing runtime must not wait six seconds on a child that never spawned');
  assert.match(await page.locator('#startup-status').innerText(),/runtime unavailable/);
  await page.getByRole('button',{name:'重试',exact:true}).click();
  await page.getByRole('button',{name:'重试',exact:true}).waitFor({timeout:10000});
  assert.match(await page.locator('#startup-status').innerText(),/runtime unavailable/);
  assert.equal(fs.existsSync(path.join(root,'.cdaf/studio.json')),false);
 }finally{await app.close();}
 const healthy=await _electron.launch({executablePath:require('electron'),args:[path.resolve(__dirname,'../src/main.cjs'),'--project',root],env:{...process.env,CDAF_DESKTOP_PYTHON:path.resolve(__dirname,'../../.work/desktop-python/python.exe')}});
 let connection;
 try{
  const page=await healthy.firstWindow();
  await page.getByRole('button',{name:'运行',exact:true}).waitFor({timeout:30000});
  const data=await healthy.evaluate(({app})=>app.getPath('userData'));
  const port=fs.readFileSync(path.join(data,'DevToolsActivePort'),'utf8').split('\n')[0];
  await healthy.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].webContents.forcefullyCrashRenderer());
  // Wait for native replacement navigation before attaching a fresh CDP
  // session: attaching to the dying target trips Playwright's crash assertion.
  const until=Date.now()+10000;
  while(Date.now()<until){
    const targets=await(await fetch('http://127.0.0.1:'+port+'/json/list')).json();
    if(targets.some(t=>t.url.endsWith('/startup.html')&&t.title==='Scientific Dataflow Inspector')) break;
    await new Promise(r=>setTimeout(r,100));
  }
  await new Promise(r=>setTimeout(r,300));
  // Playwright's original Page remains marked crashed even after native
  // recovery. Attach anew to the real replacement renderer.
  connection=await chromium.connectOverCDP('http://127.0.0.1:'+port);
  const recovered=connection.contexts()[0].pages()[0];
  await recovered.locator('#startup-status').filter({hasText:'渲染进程已停止'}).waitFor({timeout:10000});
  await recovered.getByRole('button',{name:'重试',exact:true}).click();
  await recovered.getByRole('tree',{name:'计算对象树'}).waitFor({timeout:30000});
  const address=await recovered.evaluate(()=>location.origin);
  assert(await recovered.evaluate(async()=>(await fetch('/api/v1/studio/shutdown',{method:'POST',headers:{Authorization:'Bearer '+sessionStorage.getItem('cdaf-session'),'Content-Type':'application/json'}})).ok));
  let stopped=false;
  for(let i=0;i<80;i++){
    try{await fetch(address,{signal:AbortSignal.timeout(1000)});}catch{stopped=true;break;}
    await new Promise(r=>setTimeout(r,200));
  }
  assert(stopped,'Wait for actual service shutdown, not an arbitrary refresh delay');
  await recovered.reload().catch(()=>{});
  try{await recovered.locator('#startup-status').filter({hasText:'工作台页面未能加载'}).waitFor({timeout:10000});}
  catch(error){console.error('Recovered document:',await recovered.locator('body').innerText());throw error;}
  await recovered.getByRole('button',{name:'重试',exact:true}).click();
  await recovered.getByRole('tree',{name:'计算对象树'}).waitFor({timeout:30000});
 }finally{await connection?.close();await healthy.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
