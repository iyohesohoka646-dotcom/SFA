// Native large-project selection benchmark; uses an already indexed owned fixture.
const { _electron: electron } = require('../../web/node_modules/playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
(async () => {
  const fixture = process.env.CDAF_DESKTOP_SCALE_PROJECT;
  assert(fixture, 'Set an indexed 1,000-file fixture path');
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'sdi-project-scale-'));
  const exe = process.env.CDAF_DESKTOP_TEST_EXE;
  const env = { ...process.env, PYTHONUTF8: '1' }; delete env.PYTHONPATH;
  if (exe) delete env.CDAF_DESKTOP_PYTHON;
  else env.CDAF_DESKTOP_PYTHON = path.resolve(__dirname, '../../.work/desktop-python/python.exe');
  const app = await electron.launch({ executablePath: exe || require('electron'),
    args: [...(exe ? [] : [path.resolve(__dirname, '../src/main.cjs')]), '--project', root], env, timeout: 30000 });
  try {
    const page = await app.firstWindow();
    await page.getByText('Enter folder path', { exact: true }).click();
    await page.getByLabel('Folder path', { exact: true }).fill(fixture);
    await page.getByRole('button', { name: 'Open project', exact: true }).click();
    await page.locator('.react-flow__node').nth(1).waitFor({ timeout: 45000 });
    await page.getByRole('button', { name: 'Expand', exact: true }).click();
    await page.waitForFunction(() => document.querySelectorAll('.react-flow__node').length > 10, {}, { timeout: 45000 });
    await page.locator('.project-canvas-status').waitFor({ state: 'hidden' });
    const graph = await page.evaluate(async () => {
      const id = localStorage.getItem('cdaf.project.id');
      const headers = { Authorization: 'Bearer ' + sessionStorage.getItem('cdaf-session') };
      return (await fetch('/api/v1/research/projects/' + id + '/graph?view=code&limit=350', { headers })).json();
    });
    const count = graph.graph.nodes.length + graph.graph.blocks.length;
    assert(count <= 350 && graph.omitted_count > 0);
    const times = await page.locator('.react-flow').evaluate(async canvas => {
      const nodes = [...canvas.querySelectorAll('.react-flow__node')];
      const result = [];
      for (let i = 0; i < 40; i++) {
        const start = performance.now();
        nodes[i % 2].dispatchEvent(new MouseEvent('click', { bubbles: true }));
        await new Promise(requestAnimationFrame);
        result.push(performance.now() - start);
      }
      return result;
    });
    assert((await page.locator('.react-flow__node.selected').count()) > 0, 'Benchmark must actually change graph selection');
    times.sort((a, b) => a - b);
    const p95 = times[Math.floor(times.length * .95)];
    const receipt = { files: 1000, lines: 100000, visible_units: count,
      actual_rendered_nodes: await page.locator('.react-flow__node').count(),
      omitted: graph.omitted_count, selection_p95_ms: p95, samples: times.length,
      measurement: 'alternating graph selection to next animation frame in native Electron',
      target_ms: 50, target_met: p95 < 50, result: 'measured' };
    fs.writeFileSync(path.resolve(__dirname, '../../.work/project-acceptance/desktop-project-scale.json'), JSON.stringify(receipt, null, 2));
    console.log(JSON.stringify(receipt));
  } finally { await app.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
