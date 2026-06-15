# Stock Forecasting Pipeline

Dieses Repository dient als praktischer Proof of Concept für die Seminararbeit:

**„Konzeption einer skalierbaren Datenarchitektur für eine KI-Anwendung zur Prognose von Aktienkursbewegungen auf Basis historischer Marktdaten“**

## 1. Projektziel

Ziel dieses Projekts ist der Aufbau einer kleinen Data-Engineering-Pipeline, mit der historische Aktienmarktdaten über eine API abgerufen, gespeichert, bereinigt, transformiert und für ein Machine-Learning-Modell bereitgestellt werden können.

Der Fokus liegt dabei nicht auf einer perfekten Vorhersage von Aktienkursen, sondern auf der konzeptionellen und praktischen Umsetzung einer skalierbaren Datenarchitektur.

Im Mittelpunkt stehen folgende Aspekte:

- Datenkorpus historischer Aktienmarktdaten
- API-basierte Data Ingestion
- Speicherung von Rohdaten und verarbeiteten Daten
- Preprocessing und Datenbereinigung
- Feature Engineering
- Bereitstellung der Daten für ein Machine-Learning-Modell
- Dokumentation der geplanten Architektur

## 2. Fachlicher Hintergrund

Aktienmärkte erzeugen große Mengen historischer und fortlaufend neuer Daten. Diese Daten können genutzt werden, um Kursbewegungen datenbasiert zu analysieren und mögliche zukünftige Entwicklungen einzuschätzen.

Eine KI-Anwendung zur Prognose von Aktienkursbewegungen benötigt dafür eine zuverlässige Datenbasis. Bevor ein Machine-Learning-Modell eingesetzt werden kann, müssen die Daten strukturiert aufgenommen, gespeichert, bereinigt und in geeignete Merkmale überführt werden.

Dieses Projekt bildet genau diesen Data-Engineering-Prozess ab.

## 3. Geplante Datenquelle

Als primäre Datenquelle wird Yahoo Finance über das Python-Paket `yfinance` verwendet.

Die historischen Kursdaten enthalten typischerweise folgende Merkmale:

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

Optional kann die Architektur später um weitere Datenquellen erweitert werden, z. B. Finanznachrichten über eine News API wie GNews.

## 4. Geplante Datenpipeline

Die geplante Pipeline folgt einem typischen Data-Engineering-Ablauf:

```text
Yahoo Finance API
→ Data Ingestion
→ Raw Data Storage
→ Data Cleaning
→ Feature Engineering
→ PostgreSQL / Feature Tables
→ Machine-Learning-Modell
→ Prognose / Analyse
```

### 4.1 Data Ingestion

Im ersten Schritt werden historische Aktienkursdaten über eine API abgerufen. Die Daten werden zunächst unverändert als Rohdaten gespeichert.

### 4.2 Raw Data Storage

Die Rohdaten werden im Ordner `data/raw/` abgelegt. Dadurch bleibt nachvollziehbar, welche Daten ursprünglich aus der API geladen wurden.

### 4.3 Preprocessing

Im Preprocessing werden die Daten bereinigt und vereinheitlicht. Dazu gehören unter anderem:

- Prüfung auf fehlende Werte
- Entfernung von Duplikaten
- Vereinheitlichung von Datumsformaten
- Sortierung nach Ticker und Datum
- Prüfung auf unplausible Werte

### 4.4 Feature Engineering

Aus den historischen Kursdaten werden zusätzliche Merkmale berechnet, die später einem Machine-Learning-Modell als Input dienen können.

Geplante Features:

- Tagesrendite
- Gleitender Durchschnitt über 7 Tage
- Gleitender Durchschnitt über 30 Tage
- Volatilität
- Momentum
- Veränderung des Handelsvolumens
- Zielvariable für die Kursbewegung am Folgetag

### 4.5 Bereitstellung für Machine Learning

Die berechneten Features werden in einer strukturierten Form gespeichert und können anschließend für ein Machine-Learning-Modell verwendet werden.

Ein mögliches Ziel ist die Klassifikation der Kursrichtung:

```text
Steigt der Schlusskurs am nächsten Handelstag?
Ja / Nein
```

## 5. Projektstruktur

```text
stock-forecasting-pipeline/
│
├── README.md
├── requirements.txt
├── .gitignore
│
├── data/
│   ├── raw/
│   ├── processed/
│   └── features/
│
├── notebooks/
│   ├── 01_data_ingestion.ipynb
│   ├── 02_data_preprocessing.ipynb
│   ├── 03_feature_engineering.ipynb
│   └── 04_model_baseline.ipynb
│
├── src/
│   ├── ingestion.py
│   ├── preprocessing.py
│   ├── feature_engineering.py
│   └── database.py
│
├── sql/
│   ├── create_tables.sql
│   └── sample_queries.sql
│
└── docs/
    └── architecture.md
```

## 6. Ordnerbeschreibung

### `data/`

Der Ordner `data/` enthält die unterschiedlichen Datenstände der Pipeline.

