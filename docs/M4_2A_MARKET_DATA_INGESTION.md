# M4.2a – Current Market Data Ingestion & Point-in-Time Foundation

## Stand und Abgrenzung

Implementiert auf `codex/m4-2-current-market-data`, Ausgangspunkt `ca2a054`.
Die vorhandenen drei untracked Bestandsdokumente bleiben erhalten. Keine UI-
oder API-Umstellung, kein Scheduler, keine aktuellen Forecast-Jobs und keine
Änderung eingefrorener Modellartefakte. Alle Modelle bleiben `research_only`.
Der prospektive Plan v1 und sein noch nicht gestarteter T0 bleiben unverändert.

Dieser Auftrag umfasst bereits Persistenz, Revisionen und Feature-Vorbereitung,
die der ältere M4.2-Plan auf mehrere Unterstufen verteilte. Die kompatible Lösung
ergänzt ausschließlich den vorhandenen Store. Sie umgeht dessen aktualisierende
PoC-Fact-Upserts für diese neue, unveränderliche Beobachtungshistorie.

## Architektur und Wiederverwendung

```text
ausdrücklicher lokaler CLI-Aufruf
  -> Zugangsprüfung + globale DB-Sperre + reserviertes Abrufbudget
  -> YahooDailyProvider -> vorhandener yfinance-Tageskursaufruf
  -> gehashte DataFrame-Projektion mit originalen Börsenoffsets
  -> Rohzeilenprüfung -> vorhandenes clean_price_frame
  -> bestehende Store-/SQLAlchemy-Verbindung, additive Migration v4
  -> unveränderliche Beobachtung + gehashte Kursversionen + Commit-Bestätigung
  -> as-of-Auswahl einer vollständigen Providerhistorie
  -> optional bestehendes prepare_snapshot / dieselben sechs Features
```

`src/ingestion.py` erhält lediglich einen gemeinsamen `fetch_daily_history`-
Aufruf; der bestehende historische Download behält seine bisherigen Parameter.
Neue Module liegen in `src/platform/market_data{,_provider,_quality,_store}.py`.
`Settings` ergänzt standardmäßig deaktivierte Marktdatenparameter. Die
Store-Tabellenfabrik akzeptiert einen optionalen Metadatenkatalog, damit die
neuen Tabellen erst bei ausdrücklicher Migration entstehen. Es gibt keine
zweite Datenbankanbindung. Der normale Anwendungsstart aktiviert weder diese
Migration noch einen Abruf.

## Providerentscheidung und Nutzungsgrenzen

**Adapter:** vorhandenes yfinance; lokal geprüfte Version 1.7.0. Zielinstrumente
AAPL, MSFT, NVDA, SAP.DE, ALV.DE, Yahoo-Symbole wie bisher. US-Instrumente nutzen
den bestehenden XNYS-Kalender als Sitzungskalender, deutsche Instrumente XETR;
Zeitzonen America/New_York beziehungsweise Europe/Berlin. Die Zuordnung stammt
aus `DEFAULT_INSTRUMENTS`, nicht aus unkontrollierten Company-Profile-Abfragen.
Tatsächliche Abdeckung aller fünf Symbole ist noch praktisch abzunehmen.

| Quelle | Eignung und Grenze |
|---|---|
| yfinance / Yahoo | Vorhanden, tägliche OHLCV und Corporate Actions, historisch adjustierte Preise; inoffizieller Client, keine produktive SLA oder garantierten Echtzeitdaten. Providerrechte bleiben Voraussetzung. |
| Alpha Vantage | Offizielle API mit Schlüssel und Abruflimits; laut aktueller Dokumentation ist `TIME_SERIES_DAILY_ADJUSTED` Premium. Unadjustierte kostenlose Tagesdaten sind kein ungeprüfter Ersatz für die eingefrorene adjustierte Modellbasis. Kein Tarif aktiviert. |
| Vorhandene Referenzdateien | Reproduzierbare Regression, keine aktuellen Kurse und keine nachträglich belegbare historische Erstverfügbarkeit. Werden nicht als Live-Daten importiert. |

