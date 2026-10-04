import {test,expect} from '@playwright/test';
import {session} from './session';
import {researchApi} from './scientific-helpers';

const configurationUrl='http://127.0.0.1:8879/api/v1/research/workbench/configuration';
const headers={Authorization:'Bearer '+session};
let originalConfiguration:any;
test.beforeEach(async({request})=>{
 const response=await request.get(configurationUrl,{headers});expect(response.ok()).toBe(true);
 originalConfiguration=await response.json();
});
test.afterEach(async({request})=>{
 const response=await request.get(configurationUrl,{headers});expect(response.ok()).toBe(true);
 const current=await response.json();
 const restored=await request.put(configurationUrl,{headers,data:{config:{...originalConfiguration,revision:current.revision},expected_revision:current.revision}});
 expect(restored.ok()).toBe(true);
});

test('presentation is governed by default probe, disabling persists, local controls and library are visible',async({page})=>{
 const errors:string[]=[];page.on('pageerror',e=>{errors.push(e.message);console.log('Browser error:',e.stack);});
 await page.goto('http://127.0.0.1:8879/#session='+session);
 const cfg=await researchApi(page,'research/workbench/configuration');
 const runs=await researchApi(page,'research/runs');
 const run=runs.find((r:any)=>r.name==='Analysis');
 await page.getByLabel('运行记录').selectOption(run.id);
 await page.getByLabel('搜索对象',{exact:true}).fill('X7');
 const row=page.locator('.object-row-name').filter({hasText:/^X7$/}).locator('..');await expect(row).toBeVisible();
 await expect(row.locator('.object-shape')).not.toHaveText('—');await row.dblclick();
 await expect(page.getByRole('img',{name:'矩阵热图',exact:true})).toBeVisible();
 await page.getByRole('button',{name:'探针台',exact:true}).first().click();
 const inspector=page.locator('.wb-inspector').filter({visible:true}).filter({has:page.locator('.wb-view-toolbar > strong').filter({hasText:/^探针台$/})}).first();
 await inspector.getByRole('button',{name:'自动数据视图',exact:true}).click();
 await inspector.getByRole('button',{name:'编辑源绑定',exact:true}).click();
 const projectBindings=inspector.locator('.probe-project-bindings').filter({has:page.locator('summary',{hasText:'编辑源绑定'})});
 await expect(projectBindings).toBeVisible();
 if(await projectBindings.getAttribute('open')===null)await projectBindings.locator('summary').click();
 await expect(projectBindings).toHaveJSProperty('open',true);
 await projectBindings.getByLabel('启用 view.auto',{exact:true}).uncheck();
 const saved=page.waitForResponse(response=>response.url().endsWith('/workbench/configuration')&&response.request().method()==='PUT');
 await inspector.getByRole('button',{name:'保存',exact:true}).click();
 const response=await saved;expect(response.ok()).toBe(true);
 const disabled=await response.json(),defaultProbe=cfg.probes.find((probe:any)=>probe.definition_id==='view.auto');
 expect(defaultProbe).toBeDefined();
 expect(disabled.probes.find((probe:any)=>probe.id===defaultProbe.id).enabled).toBe(false);
 await expect(page.getByRole('img',{name:'矩阵热图',exact:true})).not.toBeVisible();
 await expect(page.locator('.wb-data-content')).toBeEmpty();
 await page.reload();await expect(page.locator('.wb-data-content')).toBeEmpty();expect(errors).toEqual([]);
 const persisted=await researchApi(page,'research/workbench/configuration');
 expect(persisted.probes.find((probe:any)=>probe.id===defaultProbe.id).enabled).toBe(false);
 await page.getByRole('button',{name:'探针库',exact:true}).first().click();
 await expect(page.getByLabel('探针作用对象')).toBeVisible();
 await expect(page.getByLabel('探针用途')).toBeVisible();
});
