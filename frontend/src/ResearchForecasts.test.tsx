import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ForecastCard, HoldoutComparison, ResearchForecastPanel, type Evaluation, type ResearchForecast } from './ResearchForecasts';

afterEach(() => { cleanup(); vi.restoreAllMocks(); });
const forecast: ResearchForecast = {
  id: 'fixture-only', ticker: 'AAPL', probability: .46, model_name: 'logistic', model_version: 'fixture-model',
  generated_at: '2026-10-23T12:00:00Z', decision_at: '2026-08-25T21:45:00Z', feature_as_of: '2026-08-25',
  target_session: '2026-08-26', mode: 'historical_replay', counterfactual_model_replay: true, status: 'research_only',
  source: { name: 'Offline display fixture', observed_at: '2026-08-25T21:30:28Z' }, data_version: 'fixture-data',
};
const response = (value: unknown) => ({ ok: true, json: async () => value }) as Response;
function mount(component: React.ReactNode) {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}>{component}</QueryClientProvider>);
}

describe('Research forecasts: immutable replay, permission and evaluation disclosure', () => {
  it('shows original class probability, provenance and counterfactual replay', () => {
    render(<ForecastCard forecast={forecast} />);
    expect(screen.getByText('46,00 %')).toBeVisible();
    expect(screen.getByText('Historischer Research Replay')).toBeVisible();
    expect(screen.getByText(/Kontrafaktischer Replay/)).toBeVisible();
    expect(screen.getByText('Close(t+1) > Close(t)')).toBeVisible();
    expect(screen.getByText(/fixture-model/)).toBeInTheDocument();
    expect(screen.getByText(/Offline display fixture/)).toBeVisible();
  });
  it('shows an honest empty state with server-side writes disabled', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async input => response(String(input).includes('/research/models') ? { items: [], can_generate: false, note: 'Read profile' } : { items: [] }));
    mount(<ResearchForecastPanel ticker="AAPL" />);
    expect(await screen.findByText(/Für AAPL ist noch keine Research-Prognose gespeichert/)).toBeVisible();
    expect(screen.getByText(/Prognoseerstellung gesperrt/)).toBeVisible();
    expect(screen.queryByRole('button', { name: 'Research-Prognose ausdrücklich erstellen' })).not.toBeInTheDocument();
  });
  it('requires explicit artifact and zoned timestamp then sends the protected job request', async () => {
    const calls: { path: string; body: unknown }[] = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, options) => {
      const path = String(input);
      if (options?.method === 'POST') { calls.push({ path, body: JSON.parse(String(options.body)) }); return response({ job_id: 'fixture-job' }); }
      if (path.includes('/jobs/')) return response({ status: 'failed', error: 'Test: veraltete Kurse', result: null });
      if (path.includes('/research/models')) return response({ items: [{ artifact_id: 'fixture-artifact', model_version: 'fixture-version', name: 'logistic', tickers: ['AAPL'] }], can_generate: true, note: 'Fixture' });
      return response({ items: [] });
    });
    mount(<ResearchForecastPanel ticker="AAPL" />);
    const button = await screen.findByRole('button', { name: 'Research-Prognose ausdrücklich erstellen' });
    expect(button).toBeDisabled();
    fireEvent.change(screen.getByLabelText('Research-Artefakt'), { target: { value: 'fixture-artifact' } });
    fireEvent.change(screen.getByLabelText('Entscheidungszeitpunkt (ISO mit Zeitzone)'), { target: { value: '2026-08-25' } });
    expect(button).toBeDisabled();
    fireEvent.change(screen.getByLabelText('Entscheidungszeitpunkt (ISO mit Zeitzone)'), { target: { value: '2026-08-25T21:45:00Z' } });
    fireEvent.click(button);
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]).toEqual({ path: '/api/forecasts/research', body: { artifact_id: 'fixture-artifact', model_version: 'fixture-version', ticker: 'AAPL', mode: 'historical_replay', decision_at: '2026-08-25T21:45:00Z' } });
    expect(await screen.findByRole('alert')).toHaveTextContent('Test: veraltete Kurse');
  });
  it('propagates backend read errors without inventing a forecast', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({ ok: false, json: async () => ({ detail: 'Research-Datenbank nicht verfügbar' }) } as Response);
    mount(<ResearchForecastPanel ticker="AAPL" />);
    expect((await screen.findAllByRole('alert'))[0]).toHaveTextContent('Research-Datenbank nicht verfügbar');
    expect(screen.queryByText('46,00 %')).not.toBeInTheDocument();
  });
  it('does not imply that a missing evaluation passed', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(response({ items: [], note: 'Unabhängige Abnahme offen' }));
    mount(<HoldoutComparison />);
    expect(await screen.findByText(/Noch keine bestätigte Holdout-Auswertung gespeichert/)).toBeVisible();
    expect(screen.getByText('Unabhängige Abnahme offen')).toBeVisible();
  });
  it('compares models and training baselines with explicit reused-period warning (fixture)', async () => {
    const result = { name: 'logistic', model_version: 'fixture', metrics: { accuracy: .52, confusion_matrix: [[4, 1], [3, 2]] }, holdout_period: { start: '2026-04-01', end: '2026-08-24', last_label_session: '2026-08-25', rows: 10 }, training_majority_baseline: { accuracy: .6, brier_score: .4 }, training_prevalence_baseline: { brier_score: .25 }, calibration_summary: { ece: .1, bins: [] }, uncertainty: { warning: 'Fixture uncertainty only', low_sample: true, intervals_95: { accuracy: [.4, .6] } } };
    const report: Evaluation = { id: 'fixture-eval', evaluated_at: forecast.generated_at, evaluation_scope: 'retrospective_diagnostic', independent_acceptance: 'blocked', warning: 'Testfixture: bereits betrachteter Zeitraum', definition: { train_end: '2025-12-31', calibration_end: '2026-03-31', holdout_end: '2026-08-25' }, results: [result, { ...result, name: 'random_forest' }] };
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(response({ items: [report], note: 'Fixture' }));
    mount(<HoldoutComparison />);
    expect(await screen.findByText(/Testfixture: bereits betrachteter Zeitraum/)).toBeVisible();
    expect(screen.getByText('retrospective_diagnostic')).toBeVisible();
    expect(screen.getByRole('columnheader', { name: 'random_forest' })).toBeVisible();
    expect(screen.getAllByText(/Trainings-Mehrheitsbaseline/)).toHaveLength(2);
    expect(screen.getAllByText(/Kleine Stichprobe/)).toHaveLength(2);
  });
});
