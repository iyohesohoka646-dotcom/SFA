import { expect, type Page } from '@playwright/test';
export async function chooseExample(page: Page, example = 'analysis', capture = 'summary', args: string[] = []) {
  await page.getByRole('button', { name: '打开源码配置' }).click();
  await page.getByLabel('示例选择').selectOption(example);
  await page.getByLabel('采集模式').selectOption(capture);
  await page.getByLabel('脚本参数 JSON').fill(JSON.stringify(args));
  await page.getByLabel('计算解释器').focus();
  await page.getByRole('button', { name: '导入解析', exact: true }).click();
  await expect(page.getByRole('button', { name: '导入解析', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: '打开源码配置' }).click();
}
export async function runCompute(page: Page) {
  const previous = await page.getByLabel('运行记录').inputValue();
  await page.getByRole('button', { name: '运行', exact: true }).click();
  await expect(page.getByLabel('运行记录')).not.toHaveValue(previous);
  await expect(page.getByTestId('task-record').first().locator('strong > span')).toHaveText('completed', { timeout: 60000 });
  await expect(page.getByTestId('run-status')).toHaveText('completed');
}
export async function chooseValue(page: Page, name: string) {
  await page.getByRole('searchbox', { name: '搜索变量' }).fill(name);
  await page.getByRole('button', { name: new RegExp('^' + name + ' ·') }).first().click();
  await expect(page.getByTestId('current-variable').last()).toHaveText(name);
}
export async function researchApi(page: Page, path: string, body?: unknown, method?: string) {
  return page.evaluate(async ({ path, body, method }) => {
    const r = await fetch('/api/v1/' + path, { method: method ?? (body === undefined ? 'GET' : 'POST'), headers: { Authorization: 'Bearer ' + sessionStorage.getItem('cdaf-session'), 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) });
    const json = await r.json(); if (!r.ok) throw new Error(JSON.stringify(json)); return json;
  }, { path, body, method });
}
