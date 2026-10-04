import { expect, test, type Page } from "@playwright/test";
import { session } from "./session";
import { chooseExample, researchApi, selectObject } from "./scientific-helpers";

test.use({ baseURL: "http://127.0.0.1:8879" });

const configurationUrl = "http://127.0.0.1:8879/api/v1/research/workbench/configuration";
const headers = { Authorization: "Bearer " + session };
const autoId = "auto-view", existingId = "refinement-existing-x";
let originalConfiguration: any;

test.beforeEach(async ({ request }) => {
  const response = await request.get(configurationUrl, { headers });
  expect(response.ok()).toBe(true);
  originalConfiguration = await response.json();
});

test.afterEach(async ({ request }) => {
  const current = await (await request.get(configurationUrl, { headers })).json();
  const response = await request.put(configurationUrl, {
    headers,
    data: { config: { ...originalConfiguration, revision: current.revision }, expected_revision: current.revision },
  });
  expect(response.ok()).toBe(true);
});

const inspector = (page: Page) => page.locator(".wb-inspector").filter({ visible: true }).filter({
  has: page.locator(".wb-view-toolbar > strong").filter({ hasText: /^探针台$/ }),
}).first();
const newBinding = (page: Page) => inspector(page).locator(".probe-binding-form");
const objectSection = (page: Page, name: string) => inspector(page).locator(".probe-object-section").filter({
  has: page.locator("summary").filter({ hasText: new RegExp("^" + name + "(?:数据对象|\\s)") }),
});

async function openInspector(page: Page) {
  await page.getByRole("button", { name: "探针台", exact: true }).first().click();
  await expect(inspector(page)).toBeVisible();
}

async function saveFromInspector(page: Page) {
  const saved = page.waitForResponse((response) => response.url().endsWith("/workbench/configuration") && response.request().method() === "PUT");
  await inspector(page).getByRole("button", { name: "保存", exact: true }).click();
  const response = await saved;
  expect(response.ok()).toBe(true);
  return response.json();
}

async function prepareSource(page: Page) {
  await page.goto("/#session=" + session);
  const info = await researchApi(page, "research/info");
  const path = info.examples.find((example: any) => example.id === "analysis").script;
  const isImport = (response: import("@playwright/test").Response) => response.url().endsWith("/workbench/analyses")
    && response.request().method() === "POST" && response.request().postDataJSON().path === path;
  const parsed = page.waitForResponse(isImport);
  await chooseExample(page);
  const analysis = await (await parsed).json();
  const source = analysis.objects.find((object: any) => object.name === "X" && object.scope === "<module>");
  expect(source).toBeDefined();
  const x = { kind: "data", logical_key: source.logical_key, object_id: source.id, block_id: source.block_id,
    analysis_id: analysis.id, run_id: null, snapshot_id: null, exact_evidence: false };
  const config = await researchApi(page, "research/workbench/configuration");
  await researchApi(page, "research/workbench/configuration", {
    config: { ...config, script: analysis.path, arguments: [], probe_defaults: {}, probes: [
      { id: autoId, definition_id: "view.auto", binding: "*", enabled: true, parameters: { precision: 3, show_coordinates: true },
        policy: "continue", budget_ms: 5000, origin: "project_default", inputs: {}, overrides: {},
        selector: { mode: "project", block_id: null, targets: [], excluded_keys: [] } },
      { id: existingId, definition_id: "view.scalar", binding: "*", enabled: true, parameters: { precision: 1 },
        policy: "continue", budget_ms: 5000, origin: "local", inputs: {}, overrides: {},
        selector: { mode: "selection", block_id: null, targets: [x], excluded_keys: [] } },
    ] }, expected_revision: config.revision,
  }, "PUT");
  await page.reload();
  const imported = page.waitForResponse(isImport);
  // A real import also clears the fixture's selected historical run and block.
  await chooseExample(page);
  return (await imported).json();
}

function sourceTarget(analysis: any, name: string) {
  const object = analysis.objects.find((item: any) => item.name === name && item.scope === "<module>");
  expect(object).toBeDefined();
  return { kind: "data", logical_key: object.logical_key, object_id: object.id, block_id: object.block_id,
    analysis_id: analysis.id, run_id: null, snapshot_id: null, exact_evidence: false };
}

