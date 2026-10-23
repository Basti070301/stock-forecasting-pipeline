import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api, dateText, number, percent, type Metrics } from './api';
import { Action, Badge, Empty, QueryState, Section } from './App';

export type ResearchForecast = {
  id: string; ticker: string; probability: number; model_name: string; model_version: string;
  generated_at: string; decision_at: string; feature_as_of: string; target_session: string;
  mode: string; counterfactual_model_replay: boolean; status: string;
  source: { name: string; observed_at: string }; data_version: string;
};
type Artifact = { artifact_id: string; model_version: string; name: string; tickers: string[] };
type Catalog = { items: Artifact[]; can_generate: boolean; note: string };
type Result = {
  name: string; model_version: string; metrics: Metrics; holdout_period: { start: string; end: string; last_label_session: string; rows: number };
  training_majority_baseline: Metrics; training_prevalence_baseline: Metrics;
  calibration_summary: { ece: number; bins: { predicted: number; observed: number; count: number }[] };
  uncertainty: { warning: string; low_sample: boolean; intervals_95: Record<string, number[]> };
};
export type Evaluation = { id: string; evaluated_at: string; evaluation_scope: string; warning: string; independent_acceptance: string; definition: { train_end: string; calibration_end: string; holdout_end: string }; results: Result[] };

export function ForecastCard({ forecast: f }: { forecast: ResearchForecast }) {
  return <article className="job">
    <div className="job-top"><strong>{f.ticker} · {f.model_name}</strong><Badge>research_only</Badge>
      <Badge color="amber-badge">{f.mode === 'historical_replay' ? 'Historischer Research Replay' : 'Current Research Forecast'}</Badge></div>
    {f.counterfactual_model_replay && <p className="warning-banner">Kontrafaktischer Replay · Modell erst später erstellt; keine damals erzeugte Prognose.</p>}
    <p>Zielklasse: <strong>Close(t+1) &gt; Close(t)</strong> · Kalibrierte Wahrscheinlichkeit: <strong>{percent(f.probability)}</strong></p>
    <p>Modellklassifikation (Schwelle 0,5): {f.probability >= .5 ? 'Klasse 1 · Schlusskurs steigt' : 'Klasse 0 · Schlusskurs steigt nicht'}</p>
    <p>Erstellt: {new Date(f.generated_at).toLocaleString('de-DE')} · Zielhandelstag: {dateText(f.target_session)}</p>
    <p>Datenstand: {dateText(f.feature_as_of)} · Entscheidung: {new Date(f.decision_at).toLocaleString('de-DE')}</p>
    <p>Quelle: {f.source.name} · Beobachtet: {new Date(f.source.observed_at).toLocaleString('de-DE')}</p>
    <details><summary>Version und Datenbasis</summary><p className="hash">Modellversion: {f.model_version}</p><p className="hash">Datenversion: {f.data_version}</p></details>
    <p className="section-note">Wahrscheinlichkeit der definierten Richtungsklasse. Keine Renditewahrscheinlichkeit, Modellfreigabe oder Handelsempfehlung.</p>
  </article>;
}

export function ResearchForecastPanel({ ticker }: { ticker: string }) {
  const forecasts = useQuery({ queryKey: ['research-forecasts', ticker], queryFn: () => api<{ items: ResearchForecast[] }>(`/forecasts?ticker=${encodeURIComponent(ticker)}&kind=research_forecast`) });
  const catalog = useQuery({ queryKey: ['research-models'], queryFn: () => api<Catalog>('/research/models') });
  const [identity, setIdentity] = useState('');
  const [mode, setMode] = useState('historical_replay');
  const [decision, setDecision] = useState('');
  const model = catalog.data?.items.find(a => a.artifact_id === identity && a.tickers.includes(ticker));
  const validTime = Number.isFinite(Date.parse(decision)) && /(?:Z|[+-]\d\d:\d\d)$/.test(decision);
  return <Section title="Research-Prognosen" subtitle="Explizite Modellwahl · nächste Handelssitzung · unveränderliche Ergebnisse">
    <QueryState pending={forecasts.isPending} error={forecasts.error}>
      {forecasts.data?.items.length ? forecasts.data.items.map(f => <ForecastCard key={f.id} forecast={f} />) : <Empty>Für {ticker} ist noch keine Research-Prognose gespeichert. Historische Kurse erzeugen keine aktuelle Prognose.</Empty>}
    </QueryState>
    <QueryState pending={catalog.isPending} error={catalog.error}>
      <p className="section-note">{catalog.data?.note}</p>
      {catalog.data?.can_generate ? <><div className="form-grid">
        <label>Research-Artefakt<select value={identity} onChange={e => setIdentity(e.target.value)}><option value="">Modell ausdrücklich auswählen</option>{catalog.data.items.filter(a => a.tickers.includes(ticker)).map(a => <option key={a.artifact_id} value={a.artifact_id}>{a.name} · {a.model_version.slice(0, 12)}</option>)}</select></label>
        <label>Research-Modus<select value={mode} onChange={e => setMode(e.target.value)}><option value="historical_replay">Historical Research Replay</option><option value="current">Current Research Forecast (Aktualitätsprüfung)</option></select></label>
        <label>Entscheidungszeitpunkt (ISO mit Zeitzone)<input placeholder="z. B. 2026-08-25T21:45:00Z" value={decision} onChange={e => setDecision(e.target.value)} /></label>
      </div><Action label="Research-Prognose ausdrücklich erstellen" path="/forecasts/research" disabled={!model || !validTime} body={{ artifact_id: model?.artifact_id, model_version: model?.model_version, ticker, mode, decision_at: decision }} /></> : <p className="section-note">Prognoseerstellung gesperrt. Mutationsberechtigung und Vertrauen in lokale Artefakte müssen serverseitig eingerichtet sein.</p>}
    </QueryState>
  </Section>;
}

