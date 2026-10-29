# M4.2b – Current Research Forecast Pipeline & Controlled Automation

Prüfstand: 29.10.2026, nach ersten Teilläufen am 24.10.2026.
Branch `codex/m4-2b-forecast-automation`, Basis
`f9c1ddf7d37c017915115c3162f69e4d25899a0d`. Commit dieses Abschlussstands:
`git log -1 --format=fuller`. Keine Veröffentlichung und kein Deployment.

## Architektur und Datenfluss

```text
explizite lokale Provider-/E2E-Abnahme
  -> vorhandene Tageskurs-Ingestion und additive v4-Persistenz
  -> Receipt + Kursrevisionen + nachgelagerte Commit-Bestätigung
  -> as-of-Auswahl zum tatsächlichen serverseitigen Entscheidungszeitpunkt D
  -> vorhandenes prepare_snapshot / unveränderte sechs technische Features
  -> eingefrorene LR- und RF-Artefakte / vorhandene ResearchForecastEngine
  -> atomare Speicherung beider Prognosen im vorhandenen Store
  -> bestätigter Sitzungsmarker vor Zielöffnung und spätestens D + 300 s
  -> später: tatsächlich beobachteter Zielkurs / separates Outcome
  -> vorhandene Forecast-API und minimale Ergänzungen der Research-Oberfläche
```

`current_forecasts.py` verbindet die bestehenden Bausteine. In
`research_forecasts.py` wurde die verifizierte Erstellung von Dokumenten von deren
Commit getrennt; bestehende einzelne Replay-Jobs behalten ihr Verhalten.
`immutable_documents` speichert beide Modelle und Forecasts gemeinsam oder gar
nicht. Die sechs fingerprintgebundenen Modell-/Featuremodule bleiben unverändert.
Keine neue Datenbankarchitektur, kein Fit und keine Auswahl anhand der Diagnose.

Verwendet werden ausschließlich die zwei im eingefrorenen Protokoll v1 genannten
Artefakte, deren Versionen, Gewichts-/Metadatenhashes, Laufzeitkompatibilität und
`research_only`-Status geprüft werden. Universum: AAPL, MSFT, NVDA, SAP.DE, ALV.DE.
Die bestehende XNYS-/XETR-Zuordnung wird wiederverwendet. Ziel und Schwelle bleiben
`Close(t+1) > Close(t)` und 0,5; keine Handelsentscheidung oder Modellfreigabe.

## Anbieterprüfung und weiterhin blockierter Zugang

**Es wurden null echte Providerabrufe durchgeführt.** Kein realer Zugang oder
Tarif wurde eingerichtet. Es liegen keine echten neuen Current-Forecasts oder
prospektiven Outcomes vor. Alle positiven technischen Tests verwenden Fixtures;
auch simulierte Provider-Abnahmebelege in Unit-Tests sind keine echte Abnahme.

Erneut geprüft am 29.10.2026:

- [yfinance](https://ranaroussi.github.io/yfinance/) beschreibt ein inoffizielles,
  nicht von Yahoo abgenommenes Forschungswerkzeug und verweist für Datenrechte auf
  gesonderte Bedingungen. Persönliche Nutzung ist keine pauschale Erlaubnis für
  automatisierte Speicherung, Analyse oder Weitergabe. Die
  [Yahoo-Bedingungen](https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html)
  lieferten erneut HTTP 999. Die konkrete Rechteabnahme bleibt **BLOCKED**.
- [Alpha-Vantage-Bedingungen](https://www.alphavantage.co/terms_of_service/)
  sehen persönliche, nicht kommerzielle Nutzung unter weiteren Bedingungen vor.
  Nutzung für Organisationen, Weitergabe und bestimmte berufliche Verbindungen
  sind getrennt zu prüfen; kein allgemeiner kommerzieller Freibrief.
- [Alpha-Vantage-Support](https://www.alphavantage.co/support/) nennt für viele
  kostenlose Datensätze 25 Requests pro Tag. Sonderfreigaben für verifizierte
  Projekte werden hier nicht unterstellt. Keine Registrierung vorgenommen.
- Die [offizielle Daily-Adjusted-Dokumentation](https://www.alphavantage.co/documentation/#dailyadj)
  kennzeichnet den Endpunkt als Premium und beschreibt rohe OHLCV, adjustierten
  Close sowie Actions. Das ist nicht ungeprüft dieselbe Preisbasis wie vollständig
  adjustierte yfinance-OHLCV. US- und XETRA-Beispiele sind dokumentiert; konkrete
  AAPL/MSFT/NVDA-Entitlements sowie SAP-/Allianz-XETRA-Symbole und Abdeckung sind
  mit dem Anbieter-Suchendpunkt erst noch zu bestätigen. Eine SAP-ADR ersetzt
  SAP.DE nicht. Kein kostenpflichtiger Zugriff aktiviert, kein Tarif gebucht.

`DailyProvider` beschreibt die Adaptergrenze; yfinance bleibt die einzige
implementierte Tageskursquelle. Die aktuelle Receipt akzeptiert bewusst nur
diesen Provider. Ein Alternativadapter benötigt eine belegte Preissemantik,
Rechteprüfung und gegebenenfalls ein neues Kohortenprotokoll. Weder historische
noch verzögerte Kurse erhalten eine garantierte Echtzeitkennzeichnung.

## Datenverfügbarkeit und Featureberechnung

Das System verwendet tatsächliche UTC-Empfangszeiten und die konservative
Speicherbestätigung aus M4.2a. Nur Receipts, die spätestens bei D empfangen und
bestätigt gespeichert waren, sind auswählbar. Provider-Veröffentlichungszeiten
werden nicht aus Handelsdatum oder Schlusszeit erfunden. Die deklarierte
Verzögerung muss bekannt sein und zum konfigurierten Zugang passen.

Es gilt mindestens `max(900 Sekunden, deklarierte Verzögerung)` nach dem
kalenderabhängigen Schluss. Börsenlokale Handelsdaten bleiben erhalten.
Wochenenden, Feiertage und DST-/unterschiedliche US-/DE-Schlusszeiten bestimmen
die Sitzung und nächste Öffnung; feste UTC-Handelszeiten sind nicht eingebaut.
Nach Zielöffnung kein Nachholen. D kommt vom Server, nicht aus einem API-Upload.

Der bestehende Vertrag erkennt fehlende Sitzungen, veraltete Daten und nicht
endliche/unvollständige Features. Größere Providerverzögerungen verstärken den
Snapshot-Vertrag; die eingefrorenen Modellmodule müssen dafür nicht geändert
werden. Später beobachtete Revisionen gelangen nicht in frühere as-of-Features.
Kein Fill, keine Preisreparatur und kein Überschreiben von Referenzdateien.

Zusätzliche konservative Korrektur gegenüber M4.2a: Verschiedene Payloads oder
Herkünfte mit identischer Empfangszeit haben keine belegbare Reihenfolge.
`history()` meldet dann `ambiguous_observation`, statt einen zufälligen UUID-Wert
als zeitlich letzte Version zu interpretieren. Alle Beobachtungen bleiben erhalten.

## Forecast-Persistenz, Idempotenz und Wiederanlauf

Ein fachlicher Slot ist Protokollhash + Ticker + Featuresitzung. Beide Modelle
nutzen denselben D, Datenstand und dieselbe Receipt. Nach erfolgreicher atomarer
Speicherung dokumentiert ein append-only `current_pair_commit`-Ereignis die
tatsächliche Bestätigung. Ausführung und bestätigte Speicherung müssen vor der
Zielöffnung und innerhalb von 300 Sekunden nach D liegen.

Absturz vor dem Transaktionscommit: kein halbes Paar. Absturz danach und vor
Bestätigung: keine Kohortenaufnahme, bis eine rechtzeitige explizite Wiederholung
dieselben gespeicherten Originale bestätigt. Spätere Bestätigung wird
`late_unconfirmed`; keine Rückdatierung und keine erneute Berechnung des Slots.
Ein erfolgreicher Slot erzeugt bei Wiederholung keine weiteren Forecasts, auch
nicht nach einer späteren Kursrevision. Scheitert der zweite Partner, werden
beide Vorhersagen verworfen. Keine nachträgliche Ergänzung nach Zielöffnung.

Persistenz bleibt in `si_models`, `si_forecasts`, `si_outcomes`, `si_backtests`,
`si_jobs` und den vorhandenen v4-Tabellen. Neue Auditarten in `si_market_runs`:
Versuche, Zyklen, Paarbestätigungen, Abnahme, Outcome-Konflikte und -Korrekturen.
Es ist keine weitere Schemaänderung erforderlich. SQLite ist praktisch geprüft;
PostgreSQL-Laufzeit ohne isolierte Testinstanz bleibt **BLOCKED**.

## Sicherheits- und Aktivierungsvoraussetzungen

Standardwerte:

| Variable | Standard / Bedeutung |
|---|---|
| `SI_CURRENT_ENABLED` | `false`, operative Current-Erzeugung gesperrt |
| `SI_CURRENT_ACCEPTANCE_ID` | leer; expliziter lokaler Abnahmebeleg |
| `SI_CURRENT_AUTO_REFRESH` | `false`, kein Scheduler-Thread |
| `SI_CURRENT_INTERVAL_SECONDS` | 900, zulässig 60–86400 |
| `SI_CURRENT_MAX_CYCLES` | 24, höchstens 288 je Prozessstart |
| `SI_CURRENT_SESSION_ATTEMPTS` | 3, höchstens drei Versuche je Sitzung |

Zusätzlich benötigt: `SI_ALLOW_MUTATIONS=true`, freigegebene lokale Artefakte
über `SI_RESEARCH_TRUST_LOCAL_ARTIFACTS`, deren vorhandener Root, ausdrücklich
migrierter Marktdatenspeicher sowie sämtliche M4.2a-Rechte-/Verzögerungsparameter.
Ein bloßes Setzen von `SI_CURRENT_ENABLED=true` reicht nicht aus.

`verify` prüft gespeicherte Providerdaten für alle fünf Titel und beide Modelle.
Es speichert einen getrennten Validierungsbericht in `si_backtests`, keine
Forecast-Kohorte und keinen T0. Fixtures können technisch geprüft werden, reichen
aber nicht zur echten Aktivierung. Der Bericht wird nicht als normaler Backtest
in der vorhandenen Liste dargestellt.

Erst `accept --confirm-e2e` mit echter Validierungs-ID und einer nicht geheimen
lokalen Nachweisreferenz für manuell geprüfte API-/Browser-Ergebnisse erzeugt den
unveränderlichen Abnahmebeleg. Er bindet Protokoll, Rechte-Nachweisreferenz und
deklarierte Verzögerung. Die ID muss anschließend bewusst lokal konfiguriert
werden; weder `accept` noch ein Webaufruf aktiviert den Scheduler automatisch.
Die Betreiberbestätigung ist kein automatischer Rechtsnachweis. Schreibrechte an
Code, Konfiguration, Datenbank und vertrauenswürdigen Artefakten bleiben die
Vertrauensgrenze. Änderungen am Zugang oder an seiner Semantik neu abnehmen.

## Jobverwaltung und Scheduler

API- und Scheduler-Jobs verwenden den vorhandenen `Jobs`-Executor mit einem
Worker. `CurrentScheduler` verwendet den begrenzten Lebenszyklus von
`NewsScheduler`; beide Timer teilen dieselbe Jobausführung. Keine zusätzliche
Queue, Cron-Infrastruktur oder parallele Modell-Worker. Der Newsbetrieb bleibt
unverändert konfigurierbar. Bei belegtem Worker wird später erneut geprüft.

Eine DB-Lease `research:current-pipeline` verhindert über API-/CLI-/Prozessgrenzen
gleichzeitige Current-Läufe. Die Ingestion behält ihre gesonderte Provider-Lease,
Tagesbudget, Timeout, Backoff und persistenten Rate-Limit-Cooldown. Der Scheduler
plant nur offene, noch nicht erfolgreich bearbeitete Slots. Endliche Zyklen und
persistente Sitzungsversuche begrenzen Wiederholungen; kein verspätetes Backfill.
Nach hartem Prozessabbruch keine automatische Lease-Übernahme: Eigentümerprozess
prüfen und nur den konkreten verwaisten Eintrag kontrolliert freigeben.

Der CLI-Befehl `run` arbeitet synchron und protokolliert seine Versuche/Zyklen.
API/Scheduler besitzen zusätzlich `si_jobs`-Historie. Abgelehnte Current-Jobs
werden als fehlgeschlagen angezeigt; teilweise erfolgreiche Läufe als Teilerfolg.
Die CLI liefert bei Blockade/Teilerfolg Exitcode 1. Ein Leerlauf des Schedulers
ist keine Behauptung erfolgreich erzeugter Prognosen.

## Outcomes und Revisionskonflikte

Ein Outcome benötigt einen zuvor bestätigten Forecast, abgeschlossene
Zielsitzung plus Verzögerung und eine tatsächlich danach empfangene, bestätigte
Receipt. Das gesamte relevante ursprüngliche Eingangsfenster muss im neuen
Kursstand nachprüfbar sein. OHLCV-Präfixhash und ursprüngliche Revisionslinks
einschließlich Actions werden geprüft. Keine Mischung inkompatibler Vintages.

Gespeichert werden Forecast-ID, Zielsession, Feature-/Zielschlusskurse, Richtung,
tatsächliche Empfangs-/Beobachtungszeiten, verwendete Zielkursrevision,
Receipt/Quellhash und `prediction_correct`. Forecasts bleiben unverändert.
Wiederholte identische Ergebnisse erzeugen keine weiteren Outcomes. Spätere
kompatible Zielkurskorrekturen erhalten separate Auditdokumente, ohne das erste
akzeptierte Label zu überschreiben. Geänderte historische Preis-/Actions-Basis
blockiert die Ergebnisberechnung ausdrücklich als `outcome_revision`.

Für offene Outcomes wird das Abruffenster nach Möglichkeit erweitert (maximal
733 Tage). Ein sehr alter ungelöster Fall bleibt nachvollziehbar blockiert und
verhindert nicht alle zukünftigen aktuellen Abrufe. Kein Löschen des alten Falls.
API und Statistik verbergen Outcomes, deren Ziel-/Beobachtungs-/Berechnungszeit
noch in der Zukunft liegt.

## Prospektive Evaluation und Oberfläche

Das eingefrorene JSON bleibt byteidentisch, SHA256
`9d9aaf888b02e09206c9d7a83c10e9b53da351296ffd8c40d3ee2c400e32a272`.
T0 wird aus dem ersten bestätigten echten Paar nach Freeze/Abnahme abgeleitet.
Fixtures, Validierungsvorhersagen, Replays, kontrafaktische oder verspätete
Vorhersagen sind ausgeschlossen. **Im tatsächlichen Projektbestand ist T0
weiterhin nicht gestartet.** Simulierte Kohorten in Unit-Tests ändern das nicht.

Berichtet werden n, gereifte Paare, fehlende Outcomes, Klassenverteilung,
kalenderbasierte Abdeckung einschließlich ausgefallener Sitzungen, getrennte
LR-/RF-Metriken und alle fixierten Titel. Accuracy, Balanced Accuracy, ROC-AUC,
Brier und weitere vorhandene Metriken/Kalibrierung verwenden die bestehende
Implementierung und festen Trainingsbaselines. Fehlende/undefinierte AUC bleibt
null. Bei n=0 werden keine Scores erfunden. ROC/AUC und andere Ein-Klassen-
Grenzfälle sind keine Leistungsbestätigung.

Vor 250 gereiften Paaren je Titel/Modell, insgesamt 1.250 je Modell, zwölf Monaten,
90 % Abdeckung und den Klassenmindestzahlen steht **Insufficient Evidence**.
Deskriptive Anzeigen verwenden erste akzeptierte Labels; bekannte Korrekturen
und divergierende gepaarte Labels sperren die automatische Bereitschaft zur
Hauptauswertung. Eine spätere ausdrückliche versionierte Hauptauswertung samt
vorgesehenem Block-Bootstrap und Korrekturprüfung bleibt offen. Keine laufende
Optimierung, optionale Siegerwahl, unabhängige Freigabe oder Profitabilitätsaussage.

Die bestehende Oberfläche zeigt einen kleinen Current-Statusbereich im Dashboard
und in der Aktienanalyse: Quelle, echte Empfangs-/Bestätigungszeit, Datenqualität,
Stale-Status, letzte Prognose, verfügbare Outcomes und Kohortenzahlen. Fixtures
werden ausdrücklich markiert; alte Preisdiagramme bleiben historische Diagramme.
Die neue geschützte Paarerzeugung ist vom bisherigen expliziten Artefakt-/Replay-
Formular getrennt. Kein Redesign und keine zusätzlichen Trading-Funktionen.

Neue API:

- `GET /api/research/current/status[?ticker=AAPL]`: Status, Scheduler und Statistik.
- `POST /api/forecasts/current`: vorhandene Mutationsauthentifizierung,
  JSON `{"tickers":["AAPL"],"refresh":false}`; keine clientseitigen Datenpfade,
  Features, Modellwahl, Abnahme oder rückdatierten Entscheidungszeiten.
- Bestehendes `GET /api/forecasts`: Ergebnisse plus separate Outcomes und
  Paarbestätigung. Kein zukünftiger Forecast-/Outcome-Zeitpunkt als aktueller Wert.

## Lokale Windows-Befehle

Zuerst nur Status/Migration, ohne Provideraufruf:

```powershell
Set-Location C:\Dev\KI\LAB\stock-ai
$env:SI_MODE = 'demo'  # SQLite-Speichermodus, kein Herkunftslabel
$env:SI_RUNTIME_DIR = 'C:/Dev/KI/LAB/stock-ai/.runtime/m42-current'
$env:SI_RESEARCH_ARTIFACT_DIR = 'C:/Dev/KI/LAB/stock-ai/.runtime/m4/reference-models'
.\.venv\Scripts\python.exe -m src.platform.market_data migrate
.\.venv\Scripts\python.exe -m src.platform.current_cli status
```

**Die folgenden Aktivierungsschritte erst nach tatsächlich erlaubtem Zugang:**
M4.2a-Variablen lokal in der ignorierten `.env` konfigurieren; keine Schlüssel in
Chat/Git, keine Lizenz durch Setzen eines Flags unterstellen. Verzögerung nur nach
Prüfung setzen. Freigegebene Artefakte vertrauen. Für die erste vollständige
Verifikation ein Fenster nach Schluss aller betroffenen Börsen und vor ihrer
nächsten Öffnung wählen, sodass je Titel dessen letzte komplette Sitzung vorliegt.

```powershell
# Voraussetzung: Rechte/Providerverzögerung geprüft und lokal konfiguriert.
$env:SI_RESEARCH_TRUST_LOCAL_ARTIFACTS = 'true'
$start = (Get-Date).AddDays(-400).ToString('yyyy-MM-dd')
$end = (Get-Date).ToString('yyyy-MM-dd')
.\.venv\Scripts\python.exe -m src.platform.market_data ingest --tickers AAPL MSFT NVDA SAP.DE ALV.DE --start $start --end $end
.\.venv\Scripts\python.exe -m src.platform.current_cli verify
# Validierungs-ID aus der Ausgabe übernehmen; API-/Browser-Prüfung dokumentieren.
.\.venv\Scripts\python.exe -m src.platform.current_cli accept --validation-id '<tatsächliche-Validierungs-ID>' --evidence-reference 'eigene-nicht-geheime-E2E-Pruefreferenz' --confirm-e2e
# Danach bewusst die ausgegebene echte ID konfigurieren, kein Beispielwert:
$env:SI_CURRENT_ACCEPTANCE_ID = '<ausgegebene-ID>'
$env:SI_CURRENT_ENABLED = 'true'
.\.venv\Scripts\python.exe -m src.platform.current_cli run --tickers AAPL
```

`verify`-Bericht ist lokal über `si_backtests` und die vorhandene Detail-API
`GET /api/backtests/<validation-id>` prüfbar. Der Current-Status zeigt die echten
Receipts bereits vor Aktivierung. Für das bestehende Frontend denselben Store
verwenden. Der manuelle echte E2E-Nachweis ist hier **nicht** ausgeführt worden.

Erst nach erfolgreicher Abnahme optional aktivieren:

```powershell
$env:SI_CURRENT_AUTO_REFRESH = 'true'
.\.venv\Scripts\python.exe -m src.platform.current_cli schedule --cycles 1
# Oder mit denselben freigegebenen Einstellungen im bestehenden Backend starten:
.\.venv\Scripts\python.exe -m uvicorn src.platform.api:app --host 127.0.0.1 --port 8000
```

Ein API-Backendworker oder ein separater freigegebener Writer-CLI-Prozess genügt.
Nicht mehrere lokale Instanzen/Scheduler für denselben Zugang konfigurieren.
Der begrenzte Scheduler stoppt nach seinen Zyklen; kein dauerhaftes Hosting wird
behauptet. Abschalten: `SI_CURRENT_AUTO_REFRESH=false`; Current-Schreiben zusätzlich
mit `SI_CURRENT_ENABLED=false` oder dem Leseprofil sperren und Prozess neu starten.

## Docker-/Portainer-Voraussetzungen

Keine Dockerdatei oder bestehende Serverkonfiguration wurde verändert.
`SI_ALLOW_MUTATIONS=false` sperrt neue POSTs und Scheduler auch bei versehentlich
gesetztem Auto-Flag. Die neuen Status-/Ergebnisabfragen bleiben lesbar. Der
vorhandene private HTTPS-/Proxy-/Token-/CORS-Schutz gilt unverändert.

Vor einem späteren Deployment: zulässigen Provider praktisch abnehmen, isolierte
PostgreSQL-Tests und M2-Runtime-Abnahme ausführen, Migration v4 kontrolliert mit
DDL-Rechten anwenden, persistente Runtime-Daten und Backups prüfen. Vertraute
Modellartefakte müssen im Container lesbar, Runtime-Verzeichnisse für den vorgesehenen
nicht privilegierten Writer schreibbar sein. Ein reiner Reader benötigt keine
Scheduleraktivierung. Noch keine unabhängige PostgreSQL-, Docker- oder Portainer-
Laufzeitfreigabe aus lokalen SQLite-/Fixturetests ableiten.

## Tatsächliche Tests und offene Punkte

| Prüfung | Tatsächlich ausgeführtes Ergebnis |
|---|---|
| Gesamte Backend-Regression | **215 bestanden, 3 übersprungen**, `backend-final.xml` / `backend-final.log`, 217,79 Sekunden; davon 36 neue Current-Tests |
| Frontend | **24 bestanden**, `frontend-final.log`; Herkunft, fehlende Daten, gesperrte Jobs, Outcomes und Korrekturhinweise |
| TypeScript / Produktion | **Bestanden**, `typescript-final.log` / `build-final.log` |
| Browser | **5 bestanden**, `browser-final.log`; eigener Server, frische SQLite-Datei, Edge; Current-Fixtures, historische Oberfläche, News, Fehlerzustand und echter eingefrorener LR-Replay |
| Eingefrorene LR-/RF-Inferenz | **Beide tatsächlichen Artefakte × fünf Instrumente**, zehn Forecasts und zehn spätere Outcomes mit synthetischen Kursen/virtueller Uhr; `frozen-fixture-result.json`, `frozen-fixture.log`; keine Provideranfragen, kein T0 |
| Idempotenz / Wiederanlauf | Unveränderte Forecasts bei Wiederholung; zehn originale Forecasts/Outcomes nach Wiederöffnung des SQLite-Stores identisch; Absturz-/Verspätungsfälle zusätzlich in Unit-Tests |
| FinBERT | Vorhandener realer CPU-Cachetest erfolgreich, zwei englische synthetische Texte, Deutsch übersprungen; Offline-Modus, kein Download/Live-News-Abruf |
| Originalpipeline | Original-CLI in isolierter Kopie erfolgreich: **6.312 Featurezeilen und alle numerischen Referenzmetriken identisch**, `pipeline-check.log` / `pipeline.log` |
| Lokale CLI | Migration im separaten Test-Store, Status und bewusst blockierter Current-Aufruf; keine automatische Aktivierung, `manual-*.json` |
| Docker-Leseprofil / API | Geschützte POSTs, unzulässiger Origin, zusätzliche Eingabefelder, fremde Ticker, Zukunfts-Outcomes und gesperrter Scheduler praktisch im FastAPI-Testclient geprüft |
| PostgreSQL | **BLOCKED**: drei opt-in Laufzeittests ohne isolierte freigegebene Instanz übersprungen. Keine produktive Datenbank kontaktiert. Vorhandene SQLAlchemy-/Transaktionsimplementierung wiederverwendet |
| Provider / echte Kohorte | **BLOCKED**, null echte Abrufe, keine echte Abnahme und keine echte prospektive Beobachtung. Positive Provider-/Kohortenbelege in Unit-Tests sind ausdrücklich simuliert und isoliert |
| Bestand / Secrets | SHA256-Abgleich: **138 übrige Bestandsdateien byteidentisch**, darunter `.env`, eingefrorenes Protokoll/Berichte, Forschungsdaten, drei fremde Dokumente und **9 lokale Modell-/Registrydateien**. Gitleaks 8.30.1: keine Funde in geprüften Projektänderungen |

Ein anfänglicher Test-Fixture-Importfehler sowie zwei Fälle mit identischen
virtuellen Beobachtungszeiten wurden während der Implementierung korrigiert;
der genannte Gesamtlauf ist der anschließende erfolgreiche Lauf. Beim ersten
Browserlauf bestanden vier Tests; der neue Test wartete nur fünf Sekunden auf
historische Detaildaten. Nach einer expliziten Wartebedingung für die Apple-
Detailansicht bestanden alle fünf. Keine Produktdaten oder Modellgewichte wurden
zur Behebung verändert. Die abschließend präzisierte Meldung für nicht bestätigte
Jobs wurde danach gezielt erneut geprüft: **2 Tests bestanden**, `message-final.log`.

Warnungen: eine vorhandene Starlette/httpx-DeprecationWarning und 36 sklearn-
Warnungen über Ein-Klassen-Samples in bewusst kleinen Statistik-Fixtures.
Diese Samples bleiben `Insufficient Evidence`; ROC-AUC ist dort null. Kein
Wegfiltern günstiger/ungünstiger Fälle oder Nachkalibrieren. Der separate
Fünf-Aktien-Lauf lädt die vorhandenen Modelle ausschließlich. Die vorhandene
Regression darf weiterhin eigene temporäre Testmodelle/PoC-Modelle erzeugen.

Reproduzierbare Prüfkommandos:

```powershell
$env:SI_TEST_FINBERT_CPU = '1'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:SI_TEST_POSTGRES = '0'
$env:SI_NEWS_AUTO_REFRESH = 'false'
$env:SI_CURRENT_AUTO_REFRESH = 'false'
# Nur falls der frühere statische Compose-Export lokal vorhanden ist:
$env:SI_TEST_COMPOSE_JSON = '.runtime/m32/compose.json'
.\.venv\Scripts\python.exe -m pytest -q
Set-Location frontend
node node_modules/vitest/vitest.mjs run --maxWorkers=1
node node_modules/typescript/bin/tsc -b
node node_modules/vite/bin/vite.js build
# Eigene localhost-/Runtime-Konfiguration der Prüfung (lokal, ignoriert):
node node_modules/@playwright/test/cli.js test --config=.runtime/m42b/playwright.config.ts
```

Die Browserkonfiguration benötigt die ausdrücklich vertrauenswürdige lokale
Registry und einen freien eigenen Testport. Der Compose-Test verwendet nur das
vorher statisch exportierte Modell; er startet keine Container. Alle Logs und
Hilfsskripte liegen ignoriert unter `.runtime/m42b/`; Modellgewichte, Datenbanken,
Schlüssel und simulierte Providerbelege werden nicht versioniert. Die drei
vorhandenen untracked Dokumente werden weiterhin nicht in diesen Commit aufgenommen.

Offen bleiben: tatsächliche Datenrechte/Abnahme, reale Verzögerungs-/Actions-
Semantik, PostgreSQL-Laufzeit und Docker-Runtime. Für große dauerhafte Historien
sind die bestehenden dokumentbasierten Store-Abfragen mit gezielten SQL-Filtern/
Indizes weiterzuentwickeln. Verwaiste Leases benötigen kontrollierte manuelle
Prüfung. Bekannte Labelkorrekturen benötigen eine getrennte versionierte
Hauptauswertung; sie verschwinden nicht automatisch aus der Prüfpflicht.

Empfohlene Reihenfolge: erlaubten Provider und echte E2E-Kette abnehmen, begrenzten
manuellen Betrieb prüfen, isolierte PostgreSQL- und Docker-Runtime-Abnahme,
anschließend privates Portainer-Deployment mit zunächst deaktivierter Automation.
Unabhängige Modellvalidierung bleibt unabhängig von der technischen Abnahme offen.
