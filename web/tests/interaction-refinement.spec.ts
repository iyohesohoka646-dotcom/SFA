import {test, expect, type Page} from '@playwright/test';
import {session} from './session';
import {join} from 'node:path';
import {readFileSync, writeFileSync} from 'node:fs';
import {researchApi, selectObject, runCompute, chooseExample} from './scientific-helpers';

async function importScript(page: Page, filename: string, code: string) {
  const info = await researchApi(page, 'research/info');
  const path = join(info.root, filename);
  writeFileSync(path, code);
  await page.getByRole('button', {name:'打开源码配置'}).click();
  await page.getByLabel('分析脚本', {exact:true}).fill(path);
  await page.getByLabel('脚本参数 JSON').fill('[]');
  const response = page.waitForResponse(r => r.url().endsWith('/workbench/analyses') && r.request().method() === 'POST' && r.request().postDataJSON().path === path);
  await page.getByRole('button', {name:'导入解析', exact:true}).click();
  expect((await response).ok()).toBe(true);
  await expect(page.getByRole('button', {name:'运行', exact:true})).toBeEnabled();
  await page.getByRole('button', {name:'打开源码配置'}).click();
  return path;
}

test('logical variable shows last observed assignment and highlights same-scope definitions and uses', async ({page}) => {
  const errors:string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('http://127.0.0.1:8879/?single=1#session='+session);
  await importScript(page, 'same-variable.py', 'x = 1\nif x > 0:\n    scores = x + 2\nelse:\n    scores = x - 2\nscores = scores * 3\nresult = scores + 1\ndef shadow():\n    scores = 99\n    return scores\n');
  const tree = page.getByRole('tree', {name:'计算对象树'});
  await expect(tree.locator('.object-row-assignment, .object-row-evidence')).toHaveCount(0);
  await runCompute(page);
  const row = await selectObject(page, 'scores');
  // The lexical shadow has its own scope row; current module has one logical row.
  await expect(row.locator('.object-dtype')).not.toHaveText('—');
  const tabs = await page.locator('.workspace-tab').count();
  await row.click();
  expect(await page.locator('.workspace-tab').count()).toBe(tabs);
  const marks = page.locator('[data-source-occurrence="definition"], [data-source-occurrence="use"]');
  await expect(marks).toHaveCount(5);
  const highlighted = await marks.evaluateAll(elements => elements.map(e => e.textContent));
  expect(highlighted.every(text => text === 'scores')).toBe(true);
  await tree.focus();await page.keyboard.press('Control+a');
  await expect(page.locator('.object-selection')).toContainText('2 项选中');
  expect(await page.locator('.workspace-tab').count()).toBe(tabs);
  await expect(page.getByLabel('对象类型').locator('option')).toHaveCount(2);
  await expect(page.getByLabel('对象探针结果').locator('option')).toHaveCount(3);
  await page.getByRole('searchbox',{name:'搜索对象',exact:true}).fill('no-matching-research-object');
  await tree.focus();await page.keyboard.press('Control+a');
  await expect(page.locator('.object-selection')).toContainText('0 项选中');
  await page.getByRole('searchbox',{name:'搜索对象',exact:true}).fill('scores');
  await row.click();
  await expect(marks).toHaveCount(5);
  await page.screenshot({path:'../docs/assets/interaction-object-source.png'});
  await row.dblclick();
  await expect(page.getByTestId('current-variable').last()).toHaveText('scores');
  const runs = await researchApi(page, 'research/runs');
  const run = runs.find((r:any)=>r.script.endsWith('same-variable.py'));
  const latest = await researchApi(page, `research/runs/${run.id}/snapshots`);
  const last = latest.filter((s:any)=>s.name==='scores' && s.scope_id==='main').sort((a:any,b:any)=>b.version-a.version)[0];
  expect(last.sample.values).toEqual([[9]]);
  expect(errors).toEqual([]);
});

