import { test, expect } from '@playwright/test';

test('historische Plattform: Filter, Detail, Seiten, Backtest und responsive Ansicht', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto('/');
  await expect(page.getByText('DEMO / HISTORIE')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Der Markt. Mit Kontext.' })).toBeVisible();
  await expect(page.getByRole('link', { name: /Apple AAPL/ })).toBeVisible();
  await page.getByRole('button', { name: 'Europa', exact: true }).click();
  await expect(page.getByRole('link', { name: /SAP SAP.DE/ })).toBeVisible();
  await expect(page.getByRole('link', { name: /Apple AAPL/ })).toHaveCount(0);
  await page.getByRole('link', { name: /SAP SAP.DE/ }).click();
  await expect(page.getByRole('heading', { name: 'Technische Features' })).toBeVisible();
  await page.getByRole('button', { name: '1M', exact: true }).click();
  await expect(page.locator('.price-chart svg').first()).toBeVisible();
  for (const [nav, heading] of [['News Intelligence', 'Nachrichtenfeed'], ['Model Analytics', 'Logistische Regression · PoC'], ['Paper Trading', 'Prognosejournal'], ['Pipeline Status', 'Laufhistorie'], ['Einstellungen', 'Watchlist']]) {
    await page.getByRole('navigation').getByRole('link', { name: nav, exact: true }).click();
    await expect(page.getByRole('heading', { name: heading, exact: true })).toBeVisible();
  }
  await page.getByRole('navigation').getByRole('link', { name: 'Backtesting', exact: true }).click();
  await page.getByRole('button', { name: 'Backtest ausführen' }).click();
  await expect(page.getByText('Abgeschlossen · Ergebnis gespeichert')).toBeVisible({ timeout: 85000 });
  await expect(page.getByRole('heading', { name: 'Logistische Regression · Walk-Forward' }).first()).toBeVisible();
  await page.getByRole('navigation').getByRole('link', { name: 'Übersicht', exact: true }).click();
  await page.setViewportSize({ width: 1440, height: 1100 });
  await page.screenshot({ path: 'test-results/dashboard-desktop.png', fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole('heading', { name: 'Der Markt. Mit Kontext.' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.screenshot({ path: 'test-results/dashboard-mobile.png', fullPage: true });
  expect(errors).toEqual([]);
});

test('Fehlerzustand ohne erfundene Fallbackdaten', async ({ page }) => {
  await page.route('**/api/radar?*', route => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Test: Datenbank nicht verfügbar' }) }));
  await page.goto('/');
  await expect(page.getByRole('alert')).toContainText('Datenbank nicht verfügbar');
  await expect(page.getByRole('link', { name: /Apple AAPL/ })).toHaveCount(0);
});
