import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup } from '@testing-library/react';
import { QueryState, RadarTable } from './App';
import { api, type Stock } from './api';

afterEach(() => { cleanup(); vi.restoreAllMocks(); });
describe('API und ehrliche Datenzustände', () => {
  it('zeigt Laden und Fehler', () => {
    const { rerender } = render(<QueryState pending error={null}>Ergebnis</QueryState>);
    expect(screen.getByRole('status')).toHaveTextContent('geladen');
    rerender(<QueryState pending={false} error={new Error('Backend nicht erreichbar')}>Ergebnis</QueryState>);
    expect(screen.getByRole('alert')).toHaveTextContent('Backend nicht erreichbar');
    expect(screen.queryByText('Ergebnis')).not.toBeInTheDocument();
  });
  it('stellt fehlende Werte nicht als null Euro dar und verlinkt die Aktie', () => {
    render(<RadarTable stocks={[{ ticker: 'AAPL', company: 'Apple', exchange: 'NASDAQ', country: 'US', currency: 'USD', price: null, change: null, as_of: null, news_sentiment: null, radar_score: null, relative_volume: null } as Stock]} />);
    expect(screen.getByRole('link', { name: /Apple/ })).toHaveAttribute('href', '#stock/AAPL');
    expect(screen.getByText('Keine Analyse')).toBeInTheDocument();
    expect(screen.getByText('Nicht freigegeben')).toBeInTheDocument();
    expect(screen.queryByText('0,00')).not.toBeInTheDocument();
  });
  it('gibt API-Fehler verständlich weiter', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({ ok: false, json: async () => ({ detail: 'Zugriff fehlt' }) } as Response);
    await expect(api('/stocks')).rejects.toThrow('Zugriff fehlt');
  });
  it('lädt echte API-Antwort ohne Fallbackkurse', async () => {
    const fetcher = vi.spyOn(globalThis, 'fetch').mockResolvedValue({ ok: true, json: async () => [] } as unknown as Response);
    expect(await api('/stocks')).toEqual([]);
    expect(fetcher).toHaveBeenCalledWith('/api/stocks', undefined);
  });
});