- `data/raw/` enthält unveränderte Rohdaten aus der API.
- `data/processed/` enthält bereinigte und vereinheitlichte Daten.
- `data/features/` enthält berechnete Features für das Machine-Learning-Modell.

Die eigentlichen Datendateien werden nicht in Git versioniert.

### `notebooks/`

Die Notebooks dienen zur explorativen Entwicklung der Pipeline.

Geplante Notebooks:

- `01_data_ingestion.ipynb`
- `02_data_preprocessing.ipynb`
- `03_feature_engineering.ipynb`
- `04_model_baseline.ipynb`

### `src/`

Der Ordner `src/` enthält Python-Skripte für wiederverwendbare Funktionen.

Geplante Module:

- `ingestion.py` für den API-Abruf
- `preprocessing.py` für Datenbereinigung
- `feature_engineering.py` für Feature-Berechnung
- `database.py` für die PostgreSQL-Anbindung

### `sql/`

Der Ordner `sql/` enthält SQL-Skripte für die Datenbankstruktur und Beispielabfragen.

### `docs/`

Der Ordner `docs/` enthält ergänzende Dokumentation zur geplanten Architektur.

## 7. Geplantes Datenmodell

Für die strukturierte Speicherung der Daten kann PostgreSQL verwendet werden.

Eine mögliche Tabellenstruktur ist:

```text
dim_stock
- stock_id
- ticker
- company_name
- sector
- country

fact_stock_price
- price_id
- stock_id
- trade_date
- open_price
- high_price
- low_price
- close_price
- volume

fact_stock_features
- feature_id
- stock_id
- trade_date
- daily_return
- moving_average_7
- moving_average_30
- volatility_30
- momentum
- target_next_day_up
```

Dieses Datenmodell trennt Stammdaten, Kursdaten und berechnete Features voneinander.

## 8. Setup

### 8.1 Repository klonen

```bash
git clone https://github.com/Basti070301/stock-forecasting-pipeline.git
cd stock-forecasting-pipeline
```

### 8.2 Virtuelle Umgebung erstellen

```bash
python -m venv .venv
```

### 8.3 Virtuelle Umgebung aktivieren

Unter Windows:

```bash
.venv\Scripts\activate
```

Unter macOS/Linux:

```bash
source .venv/bin/activate
```

### 8.4 Abhängigkeiten installieren

```bash
pip install -r requirements.txt
```

## 9. Geplante Python-Pakete

Die wichtigsten verwendeten Pakete sind:

- `pandas` für Datenverarbeitung
- `numpy` für numerische Berechnungen
- `yfinance` für den Abruf historischer Aktienmarktdaten
- `scikit-learn` für ein einfaches Machine-Learning-Modell
- `matplotlib` für Visualisierungen
- `sqlalchemy` für Datenbankzugriffe
- `psycopg2-binary` für PostgreSQL
- `python-dotenv` für Umgebungsvariablen

## 10. Mögliche Machine-Learning-Idee

Für den Proof of Concept kann ein einfaches Klassifikationsmodell verwendet werden.

Zielvariable:

```text
target_next_day_up = 1, wenn der Schlusskurs am nächsten Handelstag höher ist
target_next_day_up = 0, wenn der Schlusskurs am nächsten Handelstag niedriger oder gleich ist
```

Mögliche Modelle:

- Random Forest Classifier
- Logistic Regression
- Decision Tree Classifier

Der Schwerpunkt des Projekts liegt jedoch nicht auf der Modellgüte, sondern auf der Datenarchitektur und der Bereitstellung geeigneter Daten für ein Modell.

## 11. Abgrenzung

Dieses Projekt stellt keine Anlageberatung dar. Die Anwendung dient ausschließlich als technischer Proof of Concept im Rahmen einer Seminararbeit.

Die Prognose von Aktienkursbewegungen ist grundsätzlich mit Unsicherheit verbunden. Ziel ist daher nicht die sichere Vorhersage von Kursen, sondern die beispielhafte Konzeption einer datengetriebenen Architektur für eine KI-Anwendung.

## 12. Erweiterungsmöglichkeiten

Mögliche Erweiterungen des Projekts sind:

- Integration einer News API für Finanznachrichten
- Sentiment-Analyse von Nachrichten
- Nutzung von Streaming-Daten
- Einsatz eines Feature Stores
- Deployment der Pipeline in der Cloud
- Automatisierung mit Apache Airflow
- Speicherung in einem Data Lake oder Lakehouse
- Aufbau eines Dashboards zur Visualisierung

## 13. Aktueller Status

Das Projekt befindet sich im Aufbau.

Geplante nächste Schritte:

1. Projektstruktur anlegen
2. Daten über `yfinance` abrufen
3. Rohdaten speichern
4. Preprocessing durchführen
5. Features berechnen
6. PostgreSQL-Datenmodell erstellen
7. Datenbankanbindung umsetzen
8. Ein einfaches Baseline-Modell testen
9. Architektur dokumentieren