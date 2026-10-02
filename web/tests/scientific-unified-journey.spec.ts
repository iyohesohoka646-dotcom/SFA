import { expect, test } from '@playwright/test';
import { session } from './session';
import { chooseValue, chooseExample, runCompute, researchApi } from './scientific-helpers';
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
test('manual verdict appears immediately and graph camera survives tab changes', async ({page}) => {
  await page.goto('http://127.0.0.1:8879/#session='+session);
  await chooseExample(page); await runCompute(page); await chooseValue(page,'X');
  await page.getByRole('button',{name:'计算关系图',exact:true}).first().click();
  await expect(page.getByTestId('relation-node').first()).toBeVisible();
  await expect(page.getByTestId('graph-layout-metric')).not.toContainText('布局 0 ms');
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
  const zoom = async () => Number((await page.locator('.wb-graph-canvas .react-flow__viewport').getAttribute('style'))!.match(/scale\(([^)]+)/)![1]);
  const originalZoom = await zoom();
  await page.getByRole('button',{name:'zoom out'}).click();
  await expect.poll(zoom).toBeLessThan(originalZoom * .84);
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
  const camera = await page.locator('.wb-graph-canvas .react-flow__viewport').getAttribute('style');
  await page.getByRole('button',{name:'工具库',exact:true}).first().click();
  await page.getByRole('button',{name:'计算关系图',exact:true}).first().click();
  await expect(page.getByTestId('graph-layout-metric')).not.toContainText('布局 0 ms');
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
  await expect(page.locator('.wb-graph-canvas .react-flow__viewport')).toHaveAttribute('style',camera!);
  await page.getByRole('button',{name:'探针台',exact:true}).first().click();
  await page.getByRole('button',{name:'添加探针',exact:true}).click();
  await page.getByLabel('探针类型').selectOption('check.manual');
  await page.getByRole('button',{name:'确认添加探针',exact:true}).click();
  await page.getByLabel('人工判断',{exact:true}).selectOption('pass');
  await page.getByLabel('人工判断说明').fill('人工核对数值一致');
  await page.getByRole('button',{name:'记录判断',exact:true}).click();
  await expect(page.getByTestId('probe-output').filter({hasText:'check.manual'})).toContainText('人工核对数值一致');
});

test('a pinned data probe executes its own historical run', async ({page}) => {
  await page.goto('http://127.0.0.1:8879/#session='+session);
  await chooseExample(page); await runCompute(page); await chooseValue(page,'X');
  const runA = await page.getByLabel('运行记录').inputValue();
  await page.getByRole('tab',{name:'X · v1',exact:true}).dblclick();
  await runCompute(page); await chooseValue(page,'Z');
  const runB = await page.getByLabel('运行记录').inputValue();
  expect(runB).not.toBe(runA);
  await page.getByRole('tab',{name:'X · v1',exact:true}).click();
  const request = page.waitForRequest(r => r.url().endsWith('/workbench/evaluate'));
  await page.locator('.wb-data-pane').filter({has:page.getByTestId('current-variable').filter({hasText:/^X$/})}).getByRole('button',{name:'执行探针',exact:true}).click();
  expect((await request).postDataJSON().run_id).toBe(runA);
  await expect(page.getByTestId('task-record').first().locator('strong > span')).toHaveText('completed');
  await expect(page.getByLabel('运行记录')).toHaveValue(runB);
});

test('pinned relation graph keeps its nodes and camera after switching global run', async ({page}) => {
  await page.goto('http://127.0.0.1:8879/#session='+session);
  await chooseExample(page); await runCompute(page);
  const runA = await page.getByLabel('运行记录').inputValue();
  const all = await researchApi(page,'research/runs'), other = all.find((r:{id:string}) => r.id !== runA);
  await page.getByRole('button',{name:'计算关系图',exact:true}).first().click();
  await page.getByRole('tab',{name:'计算关系图',exact:true}).dblclick();
  await expect(page.getByTestId('relation-node').first()).toBeVisible();
  const count = await page.getByTestId('relation-node').count();
  await page.getByLabel('运行记录').selectOption(other.id);
  await expect(page.getByTestId('relation-node')).toHaveCount(count);
  await expect(page.getByTestId('relation-node').filter({has:page.locator('strong',{hasText:/^X$/})})).toBeVisible();
  await page.getByTestId('relation-node').filter({has:page.locator('strong',{hasText:/^X$/})}).click();
  await expect(page.locator('.wb-data-pane .wb-evidence-bar')).toContainText(runA.slice(0,8));
});

