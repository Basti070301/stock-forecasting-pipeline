# Architekturkonzept: Stock Forecasting Pipeline

## 1. Ziel und Abgrenzung

Die Architektur stellt historische Aktienmarktdaten reproduzierbar für eine
KI-Anwendung bereit. Der Proof of Concept demonstriert Aufnahme, Speicherung,
Qualitätssicherung, Feature Engineering und eine einfache Modellbewertung.

Eine hohe Prognosegüte, automatisierter Handel und Anlageberatung sind nicht
Teil des Systems. Dadurch bleibt die technische Datenarchitektur klar vom
fachlich unsicheren Einsatzgebiet der Kursprognose getrennt.

## 2. Komponenten und Datenfluss

```text
Yahoo Finance API
        |
        v
Ingestion (src/ingestion.py)
        |
        v
Raw Layer: CSV + JSON, timestamp-basiert
        |
        v
Preprocessing (src/preprocessing.py)
        |                         |
        v                         v
Processed CSV             PostgreSQL fact_stock_price
        |                         + dim_stock
        v
Feature Engineering (src/feature_engineering.py)
        |                         |
        v                         v
Feature CSV               PostgreSQL fact_stock_features
        |
        v
Baseline-Modell (src/model_baseline.py)
        |
        v
Modellartefakt + Kennzahlen + Prognosen
        |
        v
Ausgeführte Analyse-Notebooks
```

`src/pipeline.py` orchestriert die Schritte. Die Ingestion ist optional, damit
ein gespeicherter Snapshot ohne Netzwerkzugriff erneut verarbeitet werden kann.

## 3. Datenverträge

### Raw Layer

- Pfade: `data/raw/prices/` und `data/raw/profiles/`
- Namen: `<TICKER>_<UTC_TIMESTAMP>.csv|json`
- Inhalt: von `yfinance` gelieferte Tageskurse und Unternehmensprofil
- Eigenschaft: append-only; vorhandene Snapshots werden nicht überschrieben

Das Preprocessing ermittelt pro Ticker automatisch die neueste Datei. Legacy-
Dateien ohne Zeitstempel und JSON-Payloads mit einem zusätzlichen `data`-Objekt
werden aus Gründen der Rückwärtskompatibilität unterstützt.

### Processed Layer

| Spalte | Typische Semantik |
|---|---|
| `ticker` | Yahoo-Finance-Symbol |
| `trade_date` | lokales Kalenderdatum der Börse |
| `open_price` | angepasster Eröffnungskurs |
| `high_price` | angepasstes Tageshoch |
| `low_price` | angepasstes Tagestief |
| `close_price` | angepasster Schlusskurs |
| `volume` | Handelsvolumen |
| `dividends` | Dividendenereignis |
| `stock_splits` | Splitereignis |

`trade_date` wird bewusst aus dem Datumsanteil des Quellwerts gelesen und nicht
in UTC konvertiert. Ein Börsenhandelstag ist eine fachliche Kalenderdimension;
eine UTC-Konvertierung von deutscher Mitternacht würde ihn auf den Vortag
verschieben.

### Feature Layer

Die Features werden je Ticker berechnet. Rolling Windows verwenden nur den
aktuellen und frühere Handelstage. Die Zielvariable greift als einziges Feld auf
den Folgetag zu und wird ausschließlich als Label verwendet.

## 4. Datenqualität

Das Preprocessing erzwingt folgende Regeln:

1. `Date` oder `Datetime` und die fünf Kernfelder OHLCV müssen vorhanden sein.
2. Datum und numerische Felder müssen konvertierbar sein.
3. Die Kombination aus Ticker und Handelstag ist eindeutig.
4. Kernpreise sind positiv.
5. `high_price` ist mindestens so hoch wie Open, Low und Close.
6. `low_price` ist höchstens so hoch wie Open, High und Close.
7. Volumen ist leer oder nicht negativ.
8. Dividenden und Splits erhalten bei fehlender Quelle den neutralen Wert null.

