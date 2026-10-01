import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests', testIgnore: '**/*.test.ts', workers: 1, timeout: 60000,
  reporter: [['list'], ['json', { outputFile: '../.work/browser-tests.json' }]],
  use: { baseURL: 'http://127.0.0.1:8877', viewport: { width: 1600, height: 1000 }, reducedMotion: 'reduce',
    channel: process.platform === 'win32' ? 'msedge' : undefined, screenshot: 'only-on-failure', trace: 'retain-on-failure' },
  webServer: ['serve_browser_test.py', 'serve_workspace_test.py', 'serve_research_test.py'].map((script, index) => ({ command: `${process.platform === 'win32' ? '..\\.venv\\Scripts\\python.exe' : '../.venv/bin/python'} ../scripts/${script}`, url: `http://127.0.0.1:${8877 + index}`, reuseExistingServer: false, timeout: 60000 })),
});
