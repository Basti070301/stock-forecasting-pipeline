import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AggregateView, NewsCard, NewsWorkspace, ProviderPanel, StockNewsPanel } from './NewsIntelligence';
import type { Config, NewsAggregate, NewsArticle, NewsProviderStatus } from './api';

afterEach(() => { cleanup(); vi.restoreAllMocks(); });
const fixture: NewsArticle = { id: 'fixture', title: 'Synthetic test headline: Microsoft reports quarterly earnings', description: '', source: 'Fixture Journal', provider: 'finnhub', url: 'https://example.com/fixture', published_at: '2026-09-10T10:00:00Z', first_seen_at: '2026-09-10T12:00:00Z', tickers: ['MSFT'], language: 'en', analysis_status: 'Analysiert', stale: false, data_state: 'fixture', input_scope: 'title_only', analysis: { positive: .7, negative: .1, neutral: .2, sentiment: .6, dominant: 'positive', model: 'ProsusAI/finbert', model_revision: 'fixture-revision', analyzed_at: '2026-09-10T12:01:00Z' } };
const aggregate: NewsAggregate = { ticker: 'MSFT', days: 7, as_of: '2026-09-10T12:02:00Z', relevant_count: 1, analyzed_count: 1, positive: 1, negative: 0, neutral: 0, mean_sentiment: .6, last_news_at: fixture.published_at, low_sample: true, warning: 'Tonalität, keine Kursprognose; kleine Stichprobe', duplicate_count: 0, trend: [{ date: '2026-09-10', count: 1, mean_sentiment: .6 }], basis_hash: 'fixture-basis' };
const status: NewsProviderStatus = { providers: [{ id: 'finnhub', provider: 'finnhub', configured: false, message: 'Finnhub API-Schlüssel fehlt', covered_tickers: ['AAPL', 'MSFT', 'NVDA'], last_attempt: null, last_success: null, last_error: null, next_allowed_at: null, stale: true }], schema_ready: true, news_enabled: false, market_mode: 'demo', auto_refresh: false, interval_seconds: 900, max_cycles: 24 };
function mount(component: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}>{component}</QueryClientProvider>);
}
const response = (value: unknown) => ({ ok: true, json: async () => value }) as Response;

describe('News Intelligence: ehrliche Daten und bestehendes Design', () => {
  it('zeigt Herkunft, Klasse, Wahrscheinlichkeiten und Originalquelle', () => {
    render(<NewsCard article={fixture} />);
    expect(screen.getByText('Testdaten / Fixture')).toBeVisible();
    expect(screen.getByText(/Positiv · FinBERT 0,600/)).toBeVisible();
    expect(screen.getByRole('link')).toHaveAttribute('href', fixture.url);
    expect(screen.getByText(/Positiv 70,00/)).toBeInTheDocument();
    expect(screen.getByText(/Nur Titel analysiert/)).toBeInTheDocument();
  });
  it('kennzeichnet historische Daten und unsupported Sprache ohne Scores', () => {
    render(<NewsCard article={{ ...fixture, language: 'de', data_state: 'historical_provider', stale: true, analysis: null, analysis_status: 'Sprache nicht unterstützt oder unklar' }} />);
    expect(screen.getByText(/Historische Provider-Daten · veraltet/)).toBeVisible();
    expect(screen.getByText('Sprache nicht unterstützt oder unklar')).toBeVisible();
    expect(screen.queryByText(/FinBERT 0,600/)).not.toBeInTheDocument();
  });
  it('trennt Demo-Kurse, fehlende Zugänge und tatsächliche Abrufzustände', () => {
    render(<ProviderPanel status={status} />);
    expect(screen.getByText(/Kurse: Demo/)).toBeVisible();
    expect(screen.getByText('Finnhub API-Schlüssel fehlt')).toBeVisible();
    expect(screen.getByText(/Noch kein erfolgreicher Live-Abruf/)).toBeVisible();
  });
  it('zeigt Aggregation mit Stichprobenwarnung und Berechnungsgrundlage', () => {
    render(<AggregateView value={aggregate} />);
    expect(screen.getByText('1 ausgewertet')).toBeVisible();
    expect(screen.getByText(/kleine Stichprobe/)).toBeVisible();
    expect(screen.getByText(/fixture-basis/)).toBeInTheDocument();
  });
  it('lädt die Aktien-Sentimentfenster und letzten Meldungen', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async input => response(String(input).includes('/sentiment') ? { windows: [aggregate] } : { items: [fixture] }));
    mount(<StockNewsPanel ticker="MSFT" />);
    await waitFor(() => expect(screen.getByRole('link', { name: /Synthetic test headline/ })).toBeVisible());
    expect(screen.getByText('1 ausgewertet')).toBeVisible();
  });
  it('reicht Quelle, Zeitraum und Sentimentfilter an die paginierte API weiter', async () => {
    const calls: string[] = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation(async input => {
      const url = String(input); calls.push(url);
      if (url.includes('/providers')) return response(status);
      if (url.includes('/sentiment')) return response({ windows: [] });
      return response({ items: [fixture], total: 1, page: 1, page_size: 20, as_of: '2026-09-10T12:02:00Z', sources: ['Fixture Journal'], data_state: 'fixture' });
    });
    mount(<NewsWorkspace config={{ mode: 'demo', watchlist: [], providers: [], token_required: false, intraday: '' } as Config} />);
    await waitFor(() => expect(screen.getByLabelText('News-Quelle')).toBeVisible());
    await waitFor(() => expect(screen.getByRole('option', { name: 'Fixture Journal' })).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText('News-Quelle'), { target: { value: 'Fixture Journal' } });
    fireEvent.change(screen.getByLabelText('News-Sentiment'), { target: { value: 'negative' } });
    fireEvent.change(screen.getByLabelText('News-Zeitraum'), { target: { value: '7' } });
    await waitFor(() => expect(calls.some(url => url.includes('source=Fixture+Journal') && url.includes('sentiment=negative') && url.includes('days=7'))).toBe(true));
    expect(screen.getByRole('button', { name: 'Nachrichten abrufen' })).toBeDisabled();
  });
  it('zeigt leere Zustände und Netzwerkfehler ohne Fallback-Meldungen', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async input => {
      if (String(input).includes('/sentiment')) return response({ windows: [] });
      return { ok: false, json: async () => ({ detail: 'News-Datenbank nicht erreichbar' }) } as Response;
    });
    mount(<StockNewsPanel ticker="MSFT" />);
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('News-Datenbank nicht erreichbar'));
    expect(screen.queryByRole('link', { name: /Synthetic test headline/ })).not.toBeInTheDocument();
  });
});
