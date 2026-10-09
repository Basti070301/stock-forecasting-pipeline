# M3 – Technischer Abschlussbericht

Branch: `codex/m3-live-news-intelligence`, aufbauend auf `f8fac37`.
Vorhandene Commits und die uncommitteten M2.4-Dokumente sind erhalten.
Änderungen liegen lokal; kein GitHub-Push oder Merge.

**IMPLEMENTIERT:** Financial-News-Engine mit Finnhub, wiederverwendetem Alpha-
Vantage-Parser und ausdrücklich erlaubten RSS-/Atom-Feeds, Persistenz,
CPU-Batches, Aggregaten, API, bestehender React-Oberfläche und optionaler Automatik.

**GETESTET:** lokale SQLite-/API-/Provider-Mock-Integration, reale FinBERT-
CPU-Inferenz mit synthetischen Eingaben, Frontend/Browser und ursprüngliche
Pipeline-/Modellregressionen.

**BLOCKED:** echte Provider-Live-Abnahme. Kein Finnhub-/Alpha-Vantage-Key,
kein freigegebener RSS-Feed und keine bestätigten Nutzungsrechte sind lokal
konfiguriert. **Tatsächlich getestete Live-Nachrichtenabrufe: 0.**
PostgreSQL-Laufzeit bleibt ohne Testinstanz ungeprüft. Docker war ausdrücklich
nicht Gegenstand von M3.

## Architektur und Provider

`news_providers.py` normalisiert offizielle JSON-/RSS-Antworten in das
vorhandene `Article`-Modell. `NewsEngine` verwendet den vorhandenen Store
und dessen SQLite-/PostgreSQL-Anbindung. Kein zweites ETL-System.
Der bestehende FinBERT-Cache wird für CPU-Batchinferenz genutzt. Dieselbe
Engine bedient geschützte API-Jobs, manuelle CLI und begrenzten Scheduler.
React nutzt relative `/api`-Aufrufe und bestehende Panels/Styles.

Finnhub Company News ist primär: offizieller API-Adapter, eigene Registrierung
und privater Account nötig; bestätigte US-Zuordnungen für AAPL/MSFT/NVDA.
SAP.DE/ALV.DE erhalten keinen erfundenen Provider-/ADR-Ticker. Schema, Alias-
Mapping, RSS-Emittentenzuordnung und UI unterstützen diese Titel, ihre reale
Versorgung ist mangels freigegebener Quellen weiterhin offen.

Nutzungsbedingungen, Einschränkungen und Registrierung mit Primärquellen:
[live-news-intelligence.md](live-news-intelligence.md). Insbesondere private
Finnhub-Daten/Ableitungen nicht an Dritte weitergeben und vertragliche
Löschpflichten bei Zugangsende beachten. RSS-Sichtbarkeit allein genügt nicht
als Analyse-/Speicherlizenz; ungeprüfte SAP-/Allianz-Feeds werden nicht aktiviert.
Titel/Metadaten sind Standard, keine Vollartikel oder ungeprüften Kurzfassungen.

## Implementierte Funktionen

- Exakte Provider-Symbole, kontrollierte Unternehmensaliase und dokumentierte
  Emittentenfeed-Mappings; mehrere Firmen pro Meldung, Belege je Link.
- UTC-Veröffentlichung und unveränderliche tatsächliche erste Beobachtung;
  atomare News-/Revisions-/Linkupdates und idempotente Wiederholungen.
- Geschützte, begrenzte HTTP-Versuche mit Timeout/Backoff, 429/Cooldown,
  persistentem Tagesbudget, Größenlimit und strukturierten redigierten Fehlern.
- Datenbank-Lease mit Heartbeat gegen gleichzeitige CLI-/API-Import/Analysejobs.
- Englische FinBERT-Batches, drei Wahrscheinlichkeiten, dominierende Klasse,
  numerischer Score und Input-/Modellversionsbindung. Andere Sprachen ohne Ersatzscore.
- Konservative Deduplizierung einschließlich Cross-URL-Reposts; keine
  Zusammenfassung abweichender Zahlen oder gegensätzlicher Schlüsselwörter.
- Fenster 24 Stunden/7/30 Tage, Verteilung/Mittel/Verlauf/Newsanzahl und
  gespeicherte Berechnungsgrundlage mit IDs/Regelversion/Stichtag/Hash.
- Point-in-time-Lesen von beobachteten Revisionen und rechtzeitig vorhandenen
  Analysen; keine rückwirkende Verfügbarkeit verspätet erfasster Meldungen.
- Paginierte News-/Quellen-/Zeitraum-/Sentimentfilter, Provideraktualität,
  Aktien-Sentimentbereich und kompakte Dashboardübersicht ohne Redesign.
