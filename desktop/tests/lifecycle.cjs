// Actual native application acceptance, including its private scientific runtime.
const { _electron: electron } = require('../../web/node_modules/playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const { spawnSync } = require('node:child_process');

(async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'cdaf-desktop-'));
  const installed = process.env.CDAF_DESKTOP_TEST_EXE;
  const scale = Number(process.env.CDAF_DESKTOP_TEST_SCALE || '1');
  const environment = { ...process.env, PYTHONUTF8: '1' };
  if (installed) delete environment.CDAF_DESKTOP_PYTHON;
  else environment.CDAF_DESKTOP_PYTHON = path.resolve(__dirname, '../../.work/desktop-python/python.exe');
  const python = installed
    ? path.join(path.dirname(installed), 'resources/python/python.exe')
    : environment.CDAF_DESKTOP_PYTHON;
  const invoke = args => {
    const result = spawnSync(python, ['-X', 'utf8', '-m', 'contract_driven_ai_flow', '--json', ...args],
      { cwd: root, env: environment, encoding: 'utf8', windowsHide: true, timeout: 30000 });
    assert.equal(result.status, 0, (result.stderr || result.stdout || result.error?.message || '').slice(-2000));
    return JSON.parse(result.stdout);
  };
  const code = 'import numpy as np\nimport pandas as pd\nX = np.arange(12, dtype=float).reshape(3,4)\nmu = X.mean(axis=0)\nZ = X - mu\nZ[1,2] = np.nan\nframe = pd.DataFrame({"value":[1,2],"email":["lab-sensitive@example.org","another@example.org"]})\n';
  const script = path.join(root, '自己的分析.py');
  fs.writeFileSync(script, code, 'utf8');
  const app = await electron.launch({
    executablePath: installed || require('electron'),
    args: [...(installed ? ['--project', root] : [path.resolve(__dirname, '../src/main.cjs'), '--project', root]), '--force-device-scale-factor=' + scale],
    env: environment, timeout: 30000,
  });
  try {
    const window = await app.firstWindow();
    assert.equal(await window.evaluate(() => devicePixelRatio), scale);
    await window.getByRole('button', { name: '运行', exact: true }).waitFor({ timeout: 30000 });
    await window.getByRole('button', { name: '打开终端', exact: true }).waitFor({ timeout: 5000 });
    const version = spawnSync(python, ['-c', 'import contract_driven_ai_flow; print(contract_driven_ai_flow.__version__)'],
      { cwd: root, env: environment, encoding: 'utf8', windowsHide: true, timeout: 10000 }).stdout.trim();
    assert.equal(version, '0.5.0', 'The installed desktop must contain the same scientific Python release');
    await window.getByRole('button', { name: '打开源码配置' }).click();
    await window.getByLabel('分析脚本', { exact: true }).fill(script);
    await window.getByRole('button', { name: '导入解析', exact: true }).click();
    await window.getByLabel('源码第 5 行', { exact: true }).waitFor();
    await window.getByRole('button', { name: '打开源码配置' }).click();
    await window.getByRole('button', { name: '运行', exact: true }).click();
    await window.getByTestId('task-record').first().locator('strong > span').filter({ hasText: /^completed$/ }).waitFor({ timeout: 60000 });
    const runId = await window.getByLabel('运行记录').inputValue();
    const chooseValue = async name => {await window.getByRole('searchbox',{name:'搜索对象',exact:true}).fill(name);const row=window.locator('.object-row-name').filter({hasText:new RegExp('^'+name+'$')}).first().locator('..');await row.dblclick();await window.getByTestId('current-variable').filter({hasText:new RegExp('^'+name+'$')}).waitFor();};
    await chooseValue('Z');
    await window.getByRole('img', { name: '矩阵热图' }).waitFor();
    await window.getByTestId('matrix-color-legend').waitFor();
    assert.match(await window.getByTestId('source-selection').textContent(), /Z\[1,2\] = np.nan/);
    await window.screenshot({ path: path.resolve(__dirname, '../../docs/assets/research-desktop.png') });
    await window.getByRole('button', { name: '探针台', exact: true }).click();
    await window.getByRole('button', { name: '添加探针', exact: true }).click();
    await window.getByLabel('探针类型').selectOption('view.matplotlib');
    await window.getByRole('searchbox',{name:'搜索对象',exact:true}).fill('X');await window.locator('.object-row-name').filter({hasText:/^X$/}).first().locator('..').click();
    await window.getByLabel('探针绑定范围').selectOption('selection');
    await window.getByRole('button', { name: '确认添加探针', exact: true }).click();
    await window.getByRole('button', { name: '保存', exact: true }).click();
    await window.getByLabel('运行模式').selectOption('replot');await window.getByRole('button',{name:'运行',exact:true}).click();
    await window.getByTestId('task-record').first().locator(':scope > strong').filter({ hasText: /^replot/ }).waitFor();
    await window.getByTestId('task-record').first().locator('strong > span').filter({ hasText: /^completed$/ }).waitFor({ timeout: 60000 });
    await chooseValue('X');
    await window.getByLabel('数据呈现探针').selectOption({ label: 'Matplotlib' });
    await window.getByRole('img', { name: '绘图探针产物' }).waitFor();
    await window.getByRole('button', { name: '智能助手', exact: true }).click();
    await window.getByLabel('任务指令').fill('Explain the calculation');
    await window.getByRole('button', { name: '执行智能任务', exact: true }).click();
    await window.getByTestId('task-record').first().locator('strong > span').filter({ hasText: /^completed$/ }).waitFor({ timeout: 30000 });
    await window.getByRole('button', { name: '查看智能结果', exact: true }).first().click();
    const scope = await window.locator('.wb-context-view').textContent();
    assert(!scope.includes('lab-sensitive@example.org'));
    const record = JSON.parse(fs.readFileSync(path.join(root, '.cdaf/studio.json'), 'utf8'));
    const runs = invoke(['research', 'runs', '--project', root]);
    assert(runs.some(run => run.id === runId && run.status === 'completed' && run.summary.quality === 'fail'));
    assert(invoke(['models', 'list', '--project', root]).some(profile => profile.id === 'offline'));
    const html = await (await fetch(`http://127.0.0.1:${record.port}/api/v1/research/runs/${runId}/export/html`,
      { headers: { Authorization: 'Bearer ' + record.token } })).text();
    assert(html.includes('Scientific Dataflow Inspector') && !html.includes('lab-sensitive@example.org'));
    assert(!/<script[^>]+src=["']https?:/.test(html));
    assert.equal(fs.readFileSync(script, 'utf8'), code);
    const closed = app.waitForEvent('close');
    await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].close());
    await closed;
    assert.equal(fs.existsSync(path.join(root, '.cdaf/studio.json')), false);
    await assert.rejects(fetch(`http://127.0.0.1:${record.port}/api/v1/studio`));
    fs.writeFileSync(path.resolve(__dirname, '../../docs/assets/research-desktop-validation.json'), JSON.stringify({
      platform: process.platform, installed: !!installed, device_scale_factor:scale, core_version: version, window_close: true,
      port_released: true, backend_pid: record.pid, own_script: true, source_preserved: true,
      matrix_and_anomaly: true, configured_probe_and_replot: true, automatic_harness_scope: true,
      shared_cli_history: true, offline_models: true, offline_report_privacy: true,
      run_id: runId, result: 'passed',
    }, null, 2));
  } finally { await app.close().catch(() => {}); }
})().catch(error => { console.error(error); process.exitCode = 1; });