async function selectedPlan(page: Page, analysis: any, target: any, instanceIds?: string[]) {
  return researchApi(page, "research/workbench/plans", {
    analysis_id: analysis.id, scope: "compute", ...(instanceIds ? { instance_ids: instanceIds } : {}),
    target_scope: { mode: "selection", block_id: null, targets: [target], excluded_keys: [] },
  });
}

function expectSourceInvocations(plan: any, analysis: any, target: any, instanceId: string, definitionId: string) {
  // A logical selection includes each static assignment; compute planning freezes
  // those candidates individually before a run supplies actual evidence.
  const occurrenceIds = analysis.objects.filter((object: any) => object.logical_key === target.logical_key)
    .map((object: any) => object.id).sort();
  expect(occurrenceIds.length).toBeGreaterThan(0);
  expect(plan.invocations).toHaveLength(occurrenceIds.length);
  expect(plan.invocations.flatMap((call: any) => call.targets.map((item: any) => item.object_id)).sort()).toEqual(occurrenceIds);
  for (const call of plan.invocations) {
    expect(call.instance.id).toBe(instanceId);
    expect(call.definition.id).toBe(definitionId);
    expect(call.targets).toHaveLength(1);
    expect(call.targets[0]).toMatchObject({ kind: "data", logical_key: target.logical_key, snapshot_id: null });
  }
}

test("current file is a usable block scope; selected objects expose collapsible inherited and local bindings", async ({ page }) => {
  const analysis = await prepareSource(page);
  await openInspector(page);
  await inspector(page).getByRole("button", { name: "添加探针", exact: true }).click();
  const form = newBinding(page);
  await expect(form.getByLabel("探针绑定范围")).toHaveValue("block");
  await expect(form.getByLabel("探针绑定范围").locator('option[value="block"]')).toContainText("当前文件");
  await form.getByLabel("探针绑定范围").selectOption("project");
  await form.getByLabel("探针绑定范围").selectOption("block");
  await form.getByLabel("新探针用途").selectOption("view");
  await form.getByLabel("探针类型").selectOption("view.matrix");
  await form.getByRole("button", { name: "确认添加探针", exact: true }).click();
  const saved = await saveFromInspector(page);
  const blockProbe = saved.probes.find((probe: any) => probe.definition_id === "view.matrix");
  expect(blockProbe.selector.mode).toBe("block");
  expect(analysis.graph.roots).toContain(blockProbe.selector.block_id);
  expect(blockProbe.selector.targets).toHaveLength(1);
  expect(blockProbe.selector.targets[0]).toMatchObject({ kind: "file", block_id: blockProbe.selector.block_id,
    logical_key: analysis.graph.blocks.find((block: any) => block.id === blockProbe.selector.block_id).logical_key });

  await selectObject(page, "X");
  await selectObject(page, "Z", true);
  await expect(inspector(page).locator(".probe-object-section")).toHaveCount(2);
  const xSection = objectSection(page, "X"), zSection = objectSection(page, "Z");
  await expect(xSection).toBeVisible();
  await expect(zSection).toBeVisible();
  expect(await inspector(page).locator(".probe-object-section").evaluateAll((elements) => elements.every((element) =>
    Boolean(element.compareDocumentPosition(element.closest(".wb-inspector")!.querySelector(".probe-new-section")!) & Node.DOCUMENT_POSITION_FOLLOWING)))).toBe(true);
  await expect(xSection.getByText("继承与项目默认", { exact: true })).toBeVisible();
  await expect(xSection.getByText("本地绑定", { exact: true })).toBeVisible();
  await xSection.locator("summary").first().click();
  await expect(xSection).toHaveJSProperty("open", false);
  await expect(xSection.getByText("本地绑定", { exact: true })).not.toBeVisible();
  await xSection.locator("summary").first().click();
  await expect(xSection.getByText("本地绑定", { exact: true })).toBeVisible();
  await page.screenshot({path:'../docs/assets/interaction-probe-bindings.png'});

  await xSection.getByLabel("启用 view.auto", { exact: true }).uncheck();
  const changed = await saveFromInspector(page);
  const x = sourceTarget(analysis, "X"), z = sourceTarget(analysis, "Z");
  expect(changed.probes.find((probe: any) => probe.id === autoId).overrides[x.logical_key].enabled).toBe(false);
  expect(changed.probes.find((probe: any) => probe.id === autoId).enabled).toBe(true);
  expect(changed.probes.find((probe: any) => probe.id === existingId).parameters).toEqual({ precision: 1 });
  const xPlan = await selectedPlan(page, analysis, x), zPlan = await selectedPlan(page, analysis, z);
  expect(xPlan.invocations.some((call: any) => call.instance.id === autoId)).toBe(false);
  expect(xPlan.invocations.some((call: any) => call.instance.id === existingId)).toBe(true);
  expect(zPlan.invocations.some((call: any) => call.instance.id === autoId)).toBe(true);
});

