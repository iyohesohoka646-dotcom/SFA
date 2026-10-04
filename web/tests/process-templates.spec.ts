import { test, expect } from '@playwright/test';
import { session } from './session';
import { chooseExample, chooseValue, runCompute, researchApi, selectObject } from './scientific-helpers';
test.use({ baseURL: 'http://127.0.0.1:8879' });
const url = 'http://127.0.0.1:8879/api/v1/research/workbench/configuration', headers = { Authorization: 'Bearer ' + session };
let saved: any;
test.beforeEach(async ({ request }) => { saved = await (await request.get(url, { headers })).json(); });
test.afterEach(async ({ request }) => { const current = await (await request.get(url, { headers })).json(); expect((await request.put(url, { headers, data: { config: { ...saved, revision: current.revision }, expected_revision: current.revision } })).ok()).toBe(true); });

test('data is only configured probes; disabling the template leaves just the variable and inspector entry', async ({ page }) => {
  await page.goto('/#session=' + session); await chooseExample(page); await runCompute(page); await chooseValue(page, 'X');
  const data = page.locator('.wb-data-pane').filter({ has: page.getByTestId('current-variable').filter({ hasText: /^X$/ }) }).last();
  await expect(data.getByTestId('probe-view')).toHaveCount(1);
  await expect(data.getByLabel('数据呈现探针')).toHaveCount(0);
  await expect(data.locator('.wb-operation-details, .wb-evidence-bar')).toHaveCount(0);
  await data.getByRole('button', { name: '打开探针台' }).click();
  const inspector = page.locator('.wb-inspector').filter({ visible: true });
  await expect(inspector.getByRole('tab')).toHaveText(['选中对象', '新探针', '应用模板']);
  await expect(inspector.locator('.probe-object-section > summary')).toContainText('X');
  await expect(inspector.getByText('此范围的结果', { exact: false })).toHaveCount(0);
  await inspector.getByLabel('启用 view.auto', { exact: true }).uncheck();
  await inspector.getByRole('button', { name: '保存', exact: true }).click();
  await expect(data.locator('.wb-data-content')).toBeEmpty();
  await expect(data.getByTestId('matrix-definition')).toHaveText('X');
  await page.reload();
  await expect(page.getByTestId('current-variable')).toHaveText('X');
  await expect(page.locator('.wb-data-content')).toBeEmpty();
});

test('library creates a compound template; application freezes members and changes the data page', async ({ page }) => {
  await page.goto('/#session=' + session); await chooseExample(page); await runCompute(page); await chooseValue(page, 'X');
  await page.getByRole('button', { name: '探针库', exact: true }).first().click();
  await page.getByRole('button', { name: '探针模板', exact: true }).click();
  await page.getByRole('button', { name: '新建探针模板' }).click();
  await page.getByLabel('模板名称').fill('Numeric comparison');
  await page.getByLabel('模板成员探针').selectOption('view.table'); await page.getByRole('button', { name: '加入模板' }).click();
  await page.getByLabel('模板成员探针').selectOption('view.matrix'); await page.getByRole('button', { name: '加入模板' }).click();
  await page.getByRole('button', { name: '保存模板', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: '模板已保存' })).toBeVisible();
  const template = (await researchApi(page, 'research/workbench/configuration')).probe_templates.find((t: any) => t.label === 'Numeric comparison');
  expect(template.members).toHaveLength(2);
  await page.getByLabel('对象类型').selectOption('all');
  await selectObject(page, 'analysis.py');
  await page.getByRole('button', { name: '探针台', exact: true }).first().click();
  await page.getByRole('tab', { name: '应用模板', exact: true }).click();
  await page.getByLabel('模板应用范围').selectOption('selection');
  await page.getByLabel('应用探针模板').selectOption(template.id);
  await page.getByRole('button', { name: '应用模板', exact: true }).click();
  await expect(page.getByRole('tab', { name: '选中对象' })).toHaveAttribute('aria-selected', 'true');
  await page.locator('.wb-inspector').filter({ visible: true }).getByRole('button', { name: '保存', exact: true }).click();
  await chooseValue(page, 'X');
  await expect(page.getByTestId('probe-view')).toHaveCount(3);
  const bindings = (await researchApi(page, 'research/workbench/configuration')).probes.filter((p: any) => p.template_id === template.id);
  expect(bindings).toHaveLength(2);
  expect(bindings.every((p: any) => p.selector.targets[0].kind === 'file')).toBe(true);
  const plan = await researchApi(page, 'research/workbench/plans', { analysis_id: bindings[0].selector.targets[0].analysis_id,
    scope: 'compute', instance_ids: bindings.map((p: any) => p.id), target_scope: bindings[0].selector });
  expect(plan.invocations.length).toBeGreaterThan(0);
  expect(plan.invocations.every((call: any) => call.targets.every((t: any) => t.kind === 'data'))).toBe(true);
  await page.screenshot({ path: '../docs/assets/process-probe-templates.png' });
});

