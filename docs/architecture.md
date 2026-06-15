# Architekturkonzept: Stock Forecasting Pipeline

## 1. Ziel der Architektur

Ziel dieser Architektur ist die Konzeption einer skalierbaren Data-Engineering-Pipeline für eine KI-Anwendung zur Prognose von Aktienkursbewegungen auf Basis historischer Marktdaten.

Die Anwendung soll historische Aktienkursdaten über eine API abrufen, speichern, bereinigen, in geeignete Features transformieren und anschließend für ein Machine-Learning-Modell bereitstellen.

Der Schwerpunkt liegt auf dem Data-Engineering-Prozess und nicht auf der Optimierung eines perfekten Prognosemodells.

---

## 2. Fachlicher Use Case

Aktienmärkte erzeugen kontinuierlich große Mengen an Daten. Historische Kursdaten können genutzt werden, um Muster in Kursbewegungen zu analysieren und datenbasierte Prognosen zu erstellen.

Die geplante KI-Anwendung soll auf Basis historischer Marktdaten einschätzen, ob sich der Schlusskurs einer Aktie am nächsten Handelstag eher positiv oder negativ entwickelt.

Dabei handelt es sich nicht um eine sichere Vorhersage oder Anlageberatung, sondern um einen technischen Proof of Concept für eine datengetriebene KI-Anwendung.

---

## 3. Datenquellen

### 3.1 Primäre Datenquelle: Yahoo Finance

Als primäre Datenquelle wird Yahoo Finance über das Python-Paket `yfinance` verwendet.

Die Daten enthalten historische Kursinformationen wie:

- Datum
- Ticker-Symbol
- Open
- High
- Low
- Close
- Volume

Beispielhafte Aktien für den Proof of Concept:

- AAPL
- MSFT
- NVDA
- SAP.DE
- ALV.DE

### 3.2 Optionale Datenquelle: News API

Als mögliche Erweiterung kann eine News API wie GNews integriert werden.

Damit könnten Finanznachrichten zu bestimmten Aktien abgerufen und später für eine Sentiment-Analyse verwendet werden.

Mögliche Nachrichtenmerkmale:

- Veröffentlichungsdatum
- Titel
- Beschreibung
- Quelle
- URL
- Suchbegriff oder Ticker

Diese Erweiterung ist nicht Bestandteil des Kernprojekts, sondern wird als mögliche Weiterentwicklung betrachtet.

---

## 4. Gesamtarchitektur

Die geplante Architektur folgt einem klassischen Data-Engineering-Ablauf:

```text
Yahoo Finance API
        |
        v
Data Ingestion
        |
        v
Raw Data Storage
        |
        v
Preprocessing
        |
        v
Feature Engineering
        |
        v
PostgreSQL / Feature Tables
        |
        v
Machine-Learning-Modell
        |
        v
Prognose / Analyse
```

---

## 5. Architekturkomponenten

## 5.1 Data Ingestion

Die Data-Ingestion-Komponente ist für den Abruf der historischen Aktienkursdaten verantwortlich.

Aufgaben:

- Verbindung zur API herstellen
- Kursdaten für definierte Ticker abrufen
- Zeitraum festlegen
- Daten in ein einheitliches Format bringen
- Rohdaten speichern

Beispielhafter Ablauf:

```text
Ticker-Liste definieren
→ API-Abfrage starten
→ Kursdaten abrufen
→ Rohdaten als CSV speichern
```

Die Rohdaten werden zunächst unverändert gespeichert, damit der ursprüngliche Zustand der Daten nachvollziehbar bleibt.

---

## 5.2 Raw Data Storage

Die Rohdaten werden im Ordner `data/raw/` gespeichert.

Zweck:

- Nachvollziehbarkeit der ursprünglichen API-Daten
- Trennung von Rohdaten und verarbeiteten Daten
- Grundlage für spätere Reproduzierbarkeit

Beispiel:

```text
data/raw/stock_prices_raw.csv
```

In einer produktiven Architektur könnten Rohdaten alternativ in einem Cloud Object Storage wie Azure Blob Storage, Amazon S3 oder Google Cloud Storage abgelegt werden.

