# Stock Intelligence AI lokal betreiben

Die vorhandene Pipeline bleibt erhalten. Die Webplattform startet standardmäßig
offline mit den fünf echten Repository-Snapshots vom 25.08.2026. Demo heißt hier
historische Daten, nicht synthetische Kurse. Kein API-Schlüssel und kein PostgreSQL
sind dafür erforderlich.

## Windows – Installation

Getestet: Windows, Python 3.14.7, Node.js 24.19.0, pnpm 11.25.0.
Python 3.12+ ist vorgesehen; optionale ML-Pakete benötigen passende Wheels.
Python und Node.js LTS müssen installiert und im PATH sein.

PowerShell im Repository:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-web.txt
npm install --global pnpm@11.25.0
Set-Location frontend
pnpm install --frozen-lockfile
pnpm build
Set-Location ..
Copy-Item .env.example .env
.\scripts\start.ps1
```

Falls die lokale PowerShell-Ausführungsrichtlinie das Skript blockiert, ist der
gleichwertige direkte Start ohne Änderung der Richtlinie möglich:

```powershell
.\.venv\Scripts\python.exe -m uvicorn src.platform.api:app --host 127.0.0.1 --port 8000
```

Weboberfläche: http://127.0.0.1:8000 · API-Dokumentation: http://127.0.0.1:8000/docs
Strg+C beendet den Server. Ein Worker; keine öffentliche Bindung.

Die Demo-Datenbank `.runtime/demo.sqlite` wird beim ersten Start additiv angelegt.
Backtests und Watchlist bleiben nach Neustarts erhalten. Externe News-Abrufe
sind im Demo-Modus gesperrt. Keine Fake-News, Fake-Prognosen oder Demo-Live-Kurse.

## Entwicklung mit Hot Reload

Terminal 1, Repository:

```powershell
.\.venv\Scripts\python.exe -m uvicorn src.platform.api:app --reload --host 127.0.0.1 --port 8000
```

Terminal 2:

```powershell
Set-Location frontend
pnpm dev
```

Frontend: http://127.0.0.1:5173. Vite leitet `/api` an Port 8000 weiter.
Die Oberfläche nutzt deutsche Texte, CSS-Designvariablen, React, TypeScript,
TanStack Query, Recharts und Lucide. Kein externer Font-/Bildabruf notwendig.

## Live-Modus und bestehende PostgreSQL-Datenbank

Bestehende Datenbank verwenden; Zugang nur lokal in `.env` eintragen:

```dotenv
SI_MODE=live
DB_HOST=127.0.0.1
DB_PORT=5432
DB_NAME=stock_forecasting
DB_USER=postgres
DB_PASSWORD=dein_lokales_passwort
```

Vor dem Serverstart explizit migrieren:

```powershell
.\.venv\Scripts\python.exe -m src.database --init
.\.venv\Scripts\python.exe -m src.platform.store --migrate
```

`src.database --init` legt nur fehlende PoC-Tabellen an. Die Plattformmigration
ergänzt `si_*`; sie löscht keine Daten. Details: [MIGRATIONS.md](MIGRATIONS.md).
Ein vorhandener Datenbestand erscheint sofort im Dashboard. Ohne Kursdaten
bleibt Live leer; es gibt keinen Rückfall auf Demo-Kurse.

Initiale Datenaufnahme: in der Weboberfläche **Pipeline Status → Kurse
aktualisieren**. Der kontrollierte POST-Job verwendet `run_ingestion`,
`process_ticker` und `build_features` des ursprünglichen Projekts mit Upserts.
Kein `--replace`, kein Training bei einem Seitenaufruf. Rohdaten bleiben erhalten.

Die ursprüngliche CLI ist ebenfalls verfügbar:

```powershell
.\.venv\Scripts\python.exe -m src.pipeline --ingest --period 5y
# Vorhandene Snapshots vollständig ohne PostgreSQL verarbeiten:
.\.venv\Scripts\python.exe -m src.pipeline --no-database
```

Die ursprüngliche CLI trainiert weiterhin das PoC-Modell und überschreibt dessen
Modell-/Reportdateien wie bisher. Web-Backtests schreiben ausschließlich neue
Artefakte in `.runtime/<mode>/backtests/<run-id>/`.

## Nachrichten und FinBERT

Alpha Vantage benötigt einen vom Nutzer bereitgestellten gültigen API-Zugang
mit Berechtigung für `NEWS_SENTIMENT`. Dieser Endpoint ist laut aktueller
Dokumentation Premium; ein kostenloser Key garantiert keinen Zugriff. Es werden
keine Abos abgeschlossen. Siehe [PROVIDERS.md](PROVIDERS.md).

```dotenv
SI_ALPHA_VANTAGE_KEY=dein_key
SI_FINBERT_ENABLED=true
SI_FINBERT_DEVICE=-1
```

Installation und expliziter Modelldownload/CPU-Test:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-finbert.txt
.\.venv\Scripts\python.exe -m scripts.check_finbert
```

