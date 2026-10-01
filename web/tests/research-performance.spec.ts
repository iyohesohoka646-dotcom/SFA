import { expect, test } from '@playwright/test';

test.use({baseURL: 'http://127.0.0.1:8879'});
test('research-performance: 1000 values and 10000 events stay interactive', async ({page}) => {
  await page.addInitScript(()=>{
    const measurements={paint:[] as number[],api:[] as {url:string;duration:number}[],longTasks:[] as number[]};
    (window as unknown as {researchPerformance:typeof measurements}).researchPerformance=measurements;
    for(const name of ['input','click'])document.addEventListener(name,event=>{
      if(!(event.target instanceof Element) || !event.target.closest('.research-app'))return;
      const start=performance.now();requestAnimationFrame(()=>measurements.paint.push(performance.now()-start));
    },true);
    const original=window.fetch;
    window.fetch=async(...args)=>{const start=performance.now();try{return await original(...args);}finally{measurements.api.push({url:String(args[0]),duration:performance.now()-start});}};
    new PerformanceObserver(list=>{measurements.longTasks.push(...list.getEntries().map(e=>e.duration));}).observe({type:'longtask',buffered:true});
  });
  await page.goto('/#session=research-test-session');
  await expect(page.getByRole('heading', {name: 'Scientific Dataflow Inspector'})).toBeVisible();
  await page.getByLabel('运行记录').selectOption({label:await page.getByLabel('运行记录').locator('option').filter({hasText:'Analysis · completed'}).last().textContent()||''});
  await expect(page.getByTestId('variable-count')).toHaveText('1000');
  await page.getByRole('button',{name:'展开运算链',exact:true}).click();
  await expect(page.getByTestId('flow-node')).toHaveCount(80);
  for (const name of ['X999', 'X7', 'X20', 'X999', 'X15', 'X7', 'X81', 'X999', 'X0', 'X1']) {
    await page.getByRole('searchbox', {name: '搜索变量'}).fill(name);
    await page.getByRole('button', {name: new RegExp(`^${name} ·`)}).first().click();
    await expect(page.getByTestId('current-variable')).toHaveText(name);
    await expect(page.getByTestId('detail-status')).toHaveText('详情已就绪');
  }
  const measured=await page.evaluate(()=>({...(window as unknown as {researchPerformance:Record<string,unknown>}).researchPerformance,ready:performance.now()}));
  const metrics=measured.paint as number[],sorted = metrics.sort((a,b)=>a-b);
  expect(sorted[Math.ceil(sorted.length*0.95)-1]).toBeLessThanOrEqual(100);
  const details=(measured.api as {url:string;duration:number}[]).filter(m=>m.url.includes('/snapshots/')).map(m=>m.duration).sort((a,b)=>a-b);
  expect(details[Math.ceil(details.length*.95)-1]).toBeLessThanOrEqual(250);
  await test.info().attach('paint-latency.json', {body:JSON.stringify({...measured,count: metrics.length,p50:sorted[Math.floor(sorted.length*.5)],p95:sorted[Math.ceil(sorted.length*.95)-1],detailP95:details[Math.ceil(details.length*.95)-1]}), contentType:'application/json'});
});

test('research-performance: slow details do not disable input and selection', async ({page}) => {
  let release: () => void = () => {};
  let started:()=>void=()=>{};const pending=new Promise<void>(resolve=>{started=resolve;});
  await page.route('**/research/snapshots/*', async route => {
    if (route.request().url().endsWith('s7-10')){started();await new Promise<void>(resolve => {release = resolve;});}
    await route.continue().catch(()=>{});
  });
  await page.goto('/#session=research-test-session');
  await page.getByLabel('运行记录').selectOption({label:await page.getByLabel('运行记录').locator('option').filter({hasText:'Analysis · completed'}).last().textContent()||''});
  const search = page.getByRole('searchbox', {name: '搜索变量'});
  await expect(page.getByTestId('variable-count')).toHaveText('1000');
  await search.fill('X7');
  await page.getByRole('button', {name: /^X7 ·/}).first().click();
  await pending;
  await search.fill('X999');
  await page.getByRole('button', {name: /^X999 ·/}).first().click();
  await expect(page.getByTestId('current-variable')).toHaveText('X999');
  release();
  await expect(page.getByTestId('current-variable')).toHaveText('X999');
});
