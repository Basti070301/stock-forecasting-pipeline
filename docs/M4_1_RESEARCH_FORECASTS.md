# M4.1 – Research Forecasts und eingefrorene Evaluation

Stand: 23.10.2026. Branch `codex/m4-ai-forecasting-engine`.
M4.0 wurde nach Diff-, Integritäts- und Gitleaks-Prüfung lokal gesichert:
`341fb6d388df84647812df398866ec293dcdc74f`
(`feat: implement versioned AI forecasting foundation`). Kein Push, Merge oder History-Rewrite.
Die vorhandenen unversionierten M2.4-/M3.2-Dokumente wurden erhalten und nicht mitcommitted.

## Aktueller Abschlussstand und wissenschaftliche Grenze

**M4.1 ist technisch abgeschlossen; die unabhängige Modellvalidierung bleibt offen.**

Die retrospektive Auswertung wurde am 23.10.2026 ausdrücklich genehmigt und als
`retrospective_diagnostic` ausgeführt. Der vollständige Abschluss mit Ergebnissen,
Git-Sicherung und aktuellen Tests steht in [M4.1 Abschluss](M4_1_COMPLETION.md).
Die ursprüngliche Implementierung ist lokal in
`e04191d6e2819fc5c5a5d972bf6bbe8b02de83eb` gesichert.

Der neue versionierte Bericht
`reports/research/m4_1_retrospective_diagnostic_v1.json` enthält die tatsächlichen
LR-/RF-Ergebnisse für identische 501 Beobachtungen: Featuretage 01.04.–24.08.2026,
letztes Label 25.08.2026. Accuracy LR 43,71 %, RF 43,91 %, Trainingsmehrheit 56,29 %.
Keine Optimierung, kein erneutes Training oder Kalibrieren der eingefrorenen Artefakte.

**Die unabhängige Modellvalidierung bleibt offen.** Der Zeitraum wurde bereits in
`reports/model_metrics.json` (Test 01.09.2025–24.08.2026) und früheren Forschungs-
Backtests betrachtet. Der alte Preflight-Bericht
`reports/research/m4_1_holdout_preflight_v1.json` bleibt unverändert als historischer
Nachweis der damaligen Blockade erhalten. Eine retrospektive Diagnose ist weder
unabhängige Leistungsbestätigung noch Profitabilitätsnachweis oder Modellfreigabe.

Der ursprüngliche identische Plan beider Modelle bleibt Training bis 31.12.2025,
Kalibrierung bis 31.03.2026 und Evaluationslabels bis 25.08.2026. Diese finale
Trainings-/Kalibrierungstrennung gilt weiter; sie macht den bereits betrachteten
Zeitraum nicht projektweit unangetastet. Alle Modelle bleiben `research_only`.

Der [prospektive Plan v1](M4_2_PROSPECTIVE_EVALUATION_V1.md) wurde vor Betrachtung der
retrospektiven Kennzahlen eingefroren. [M4.2](M4_2_CURRENT_MARKET_DATA_PLAN.md) ist
vorbereitet; noch keine Current-Automatisierung implementiert oder aktiviert.

## Architektur und Dateien

`ForecastRequest → ResearchForecastEngine.prepare → DB-Lease → bestehender Jobs-Worker
→ ArtifactRepository.load → LoadedResearchModel.predict_research → atomarer Store-Write
→ GET /api/forecasts → bestehende Aktienanalyse`.

Wiederverwendet werden der M4.0-Prognosevertrag, sechs technische Features,
Börsenkalender, Artefaktprüfungen, FastAPI-Autorisierung, Jobstatus und SQLite-/PostgreSQL-Store.
Die Trainings- und Inferenzmodule von M4.0 bleiben byteidentisch; andernfalls würde
deren absichtlich strenger Code-Fingerprint die eingefrorenen Artefakte ablehnen.
Es gibt keinen Modell-Upload, keine automatische Modellwahl und keine Modellfreigabe.

Neue Projektdateien:

- `src/platform/research_forecasts.py`: Requests, Engine, atomare Forschungsdokumente,
  prozessübergreifende Sperre und explizite Outcome-Prüfung.
- `src/platform/holdout_evaluation.py`: eingefrorener LR-/RF-Vergleich mit Reuse-Schutz.
- `frontend/src/ResearchForecasts.tsx`: Research-Panel und Evaluationsvergleich im bestehenden Design.
- `tests/test_research_forecasts.py`, `frontend/src/ResearchForecasts.test.tsx`,
  `frontend/e2e/research.spec.ts`: Offline-, Zugriffs-, Persistenz- und Browserprüfungen.
