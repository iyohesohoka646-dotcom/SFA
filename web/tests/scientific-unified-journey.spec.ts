import { expect, test } from '@playwright/test';
import { session } from './session';
import { chooseValue, researchApi } from './scientific-helpers';
import { writeFileSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

test('probe configuration is inert and execution produces real views and checks', async ({ page }) => {
  let executions = 0;
  page.on('request', request => { if (request.url().endsWith('/execute')) executions++; });
  await page.goto('http://127.0.0.1:8879/#session=' + session);
  await expect(page.getByRole('button', { name: '导入解析', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '打开源码配置' }).click();
  await page.getByLabel('示例选择').selectOption('analysis');
  await page.getByRole('button', { name: '导入解析', exact: true }).click();
  await page.getByRole('button', { name: '打开源码配置' }).click();
  await page.getByRole('button', { name: '探针台', exact: true }).first().click();
  await page.getByRole('button', { name: '添加探针', exact: true }).click();
  await page.getByLabel('探针类型').selectOption('view.relationships');
  await page.getByLabel('探针绑定').fill('*');
  await page.getByRole('button', { name: '确认添加探针' }).click();
  expect(executions).toBe(0);
  await page.getByRole('button', { name: '运行', exact: true }).click();
  await expect(page.getByTestId('task-record').first().locator('strong > span')).toHaveText('completed', { timeout: 60000 });
  await page.getByRole('button', { name: '探针台', exact: true }).first().click();
  await expect(page.getByTestId('probe-output').first()).toBeVisible();
  await page.getByRole('button', { name: '计算关系图', exact: true }).first().click();
  await expect(page.getByTestId('relation-node').first()).toBeVisible();
  await page.getByTestId('relation-node').first().click();
  await expect(page.locator('.relation-focus')).toBeVisible();
});

test('fixed data versions remain visible side by side across selection and reload', async ({ page }) => {
  await page.goto('http://127.0.0.1:8879/#session=' + session);
  const runs = await researchApi(page, 'research/runs');
  await page.getByLabel('运行记录').selectOption(runs.find((r: {source_digest:string;name:string}) => r.source_digest === 'fixture-source' && !r.name?.includes('Point cloud')).id);
  await chooseValue(page, 'X7');
  await page.getByRole('button', { name: '查看变量历史', exact: true }).click();
  await page.getByRole('button', { name: '并排固定此版本', exact: true }).click();
  await chooseValue(page, 'X7');
  await page.getByRole('button', { name: '查看变量历史', exact: true }).first().click();
  await page.getByRole('button', { name: '版本 1', exact: true }).first().click();
  await expect(page.getByTestId('matrix-definition').filter({ hasText: /v1\s·/ })).toBeVisible();
  await expect(page.getByTestId('matrix-definition').filter({ hasText: 'v10' })).toBeVisible();
  await page.screenshot({ path: '../docs/assets/scientific-compare.png' });
  await page.reload();
  await expect(page.getByTestId('matrix-definition').filter({ hasText: 'v10' })).toBeVisible();
});

test('automatic harness reads tools, proposes a scoped diff and waits for acceptance', async ({ page }) => {
  await page.goto('http://127.0.0.1:8879/#session=' + session);
  const info = await researchApi(page, 'research/info');
  const path = join(info.root, 'reviewed.py'), original = 'def calculate(x):\n    return x + 1\n\nY = calculate(3)\n';
  writeFileSync(path, original, 'utf8');
  await researchApi(page, 'settings/models/harness-lab', { profile: { id: 'harness-lab', protocol: 'openai-compatible', base_url: 'http://127.0.0.1:8879/fake-model/v1', default_model: 'harness-model' } }, 'PUT');
  await page.getByRole('button', { name: '打开源码配置' }).click(); await page.getByLabel('分析脚本').fill(path);
  await page.getByRole('button', { name: '导入解析', exact: true }).click(); await expect(page.getByRole('button', { name: '导入解析', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: '打开源码配置' }).click();
  const analyses = await researchApi(page, 'research/workbench/analyses'); const analysis = analyses.find((a: {path:string}) => a.path === path);
  await page.getByLabel('源码对象').selectOption(analysis.objects.find((o: {qualname:string}) => o.qualname === 'calculate').id);
  await page.getByRole('button', { name: '智能助手', exact: true }).click();
  await page.getByLabel('智能任务角色').selectOption('code'); await page.getByRole('button', { name: '任务设置' }).click();
  await page.getByLabel('任务模型服务').selectOption('harness-lab'); await page.getByLabel('任务指令').fill('将 calculate 的加一改成加二，提出供我审查的修改。');
  await page.getByRole('button', { name: '执行智能任务' }).click(); await expect(page.getByTestId('task-record').first().locator('strong')).toContainText('intelligence.code');
  await expect(page.getByTestId('task-record').first().locator('strong > span')).toHaveText('completed');
  expect(readFileSync(path, 'utf8')).toBe(original);
  await page.getByRole('button', { name: '查看智能结果' }).first().click();
  await expect(page.locator('.wb-ai-answer')).toContainText('真实定义');
  await expect(page.locator('.wb-context-view')).toContainText('source.read'); await expect(page.locator('.wb-context-view')).toContainText('code.propose');
  await page.getByRole('button', { name: '代码审查', exact: true }).click(); await page.getByRole('button', { name: /reviewed.py.*valid/ }).first().click();
  await expect(page.getByTestId('proposal-diff')).toContainText('+    return x + 2');
  await page.getByRole('button', { name: '接受并应用' }).click();
  await expect.poll(() => readFileSync(path, 'utf8')).toContain('return x + 2');
  await page.getByRole('button', { name: '代码审查', exact: true }).click();
  await expect(page.locator('.wb-review-content')).toContainText('行为未验证');
});

test('tool catalog and automatic intelligence context remain independently accessible', async ({ page }) => {
  await page.goto('http://127.0.0.1:8879/#session=' + session);
  await page.getByRole('button', { name: '工具库', exact: true }).first().click();
  await expect(page.getByRole('cell', { name: 'PyVista', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '检测工具', exact: true }).click();
  await expect(page.getByTestId('task-record').first()).toContainText('completed', { timeout: 30000 });
  await page.getByRole('button', { name: '智能助手', exact: true }).first().click();
  await expect(page.getByLabel('任务指令')).toBeVisible();
  await expect(page.getByRole('button', { name: '模型设置', exact: true }).first()).toBeVisible();
  await expect(page.getByLabel('上下文选择')).toHaveCount(0);
});

test('an active task cannot replace an explicitly chosen historical run',async({page})=>{
  await page.goto('http://127.0.0.1:8879/#session='+session);
  const runs=await researchApi(page,'research/runs'),historic=runs.find((r:{name:string})=>r.name==='Analysis'),latest=runs[0];
  const task={protocol_version:2,id:'delayed-compute',kind:'compute',status:'running',created_at:'',updated_at:'',run_id:latest.id,plan_id:null,calculation_status:'running',progress:0,output_ids:[],message:'',receipt:{}};
  await page.route('**/workbench/tasks',route=>route.fulfill({json:[task]}));
  await page.route('**/workbench/tasks/delayed-compute',route=>route.fulfill({json:task}));
  await page.reload();await expect(page.getByRole('button',{name:'运行',exact:true})).toBeEnabled();
  await page.getByLabel('运行记录').selectOption(historic.id);await page.waitForTimeout(1000);
  await expect(page.getByLabel('运行记录')).toHaveValue(historic.id);
 });

test('real plotting is explicit and saved artifacts remain independent of computation',async({page})=>{
  await page.goto('http://127.0.0.1:8879/#session='+session);
  await page.getByRole('button',{name:'打开源码配置'}).click();await page.getByLabel('示例选择').selectOption('analysis');
  await page.getByLabel('脚本参数 JSON').fill('[]');await page.getByLabel('计算解释器').focus();
  await page.getByRole('button',{name:'导入解析',exact:true}).click();await expect(page.getByRole('button',{name:'导入解析',exact:true})).toBeEnabled();
  await page.getByRole('button',{name:'打开源码配置'}).click();await page.getByRole('button',{name:'探针台',exact:true}).click();
  await page.getByRole('button',{name:'添加探针',exact:true}).click();await page.getByLabel('探针类型').selectOption('view.matplotlib');await page.getByLabel('探针绑定').fill('C');await page.getByRole('button',{name:'确认添加探针'}).click();
  const old=await page.getByLabel('运行记录').inputValue();await page.getByRole('button',{name:'运行',exact:true}).click();await expect(page.getByLabel('运行记录')).not.toHaveValue(old);
  await expect(page.getByTestId('task-record').first().locator('strong > span')).toHaveText('completed',{timeout:60000});
  await chooseValue(page,'C');await page.getByLabel('数据呈现').selectOption({label:'view.matplotlib'});
  await expect(page.getByRole('img',{name:'绘图探针产物'})).toBeVisible();
  const run=await page.getByLabel('运行记录').inputValue();await page.getByLabel('运行选项').click();await page.getByRole('button',{name:'仅重绘'}).click();
  await expect(page.getByTestId('task-record').first().locator('strong > span')).toHaveText('completed');
  await expect(page.getByLabel('运行记录')).toHaveValue(run);
});

test('narrow screens focus one tool document and keep other views reachable',async({page})=>{
  await page.setViewportSize({width:390,height:844});await page.goto('http://127.0.0.1:8879/#session='+session);
  await page.getByRole('button',{name:'智能助手',exact:true}).click();await expect(page.getByLabel('任务指令')).toBeVisible();
  const box=await page.getByLabel('任务指令').boundingBox();expect(box!.width).toBeGreaterThan(240);
  await page.getByRole('button',{name:'探针台',exact:true}).click();await expect(page.getByRole('button',{name:'添加探针',exact:true})).toBeVisible();
  await page.screenshot({path:'../docs/assets/scientific-narrow.png'});
});
