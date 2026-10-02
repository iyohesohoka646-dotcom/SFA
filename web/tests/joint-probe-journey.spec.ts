import {test,expect} from '@playwright/test';
import {session} from './session';
import {chooseExample,runCompute,selectObject,researchApi,runMode} from './scientific-helpers';

let saved:any;
test.beforeEach(async({request})=>{saved=await(await request.get('http://127.0.0.1:8879/api/v1/research/workbench/configuration',{headers:{Authorization:'Bearer '+session}})).json();});
test.afterEach(async({request})=>{const url='http://127.0.0.1:8879/api/v1/research/workbench/configuration',headers={Authorization:'Bearer '+session};const now=await(await request.get(url,{headers})).json();await request.put(url,{headers,data:{config:{...saved,revision:now.revision},expected_revision:now.revision}});});

test('multi-object bindings produce comparison, exact derived data and a useful shape error',async({page})=>{
 test.setTimeout(120000);
 await page.goto('http://127.0.0.1:8879/#session='+session);
 await chooseExample(page,'analysis','full');await runCompute(page);
 const run=await page.getByLabel('运行记录').inputValue();
 const dataTabs=await page.locator('.workspace-tab').filter({hasText:/ · v\d+/}).count();
 await selectObject(page,'X');await selectObject(page,'Z',true);
 await expect(page.locator('.object-selection')).toContainText('2 项选中');
 expect(await page.locator('.workspace-tab').filter({hasText:/ · v\d+/}).count()).toBe(dataTabs);
 await page.getByRole('button',{name:'探针台',exact:true}).first().click();
 const bind=async(type:string)=>{
  await page.getByRole('button',{name:'添加探针',exact:true}).click();
  await page.getByLabel('探针绑定范围').selectOption('selection');
  await page.getByLabel('探针类型').selectOption(type);
  await expect(page.getByLabel('输入角色 left')).not.toHaveValue('');
  await expect(page.getByLabel('输入角色 right')).not.toHaveValue('');
 };
 await bind('view.compare');await page.getByLabel('共同色阶',{exact:true}).check();await page.getByLabel('联动缩放',{exact:true}).check();await page.getByRole('button',{name:'确认添加探针',exact:true}).click();
 await bind('derive.elementwise');await page.getByLabel('运算',{exact:true}).last().selectOption('subtract');await page.getByRole('button',{name:'确认添加探针',exact:true}).click();
 await bind('derive.matmul');await page.getByRole('button',{name:'确认添加探针',exact:true}).click();
 const pending=page.waitForResponse(r=>r.url().endsWith('/workbench/evaluate'));
 await runMode(page,'probes');const task=await(await pending).json();
 // Selection can change after submission; the saved input roles remain frozen.
 await selectObject(page,'X');
 await expect.poll(async()=>(await researchApi(page,'research/workbench/tasks/'+task.id)).status,{timeout:60000}).toBe('completed');
 const outputs=await researchApi(page,'research/workbench/outputs?task_id='+task.id);
 const compared=outputs.find((o:any)=>o.definition_id==='view.compare');
 const derived=outputs.find((o:any)=>o.definition_id==='derive.elementwise');
 const invalid=outputs.find((o:any)=>o.definition_id==='derive.matmul');
 expect(compared.status).toBe('ready');expect(derived.status).toBe('ready');expect(derived.data.complete_inputs).toBe(true);
 expect(invalid.status).toBe('error');expect(invalid.message).toMatch(/形状|维度|shape/i);
 const parents=await Promise.all(derived.parent_snapshot_ids.map((id:string)=>researchApi(page,'research/snapshots/'+id)));
 const result=await researchApi(page,'research/snapshots/'+derived.snapshot_id);
 expect(parents.map((p:any)=>p.name)).toEqual(['X','Z']);expect(parents.every((p:any)=>p.run_id===run)).toBe(true);
 expect(result.parents).toEqual(derived.parent_snapshot_ids);
 expect(result.sample.values[0][0]).toBeCloseTo(parents[0].sample.values[0][0]-parents[1].sample.values[0][0],8);
 await page.getByRole('button',{name:/^探针结果 ·/}).click();
 await page.getByLabel('结果探针').selectOption('view.compare');await page.locator('.wb-result-row').filter({hasText:'view.compare'}).first().click();
 await expect(page.locator('.comparison-input')).toHaveCount(2);await expect(page.getByLabel('联动缩放',{exact:true})).toBeVisible();
 await page.getByRole('tab',{name:'任务与结果',exact:true}).click();
 await page.getByLabel('结果探针').selectOption('derive.elementwise');await page.locator('.wb-result-row').filter({hasText:'derive.elementwise'}).first().click();
 await expect(page.getByRole('button',{name:'生成代码提案',exact:true})).toBeVisible();
 await page.getByRole('button',{name:'打开数据',exact:true}).last().click();
 await expect(page.getByRole('img',{name:'矩阵热图',exact:true}).last()).toBeVisible();
 await page.getByTestId('matrix-color-legend').last().waitFor();
 await page.screenshot({path:'../docs/assets/scientific-joint-derived.png'});
});