- Diese Dokumentation und der Holdout-Preflight-Bericht unter `reports/research/`.

Geändert: `src/platform/api.py`, `src/platform/config.py`, `frontend/src/App.tsx`,
`frontend/src/api.ts`, `.env.example`; README nur um den Dokumentationsverweis ergänzt.
Das bestehende Prognosejournal bekommt lediglich eine Replay-Kennzeichnung;
keine neuen Paper-Trading-Funktionen. Keine Änderung an News-Pipeline, Docker,
SQL-Referenzschema, historischen Kursdateien oder ursprünglichen Modellmetriken.

## Artefakte und tatsächlich ausgeführte Inferenz

Verwendete lokale, bereits vorhandene Artefakte:

| Modell | Artefakt-ID |
|---|---|
| LR | `m4-logistic-7a1a9e04acd8586ca379f2f1` |
| RF | `m4-random_forest-9bd3dc5bccedd47a2eb9c07c` |

Die vollständigen Versionen und SHA256-Prüfsummen stehen im Preflight-Bericht.
Lokaler Artefaktordner dieses Workspaces: `.runtime/m4/reference-models`.
Gewichte und Registry bleiben ignorierte lokale Laufzeitdaten, keine Git-Dateien.
Andere veraltete Artefakte im Ordner werden durch Kompatibilitätsprüfungen ausgeschlossen.

Ein eigener HTTP-Testserver auf Loopback-Port 18042 erzeugte **zehn tatsächliche
Research-Forecasts**: beide Modelle × AAPL, MSFT, NVDA, SAP.DE, ALV.DE.
Entscheidung `2026-08-25T21:45:00Z`, Feature-Sitzung 25.08., Ziel-Sitzung 26.08.2026.
Zehn Wiederholungen verwendeten dieselben Datensätze. Ein beendeter und neu
gestarteter Uvicorn-Prozess lieferte anschließend exakt dieselben gespeicherten Einträge.
Nachweis des abschließenden Laufs: `.runtime/m41/http-final/result.json` und
`server.log` im selben Ordner. Die eigenen Testprozesse wurden wieder beendet.

Beispiel AAPL: LR `P(Close(t+1)>Close(t)) = 0.4660470417871665`,
RF `0.4668304694424609`. Das sind einzelne kalibrierte Inferenzwerte,
**keine Trefferquoten, Holdout-Metriken oder Renditewahrscheinlichkeiten**.
Alle zehn Einträge sind `research_only`, `forecast_enabled=false`,
`historical_replay` und `counterfactual_model_replay=true`.

Die Modelle wurden am 17.10.2026 erzeugt. Ihre Anwendung auf Augustdaten ist
kontrafaktisch und wird nicht als damals erzeugte Prognose präsentiert.
Der konservative M4.0-Wissenszeitpunkt berücksichtigt die tatsächliche Beobachtung
des gesamten Repository-Snapshots am 25.08.2026 um 21:30:28 UTC. Frühere Replay-
Entscheidungen können deshalb trotz getrenntem Trainings-/Kalibrierungszeitraum
abgelehnt werden. Eine statistische Out-of-Sample-Auswertung wäre kein Nachweis,
dass das Artefakt damals operativ verfügbar war.

## Datenaktualität und Current Research Forecast

Entscheidungszeiten müssen eine Zeitzone enthalten und werden auf UTC normalisiert.
Die nächste abgeschlossene Sitzung wird über den jeweiligen Börsenkalender und
die im Modell festgelegte Publikationsverzögerung bestimmt. Fehlende Sitzungen,
ungültiges OHLCV, unvollständige Features und zukünftige Daten werden abgelehnt.
Features verwenden ausschließlich den zum Entscheidungspunkt zugelassenen Präfix.

Current benötigt zusätzlich belegte aktuelle Kursbeobachtungen und ein damals
vorhandenes Artefakt. Der August-Snapshot wird im Oktober als `stale_data`
abgelehnt. Die bestehende Live-OHLCV-Tabelle enthält keine hinreichenden
Original-Beobachtungszeitpunkte; dort wird `missing_provenance` gemeldet.
Ein neuer DB-Lesezeitpunkt wird ausdrücklich nicht als ursprünglicher Abrufzeitpunkt erfunden.

