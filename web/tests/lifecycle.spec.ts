import {test,expect} from '@playwright/test';
import {spawnSync} from 'node:child_process';
import {mkdtempSync,readFileSync,existsSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';

test('lifecycle: refresh, background and multiple tabs preserve the service until last close',async({browser})=>{
 const root=mkdtempSync(join(tmpdir(),'cdaf-browser-lifecycle-'));
 const python=resolve(process.platform==='win32'?'../.venv/Scripts/python.exe':'../.venv/bin/python');
 const script='import json,sys;from pathlib import Path;from contract_driven_ai_flow.studio import start;print(json.dumps(start(Path(sys.argv[1]),owned=True)))';
 const launched=spawnSync(python,['-X','utf8','-c',script,root],{encoding:'utf8',timeout:30000});
 expect(launched.status,launched.stderr).toBe(0);
 const handle=JSON.parse(launched.stdout);const state=join(root,'.cdaf/studio.json');
 const context=await browser.newContext();const page=await context.newPage();
 try{
  await page.goto(handle.url);await expect(page.getByRole('heading',{name:'Scientific Dataflow Inspector'})).toBeVisible();
  await expect(page.getByRole('button',{name:'退出并停止'})).toBeVisible();
  const second=await context.newPage();await second.goto(handle.url);
  await page.reload();await expect(page.getByRole('button',{name:'退出并停止'})).toBeVisible();
  await page.close();await second.waitForTimeout(3500);expect(existsSync(state)).toBe(true);
  await second.close();await expect.poll(()=>existsSync(state),{timeout:10000}).toBe(false);
 }finally{
  await context.close();
  if(existsSync(state)){
   const record=JSON.parse(readFileSync(state,'utf8'));
   await fetch(`http://127.0.0.1:${record.port}/api/v1/studio/shutdown`,{method:'POST',headers:{Authorization:'Bearer '+record.token}}).catch(()=>{});
  }
 }
});