test('pause gate shows a continuation control and resumes once', async ({page}) => {
  await page.goto('http://127.0.0.1:8879/#session='+session);
  const info = await researchApi(page,'research/info'), path = join(info.root,'pause-review.py'), counter = join(info.root,'pause-counter');
  writeFileSync(path,"import numpy as np\nfrom pathlib import Path\nX = np.array([float('nan')])\np = Path(__file__).with_name('pause-counter')\np.write_text('continued')\n",'utf8');
  await page.getByRole('button',{name:'打开源码配置'}).click(); await page.getByLabel('分析脚本').fill(path);
  await page.getByRole('button',{name:'导入解析',exact:true}).click(); await expect(page.getByRole('button',{name:'导入解析',exact:true})).toBeEnabled();
  await page.getByRole('button',{name:'打开源码配置'}).click(); await page.getByRole('button',{name:'探针台',exact:true}).first().click();
  await page.getByRole('button',{name:'添加探针',exact:true}).click(); await page.getByLabel('探针类型').selectOption('check.finite');
  await page.getByLabel('探针绑定').fill('X'); await page.getByRole('button',{name:'确认添加探针',exact:true}).click();
  const cfg = await researchApi(page,'research/workbench/configuration');
  cfg.script=path; cfg.probes=[{id:'pause-finite',definition_id:'check.finite',binding:'X',parameters:{},policy:'pause',budget_ms:5000,enabled:true}];
  await researchApi(page,'research/workbench/configuration',{config:cfg,expected_revision:cfg.revision},'PUT');
  await page.reload(); await expect(page.getByRole('button',{name:'运行',exact:true})).toBeEnabled();
  await page.getByRole('button',{name:'运行',exact:true}).click();
  await expect(page.getByTestId('run-status')).toHaveText('paused',{timeout:30000});
  await expect(page.getByRole('button',{name:'继续计算',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'继续计算',exact:true}).click();
  await expect(page.getByTestId('task-record').first().locator('strong > span')).toHaveText('completed',{timeout:30000});
  expect(readFileSync(counter,'utf8')).toBe('continued');
});

test('heatmap explains its color scale and captured sample without an essay', async ({page}) => {
  await page.goto('http://127.0.0.1:8879/#session='+session);
  await chooseExample(page); await runCompute(page); await chooseValue(page,'X');
  await expect(page.getByTestId('matrix-color-legend')).toBeVisible();
  await expect(page.getByTestId('matrix-color-legend')).toContainText('线性');
  await expect(page.getByTestId('matrix-axis-labels')).toContainText('行');
  await expect(page.getByTestId('matrix-cell-value')).toBeVisible();
  await expect(page.getByText('统计与采集', {exact:true})).toBeVisible();
  await page.screenshot({path:'../docs/assets/scientific-matrix.png'});
});

test('toolbar replot applies configured probes beyond the selected value', async ({page}) => {
  await page.goto('http://127.0.0.1:8879/#session='+session);
  await chooseExample(page); await runCompute(page); await chooseValue(page,'Z');
  await page.getByRole('button',{name:'探针台',exact:true}).first().click();
  await page.getByRole('button',{name:'添加探针',exact:true}).click();
  await page.getByLabel('探针类型').selectOption('view.matplotlib'); await page.getByLabel('探针绑定').fill('C');
  await page.getByRole('button',{name:'确认添加探针',exact:true}).click();
  const response=page.waitForResponse(r=>r.url().endsWith('/workbench/replot'));
  await page.getByLabel('运行选项').click(); await page.getByRole('button',{name:'仅重绘',exact:true}).click();
  const reply=await response;
  expect(reply.request().postDataJSON().snapshot_ids).toEqual([]);
  const task=await reply.json();
  await expect.poll(async()=> (await researchApi(page,'research/workbench/tasks/'+task.id)).status).toBe('completed');
  const outputs=await researchApi(page,'research/workbench/outputs?task_id='+task.id);
  expect(outputs.some((o:{definition_id:string;status:string})=>o.definition_id==='view.matplotlib'&&o.status==='ready')).toBe(true);
});

test('completed task reconciles a stale bootstrap status at its final event cursor', async ({page}) => {
  await page.goto('http://127.0.0.1:8879/#session='+session);
  await chooseExample(page);
  await page.route('**/research/runs/*/bootstrap', async route=>{
    const run=route.request().url().split('/').at(-2)!;
    for(let tries=0;tries<120;tries++){
      const response=await page.request.get('http://127.0.0.1:8879/api/v1/research/runs/'+run,{headers:{Authorization:'Bearer '+session}});
      if((await response.json()).status==='completed') break;
      await new Promise(resolve=>setTimeout(resolve,50));
    }
    const response=await route.fetch(), data=await response.json();
    data.run.status='running';
    await route.fulfill({json:data});
  });
  await page.getByRole('button',{name:'运行',exact:true}).click();
  await expect(page.getByTestId('task-record').first().locator('strong > span')).toHaveText('completed',{timeout:30000});
  await expect(page.getByTestId('run-status')).toHaveText('completed');
});