Der Current-Vertrag ist mit kontrolliertem historischen Clock-/Observation-Fixture
testbar. **Ein echter aktueller Forecast ist mit den vorhandenen Kursquellen noch BLOCKED.**
Es wurde kein neuer Datenabruf, keine zweite Marktdatenpipeline und keine externe
Veröffentlichung implementiert.

## Persistenz, Idempotenz und parallele Aufträge

Keine neue Datenbankarchitektur oder Tabelle:

| Bestehende Tabelle | Verwendung |
|---|---|
| `si_models` | Referenz auf eingefrorenes, kalibriertes Forschungsartefakt |
| `si_forecasts` | unveränderliches Forecast-Dokument mit vollständigem M4.0-Vertrag |
| `si_outcomes` | separat berechnete tatsächliche Richtung |
| `si_jobs` | vorhandene Jobzustände und Ergebnisse |
| `si_backtests` | typisierte, unveränderliche Vergleichsberichte |
| `si_news_locks` | vorhandener Lease-Speicher; isolierter Schlüsselraum `research:…` |

Forecast-ID: SHA256 über Artefakt-ID, Instrument, Horizont und normalisierten
Entscheidungszeitpunkt. Modus und Eingabedaten sind bewusst nicht Teil dieser ID,
damit eine Änderung daran einen Konflikt erzeugt. Der zusätzliche Fingerprint bindet
Modellversion, Artefakt-SHA, Datenversion, Herkunft, Features und Verfügbarkeitszeiten.
Die reine erneute Ausführungszeit wird nicht als neue Eingabe gewertet.

`immutable_documents` verwendet den bestehenden Store und transaktionale
`INSERT … ON CONFLICT DO NOTHING`-Operationen mit anschließendem Vergleich.
Ein Konflikt rollt die gesamte Modell-/Forecast-Transaktion zurück. Identische
Aufträge geben das Original zurück, ohne Wahrscheinlichkeit oder Erstellungszeit zu ändern.
Die bisherige Semantik von `Store.add` für ältere Aufrufer wurde nicht verändert.

Der API-Auftrag reserviert vor dem Scheduling eine atomare DB-Sperre. Dadurch
kann dieselbe fachliche Anfrage auch über getrennte DB-Verbindungen nicht parallel
Inferenz ausführen. Normale Erfolge, Ablehnungen und Schedulingfehler lösen die
Sperre ausschließlich mit passendem Owner wieder auf.

Nach hartem Prozessabbruch wird eine Research-Sperre bewusst **nicht automatisch
nach Zeitablauf gestohlen**. Zuerst alle eigenen Research-Worker beenden und prüfen,
dass kein Auftrag mehr läuft; anschließend ausschließlich den betreffenden Lock mit
bekanntem Owner über `ResearchForecastEngine.release(forecast_id, owner)` entfernen.
Kein pauschales Löschen der Lock-Tabelle. Aktueller Betriebsvertrag bleibt ein
ASGI-Worker; ein allgemeiner verteilter Job-Dispatcher gehört nicht zu M4.1.

## API und Berechtigungen

| Endpunkt | Zweck |
|---|---|
| `GET /api/research/models` | kompatible registrierte Artefakte, kein Joblib-Laden; Schreibfähigkeit |
| `POST /api/forecasts/research` | ausdrücklich angeforderter geschützter Job, HTTP 202 |
| `GET /api/jobs/{id}` | vorhandener Jobstatus, Fehler und Forecast-ID |
| `GET /api/forecasts?ticker=AAPL&kind=research_forecast&limit=50` | vorhandener lesender Endpunkt, neue optionale Filter |
| `GET /api/research/evaluations` | gespeicherte eingefrorene Vergleiche mit Evaluationsstatus |

POST verlangt `artifact_id`, vollständige `model_version`, einen der fünf Ticker,
`mode`, `decision_at` mit Zeitzone und optional `horizon="next_session"`.
Keine Dateipfade und keine zusätzlichen Upload-/Feature-Felder werden akzeptiert.
Ergebnis des Jobs: `forecast_id`, `reused`.