- Fehlende Zugänge, historische/veraltete Inhalte, Fixtures/Demo und echte
  Providerdaten klar gekennzeichnet. Standardstart erzeugt keine Demo-News.
- Opt-in Scheduler unabhängig vom Browser, maximal konfigurierte Zyklen,
  gemeinsame Job-Queue/Sperre und CLI mit Fehler-Exitcode.

## Neue Dateien (M3)

| Datei | Zweck |
|---|---|
| `src/platform/news_providers.py` | Finnhub/RSS/Alpha-Adapter, Mappings, bounded HTTP |
| `src/platform/news_engine.py` | Lease, Ingestion, Revisionen, Batches und Aggregate |
| `src/platform/news_scheduler.py` | Bestehender Jobexecutor plus begrenzter Scheduler/CLI |
| `sql/migrations/003_news_intelligence.sql` | Additive versionierte PostgreSQL-Newsmetadaten |
| `frontend/src/NewsIntelligence.tsx` | Erweiterung bestehender UI-Komponenten |
| `frontend/src/NewsIntelligence.test.tsx` | Anzeige/Filter/Status/Sentiment/Fehler-Tests |
| `frontend/e2e/news.spec.ts` | Markierte Browser-Fixtures; kein Live-Beleg |
| `tests/test_news_intelligence.py` | Reproduzierbare Provider-/Engine-/API-Tests |
| `tests/test_news_finbert_cpu.py` | Opt-in echte Offline-CPU-Batchprüfung |
| `docs/M3_IMPLEMENTATION_PLAN.md` | Bestandsaufnahme und Plan |
| `docs/live-news-intelligence.md` | Rechte, Konfiguration, Architektur, API und Betrieb |
| `docs/M3_REPORT.md` | Dieser Bericht |

## Geänderte Dateien

- `.env.example`: neue Variablen, Keys leer, Abruf/Automatik/Rechtebestätigung aus.
- `src/platform/config.py`: additive News-Einstellungen und Feedvalidierung.
- `src/platform/news.py`: vorhandener Alpha-Parser extrahiert/wiederverwendet,
  zusätzliche Metadaten, URL-Schutz, dominante Klasse, delegierte Batchanalyse.
- `src/platform/store.py`: vier additive Dokumenttabellen, modebezogenes Lesen,
  eingeschränkte News-Upserts und transaktionales append-only Schreiben.
- `src/platform/api.py`: neue GETs, kompatible Alt-GETs, kontrollierter Newsjob,
  vorhandener Schutz, optionaler Scheduler-Lifecycle und Konfigurationsstatus.
- `src/platform/market.py`: vorhandenes Radar verwendet deduplizierte Newsaggregate.
- `src/platform/maintenance.py`: neue Migration/v3-Marker bei explizitem Migrationslauf.
- `frontend/src/api.ts`: neue DTOs; `frontend/src/App.tsx`: vorhandene UI-Primitiven
  wiederverwendet, Newsansichten eingebunden, Teil-Erfolg klar bezeichnet.
- `tests/test_platform_postgres.py`: erwartete additive Migrationanzahl auf drei ergänzt.
- `README.md`, `docs/PROVIDERS.md`: Verweise und aktuelle Providerhinweise.

33 geschützte Bestandsdateien wurden per SHA256 unverändert bestätigt:
historische Raw-Daten, ursprüngliche Datenpipeline, Referenzmetriken,
Dockerfiles/Compose/Nginx, bestehende Migrationen 001/002, Styles,
Dependencylocks und Windows-Startskript. Keine bestehenden Kurs-/Feature-
oder Forschungsartefakte neu erzeugt/überschrieben. Browserbacktests schreiben
weiterhin nur eigene ignorierte Laufzeit-/Testartefakte.

## API und Datenbankschema

Neue GETs:

- `/api/news/feed`: Filter/Pagination, konsistenter `as_of`-Stichtag.
- `/api/news/providers`: Abdeckung, Zugang vorhanden (nur Boolean), letzter
  Erfolg/Fehler, Abrufpause, unterstützte Adapter und Schedulerstatus.
- `/api/news/summary`: Watchlist-Aggregate und letzte echte Meldungen.
- `/api/stocks/{ticker}/sentiment`: 24h/7d/30d und optionaler historischer Stichtag.

Bestehende `/api/news`, `/api/stocks/{ticker}/news`, geschützte
`POST /api/news/refresh` und `/api/news/analyze` bleiben erhalten/erweitert.
Vollständig fehlgeschlagene Refreshjobs gelten nicht als erfolgreiche Abrufe;
bei Teilerfolg bleiben Daten erhalten und der Status zeigt den Fehler.
Keine Schlüssel an das Frontend; Docker-Schreibsperre/Proxy-Authentifizierung unverändert.

