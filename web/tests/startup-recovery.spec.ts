import {test,expect} from '@playwright/test';
import {session} from './session';
import {researchApi,runCompute,selectObject,chooseExample} from './scientific-helpers';
import {writeFileSync} from 'node:fs';
import {join} from 'node:path';

test('background source import preserves a pressed settings control',async({page})=>{
 let release!:()=>void,requested!:()=>void;
 const pending=new Promise<void>(resolve=>release=resolve);
 const sourceRequested=new Promise<void>(resolve=>requested=resolve);
 let first=true;
 await page.route('**/workbench/analyses/*/source',async route=>{
  if(first){first=false;requested();await pending;}
  await route.continue();
 });
 try{
  await page.goto('http://127.0.0.1:8879/#session='+session);
  await sourceRequested;
  await page.getByRole('button',{name:'设置',exact:true}).click();
  await expect(page.getByLabel('主题',{exact:true})).toBeVisible();
  const category=page.getByRole('navigation',{name:'设置分类'}).getByRole('button',{name:'计算关系图',exact:true});
  const main=page.locator('.dv-groupview[data-group="main"]');
  await expect(main).toHaveClass(/dv-active-group/);
  const point=(await category.boundingBox())!;
  // Complete the actual background import between press and release.
  // Reactivating a visible tab used to detach it and suppress its click.
  await page.mouse.move(point.x+point.width/2,point.y+point.height/2);
  await page.mouse.down();
  const sourceResponse=page.waitForResponse(r=>r.url().includes('/workbench/analyses/')&&r.url().endsWith('/source'));
  release();
  await sourceResponse;
  await expect(page.getByText('已解析',{exact:true})).toBeVisible();
  await page.evaluate(()=>new Promise<void>(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve()))));
  await expect(main).toHaveClass(/dv-active-group/);
  await page.mouse.up();
  await expect(category).toHaveAttribute('aria-pressed','true');
  await expect(page.getByLabel('淡化无关对象',{exact:true})).toBeVisible();
  await expect(page.getByLabel('源码对象')).toBeVisible();
  await page.getByRole('navigation',{name:'工作区'}).getByRole('button',{name:'源码',exact:true}).click();
  await expect(page.locator('.dv-groupview[data-group="source"]')).toHaveClass(/dv-active-group/);
  await page.getByRole('button',{name:'设置',exact:true}).click();
  await expect(main).toHaveClass(/dv-active-group/);
 }finally{release();}
});

