// Requires the existing frontend development dependencies. No UI changes.
import fs from 'node:fs';
import { createRequire } from 'node:module';
const require = createRequire(new URL('../frontend/package.json', import.meta.url));
const { chromium, expect } = require('@playwright/test');
const values = Object.fromEntries(fs.readFileSync(process.argv[2] || '.env.docker', 'utf8')
  .split(/\r?\n/).filter(line => line && !line.startsWith('#')).map(line => {
    const split = line.indexOf('='); return [line.slice(0, split), line.slice(split + 1)];
  }));
const preview = values.SI_DEPLOYMENT_PROFILE === 'historical-preview';
if (!(values.COMPOSE_PROJECT_NAME.startsWith('stockintelligence-m22-test') || (preview && values.COMPOSE_PROJECT_NAME.startsWith('stockintelligence-m43-test'))) || values.SI_BIND_IP !== '127.0.0.1' || !['127.0.0.1', 'localhost'].includes(values.SI_PUBLIC_HOST)) {
  throw new Error('Only the isolated loopback test stack is allowed');
}
const browser = await chromium.launch(process.env.SI_TEST_EDGE ? { channel: 'msedge' } : {});
try {
  // Self-signed test certificate; the HTTP smoke test separately checks its CA/hostname.
  const context = await browser.newContext({ ignoreHTTPSErrors: true,
    httpCredentials: { username: values.SI_AUTH_USER, password: values.SI_AUTH_PASSWORD },
    viewport: { width: 1440, height: 1000 } });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(`https://${values.SI_PUBLIC_HOST}:${values.SI_PORT}/`);
  await expect(page.getByRole('heading', { name: 'Der Markt. Mit Kontext.' })).toBeVisible();
  await expect(page.getByRole('link', { name: /Apple AAPL/ })).toBeVisible({ timeout: 60000 });
  await page.getByRole('link', { name: /Apple AAPL/ }).click();
  await expect(page.getByRole('heading', { name: 'Technische Features' })).toBeVisible();
  if (preview) {
    await expect(page.getByText('DEMO / HISTORIE', { exact: true })).toBeVisible();
    await expect(page.getByText('Historischer Research Replay', { exact: true }).first()).toBeVisible({ timeout: 60000 });
    await expect(page.getByText('Insufficient Evidence', { exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Current-Paar ausdrücklich erstellen' })).toHaveCount(0);
  }
  await page.screenshot({ path: preview ? '.runtime/m43-docker/browser.png' : '.runtime/m22-docker/browser.png', fullPage: true });
  if (preview) {
    await page.getByRole('navigation').getByRole('link', { name: 'Model Analytics', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Eingefrorene Modelle · Holdout-Vergleich' })).toBeVisible();
    await expect(page.getByText('retrospective_diagnostic', { exact: true })).toBeVisible({ timeout: 60000 });
    await page.screenshot({ path: '.runtime/m43-docker/reports.png', fullPage: true });
  }
  expect(errors).toEqual([]);
  console.log('Docker browser smoke passed: existing React UI -> nginx /api -> PostgreSQL backend.');
} finally { await browser.close(); }
