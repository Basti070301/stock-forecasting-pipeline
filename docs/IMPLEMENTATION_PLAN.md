# Stock Intelligence AI – Implementierungsplan

Stand: 08.10.2026. Branch: `codex/stock-intelligence-platform`.

## M1 – Bestandsaufnahme

Der Checkout enthält fünf Yahoo-Tageskurs-Snapshots vom 25.08.2026, Profile,
eine CLI-Pipeline und drei unittest-Module. Keine AGENTS.md vorhanden.
Der erste Testversuch scheitert vor Testausführung an fehlendem SQLAlchemy.
Der Referenzbericht bleibt unverändert: Accuracy 0,519059, Mehrheitsreferenz
0,533658. Die bisherige Mehrheitsreferenz verwendet die Testklassenverteilung;
neue Evaluationen bestimmen die naive Klasse ausschließlich im Training.

Verträge: Raw = Yahoo Date/Open/High/Low/Close/Volume (adjustiert);
Processed = ticker + börsenlokales trade_date + snake_case OHLCV;
Features = sechs numerische Merkmale + nullable target_next_day_up.
Bestehende Tabellen: dim_stock, fact_stock_price, fact_stock_features.
CLI und historische Artefakte bleiben erhalten.

## Umsetzung

1. M2: FastAPI-Service in src/platform, React/TypeScript in frontend. Demo liest
   ausschließlich den fest benannten Repository-Snapshot; Live liest PostgreSQL.
   Bestehende reine Bereinigungs-/Featurefunktionen werden wiederverwendet.
2. M3: austauschbarer News-Provider, Alpha Vantage, UTC, URL-Deduplizierung,
   persistierte Erst-Erfassung, lazy FinBERT, explizite Sprachgrenzen.
3. M4: erklärbares Radar mit festen Gewichten, fehlenden Werten und Aktualität.
4. M5: LogisticRegression/RandomForest als Forschungskandidaten, zeitlich
   getrennte Kalibrierung. Keine Aktivierung durch einen einzelnen guten Backtest.
   Intraday separat, bis geeignete Daten vorliegen deaktiviert.
5. M6: expandierendes Walk-Forward, Label-Purging, nächste Sitzung Open→Close
   für ausführbare Paper-Renditen, Kosten, persistierte Reports und Jobstatus.
6. M7: Regression/API/Leakage/Provider/UI-Tests, Build, lokale Smoke-Prüfung,
   CI, Docker-Option, Windows-Anleitung und ehrlicher Abschlussbericht.

## Betriebsentscheidungen

Neue Tabellen nutzen das Präfix si_. Explizite additive Migration, kein DROP.
Demo darf eine separate SQLite-Datei nutzen; Live verwendet denselben
PostgreSQL-Zugang wie die Pipeline. Keine Migration bei GET-Anfragen.
Ein begrenzter Hintergrundworker pro Prozess; Serverbetrieb mit einem Worker.
Mutationen mit lokalem Zugriffsschutz, keine Secrets in API-Antworten.
Nach jedem Meilenstein passende Prüfungen; keine Veröffentlichung.
