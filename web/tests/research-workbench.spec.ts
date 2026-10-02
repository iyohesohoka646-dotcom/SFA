import {session} from './session';
import {test,expect} from '@playwright/test';
import {chooseExample,runCompute,chooseValue} from './scientific-helpers';
test.use({baseURL:'http://127.0.0.1:8879'});

test('research-workbench: real matrix, source, checks and NaN journey',async({page})=>{
  const errors:string[]=[];page.on('pageerror',error=>errors.push(error.message));
  await page.goto(`/#session=${session}`);await chooseExample(page);await runCompute(page);await chooseValue(page,'Z');
  await expect(page.getByTestId('matrix-definition')).toContainText('120 × 8');
  await expect(page.getByRole('img',{name:'矩阵热图'})).toBeVisible();
  await expect(page.getByTestId('source-selection')).toContainText('Z = (X - mu) / sigma');
  await page.getByText('计算定义与解释',{exact:true}).click();
  await expect(page.getByTestId('operation-explanation')).toContainText('标准化');
  await page.screenshot({path:'../docs/assets/research-workbench.png'});
  await chooseExample(page,'analysis','summary',['--failure','nan']);await runCompute(page);await chooseValue(page,'X');
  await page.getByRole('button',{name:'探针台',exact:true}).click();
  await expect(page.getByTestId('probe-output').filter({hasText:'fail'}).first()).toBeVisible();
  await expect(page.getByTestId('source-selection')).toContainText('np.nan');
  await page.getByRole('button',{name:'查看变量历史'}).click();await page.getByRole('button',{name:'版本 1',exact:true}).click();
  await page.getByRole('button',{name:'读取此版本切片',exact:true}).click();
  await expect(page.getByTestId('slice-result')).toContainText('未保存完整数据');
  expect(errors).toEqual([]);
});

test('research-workbench: paged historical events and narrow workspace remain reachable',async({page})=>{
  await page.goto(`/#session=${session}`);
  await page.getByLabel('运行记录').selectOption({label:await page.getByLabel('运行记录').locator('option').filter({hasText:'Analysis · completed'}).last().textContent()||''});
  await page.getByRole('button',{name:'运行事件',exact:true}).click();await page.getByRole('button',{name:'读取历史事件',exact:true}).click();
  await expect(page.locator('.ri-event').first().locator('small')).toHaveText('1');
  await page.setViewportSize({width:960,height:800});await page.getByRole('button',{name:'探针台',exact:true}).click();
  await expect(page.getByRole('button',{name:'添加探针',exact:true})).toBeVisible();
  await page.screenshot({path:'../.work/research-tablet.png',fullPage:true});
});

test('research-workbench: delayed preferences cannot replace current source edits',async({page})=>{
  let release=()=>{};const gate=new Promise<void>(resolve=>{release=resolve;});
  await page.route('**/research/workbench/configuration',async route=>{const response=await route.fetch();await gate;await route.fulfill({response}).catch(()=>{});});
  await page.goto(`/#session=${session}`);await page.getByRole('button',{name:'打开源码配置'}).click();
  await page.getByLabel('分析脚本').fill('current.py');release();
  await expect(page.getByLabel('示例选择').locator('option')).toHaveCount(3);
  await expect(page.getByLabel('分析脚本')).toHaveValue('current.py');
});