test('a slow graph view keeps the existing probe panel usable',async({page})=>{
 let release!:()=>void,requested!:()=>void;
 const pending=new Promise<void>(resolve=>release=resolve);
 const graphRequested=new Promise<void>(resolve=>requested=resolve);
 await page.route('**/assets/RelationGraph-*.js',async route=>{
  requested();await pending;await route.continue();
 });
 try{
  await page.goto('http://127.0.0.1:8879/#session='+session);
  await expect(page.getByRole('button',{name:'运行',exact:true})).toBeEnabled();
  await page.getByRole('button',{name:'探针台',exact:true}).first().click();
  await expect(page.getByRole('button',{name:'添加探针',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'计算关系图',exact:true}).first().click();
  await graphRequested;
  await expect(page.getByRole('button',{name:'添加探针',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'添加探针',exact:true}).click();
  await expect(page.getByLabel('探针类型')).toBeVisible();
  release();
  await expect(page.getByTestId('relation-node').first()).toBeVisible();
 }finally{release();}
});

test('failed entry script shows recovery and reload opens the actual workbench',async({page})=>{
 const blocked='**/assets/index-*.js';
 await page.route(blocked,r=>r.abort('failed'));
 await page.goto('http://127.0.0.1:8879/#session='+session);
 await expect(page.getByRole('alert')).toContainText('界面资源未能加载');
 await expect(page.getByRole('button',{name:'重试加载',exact:true})).toBeVisible();
 await page.unroute(blocked);
 await page.getByRole('button',{name:'重试加载',exact:true}).click();
 await expect(page.getByRole('button',{name:'运行',exact:true})).toBeVisible();
 await expect(page.getByRole('tree',{name:'计算对象树'})).toBeVisible();
});

test('probe filtering binds the displayed definition rather than a hidden previous choice',async({page})=>{
 await page.goto('http://127.0.0.1:8879/#session='+session);
 await expect(page.getByRole('button',{name:'运行',exact:true})).toBeEnabled();
 await page.getByRole('button',{name:'探针台',exact:true}).first().click();
 await page.getByRole('button',{name:'添加探针',exact:true}).click();
 await page.getByLabel('探针类型').selectOption('view.matplotlib');
 await page.getByLabel('新探针用途').selectOption('check');
 await expect(page.getByLabel('探针类型')).toHaveValue('check.finite');
 await page.getByRole('button',{name:'确认添加探针',exact:true}).click();
 const written=page.waitForResponse(r=>r.url().endsWith('/workbench/configuration')&&r.request().method()==='PUT');
 await page.getByRole('button',{name:'保存',exact:true}).click();
 expect((await written).ok()).toBe(true);
 const saved=await researchApi(page,'research/workbench/configuration');
 expect(saved.probes.at(-1).definition_id).toBe('check.finite');
});

test('failed initial API loading offers an explicit retry',async({page})=>{
 let failed=true;
 await page.route('**/api/v1/research/info',route=>failed?route.fulfill({status:503,json:{detail:'Fixture backend not ready'}}):route.continue());
 await page.goto('http://127.0.0.1:8879/#session='+session);
 await expect(page.getByRole('alert').filter({hasText:'项目未能加载'})).toBeVisible();
 failed=false;
 await page.getByRole('button',{name:'重试连接',exact:true}).click();
 await expect(page.getByRole('tree',{name:'计算对象树'})).toBeVisible();
 await expect(page.getByRole('button',{name:'运行',exact:true})).toBeEnabled();
});

test('searching a settings category retains its editable fields',async({page})=>{
 await page.goto('http://127.0.0.1:8879/#session='+session);
 await page.getByRole('button',{name:'设置',exact:true}).click();
 await page.getByLabel('搜索设置').fill('工作区');
 await expect(page.getByLabel('主题',{exact:true})).toBeVisible();
 await expect(page.getByLabel('对象栏宽度',{exact:true})).toBeVisible();
});

test('the library can request the same probe twice and opens an actionable binding range',async({page})=>{
 await page.goto('http://127.0.0.1:8879/#session='+session);
 await expect(page.getByRole('button',{name:'运行',exact:true})).toBeEnabled();
 await page.getByRole('button',{name:'探针库',exact:true}).first().click();
 const auto=page.locator('.library-definition').filter({hasText:'自动数据视图'});
 await auto.getByRole('button',{name:'绑定',exact:true}).click();
 await expect(page.getByLabel('探针绑定范围')).toHaveValue('project');
 await expect(page.getByRole('button',{name:'确认添加探针',exact:true})).toBeEnabled();
 await page.getByRole('button',{name:'确认添加探针',exact:true}).click();
 await page.getByRole('button',{name:'探针库',exact:true}).first().click();
 await auto.getByRole('button',{name:'绑定',exact:true}).click();
 await expect(page.getByRole('button',{name:'确认添加探针',exact:true})).toBeEnabled();
});

test('a renderer failure stays inside its view and can be retried',async({page})=>{
 // Corrupt a delivered schema at the API boundary; it crashes the real
 // ParameterForm instead of inventing a production test-only throw path.
 let breakSchema=true;
 await page.route('**/workbench/probe-definitions',async route=>{
  const response=await route.fetch();const data=await response.json();
  if(breakSchema) data.find((d:any)=>d.id==='view.matrix').parameter_schema={properties:{palette:{type:'string',enum:{invalid:true}}}};
  await route.fulfill({response,json:data});
 });
 await page.goto('http://127.0.0.1:8879/#session='+session);
 await page.getByRole('button',{name:'探针台',exact:true}).first().click();
 await page.getByRole('button',{name:'添加探针',exact:true}).click();
 await expect(page.getByRole('alert').filter({hasText:'视图未能显示'})).toBeVisible();
 await expect(page.getByRole('button',{name:'运行',exact:true})).toBeVisible();
 await page.getByRole('button',{name:'设置',exact:true}).click();
 await expect(page.getByLabel('搜索设置')).toBeVisible();
 breakSchema=false;
 await page.reload();
 await page.getByRole('button',{name:'探针台',exact:true}).first().click();
 await page.getByRole('button',{name:'添加探针',exact:true}).click();
 await page.getByLabel('探针类型').selectOption('view.matrix');
 await expect(page.getByRole('button',{name:'确认添加探针',exact:true})).toBeEnabled();
});

test('historical source definitions select their own analysis after a new import',async({page})=>{
 await page.goto('http://127.0.0.1:8879/#session='+session);
 await expect(page.getByRole('button',{name:'运行',exact:true})).toBeEnabled();
 const info=await researchApi(page,'research/info');
 const script=join(info.root,'historical-source-audit.py');
 const importFile=async()=>{
  await page.getByRole('button',{name:'打开源码配置'}).click();
  await page.getByLabel('分析脚本',{exact:true}).fill(script);
  const response=page.waitForResponse(r=>r.url().endsWith('/workbench/analyses')&&r.request().method()==='POST');
  await page.getByRole('button',{name:'导入解析',exact:true}).click();
  const result=await(await response).json();
  await page.getByRole('button',{name:'打开源码配置'}).click();
  return result;
 };
 writeFileSync(script,'X=1\nY=X+1\n','utf8');
 const previous=await importFile();
 await runCompute(page);
 const run=await page.getByLabel('运行记录').inputValue();
 writeFileSync(script,'NEW=100\n','utf8');
 await importFile();
 await page.getByLabel('运行记录').selectOption(run);
 const row=await selectObject(page,'X');
 await row.click({button:'right'});
 await page.getByRole('button',{name:'定位源码',exact:true}).click();
 const dropdown=page.getByLabel('源码对象').filter({has:page.locator('option',{hasText:'Y · L2'})});
 await expect(dropdown).toBeVisible();
 await dropdown.selectOption(previous.objects.find((o:any)=>o.name==='Y').id);
 await expect(page.getByTestId('source-selection').last()).toContainText('Y=X+1');
 await page.getByRole('searchbox',{name:'搜索对象',exact:true}).fill('Y');
 const selected=page.locator('[role="treeitem"][aria-selected="true"]').filter({hasText:'Y'});
 await expect(selected).toBeVisible();
 await chooseExample(page);
});

test('result history offers another page rather than silently dropping older results',async({page})=>{
 await page.goto('http://127.0.0.1:8879/#session='+session);
 await chooseExample(page);await runCompute(page);
 const run=await page.getByLabel('运行记录').inputValue();
 const actual=await researchApi(page,'research/workbench/outputs?run_id='+run);
 expect(actual.length).toBeGreaterThan(0);
 const sample=actual[0];
 await page.route('**/workbench/outputs?*',route=>{
  const query=new URL(route.request().url()).searchParams;
  if(query.get('run_id')!==run)return route.continue();
  const count=query.get('before')?2:1000;
  const outputs=Array.from({length:count},(_,i)=>({...sample,id:(query.get('before')?'older-':'recent-')+i}));
  return route.fulfill({json:outputs});
 });
 await page.getByLabel('运行记录').selectOption('');
 await page.getByLabel('运行记录').selectOption(run);
 await page.getByRole('button',{name:/^探针结果 ·/}).click();
 await expect(page.getByRole('button',{name:'读取更多结果',exact:true})).toBeVisible();
 const second=page.waitForRequest(r=>new URL(r.url()).searchParams.get('before')==='recent-999');
 await page.getByRole('button',{name:'读取更多结果',exact:true}).click();await second;
 await expect(page.getByRole('button',{name:'探针结果 · 1002',exact:true})).toBeVisible();
 await expect(page.getByRole('button',{name:'读取更多结果',exact:true})).toHaveCount(0);
});

for(const returnFirst of [false,true]){
test('leaving a pending result page allows a fresh request '+(returnFirst?'before the old reply':'after the old reply'),async({page})=>{
 await page.goto('http://127.0.0.1:8879/#session='+session);
 await chooseExample(page);await runCompute(page);
 const first=await page.getByLabel('运行记录').inputValue();
 const actual=await researchApi(page,'research/workbench/outputs?run_id='+first);
 expect(actual.length).toBeGreaterThan(0);
 await runCompute(page);
 const second=await page.getByLabel('运行记录').inputValue();
 expect(second).not.toBe(first);
 let release!:()=>void;
 const pending=new Promise<void>(resolve=>release=resolve);
 let pages=0;
 await page.route('**/workbench/outputs?*',async route=>{
  const query=new URL(route.request().url()).searchParams;
  if(query.get('run_id')!==first)return route.continue();
  if(query.get('before')){
   pages++;
   const old=pages===1;
   if(old)await pending;
   return route.fulfill({json:[{...actual[0],id:old?'stale-page':'fresh-page'}]});
  }
  return route.fulfill({json:Array.from({length:1000},(_,i)=>({...actual[0],id:'recent-'+i}))});
 });
 await page.getByLabel('运行记录').selectOption(first);
 await page.getByRole('button',{name:/^探针结果 ·/}).click();
 await expect(page.getByRole('button',{name:'读取更多结果',exact:true})).toBeEnabled();
 const started=page.waitForRequest(r=>new URL(r.url()).searchParams.get('before')==='recent-999');
 await page.getByRole('button',{name:'读取更多结果',exact:true}).click();await started;
 await page.getByLabel('运行记录').selectOption(second);
 const completed=page.waitForResponse(async r=>new URL(r.url()).searchParams.get('before')==='recent-999'&&(await r.json())[0]?.id==='stale-page');
 if(!returnFirst){release();await completed;}
 await page.getByLabel('运行记录').selectOption(first);
 await expect(page.getByRole('button',{name:'读取更多结果',exact:true})).toBeEnabled();
 await page.getByRole('button',{name:'读取更多结果',exact:true}).click();
 await expect(page.getByRole('button',{name:'探针结果 · 1001',exact:true})).toBeVisible();
 if(returnFirst){release();await completed;}
 await expect(page.getByRole('button',{name:'探针结果 · 1001',exact:true})).toBeVisible();
 expect(pages).toBe(2);
});
}
