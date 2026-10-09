import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ArrowUpRight, Newspaper } from 'lucide-react';
import { Action, Badge, Empty, QueryState, Section } from './App';
import { api, dateText, number, percent, type Config, type NewsAggregate, type NewsArticle, type NewsFeed, type NewsProviderStatus } from './api';

const labels: Record<string, string> = { positive: 'Positiv', negative: 'Negativ', neutral: 'Neutral' };
const color: Record<string, string> = { positive: 'green', negative: 'red', neutral: '' };
const provenance: Record<string, string> = { provider: 'Echte Provider-Daten', historical_provider: 'Historische Provider-Daten · veraltet', fixture: 'Testdaten / Fixture', demo: 'Demo-Daten' };

export function NewsCard({ article }: { article: NewsArticle }) {
  const n = article;
  return <article>
    <div className="news-meta"><Badge>{n.source}</Badge><Badge color={n.stale ? 'amber-badge' : 'green'}>{provenance[n.data_state] || 'Herkunft ungeprüft'}</Badge><span>{new Date(n.published_at).toLocaleString('de-DE')} · {n.language.toUpperCase()}</span><span>{n.tickers.join(', ')}</span></div>
    <a href={n.url} target="_blank" rel="noopener noreferrer"><h3>{n.title} <ArrowUpRight size={16} /></h3></a>
    {n.description && <p>{n.description}</p>}
    <div className="news-meta"><Badge color={color[n.analysis?.dominant || '']}>{n.analysis ? `${labels[n.analysis.dominant]} · FinBERT ${number(n.analysis.sentiment, 3)}` : n.analysis_status}</Badge><small>Erstmals beobachtet: {new Date(n.first_seen_at).toLocaleString('de-DE')}</small></div>
    <details><summary>Herkunft, Zuordnung und Modellwahrscheinlichkeiten</summary>
      <p>Provider: {n.provider} · Aktualisiert: {n.last_updated_at ? new Date(n.last_updated_at).toLocaleString('de-DE') : 'Unbekannt'}</p>
      {n.analysis ? <><p>Positiv {percent(n.analysis.positive)} · Neutral {percent(n.analysis.neutral)} · Negativ {percent(n.analysis.negative)}</p><p>{n.analysis.model} · Revision {n.analysis.model_revision} · {n.input_scope === 'title_only' ? 'Nur Titel analysiert' : 'Titel und freigegebene Kurzfassung'}</p><p>Analysezeit: {new Date(n.analysis.analyzed_at).toLocaleString('de-DE')}</p></> : <p>Keine Modellwerte vorhanden. Andere oder unklare Sprachen werden nicht analysiert.</p>}
      {n.mapping_evidence?.map((e, i) => <p key={i}>{e.ticker}: {e.method} · {e.matched}</p>)}
    </details>
  </article>;
}

export function ProviderPanel({ status }: { status: NewsProviderStatus }) {
  return <Section title="Provider & Datenaktualität" subtitle="Ein konfigurierter Zugang ist noch kein erfolgreicher Abruf.">
    {!status.schema_ready && <p className="negative" role="alert">News-Migration v3 erforderlich.</p>}
    {status.market_mode === 'demo' && <p className="section-note">Kurse: Demo / Historie. Nachrichten sind separat gekennzeichnet; keine Demo-News werden erzeugt.</p>}
    {!status.providers.length && <Empty>Kein zugelassener News-Provider konfiguriert.</Empty>}
    {status.providers.map(provider => <div className="provider" key={provider.id}><Newspaper size={18} /><div><strong>{provider.provider} · {provider.configured ? 'Konfiguriert' : 'Nicht verfügbar'}</strong><p>{provider.message}</p><p>Abdeckung: {provider.covered_tickers.join(', ') || 'Keine bestätigte Zuordnung'}</p><p>Letzter erfolgreicher Abruf: {provider.last_success ? new Date(provider.last_success).toLocaleString('de-DE') : 'Noch kein erfolgreicher Live-Abruf'} · {provider.stale ? 'Datenstand fehlt oder ist veraltet' : 'Abruf aktuell'}</p>{provider.last_error && <p className="negative" role="alert">{provider.last_error.message} ({provider.last_error.code})</p>}</div></div>)}
    <p className="section-note">Automatik: {status.scheduler?.running ? `Aktiv · ${status.scheduler.cycles}/${status.max_cycles} Zyklen · Intervall ${status.interval_seconds}s` : 'Nicht aktiv'}. Sentiment ist keine Kauf-/Verkaufsempfehlung.</p>
  </Section>;
}