test('Code expresses real dependencies and guards, blocks drag in either mode, and selection highlights source', async ({ page }) => {
  await page.goto('/#session=' + session); await chooseExample(page);
  await page.getByRole('button', { name: '计算关系图', exact: true }).first().click();
  await page.getByRole('button', { name: '放大 main 视图', exact: true }).click();
  const graph = page.locator('.wb-graph-pane');
  await expect(graph).toHaveAttribute('data-layout-state', 'ready');
  await page.getByRole('button', { name: '适应画布', exact: true }).click();
  await expect(graph.locator('.react-flow__edge').first()).toBeVisible();
  const block = graph.locator('.semantic-plate.kind-condition').first();
  const drag = async () => {
    const parent = block.locator('..'), before = await parent.getAttribute('style'), b = await block.boundingBox();
    await page.mouse.move(b!.x + b!.width * .45, b!.y + b!.height * .4); await page.mouse.down();
    await page.mouse.move(b!.x + b!.width * .45 + 75, b!.y + b!.height * .4 + 40, { steps: 12 }); await page.mouse.up();
    await expect(parent).not.toHaveAttribute('style', before!);
  };
  await drag(); await page.getByRole('button', { name: '框选', exact: true }).click(); await drag();
  await block.locator('strong').click();
  await page.getByRole('button', { name: '还原 main 视图', exact: true }).click();
  await expect(page.locator('.ri-code-line.active').first()).toBeVisible();
  await expect(page.locator('.ri-code-line.active').first()).toContainText(/if options.failure == ["']constant["']/);
  await page.getByRole('button', { name: '放大 main 视图', exact: true }).click();
  await block.getByRole('button', { name: /^Expand / }).click();
  await expect(graph).toHaveAttribute('data-layout-state', 'ready');
  const label = graph.locator('.semantic-node.kind-condition strong').first();
  await expect(label).toContainText("options.failure == 'constant'");
  expect(await label.evaluate(el => el.scrollWidth <= el.clientWidth + 1 && el.scrollHeight <= el.clientHeight + 1)).toBe(true);
  await page.getByRole('button', { name: '自动对齐排线', exact: true }).click();
  await expect(graph).toHaveAttribute('data-layout-state', 'ready');
  await page.getByRole('button', { name: '适应画布', exact: true }).click();
  await page.screenshot({ path: '../docs/assets/process-code.png' });
});

test('run evidence and data metadata have distinct rectangles', async ({ page }) => {
  await page.goto('/#session=' + session); await chooseExample(page); await runCompute(page);
  await page.getByRole('button', { name: '计算关系图', exact: true }).first().click();
  await page.getByLabel('关系图视图').selectOption('data');
  await page.getByRole('button', { name: '放大 main 视图', exact: true }).click();
  await expect(page.locator('.wb-graph-pane')).toHaveAttribute('data-layout-state', 'ready');
  await page.getByRole('button', { name: '布局与关系', exact: true }).click(); await page.getByLabel('运行证据', { exact: true }).check(); await page.keyboard.press('Escape');
  await expect(page.locator('.graph-data-detail').first()).toBeVisible();
  expect(await page.locator('.graph-node-footer').evaluateAll(footers => footers.every(footer => {
    const detail = footer.querySelector('.graph-data-detail'), receipt = footer.querySelector('.graph-node-receipt');
    if (!detail || !receipt) return true;
    return detail.getBoundingClientRect().bottom <= receipt.getBoundingClientRect().top;
  }))).toBe(true);
  await page.getByRole('button', { name: '适应画布', exact: true }).click();
  await page.screenshot({ path: '../docs/assets/process-data-evidence.png' });
});

test('provider-neutral model services validate blank setup and use optional presets', async ({ page }) => {
  await page.goto('/#session=' + session); await page.getByRole('button', { name: '模型设置', exact: true }).click();
  await page.getByRole('button', { name: '新增模型服务', exact: true }).click();
  await expect(page.getByLabel('服务地址')).toHaveValue('');
  await expect(page.getByLabel('默认模型 ID')).toHaveValue('');
  await page.getByLabel('模型服务 ID').fill('generic-model-lab');
  await page.getByRole('button', { name: '保存模型配置', exact: true }).click();
  expect(await page.getByLabel('服务地址').evaluate((e: HTMLInputElement) => e.validity.valueMissing)).toBe(true);
  await page.getByLabel('服务预设', { exact: true }).selectOption('ollama');
  await expect(page.getByLabel('服务地址')).toHaveValue('http://127.0.0.1:11434/v1');
  await page.getByLabel('服务地址').fill('http://127.0.0.1:8879/fake-model/v1'); await page.getByLabel('默认模型 ID').fill('manual-model');
  await page.getByRole('button', { name: '保存模型配置', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: '模型配置已保存' })).toBeVisible();
  await page.getByRole('button', { name: '连接测试（不推理）', exact: true }).click(); await expect(page.getByTestId('connection-result')).toContainText('connected');
  await page.getByRole('button', { name: '删除此服务', exact: true }).click(); await expect(page.getByRole('status').filter({ hasText: '模型服务已删除' })).toBeVisible();
  await expect(page.getByLabel('已配置模型服务').locator('option[value="generic-model-lab"]')).toHaveCount(0);
  await expect(page.getByLabel('模型协议')).toHaveValue('offline');
  await expect(page.getByLabel('默认模型 ID')).toHaveCount(0);
});
