import {session} from './session';
import {test,expect} from '@playwright/test';
test.use({baseURL:'http://127.0.0.1:8879'});
test('research-matrix: complex, higher axes, empty matrices and table indices',async({page})=>{
  await page.goto(`/#session=${session}`);
  await page.getByText('示例、脚本参数与扩展适配器',{exact:true}).click();
  await page.getByLabel('示例选择').selectOption('edge-cases');
  await page.getByRole('button',{name:'运行分析',exact:true}).click();
  await expect(page.getByTestId('run-status')).toHaveText('completed',{timeout:15000});
  const search=page.getByRole('searchbox',{name:'搜索变量'});
  await search.fill('complex_matrix');await page.getByRole('button',{name:/^complex_matrix ·/}).first().click();
  await page.getByLabel('复数显示').selectOption('imag');
  await expect(page.getByTestId('matrix-cell-value')).toContainText('4');
  await search.fill('tensor');await page.getByRole('button',{name:/^tensor ·/}).first().click();
  await expect(page.getByLabel('固定 axis 0')).toBeVisible();
  await page.getByLabel('固定 axis 0').fill('1');
  await page.getByRole('button',{name:'读取此版本切片',exact:true}).click();
  await expect(page.getByTestId('slice-result')).toContainText('未保存完整数据');
  await search.fill('empty_matrix');await page.getByRole('button',{name:/^empty_matrix ·/}).first().click();
  await expect(page.getByTestId('matrix-empty')).toContainText('空矩阵');
  await search.fill('frame');await page.getByRole('button',{name:/^frame ·/}).first().click();
  await expect(page.getByRole('table',{name:'数据表预览'})).toBeVisible();
  await expect(page.getByRole('table',{name:'数据表预览'})).toContainText('重复索引');
  await expect(page.getByRole('table',{name:'数据表预览'})).toContainText('[REDACTED]');
  const download=page.waitForEvent('download');await page.getByRole('button',{name:'导出离线报告',exact:true}).click();
  const artifact=await download;await artifact.saveAs('../.work/research-offline.html');
  await page.goto('file:///'+process.cwd().replaceAll('\\','/')+'/../.work/research-offline.html');
  await expect(page.getByRole('heading',{name:'Scientific Dataflow Inspector'})).toBeVisible();
  await expect(page.locator('body')).not.toContainText('private@example.org');
});

test('research-matrix: exact slices use exact coordinates and keyboard selection',async({page})=>{
  await page.goto(`/#session=${session}`);
  await page.getByText('示例、脚本参数与扩展适配器',{exact:true}).click();
  await page.getByLabel('示例选择').selectOption('edge-cases');
  await page.getByLabel('采集级别').selectOption('full');
  const previous=await page.getByLabel('运行记录').inputValue();
  await page.getByRole('button',{name:'运行分析',exact:true}).click();
  await expect(page.getByLabel('运行记录')).not.toHaveValue(previous);
  await expect(page.getByTestId('run-status')).toHaveText('completed',{timeout:15000});
  await page.getByRole('searchbox',{name:'搜索变量'}).fill('tensor');
  await page.getByRole('button',{name:/^tensor ·/}).first().click();
  await page.getByLabel('固定 axis 0').fill('1');
  await page.getByRole('button',{name:'读取此版本切片',exact:true}).click();
  await expect(page.getByTestId('slice-result')).toContainText('已读取');
  await expect(page.getByTestId('matrix-cell-value')).toContainText('12');
  await page.getByRole('img',{name:'矩阵热图'}).focus();
  await page.keyboard.press('ArrowRight');
  await expect(page.getByTestId('matrix-cell-value')).toHaveText('[0, 1] = 13');
});

test('research-matrix: an independent point-cloud renderer uses the same workbench',async({page})=>{
  await page.goto(`/#session=${session}`);
  await page.getByLabel('运行记录').selectOption({label:await page.getByLabel('运行记录').locator('option').filter({hasText:'Point cloud extension'}).first().textContent()||''});
  await page.getByRole('searchbox',{name:'搜索变量'}).fill('points');
  await page.getByRole('button',{name:/^points ·/}).first().click();
  await expect(page.getByRole('img',{name:'扩展点云预览'})).toBeVisible();
  await expect(page.locator('[data-testid=point-cloud] circle')).toHaveCount(2);
});