Es gelten unverändert Loopback-/Token-Schutz, Origin-Prüfung und gegebenenfalls
Proxy-Anmeldung. `SI_ALLOW_MUTATIONS=false` sperrt den Endpunkt auch bei gültigem
Token und vertrauenswürdigen Modellen. Ein Vertrauen-Schalter ersetzt keine
Authentifizierung. Gewichte nur aus selbst kontrolliertem Ordner laden:
Joblib ist kein sicheres Austauschformat für fremde Dateien.

Frontend: Aktienanalyse → **Research-Prognosen**. Modell und Zeitpunkt bewusst
auswählen; keine Vorauswahl eines Sieger-Modells. Kalibrierte Klassenwahrscheinlichkeit,
Zielsitzung, Erstellungszeit, historischer Entscheidungszeitpunkt, Datenstand,
Herkunft und Versionen werden angezeigt. Model Analytics enthält den separaten
Holdout-Vergleich mit Leerzustand und wissenschaftlichen Einschränkungen.

## Explizite retrospektive Evaluation

Das neue Modul ruft die bestehende Funktion `evaluate_holdout` auf. LR und RF müssen
identische Trainings-, Kalibrierungs-, Holdout-, Universums- und Datenstanddefinitionen
besitzen. Kein Fit, Refitting, Tuning oder Promoting. Tests erzwingen diese Eigenschaft.

Neben bestehenden Metriken werden zwei ausschließlich aus Training abgeleitete
Baselines berechnet: konstante Trainingsprävalenz und Trainingsmehrheitsklasse.
Kalibrierung: zehn disjunkte Bins einschließlich 0/1, ECE, mittlere Wahrscheinlichkeit
und tatsächlicher Positivanteil. Deskriptive 95%-Intervalle: gepaarter zirkulärer
Bootstrap über Sitzungsblöcke von fünf Tagen, alle Titel eines Tages zusammen,
1.000 Wiederholungen, Seed 42. Keine Signifikanz-/Profitabilitätsbehauptung;
kleine Stichproben und fehlende Regime-/Selektionskorrektur werden ausgewiesen.

Die ausdrückliche Genehmigung liegt jetzt vor; v1 wurde bereits ausgeführt.
Für eine spätere Wiederholung ausschließlich einen neuen Versionsnamen verwenden
(hier beispielhaft v2), niemals als unabhängigen Holdout-Test umdeuten:

```powershell
.\.venv\Scripts\python.exe -m src.platform.holdout_evaluation `
  --root .runtime/m4/reference-models `
  --artifacts m4-logistic-7a1a9e04acd8586ca379f2f1 m4-random_forest-9bd3dc5bccedd47a2eb9c07c `
  --trust-local-artifacts --acknowledge-reused-period `
  --output reports/research/m4_1_retrospective_diagnostic_v2.json
```

Ausgabedateien werden ausschließlich neu angelegt (`open("x")`), nie überschrieben.
Der Report bindet Codeversion, Modell-/Datenhashes und Zeitgrenzen. Optionales
`--persist` schreibt über den bestehenden Store nach `si_backtests` in den bewusst
konfigurierten lokalen Datenmodus. Ohne Reuse-Bestätigung lehnt die CLI ab.
Die Kennzeichnung lautet `retrospective_diagnostic`; unabhängige Abnahme bleibt
auch bei erlaubter retrospektiver Auswertung `blocked`.

## Outcome-Vorbereitung

`record_outcome` ist eine explizite Python-Funktion ohne Scheduler/öffentlichen
Schreibendpunkt. Sie prüft Originalvertrag, tatsächlichen Zielsitzungsschluss plus
Verzögerung, Beobachtungszeit, beide Schlusskurse, zusammenhängende Sitzungen
und unveränderten historischen Kurspräfix. Zu frühe oder revidierte Eingaben werden
abgelehnt. Originalprognosen bleiben unberührt; Outcomes sind separat idempotent.
Die lesende API unterdrückt zukünftige Outcome-, Beobachtungs- und Berechnungszeiten.
Zeitlich ungültige Snapshot-Verträge werden als verständliche HTTP-409-Ablehnung
zurückgegeben, nicht als interner Serverfehler.

Für die echten August-25-Replays fehlt im Referenzbestand der Schlusskurs vom
26.08.2026. Deshalb wurden dafür **keine Outcomes** erzeugt. Outcome-Automatisierung
und dauerhafte Point-in-Time-Kursbeobachtung sind für M4.2 vorgesehen.

## Lokaler Windows-Start

Bestehende virtuelle Umgebung und vorhandene Frontend-Abhängigkeiten verwenden.
Für einen isolierten Research-Workspace in einem eigenen Terminal:

```powershell
Set-Location C:\Dev\KI\LAB\stock-ai
$env:SI_MODE = 'demo'
$env:SI_RUNTIME_DIR = '.runtime/m41/local'
$env:SI_RESEARCH_ARTIFACT_DIR = '.runtime/m4/reference-models'
$env:SI_RESEARCH_TRUST_LOCAL_ARTIFACTS = 'true'
$env:SI_NEWS_AUTO_REFRESH = 'false'
.\.venv\Scripts\python.exe -m uvicorn src.platform.api:app --host 127.0.0.1 --port 8000
```

Vorher freien Port prüfen. Bereits bestehende `.env`-Authentifizierung nicht
überschreiben; bei gesetztem Mutationstoken den vorhandenen Einstellungsdialog nutzen.
Öffnen: `http://127.0.0.1:8000/#stock/AAPL`. Frontend-Build bei Bedarf in separatem
Terminal aus `frontend`: `node node_modules/typescript/bin/tsc -b`, danach
`node node_modules/vite/bin/vite.js build`. Lokaler Vite-Entwicklungsmodus bleibt erhalten.

Artefaktordner fehlt auf anderem Rechner: keine Gewichte aus fremdem Chat/Upload
nachladen. Vorhandenes eigenes Artefaktbackup sicher kopieren und mit `model_training
inspect --root … --artifact-id …` kontrollieren; alternativ ausdrücklich neue Modelle
mit dem dokumentierten M4.0-Plan trainieren. Das wäre ein neuer Trainingslauf,
kein Ersatz für die hier geprüften eingefrorenen Dateien.

## Tests und Grenzen

Erfolgreich praktisch geprüft:

- Vollständige Backend-Regression: **123 bestanden, 2 PostgreSQL-Tests übersprungen**
  (`.runtime/m41/backend.xml`), einschließlich echter FinBERT-CPU-Inferenz ohne Netzwerkdownload.
- Nach den abschließenden Prüfungen zusätzlich **43 gezielte Forecast-/API-Tests bestanden**.
  Die endgültige Research-Suite besteht mit **27 Tests** einschließlich der letzten
  Snapshot-/Registry-Fehlerfälle (`.runtime/m41/accepted-forecast.xml`). Die gezielten
  Läufe überschneiden sich mit der vollständigen Regression und sind nicht zu addieren.
- 17 Frontendtests inklusive sechs neuer Research-Tests; Testdaten sind explizite Fixtures.
- TypeScript und abschließender Produktionsbuild bestanden, einschließlich Legacy-/Research-Filter
  und expliziter Richtungsklasse mit Schwelle 0,5.
- **4 Browser-Tests bestanden**, auch gegen den abschließenden Build: bestehende
  Plattform/Backtest, Fehleransicht, markierte News-Fixtures und tatsächlicher Research-Job
  mit eingefrorenem LR-Modell, Wiederholung, Replay-Anzeige und Current-Stale-Ablehnung.
  Screenshot: `frontend/test-results/research-replay.png` (lokal, nicht versioniert).
- Zehn echte HTTP-Inferenzen plus zehn Wiederholungen und Server-Prozessneustart.
- Ursprüngliche Pipeline in isolierter Projektkopie: **6.312 Featurezeilen**, alle
  ursprünglichen numerischen Referenzmetriken unverändert.

Statisch geprüft: Ruff, `git diff --check`, PostgreSQL-SQL-Kompilierung für atomare
Inserts und Gitleaks (keine Secrets). SHA256-Vergleich bestätigt **124 unveränderte
Bestandsdateien**, darunter M4.0-Trainings-/Artefaktmodule, eingefrorene Modelle,
historische Daten/Referenzmetriken, `.env` und die drei fremden/unversionierten Dokumente.
Es gibt sechs beabsichtigt geänderte Bestandsdateien und acht neue M4.1-Projektdateien.
Die ursprünglichen 14 M4.1-Dateien sind in `e04191d` lokal gesichert.
Die abschließende Genehmigung, Diagnose und Planungsdokumentation werden separat
lokal gesichert; kein GitHub-Push. Aktuelle Tests/Dateien siehe Abschlussbericht.

