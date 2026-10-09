import { test, expect } from '@playwright/test';

test('M3: ausdrücklich markierte Browser-Fixtures, Feedfilter und Aktien-Sentiment', async ({ page }) => {
  const fixture = { id: 'm3-browser-fixture', title: 'SYNTHETIC BROWSER FIXTURE: Microsoft financial results', source: 'Fixture Journal', provider: 'finnhub', url: 'https://example.com/m3-fixture', description: '', published_at: '2026-09-10T10:00:00Z', first_seen_at: '2026-09-10T12:00:00Z', tickers: ['MSFT'], language: 'en', analysis_status: 'Analysiert', data_state: 'fixture', stale: false, input_scope: 'title_only', analysis: { positive: .7, negative: .1, neutral: .2, sentiment: .6, dominant: 'positive', model: 'ProsusAI/finbert', model_revision: 'fixture-only', analyzed_at: '2026-09-10T12:01:00Z' } };
  const urls: string[] = [];
  await page.route('**/api/news/feed?*', async route => {
    urls.push(route.request().url());
    await route.fulfill({ json: { items: [fixture], total: 1, page: 1, page_size: 20, sources: ['Fixture Journal'], as_of: '2026-09-10T12:02:00Z', data_state: 'fixture' } });
  });
  await page.route('**/api/news/providers', route => route.fulfill({ json: { providers: [{ id: 'finnhub', provider: 'finnhub', configured: false, message: 'Kein Live-Zugang: Browser-Fixture', covered_tickers: ['MSFT'], last_success: null, last_error: null, stale: true }], schema_ready: true, news_enabled: false, market_mode: 'demo', auto_refresh: false, interval_seconds: 900, max_cycles: 24 } }));
  await page.route('**/api/stocks/MSFT/sentiment', route => route.fulfill({ json: { windows: [{ ticker: 'MSFT', days: 7, as_of: '2026-09-10T12:02:00Z', analyzed_count: 1, mean_sentiment: .6, positive: 1, negative: 0, neutral: 0, low_sample: true, duplicate_count: 0, last_news_at: fixture.published_at, warning: 'Fixture-Auswertung; keine echten Live-Daten', trend: [], basis_hash: 'fixture-basis' }] } }));
  await page.goto('/#news');
  await expect(page.getByRole('heading', { name: 'Nachrichtenfeed', exact: true })).toBeVisible();
  await expect(page.getByText('Kein Live-Zugang: Browser-Fixture')).toBeVisible();
  await page.getByLabel('News-Ticker').selectOption('MSFT');
  await page.getByLabel('News-Quelle').selectOption('Fixture Journal');
  await page.getByLabel('News-Sentiment').selectOption('positive');
  await page.getByLabel('News-Zeitraum').selectOption('7');
  await expect.poll(() => urls.some(url => { const params = new URL(url).searchParams; return params.get('ticker') === 'MSFT' && params.get('source') === 'Fixture Journal' && params.get('sentiment') === 'positive' && params.get('days') === '7'; })).toBeTruthy();
  await expect(page.getByText('Testdaten / Fixture').first()).toBeVisible();
  await expect(page.getByText('1 ausgewertet')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Nachrichten abrufen', exact: true })).toBeDisabled();
  await expect(page.getByRole('link', { name: /SYNTHETIC BROWSER FIXTURE/ }).first()).toHaveAttribute('href', fixture.url);
  await page.screenshot({ path: 'test-results/m3-news-browser-fixtures.png', fullPage: true });
});
