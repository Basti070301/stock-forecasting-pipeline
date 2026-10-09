export type Stock = {
  ticker: string; company: string; exchange: string; country: string; region: string;
  currency: string; sector: string; timezone: string; calendar: string; yahoo_symbol: string;
  news_symbol: string | null; price: number | null; change: number | null;
  as_of: string | null; volume: number | null; relative_volume: number | null;
  session_close_utc: string | null; session_complete: boolean | null;
  features: Record<string, number | null>; source: string; age_days?: number; stale?: boolean;
  news_sentiment?: number | null; news_count?: number; radar_score?: number | null;
  momentum?: number | null; components?: Record<string, number | null>;
  quality: { rows: number; missing_feature_values?: number; missing_volume_rows?: number };
  forecast_status: string; intraday_status: string; forecast_probability: number | null;
};
export type Bar = { trade_date: string; close_price: number; open_price: number; high_price: number; low_price: number; volume: number };
export type Article = { id: string; title: string; description: string; source: string; url: string; published_at: string; first_seen_at: string; tickers: string[]; language: string; analysis_status: string; analysis: { positive: number; negative: number; neutral: number; sentiment: number } | null };
export type Metrics = Record<string, number | number[][] | string | null>;
export type Model = { id: string; name: string; metrics: Metrics; calibrated: boolean; forecast_enabled: boolean; warning: string; created_at?: string; folds?: { train_start: string; train_end: string; test_start: string; test_end: string }[]; calibration?: { predicted: number; observed: number; count: number }[]; feature_importance?: { feature: string; value: number }[] };
export type Backtest = { id: string; created_at: string; request: { model: string; start: string; end: string }; metrics: Metrics; naive_metrics: Metrics; equity: { date: string; value: number }[]; test_rows: number; folds: unknown[]; round_trip_cost_bps: number; data_hash: string; limitations: string[] };
export type Job = { steps?: { name: string; status: string; rows?: number }[]; id: string; kind: string; status: string; started_at: string | null; finished_at: string | null; error: string | null; result: { rows?: number; test_rows?: number; backtest_id?: string; steps?: { name: string; status: string }[] } | null };
export type Config = { mode: string; watchlist: Stock[]; providers: { name: string; status: string }[]; token_required: boolean; intraday: string };
export let mutationToken = '';
export function setToken(value: string) { mutationToken = value; }
export async function api<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api${path}`, body === undefined ? undefined : {
    method: 'POST', headers: { 'Content-Type': 'application/json', ...(mutationToken ? { 'X-SI-Token': mutationToken } : {}) }, body: JSON.stringify(body),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(typeof error.detail === 'string' ? error.detail : `Anfrage fehlgeschlagen (${response.status})`);
  }
  return response.json();
}
export const number = (value: number | null | undefined, digits = 2) => value == null ? '—' : value.toLocaleString('de-DE', { maximumFractionDigits: digits, minimumFractionDigits: digits });
export const percent = (value: number | null | undefined) => value == null ? '—' : `${number(value * 100)} %`;
export const dateText = (value?: string | null) => value ? new Date(value).toLocaleDateString('de-DE') : 'Noch kein Lauf';
