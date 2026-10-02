import { expect, type Page } from '@playwright/test';
export async function chooseExample(page: Page, example = 'analysis', capture = 'summary', args: string[] = []) {
  await page.getByRole('button', { name: '打开源码配置' }).click();
  await page.getByLabel('示例选择').selectOption(example);
  await page.getByLabel('采集模式').selectOption(capture);
  await page.getByLabel('脚本参数 JSON').fill(JSON.stringify(args));
  await page.getByLabel('计算解释器').focus();
  const path = await page.getByLabel('分析脚本',{exact:true}).inputValue();
  const imported = page.waitForResponse(r => r.url().endsWith('/workbench/analyses') && r.request().method() === 'POST' && r.request().postDataJSON().path === path);
  await page.getByRole('button', { name: '导入解析', exact: true }).click();
  expect((await imported).ok()).toBe(true);
  await expect(page.getByRole('button', { name: '导入解析', exact: true })).toBeEnabled();
  await expect(page.getByRole('button',{name:'运行',exact:true})).toBeEnabled();
  await page.getByRole('button', { name: '打开源码配置' }).click();
}
export async function runCompute(page: Page) {
  await page.getByLabel('运行模式').selectOption('compute');
  const previous = await page.getByLabel('运行记录').inputValue();
  await page.getByRole('button', { name: '运行', exact: true }).click();
  await expect(page.getByLabel('运行记录')).not.toHaveValue(previous,{timeout:60000});
  await expect(page.getByTestId('task-record').first().locator('strong > span')).toHaveText('completed', { timeout: 60000 });
  await expect(page.getByTestId('run-status')).toHaveText('completed');
}
export async function selectObject(page:Page,name:string,toggle=false) {
  await page.getByRole('searchbox',{name:'搜索对象',exact:true}).fill(name);
  const escaped=name.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
  const row=page.locator('.object-row-name').filter({hasText:new RegExp('^'+escaped+'$')}).first().locator('..');
  await expect(row).toBeVisible();
  await row.click({modifiers:toggle?['Control']:[]});
  return row;
}
export async function chooseValue(page: Page, name: string) {
  const row=await selectObject(page,name);
  await expect(row.locator('small')).toContainText(/v\d+/);
  await row.dblclick();
  await expect(page.getByTestId('current-variable').last()).toHaveText(name);
}
export async function bindProbe(page:Page,type:string,binding='*') {
  if(binding!=='*')await selectObject(page,binding);
  await page.getByRole('button',{name:'探针台',exact:true}).first().click();
  await page.getByRole('button',{name:'添加探针',exact:true}).click();
  await page.getByLabel('探针绑定范围').selectOption(binding==='*'?'project':'selection');
  await page.getByLabel('探针类型').selectOption(type);
  await page.getByRole('button',{name:'确认添加探针',exact:true}).click();
}
export async function runMode(page:Page,mode:'probes'|'replot') {
  await page.getByLabel('运行模式').selectOption(mode);
  await page.getByRole('button',{name:'运行',exact:true}).click();
}
export async function researchApi(page: Page, path: string, body?: unknown, method?: string) {
  return page.evaluate(async ({ path, body, method }) => {
    const r = await fetch('/api/v1/' + path, { method: method ?? (body === undefined ? 'GET' : 'POST'), headers: { Authorization: 'Bearer ' + sessionStorage.getItem('cdaf-session'), 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) });
    const json = await r.json(); if (!r.ok) throw new Error(JSON.stringify(json)); return json;
  }, { path, body, method });
}
