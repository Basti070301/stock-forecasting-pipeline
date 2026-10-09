import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './e2e', timeout: 90000, workers: 1,
  use: { baseURL: 'http://127.0.0.1:8000', headless: true,
    ...(process.env.SI_TEST_EDGE ? { channel: 'msedge' } : {}) },
  webServer: { command: `${process.env.SI_TEST_PYTHON || 'python'} -m uvicorn src.platform.api:app --host 127.0.0.1 --port 8000`,
    cwd: '..', url: 'http://127.0.0.1:8000/api/health', reuseExistingServer: !process.env.CI, timeout: 120000,
    env: { SI_MODE: 'demo', SI_RUNTIME_DIR: '.runtime/e2e' } },
});