test('configured model stages safe writing proposal and acceptance is explicit and reversible', async ({page}) => {
  await page.goto('http://127.0.0.1:8879/?single=1#session='+session);
  const original = '# 研究说明\nX=2\ndef calculate(x):\n    return x+1\n';
  const path = await importScript(page, 'writing-format.py', original);
  await researchApi(page, 'settings/models/format-browser', {profile:{id:'format-browser', protocol:'openai-compatible', base_url:'http://127.0.0.1:8879/fake-model/v1', models:['format-model'], default_model:'format-model'}}, 'PUT');
  await page.getByRole('button', {name:'智能助手', exact:true}).first().click();
  await page.getByLabel('智能任务角色').selectOption('format');
  await page.getByLabel('任务模型服务').selectOption('format-browser');
  await page.getByLabel('任务模型', {exact:true}).selectOption('format-model');
  await page.getByRole('button', {name:'创建整理提案', exact:true}).click();
  await expect(page.getByTestId('task-record').first().locator('strong > span')).toHaveText('completed');
  expect(readFileSync(path, 'utf8')).toBe(original);
  await page.getByRole('button', {name:'代码审查', exact:true}).first().click();
  const proposalRow = page.locator('.wb-proposal-list button').filter({hasText:'writing-format.py'}).filter({hasText:'书写整理'}).first();
  await proposalRow.click();
  await expect(page.getByTestId('proposal-diff')).toContainText('X = 2');
  let releaseSource!: () => void;
  let sawSource!: () => void;
  const sourceGate = new Promise<void>(resolve => { releaseSource = resolve; });
  const sourceRequested = new Promise<void>(resolve => { sawSource = resolve; });
  const sourcePattern = /\/workbench\/analyses\/[^/]+\/source$/;
  await page.route(sourcePattern, async route => {
    sawSource();
    await sourceGate;
    await route.continue();
  });
  await page.getByRole('button', {name:'接受并应用', exact:true}).click();
  await expect(page.getByRole('button', {name:'生成回滚提案', exact:true})).toBeEnabled();
  await sourceRequested;
  await expect(page.getByRole('button', {name:'运行', exact:true})).toBeDisabled();
  releaseSource();
  await expect(page.getByRole('button', {name:'运行', exact:true})).toBeEnabled();
  await page.unroute(sourcePattern);
  expect(readFileSync(path, 'utf8')).toContain('return x + 1');
  await page.getByRole('button', {name:'生成回滚提案', exact:true}).click();
  await expect(page.getByRole('button', {name:'接受并应用', exact:true})).toBeEnabled();
  const rolledBack = page.waitForResponse(r => r.url().endsWith('/accept') && r.request().method() === 'POST');
  await page.getByRole('button', {name:'接受并应用', exact:true}).click();
  expect((await rolledBack).ok()).toBe(true);
  expect(readFileSync(path, 'utf8')).toBe(original);
});

test('graph uses collapsed structural overview, floating controls, distinct data view and drag panning', async ({page}) => {
  await page.goto('http://127.0.0.1:8879/?single=1#session='+session);
  await chooseExample(page);
  await page.getByLabel('运行记录').selectOption('');
  await page.getByRole('button', {name:'计算关系图', exact:true}).first().click();
  await page.getByRole('button', {name:'放大 main 视图', exact:true}).click();
  await page.getByLabel('关系图视图').selectOption('code');
  await expect(page.getByTestId('graph-layout-metric')).toHaveText(/· [1-9]\d* ms$/);
  await expect(page.locator('.semantic-plate.kind-file.is-expanded')).toHaveCount(1);
  const descendants = page.locator('.semantic-plate:not(.kind-file)');
  expect(await descendants.count()).toBeGreaterThan(0);
  expect(await descendants.evaluateAll(items => items.every(item => item.classList.contains('is-collapsed')))).toBe(true);
  await expect(page.locator('.semantic-node.kind-data')).toHaveCount(0);
  await page.screenshot({path:'../docs/assets/interaction-graph-structure.png'});
  await page.getByRole('button', {name:'布局与关系',exact:true}).click();
  const direction = page.getByLabel('布局方向');
  await expect(direction).toBeVisible();
  const overlay = direction.locator('xpath=ancestor::*[@role="dialog"][1]');
  const bounds = await overlay.boundingBox();
  expect(bounds!.height).toBeGreaterThan(180);
  expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(1000);
  await page.screenshot({path:'../docs/assets/interaction-graph-settings.png'});
  await page.keyboard.press('Escape');
  await expect(direction).not.toBeVisible();
  const pane = page.locator('.wb-graph-pane .react-flow__pane');
  const area = await pane.boundingBox();
  const viewport = page.locator('.wb-graph-pane .react-flow__viewport');
  const before = await viewport.getAttribute('style');
  await page.mouse.move(area!.x + 14, area!.y + 100);
  await page.mouse.down();
  await page.mouse.move(area!.x + 94, area!.y + 150, {steps:8});
  await page.mouse.up();
  await expect(viewport).not.toHaveAttribute('style', before!);
  await page.getByLabel('关系图视图').selectOption('data');
  await expect(page.locator('.semantic-node.kind-data').first()).toBeVisible();
  await page.screenshot({path:'../docs/assets/interaction-graph-data.png'});
  await page.getByRole('button', {name:'切换主题',exact:true}).click();
  await page.screenshot({path:'../docs/assets/interaction-graph-data-dark.png'});
  await page.getByRole('button', {name:'切换主题',exact:true}).click();
  await page.getByLabel('关系图视图').selectOption('code');
  await expect(page.getByLabel('关系图视图').locator('option')).toHaveCount(2);
  await page.getByRole('button', {name:'布局与关系',exact:true}).click();
  await page.getByLabel('运行证据', {exact:true}).check();
  await page.keyboard.press('Escape');
  await expect(page.locator('.graph-node-receipt')).toHaveCount(0);
});