Testgrenzen: Provider-/News-UI-Tests arbeiten weiterhin mit markierten Fixtures;
die Research-HTTP- und Browser-Prüfungen laden tatsächliche lokale M4.0-Artefakte.
Reproduzierbare Eval-Unit-Tests verwenden eigene kleine Referenz-Teilmengen und
Testmodelle. Der zusätzlich genehmigte tatsächliche Diagnoselauf mit beiden
eingefrorenen Artefakten ist im neuen versionierten Bericht separat dokumentiert. Ein Test erwartete zunächst einen
anderen sicheren Fehlercode für eine beschädigte Registry; die Erwartung wurde an
den bestehenden Repository-Code `invalid_metadata` angepasst und erneut geprüft.
Eine vorhandene Starlette/httpx-Deprecation-Warnung bleibt bestehen.

BLOCKED: unabhängiger unangetasteter Holdout, echte Current-Marktdaten mit
belegter Beobachtung, PostgreSQL-Laufzeitprüfung ohne ausdrücklich bereitgestellte
isolierte Instanz. Docker-/Proxmox-Laufzeittests wurden nicht durchgeführt und gehören
nicht zu M4.1. Keine Live-News-Abrufe oder kostenpflichtigen Dienste aktiviert.

Reproduzierbare Befehle:

```powershell
$env:SI_TEST_FINBERT_CPU = '1'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:SI_TEST_POSTGRES = '0'
$env:SI_TEST_COMPOSE_JSON = '.runtime/m32/compose.json'
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.runtime/m41/recheck
# Aus frontend:
node node_modules/vitest/vitest.mjs run --maxWorkers=1
node node_modules/typescript/bin/tsc -b
node node_modules/vite/bin/vite.js build
```

Der Compose-JSON-Pfad ist eine vorhandene statische Testfixture, kein Nachweis
eines Docker-Laufzeittests. Browser-Regression nutzt einen eigenen Loopback-Testserver
und eine eigene SQLite-Datei. Der neue Browser-Test wird ohne ausdrücklich
konfigurierten vertrauenswürdigen Artefaktordner übersprungen; dadurch bleibt die
normale Installation ohne lokale Gewichte testbar. Für M4.1 wird dieser Test
ausdrücklich mit den vorhandenen Artefakten ausgeführt, nicht durch Modell-Fixtures ersetzt.

Für die Browser-Suite aus `frontend`, bei freiem Port 8000 und vorhandenem
eigenem M4.0-Artefaktordner:

```powershell
$env:CI = '1'  # Verhindert Wiederverwendung eines bereits laufenden Servers.
$env:SI_TEST_PYTHON = 'C:\Dev\KI\LAB\stock-ai\.venv\Scripts\python.exe'
$env:SI_TEST_EDGE = '1'
$env:SI_RESEARCH_ARTIFACT_DIR = (Resolve-Path ..\.runtime\m4\reference-models).Path
$env:SI_RESEARCH_TRUST_LOCAL_ARTIFACTS = 'true'
$env:SI_ALLOW_MUTATIONS = 'true'
$env:SI_MUTATION_TOKEN = ''
$env:SI_PROXY_TOKEN = ''
$env:SI_NEWS_ENABLED = 'false'
$env:SI_NEWS_AUTO_REFRESH = 'false'
node node_modules/@playwright/test/cli.js test
```

Diese Flags gehören ausschließlich in das eigene Testterminal; sie ändern weder
die lokale `.env` noch die Authentifizierung vorhandener Server. Die Standard-
Browserkonfiguration erzwingt Demo-Modus und `.runtime/e2e`. Unsere dokumentierten
Abnahmeläufe verwendeten zusätzlich den separaten Port 18041 und
`.runtime/m41/browser-final`. Ein Portkonflikt ist ein Abbruchgrund, keine Freigabe
zum Beenden oder Wiederverwenden anderer Prozesse.

## Empfehlung für M4.2

1. Eingefrorenes Protokoll v1 für neue echte Forecasts beibehalten. Die genehmigte
   retrospektive Diagnose bleibt separat; keine Modellwahl oder Optimierung aus ihr.
2. Beobachtungszeitpunkte/Revisionen echter Kursabrufe additiv an die vorhandene
   Pipeline anbinden; Training, Forecasts und Outcomes müssen dieselbe Point-in-Time-
   Datenbasis nachvollziehen können.
3. Erst danach Current Research Forecasts und kontrollierte Outcome-Automatisierung
   praktisch abnehmen; weiterhin keine automatische Modellfreigabe oder Trading-Ausführung.
