const {_electron:electron}=require('../../web/node_modules/playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');const path=require('node:path');const os=require('node:os');
(async()=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'cdaf-terminal-native-'));
 const installed=process.env.CDAF_DESKTOP_TEST_EXE;
 const env={...process.env,PYTHONUTF8:'1'};
 if(installed)delete env.CDAF_DESKTOP_PYTHON;else env.CDAF_DESKTOP_PYTHON=path.resolve(__dirname,'../../.work/desktop-python/python.exe');
 const app=await electron.launch({executablePath:installed||require('electron'),args:installed?['--project',root]:[path.resolve(__dirname,'../src/main.cjs'),'--project',root],env,timeout:30000});
 try{
  const window=await app.firstWindow();try{await window.getByRole('button',{name:'运行',exact:true}).waitFor({timeout:30000});}catch(e){console.error(await window.locator('body').innerText());throw e;}
  await window.getByRole('button',{name:'打开终端',exact:true}).click();
  await window.getByLabel('终端配置').selectOption('python');await window.getByRole('button',{name:'新建终端',exact:true}).click();
  await window.getByLabel('终端输入',{exact:true}).waitFor();await window.getByLabel('终端输入',{exact:true}).focus();await window.keyboard.insertText("print('NATIVE-'+str(6*7)+' 中文')");await window.keyboard.press('Enter');await window.getByLabel('无障碍输出',{exact:true}).check();
  const deadline=Date.now()+15000;let text='';while(Date.now()<deadline){text=await window.locator('.xterm-accessibility-tree').innerText();if(text.includes('NATIVE-42 中文'))break;await new Promise(r=>setTimeout(r,50));}
  assert(text.includes('NATIVE-42 中文'),text);
  const id=await window.getByLabel('终端会话').inputValue();const record=JSON.parse(fs.readFileSync(path.join(root,'.cdaf/studio.json'),'utf8'));
  const state=await (await fetch(`http://127.0.0.1:${record.port}/api/v1/research/terminals/${id}`,{headers:{Authorization:'Bearer '+record.token}})).json();assert.equal(state.status,'running');
  const children=[state.pid];
  const output=async marker=>{const until=Date.now()+20000;let actual='';while(Date.now()<until){actual=await window.locator('.xterm-accessibility-tree').innerText();if(actual.includes(marker))return;await new Promise(r=>setTimeout(r,100));}throw new Error('Terminal output missing '+marker+': '+actual.slice(-1500));};
  await window.getByLabel('终端配置').selectOption('cli');await window.getByRole('button',{name:'新建终端',exact:true}).click();
  await output('Scientific');await window.getByLabel('终端输入',{exact:true}).focus();await window.keyboard.type('/help');await window.keyboard.press('Enter');await output('/workbench');
  const cliId=await window.getByLabel('终端会话').inputValue();const cliState=await(await fetch(`http://127.0.0.1:${record.port}/api/v1/research/terminals/${cliId}`,{headers:{Authorization:'Bearer '+record.token}})).json();assert.equal(cliState.status,'running');children.push(cliState.pid);
  await window.getByLabel('终端配置').selectOption('shell');await window.getByRole('button',{name:'新建终端',exact:true}).click();await output('PS ');await window.getByLabel('终端输入',{exact:true}).focus();await window.keyboard.type("$taskValue=6*7;Write-Output ('SHELL-'+$taskValue+' '+[char]0x4e2d+[char]0x6587)");await window.keyboard.press('Enter');await output('SHELL-42 中文');
  const shellId=await window.getByLabel('终端会话').inputValue();const shellState=await(await fetch(`http://127.0.0.1:${record.port}/api/v1/research/terminals/${shellId}`,{headers:{Authorization:'Bearer '+record.token}})).json();children.push(shellState.pid);
  await window.screenshot({path:path.resolve(__dirname,'../../docs/assets/research-embedded-terminal.png')});
  const closed=app.waitForEvent('close');await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].close());await closed;
  await assert.rejects(fetch(`http://127.0.0.1:${record.port}/api/v1/studio`));
  const {spawnSync}=require('node:child_process');const check=spawnSync('powershell.exe',['-NoProfile','-Command',`if(Get-Process -Id ${children.join(',')} -ErrorAction SilentlyContinue){exit 1}`],{windowsHide:true,timeout:10000});assert.equal(check.status,0,'Terminal child survived its owning window');
  fs.writeFileSync(path.resolve(__dirname,'../../docs/assets/research-embedded-terminal-validation.json'),JSON.stringify({platform:process.platform,installed:!!installed,unicode:true,real_python:true,real_cli:true,real_shell:true,concurrent_sessions:3,owner_exit_cleanup:true,port_released:true,result:'passed'},null,2));
 }finally{await app.close().catch(()=>{});}
})().catch(e=>{console.error(e);process.exitCode=1;});