Primärquellen, geprüft am 23.10.2026:
[yfinance-Dokumentation](https://ranaroussi.github.io/yfinance/),
[Yahoo-Nutzungsbedingungen](https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html),
[Yahoo-Börsen und Verzögerungen](https://help.yahoo.com/kb/finance/article-exchanges-data-delays-sln2310.html),
[Alpha-Vantage-Dokumentation](https://www.alphavantage.co/documentation/#dailyadj).
Die yfinance-Dokumentation weist auf Forschungs-/Bildungszwecke und persönliche
Nutzung hin; daraus folgt keine pauschale Erlaubnis für automatisierten Abruf,
Speicherung oder Weiterverteilung. Die Yahoo-Seiten lieferten bei der aktuellen
Prüfung HTTP 999 beziehungsweise 429; eine abschließende Rechteprüfung ist somit
nicht erfolgt. Es wird weder eine API-Freigabe noch ein Verzögerungs-SLA behauptet.

**Echter Abruf: BLOCKED.** In diesem Workspace liegt kein belegter erlaubter
Providerzugang vor. Deshalb wurden **0 echte Provideraufrufe und 0 echte neue
Kursmeldungen** ausgeführt/gespeichert. Alle neuen Kursdaten in Tests sind
kontrollierte Fixtures. Die beiden Konfigurationsflags sind eine technische
Sperre; ihr Setzen erteilt keine Lizenz. Vor Aktivierung tatsächliche Berechtigung
für Zugriff, private lokale Speicherung und Analyse prüfen und eine nicht geheime
lokale Nachweisreferenz hinterlegen. Keine Umgehung von Sperren, kein Scraping
von Webseiten, keine Weiterveröffentlichung und keine kostenpflichtige Aktivierung.

## Datenvertrag und Zeiten

Eine `MarketReceipt` enthält UUID, Quelle `yfinance`, `source_kind`
(`provider` oder `fixture`), Ticker, angeforderten inklusiven Datumsbereich,
`request_started_at`, `received_at`, nullable `provider_published_at`, nullable
`declared_delay_seconds`, Bibliotheks-/Adapterversion, Adjustierungsmodus und
Payload. Instrument/Börse, Währung, Zeitzone und Kalender werden mitgespeichert.

- Request-Start wird unmittelbar vor dem Provideraufruf gemessen, Empfang direkt
  nach Rückgabe. Jeder einzelne Abruf erhält eigene Zeiten, keine vorab erzeugte
  Batchzeit als angebliche Erstbeobachtung.
- Alle Beobachtungs-/Systemzeiten sind UTC mit Zeitzone. `trade_date` bleibt
  börsenlokales Datum; deutsches Mitternachtsdatum wird nicht durch UTC-Konversion
  auf den Vortag verschoben. Mehrdeutige Tageszeitstempel werden abgelehnt.
- `provider_published_at` bleibt bei yfinance **null**. Handelsdatum, Session-Close,
  Request-Zeit und Veröffentlichungszeit sind verschiedene Größen. Der Client
  liefert keinen belastbaren Veröffentlichungszeitpunkt und keinen auswertbaren
  finalen HTTP-Status aus `history()`; insbesondere wird kein HTTP 200 erfunden.
- `first_seen_at` / `last_seen_at` einer Kursrevision werden als Minimum/Maximum
  ihrer unveränderlichen Empfangsereignisse abgeleitet, nicht nachträglich
  überschrieben. Eine as-of-Auswertung berücksichtigt dabei ausschließlich
  damals bestätigte Beobachtungen.
- Beobachtung und Kursrevisionen werden in einer Transaktion committed. Erst
  anschließend wird ein unveränderliches `receipt_commit`-Ereignis mit
  `available_at` erfasst. Dieser konservative Bestätigungszeitpunkt muss ebenfalls
  vor dem Entscheidungsstichtag liegen. Nach einem Absturz vor Bestätigung bleibt
  die Beobachtung gespeichert, aber für Features unveröffentlicht. Explizites
  Wiederholen derselben Receipt kann sie erst zum neuen Bestätigungszeitpunkt
  freischalten, ohne Rückdatierung.

Der SHA256-Payload ist eine kanonische JSON-Projektion des tatsächlich
zurückgegebenen yfinance-DataFrames, **kein Hash unbekannter HTTP-Wire-Bytes**.
Er umfasst Börsendatums-Offsets, OHLCV und verfügbare Actions. Nicht finite Werte
werden als null festgehalten und anschließend beanstandet. Es werden keine
Profile, Zugangsdaten oder URL-Crumbs gespeichert. Zusätzlich werden die gesamte
Receipt und jede normalisierte Kursversion gehasht. Die Hashes belegen Integrität,
keine Echtheitsgarantie gegen einen schreibberechtigten Datenbankadministrator.

## Persistenz, Revisionen und Point-in-Time

Additive Plattformmigration **v4** im selben Store:

| Tabelle | Unveränderlicher Inhalt |
|---|---|
| `si_market_runs` | Lauf-/Versuchsereignisse, vorab reserviertes Tagesbudget, sichere Fehlercodes, Rate-Limit-Pause, Commit-Bestätigungen |
| `si_market_observations` | Receipt einschließlich Payload, Prüfsummen, Instrument, Qualitätsbericht und Sitzung-/Revisionslinks |
| `si_price_revisions` | Hash-ID über Provider, Ticker, Handelsdatum, Adjustierungsmodus und OHLCV/Actions |

Alle Tabellen nutzen die vorhandene mode-bezogene Dokumenttabellenstruktur
(JSON-Payload, SQLAlchemy), SQLite für lokale Entwicklung und PostgreSQL im
bereits unterstützten `live`-Speichermodus. Vorhandene `dim_stock`,
`fact_stock_price`, `fact_stock_features`, Forecasts, Outcomes, Raw-Snapshots,
Berichte und Registry bleiben unangetastet. Keine DROP-/TRUNCATE-Operation,
kein Backfill mit erfundenen Erstbeobachtungen und kein Fact-Rebuild.
Die Migration ist wiederholbar und benötigt in PostgreSQL die vorhandene
Plattformschema-Initialisierung sowie explizite DDL-Rechte des Betreibers.
Sie ist von den bestehenden drei Deployment-SQL-Migrationen getrennt; deren
Reihenfolge und Prüfsummen ändern sich nicht.

Gleicher Receipt-Identifier mit gleichem Inhalt ist idempotent; abweichender
Inhalt unter derselben ID wird abgewiesen. Ein neuer echter Abruf erzeugt bewusst
ein neues Beobachtungsereignis, aber bei gleichen Kursen keine neuen Kursversionen.
Auch eine Folge A → B → A ist nachvollziehbar: zwei Inhaltsversionen, drei
Beobachtungen. Für as-of zählt die zuletzt **beobachtete** Version, nicht die
zuletzt neu angelegte Inhaltsversion. Verspätete Commits älterer Abrufe ändern
diese Reihenfolge nicht.

`history(ticker, as_of)` wählt die jüngste rechtzeitig empfangene und bestätigte
**vollständige Abrufhistorie**. Sie mischt keine verschiedenen Adjustierungsstände
und fällt nach einer neueren fehlerhaften Historie nicht still auf ältere gute
Daten zurück. Der konservative Entwurf ersetzt bei einem kürzeren neuen Abruf
keine fehlenden älteren Tage durch andere Vintages; für SMA200 ausreichend lange
Fenster abrufen. Rohdaten fehlerhafter Antworten bleiben in Quarantäne erhalten.

Eine heute geladene, nachträglich adjustierte Historie kann nicht als damals
verfügbar ausgegeben werden. PIT-Abfragen sind erst ab den tatsächlich
aufgezeichneten Beobachtungen möglich. Sie rekonstruieren keine unbekannte
Providerhistorie vor dem ersten Abruf.

## Qualität und Corporate Actions

Vor `clean_price_frame` werden Pflichtfelder, endliche positive OHLC-Preise,
High/Low-Konsistenz, ganzzahliges nicht negatives Volumen und nicht negative
Actions geprüft. Keine Volumenrundung zur Reparatur ungültiger Rohwerte.
Doppelte Sitzungen werden vollständig ausgeschlossen und beanstandet.
Wochenenden, Feiertage, ungültige Offsets und Daten außerhalb des Requests sind
Fehler. Fehlende Sitzungen werden über das gesamte angeforderte, bereits
abgeschlossene Fenster geprüft; keine künstlichen Kurse und kein Forward-Fill.

Die vorhandenen Kalender bestimmen die letzte abgeschlossene Sitzung mit
mindestens 900 Sekunden Sicherheitsabstand beziehungsweise größerer deklarierter
Providerverzögerung. Noch laufende Tageskerzen bleiben im Payload, werden aber
als `incomplete_session` von nutzbaren Bars ausgeschlossen. Nullvolumen,
bekannte Dividenden/Splits und veraltete Daten sind sichtbare Warnungen.
Extreme Actions und Schlusskurssprünge außerhalb 0,5–1,5 werden konservativ
quarantänisiert und benötigen manuelle Prüfung; keine automatische Preisreparatur.
Diese Heuristiken ersetzen keine vollständige Corporate-Action-Verifikation.

`quality.status=accepted` bedeutet strukturell gültig, nicht garantiert aktuell.
`quality.stale` muss zusätzlich beachtet werden. Absichtlich ältere Abfragefenster
können gültig und zugleich veraltet sein. Die spätere Feature-Vorbereitung
verwendet zusätzlich die bestehende strikte Stale-/Kalender-/Featurevalidierung.
Unbekannte Providerverzögerung und Fixtures sind für aktuelle Feature-Snapshots
gesperrt. Die numerische deklarierte Verzögerung ist eine Betreiberangabe,
kein aus dem Download automatisch bewiesenes SLA.

## Kontrollierter manueller Betrieb unter Windows

Im bestehenden venv, keine globale Installation erforderlich:

```powershell
Set-Location C:\Dev\KI\LAB\stock-ai
$env:SI_MODE = 'demo'  # vorhandener SQLite-Speichermodus, kein Herkunftslabel
$env:SI_RUNTIME_DIR = 'C:/Dev/KI/LAB/stock-ai/.runtime/market-data'
.\.venv\Scripts\python.exe -m src.platform.market_data status
.\.venv\Scripts\python.exe -m src.platform.market_data migrate
```

Migration und Status greifen nicht auf Yahoo zu. Mit dem separaten lokalen
Runtime-Pfad bleibt auch die bisherige Demo-SQLite-Datei unberührt. Zur Nutzung
derselben bisherigen lokalen Store-Datei kann deren Runtime-Pfad stattdessen
bewusst gewählt werden. `SI_MODE=live` ist für PostgreSQL vorgesehen, **nicht**
Voraussetzung für echte Providerkurse. Keine Verbindung zu einer produktiven
Datenbank nur zum Testen herstellen.

Erst **nach tatsächlich geklärtem erlaubtem Zugang** die eigenen nicht
versionierten `.env`-Werte ergänzen oder nur in dieser Shell setzen:

```powershell
$env:SI_MARKET_ENABLED = 'true'
$env:SI_MARKET_RIGHTS_ACCEPTED = 'true'
$env:SI_MARKET_RIGHTS_REFERENCE = 'lokale-nicht-geheime-referenz-zur-erlaubnis'
# Optional: SI_MARKET_DELAY_SECONDS nur nach Prüfung einer belastbaren Verzögerung.
$start = (Get-Date).AddDays(-10).ToString('yyyy-MM-dd')
$end = (Get-Date).AddDays(-1).ToString('yyyy-MM-dd')
.\.venv\Scripts\python.exe -m src.platform.market_data ingest --tickers AAPL --start $start --end $end
if ($LASTEXITCODE -ne 0) { throw 'Abruf fehlgeschlagen/teilweise/quarantänisiert: JSON-Bericht prüfen' }
$asof = [DateTimeOffset]::UtcNow.ToString('o')
.\.venv\Scripts\python.exe -m src.platform.market_data history --ticker AAPL --as-of $asof
.\.venv\Scripts\python.exe -m src.platform.market_data revisions --ticker AAPL --as-of $asof
```

Danach bei erfolgreicher Abnahme aller notwendigen Rechte und ausreichend Budget
das Fenster auf etwa 365 Kalendertage und die fünf Instrumente erweitern:

```powershell
$start = (Get-Date).AddDays(-365).ToString('yyyy-MM-dd')
.\.venv\Scripts\python.exe -m src.platform.market_data ingest --tickers AAPL MSFT NVDA SAP.DE ALV.DE --start $start --end $end
```

Inklusive Datumsbereiche sind auf 733 Kalendertage und Antworten auf 1000 Zeilen/
4 MiB Projektion begrenzt. Standard: 15 Sekunden History-Request-Timeout,
maximal drei Versuche je Instrument, exponentieller Backoff, mindestens drei
Sekunden zwischen logischen Abrufen und 20 reservierte Abrufe pro UTC-Tag.
Das ist ein **lokales Budget von SDK-History-Aufrufen**, kein garantierter
Yahoo-HTTP-Requestzähler: Cookies, Zeitzonenanfragen und interne SDK-Aufrufe
können zusätzliche HTTP-Aufrufe verursachen. Ebenso ist der SDK-Timeout kein
harter Gesamtlaufzeit-Timeout. Es gibt keinen eingerichteten Anbieter-SLA.
Rate Limit löst mindestens 300 Sekunden persistenten Cooldown aus und wird nicht
sofort wiederholt. Es werden keine nicht verfügbaren Retry-After-Header erfunden.

Eine globale Sperre in der vorhandenen `si_news_locks`-Tabelle mit separatem
Schlüssel `market:yfinance` verhindert parallele Marktdatenläufe im selben
Store/Mode. Laufende News-Jobs haben andere Schlüssel. Alle Kurs-CLI-Prozesse
für denselben Zugang müssen dieselbe DB verwenden; verschiedene Datenbanken
können kein gemeinsames kontoweites Budget erzwingen. Nach einem harten Absturz
wird eine Sperre bewusst nicht automatisch übernommen. Nur nach Prüfung, dass
kein Eigentümerprozess mehr läuft, den konkreten Sperrdatensatz durch einen
lokalen Administrator kontrolliert freigeben; keine allgemeinen DELETE-Befehle.
Normalerweise wird die Sperre im `finally` freigegeben.

Ausgabe ist JSON mit Lauf-ID, Status pro Ticker, Versuchen, Receipt-ID,
Herkunftskennzeichnung, neuen Revisionen und Qualitätsbericht. Teilerfolg,
Quarantäne oder vollständiger Fehler liefern Exitcode 1. Fehlender Zugang
liefert `access_blocked`, ohne Netzwerkkontakt. Keine unbegrenzten Schleifen,
kein öffentlicher Trigger und keine Scheduleraktivierung. SDK-Debuglogging
nicht einschalten; in eigenen Fehlerberichten stehen ausschließlich sichere Codes.

## Forecast-Vertrag und M4.2b

`MarketRepository.feature_snapshot(ticker, decision_at)` bereitet ausschließlich
die vorhandenen sechs Features über `prepare_snapshot` vor. Die bestätigte
Speicherzeit wird konservativ als `SourceProvenance.observed_at` verwendet;
tatsächliche Request-/Empfangszeiten und beide Hashes bleiben in der Receipt
nachvollziehbar. Ein neues Schema in den eingefrorenen Modellverträgen ist hierfür
nicht erforderlich. Die API/ResearchForecastEngine bleiben bisher angebunden;
es wird kein neuer Forecast geschrieben und kein Modell geladen oder trainiert.

**Empfehlung M4.2b:** zuerst erlaubten Zugang und echte fünf-Ticker-Abrufe samt
Verzögerung/Actions praktisch abnehmen, SQLite-/PostgreSQL-Persistenz testen,
danach die vorhandene ResearchForecastEngine ausdrücklich mit den neuen
as-of-Snapshots verbinden. Kalenderabhängige Ausführung nach Schluss und vor
nächster Öffnung, unveränderliche Forecast-/Outcome-Trennung, revidierbare
Ergebnisbeobachtungen und UI-Herkunftsstatus aus dem eingefrorenen prospektiven
Plan übernehmen. Erst dann optionale begrenzte Automatisierung. Keine Optimierung
anhand der retrospektiven Diagnostik; unabhängige Validierung bleibt offen.

## Validierung

Tatsächlich ausgeführt am **23.10.2026**, Windows / Python 3.14.7. Testlogs liegen
ausschließlich unter `.runtime/m42a/`; sie werden nicht als Providerdaten
versioniert. Der Commit zu diesem Bericht ist über `git log -1 --format=fuller`
auf dem genannten Feature-Branch nachvollziehbar; kein GitHub-Push.

| Prüfung | Ergebnis / Beleg |
|---|---|
| Gesamte Python-Regression | **179 bestanden, 3 übersprungen**, keine Fehler; `backend-final.xml`, `backend-final.log` |
| Neue Marktdatenregression nach letzter Speichersicherung | **53 bestanden, 1 übersprungen**; `market-final.xml`, `market-final.log`; Teilmenge der obigen Suite, nicht hinzuzählen |
| Reale FinBERT-CPU-Inferenz | **Bestanden**, vorhandener explizit aktivierter Offline-Cache-Test: zwei englische synthetische Texte analysiert, Deutsch übersprungen; kein Nachrichtenzugriff/Modelldownload |
| Frontend | **17 Tests bestanden**, `frontend.log` |
| TypeScript / Produktionsbuild | **Bestanden**, `typescript.log`, `build.log` |
| Browser | **4 Tests bestanden** mit Edge und eigenem localhost-Testserver/isolierter SQLite-Datei, `browser.log`; historische UI, News-Fixtures, Fehlerzustand und eingefrorenes LR-Artefakt im Research-Replay, keine neue Live-Datenanzeige behauptet |
| Ursprüngliche Datenpipeline | **Bestanden**, Original-CLI mit `--no-database` in separater Kopie; **6.312 Featurezeilen und alle ursprünglichen numerischen Modellmetriken identisch**, `pipeline-check.log` / `pipeline.log` |
| SQLite / manuelle CLI | **Praktisch getestet**: Status vor Migration, zweimalige additive Migration, Status danach, gesperrter Abruf mit Exitcode 1; `manual-*.json` |
| Revisionen / Neustart | **Praktisch mit Fixtures getestet**, neue Store-Verbindung nach Engine-Neustart, unveränderte Wiederholung, A→B→A, Identitätskonflikt, vollständige Vintage-Auswahl, keine zukünftigen Daten; neue Forecast-Tabelle bleibt leer |
| Absturz / verspätete Beobachtung | **Mit Fixtures getestet**: fehlende Commit-Bestätigung sperrt Daten; erneute Bestätigung wird nicht zurückdatiert; später gespeicherter älterer Abruf verdrängt keinen neueren Datenstand |
| PostgreSQL | **DDL statisch kompiliert**. **3 Laufzeittests BLOCKED/übersprungen**, weil keine ausdrücklich freigegebene isolierte PostgreSQL-Testdatenbank vorliegt; kein bestehender Server kontaktiert |
| Echte Providerkurse | **BLOCKED**, 0 Netzwerkabrufe, 0 echte neue Datensätze; fehlender Zugangsnachweis, keine Live-Abnahme |
| Sicherheit / Bestandserhalt | Gitleaks 8.30.1: **keine Funde** in den geprüften Projektänderungen; `integrity.json` bestätigt unveränderte übrige Bestandsdateien einschließlich `.env`, drei fremder Dokumente, ursprünglicher Daten/Berichte und **9 lokaler Modell-/Registrydateien** |

Gezielte Fixtureprüfungen decken die fünf Instrumente, UTC, Sommer-/Winteroffsets,
Börsenfeiertage, unterschiedliche Börsenschlüsse, fehlende Sitzungen,
ungültige/duplizierte OHLCV, Actions, noch laufende Kerzen, Stale-Status,
Timeout/Rate-Limit, persistentes Budget/Cooldown, parallele Importsperre,
Herkunftstrennung und Wiederanlauf ab. HTTP-Szenarien verwenden Mock-Responses;
diese sind **kein Nachweis einer erreichbaren oder lizenzierten Yahoo-Schnittstelle**.
Keine historische Modell-/Referenzdatei wurde verändert. Die bestehenden Tests
dürfen temporäre Testmodelle und den ursprünglichen PoC in isolierten Kopien
erzeugen; eingefrorene Forschungsmodelle wurden nicht neu trainiert/kalibriert.

Reproduzierbare Prüfkommandos (vorhandene Entwicklungsabhängigkeiten):

```powershell
$env:SI_TEST_FINBERT_CPU = '1'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:SI_TEST_POSTGRES = '0'
$env:SI_NEWS_AUTO_REFRESH = 'false'
# Optional nur bei bereits statisch exportiertem Compose-Modell:
$env:SI_TEST_COMPOSE_JSON = '.runtime/m32/compose.json'
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pytest tests/test_market_data.py -q
Set-Location frontend
node node_modules/vitest/vitest.mjs run --maxWorkers=1
node node_modules/typescript/bin/tsc -b
node node_modules/vite/bin/vite.js build
# Für Browserregression eigene freie localhost-Ports und isolierten Store wählen;
# Abschlusskonfiguration: frontend/.runtime/m42a/playwright.config.ts (lokal, ignoriert).
```

Der vorhandene Compose-Vertragstest prüft dabei nur das bereits aufgelöste
statische Modell, **keine Docker-Laufzeit**. Docker, Proxmox, produktive
Datenbanken und fremde laufende Dienste wurden nicht verändert.

Bekannte Einschränkungen: eine bestehende Starlette/httpx-DeprecationWarning,
SDK-interne Requests/Timeouts nicht vollständig steuerbar, keine belastbar
bekannte Yahoo-Verzögerung, manuelle statt umfassender Actions-Verifikation,
begrenzter Kalenderbereich der verwendeten Bibliotheksversion und derzeit
Dokumentabfragen über den vorhandenen Store. Vor dauerhaftem automatisiertem
Betrieb gezielte SQL-Filter/Indizes für große Beobachtungshistorien und einen
kontrollierten Umgang mit verwaisten Sperren ergänzen. Keine unabhängige
Modellvalidierung oder Produktivfreigabe aus diesen Infrastrukturtests ableiten.
