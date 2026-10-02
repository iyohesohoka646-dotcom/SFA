import {session} from './session';
import {expect,test} from '@playwright/test';
import {writeFileSync} from 'node:fs';
import {chooseValue,researchApi,selectObject} from './scientific-helpers';
test.use({baseURL:'http://127.0.0.1:8879'});
test('research-performance: 1000 objects select without navigation or relayout below 50 ms P95',async({page})=>{
 await page.addInitScript(()=>{
  const m={paint:[] as number[],longTasks:[] as number[],api:[] as {url:string;duration:number}[],measuring:false};
  (window as any).researchPerformance=m;
  document.addEventListener('click',event=>{if(!m.measuring||!(event.target instanceof Element)||!event.target.closest('.object-row'))return;const start=performance.now();requestAnimationFrame(()=>m.paint.push(performance.now()-start));},true);
  const fetcher=window.fetch;window.fetch=async(...args)=>{const start=performance.now();try{return await fetcher(...args);}finally{m.api.push({url:String(args[0]),duration:performance.now()-start});}};
  new PerformanceObserver(list=>m.longTasks.push(...list.getEntries().map(e=>e.duration))).observe({type:'longtask',buffered:true});
 });
 await page.goto('/#session='+session);
 const runs=await researchApi(page,'research/runs');await page.getByLabel('运行记录').selectOption(runs.find((r:any)=>r.name==='Analysis').id);
 await selectObject(page,'X7');await expect(page.locator('.object-row-name').filter({hasText:/^X7$/}).locator('..').locator('small')).toContainText('v10');
 await page.getByRole('button',{name:'计算关系图',exact:true}).first().click();
 await expect(page.getByTestId('graph-layout-metric')).toHaveText(/· [1-9]\d* ms$/);
 await expect(page.getByTestId('graph-layout-metric')).toContainText('2000 已折叠');
 expect(await page.getByTestId('relation-node').count()).toBeLessThanOrEqual(160);
 const metric=await page.getByTestId('graph-layout-metric').textContent(),camera=await page.locator('.react-flow__viewport').getAttribute('style'),tabs=await page.locator('.workspace-tab').count();
 await page.evaluate(()=>{(window as any).researchPerformance.measuring=true;});
 for(const name of ['X999','X7','X20','X0','X15','X7','X81','X999','X0','X1','X999','X7','X20','X0','X15','X7','X81','X999','X0','X1']){
  const row=await selectObject(page,name);await expect(row).toHaveAttribute('aria-selected','true');
  await page.evaluate(()=>new Promise<void>(resolve=>requestAnimationFrame(()=>resolve())));
 }
 await page.evaluate(()=>{(window as any).researchPerformance.measuring=false;});
 expect(await page.locator('.workspace-tab').count()).toBe(tabs);
 await expect(page.getByTestId('graph-layout-metric')).toHaveText(metric!);
 await expect(page.locator('.react-flow__viewport')).toHaveAttribute('style',camera!);
 await page.getByLabel('搜索对象',{exact:true}).fill('');await page.getByRole('tree',{name:'计算对象树'}).focus();await page.keyboard.press('Control+a');
 await expect(page.locator('.object-selection')).toContainText('1001 项选中');expect(await page.locator('.workspace-tab').count()).toBe(tabs);
 for(const name of ['X7','X999','X15']){await chooseValue(page,name);await expect(page.getByRole('img',{name:'矩阵热图',exact:true})).toBeVisible();}
 const measured=await page.evaluate(()=>{const m=(window as any).researchPerformance;const sorted=[...m.paint].sort((a,b)=>a-b);return {...m,paint:sorted,p95:sorted[Math.ceil(sorted.length*.95)-1],p50:sorted[Math.floor(sorted.length*.5)],count:sorted.length};});
 expect(measured.count).toBeGreaterThanOrEqual(20);expect(measured.p95).toBeLessThan(50);
 const evidence={...measured,fixture:{logical_objects:1000,versions:10,events:10000},scope:'Synthetic saved-history fixture; selection event to next animation frame, with DOM effects checked. Excludes scientific computation and cold import.'};
 await test.info().attach('paint-latency.json',{body:JSON.stringify(evidence),contentType:'application/json'});
 writeFileSync('../docs/assets/scientific-performance.json',JSON.stringify(evidence,null,2));
});
test('research-performance: slow evidence cannot replace a newer explicit selection',async({page})=>{
 let release=()=>{},started=()=>{};const pending=new Promise<void>(resolve=>{started=resolve;});
 await page.route('**/research/snapshots/s7-10',async route=>{started();await new Promise<void>(r=>{release=r;});await route.continue().catch(()=>{});});
 await page.goto('/#session='+session);const runs=await researchApi(page,'research/runs');await page.getByLabel('运行记录').selectOption(runs.find((r:any)=>r.name==='Analysis').id);
 const row=await selectObject(page,'X7');await expect(row.locator('small')).toContainText('v10');await row.dblclick();await pending;
 await chooseValue(page,'X999');await expect(page.getByTestId('current-variable').last()).toHaveText('X999');release();
 await expect(page.getByTestId('current-variable').last()).toHaveText('X999');
});