export function AggregateView({ value }: { value: NewsAggregate }) {
  return <div>
    <div className="data-row"><strong>{value.days === 1 ? '24 Stunden' : `${value.days} Tage`}</strong><Badge color={value.low_sample ? 'amber-badge' : ''}>{value.analyzed_count} ausgewertet</Badge></div>
    <div className="data-row"><span>Durchschnittlicher Score</span><strong>{number(value.mean_sentiment, 3)}</strong></div>
    <div className="data-row"><span>Positiv / Neutral / Negativ</span><strong>{value.positive} / {value.neutral} / {value.negative}</strong></div>
    <p className="section-note">{value.warning}. {value.duplicate_count} Duplikate ausgeschlossen. Letzte Meldung: {dateText(value.last_news_at)}.</p>
    {value.trend.length > 0 && <details><summary>Sentiment-Verlauf und Berechnungsgrundlage</summary>{value.trend.map(day => <div className="data-row" key={day.date}><span>{day.date} · {day.count} Meldungen</span><strong>{number(day.mean_sentiment, 3)}</strong></div>)}<p>Verlauf nach erster Beobachtung (UTC), gleiches Gewicht je Geschichte.</p><small>Basis: {value.basis_hash} · Stand: {value.as_of}</small></details>}
  </div>;
}

export function StockNewsPanel({ ticker }: { ticker: string }) {
  const stats = useQuery({ queryKey: ['news-sentiment', ticker], queryFn: () => api<{ windows: NewsAggregate[] }>(`/stocks/${encodeURIComponent(ticker)}/sentiment`) });
  const feed = useQuery({ queryKey: ['stock-news-feed', ticker], queryFn: () => api<NewsFeed>(`/news/feed?ticker=${encodeURIComponent(ticker)}&days=30&page_size=5`) });
  return <Section title="News & AI Sentiment" subtitle="24 Stunden, 7 und 30 Tage · nur tatsächlich analysierte Meldungen">
    <QueryState pending={stats.isPending} error={stats.error}><div className="three-grid">{stats.data?.windows.map(window => <AggregateView key={window.days} value={window} />)}</div></QueryState>
    <QueryState pending={feed.isPending} error={feed.error}>{feed.data?.items.length ? <div className="news-list">{feed.data.items.map(item => <NewsCard key={item.id} article={item} />)}</div> : <Empty>Keine gespeicherten Nachrichten für diese Aktie. Ein fehlender Zugang wird nicht durch Demo-Meldungen ersetzt.</Empty>}</QueryState>
  </Section>;
}

export function MarketNewsOverview() {
  const query = useQuery({ queryKey: ['market-news'], queryFn: () => api<{ items: NewsAggregate[]; latest: NewsArticle[]; providers: NewsProviderStatus }>('/news/summary') });
  return <Section title="Market News Intelligence" subtitle="Tatsächliche Nachrichten zur Watchlist · keine Handelssignale">
    <QueryState pending={query.isPending} error={query.error}>
      {query.data?.latest.length ? <><div className="watchlist-chips">{query.data.items.map(item => <a className="button" href={`#stock/${item.ticker}`} key={item.ticker}>{item.ticker} · {item.analyzed_count} Analysen · {number(item.mean_sentiment)}</a>)}</div><div className="news-list">{query.data.latest.slice(0, 3).map(item => <NewsCard key={item.id} article={item} />)}</div></> : <Empty>Keine echten Nachrichten gespeichert. Providerzugang unter News Intelligence konfigurieren; historische Kursdaten bleiben unabhängig nutzbar.</Empty>}
    </QueryState>
  </Section>;
}

