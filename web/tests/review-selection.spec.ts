import { test, expect, type Page } from "@playwright/test";
import { writeFileSync } from "node:fs";
import { join } from "node:path";
import { session } from "./session";
import { researchApi, runCompute } from "./scientific-helpers";

async function importSource(
  page: Page,
  name: string,
  code: string,
  probes: unknown[],
) {
  const info = await researchApi(page, "research/info"),
    path = join(info.root, name);
  writeFileSync(path, code);
  const current = await researchApi(page, "research/workbench/configuration");
  await researchApi(
    page,
    "research/workbench/configuration",
    {
      config: { ...current, script: path, probes },
      expected_revision: current.revision,
    },
    "PUT",
  );
  await page.reload();
  await page.getByRole("button", { name: "打开源码配置" }).click();
  await page.getByLabel("分析脚本", { exact: true }).fill(path);
  const response = page.waitForResponse(
    (r) =>
      r.url().endsWith("/workbench/analyses") &&
      r.request().method() === "POST" &&
      r.request().postDataJSON().path === path,
  );
  await page.getByRole("button", { name: "导入解析", exact: true }).click();
  const analysis = await (await response).json();
  await expect(
    page.getByRole("button", { name: "运行", exact: true }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "打开源码配置" }).click();
  return analysis;
}
async function runSelected(page: Page, mode: "probes" | "replot") {
  await page.getByLabel("探针执行范围").selectOption("selection");
  await page.getByLabel("运行模式").selectOption(mode);
  const response = page.waitForResponse(
    (r) =>
      r
        .url()
        .endsWith(
          mode === "probes" ? "/workbench/evaluate" : "/workbench/replot",
        ) && r.request().method() === "POST",
  );
  await page.getByRole("button", { name: "运行", exact: true }).click();
  const r = await response;
  expect(r.ok()).toBe(true);
  const task = await r.json();
  await expect
    .poll(
      async () =>
        (await researchApi(page, "research/workbench/tasks/" + task.id)).status,
      { timeout: 30000 },
    )
    .toBe("completed");
  return {
    task,
    plan: await researchApi(page, "research/workbench/plans/" + task.plan_id),
    outputs: await researchApi(
      page,
      "research/workbench/outputs?task_id=" + task.id,
    ),
  };
}
test("real tree function and graph operation selections resolve to distinct frozen probe targets", async ({
  page,
}) => {
  await page.goto("http://127.0.0.1:8879/#session=" + session);
  const analysis = await importSource(
    page,
    "selection-identity.py",
    "def calculate(x):\n    a = x + 1; b = a * 2\n    return b\nX = calculate(3)\n",
    [{ id: "timing", definition_id: "check.timing" }],
  );
  await runCompute(page);
  const tabs = await page.locator(".workspace-tab").count();
  const tree = page.getByRole("tree", { name: "计算对象树" });
  const functionRow = tree
    .locator(".object-row-name")
    .filter({ hasText: /^calculate$/ })
    .locator("..");
  await functionRow.click();
  const first = await runSelected(page, "probes");
  const functionOutput = first.outputs.find((o: any) =>
    o.targets.some((t: any) => t.kind === "function"),
  );
  expect(functionOutput?.status).toBe("pass");
  expect(functionOutput?.data.calls).toBe(1);
  expect(first.plan.target_scope.targets[0].logical_key).toBe(
    analysis.objects.find((o: any) => o.kind === "function").logical_key,
  );
  expect(await page.locator(".workspace-tab").count()).toBe(tabs);
  await page
    .getByRole("button", { name: "计算关系图", exact: true })
    .first()
    .click();
  await page
    .getByRole("button", { name: "放大 main 视图", exact: true })
    .click();
  await expect(page.getByTestId("graph-layout-metric")).toHaveText(
    /· [1-9]\d* ms$/,
  );
  await page
    .locator(".semantic-node .semantic-heading strong")
    .filter({ hasText: /^a = x \+ 1$/ })
    .click();
  await page
    .locator(".semantic-node .semantic-heading strong")
    .filter({ hasText: /^b = a \* 2$/ })
    .click({ modifiers: ["Control"] });
  await expect(page.locator(".object-selection")).toContainText("2 项选中");
  const second = await runSelected(page, "probes");
  expect(second.plan.target_scope.targets).toHaveLength(2);
  expect(
    new Set(second.plan.target_scope.targets.map((t: any) => t.logical_key))
      .size,
  ).toBe(2);
  expect(
    second.plan.target_scope.targets.every((t: any) => t.kind === "operation"),
  ).toBe(true);
  expect(second.outputs).toHaveLength(2);
  expect(second.outputs.every((o: any) => o.status === "pass")).toBe(true);
});
test("selecting v1 and replotting through the toolbar evaluates that exact historic evidence", async ({
  page,
}) => {
  await page.goto("http://127.0.0.1:8879/#session=" + session);
  await importSource(page, "historic-selection.py", "X = 1\nX = 2\n", [
    { id: "scalar", definition_id: "view.scalar" },
  ]);
  await runCompute(page);
  const tree = page.getByRole("tree", { name: "计算对象树" });
  await tree.getByRole("button", { name: "展开 X", exact: true }).click();
  const old = tree
    .locator(".object-row-name")
    .filter({ hasText: /^v1$/ })
    .locator("..");
  await expect(old).toBeVisible();
  await old.click();
  await expect(old).toHaveAttribute("aria-selected", "true");
  const result = await runSelected(page, "replot");
  const selected = result.plan.target_scope.targets[0];
  expect(selected.exact_evidence).toBe(true);
  expect(result.plan.resolved_targets.map((t: any) => t.snapshot_id)).toEqual([
    selected.snapshot_id,
  ]);
  expect(result.outputs).toHaveLength(1);
  expect(result.outputs[0].snapshot_id).toBe(selected.snapshot_id);
  const snapshot = await researchApi(
    page,
    "research/snapshots/" + selected.snapshot_id,
  );
  expect(snapshot.version).toBe(1);
  expect(snapshot.sample.values).toEqual([[1]]);
});
