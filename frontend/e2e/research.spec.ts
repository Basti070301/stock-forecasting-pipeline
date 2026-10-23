import { test, expect } from '@playwright/test';

test('frozen local artifact: real research job, replay display, immutable repeat and stale rejection', async ({ page, request }) => {
  const catalog = await (await request.get('/api/research/models')).json();
  test.skip(!catalog.can_generate || !catalog.items.length, 'Explicit trusted local artifact root required; no model training inside browser tests');
  const model = catalog.items.find((m: { name: string }) => m.name === 'logistic');
  expect(model).toBeTruthy();
  await page.goto('/#stock/AAPL');
  await expect(page.getByRole('heading', { name: 'Research-Prognosen', exact: true })).toBeVisible({ timeout: 15000 });
  await page.getByLabel('Research-Artefakt').selectOption(model.artifact_id);
  await page.getByLabel('Entscheidungszeitpunkt (ISO mit Zeitzone)').fill('2026-08-25T21:45:00Z');
  await page.getByRole('button', { name: 'Research-Prognose ausdrücklich erstellen' }).click();
  await expect(page.getByText('Abgeschlossen · Ergebnis gespeichert')).toBeVisible({ timeout: 15000 });
  await expect(page.getByText('Historischer Research Replay', { exact: true })).toBeVisible();
  await expect(page.getByText(/Kontrafaktischer Replay · Modell erst später/)).toBeVisible();
  await expect(page.getByText('46,60 %', { exact: true })).toBeVisible();
  const before = await (await request.get('/api/forecasts?ticker=AAPL')).json();
  expect(before.items).toHaveLength(1);
  expect(before.items[0].target_session).toBe('2026-08-26');
  expect(before.items[0].status).toBe('research_only');
  await page.getByRole('button', { name: 'Research-Prognose ausdrücklich erstellen' }).click();
  await expect.poll(async () => {
    const jobs = await (await request.get('/api/pipeline/status')).json();
    return jobs.jobs.filter((j: { kind: string; status: string }) => j.kind === 'research_forecast' && j.status === 'succeeded').length;
  }).toBeGreaterThanOrEqual(2);
  const after = await (await request.get('/api/forecasts?ticker=AAPL')).json();
  expect(after.items).toEqual(before.items);
  await page.getByLabel('Research-Modus').selectOption('current');
  await page.getByLabel('Entscheidungszeitpunkt (ISO mit Zeitzone)').fill(new Date().toISOString());
  await page.getByRole('button', { name: 'Research-Prognose ausdrücklich erstellen' }).click();
  await expect(page.getByRole('alert')).toContainText('Veraltete Kurse');
  await page.reload();
  await expect(page.getByText('Historischer Research Replay', { exact: true })).toBeVisible();
  await page.screenshot({ path: 'test-results/research-replay.png', fullPage: true });
  await page.getByRole('navigation').getByRole('link', { name: 'Model Analytics', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Eingefrorene Modelle · Holdout-Vergleich' })).toBeVisible();
  await expect(page.getByText(/Projektweit unangetasteter Holdout noch nicht nachgewiesen/)).toBeVisible();
  const evaluations = await (await request.get('/api/research/evaluations')).json();
  const diagnostic = evaluations.items.find((r: { evaluation_scope: string }) => r.evaluation_scope === 'retrospective_diagnostic');
  if (diagnostic) {
    const comparison = page.locator('section.panel').filter({ has: page.getByRole('heading', { name: 'Eingefrorene Modelle · Holdout-Vergleich' }) });
    await expect(comparison.getByText('retrospective_diagnostic', { exact: true })).toBeVisible();
    await expect(comparison.getByRole('columnheader', { name: 'random_forest', exact: true })).toBeVisible();
    const accuracy = diagnostic.results[0].metrics.accuracy.toLocaleString('de-DE', { minimumFractionDigits: 4, maximumFractionDigits: 4 });
    await expect(comparison.getByRole('cell', { name: accuracy, exact: true }).first()).toBeVisible();
    await comparison.screenshot({ path: 'test-results/retrospective-diagnostic.png' });
  }
});