Der Prüfsatz ist synthetisch und wird nicht als Nachricht gespeichert. Der
Cache liegt unter `.cache/huggingface`. Danach Backend neu starten,
**News Intelligence → Nachrichten abrufen → FinBERT ausführen**. FinBERT wird
lazy einmal je Prozess geladen. `-1` = CPU; bei einem GPU-Geräteindex erfolgt
CPU-Fallback, wenn CUDA nicht verfügbar ist. Deutsche/unklare Sprache wird
gekennzeichnet und nicht analysiert. Es wird nicht automatisch übersetzt.

## Schutz lokaler Aktionen

Standardmäßig dürfen nur Loopback-Clients mutieren, mit geprüften Origins und
Hosts. Optional `SI_MUTATION_TOKEN` setzen und in der Oberfläche unter
**Einstellungen** eingeben. Der Schlüssel bleibt im Arbeitsspeicher des Tabs;
er wird weder vom Backend ausgeliefert noch in Local Storage gespeichert.
Die UI zeigt ausschließlich Providerstatus. Keine Multiuser-Authentifizierung;
öffentlicher Betrieb ist nicht Gegenstand dieses Projekts.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check src/platform tests/test_platform.py tests/test_platform_postgres.py
Set-Location frontend
pnpm test
pnpm build
pnpm exec playwright install chromium
$env:SI_TEST_PYTHON = (Resolve-Path ..\.venv\Scripts\python.exe).Path
pnpm test:e2e
```

Alternativ nutzt `SI_TEST_EDGE=1` den bereits installierten Microsoft Edge.
E2E startet das Backend bei Bedarf selbst; bei laufendem Server wird dieser
wiederverwendet. E2E legt echte Forschungs-Backtests in dessen Demo-Datenbank an.
Screenshots liegen unter `frontend/test-results/` und sind nicht versioniert.

Für den PostgreSQL-Test nur eine ausdrücklich entbehrliche Testdatenbank
verwenden: `SI_TEST_POSTGRES=1` und `DB_*` setzen. CI provisioniert hierfür einen
eigenen PostgreSQL-Container. Ohne diese Einstellung wird genau dieser Test
übersprungen. News-Unit-Tests verwenden HTTP-Mocks, keine kostenpflichtigen APIs.

## Docker als Option

Docker Desktop muss laufen. Für lokale Mutationen durch die Container-Bridge
`SI_MUTATION_TOKEN` in `.env` setzen; außerdem `DB_PASSWORD` für das optionale
PostgreSQL-Profil. Keine Standardpasswörter verwenden.

```powershell
docker compose up --build web
# Optional nur einen lokalen PostgreSQL-Server bereitstellen:
docker compose --profile live up -d postgres
```

Der Webcontainer läuft standardmäßig im Demo-Modus; Port 8000 und der optionale
DB-Port 5432 sind ausschließlich an 127.0.0.1 gebunden. Für eine bestehende
PostgreSQL-Datenbank ist der oben beschriebene native Start der einfachste Weg.
Docker-Live-Betrieb benötigt zusätzlich SI_MODE/DB_* für den Webservice und die
explizite Migration vor dem Start. Keine automatische Live-Migration vorgesehen.

## Typische Probleme

- **API nicht erreichbar:** Backend starten; Port 8000 prüfen. Ein vorhandener
  `frontend/dist`-Build ist für den Ein-Server-Modus erforderlich.
- **Live-Start meldet Migration:** beide oben dokumentierten Migrationsbefehle
  gegen die richtige DB ausführen. Keine automatische Datenlöschung versuchen.
- **News fehlen:** Live-Modus, Key, Tarif und Watchlist-News-Symbol prüfen.
  SAP.DE/ALV.DE haben absichtlich keine ungeprüfte Alpha-Vantage-Zuordnung.
- **Backtest hat zu wenig Daten:** Standard benötigt 252 Trainingstage,
  63 Kalibrierungstage und mindestens einen Testtag nach Feature-Anlaufphase.
  Feiertage, fehlende Folgesitzungen und unbekannte Targets werden ausgeschlossen.
- **Job unterbrochen:** Serverneustart beendet In-Process-Jobs; der nächste Start
  markiert sie als `interrupted`. Jobs sind nicht automatisch wiederaufnehmbar.
- **FinBERT-Download:** Internet und Speicherplatz prüfen. Webplattform und
  historische Backtests funktionieren auch ohne Transformers/PyTorch.
