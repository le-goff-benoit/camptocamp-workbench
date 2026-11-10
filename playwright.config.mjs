import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './tests/ui', workers: 1, retries: 0, timeout: 45000,
  use: { baseURL: 'http://127.0.0.1:18796', headless: true, channel: process.env.WORKBENCH_TEST_BROWSER || undefined, viewport: { width: 1360, height: 900 }, screenshot: 'only-on-failure' },
  webServer: { command: 'python3 scripts/qa_server.py', url: 'http://127.0.0.1:18796/workbench/health', reuseExistingServer: false, timeout: 15000 },
});