export function HoldoutComparison() {
  const query = useQuery({ queryKey: ['research-evaluations'], queryFn: () => api<{ items: Evaluation[]; note: string }>('/research/evaluations') });
  const metricNames = ['accuracy', 'balanced_accuracy', 'precision', 'recall', 'f1', 'roc_auc', 'brier_score'];
  return <Section title="Eingefrorene Modelle · Holdout-Vergleich" subtitle="LR / RF und feste Trainingsbaselines · keine automatische Modellwahl">
    <QueryState pending={query.isPending} error={query.error}>
      <p className="section-note">{query.data?.note}</p>
      {!query.data?.items.length && <Empty>Noch keine bestätigte Holdout-Auswertung gespeichert. Fehlende Ergebnisse werden nicht ersetzt.</Empty>}
      {query.data?.items.map(report => <article key={report.id}>
        <div className="warning-banner">{report.warning} · Unabhängige Abnahme: {report.independent_acceptance}</div>
        <p>Training bis {report.definition.train_end} · Kalibrierung bis {report.definition.calibration_end} · Holdout bis {report.definition.holdout_end}</p>
        <div className="table-scroll"><table><thead><tr><th>Metrik</th>{report.results.map(r => <th key={r.name}>{r.name}</th>)}</tr></thead><tbody>{metricNames.map(key => <tr key={key}><td>{key}</td>{report.results.map(r => <td key={r.name}>{number(r.metrics[key] as number | null, 4)}</td>)}</tr>)}</tbody></table></div>
        {report.results.map(r => <div className="job" key={r.name}><h3>{r.name} · research_only</h3>
          <p>{r.holdout_period.rows} Beobachtungen · Features {r.holdout_period.start} bis {r.holdout_period.end} · letztes Label {r.holdout_period.last_label_session}</p>
          <p>Trainings-Mehrheitsbaseline: Accuracy {number(r.training_majority_baseline.accuracy as number, 4)} · Brier {number(r.training_majority_baseline.brier_score as number, 4)}</p>
          <p>Trainings-Prävalenzbaseline: Brier {number(r.training_prevalence_baseline.brier_score as number, 4)} · ECE {number(r.calibration_summary.ece, 4)}</p>
          <p>{r.uncertainty.low_sample ? 'Kleine Stichprobe. ' : ''}{r.uncertainty.warning}</p>
          <details><summary>Unsicherheit, Kalibrierung und Konfusionsmatrix</summary>
            {Object.entries(r.uncertainty.intervals_95).map(([key, interval]) => <p key={key}>{key} · deskriptives 95%-Intervall: {interval.map(n => number(n, 4)).join(' bis ')}</p>)}
            <p>Konfusionsmatrix (Ist / Prognose 0, 1): {JSON.stringify(r.metrics.confusion_matrix)}</p>
            {r.calibration_summary.bins.map((b, i) => <p key={i}>P {percent(b.predicted)} · beobachtet {percent(b.observed)} · n={b.count}</p>)}
            <p className="hash">Modellversion: {r.model_version}</p>
          </details></div>)}
      </article>)}
    </QueryState>
  </Section>;
}