export function NewsWorkspace({ config }: { config?: Config }) {
  const [ticker, setTicker] = useState('AAPL');
  const [days, setDays] = useState('30');
  const [source, setSource] = useState('');
  const [sentiment, setSentiment] = useState('');
  const [page, setPage] = useState(1);
  const [snapshot, setSnapshot] = useState<string | null>(null);
  const [generation, setGeneration] = useState(0);
  const reset = () => { setPage(1); setSnapshot(null); setGeneration(value => value + 1); };
  const params = new URLSearchParams({ days, page: String(page), page_size: '20', ...(ticker ? { ticker } : {}), ...(source ? { source } : {}), ...(sentiment ? { sentiment } : {}), ...(snapshot ? { as_of: snapshot } : {}) });
  const query = useQuery({ queryKey: ['news-feed', generation, params.toString()], queryFn: () => api<NewsFeed>(`/news/feed?${params}`), placeholderData: previous => previous });
  const providers = useQuery({ queryKey: ['news-providers'], queryFn: () => api<NewsProviderStatus>('/news/providers'), refetchInterval: 60000 });
  useEffect(() => { if (!snapshot && query.data?.as_of && !query.isPlaceholderData && !query.isFetching) setSnapshot(query.data.as_of); }, [snapshot, query.data?.as_of, query.isPlaceholderData, query.isFetching]);
  const supported = providers.data?.providers.some(p => p.configured && (!ticker || p.covered_tickers.includes(ticker)));
  return <>
    <div className="info-banner"><Newspaper size={19} /><div><strong>Sentiment beschreibt Tonalität, keine Kursprognose.</strong><p>ProsusAI/finbert verarbeitet englische Titel und nur freigegebene Kurzfassungen. Andere Sprachen erhalten keine künstlichen Scores.</p></div></div>
    <QueryState pending={providers.isPending} error={providers.error}>{providers.data && <ProviderPanel status={providers.data} />}</QueryState>
    <div className="toolbar">
      <select aria-label="News-Ticker" value={ticker} onChange={e => { setTicker(e.target.value); reset(); }}><option value="">Alle Aktien</option>{config?.watchlist.map(s => <option key={s.ticker}>{s.ticker}</option>)}</select>
      <select aria-label="News-Zeitraum" value={days} onChange={e => { setDays(e.target.value); reset(); }}><option value="1">24 Stunden</option><option value="7">7 Tage</option><option value="30">30 Tage</option><option value="365">1 Jahr</option></select>
      <select aria-label="News-Quelle" value={source} onChange={e => { setSource(e.target.value); reset(); }}><option value="">Alle Quellen</option>{query.data?.sources.map(s => <option key={s}>{s}</option>)}</select>
      <select aria-label="News-Sentiment" value={sentiment} onChange={e => { setSentiment(e.target.value); reset(); }}><option value="">Alle Sentiments</option><option value="positive">Positiv</option><option value="neutral">Neutral</option><option value="negative">Negativ</option><option value="unavailable">Nicht analysiert</option></select>
      <Action label="Nachrichten abrufen" path="/news/refresh" body={{ ticker: ticker || null }} disabled={!supported || config?.allow_mutations === false} onDone={reset} />
      <Action label="FinBERT ausführen" path="/news/analyze" disabled={config?.allow_mutations === false} onDone={reset} />
    </div>
    <Section title="Nachrichtenfeed" subtitle="Veröffentlichung, tatsächliche erste Beobachtung und Analysezeit sind getrennt.">
      <QueryState pending={query.isPending || query.isPlaceholderData} error={query.error}>{query.data?.items.length ? <div className="news-list">{query.data.items.map(item => <NewsCard key={item.id} article={item} />)}</div> : <Empty>Keine Nachrichten für diese Filter. Es werden keine simulierten Live-Meldungen erzeugt.</Empty>}</QueryState>
      <div className="table-footer"><button className="button" disabled={page <= 1} onClick={() => setPage(page-1)}>Vorherige Seite</button><span>Seite {page} · {query.data?.total ?? 0} Meldungen</span><button className="button" disabled={!query.data || page*query.data.page_size >= query.data.total} onClick={() => setPage(page+1)}>Nächste Seite</button></div>
    </Section>
    {ticker && <StockNewsPanel ticker={ticker} />}
  </>;
}
