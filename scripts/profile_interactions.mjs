import { createRequire } from 'node:module';
import { writeFile } from 'node:fs/promises';
const require = createRequire(new URL('../web/package.json', import.meta.url));
const { chromium } = require('@playwright/test');
const browser = await chromium.launch({ channel: process.platform === 'win32' ? 'msedge' : undefined });
const page = await browser.newPage({viewport:{width:1600,height:1000},reducedMotion:'reduce'});
const reports = [];
try {
  for (const [name, id, count] of [['small',process.env.PROFILE_SMALL,4],['large-folded',process.env.PROFILE_LARGE,30]]) {
    const requests=[];
    page.on('response', async response => {if(response.url().includes('/api/')) requests.push({path:new URL(response.url()).pathname,status:response.status(),timing:response.request().timing()});});
    const started = performance.now();
    await page.goto(`${process.env.PROFILE_URL}/p/${id}/#session=profile-session`);
    await page.locator('.react-flow__node').nth(count-1).waitFor();
    const loadMs=performance.now()-started;
    const search=page.getByLabel('Search modules');
    const latencies=[];
    for(const term of ['step','summary','group','']) {const t=performance.now();await search.fill(term);await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));latencies.push(performance.now()-t);}
    reports.push({name,visible_nodes:count,load_and_layout_ms:loadMs,search_ms:latencies,requests});
    await writeFile(process.env.PROFILE_OUTPUT,JSON.stringify({measured_at:new Date().toISOString(),browser:process.platform==='win32'?'Edge':'Chromium',reports},null,2));
    page.removeAllListeners('response');
  }
  await page.goto(`${process.env.PROFILE_URL}/p/${process.env.PROFILE_SMALL}/#session=profile-session`);
  await page.locator('.react-flow__node').nth(3).waitFor();
  await page.getByRole('button',{name:'Context',exact:true}).click();
  let release, startedContext;const held = new Promise(resolve=>release=resolve);const pending=new Promise(resolve=>startedContext=resolve);
  await page.route('**/api/v1/context/*',async route=>{startedContext();await held;await route.continue();},{times:1});
  const responsePromise=page.waitForResponse(response=>response.url().includes('/api/v1/context/'));
  await page.getByRole('button',{name:'Inspect exact context'}).click();
  await pending;
  const runBlocked=await page.getByRole('button',{name:'Generate from offline fixtures'}).isDisabled();
  await page.locator('[data-id="normalize"]').click();
  await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  release();
  const response=await responsePromise;
  await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  const staleContext=await page.locator('.context-json').count()?await page.locator('.context-json').innerText():'';
  reports.push({name:'context-request-race',selected:'normalize',response_status:response.status(),previous_response_displayed:staleContext.includes('summarize'),response_not_displayed:!staleContext,generation_blocked_by_unrelated_context:runBlocked,error:await page.locator('.notice.error').allTextContents()});
  await writeFile(process.env.PROFILE_OUTPUT,JSON.stringify({measured_at:new Date().toISOString(),browser:process.platform==='win32'?'Edge':'Chromium',reports},null,2));
  process.stdout.write(JSON.stringify(reports.map(({requests,...report})=>report))+'\n');
}finally{await browser.close();}
