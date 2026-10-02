import {test,expect} from '@playwright/test';
import {session} from './session';
import {researchApi} from './scientific-helpers';
test('presentation is governed by default probe, deletion persists, local controls and library are visible',async({page})=>{
 const errors:string[]=[];page.on('pageerror',e=>{errors.push(e.message);console.log('Browser error:',e.stack);});
 await page.goto('http://127.0.0.1:8879/#session='+session);
 const cfg=await researchApi(page,'research/workbench/configuration');
 const runs=await researchApi(page,'research/runs');
 const run=runs.find((r:any)=>r.name==='Analysis');
 await page.getByLabel('运行记录').selectOption(run.id);
 await page.getByLabel('搜索对象',{exact:true}).fill('X7');
 const row=page.locator('.object-row-name').filter({hasText:/^X7$/}).locator('..');await expect(row).toBeVisible();await row.dblclick();
 await expect(page.getByRole('img',{name:'矩阵热图',exact:true})).toBeVisible();
 await page.getByRole('button',{name:'探针台',exact:true}).first().click();
 await page.getByLabel('启用 view.auto',{exact:true}).uncheck();
 await page.getByRole('button',{name:'保存',exact:true}).click();
 await expect(page.getByRole('img',{name:'矩阵热图',exact:true})).not.toBeVisible();
 await expect(page.getByText('没有有效呈现探针',{exact:true})).toBeVisible();
 await page.reload();await expect(page.getByText('没有有效呈现探针',{exact:true})).toBeVisible();expect(errors).toEqual([]);
 await page.getByRole('button',{name:'探针库',exact:true}).first().click();
 await expect(page.getByLabel('探针作用对象')).toBeVisible();
 await expect(page.getByLabel('探针用途')).toBeVisible();
 // Restore fixture explicitly; disabling did not resurrect itself.
 const next=await researchApi(page,'research/workbench/configuration');await researchApi(page,'research/workbench/configuration',{config:{...cfg,revision:next.revision},expected_revision:next.revision},'PUT');
});