---

## 5.3 Preprocessing

Im Preprocessing werden die Rohdaten bereinigt und vereinheitlicht.

Typische Schritte:

- Spaltennamen vereinheitlichen
- Datumsformat standardisieren
- fehlende Werte prüfen
- Duplikate entfernen
- Daten nach Ticker und Datum sortieren
- unplausible Werte identifizieren

Das Ergebnis wird als bereinigter Datensatz gespeichert.

Beispiel:

```text
data/processed/stock_prices_clean.csv
```

---

## 5.4 Feature Engineering

Beim Feature Engineering werden aus den historischen Kursdaten zusätzliche Merkmale berechnet.

Diese Features dienen später als Input für das Machine-Learning-Modell.

Geplante Features:

| Feature | Beschreibung |
|---|---|
| `daily_return` | prozentuale Veränderung des Schlusskurses zum Vortag |
| `moving_average_7` | gleitender Durchschnitt über 7 Handelstage |
| `moving_average_30` | gleitender Durchschnitt über 30 Handelstage |
| `volatility_30` | Schwankungsintensität über 30 Handelstage |
| `momentum` | Kursdynamik über einen definierten Zeitraum |
| `volume_change` | Veränderung des Handelsvolumens |
| `target_next_day_up` | Zielvariable: Kurs steigt am nächsten Handelstag ja/nein |

Beispiel für die Zielvariable:

```text
target_next_day_up = 1, wenn Close(t+1) > Close(t)
target_next_day_up = 0, wenn Close(t+1) <= Close(t)
```

Die berechneten Features werden gespeichert unter:

```text
data/features/stock_features.csv
```

---

## 5.5 Speicherung in PostgreSQL

Für die strukturierte Speicherung kann PostgreSQL verwendet werden.

Die Datenbank trennt Stammdaten, Kursdaten und berechnete Features voneinander.

### Tabelle: `dim_stock`

Diese Tabelle enthält Stammdaten zu den Aktien.

```text
dim_stock
- stock_id
- ticker
- company_name
- sector
- country
```

### Tabelle: `fact_stock_price`

Diese Tabelle enthält historische Kursdaten.

```text
fact_stock_price
- price_id
- stock_id
- trade_date
- open_price
- high_price
- low_price
- close_price
- volume
```

### Tabelle: `fact_stock_features`

Diese Tabelle enthält berechnete Features für das Machine-Learning-Modell.

```text
fact_stock_features
- feature_id
- stock_id
- trade_date
- daily_return
- moving_average_7
- moving_average_30
- volatility_30
- momentum
- volume_change
- target_next_day_up
```

---

## 6. Datenmodell

Das Datenmodell orientiert sich an einem einfachen analytischen Schema.

```text
dim_stock
    |
    | stock_id
    v
fact_stock_price
    |
    | stock_id, trade_date
    v
fact_stock_features
```

Die Tabelle `dim_stock` enthält beschreibende Informationen zu den Aktien.

Die Tabellen `fact_stock_price` und `fact_stock_features` enthalten messbare und berechnete Werte.

Diese Trennung verbessert:

- Übersichtlichkeit
- Wiederverwendbarkeit
- Erweiterbarkeit
- Analysefähigkeit
- Nachvollziehbarkeit der Datenverarbeitung

---

## 7. Machine-Learning-Bereitstellung

Die Feature-Daten werden dem Machine-Learning-Modell in tabellarischer Form bereitgestellt.

Mögliche Input-Features:

- `daily_return`
- `moving_average_7`
- `moving_average_30`
- `volatility_30`
- `momentum`
- `volume_change`

Möglicher Output:

```text
target_next_day_up
```

Die Aufgabe kann als Klassifikationsproblem formuliert werden:

```text
Steigt der Schlusskurs am nächsten Handelstag?
Ja / Nein
```

Mögliche Baseline-Modelle:

- Logistic Regression
- Decision Tree Classifier
- Random Forest Classifier