test("the chosen purpose lists only compatible probes and never leaves empty optgroups", async ({ page }) => {
  const analysis = await prepareSource(page);
  await selectObject(page, "X");
  await openInspector(page);
  await inspector(page).getByRole("button", { name: "添加探针", exact: true }).click();
  const form = newBinding(page), selector = form.getByLabel("探针类型");
  const definitions = await researchApi(page, "research/workbench/probe-definitions");
  for (const purpose of ["view", "interpret", "check"]) {
    await form.getByLabel("新探针用途").selectOption(purpose);
    const expected = definitions.filter((definition: any) => definition.capability === purpose && definition.supported_targets.includes("data"))
      .map((definition: any) => definition.id).sort();
    await expect.poll(async () => (await selector.locator("option").evaluateAll((options) => options.map((option) => (option as HTMLOptionElement).value))).sort()).toEqual(expected);
    await expect(selector.locator("optgroup")).toHaveCount(0);
  }
  await expect(selector.locator('option[value="check.structure"]')).toHaveCount(0);
  await form.getByLabel("新探针用途").selectOption("all");
  expect(await selector.locator("optgroup").evaluateAll((groups) => groups.every((group) => group.querySelectorAll("option").length > 0))).toBe(true);
  await form.getByLabel("新探针用途").selectOption("check");
  await selector.selectOption("check.finite");
  await form.getByRole("button", { name: "确认添加探针", exact: true }).click();
  const saved = await saveFromInspector(page);
  const binding = saved.probes.find((probe: any) => probe.definition_id === "check.finite");
  expect(binding.selector.mode).toBe("selection");
  expect(binding.selector.targets.map((target: any) => target.logical_key)).toEqual([sourceTarget(analysis, "X").logical_key]);
  const target = sourceTarget(analysis, "X");
  const plan = await selectedPlan(page, analysis, target, [binding.id]);
  expectSourceInvocations(plan, analysis, target, binding.id, "check.finite");
});

test("saved library defaults seed a new binding and do not rewrite either older binding", async ({ page }) => {
  await prepareSource(page);
  await selectObject(page, "Z");
  await page.getByRole("button", { name: "探针库", exact: true }).first().click();
  const library = page.locator(".probe-library").filter({ visible: true });
  await library.getByRole("searchbox", { name: "搜索探针库" }).fill("view.scalar");
  await library.getByRole("button", { name: "配置 数值 默认参数", exact: true }).click();
  const editor = library.locator(".library-default-editor");
  await editor.getByLabel("小数位数", { exact: true }).fill("7");
  await editor.getByLabel("显示数值", { exact: true }).check();
  const savedDefaults = page.waitForResponse((response) => response.url().endsWith("/workbench/configuration") && response.request().method() === "PUT");
  await editor.getByRole("button", { name: "保存默认参数", exact: true }).click();
  expect((await savedDefaults).ok()).toBe(true);
  await expect(editor.getByRole("status")).toHaveText("默认参数已保存。");
  const before = await researchApi(page, "research/workbench/configuration");
  expect(before.probe_defaults["view.scalar"].precision).toBe(7);
  expect(before.probes.find((probe: any) => probe.id === existingId).parameters).toEqual({ precision: 1 });
  await library.getByRole("button", { name: "绑定", exact: true }).click();
  const form = newBinding(page);
  await expect(form.getByLabel("探针类型")).toHaveValue("view.scalar");
  await expect(form.getByLabel("小数位数", { exact: true })).toHaveValue("7");
  await expect(form.getByLabel("显示数值", { exact: true })).toBeChecked();
  await form.getByRole("button", { name: "确认添加探针", exact: true }).click();
  const withNewBinding = await saveFromInspector(page);
  const created = withNewBinding.probes.find((probe: any) => probe.definition_id === "view.scalar" && probe.id !== existingId);
  expect(created.parameters.precision).toBe(7);
  expect(created.parameters.show_values).toBe(true);
  expect(withNewBinding.probes.find((probe: any) => probe.id === existingId).parameters).toEqual({ precision: 1 });

  await page.getByRole("button", { name: "探针库", exact: true }).first().click();
  await library.getByRole("searchbox", { name: "搜索探针库" }).fill("view.scalar");
  const defaultButton = library.getByRole("button", { name: "配置 数值 默认参数", exact: true });
  if (await defaultButton.getAttribute("aria-expanded") !== "true") await defaultButton.click();
  await editor.getByLabel("小数位数", { exact: true }).fill("9");
  const savedAgain = page.waitForResponse((response) => response.url().endsWith("/workbench/configuration") && response.request().method() === "PUT");
  await editor.getByRole("button", { name: "保存默认参数", exact: true }).click();
  expect((await savedAgain).ok()).toBe(true);
  await page.reload();
  const persisted = await researchApi(page, "research/workbench/configuration");
  expect(persisted.probe_defaults["view.scalar"].precision).toBe(9);
  expect(persisted.probes.find((probe: any) => probe.id === created.id).parameters.precision).toBe(7);
  expect(persisted.probes.find((probe: any) => probe.id === existingId).parameters).toEqual({ precision: 1 });
});

