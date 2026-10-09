# Additive Plattformmigration v1

Ausführen: `python -m src.platform.store --migrate`.

Die vorhandenen Tabellen `dim_stock`, `fact_stock_price` und
`fact_stock_features` werden weiterverwendet und nicht verändert. Neue Tabellen
werden mit SQLAlchemy-Metadaten und `create_all(checkfirst=True)` angelegt.
`si_schema_versions` dokumentiert v1; erneute Aufrufe sind idempotent.
Es gibt keinen automatischen Downgrade, DROP, TRUNCATE oder vollständigen Rebuild.

| Tabelle | Zweck / logischer Schlüssel |
|---|---|
| si_instruments | Instrumentkonfiguration / Modus + Ticker |
| si_news | Originaltext und Herkunft / Modus + Hash der kanonischen URL |
| si_news_links | News-Ticker-Zuordnung / Modus + News-ID + Ticker |
| si_sentiments | FinBERT-Scores und Modellrevision / Modus + News-ID |
| si_models | Evaluierte Modellläufe, Version, Metriken / Modus + UUID |
| si_forecasts | Unveränderliches Prognosejournal / Modus + Prognose-ID |
| si_outcomes | Später beobachtetes Ergebnis / Modus + Prognose-ID |
| si_backtests | Parameter, Metriken, Folds, Einzelprognosen / Modus + UUID |
| si_jobs | Pipeline-/News-/Analyse-/Backteststatus, Schritte / Modus + UUID |
| si_provider_calls | Persistiertes lokales News-Abrufbudget / Modus + UUID |
| si_intraday_prices | Reservierte Ablage, noch kein Datenfeed / Modus + Bar-ID |
| si_schema_versions | Migration / Modus + Version |

v1 verwendet einheitliche Dokumenttabellen mit `id` (PK), `mode` (Index),
`created_at` (UTC-ISO) und `payload` (SQLAlchemy JSON). Die fachlichen Felder
liegen im Payload. Keine implizite relationale FK-Prüfung zwischen den neuen
Dokumenttabellen: Referenzen und Providerdaten validiert die Service-Schicht.
Die News-Zuordnung wird bewusst separat gespeichert, sodass erneute Erfassung
den ersten Beobachtungszeitpunkt oder Originaltext nicht überschreibt.

Alle Inserts sind per Primärschlüssel idempotent. Nur Jobs und Instrumente sind
über die Store-Schnittstelle aktualisierbar. Prognosen, Ergebnisse, News,
Sentiment und Forschungsberichte sind dort append-only. Das ist ein
Anwendungsschutz, keine DB-Trigger-Sperre gegen direkte Administrator-SQLs.

Demo nutzt `.runtime/demo.sqlite`; Live dieselbe PostgreSQL-Engine wie die CLI.
Moduspräfixe isolieren auch dann, wenn bei Tests dieselbe Engine benutzt wird.
Für Live muss die Migration vor dem Backendstart erfolgen. Demo initialisiert
die ausschließlich lokale Datei beim Startup. GET-Anfragen migrieren niemals.

Vor künftigen Schemaänderungen DB sichern und eine neue explizite Migration
implementieren. `create_all` ist keine Änderung bestehender Spalten; v2 darf
nicht still in v1 hineingeschrieben werden.