Neue Tabellen: `si_news_revisions`, `si_provider_status`, `si_news_aggregates`,
`si_news_locks`, jeweils bestehendes Dokumentformat id/mode/created_at/payload.
Bestehende News/Links/Sentiments/Requests werden wiederverwendet. Migration
003 ist additiv; native Metadatenmigration ergänzt Marker v3. GETs schreiben
keine Aggregate und brauchen nur Leserollenrechte. Fachdatenschema bleibt unverändert.

## FinBERT-Nachweis

`ProsusAI/finbert`, Revision `4556d13015211d73dccd3fdd39d39232506f3e43`.
Die vollständige Backendprüfung aktivierte `SI_TEST_FINBERT_CPU=1` und
`HF_HUB_OFFLINE=1`. Zwei ausdrücklich synthetische englische Texte wurden
als Batch auf echter CPU/Torch/Transformers analysiert; ein deutscher Text
wurde übersprungen. Alle drei Modellwahrscheinlichkeiten waren gültig,
ihre Summe ungefähr 1, Score = positiv − negativ und Gerätekennung CPU.
Keine erneute Modellinitialisierung bei Wiederholung. Fixture-Meldungen
gingen nicht in reale Newsaggregate ein. Kein Modelldownload während dieser Tests.

## Tatsächliche Testergebnisse

| Prüfung | Ergebnis | Was sie belegt |
|---|---|---|
| Gesamte Python-Suite einschließlich CPU-Test | **56 bestanden, 2 übersprungen** | Originalpipeline/Modelle, neue Mock-Provider-/Store-/API-Tests, reale Inferenz |
| PostgreSQL-Integrationstests | **BLOCKED / 2 übersprungen** | Keine explizite Testinstanz; kein Erfolg behauptet |
| Frontend-Tests | **11 bestanden** | 4 bestehende + 7 neue Anzeige-/Filter-/Statusfälle |
| TypeScript | **Bestanden** | Neue DTOs/Komponenten konsistent |
| Vite-Produktionsbuild | **Bestanden** | Produktionsassets erfolgreich gebaut |
| Edge/Playwright | **3 bestanden** | 2 bestehende Regressionen + 1 neuer markierter Fixture-News-Test |
| News-Screenshot | **Visuell geprüft** | Bestehendes Design, Fixturekennzeichnung, Providerstatus/Sentiment sichtbar |
| Ruff | **Bestanden** | Neue/angepasste Backend- und Testmodule |
| Daten-/Docker-/Style-Integrität | **33 Dateien byteidentisch** | Bestand geschützt |
| Reale Finnhub-/Alpha-/RSS-Abrufe | **0; BLOCKED** | Kein gültiger konfigurierter Zugang |

Die bestehende Starlette/httpx-TestClient-DeprecationWarning bleibt vorhanden,
ohne Testfehler. Keine Live-Daten werden aus Fixturetests abgeleitet. Keine
Docker-/Serverprüfung oder Veröffentlichung ausgeführt.

Abschließender Gitleaks-Scan: 113 Git-Kandidatendateien geprüft; keine echten
Secrets gefunden. Ein Treffer stammt aus der vorhandenen M2.4-Anleitung:
`wrong-test-password` ist dort ausdrücklich ein falsches Kennwort für einen
401-Test. `.env`, virtuelle Umgebung, Modellcache und Laufzeitdaten bleiben
ignoriert. RSS-URLs mit Zugangsdaten als Queryparameter werden abgewiesen.

## Lokal starten und noch abnehmen

Ausführliche [Windows-Anleitung](live-news-intelligence.md#konfiguration-und-windows-schnellstart).
Ohne Providerzugang startet die App wie bisher auf 127.0.0.1:8000 und erklärt
den leeren Newszustand. Für echte News mit weiterhin historischen Kursen:
`SI_MODE=demo`, `SI_NEWS_ENABLED=true`, gewählten privaten Zugang/Rechte
in `.env` konfigurieren, FinBERT optional aktivieren und Frontend bauen.

```powershell
.\.venv\Scripts\python.exe -m src.platform.news_scheduler status
# Erst nach rechtmäßiger Konfiguration des eigenen Zugangs:
.\.venv\Scripts\python.exe -m src.platform.news_scheduler refresh --ticker MSFT
.\.venv\Scripts\python.exe -m uvicorn src.platform.api:app --host 127.0.0.1 --port 8000
```

Nächste Abnahme: einmaliger echter US-Providerabruf mit Original-URLs,
Beobachtungszeit, Mapping, CPU-Analyse und Persistenznachweis. Danach erlaubte
europäische Quellen und PostgreSQL prüfen. Größere Datenmengen brauchen
gezielte SQL-Filter/Indizes, Retention-/Lizenzabläufe und kalibrierte
Deduplizierung. Title-only-Sentiment/Spracherkennung bleiben begrenzt;
keine Kauf-/Verkaufssignale oder neue Forecastingmodelle wurden ergänzt.