test("saved service/model selections and all four model requirements are frozen into a real plan", async ({ page }) => {
  const analysis = await prepareSource(page);
  const profileId = "probe-refinement-profile";
  await researchApi(page, "settings/models/" + profileId, { profile: {
    id: profileId, protocol: "openai-compatible", base_url: "http://127.0.0.1:8879/fake-model/v1",
    models: ["harness-model", "format-model"], default_model: "harness-model", credential_ref: "env:CDAF_BROWSER_TEST_KEY",
  } }, "PUT");
  await selectObject(page, "X");
  await openInspector(page);
  await inspector(page).getByRole("button", { name: "添加探针", exact: true }).click();
  const form = newBinding(page);
  await form.getByLabel("新探针用途").selectOption("interpret");
  await form.getByLabel("探针类型").selectOption("interpret.model");
  await form.getByLabel("探针模型服务", { exact: true }).selectOption(profileId);
  await form.getByLabel("探针模型", { exact: true }).selectOption("format-model");
  await form.getByRole("button", { name: "探针模型设置", exact: true }).click();
  await expect(page.getByRole("complementary", { name: "模型设置", exact: true })).toBeVisible();
  await expect(page.getByLabel("已配置模型服务").locator('option[value="' + profileId + '"]')).toHaveCount(1);
  await page.getByRole("button", { name: "关闭模型设置", exact: true }).click();
  const requirements = { task: "解释 X 的来源和计算作用", focus: "数值范围与直接依赖", constraints: "只使用提供的证据，不推断未执行的结果", output_format: "按结论、依据、未知项给出三段中文" };
  await form.getByLabel("任务", { exact: true }).fill(requirements.task);
  await form.getByLabel("关注重点", { exact: true }).fill(requirements.focus);
  await form.getByLabel("约束", { exact: true }).fill(requirements.constraints);
  await form.getByLabel("输出格式", { exact: true }).fill(requirements.output_format);
  await page.screenshot({path:'../docs/assets/interaction-probe-model.png'});
  await form.getByRole("button", { name: "确认添加探针", exact: true }).click();
  const saved = await saveFromInspector(page);
  const created = saved.probes.find((probe: any) => probe.definition_id === "interpret.model");
  expect(created.parameters).toMatchObject({ ...requirements, provider_id: profileId, model: "format-model" });
  const target = sourceTarget(analysis, "X");
  const frozen = await selectedPlan(page, analysis, target, [created.id]);
  expectSourceInvocations(frozen, analysis, target, created.id, "interpret.model");
  for (const call of frozen.invocations) expect(call.instance.parameters).toEqual(created.parameters);

  const section = objectSection(page, "X");
  await section.getByLabel("任务", { exact: true }).fill("后续修改的任务");
  await saveFromInspector(page);
  const unchanged = await researchApi(page, "research/workbench/plans/" + frozen.id);
  expect(unchanged.invocations).toEqual(frozen.invocations);
  const nextPlan = await selectedPlan(page, analysis, target, [created.id]);
  expectSourceInvocations(nextPlan, analysis, target, created.id, "interpret.model");
  for (const call of nextPlan.invocations)
    expect(call.instance.parameters).toEqual({ ...created.parameters, task: "后续修改的任务" });
});
