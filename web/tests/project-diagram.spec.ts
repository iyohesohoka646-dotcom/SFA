import { test, expect, type Page, type Locator } from "@playwright/test";

test.use({ baseURL: "http://127.0.0.1:8880" });
const token = process.env.CDAF_BROWSER_TEST_SESSION!;
const headers = { Authorization: "Bearer " + token };

async function openDiagram(page: Page, root: string) {
  await page.goto("/#session=" + token);
  await page.getByText("Enter folder path", { exact: true }).click();
  await page.getByLabel("Folder path", { exact: true }).fill(root);
  await page.getByRole("button", { name: "Open project", exact: true }).click();
  const canvas = page.locator(".project-canvas");
  await expect(canvas.locator(".react-flow__node").first()).toBeVisible();
  await expect(canvas.locator(".project-canvas-status")).not.toBeVisible();
  return canvas;
}

function group(canvas: Locator, name: string) {
  return canvas.locator(".react-flow__node").filter({
    has: canvas.page().locator(".project-node-label", { hasText: new RegExp("^" + name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "$") }),
  });
}

async function cameraState(page: Page, projectId: string) {
  return page.evaluate((id) => {
    const key = Object.keys(localStorage).find((item) => item.startsWith("cdaf-project-camera:" + id + ":") && item.endsWith(":root:code"));
    return key ? JSON.parse(localStorage.getItem(key)!) as { positions: Record<string, { x: number; y: number }> } : null;
  }, projectId);
}

test("project groups expand individually with visible named ports and directed relationships", async ({ page, request }) => {
  const fixture = await (await request.get("/api/v1/project-test-fixture", { headers })).json();
  const canvas = await openDiagram(page, fixture.root);
  const file = group(canvas, "prepare.py");
  const initialCount = await canvas.locator(".react-flow__node").count();
  await file.getByRole("button", { name: "Expand group prepare.py", exact: true }).click();
  await expect.poll(() => canvas.locator(".react-flow__node").count()).toBeGreaterThan(initialCount);
  await expect(canvas.locator(".project-canvas-status")).not.toBeVisible();
  await expect(group(canvas, "build_dataset")).toBeVisible();

  // The real expanded group header stays above the children rather than in
  // the middle of its background plate. This measures DOM rectangles.
  const header = await file.locator(".project-node-header").boundingBox();
  const plate = await file.boundingBox();
  expect(header!.y - plate!.y).toBeLessThan(18);
  expect(header!.y + header!.height).toBeLessThan((await group(canvas, "build_dataset").boundingBox())!.y);
  await expect(canvas.locator(".project-port-label").first()).toBeVisible();
  const portNames = (await canvas.locator(".project-port-label").allTextContents()).map((name) => name.trim());
  expect(portNames.some((name) => name.length > 0 && !["Data", "Call", "Control", "Link"].includes(name))).toBe(true);
  const paths = canvas.locator(".react-flow__edge-path");
  await expect(paths.first()).toBeVisible();
  expect(await paths.evaluateAll((items) => items.every((path) => Boolean(path.getAttribute("marker-end"))))).toBe(true);

  await file.getByRole("button", { name: "Collapse group prepare.py", exact: true }).click();
  await expect(group(canvas, "build_dataset")).toHaveCount(0);
  await expect(canvas.locator(".react-flow__node")).toHaveCount(initialCount);
  // Folding does not remove the cross-file pipeline's relationships.
  await expect(canvas.locator(".react-flow__edge").first()).toBeVisible();
});

