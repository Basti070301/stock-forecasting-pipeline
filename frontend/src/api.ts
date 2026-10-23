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
export type NewsArticle = Article & { provider: string; stale: boolean; data_state: string; last_updated_at?: string; input_scope?: string; mapping_evidence?: { ticker: string; method: string; matched: string }[]; analysis: (NonNullable<Article['analysis']> & { dominant: string; model: string; model_revision: string; analyzed_at: string }) | null };
export type NewsFeed = { items: NewsArticle[]; total: number; page: number; page_size: number; as_of: string; sources: string[]; data_state: string };
export type NewsAggregate = { ticker: string; days: number; as_of: string; relevant_count: number; analyzed_count: number; positive: number; negative: number; neutral: number; mean_sentiment: number | null; last_news_at: string | null; low_sample: boolean; warning: string; duplicate_count: number; trend: { date: string; count: number; mean_sentiment: number }[]; basis_hash: string };
export type NewsProviderStatus = { providers: { id: string; provider: string; configured: boolean; message: string; covered_tickers: string[]; last_attempt: string | null; last_success: string | null; last_error: { code: string; message: string; at: string } | null; next_allowed_at: string | null; stale: boolean }[]; schema_ready: boolean; news_enabled: boolean; market_mode: string; auto_refresh: boolean; interval_seconds: number; max_cycles: number; scheduler?: { running: boolean; cycles: number } };
export type Metrics = Record<string, number | number[][] | string | null>;
export type Model = { id: string; name: string; metrics: Metrics; calibration_period?: { start: string; end: string }; calibrated: boolean; forecast_enabled: boolean; warning: string; created_at?: string; folds?: { train_start: string; train_end: string; test_start: string; test_end: string }[]; calibration?: { predicted: number; observed: number; count: number }[]; feature_importance?: { feature: string; value: number }[] };
export type Backtest = { id: string; created_at: string; request: { model: string; start: string; end: string }; metrics: Metrics; naive_metrics: Metrics; equity: { date: string; value: number }[]; test_rows: number; folds: unknown[]; round_trip_cost_bps: number; data_hash: string; limitations: string[] };
export type Job = { steps?: { name: string; status: string; rows?: number }[]; id: string; kind: string; status: string; started_at: string | null; finished_at: string | null; error: string | null; result: { rows?: number; test_rows?: number; backtest_id?: string; partial?: boolean; steps?: { name: string; status: string }[] } | null };
export type Config = { mode: string; watchlist: Stock[]; providers: { name: string; status: string }[]; token_required: boolean; intraday: string; allow_mutations?: boolean };
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
