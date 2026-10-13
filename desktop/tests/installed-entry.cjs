// Verify the installed shortcut's exact target and arguments against real user data.
const { _electron: electron } = require('../../web/node_modules/playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

(async () => {
  assert(process.env.CDAF_DESKTOP_TEST_SHORTCUT, 'Set the actual desktop shortcut path');
  const shell = spawnSync('powershell.exe', ['-NoProfile', '-Command',
    '[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new(); $s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:CDAF_DESKTOP_TEST_SHORTCUT); @{target=$s.TargetPath;arguments=$s.Arguments;cwd=$s.WorkingDirectory}|ConvertTo-Json -Compress'],
    { encoding: 'utf8', windowsHide: true, timeout: 10000 });
  assert.equal(shell.status, 0, shell.stderr);
  const shortcut = JSON.parse(shell.stdout);
  assert.equal(shortcut.arguments, '', 'Expected the installed default entry, without test switches');
  assert(fs.existsSync(shortcut.target));
  const env = { ...process.env, PYTHONUTF8: '1' };
  for (const key of ['CDAF_DESKTOP_PYTHON', 'PYTHONPATH', 'CDAF_HOME']) delete env[key];
  const app = await electron.launch({ executablePath: shortcut.target, args: [], cwd: shortcut.cwd, env, timeout: 30000 });
  const errors = [];
  try {
    const page = await app.firstWindow();
    page.on('pageerror', error => errors.push(error.message));
    await page.locator('.project-host-bar').waitFor({ timeout: 45000 });
    await page.getByLabel('Folder path').waitFor({ timeout: 45000 });
    assert.equal(await page.locator('.project-host-error').count(), 0, 'Missing remembered projects must return to the chooser without an error');
    assert.equal(await app.evaluate(({ app }) => app.getVersion()), '0.6.0');
    const info = await page.evaluate(async () => {
      const response = await fetch('/api/v1/research/info', {
        headers: { Authorization: 'Bearer ' + sessionStorage.getItem('cdaf-session') },
      });
      if (!response.ok) throw Error('Installed core unavailable: ' + response.status);
      return response.json();
    });
    assert.equal(info.software_version, '0.6.0');
    const background = await page.locator('.project-host').evaluate(element => getComputedStyle(element).backgroundColor);
    assert.notEqual(background, 'rgba(0, 0, 0, 0)', 'Project header must have its theme background');
    await page.screenshot({ path: path.resolve(__dirname, '../../docs/assets/project-installed-startup.png') });
    const origin = await page.evaluate(() => location.origin);
    const closed = app.waitForEvent('close');
    await page.getByRole('button', { name: '退出并停止', exact: true }).click();
    await closed;
    await assert.rejects(fetch(origin + '/api/v1/studio'));
    assert.deepEqual(errors, []);
    const receipt = { version: '0.6.0', entry_kind: 'installed-shortcut-target',
      shortcut: process.env.CDAF_DESKTOP_TEST_SHORTCUT, target: shortcut.target,
      exact_shortcut_arguments: true, node_or_checkout_override: false,
      core_version: info.software_version, root: info.root, renderer_errors: errors,
      theme_background: background, restored_chooser_without_error: true,
      owner_cleanup: true, port_released: true, result: 'passed' };
    fs.writeFileSync(path.resolve(__dirname, '../../.work/project-acceptance/desktop-installed-entry.json'), JSON.stringify(receipt, null, 2));
    console.log(JSON.stringify(receipt));
  } finally { await app.close().catch(() => {}); }
})().catch(error => { console.error(error); process.exitCode = 1; });
