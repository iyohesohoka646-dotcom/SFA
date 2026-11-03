// A real ten-minute 10 Hz analysis; invoke manually, never inflate fast-suite claims.
const {chromium}=require('../web/node_modules/playwright');
const {spawn}=require('node:child_process');const {createInterface}=require('node:readline');
const fs=require('node:fs');const path=require('node:path');
(async()=>{
 const seconds=Number(process.argv[2]||600);const root=path.resolve('.work/research-soak-'+Date.now());
 const host=spawn(path.resolve('.venv/Scripts/python.exe'),['-u','-X','utf8','scripts/soak_host.py',root,String(seconds)],{windowsHide:true,stdio:['ignore','pipe','pipe']});
 const handle=await new Promise((resolve,reject)=>{createInterface({input:host.stdout}).once('line',line=>resolve(JSON.parse(line)));host.once('exit',()=>reject(Error('Soak fixture exited before readiness')));});
 const browser=await chromium.launch({channel:'msedge'});const page=await browser.newPage({viewport:{width:1600,height:1000},reducedMotion:'reduce'});
 const metrics=[];const started=Date.now();let result;
 try{
  await page.goto(handle.url);await page.getByRole('button',{name:'运行分析',exact:true}).waitFor();
  const state=JSON.parse(fs.readFileSync(path.join(root,'.cdaf/studio.json'),'utf8'));
  const base=`http://127.0.0.1:${state.port}`;const auth={Authorization:'Bearer '+state.token,'Content-Type':'application/json'};
  const response=await fetch(base+'/api/v1/research/runs',{method:'POST',headers:auth,body:JSON.stringify({script:handle.script,interpreter:path.resolve('.venv/Scripts/python.exe'),watched_names:['X'],instrument:'auto',mode:'summary'})});
  if(!response.ok)throw Error('Soak run rejected '+response.status);
  const run=await response.json();await page.getByRole('button',{name:'刷新记录',exact:true}).click();await page.getByLabel('运行记录').selectOption(run.run_id||run.id);
  const cdp=await page.context().newCDPSession(page);await cdp.send('Performance.enable');
  while(Date.now()-started<(seconds+3)*1000){
   const value=page.getByRole('button',{name:/^X ·/}).first();
   if(await value.count()){
    const click=performance.now();await value.click();await page.getByRole('img',{name:'矩阵热图'}).waitFor();
    const cpu=await cdp.send('Performance.getMetrics');const dom=await cdp.send('Memory.getDOMCounters');
    metrics.push({seconds:(Date.now()-started)/1000,detail_ms:performance.now()-click,js_heap_bytes:cpu.metrics.find(item=>item.name==='JSHeapUsedSize').value,dom_nodes:dom.nodes});
   }
   await new Promise(resolve=>setTimeout(resolve,1000));
  }
  const record=await (await fetch(base+'/api/v1/research/runs/'+(run.run_id||run.id),{headers:auth})).json();
  result={scope:'Real live 64x64 NumPy auto capture, target 10 Hz; externally measured backend RSS and Chromium JS heap; no universal overhead claim',duration_seconds:(Date.now()-started)/1000,run_id:run.run_id||run.id,run:record,ui_samples:metrics,backend_samples:JSON.parse(fs.readFileSync(path.join(root,'rss.json'),'utf8'))};
  await page.screenshot({path:'docs/assets/research-soak.png'});
 }finally{
  await browser.close();await new Promise(resolve=>{if(host.exitCode!==null)return resolve();host.once('exit',resolve);setTimeout(()=>{host.kill();resolve();},10000);});
 }
 fs.writeFileSync('docs/assets/research-soak.json',JSON.stringify(result,null,2));
 console.log('Live soak saved',metrics.length,'samples');
})().catch(error=>{console.error(error);process.exitCode=1;});
