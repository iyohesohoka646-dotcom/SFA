// Observe a real 10 Hz run from its timestamp to the painted selected matrix.
const { chromium } = require('../web/node_modules/playwright');
const { spawn } = require('node:child_process');
const { createInterface } = require('node:readline');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const seconds = Number(process.argv[2] || 60);
  assert(Number.isInteger(seconds) && seconds >= 10 && seconds <= 600);
  const root = path.resolve('.work/research-stream-' + Date.now());
  const host = spawn(path.resolve('.venv/Scripts/python.exe'), ['-u', '-X', 'utf8', 'scripts/soak_host.py', root, String(seconds)],
    { windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
  let browser;
  try {
    const handle = await new Promise((resolve, reject) => {
      createInterface({ input: host.stdout }).once('line', line => resolve(JSON.parse(line)));
      host.once('exit', () => reject(Error('Stream fixture exited before readiness')));
    });
    browser = await chromium.launch({ channel: 'msedge' });
    const page = await browser.newPage({ viewport: { width: 1600, height: 1000 }, reducedMotion: 'reduce' });
    await page.addInitScript(() => {
      window.streamPaints = [];
      let last = 0;
      new MutationObserver(() => {
        const version = Number(document.querySelector('.ri-data header span')?.textContent.match(/^v(\d+)/)?.[1]);
        if (!version || version <= last || document.querySelector('[data-testid="detail-status"]')?.textContent !== '详情已就绪') return;
        last = version;
        requestAnimationFrame(() => requestAnimationFrame(() => window.streamPaints.push({ version, visible_at_ms: Date.now() })));
      }).observe(document, { childList: true, subtree: true, characterData: true });
    });
    await page.goto(handle.url);
    await page.getByRole('button', { name: '运行分析', exact: true }).waitFor();
    const state = JSON.parse(fs.readFileSync(path.join(root, '.cdaf/studio.json'), 'utf8'));
    const base = `http://127.0.0.1:${state.port}`, headers = { Authorization: 'Bearer ' + state.token, 'Content-Type': 'application/json' };
    const response = await fetch(base + '/api/v1/research/runs', { method: 'POST', headers,
      body: JSON.stringify({ script: handle.script, interpreter: path.resolve('.venv/Scripts/python.exe'),
        watched_names: ['X'], instrument: 'auto', mode: 'summary', probes: [] }) });
    assert(response.ok, 'The scientific run must start');
    const run = await response.json(), id = run.run_id || run.id;
    await page.getByRole('button', { name: '刷新记录', exact: true }).click();
    await page.getByLabel('运行记录').selectOption(id);
    await page.getByRole('button', { name: /^X ·/ }).first().click();
    await page.getByRole('img', { name: '矩阵热图' }).waitFor();
    await page.getByTestId('run-status').filter({ hasText: 'completed' }).waitFor({ timeout: (seconds + 30) * 1000 });
    await page.waitForTimeout(300);
    const record = await (await fetch(base + '/api/v1/research/runs/' + id, { headers })).json();
    const observations = [];
    let cursor = 0;
    while (true) {
      const events = await (await fetch(base + `/api/v1/research/runs/${id}/event-page?after=${cursor}&limit=200`, { headers })).json();
      if (!events.length) break;
      for (const event of events) if (event.kind === 'value.observed' && event.payload.snapshot?.name === 'X') observations.push(event.payload.snapshot);
      cursor = events.at(-1).sequence;
    }
    const paints = await page.evaluate(() => window.streamPaints);
    const times = new Map(observations.map(snapshot => [snapshot.version, Date.parse(snapshot.observed_at)]));
    const samples = paints.filter(paint => times.has(paint.version)).map(paint => ({ version: paint.version,
      observation_to_paint_ms: paint.visible_at_ms - times.get(paint.version) }));
    const sorted = samples.map(sample => sample.observation_to_paint_ms).sort((a, b) => a - b);
    const receipt = { measured_at: new Date().toISOString(), browser: 'Microsoft Edge', duration_seconds: seconds,
      fixture: { shape: [64, 64], target_hz: 10, capture: 'summary', probes: 0 },
      scope: 'Same-host observation timestamp to two animation frames after selected snapshot details are ready; includes batching, transport, storage, UI state and detail fetch. Observation precedes publication, so this is a conservative bound; no cross-host clock claim.',
      status: record.status, observed_versions: observations.length, rendered_versions: samples.length,
      omitted_versions: observations.length - samples.length,
      p50_ms: sorted[Math.floor(sorted.length * .5)], p95_ms: sorted[Math.ceil(sorted.length * .95) - 1], max_ms: sorted.at(-1), samples };
    fs.writeFileSync('docs/assets/research-stream-performance.json', JSON.stringify(receipt, null, 2) + '\n');
    assert.equal(record.status, 'completed');
    assert(samples.length >= seconds * 5, 'At least half the 10 Hz stream must be measured');
    assert(sorted.every(value => value >= 0), 'Same-host timestamps must agree');
    assert(receipt.p95_ms <= 250, 'Observation-to-paint p95 exceeds the 250 ms budget');
    console.log(JSON.stringify({ measured: samples.length, omitted: receipt.omitted_versions, p50_ms: receipt.p50_ms, p95_ms: receipt.p95_ms }));
  } finally {
    if (browser) await browser.close();
    await new Promise(resolve => { if (host.exitCode !== null) return resolve(); host.once('exit', resolve);
      const timeout = setTimeout(() => { host.kill(); resolve(); }, 10000); timeout.unref(); });
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
