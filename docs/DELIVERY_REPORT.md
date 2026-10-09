# Technischer Abschlussbericht – Stock Intelligence AI

Stand: 08.10.2026. Umsetzung im bestehenden Repository, Branch
`codex/stock-intelligence-platform`. Keine Veröffentlichung, kein Push, kein
Live-Deployment, keine kostenpflichtige Buchung, keine Brokerintegration.

## Geliefertes Ergebnis

Lokal startbare FastAPI-/React-Plattform mit einem gebauten Frontend, echter
historischer Datenbasis und persistenter Forschungsauswertung. Die bestehende
Pipeline bleibt unverändert. Neue Services importieren ihre Bereinigungs-,
Feature-, Ingestion- und Modellfunktionen. PostgreSQL wird im Live-Modus
weiterverwendet; offline läuft eine getrennte SQLite-Demo.

Die Architektur ist in [PLATFORM_ARCHITECTURE.md](PLATFORM_ARCHITECTURE.md)
dokumentiert. Startanleitung: [LOCAL_SETUP.md](LOCAL_SETUP.md).

## Meilensteine und tatsächlicher Funktionsumfang

| Meilenstein | Ergebnis |
|---|---|
| M1 | Repository und Datenverträge geprüft; Implementierungsplan gespeichert; Originaltests bestanden |
| M2 | Backend, deutsche responsive Weboberfläche, Dashboard, fünf US-/EU-Aktien, Historien-/Volumencharts, Detailansichten, Dark/Light Mode, Live-DB-Leser und additive Migration |
| M3 | Alpha-Vantage-Adapter, Rate-Limits/Retry, UTC, Sprache, Deduplizierung, News-Ticker-Verknüpfung, echte FinBERT-CPU-Inferenz; Live-Providerabruf ohne Zugang unbestätigt |
| M4 | Regelbasiertes Radar, feste dokumentierte Gewichte, Erklärungen, Filter, Aktualität und fehlende Werte |
| M5 | Logistische Regression und Random Forest im Next-Day-Forschungsweg, getrennte Kalibrierung; keine operativen Modelle freigegeben; Intraday nur gesonderte Kalender-/Datenvalidierung |
| M6 | Ausführbare Walk-Forward-Backtests mit Kosten, Metriken, Artefakten und Einzelvorhersagen; append-only Journal/Outcome-Speicher und Paper-Ansicht vorbereitet, ohne automatische Prognosequelle |
| M7 | Backend-/Frontend-/Browserprüfungen, Windows-Start, CI und optionale Docker-Konfiguration; PostgreSQL und Docker hier nicht praktisch verifiziert |

Alle acht Navigationsseiten besitzen tatsächliche API-Anbindung. Nicht
verfügbare Nachrichten, Prognosen, Intervalle und Kennzahlen werden ausdrücklich
gekennzeichnet. Die Anwendung erzeugt keine Livekurse oder Prognosen als Demo.

## Testergebnisse

| Prüfung | Tatsächlich beobachtetes Ergebnis |
|---|---|
| Ursprüngliche unittest-Suite | 4 Tests bestanden |
| Vollständige pytest-Suite nach Erweiterungen | 26 bestanden, 1 PostgreSQL-Test übersprungen |
| Zusätzliche abschließende API-Prüfung nach Zeitzonen-Fix | 1 gezielter Test bestanden |
| Ruff auf neuer Service-/Testschicht | bestanden |
| Python-Bytecode-Kompilierung | bestanden |
| TypeScript Type Checking | bestanden |
| Vitest | 4 Tests bestanden |
| Vite-Produktionsbuild | bestanden; Diagramme separat gebündelt |
| Playwright / installierter Microsoft Edge | 2 End-to-End-Tests bestanden; Desktop/Mobil und API-Fehlerzustand |
| Ursprüngliche CLI `src.pipeline --no-database` | erfolgreich; 6.312 Featurezeilen, ROC-AUC 0,527831 |
| FinBERT Download + echte CPU-Inferenz | erfolgreich, drei Softmax-Scores und Modellrevision ausgegeben |
| PostgreSQL-Serverprüfung | nicht ausgeführt: kein konfigurierter Testserver |
| Docker-Build/-Start | nicht ausgeführt: Docker-Daemon nicht gestartet |
| Live-News-Providerabfrage | nicht ausgeführt: kein konfigurierter berechtigter API-Zugang |
| GitHub Actions | Workflow erstellt; nicht gepusht und daher kein Remote-CI-Ergebnis behauptet |

Der ursprüngliche Pipeline-Smoke-Lauf ergab identische Modellkennzahlen:
Accuracy 0,5190592052, Mehrheitsreferenz 0,5336577453. Der versionierte
`reports/model_metrics.json` wurde nach dieser Prüfung bytegenau wiederhergestellt.
Historische Raw-Snapshots, ursprüngliche Pythonmodule und Tests sind unverändert.