test('same-name redefined functions keep local probe overrides separate and reject stale ambiguous scopes', async ({page}) => {
  await page.goto('http://127.0.0.1:8879/?single=1#session='+session);
  const before = await researchApi(page, 'research/workbench/configuration');
  try {
    const source = 'def f():\n    x = 1\n    return x\nfirst = f\ndef f():\n    x = 8\n    return x\na = first()\nb = f()\n';
    const path = await importScript(page, 'redefined-functions.py', source);
    const analysis = await researchApi(page, 'research/workbench/analyses', {path});
    const objects = analysis.objects.filter((o:any) => o.name === 'x' && o.kind === 'assignment');
    expect(objects).toHaveLength(2);
    expect(objects[0].logical_key).toBe(objects[1].logical_key);
    await page.getByRole('searchbox', {name:'搜索对象',exact:true}).fill('x');
    const rows = page.getByRole('tree', {name:'计算对象树'}).locator('.object-row-name').filter({hasText:/^x$/}).locator('..');
    await expect(rows).toHaveCount(2);
    await rows.first().click();
    await page.getByRole('button', {name:'探针台',exact:true}).first().click();
    const section = page.locator('.probe-object-section');
    await expect(section).toHaveCount(1);
    await section.getByLabel('启用 view.auto', {exact:true}).uncheck();
    const saved = page.waitForResponse(r => r.url().endsWith('/workbench/configuration') && r.request().method() === 'PUT');
    await page.locator('.wb-inspector').filter({has:page.locator('.wb-view-toolbar > strong').filter({hasText:/^探针台$/})}).getByRole('button', {name:'保存',exact:true}).click();
    expect((await saved).ok()).toBe(true);
    await rows.last().click();
    await expect(section.getByLabel('启用 view.auto', {exact:true})).toBeChecked();
    const target = (object:any) => ({kind:'data', logical_key:object.logical_key, object_id:object.id,
      block_id:object.block_id, analysis_id:analysis.id, exact_evidence:false});
    for (const [i,object] of objects.entries()) {
      const plan = await researchApi(page, 'research/workbench/plans', {analysis_id:analysis.id, scope:'compute',
        target_scope:{mode:'selection',targets:[target(object)]}});
      expect(plan.invocations.some((call:any) => call.definition.id === 'view.auto')).toBe(i === 1);
    }
    writeFileSync(path, '\n\n'+source);
    const reparsed = page.waitForResponse(r => r.url().endsWith('/workbench/analyses') && r.request().method() === 'POST');
    await page.getByRole('button', {name:'导入解析',exact:true}).click();
    const current = await (await reparsed).json();
    const result = await page.evaluate(async ({analysisId,object}) => {
      const response = await fetch('/api/v1/research/workbench/plans', {method:'POST',
        headers:{Authorization:'Bearer '+sessionStorage.getItem('cdaf-session'),'Content-Type':'application/json'},
        body:JSON.stringify({analysis_id:analysisId, scope:'compute', target_scope:{mode:'selection',targets:[object]}})});
      return {status:response.status, text:await response.text()};
    }, {analysisId:current.id, object:{...target(current.objects.find((o:any)=>o.name==='x'&&o.kind==='assignment')),analysis_id:current.id}});
    expect(result.status).toBe(400);
    expect(result.text).toContain('bind it again');
  } finally {
    const current = await researchApi(page, 'research/workbench/configuration');
    await researchApi(page, 'research/workbench/configuration', {config:{...before,revision:current.revision},expected_revision:current.revision},'PUT');
  }
});