Für den Proof of Concept reicht ein einfaches Baseline-Modell aus. Die Modellgüte steht nicht im Mittelpunkt des Projekts.

---

## 8. Skalierbarkeit

Die Architektur ist so gestaltet, dass sie später erweitert werden kann.

Mögliche Skalierungsansätze:

### 8.1 Mehr Aktien

Statt weniger Beispielaktien können später viele Ticker automatisiert verarbeitet werden.

### 8.2 Automatisierte Ausführung

Die Pipeline kann regelmäßig ausgeführt werden, z. B. täglich nach Börsenschluss.

Mögliche Tools:

- Cronjob
- Windows Task Scheduler
- Apache Airflow

### 8.3 Cloud Storage

Rohdaten könnten in einem Cloud-Speicher abgelegt werden.

Beispiele:

- Azure Blob Storage
- Amazon S3
- Google Cloud Storage

### 8.4 Data Warehouse oder Lakehouse

Für größere Datenmengen könnten analytische Plattformen genutzt werden.

Beispiele:

- PostgreSQL
- Azure Synapse
- Databricks
- Snowflake
- BigQuery

### 8.5 Erweiterung um weitere Datenquellen

Zusätzlich zu historischen Kursdaten könnten weitere Datenquellen integriert werden:

- Finanznachrichten
- Makroökonomische Daten
- Unternehmenskennzahlen
- Sentiment-Daten

---

## 9. Betriebskonzept

Ein mögliches Betriebskonzept sieht eine regelmäßige Aktualisierung der Daten vor.

Beispielhafter Tagesablauf:

```text
1. Pipeline startet nach Börsenschluss
2. Neue Kursdaten werden über die API geladen
3. Rohdaten werden gespeichert
4. Daten werden bereinigt
5. Features werden berechnet
6. Daten werden in PostgreSQL aktualisiert
7. Modell erhält neue Input-Daten
8. Prognose wird erzeugt
```

Wichtige Betriebsaspekte:

- Logging der Pipeline-Ausführung
- Fehlerbehandlung bei API-Ausfällen
- Prüfung auf fehlende Daten
- Speicherung historischer Datenstände
- regelmäßige Backups der Datenbank
- Dokumentation von Datenquellen und Verarbeitungsschritten

---

## 10. Limitationen

Die geplante Architektur hat einige Einschränkungen:

- Aktienkursbewegungen sind grundsätzlich schwer prognostizierbar.
- Historische Daten erklären zukünftige Entwicklungen nur begrenzt.
- Externe Ereignisse wie Nachrichten, Zinsentscheidungen oder Krisen werden im Basiskonzept nicht vollständig berücksichtigt.
- Yahoo-Finance-Daten über `yfinance` eignen sich gut für Lern- und Forschungszwecke, sind aber nicht zwingend für produktive Finanzsysteme geeignet.
- Die Modellgüte ist abhängig von Datenqualität, Feature-Auswahl und Marktphase.

---

## 11. Erweiterungsmöglichkeiten

Mögliche Erweiterungen der Architektur:

- Integration von GNews oder einer anderen News API
- Sentiment-Analyse von Finanznachrichten
- Verarbeitung von Streaming-Marktdaten
- Einsatz eines Feature Stores
- Orchestrierung mit Apache Airflow
- Deployment in Azure oder AWS
- Nutzung eines Data Lakehouse mit Delta Lake
- Visualisierung der Ergebnisse in einem Dashboard
- Monitoring der Modellperformance

---

## 12. Zusammenfassung

Die Architektur beschreibt eine skalierbare Data-Engineering-Pipeline für eine KI-Anwendung zur Prognose von Aktienkursbewegungen.

Im Mittelpunkt stehen:

- API-basierte Datenaufnahme
- Speicherung von Rohdaten
- Datenbereinigung
- Feature Engineering
- strukturierte Speicherung in PostgreSQL
- Bereitstellung der Daten für ein Machine-Learning-Modell

Damit bildet das Projekt die wesentlichen Schritte ab, die notwendig sind, um historische Aktienmarktdaten für eine KI-Anwendung nutzbar zu machen.