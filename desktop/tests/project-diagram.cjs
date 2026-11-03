// Verify diagram delivery through the installed executable and private backend.
// All projects and app state for this acceptance run are disposable.
const { _electron: electron } = require('../../web/node_modules/playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

(async () => {
  const executablePath = process.env.CDAF_DESKTOP_TEST_EXE;
  assert(executablePath, 'Set CDAF_DESKTOP_TEST_EXE to the installed executable');
  const repo = path.resolve(__dirname, '../..');
  const root = fs.mkdtempSync(path.join(repo, '.work/native-diagram-'));
  const lab = path.join(root, 'flat-lab');
  fs.cpSync(path.join(repo, 'examples/research/projects/flat-lab'), lab, { recursive: true });
  const env = { ...process.env, PYTHONUTF8: '1', CDAF_HOME: path.join(root, 'home') };
  delete env.PYTHONPATH; delete env.CDAF_DESKTOP_PYTHON;
  const app = await electron.launch({ executablePath, args: ['--project', root, '--user-data-dir=' + path.join(root, 'profile')], env, timeout: 30000 });
  const errors = [];
  try {
    const page = await app.firstWindow();
    page.on('pageerror', error => errors.push(error.message));
    page.setDefaultTimeout(15000);
    await page.locator('.project-host-bar').waitFor({ timeout: 45000 });
    await page.getByText('Enter folder path', { exact: true }).click();
    await page.getByLabel('Folder path', { exact: true }).fill(lab);
    await page.getByRole('button', { name: 'Open project', exact: true }).click();
    const canvas = page.locator('.project-canvas');
    await canvas.locator('.react-flow__node').first().waitFor();
    await canvas.locator('.project-canvas-status').waitFor({ state: 'hidden' });
    await canvas.getByRole('button', { name: 'Expand group prepare.py', exact: true }).waitFor();
    assert((await canvas.locator('.project-port-label').allTextContents()).includes('build_dataset'));
    assert(await canvas.locator('.react-flow__edge-path').evaluateAll(paths => paths.length > 0 && paths.every(p => p.hasAttribute('marker-end'))));
    const count = await canvas.locator('.react-flow__node').count();
    await canvas.getByRole('button', { name: 'Expand group prepare.py', exact: true }).click();
    await page.waitForFunction(n => document.querySelectorAll('.project-canvas .react-flow__node').length > n, count);
    await canvas.locator('.project-canvas-status').waitFor({ state: 'hidden' });
    await canvas.getByRole('button', { name: 'Collapse', exact: true }).click();
    await canvas.locator('.project-canvas-status').waitFor({ state: 'hidden' });
    const sizes = [];
    for (const width of [1600, 900]) {
      await app.evaluate(({ BrowserWindow }, width) => BrowserWindow.getAllWindows()[0].setBounds({ width, height: 950 }), width);
      await canvas.getByRole('button', { name: 'Fit', exact: true }).click();
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
      assert(await canvas.evaluate(element => element.scrollWidth <= element.clientWidth + 1));
      sizes.push(width);
      await page.screenshot({ path: path.join(root, `diagram-${width}.png`) });
    }
    await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].setBounds({ width: 1600, height: 1000 }));
    await page.getByRole('button', { name: '切换主题', exact: true }).click();
    await canvas.screenshot({ path: path.join(root, 'diagram-dark.png') });
    await page.getByRole('button', { name: '切换主题', exact: true }).click();
    await canvas.getByRole('button', { name: 'Fit', exact: true }).click();
    await canvas.screenshot({ path: path.join(root, 'diagram-light.png') });
    const origin = await page.evaluate(() => location.origin);
    const closed = app.waitForEvent('close');
    await page.getByRole('button', { name: '退出并停止', exact: true }).click();
    await closed;
    await assert.rejects(fetch(origin + '/api/v1/studio'));
    assert.deepEqual(errors, []);
    const receipt = { executablePath, sizes, private_backend: true, directed_named_connections: true, local_expansion: true, renderer_errors: errors, owner_port_released: true, artifacts: root };
    fs.writeFileSync(path.join(root, 'receipt.json'), JSON.stringify(receipt, null, 2));
    console.log(JSON.stringify(receipt));
  } finally { await app.close().catch(() => {}); }
})().catch(error => { console.error(error); process.exitCode = 1; });