Ungültige Kernzeilen gelangen weder in die Processed-Dateien noch in
`fact_stock_price`. Unit Tests sichern insbesondere die Datumssemantik und die
Ticker-Grenzen des Feature Engineerings ab.

## 5. PostgreSQL-Datenmodell

```text
dim_stock (1)
   |
   +----< fact_stock_price (n)
   |
   `----< fact_stock_features (n)
```

### `dim_stock`

Unternehmensname, Sektor, Industrie, Land, Währung, Börse und Marktkapitalisierung.
Der Ticker ist eindeutig.

### `fact_stock_price`

Eine Zeile pro `stock_id` und `trade_date`. Ein Fremdschlüssel verweist auf
`dim_stock`; Upserts machen wiederholte Läufe idempotent.

### `fact_stock_features`

Eine Zeile pro `stock_id` und `trade_date` mit sechs Features und dem optionalen
Target. Die letzte Beobachtung eines Tickers besitzt kein bekanntes Target.

Bei einem kontrollierten Rebuild löscht `--replace` ausschließlich die Zeilen
der ausgewählten Ticker und schreibt sie innerhalb einer Transaktion neu. Raw-
Dateien werden dabei nicht verändert.

## 6. Machine-Learning-Bereitstellung

Die Baseline verwendet:

- standardisierte numerische Features,
- One-Hot-Encoding des Tickers,
- logistische Regression,
- chronologischen 80/20-Split anhand eindeutiger Handelstage,
- Accuracy, Balanced Accuracy, Precision, Recall, F1 und ROC-AUC,
- Vergleich mit einer Mehrheitsbaseline.

Ein zufälliger Split wird vermieden, weil er bei Zeitreihen Informationen aus
zukünftigen Marktphasen in das Training mischen könnte. Die Modellgüte wird als
technischer Referenzwert und nicht als Nachweis einer Handelsstrategie
interpretiert.

## 7. Betrieb und Fehlerbehandlung

Ein regelmäßiger Lauf kann nach Börsenschluss erfolgen:

```text
1. neuer Raw-Snapshot
2. Validierung und idempotenter Preis-Upsert
3. Neuberechnung der Features
4. Modellbewertung auf chronologischem Holdout
5. Speicherung von Kennzahlen und Laufstatus
```

Für einen produktiveren Betrieb wären zusätzlich sinnvoll:

- strukturiertes Logging mit Run-ID,
- Retry-Strategien und API-Rate-Limit-Behandlung,
- Schema-Migrationen statt eines einzelnen SQL-Skripts,
- Secrets Management statt lokaler `.env`,
- Data-Quality-Metriken und Alarmierung,
- Modell- und Daten-Drift-Monitoring,
- Backups und Aufbewahrungsregeln für Raw-Snapshots.

## 8. Skalierungspfad

Der PoC verarbeitet kleine Datenmengen mit pandas und PostgreSQL. Die logischen
Schichten lassen sich ohne Änderung der fachlichen Verträge skalieren:

| PoC | Mögliche Skalierung |
|---|---|
| lokales Raw-Verzeichnis | S3, Azure Blob Storage oder GCS |
| pandas | Spark, Polars oder SQL-Transformationen |
| manueller Aufruf | Airflow, Dagster oder Cloud Scheduler |
| PostgreSQL | Warehouse oder Lakehouse |
| lokale Modellartefakte | MLflow oder verwaltete Modellregistry |

Die wichtigsten Voraussetzungen dafür sind bereits vorhanden: getrennte
Datenzonen, stabile Schlüssel, idempotente Datenbankoperationen und ein
chronologisches Bewertungsverfahren.

## 9. Limitationen

- `yfinance` bietet keine garantierte Verfügbarkeit oder produktive SLA.
- `auto_adjust=True` verändert die historische Preisdarstellung fachlich.
- Fünf Aktien reichen nicht für allgemeine Marktaussagen.
- Technische Features erfassen Nachrichten, Zinsen und andere externe Ereignisse
  nicht.
- Gute historische Modellmetriken wären ohne zusätzliche Validierung kein
  Beleg für zukünftige Performance.