Die Backend-Suite prüft unter anderem API-Routen, Migrationserhalt,
Demo-/Live-Trennung, Deduplizierung, Sprachgrenzen, UTC-Konvertierung, Secretschutz,
chronologische Purges, fehlende Handelssitzungen, Kosten, Reproduzierbarkeit,
Modelldateien, Prognose-/Ausführungszeitpunkte, Intraday-Lücken und Jobfehler.
Provider-Tests verwenden Mocks. Eine Starlette-Deprecation-Warnung betrifft
den TestClient/httpx-Adapter; es gab dadurch keinen Testfehler.

E2E prüft Filter USA/Europa, Aktienwahl, Chartzeitraum, alle Seiten, einen echten
historischen Backtest, eine 390px-Ansicht ohne Seitenüberlauf und einen
absichtlich fehlerhaften API-Aufruf ohne erfundene Fallbackdaten.
Screenshots: `frontend/test-results/dashboard-desktop.png` und
`frontend/test-results/dashboard-mobile.png` (lokale, nicht versionierte Artefakte).

FinBERT-Smoke-Test: ausdrücklich synthetischer Prüfsatz, nicht als Nachricht
gespeichert. Modellrevision `4556d13015211d73dccd3fdd39d39232506f3e43`;
CPU-Scores positiv 0,954477, negativ 0,026259, neutral 0,019265. Das belegt die
funktionierende Modellinferenz, nicht einen erfolgreichen Live-News-Abruf.
Die geprüfte Windows-Paketliste steht in `tested-environment-windows.txt`.

## Neue und geänderte Dateien

- `src/platform/`: Konfiguration, Persistenz/Migration, Marktservice, Nachrichten,
  FinBERT, Radar, Forschung, Intraday-Grenzen, Jobs, API.
- `frontend/`: React/TypeScript-Anwendung, CSS, Vite-Konfiguration,
  reproduzierbarer pnpm-Lockfile, Komponenten-/API-Tests, Browserprüfungen.
- `tests/test_platform*.py`: Service-, API-, Zeitreihen-, Persistenz- und
  optionaler PostgreSQL-Integrationstest.
- `requirements-web.txt`, `requirements-finbert.txt`, `pyproject.toml`:
  Web-/ML-/Testabhängigkeiten und Prüfkonfiguration.
- `.env.example`, `scripts/start.ps1`, `scripts/check_finbert.py`:
  lokale Konfiguration, Start und optionaler Modelldownload/Inference-Smoke.
- `Dockerfile`, `compose.yaml`, `.dockerignore`: zusätzliche lokale Betriebsoption.
- `.github/workflows/platform.yml`: Backend, PostgreSQL, Frontend und E2E in CI.
- `docs/IMPLEMENTATION_PLAN.md`, `LOCAL_SETUP.md`, `PLATFORM_ARCHITECTURE.md`,
  `MIGRATIONS.md`, `PROVIDERS.md`, dieser Bericht und Paketnachweis.
- `README.md` ergänzt Einstieg zur Webplattform; `.gitignore` ergänzt
  Build-, Laufzeit-, Modellcache- und Testartefakte.

## Konkrete Grenzen und nächste Schritte

1. **PostgreSQL live prüfen:** vorhandenen Zugang in `.env` konfigurieren,
   additive Migration ausführen und den vorhandenen Kursbestand anzeigen.
   Ein gesonderter PostgreSQL-Test ist für CI vorbereitet.
2. **News aktivieren:** berechtigten Alpha-Vantage-Key bereitstellen;
   europäischen Wertpapieren erst nach Providerprüfung passende News-Symbole
   zuordnen. Die Provider-Schnittstelle, Speicherung und FinBERT funktionieren
   technisch; Zugriff und Berechtigungen sind hier nicht nachgewiesen.
3. **Zeitkorrekte News-Historie sammeln:** Erst-Erfassung und tatsächliche
   Analyseverfügbarkeit über längere Zeit archivieren. Erst dann News-Features
   in historische Prognosemodelle aufnehmen.
4. **Modellfreigabeverfahren entwickeln:** unabhängigen Holdout,
   Kalibrierungsstabilität, Regime-/Universumswechsel und realistische Kosten
   prüfen. Danach einen kontrollierten Next-Day-Forecast-Produzenten und
   Outcome-Abgleich an das bereits getrennte Journal anschließen.
5. **Intraday ergänzen:** berechtigten historischen Minutenfeed, Datenverzögerung
   und Handelsunterbrechungen dokumentieren; darauf eine eigene Feature-/Trainings-
   pipeline für 60/120 Handelsminuten aufbauen. Aktuell nicht implementiert.
6. **Betrieb skalieren:** bei Multiuser-/Mehrprozessbedarf echte Jobqueue,
   Authentifizierung, paginierte DB-Abfragen und versionierte Folgemigrationen
   ergänzen. Aktuell ist dies ein lokaler Einbenutzer-Forschungsserver.

Der vollständige ursprüngliche Gesamtauftrag ist bezüglich operativer
Prognosen/Intraday und freigeschalteter Live-Anbieter noch nicht abgeschlossen.
Die ausgelieferte Historien- und Forschungsplattform ist lokal ausführbar;
die offenen Teile werden in der UI und Dokumentation nicht als fertig ausgegeben.
