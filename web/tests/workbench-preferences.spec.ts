import {test,expect} from '@playwright/test';
import {session} from './session';
import {researchApi,chooseExample,runCompute} from './scientific-helpers';
test('the selected current run stays visible while the history list is stale',async({page})=>{
 await page.goto('http://127.0.0.1:8879/#session='+session);
 await chooseExample(page);
 const history=await researchApi(page,'research/runs');
 await page.route('**/api/v1/research/runs',route=>route.fulfill({json:history}));
 await runCompute(page);
 const selected=await page.getByLabel('运行记录').inputValue();
 expect(selected).not.toBe('');
 expect(history.some((r:{id:string})=>r.id===selected)).toBe(false);
 await expect(page.getByLabel('运行记录').locator('option:checked')).toContainText(selected.slice(0,8));
});
test('changing run mode is configuration and does not execute until Run is pressed',async({page})=>{
 let executions=0;page.on('request',r=>{if(r.url().endsWith('/workbench/execute')||r.url().endsWith('/workbench/replot'))executions++;});
 await page.goto('http://127.0.0.1:8879/#session='+session);
 await expect(page.getByRole('button',{name:'运行',exact:true})).toBeEnabled();
 await page.getByLabel('运行模式').selectOption('replot');
 await expect(page.getByLabel('运行模式')).toHaveValue('replot');
 expect(executions).toBe(0);
});
test('saving graph preferences preserves authored capture and intelligence settings',async({page})=>{
 await page.goto('http://127.0.0.1:8879/#session='+session);
 const current=await researchApi(page,'research/workbench/configuration');
 await researchApi(page,'research/workbench/configuration',{config:{...current,capture:'sample',harness:current.harness.map((h:any)=>({...h,input_tokens:1500,include_samples:true}))},expected_revision:current.revision},'PUT');
 await page.reload();
 const before=await researchApi(page,'research/workbench/configuration');
 await page.getByRole('button',{name:'设置',exact:true}).click();
 await page.getByRole('button',{name:'计算关系图',exact:true}).last().click();
 await page.getByLabel('淡化无关对象',{exact:true}).check();
 await page.getByRole('button',{name:'保存此组设置',exact:true}).click();
 await page.getByRole('button',{name:'探针台',exact:true}).first().click();
 await page.getByRole('button',{name:'保存',exact:true}).click();
 const after=await researchApi(page,'research/workbench/configuration');
 expect(after.capture).toBe(before.capture);expect(after.harness).toEqual(before.harness);
});
test('importing a new source switches the object tree to that definition without a run',async({page})=>{
 await page.goto('http://127.0.0.1:8879/#session='+session);
 await expect(page.getByLabel('运行记录')).not.toHaveValue('');
 await page.getByRole('button',{name:'打开源码配置'}).click();
 await page.getByLabel('示例选择').selectOption('analysis');
 await page.getByRole('button',{name:'导入解析',exact:true}).click();
 await expect(page.getByLabel('运行记录')).toHaveValue('');
 await page.getByLabel('搜索对象',{exact:true}).fill('Z');
 await expect(page.locator('.object-row-name').filter({hasText:/^Z$/})).toBeVisible();
});
