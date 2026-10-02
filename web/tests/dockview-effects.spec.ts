import { test, expect } from "@playwright/test";
import { session } from "./session";
for (const width of [900, 1100, 1280, 1600])
  test(`layout geometry really changes at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("http://127.0.0.1:8879/#session=" + session);
    await expect(
      page.getByRole("button", { name: "缩小 main 视图" }),
    ).toBeVisible();
    const panel = page.locator('[data-group="main"]');
    const before = await panel.boundingBox();
    await page.getByRole("button", { name: "缩小 main 视图" }).click();
    await expect(
      page.getByRole("button", { name: "恢复 main 视图" }),
    ).toBeVisible();
    expect((await panel.boundingBox())?.width ?? 0).toBeLessThan(
      before!.width * 0.6,
    );
    await page.getByRole("button", { name: "恢复 main 视图" }).click();
    await expect
      .poll(async () => Math.round((await panel.boundingBox())!.width))
      .toBe(Math.round(before!.width));
    await page.getByRole("button", { name: "设置", exact: true }).click();
    await expect(page.getByLabel("搜索设置")).toBeVisible();
  });
test("resize, maximize, locked slots and named layouts change and preserve actual geometry", async ({
  page,
}) => {
  await page.goto("http://127.0.0.1:8879/#session=" + session);
  const panel = page.locator('[data-group="main"]');
  await expect(panel).toBeVisible();
  const before = (await panel.boundingBox())!;
  const sash = page
    .locator(".dv-horizontal > .dv-sash-container > .dv-sash.dv-enabled")
    .filter({ visible: true })
    .first();
  const box = (await sash.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2 + 65, box.y + box.height / 2, {
    steps: 8,
  });
  await page.mouse.up();
  await expect
    .poll(async () =>
      Math.abs((await panel.boundingBox())!.width - before.width),
    )
    .toBeGreaterThan(30);
  const resized = (await panel.boundingBox())!;
  await page
    .getByRole("button", { name: "放大 main 视图", exact: true })
    .click();
  await expect
    .poll(async () => (await panel.boundingBox())!.width)
    .toBeGreaterThan(resized.width + 80);
  await page
    .getByRole("button", { name: "还原 main 视图", exact: true })
    .click();
  await expect
    .poll(async () => Math.round((await panel.boundingBox())!.width))
    .toBe(Math.round(resized.width));
  await page.getByRole("button", { name: "锁定布局", exact: true }).click();
  const count = await page.locator("[data-group]").count();
  await page.getByRole("button", { name: "设置", exact: true }).click();
  expect(await page.locator("[data-group]").count()).toBe(count);
  const locked = (await panel.boundingBox())!;
  await sash.focus();
  await sash.press("ArrowRight");
  expect(Math.round((await panel.boundingBox())!.width)).toBe(
    Math.round(locked.width),
  );
  await page.getByRole("button", { name: "布局", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "左右分屏", exact: true }),
  ).toBeDisabled();
  await page.getByLabel("布局名称").fill("geometry");
  await page.getByRole("button", { name: "保存布局", exact: true }).click();
  await page.reload();
  await expect(
    page.getByRole("button", { name: "解锁布局", exact: true }),
  ).toBeVisible();
  await expect
    .poll(async () =>
      Math.round(
        (await page.locator('[data-group="main"]').boundingBox())!.width,
      ),
    )
    .toBe(Math.round(locked.width));
});

for (const scale of [1.25, 1.5])
  test(`layout resize and restoration work at ${scale * 100}% device density`, async ({
    browser,
  }) => {
    const context = await browser.newContext({
      viewport: { width: 1280, height: 900 },
      deviceScaleFactor: scale,
      reducedMotion: "reduce",
    });
    const page = await context.newPage();
    try {
      await page.goto("http://127.0.0.1:8879/#session=" + session);
      expect(await page.evaluate(() => devicePixelRatio)).toBe(scale);
      const panel = page.locator('[data-group="main"]');
      await expect(panel).toBeVisible();
      const before = (await panel.boundingBox())!;
      const sash = page
        .locator(".dv-horizontal > .dv-sash-container > .dv-sash.dv-enabled")
        .filter({ visible: true })
        .first();
      const box = (await sash.boundingBox())!;
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
      await page.mouse.down();
      await page.mouse.move(
        box.x + box.width / 2 + 55,
        box.y + box.height / 2,
        { steps: 8 },
      );
      await page.mouse.up();
      await expect
        .poll(async () =>
          Math.abs((await panel.boundingBox())!.width - before.width),
        )
        .toBeGreaterThan(25);
      const resized = (await panel.boundingBox())!;
      await page
        .getByRole("button", { name: "缩小 main 视图", exact: true })
        .click();
      await expect
        .poll(async () => (await panel.boundingBox())?.width ?? 0)
        .toBeLessThan(resized.width * 0.6);
      await page
        .getByRole("button", { name: "恢复 main 视图", exact: true })
        .click();
      await expect
        .poll(async () => Math.round((await panel.boundingBox())!.width))
        .toBe(Math.round(resized.width));
    } finally {
      await context.close();
    }
  });
