import { test, expect } from '@playwright/test';
import { session } from './session';

test('workspace minimizes, resizes, locks and restores named layouts without execution', async ({ page }) => {
  let executions = 0;
  page.on('request', request => { if (/\/(execute|intelligence|replot|evaluate)$/.test(request.url()) && request.method() === 'POST') executions++; });
  await page.goto('http://127.0.0.1:8879/#session=' + session);
  await expect(page.getByRole('button', { name: '锁定布局', exact: true })).toBeVisible();
  const horizontal = page.locator('.dv-horizontal > .dv-sash-container > .dv-sash.dv-enabled').filter({visible:true}).first();
  await horizontal.focus(); await page.keyboard.press('ArrowRight');
  const vertical = page.locator('.dv-vertical > .dv-sash-container > .dv-sash.dv-enabled').filter({visible:true}).first();
  await vertical.focus(); await page.keyboard.press('ArrowUp');
  const bounds = await horizontal.boundingBox();
  if (bounds) { await page.mouse.move(bounds.x + 2, bounds.y + 60); await page.mouse.down(); await page.mouse.move(bounds.x + 40, bounds.y + 60); await page.mouse.up(); }
  await page.getByRole('button', { name: '缩小 main 视图' }).click();
  await page.getByRole('button', { name: '恢复 main 视图' }).click();
  await page.getByRole('button', { name: '放大 main 视图' }).click();
  await page.getByRole('button', { name: '还原 main 视图' }).click();
  await page.getByRole('button', { name: '锁定布局', exact: true }).click();
  const before = await horizontal.boundingBox();
  await page.getByRole('button', { name: '计算关系图', exact: true }).first().click();
  expect(await horizontal.boundingBox()).toEqual(before);
  await page.getByRole('button', { name: '布局', exact: true }).click();
  await page.getByLabel('布局名称').fill('科研对比');
  await page.getByRole('button', { name: '保存布局', exact: true }).click();
  await page.reload();
  await expect(page.getByRole('button', { name: '解锁布局', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '布局', exact: true }).click();
  await expect(page.getByRole('button', { name: '恢复布局 科研对比' })).toBeVisible();
  expect(executions).toBe(0);
});