test("related lines respond to selection and explicit Focus; inspecting a line keeps navigation and camera", async ({ page, request }) => {
  const fixture = await (await request.get("/api/v1/project-test-fixture", { headers })).json();
  const canvas = await openDiagram(page, fixture.root);
  const viewport = canvas.locator(".react-flow__viewport");
  const before = await viewport.getAttribute("style");
  await group(canvas, "prepare.py").locator(".project-node-header").click();
  await expect(canvas.locator(".is-related-edge").first()).toBeVisible();
  await expect(canvas.locator(".is-muted-edge")).toHaveCount(0);
  await expect(viewport).toHaveAttribute("style", before!);
  const focus = canvas.getByRole("button", { name: "Focus", exact: true });
  await expect(focus).toHaveAttribute("aria-pressed", "false");
  await focus.click();
  await expect(focus).toHaveAttribute("aria-pressed", "true");
  // An axis-aligned SVG group may have a zero-height DOM bounding box even
  // though its stroked path is painted. Verify the path and opacity together.
  await expect.poll(() => canvas.locator(".is-muted-edge").first().evaluate(element => {
    const opacity = Number(getComputedStyle(element).opacity);
    const path = element.querySelector("path") as SVGPathElement | null;
    return opacity > 0 && opacity < 1 && !!path && path.getTotalLength() > 0;
  })).toBe(true);
  await focus.click();
  await expect(canvas.locator(".is-muted-edge")).toHaveCount(0);

  const tabs = await page.locator(".dv-tab").count();
  const edge = canvas.locator(".is-related-edge .react-flow__edge-path").first();
  const point = await edge.evaluate((element) => {
    const path = element as SVGPathElement;
    const at = path.getPointAtLength(path.getTotalLength() * 0.37);
    const p = new DOMPoint(at.x, at.y).matrixTransform(path.getScreenCTM()!);
    return { x: p.x, y: p.y };
  });
  await page.mouse.click(point.x, point.y);
  await expect(canvas.locator(".project-relation-detail")).toBeVisible();
  await expect(canvas.locator(".project-relation-detail")).toContainText("→");
  await expect(page.locator(".dv-tab")).toHaveCount(tabs);
  await expect(viewport).toHaveAttribute("style", before!);
});

test("dragging a function beyond its file keeps the block inside and below the file header", async ({ page, request }) => {
  const fixture = await (await request.get("/api/v1/project-test-fixture", { headers })).json();
  const canvas = await openDiagram(page, fixture.root);
  const file = group(canvas, "prepare.py");
  await file.getByRole("button", { name: "Expand group prepare.py", exact: true }).click();
  const fn = group(canvas, "build_dataset");
  await expect(fn).toBeVisible();
  await expect(canvas.locator(".project-canvas-status")).not.toBeVisible();
  const bounds = await file.boundingBox();
  const heading = await file.locator(".project-node-header").boundingBox();
  const handle = await fn.locator(".project-node-header").boundingBox();
  await page.mouse.move(handle!.x + handle!.width * 0.35, handle!.y + handle!.height * 0.5);
  await page.mouse.down();
  // Intentionally request a position both beyond the right edge and above
  // the title. The pointer gesture must obey the actual parent bounds.
  await page.mouse.move(bounds!.x + bounds!.width + 90, bounds!.y - 80, { steps: 16 });
  await page.mouse.up();
  const moved = await fn.boundingBox();
  expect(moved!.x).toBeGreaterThanOrEqual(bounds!.x - 1);
  expect(moved!.x + moved!.width).toBeLessThanOrEqual(bounds!.x + bounds!.width + 1);
  expect(moved!.y).toBeGreaterThanOrEqual(heading!.y + heading!.height - 1);
  expect(moved!.y + moved!.height).toBeLessThanOrEqual(bounds!.y + bounds!.height + 1);
});

test("dragged positions survive reload and Arrange replaces and persists the manual placement", async ({ page, request }) => {
  const fixture = await (await request.get("/api/v1/project-test-fixture", { headers })).json();
  const canvas = await openDiagram(page, fixture.root);
  const file = group(canvas, "prepare.py");
  const id = await file.getAttribute("data-id");
  const position = async () => {
    const box = await file.boundingBox();
    return box ? { x: Math.round(box.x), y: Math.round(box.y) } : null;
  };
  const initial = await position();
  const header = await file.locator(".project-node-header").boundingBox();
  const x = header!.x + header!.width * 0.4;
  const y = header!.y + header!.height * 0.5;
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x - 48, y - 32, { steps: 12 });
  await page.mouse.up();
  await expect.poll(position).not.toEqual(initial);
  await expect.poll(async () => (await cameraState(page, fixture.project_id))?.positions[id!]).toBeTruthy();
  const dragged = (await cameraState(page, fixture.project_id))!.positions[id!];
  const draggedPosition = await position();
  await page.reload();
  await expect.poll(position).toEqual(draggedPosition);
  expect((await cameraState(page, fixture.project_id))!.positions[id!]).toEqual(dragged);

  await canvas.getByRole("button", { name: "Arrange", exact: true }).click();
  await expect.poll(position).not.toEqual(draggedPosition);
  await expect.poll(async () => (await cameraState(page, fixture.project_id))?.positions[id!] ?? null).not.toEqual(dragged);
  const arrangedPosition = await position();
  await page.reload();
  await expect.poll(position).toEqual(arrangedPosition);
});
