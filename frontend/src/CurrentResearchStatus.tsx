import { useQuery } from '@tanstack/react-query';
import { api, number } from './api';
import { Action, Badge, QueryState, Section } from './App';

export type CurrentStatus = {
  enabled: boolean; auto_refresh: boolean;
  blocked: { code: string; message: string } | null;
  items: { ticker: string; provider: string | null; source_kind: string; last_received_at: string | null; last_confirmed_at: string | null; stale: boolean | null; quality: { status: string } | null; error: { message: string } | null; latest_forecast_at: string | null; forecast_scope: string | null; prospective_pairs: number; matured_pairs: number; outcome: { actual: number; prediction_correct?: boolean } | null }[];
  prospective: { status: string; T0: string | null; prospective_pairs: number; matured_pairs: number; known_outcome_revisions?: number; models: { model_id: string; n: number; metrics: { accuracy: number; balanced_accuracy: number; roc_auc: number | null; brier_score: number } | null }[]; warning: string };
  scheduler?: { running: boolean; cycles: number; blocked_code: string | null }; note: string;
  last_cycle?: { status: string; results: { ticker: string; status: string; message?: string; code?: string }[] } | null;
};
const timestamp = (value: string | null) => value ? new Date(value).toLocaleString('de-DE') : 'Nicht vorhanden';

export function CurrentResearchStatus({ ticker }: { ticker?: string }) {
  const query = useQuery({ queryKey: ['current-research-status', ticker || 'all'], queryFn: () => api<CurrentStatus>(`/research/current/status${ticker ? `?ticker=${encodeURIComponent(ticker)}` : ''}`), refetchInterval: 30000 });
  const data = query.data;
  return <Section title="Current Research · Daten & Status" subtitle="Separate versionierte Kursbasis · keine Modellfreigabe">
    <QueryState pending={query.isPending} error={query.error}>
      {data?.blocked && <p className="warning-banner">{data.blocked.message} · {data.blocked.code}</p>}
      {data?.last_cycle && data.last_cycle.status !== 'completed' && <p role="alert">Letzter Current-Lauf: {data.last_cycle.status} · {data.last_cycle.results.filter(r => r.status === 'blocked').map(r => `${r.ticker}: ${r.message || r.code || r.status}`).join(' · ')}</p>}
      <p className="section-note">{data?.note} Scheduler: {data?.scheduler?.running ? 'Läuft begrenzt' : 'Inaktiv'}.</p>
      {data?.items.map(row => <article className="job" key={row.ticker}>
        <div className="job-top"><strong>{row.ticker}</strong><Badge>{row.source_kind === 'fixture' ? 'Testdaten / Fixture' : row.source_kind === 'provider' ? 'Gespeicherte Providerdaten' : 'Keine aktuellen Kursdaten'}</Badge></div>
        <p>Quelle: {row.provider || 'Nicht verfügbar'} · Datenqualität: {row.quality?.status || 'Ungeprüft'} · {row.stale === true ? 'Veraltet' : row.stale === false ? 'Letzte abgeschlossene Sitzung vorhanden' : 'Aktualität nicht bestätigt'}</p>
        <p>Tatsächlich empfangen: {timestamp(row.last_received_at)} · Speicherung bestätigt: {timestamp(row.last_confirmed_at)}</p>
        <p>Letzter Research Forecast: {timestamp(row.latest_forecast_at)} · Status: {row.forecast_scope || 'Keine Prognose'}</p>
        <p>Prospektive Prognosepaare: {row.prospective_pairs} · Gereifte Paare: {row.matured_pairs}</p>
        {row.outcome ? <p>Beobachtetes Ergebnis: {row.outcome.actual === 1 ? 'Schlusskurs gestiegen' : 'Schlusskurs nicht gestiegen'}{row.outcome.prediction_correct != null && ` · Prognose ${row.outcome.prediction_correct ? 'korrekt' : 'nicht korrekt'}`}</p> : <p>Noch kein verfügbares Ergebnis.</p>}
        {row.error && <p role="alert">{row.error.message}</p>}
      </article>)}
      {data?.prospective && <><Badge>{data.prospective.status}</Badge><p>Prospektiver Start T0: {timestamp(data.prospective.T0)} · Gereifte Paare: {data.prospective.matured_pairs}</p>
        {!!data.prospective.known_outcome_revisions && <p className="warning-banner">Bekannte Outcome-Korrekturen: {data.prospective.known_outcome_revisions}. Die deskriptiven Metriken verwenden erste akzeptierte Labels; Korrekturen benötigen eine ausdrückliche Prüfung vor der Hauptauswertung.</p>}
        {data.prospective.models.map(model => <p key={model.model_id}>{model.model_id.includes('logistic') ? 'Logistic Regression' : 'Random Forest'} · n={model.n} · Accuracy {number(model.metrics?.accuracy, 4)} · Balanced Accuracy {number(model.metrics?.balanced_accuracy, 4)} · ROC-AUC {number(model.metrics?.roc_auc, 4)} · Brier {number(model.metrics?.brier_score, 4)}</p>)}
        <p className="section-note">{data.prospective.warning}</p></>}
      {ticker && data?.enabled && !data.blocked && <Action label="Current-Paar ausdrücklich erstellen" path="/forecasts/current" body={{ tickers: [ticker], refresh: false }} />}
    </QueryState>
  </Section>;
}
