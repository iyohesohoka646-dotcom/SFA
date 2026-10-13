import { test, expect } from "@playwright/test";
test.use({ baseURL: "http://127.0.0.1:8880" });
const token = process.env.CDAF_BROWSER_TEST_SESSION!,
  headers = { Authorization: "Bearer " + token };

for (const status of [404, 500]) {
  test(`restoring a remembered project handles ${status} explicitly`, async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem("cdaf.project.id", "previous-local-workspace"));
    if (status === 500) await page.route("**/research/projects/previous-local-workspace", route => route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "Project service unavailable" }) }));
    await page.goto("/#session=" + token);
    await expect(page.getByRole("button", {name:"Open folder", exact:true})).toBeEnabled();
    await expect.poll(() => page.evaluate(() => localStorage.getItem("cdaf.project.id"))).toBe(null);
    if (status === 404) await expect(page.locator(".project-host-error")).not.toBeVisible();
    else await expect(page.locator(".project-host-error")).toContainText("Project service unavailable");
  });
}

test("project browser, cross-file evidence, probes and source versions share one real run", async ({
  page,
  request,
}) => {
  const fixture = await (
    await request.get("/api/v1/project-test-fixture", { headers })
  ).json();
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/#session=" + token);
  await page.getByText("Enter folder path", {exact:true}).click();
  await page.getByLabel("Folder path", { exact: true }).fill(fixture.root);
  await page.getByRole("button", { name: "Open project", exact: true }).click();
  await expect(page.getByLabel("项目运行入口", { exact: true })).toHaveValue(
    "main",
  );
  const before = await request.get(
    `/api/v1/research/projects/${fixture.project_id}/runs`,
    { headers },
  );
  expect(await before.json()).toEqual([]);
  await page.getByRole("button", { name: "运行", exact: true }).click();
  await expect(page.locator(".wb-statusbar")).toContainText("completed", {
    timeout: 45000,
  });
  const runId = await page
    .getByLabel("项目运行记录", { exact: true })
    .inputValue();
  expect(runId).not.toBe("");
  await page
    .getByRole("button", { name: "Expand prepare.py", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Expand build_dataset", exact: true })
    .click();
  const row = page
    .locator(".project-object-row")
    .filter({ has: page.locator(".project-object-name", { hasText: /^X$/ }) });
  await row.click();
  await expect(page.locator(".wb-statusbar")).toContainText("1 个选中");
  await expect(
    page.getByRole("button", { name: "打开探针台", exact: true }),
  ).toHaveCount(0);
  await row.dblclick();
  await page.getByRole("button", { name: "打开探针台", exact: true }).click();
  await expect(page.locator(".wb-inspector")).toContainText("X");
  const bootstrap = await (
    await request.get(
      `/api/v1/research/projects/${fixture.project_id}/runs/${runId}/bootstrap`,
      { headers },
    )
  ).json();
  expect(
    bootstrap.snapshots.some((s: { source?: { path: string } }) =>
      s.source?.path.endsWith("compute.py"),
    ),
  ).toBe(true);
  expect(errors).toEqual([]);
});

test("switching projects unmounts old sessions without running the new project", async ({
  page,
  request,
}) => {
  const fixture = await (
    await request.get("/api/v1/project-test-fixture", { headers })
  ).json();
  await page.goto("/#session=" + token);
  await page.getByText("Enter folder path", {exact:true}).click();
  await page.getByLabel("Folder path", { exact: true }).fill(fixture.root);
  await page.getByRole("button", { name: "Open project", exact: true }).click();
  await page.getByRole("button", { name: "智能助手", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "上下文预览", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Switch project", exact: true })
    .click();
  await page.getByText("Enter folder path", {exact:true}).click();
  await page.getByLabel("Folder path", { exact: true }).fill(fixture.other);
  await page.getByRole("button", { name: "Open project", exact: true }).click();
  await expect(page.locator(".wb-project-name")).toHaveText("other", {
    timeout: 15000,
  });
  await expect(page.getByLabel("项目运行记录", { exact: true })).toHaveValue(
    "",
  );
  await expect(
    page.getByRole("button", { name: "上下文预览", exact: true }),
  ).toHaveCount(0);
  await expect(page.getByLabel("项目运行入口", { exact: true })).toHaveValue(
    "",
  );
});

test("embedded terminal executes Python in the selected project and ends explicitly", async ({
  page,
  request,
}) => {
  const fixture = await (
    await request.get("/api/v1/project-test-fixture", { headers })
  ).json();
  const frames: string[] = [];
  page.on("websocket", (socket) =>
    socket.on("framereceived", (event) => frames.push(String(event.payload))),
  );
  await page.goto("/#session=" + token);
  await page.getByText("Enter folder path", {exact:true}).click();
  await page.getByLabel("Folder path", { exact: true }).fill(fixture.root);
  await page.getByRole("button", { name: "Open project", exact: true }).click();
  await page.getByRole("button", { name: "终端", exact: true }).click();
  await page.getByLabel("终端配置", { exact: true }).selectOption("python");
  await page.getByRole("button", { name: "新建终端", exact: true }).click();
  await expect(page.getByLabel("终端会话", { exact: true })).not.toHaveValue(
    "",
  );
  await expect.poll(() => frames.join("")).toContain("Python");
  const input = page.getByLabel("终端输入", { exact: true });
  await input.pressSequentially("print('PROJECT_'+'TERM_OK')", { delay: 15 });
  await input.press("Enter");
  await expect
    .poll(() => frames.join(""), { timeout: 15000 })
    .toContain("PROJECT_TERM_OK");
  await input.pressSequentially(
    "import os;print(os.path.basename(os.getcwd()))",
    { delay: 15 },
  );
  await input.press("Enter");
  await expect.poll(() => frames.join("")).toContain("flat-lab");
  await page.getByRole("button", { name: "结束会话", exact: true }).click();
  await expect(page.locator(".terminal-pane [role=status]")).toHaveText(
    "已结束",
  );
});

test("saving an entry then immediately running does not overwrite a stale clean configuration", async ({ page, request }) => {
  const fixture = await (await request.get("/api/v1/project-test-fixture", { headers })).json();
  await page.goto("/#session=" + token);
  await page.getByText("Enter folder path", {exact:true}).click();
  await page.getByLabel("Folder path", { exact: true }).fill(fixture.other);
  await page.getByRole("button", { name: "Open project", exact: true }).click();
  await page.getByRole("button", { name: "运行入口", exact: true }).click();
  await page.locator(".project-entries-candidates").getByRole("button", { name: "main.py", exact: true }).click();
  let hold = false;
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  await page.route("**/workbench/configuration", async route => {
    if (hold && route.request().method() === "GET") await gate;
    await route.continue();
  });
  hold = true;
  try {
    await page.getByRole("button", { name: "Save entry", exact: true }).click();
    await expect(page.getByRole("button", { name: "Save entry", exact: true })).not.toBeVisible();
    await page.getByRole("button", { name: "关闭运行入口", exact: true }).click();
    await page.getByRole("button", { name: "运行", exact: true }).click();
    await expect(page.locator(".wb-statusbar")).toContainText("completed", { timeout: 15000 });
  } finally { release(); }
});

test("Fit contains every project block in a narrow dock and selection keeps the camera", async ({ page, request }) => {
  const fixture = await (await request.get("/api/v1/project-test-fixture", { headers })).json();
  await page.setViewportSize({ width: 1100, height: 900 });
  await page.goto("/#session=" + token);
  await page.getByText("Enter folder path", {exact:true}).click();
  await page.getByLabel("Folder path", { exact: true }).fill(fixture.matrix_root);
  await page.getByRole("button", { name: "Open project", exact: true }).click();
  const response = page.waitForResponse(r => r.url().includes("/graph?") && r.url().includes("view=data") && r.ok());
  await page.getByRole("button", { name: "Data", exact: true }).click();
  await response;
  const canvas = page.locator(".project-canvas-flow");
  await expect(canvas.locator(".react-flow__node").first()).toBeVisible();
  await expect(page.locator(".project-canvas-status")).not.toBeVisible();
  await page.getByRole("button", { name: "Fit", exact: true }).click();
  const clipped = () => canvas.evaluate(element => {
    const bounds = element.getBoundingClientRect();
    return [...element.querySelectorAll(".react-flow__node")].filter(node => {
      const box = node.getBoundingClientRect();
      return box.left < bounds.left - 2 || box.right > bounds.right + 2 || box.top < bounds.top - 2 || box.bottom > bounds.bottom + 2;
    }).map(node => node.getAttribute("data-id"));
  });
  await expect.poll(clipped).toEqual([]);
  const viewport = canvas.locator(".react-flow__viewport");
  const before = await viewport.getAttribute("style");
  await page.getByRole("treeitem").filter({ has: page.locator(".project-tree-label", { hasText: /^main\.py$/ }) }).click();
  await expect(page.locator(".wb-statusbar")).toContainText("1 个选中");
  await expect(viewport).toHaveAttribute("style", before!);
  expect(await clipped()).toEqual([]);
});

test("project probes added after a run create real views and disabling them persists", async ({
  page,
  request,
}) => {
  const shared = await (
    await request.get("/api/v1/project-test-fixture", { headers })
  ).json();
  const fixture = { ...shared, root: shared.matrix_root, project_id: shared.matrix_project_id };
  const configUrl = `/api/v1/research/projects/${fixture.project_id}/workbench/configuration`;
  const original = await (await request.get(configUrl, { headers })).json();
  try {
    await page.goto("/#session=" + token);
    await page.getByText("Enter folder path", {exact:true}).click();
  await page.getByLabel("Folder path", { exact: true }).fill(fixture.root);
    await page
      .getByRole("button", { name: "Open project", exact: true })
      .click();
    await page.getByRole("button", { name: "运行", exact: true }).click();
    await expect(page.locator(".wb-statusbar")).toContainText("completed", {
      timeout: 45000,
    });
    await page
      .getByRole("button", { name: "Expand prepare.py", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Expand build_dataset", exact: true })
      .click();
    const row = page
      .locator(".project-object-row")
      .filter({
        has: page.locator(".project-object-name", { hasText: /^X$/ }),
      });
    await row.dblclick();
    const data = page
      .locator(".wb-data-pane")
      .filter({
        has: page.getByTestId("current-variable").filter({ hasText: /^X$/ }),
      })
      .last();
    await expect(data.getByTestId("probe-view")).toHaveCount(1);
    await data.getByRole("button", { name: "打开探针台", exact: true }).click();
    const inspector = page.locator(".wb-inspector").filter({ visible: true });
    await inspector.getByRole("tab", { name: "新探针", exact: true }).click();
    await inspector
      .getByLabel("探针绑定范围", { exact: true })
      .selectOption("selection");
    await inspector
      .getByLabel("探针类型", { exact: true })
      .selectOption("view.table");
    await inspector
      .getByRole("button", { name: "确认添加探针", exact: true })
      .click();
    await inspector.getByRole("button", { name: "保存", exact: true }).click();
    await expect(data.getByTestId("probe-view")).toHaveCount(2);
    await data.getByRole("button", { name: "执行探针", exact: true }).click();
    await expect(
      data.getByTestId("probe-view").locator("summary .wb-kind"),
    ).toHaveText(["ready", "ready"], { timeout: 30000 });
    await inspector.getByRole("tab", { name: "选中对象", exact: true }).click();
    const object = inspector.locator(".probe-object-section").first();
    await object.getByLabel("启用 view.auto", { exact: true }).uncheck();
    await object.getByLabel("启用 view.table", { exact: true }).uncheck();
    await inspector.getByRole("button", { name: "保存", exact: true }).click();
    await expect(data.locator(".wb-data-content")).toBeEmpty();
    await page.reload();
    await expect(page.locator(".wb-data-content")).toBeEmpty();
    expect(
      (await (await request.get(configUrl, { headers })).json()).probes.some(
        (p: { definition_id: string }) => p.definition_id === "view.table",
      ),
    ).toBe(true);
  } finally {
    const current = await (await request.get(configUrl, { headers })).json();
    expect(
      (
        await request.put(configUrl, {
          headers,
          data: {
            config: { ...original, revision: current.revision },
            expected_revision: current.revision,
          },
        })
      ).ok(),
    ).toBe(true);
  }
});
