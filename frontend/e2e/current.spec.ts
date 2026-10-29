import { test, expect } from '@playwright/test';

test('M4.2b: echte Aktivierung bleibt gesperrt, ausdrücklich markierte UI-Fixtures und Outcomes', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Current Research · Daten & Status' })).toBeVisible();
  await expect(page.getByText('Insufficient Evidence', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Current-Paar ausdrücklich erstellen' })).toHaveCount(0);

  const outcome = { actual: 0, prediction_correct: false, observed_at: '2026-10-27T21:00:00Z' };
  const forecast = { id: 'browser-fixture-current', ticker: 'AAPL', probability: .6, model_name: 'logistic', model_version: 'fixture-only', generated_at: '2026-10-26T21:00:00Z', decision_at: '2026-10-26T21:00:00Z', feature_as_of: '2026-10-26', target_session: '2026-10-27', mode: 'current', status: 'research_only', counterfactual_model_replay: false, source_kind: 'fixture', evaluation_scope: 'fixture', source: { name: 'Ausdrückliche Browser-Testfixture, kein Providerabruf', observed_at: '2026-10-26T20:59:59Z' }, data_version: 'browser-fixture-only', current_confirmation: { status: 'fixture', saved_at: '2026-10-26T21:00:01Z' }, outcome };
  await page.route('**/api/research/current/status**', route => route.fulfill({ json: {
    enabled: false, auto_refresh: false, blocked: { code: 'provider_blocked', message: 'Testfixture: kein echter Providerzugang' },
    items: [{ ticker: 'AAPL', provider: 'yfinance', source_kind: 'fixture', last_received_at: '2026-10-26T20:59:59Z', last_confirmed_at: '2026-10-26T21:00:00Z', quality: { status: 'accepted' }, stale: true, error: null, latest_forecast_at: forecast.generated_at, forecast_scope: 'fixture', outcome, prospective_pairs: 0, matured_pairs: 0 }],
    prospective: { status: 'Insufficient Evidence', T0: null, prospective_pairs: 0, matured_pairs: 0, models: [], warning: 'Browser-Testfixture, keine unabhängige Modellvalidierung' }, note: 'Explizite Browser-Fixtures, keine Live-Daten', scheduler: { running: false, cycles: 0, blocked_code: null },
  } }));
  await page.route('**/api/forecasts?*kind=research_forecast*', route => route.fulfill({ json: { items: [forecast] } }));
  await page.goto('/#stock/AAPL');
  // Archived stock/calendar calculations can take longer on their first load.
  await expect(page.getByRole('heading', { name: 'Apple', exact: true })).toBeVisible({ timeout: 20000 });
  await expect(page.getByText('Testdaten / Fixture', { exact: true })).toBeVisible({ timeout: 15000 });
  await expect(page.getByText('Fixture · keine Live-Prognose', { exact: true })).toBeVisible();
  await expect(page.getByText(/Prospektive Prognosepaare: 0/)).toBeVisible();
  await expect(page.getByText(/Beobachtetes Ergebnis: Klasse 0/)).toBeVisible();
  await expect(page.getByText(/Beobachtetes Ergebnis: Schlusskurs nicht gestiegen/)).toBeVisible();
  await expect(page.getByText('Current Research Forecast · bestätigt', { exact: true })).toHaveCount(0);
  await page.screenshot({ path: 'test-results/current-fixture-status.png', fullPage: true });
});
