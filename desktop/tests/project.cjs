// Real packaged/development project workflow; all user data lives in a disposable folder.
const {_electron:electron}=require('../../web/node_modules/playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {spawnSync}=require('node:child_process');
(async()=>{
 const fixtures=path.resolve(__dirname,'../../.work');fs.mkdirSync(fixtures,{recursive:true});
 const root=fs.mkdtempSync(path.join(fixtures,'native-project-'));
 const lab=path.join(root,'matrix-lab');fs.cpSync(path.resolve(__dirname,'../../examples/research/projects/matrix-lab'),lab,{recursive:true});
 const installed=process.env.CDAF_DESKTOP_TEST_EXE;
 const env={...process.env,PYTHONUTF8:'1',CDAF_HOME:path.join(root,'home')};delete env.PYTHONPATH;
 if(installed)delete env.CDAF_DESKTOP_PYTHON;
 else env.CDAF_DESKTOP_PYTHON=path.resolve(__dirname,'../../.work/desktop-python/python.exe');
 const python=installed?path.join(path.dirname(installed),'resources/python/python.exe'):env.CDAF_DESKTOP_PYTHON;
 const profile=path.join(root,'desktop-profile');
 const app=await electron.launch({executablePath:installed||require('electron'),args:[...(installed?[]:[path.resolve(__dirname,'../src/main.cjs')]),'--project',root,'--user-data-dir='+profile],env,timeout:30000});
 const errors=[],children=[];let state,projectId;
 try{
  const page=await app.firstWindow();page.on('pageerror',e=>errors.push(e.message));page.setDefaultTimeout(15000);
  assert.equal(path.resolve(await app.evaluate(({app})=>app.getPath('userData'))),path.resolve(profile));
  await page.locator('.project-host-bar').waitFor({timeout:45000});
  const open=page.getByRole('button',{name:'Open folder',exact:true});
  await open.waitFor();assert(await open.isEnabled());
  assert(await page.locator('.project-host-bar').getByRole('button',{name:'退出并停止',exact:true}).isVisible());
  let nativeDialog=false;
  if(process.platform==='win32'){
   await open.click();
   const windowHandle=await app.evaluate(({BrowserWindow})=>{const b=BrowserWindow.getAllWindows()[0].getNativeWindowHandle();return (b.length===8?b.readBigUInt64LE():BigInt(b.readUInt32LE())).toString();});
   const realDialog=spawnSync('powershell.exe',['-NoProfile','-ExecutionPolicy','Bypass','-File',path.resolve(__dirname,'native-folder-dialog.ps1'),'-OwnerProcessId',String(app.process().pid),'-OwnerWindowHandle',windowHandle],{encoding:'utf8',windowsHide:true,timeout:15000});
   assert.equal(realDialog.status,0,realDialog.stdout+'\n'+realDialog.stderr);nativeDialog=JSON.parse(realDialog.stdout).native_directory_dialog_visible;assert(nativeDialog);
   await page.waitForFunction(()=>!document.querySelector('.project-welcome-action')?.disabled);
   assert.equal(await page.locator('.project-host-error').count(),0);
  }
  await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].setBounds({width:1280,height:900}));
  await page.evaluate(()=>{document.documentElement.dataset.theme='light';});
  await page.screenshot({path:path.resolve(__dirname,'../../docs/assets/project-welcome.png')});
  await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].setBounds({width:900,height:800}));
  await page.evaluate(()=>{document.documentElement.dataset.theme='dark';});
  await page.screenshot({path:path.resolve(__dirname,'../../.work/project-acceptance/project-welcome-dark-900.png')});
  await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].setBounds({width:1600,height:1000}));
  await page.evaluate(()=>{document.documentElement.dataset.theme='light';});
  // Deterministic native IPC integration: stub only the OS dialog result, then
  // use the real preload/main handler and project import/index/compute pipeline.
  await app.evaluate(({dialog},lab)=>{
   globalThis.folderDialogCalls=[];
   const choices=[{canceled:true,filePaths:[]},{canceled:false,filePaths:[lab]}];
   dialog.showOpenDialog=async(parent,options)=>{globalThis.folderDialogCalls.push({parent:parent.id,properties:options.properties});return choices.shift();};
  },lab);
  assert(await open.isEnabled());await open.click();await open.waitFor();assert(await open.isEnabled());
  assert.equal(await page.locator('.project-host-error').count(),0);
  await open.click();
  await page.getByRole('button',{name:'运行入口',exact:true}).click();await page.locator('.project-entries-candidates').getByRole('button',{name:'main.py',exact:true}).click();
  await page.getByRole('button',{name:'Save entry',exact:true}).click();await page.getByRole('button',{name:'Save entry',exact:true}).waitFor({state:'hidden'});await page.getByRole('button',{name:'关闭运行入口',exact:true}).click();
  await page.getByRole('button',{name:'运行',exact:true}).click();await page.waitForFunction(()=>document.querySelector('.wb-statusbar')?.textContent.includes('completed'),{},{timeout:60000});
  const runId=await page.getByLabel('项目运行记录',{exact:true}).inputValue();assert(runId);
  const choices=await app.evaluate(()=>globalThis.folderDialogCalls);assert.equal(choices.length,2);assert(choices.every(choice=>choice.properties.join(',')==='openDirectory'));
  await page.getByRole('button',{name:'Expand prepare.py',exact:true}).click();await page.getByRole('button',{name:'Expand build_dataset',exact:true}).click();
  const row=page.locator('.project-object-row').filter({has:page.locator('.project-object-name',{hasText:/^X$/})});await row.dblclick();
  await page.getByRole('img',{name:'矩阵热图',exact:true}).waitFor();await page.getByRole('button',{name:'打开探针台',exact:true}).click();
  assert((await page.locator('.wb-inspector').innerText()).includes('X'));
  state=JSON.parse(fs.readFileSync(path.join(root,'.cdaf/studio.json'),'utf8'));
  projectId=await page.evaluate(()=>localStorage.getItem('cdaf.project.id'));
  const prefix=`http://127.0.0.1:${state.port}/api/v1/research/projects/${projectId}`;
  const headers={Authorization:'Bearer '+state.token};
  const evidence=await(await fetch(prefix+'/runs/'+runId+'/bootstrap',{headers})).json();
  assert(evidence.snapshots.some(s=>s.source?.path.endsWith('compute.py')));
  await page.getByRole('button',{name:'计算关系图',exact:true}).click();
  const dataGraph=page.waitForResponse(response=>response.url().includes('/graph?')&&response.url().includes('view=data')&&response.ok());
  await page.getByRole('button',{name:'Data',exact:true}).click();await dataGraph;
  await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  await page.locator('.project-canvas-status').waitFor({state:'hidden'});await page.locator('.react-flow__node').first().waitFor();
  await page.getByRole('button',{name:'Fit',exact:true}).click();
  await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  const canvasGeometry=()=>page.locator('.project-canvas-flow').evaluate(element=>{
    const bounds=element.getBoundingClientRect();
    const clipped=[...element.querySelectorAll('.react-flow__node')].filter(node=>{
      const box=node.getBoundingClientRect();
      return box.left<bounds.left-2||box.right>bounds.right+2||box.top<bounds.top-2||box.bottom>bounds.bottom+2;
    }).map(node=>node.getAttribute('data-id'));
    return {width:bounds.width,height:bounds.height,clipped,nodes:element.querySelectorAll('.react-flow__node').length,viewport:element.querySelector('.react-flow__viewport')?.getAttribute('style')};
  });
  const fitted=await canvasGeometry();assert(fitted.nodes>0);assert.deepEqual(fitted.clipped,[],'Fit must keep every visible block inside the canvas');
  const timings=await row.evaluate(async element=>{const result=[];for(let i=0;i<30;i++){const start=performance.now();element.dispatchEvent(new MouseEvent('click',{bubbles:true}));await new Promise(requestAnimationFrame);result.push(performance.now()-start);}return result;});
  timings.sort((a,b)=>a-b);const p95=timings[Math.floor(timings.length*.95)];
  const afterSelection=await canvasGeometry();console.log(JSON.stringify({fitted,afterSelection}));
  assert.equal(afterSelection.viewport,fitted.viewport,'Selection must preserve the fitted camera');
  assert.deepEqual(afterSelection.clipped,[],'The fitted blocks must remain inside the canvas after selection');
  await page.screenshot({path:path.resolve(__dirname,'../../docs/assets/project-graph.png')});
  await page.getByRole('tab',{name:'X',exact:true}).locator('.workspace-tab-title').click();await page.getByRole('img',{name:'矩阵热图',exact:true}).waitFor();
  await page.screenshot({path:path.resolve(__dirname,'../../docs/assets/project-workbench.png')});
  const frames=[];page.on('websocket',socket=>socket.on('framereceived',event=>frames.push(String(event.payload))));
  await page.getByRole('button',{name:'打开终端',exact:true}).click();await page.getByLabel('终端配置',{exact:true}).selectOption('python');await page.getByRole('button',{name:'新建终端',exact:true}).click();
  const waitOutput=async value=>{for(let i=0;i<100;i++){if(frames.join('').includes(value))return;await page.waitForTimeout(100);}throw Error('Missing terminal output: '+value);};
  await waitOutput('Python');const input=page.getByLabel('终端输入',{exact:true});await input.pressSequentially("print('NATIVE_'+'PROJECT_OK')");await input.press('Enter');await waitOutput('NATIVE_PROJECT_OK');
  const terminalId=await page.getByLabel('终端会话',{exact:true}).inputValue();const terminal=await(await fetch(prefix+'/terminals/'+terminalId,{headers})).json();children.push(terminal.pid);
  const version=spawnSync(python,['-I','-c','import contract_driven_ai_flow;print(contract_driven_ai_flow.__version__)'],{cwd:root,env,encoding:'utf8',windowsHide:true,timeout:10000});
  assert.equal(version.status,0);assert.equal(version.stdout.trim(),'0.6.0');assert.deepEqual(errors,[]);
  const closed=app.waitForEvent('close');await page.getByRole('button',{name:'退出并停止',exact:true}).click();await closed;
  await assert.rejects(fetch(`http://127.0.0.1:${state.port}/api/v1/studio`));assert(!fs.existsSync(path.join(root,'.cdaf/studio.json')));
  const check=spawnSync('powershell.exe',['-NoProfile','-Command',`if(Get-Process -Id ${children.join(',')} -ErrorAction SilentlyContinue){exit 1}`],{windowsHide:true,timeout:10000});assert.equal(check.status,0,'Owned PTY survived application exit');
  const receipt={version:'0.6.0',entry_kind:process.env.CDAF_DESKTOP_ENTRY_KIND||(installed?'packaged':'development'),executable:installed||require('electron'),project_id:projectId,run_id:runId,native_system_dialog_visible:nativeDialog,native_picker_ipc:true,subsequent_dialog_result_stubbed:true,cancel_then_open:true,cross_module_evidence:true,real_matrix:true,real_terminal:true,selection_p95_ms:p95,selection_samples:30,owner_cleanup:true,port_released:true,result:'passed'};
  fs.writeFileSync(path.resolve(__dirname,'../../.work/project-acceptance/desktop-project-'+receipt.entry_kind+'.json'),JSON.stringify(receipt,null,2));console.log(JSON.stringify(receipt));
 }catch(error){
  const page=await app.firstWindow().catch(()=>null);
  if(page){
   console.error('Project status:',await page.locator('.wb-statusbar').innerText().catch(()=>'(renderer unavailable)'));
   console.error('Panels:',await page.locator('.workspace-document[aria-hidden=false]').allTextContents());
   console.error('Tabs:',await page.getByRole('tab').evaluateAll(elements=>elements.map(element=>({name:element.textContent,selected:element.getAttribute('aria-selected')}))));
   await page.screenshot({path:path.resolve(__dirname,'../../.work/project-acceptance/native-project-failure.png')}).catch(()=>{});
  }
  throw error;
 }
 finally{await app.close().catch(()=>{});}
})().catch(error=>{console.error(error);process.exitCode=1;});
