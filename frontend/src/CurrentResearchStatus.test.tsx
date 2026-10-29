import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { CurrentResearchStatus, type CurrentStatus } from './CurrentResearchStatus';
import { ForecastCard, type ResearchForecast } from './ResearchForecasts';

afterEach(() => { cleanup(); vi.restoreAllMocks(); });
const response = (value: unknown) => ({ ok: true, json: async () => value }) as Response;
const empty: CurrentStatus = {
  enabled: false, auto_refresh: false, blocked: { code: 'provider_blocked', message: 'Erlaubter Providerzugang fehlt' },
  items: [{ ticker: 'AAPL', provider: null, source_kind: 'unavailable', last_received_at: null, last_confirmed_at: null, stale: null, quality: null, error: null, latest_forecast_at: null, forecast_scope: null, prospective_pairs: 0, matured_pairs: 0, outcome: null }],
  prospective: { status: 'Insufficient Evidence', T0: null, prospective_pairs: 0, matured_pairs: 0, models: [], warning: 'Keine unabhängige Leistungsbestätigung' },
  scheduler: { running: false, cycles: 0, blocked_code: null }, note: 'Kursstatus unabhängig vom historischen Preisdiagramm',
};
function mount() {
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><CurrentResearchStatus ticker="AAPL" /></QueryClientProvider>);
}

describe('Current research status: explicit provenance and evidence boundaries', () => {
  it('shows blocked empty status and no active forecast action', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(response(empty));
    mount();
    expect(await screen.findByText('Insufficient Evidence')).toBeVisible();
    expect(screen.getByText(/Erlaubter Providerzugang fehlt/)).toBeVisible();
    expect(screen.getByText('Keine aktuellen Kursdaten')).toBeVisible();
    expect(screen.getByText(/Noch kein verfügbares Ergebnis/)).toBeVisible();
    expect(screen.queryByRole('button', { name: 'Current-Paar ausdrücklich erstellen' })).not.toBeInTheDocument();
  });
  it('labels fixtures, stale data and recorded outcomes without counting them as prospective', async () => {
    const data: CurrentStatus = { ...empty, items: [{ ...empty.items[0], provider: 'yfinance', source_kind: 'fixture', stale: true, quality: { status: 'accepted' }, last_received_at: '2026-10-26T21:00:00Z', last_confirmed_at: '2026-10-26T21:00:01Z', latest_forecast_at: '2026-10-26T21:01:00Z', forecast_scope: 'fixture', outcome: { actual: 1, prediction_correct: true } }] };
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(response(data));
    mount();
    expect(await screen.findByText('Testdaten / Fixture')).toBeVisible();
    expect(screen.getByText(/Veraltet/)).toBeVisible();
    expect(screen.getByText(/Prospektive Prognosepaare: 0/)).toBeVisible();
    expect(screen.getByText(/Beobachtetes Ergebnis: Schlusskurs gestiegen · Prognose korrekt/)).toBeVisible();
  });
  it('does not invent a status on an API failure', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({ ok: false, json: async () => ({ detail: 'Current-Datenbank nicht verfügbar' }) } as Response);
    mount();
    expect(await screen.findByRole('alert')).toHaveTextContent('Current-Datenbank nicht verfügbar');
    expect(screen.queryByText('Gespeicherte Providerdaten')).not.toBeInTheDocument();
  });
  it('shows the last blocked job and its concrete data failure', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(response({ ...empty, last_cycle: { status: 'blocked', results: [{ ticker: 'AAPL', status: 'blocked', code: 'missing_prices', message: 'Vollständige OHLCV-Kurse fehlen' }] } }));
    mount();
    expect(await screen.findByRole('alert')).toHaveTextContent('Vollständige OHLCV-Kurse fehlen');
  });
  it('discloses known label corrections instead of implying final evaluation', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(response({ ...empty, prospective: { ...empty.prospective, known_outcome_revisions: 2 } }));
    mount();
    expect(await screen.findByText(/Bekannte Outcome-Korrekturen: 2/)).toBeVisible();
    expect(screen.getByText('Insufficient Evidence')).toBeVisible();
  });
  it('submits only the selected ticker and never a browser decision time or model path', async () => {
    const calls: unknown[] = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, options) => {
      if (options?.method === 'POST') { calls.push(JSON.parse(String(options.body))); return response({ job_id: 'fixture-current' }); }
      if (String(input).includes('/jobs/')) return response({ status: 'succeeded', result: {}, error: null });
      return response({ ...empty, enabled: true, blocked: null });
    });
    mount();
    fireEvent.click(await screen.findByRole('button', { name: 'Current-Paar ausdrücklich erstellen' }));
    await waitFor(() => expect(calls).toEqual([{ tickers: ['AAPL'], refresh: false }]));
  });
  it('labels a fixture forecast and shows a separately observed outcome', () => {
    const forecast: ResearchForecast = { id: 'fixture', ticker: 'AAPL', probability: .5, model_name: 'logistic', model_version: 'fixture', generated_at: '2026-10-26T21:00:00Z', decision_at: '2026-10-26T21:00:00Z', feature_as_of: '2026-10-26', target_session: '2026-10-27', mode: 'current', counterfactual_model_replay: false, status: 'research_only', source: { name: 'Isolated fixture', observed_at: '2026-10-26T20:59:00Z' }, data_version: 'fixture', source_kind: 'fixture', evaluation_scope: 'fixture', current_confirmation: { status: 'fixture', saved_at: '2026-10-26T21:00:01Z' }, outcome: { actual: 0, observed_at: '2026-10-27T21:00:00Z', prediction_correct: false } };
    render(<ForecastCard forecast={forecast} />);
    expect(screen.getByText('Fixture · keine Live-Prognose')).toBeVisible();
    expect(screen.getByText(/Beobachtetes Ergebnis: Klasse 0/)).toBeVisible();
    expect(screen.queryByText('Current Research Forecast · bestätigt')).not.toBeInTheDocument();
  });
});
