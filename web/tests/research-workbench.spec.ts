import {test,expect} from '@playwright/test';
test.use({baseURL:'http://127.0.0.1:8879'});

test('research-workbench: real matrix, source, probe and NaN journey',async({page})=>{
  const errors:string[]=[];page.on('pageerror',error=>errors.push(error.message));
  await page.goto('/#session=research-test-session');
  await page.getByText('示例、脚本参数与扩展适配器',{exact:true}).click();
  await page.getByLabel('示例选择').selectOption('analysis');
  await page.getByRole('button',{name:'运行分析',exact:true}).click();
  await expect(page.getByTestId('run-status')).toHaveText('completed',{timeout:15000});
  await page.getByRole('searchbox',{name:'搜索变量'}).fill('Z');
  await page.getByRole('button',{name:/^Z ·/}).first().click();
  await expect(page.getByTestId('matrix-definition')).toContainText('120 × 8');
  await expect(page.getByRole('img',{name:'矩阵热图'})).toBeVisible();
  await expect(page.getByTestId('source-selection')).toContainText('Z = (X - mu) / sigma');
  await expect(page.getByLabel('源码第 21 行',{exact:true})).toBeInViewport();
  await expect(page.getByTestId('flow-node').filter({has:page.locator('strong').getByText('Z',{exact:true})})).toBeInViewport();
  await expect(page.getByTestId('operation-explanation')).toContainText('标准化');
  await page.screenshot({path:'../docs/assets/research-workbench.png'});
  await page.getByRole('button',{name:'添加探针',exact:true}).click();
  await page.getByLabel('探针种类').selectOption('finite');
  await page.getByRole('button',{name:'预演探针',exact:true}).click();
  await expect(page.getByTestId('probe-preview')).toContainText('pass');
  await page.getByRole('button',{name:'保存探针定义',exact:true}).click();
  await expect(page.getByRole('status').filter({hasText:'探针已保存'})).toBeVisible();
  await page.getByLabel('脚本参数').fill('--failure nan');
  const previousRun=await page.getByLabel('运行记录').inputValue();
  await page.getByRole('button',{name:'运行分析',exact:true}).click();
  await expect(page.getByLabel('运行记录')).not.toHaveValue(previousRun);
  await expect(page.getByTestId('run-status')).toHaveText('completed',{timeout:15000});
  await expect(page.getByTestId('quality-status')).toHaveText('fail');
  await page.getByRole('searchbox',{name:'搜索变量'}).fill('X');
  await page.getByRole('button',{name:/^X ·/}).first().click();
  await expect(page.getByTestId('probe-results')).toContainText('fail');
  await expect(page.getByTestId('source-selection')).toContainText('X[3, 2] = np.nan');
  await page.getByRole('button',{name:'查看变量历史',exact:true}).click();
  await page.getByRole('button',{name:'版本 1',exact:true}).click();
  await page.getByRole('button',{name:'读取此版本切片',exact:true}).click();
  await expect(page.getByTestId('slice-result')).toContainText('未保存完整数据');
  expect(errors).toEqual([]);
});

test('research-workbench: historical pages and probes remain reachable on narrower screens',async({page})=>{
  await page.goto('/#session=research-test-session');
  await page.getByLabel('运行记录').selectOption({label:await page.getByLabel('运行记录').locator('option').filter({hasText:'Analysis · completed'}).last().textContent()||''});
  await page.getByRole('button',{name:'读取历史事件',exact:true}).click();
  await expect(page.locator('.ri-event').first().locator('small')).toHaveText('1');
  await page.setViewportSize({width:960,height:800});
  await expect(page.getByRole('heading',{name:'探针',exact:true})).toBeVisible();
  await page.screenshot({path:'../.work/research-tablet.png',fullPage:true});
});

test('research-workbench: delayed saved preferences do not replace current edits',async({page})=>{
  let release=()=>{};const gate=new Promise<void>(resolve=>{release=resolve;});
  await page.route('**/research/experiment',async route=>{await gate;await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({name:'old',script:'old.py',interpreter:'old-python',arguments:['--old'],capture:{level:'full'},annotations:{},adapters:[],probes:[]})}).catch(()=>{});});
  await page.goto('/#session=research-test-session');
  await page.getByLabel('分析脚本').fill('current.py');
  release();
  await expect(page.getByLabel('示例选择').locator('option')).toHaveCount(3);
  await expect(page.getByLabel('分析脚本')).toHaveValue('current.py');
});
