# M3.1 – Live News Activation, Integrationstest und lokale Git-Sicherung

Prüfstand: 09.10.2026. **Teilweise abgeschlossen; echte Live-Abnahme BLOCKED.**
Es wurden keine Provider-Nachrichten abgerufen. Die unten dokumentierten
Offline-Prüfungen ersetzen den erforderlichen Live-Durchlauf nicht.

## 1. Branch und gesicherter Commit

- Branch: `codex/m3-live-news-intelligence`.
- M3-Sicherungscommit: `5e8b928f483457f88fab6694b6e70b49c5bb98dc`.
- Nachricht: `feat: implement financial news intelligence with FinBERT`.
- Unveränderter Parent: `f8fac3739bffaacbad81db95e3b1c955f2c9d852`.
- 24 gezielt geprüfte/staged M3-Dateien; 2918 Ergänzungen, 123 Entfernungen.
- `main` bleibt `4a026d529ffcf1a1e710cf43e1b5b2193fcfcdb8`.
- Kein Push, Merge, Force-Push oder Umschreiben vorhandener Commits.

Der vollständige tracked Diff und die neuen M3-Module, Migration,
Komponenten, Tests und Dokumente wurden geprüft. 33 geschützte Bestandsdateien
stimmen weiterhin mit ihren SHA256-Werten vor M3 überein: historische Daten,
ursprüngliche Pipeline, Referenzmetriken, Docker-/Nginx-/Compose-Konfiguration,
Migrationen 001/002, CSS, Locks und Windows-Startskript.
In der neuen Migration 003 wurden vor dem Commit ausschließlich Leerzeichen
am Zeilenende entfernt; SQL-Semantik und bestehende Migrationen unverändert.

Die M3-Kandidaten sind UTF-8-Text ohne Binärdateien, insgesamt rund 261 kB.
Gitleaks 8.30.1 fand sowohl im Arbeitsdatei-Scan als auch im separaten Scan
der 24 tatsächlichen Index-Blobs **keine Secrets**. Die Index-Blobs wurden
mit den geprüften Dateien verglichen. `git diff --cached --check` erfolgreich.
Der umfassendere Repository-Dateiscan meldete nur das ausdrücklich falsche
`wrong-test-password` im vorhandenen M2.4-401-Testbeispiel; kein echtes Secret.

`.env`, `.venv`, `node_modules`, Modellcache und `.runtime` sind ignoriert.
Die vor M3.1 vorhandenen, nicht versionierten Dateien
`docs/M24_RUNTIME_PREFLIGHT.md` und `docs/M24_RUNTIME_ACCEPTANCE.md` bleiben
erhalten und gehören nicht zum M3-Commit. Der vorliegende M3.1-Bericht wird
separat lokal gesichert, damit er den bereits erzeugten M3-Hash nennen kann.

## 2. Provider und tatsächliche Konfiguration

Der vorhandene Finnhub-Adapter wird wiederverwendet:

| Eigenschaft | Geprüfter Stand |
|---|---|
| Methode/Endpunkt | `GET https://api.finnhub.io/api/v1/company-news` |
| Authentifizierung | Header `X-Finnhub-Token`; kein Token in URL oder Frontend |
| Parameter | `symbol`, `from`, `to` als UTC-Kalenderdaten `YYYY-MM-DD` |
| Aktueller Adapterzeitraum | Jetzt minus 30 Tage bis heute; maximal 250 Datensätze verarbeitet |
| Format | JSON-Liste; `id`, `headline`, `source`, `url`, `datetime`, `related`; optional `summary` |
| Nachrichten-ID | Interner SHA256 der kanonischen URL plus separat gespeicherte Provider-ID |
| Zeit | Unix-`datetime` → UTC; erste tatsächliche Beobachtung separat |
| Bestätigte technische Zuordnung | AAPL, MSFT, NVDA; vorrangig `related`/Provider-Ticker |
| Keine bestätigte Quelle | SAP.DE und ALV.DE; keine Live-Unterstützung behauptet |
| Richtiger Env-Name | **`SI_FINNHUB_KEY`**, nicht `FINNHUB_API_KEY` |
| Konfigurationsdatei | `C:\Dev\KI\LAB\stock-ai\.env`, vom Repository ignoriert |

Die offizielle [API-Dokumentation](https://finnhub.io/docs/api) und das
[offizielle OpenAPI-Schema](https://github.com/Finnhub-Stock-API/finnhub-go/blob/master/api/openapi.yaml)
beschreiben Company News für nordamerikanische Unternehmen. Der
[offizielle Python-Client](https://github.com/Finnhub-Stock-API/finnhub-python/blob/master/finnhub/client.py)
bestätigt Endpunkt und Parameter. Die
[Authentifizierungsdokumentation](https://finnhub.io/docs/api/websocket-trades)
bestätigt den verwendeten Header und HTTP 429 bei Quotenüberschreitung.

Die [Bedingungen](https://finnhub.io/terms-of-service) nennen zusätzlich zu
Tarifquoten eine Obergrenze von 30 Aufrufen/Sekunde. Die konkrete kostenlose
Kontingent-/Endpoint-Berechtigung des Nutzerkontos ist **noch nicht geprüft**.
Es wird keine unbestätigte Free-Tier-Quote als zugesicherter Zugang behandelt.
Die Engine begrenzt selbst auf standardmäßig 100 HTTP-Versuche/UTC-Tag,
mindestens 60 Sekunden zwischen Refreshläufen, drei begrenzte Transport-/5xx-
Versuche und 20 Sekunden Timeout. 429 pausiert ohne sofortigen Retry.
DB-Lease verhindert doppelte Importläufe; automatische Aktualisierung bleibt aus.

Beim redigierten Konfigurationscheck: kein Finnhub-Key, News deaktiviert,
keine Rechtebestätigung, keine Summaries, kein Scheduler, Kursmodus `demo`.
Die zunächst fehlende `.env` wurde aus `.env.example` angelegt, ohne echte
Zugangsdaten und mit deaktiviertem News-Abruf. Kein Konto oder Tarif angelegt.

## 3. Rechte und sichere Aktivierung

Finnhub beschränkt persönliche Pläne auf berechtigte individuelle Nutzung.
Daten und abgeleitete Ergebnisse dürfen ohne schriftliche Zustimmung nicht
mit Dritten geteilt werden. Die Bedingungen verleihen keine pauschalen Rechte
an Drittinhalten und verlangen Datenlöschung bei Ende des Datenabonnements.
Ein gültiger Key ist kein eigenständiger Rechtebeleg für Speicherung/Anzeige/
KI-Analyse. Die Berechtigung des konkreten Zugangs ist noch zu bestätigen.

Standardmäßig werden nur Titel und Metadaten gespeichert; keine Vollartikel
oder Provider-Summaries. `SI_NEWS_STORE_SUMMARIES=false` bleibt bestehen.
Private Nutzung auf dem eigenen Rechner; keine externe Veröffentlichung.

1. Unter [Finnhub registrieren](https://finnhub.io/register), nur einen
   kostenlosen persönlichen Zugang wählen; keine kostenpflichtige Buchung.
2. Key aus dem eigenen Finnhub-Dashboard ausschließlich im lokalen Editor in
   `C:\Dev\KI\LAB\stock-ai\.env` hinter `SI_FINNHUB_KEY=` eintragen.
3. Die folgenden Einstellungen in derselben Datei ergänzen/ändern. Die
   Rechtebestätigung nur auf `true` setzen, wenn der eigene Zugang Abruf,
   lokale Speicherung/Anzeige und Analyse der verwendeten Inhalte erlaubt.

```dotenv
SI_MODE=demo
SI_NEWS_PROVIDER=finnhub
SI_FINNHUB_KEY=HIER_NUR_LOKAL_DEN_EIGENEN_KEY_EINTRAGEN
SI_NEWS_ENABLED=true
SI_NEWS_RIGHTS_ACCEPTED=true
SI_NEWS_STORE_SUMMARIES=false
SI_NEWS_AUTO_REFRESH=false
SI_FINBERT_ENABLED=true
SI_FINBERT_DEVICE=-1
```

Der Key gehört weder in Chat, Screenshots, Git noch GitHub. Der Platzhalter
oben ist kein Schlüssel und muss lokal ersetzt werden. Eine abweichende
Umgebungsvariable in PowerShell hat Vorrang vor `.env`; keine Keys in
Terminalbefehle mit sichtbarer History setzen. Nach Eintragung nur bestätigen:
**„Schlüssel lokal eingetragen, Nutzungsrechte geprüft; AAPL-Test starten.“**
Vor dieser Bestätigung findet kein echter Integrationstest statt.

## 4. Live-Abrufstatus und tatsächliche Nachrichtenanzahl

| Messgröße dieses M3.1-Laufs | Ergebnis |
|---|---|
| Tatsächliche News-Provider-Requests | **0** |
| Provider/Aktie/Zeitraum live abgefragt | Nicht ausgeführt |
| HTTP-Status | Nicht gemessen |
| Reale Meldungen empfangen/neu gespeichert | **0 / 0** |
| Duplikate/Fehler eines echten Abrufs | Nicht gemessen |
| Reale Meldungen mit FinBERT analysiert | **0** |
| Live-News bis zum Browser geprüft | **BLOCKED** |

Keine leere Liste, Fixture oder HTTP-200-Simulation wird als erfolgreiche
Live-Integration bezeichnet. Primärer Blocker: fehlender API-Key plus
noch nicht bestätigte Berechtigungen. Keine echten ungültigen Keys ausprobiert.

## 5. FinBERT-Prüfung

Die vollständige Backend-Suite wurde mit `SI_TEST_FINBERT_CPU=1` und
`HF_HUB_OFFLINE=1` ausgeführt. Zwei synthetische englische Finanztexte wurden
als Batch mit **echtem Torch/Transformers auf CPU** klassifiziert, ein
deutscher Text übersprungen. Alle drei Wahrscheinlichkeiten in [0, 1], Summe
ungefähr 1 (Toleranz 0,001), Score = positiv minus negativ. Dominierende Klasse
und Verknüpfung zur Nachrichten-ID sind Bestandteil der Engine/Tests.

Modell: `ProsusAI/finbert`; unveränderte Revision:
`4556d13015211d73dccd3fdd39d39232506f3e43`.
Vorhandener Cache genutzt, keine Downloads; bei wiederholter Analyse weder
neue Inferenz für unveränderte Texte noch erneute Modellinitialisierung.
Die echten CPU-Ergebnisse wurden im temporären Teststore gespeichert.
Dies ist **kein** FinBERT-Nachweis an real abgerufenen Nachrichten.

## 6. Persistenz und API

Der bereits unterstützte lokale Kursmodus `demo` verwendet SQLite:
standardmäßig `.runtime/demo.sqlite`; echte News dürfen hier getrennt von
historischen Kursdaten gespeichert werden. Die Tests verwenden eigene
temporäre SQLite-Dateien, keine bestehenden Kurs-/Referenzdatenbanken.

Der vorhandene Mock-HTTP-Integrationstest prüft Parsing → Store → Analyse →
Providerstatus und öffnet danach denselben SQLite-Store mit einer neuen
Instanz. Nachricht, Score und erste Beobachtungszeit bleiben erhalten.
Weitere Tests prüfen wiederholte Inserts, unveränderte IDs/Beobachtungszeit,
atomare Revisionen, Mapping, rückwirkungsfreie Stichtage und Deduplizierung.
Mock-Klassifikation in diesem Test; echte CPU-Inferenz im separaten Test.

GETs `/api/news/feed`, `/api/news/providers`, `/api/news/summary`,
`/api/stocks/{ticker}/news` und `/api/stocks/{ticker}/sentiment` sind über
FastAPI-TestClient mit lokalen Testdaten geprüft. Filter, Pagination,
Parameterfehler, fehlende Konfiguration und kein Secret im Response getestet.
Bestehender Schutz für `POST /api/news/refresh` und `/api/news/analyze` bleibt.

PostgreSQL: **BLOCKED**, beide opt-in Tests übersprungen, weil keine ausdrücklich
bereitgestellte Testdatenbank vorliegt. Kein PostgreSQL-Dienst/Docker gestartet.
Neustartpersistenz echter Providerdaten und echter Backend-Prozessneustart
nach einem Live-Import bleiben offen; Store-Wiederöffnung mit Mocks ist geprüft.

## 7. Frontend und Fehlerzustände

Die vorhandene Windows-App wurde durch Playwright mit Uvicorn auf
`127.0.0.1:8000` gestartet, in Edge getestet und nach dem Lauf beendet.
Die bisherigen Historie-/Detail-/Filter-/Backtest-Regressionen bestehen.
Der neue News-Browsertest verwendet explizit markierte Browser-Fixtures:
Feedfilter, Quellenlink, Sentimentbereich und fehlender Zugang sichtbar;
kein synthetischer Datensatz wird als echte Live-Nachricht ausgegeben.

Fehlender Key, HTTP 401 (ungültiger Zugang), 429, 500/503 und Transporttimeout
sind mit Provider-Mocks getestet. Leere Nachrichten und UI/API-Fehlerzustände
sind offline geprüft. Diese Fehler wurden **nicht** absichtlich am echten
Provider ausgelöst. Reale AAPL-News in Feed/Detail/Dashboard bleiben offen.

## 8. Erneut ausgeführte Regressionen

| Prüfung | Tatsächliches Ergebnis |
|---|---|
| Gesamte Python-Suite, inklusive Pipeline/API/News/CPU | **56 bestanden, 2 übersprungen** |
| News-Regressionen innerhalb dieser Suite | **23 bestanden**; kein separat behaupteter zusätzlicher Lauf |
| PostgreSQL | 2 übersprungen; BLOCKED |
| Frontend / Vitest | **11 bestanden** |
| TypeScript `tsc -b` | Bestanden |
| Vite Produktionsbuild | Bestanden |
| Edge / Playwright | **3 bestanden** |
| Ruff | Bestanden |
| Secrets in 24 M3-Dateien / Index-Blobs | Keine Treffer |
| Schutz bestehender Daten/Konfiguration | 33 Dateien byteidentisch |

Ein erster Python-Teststart scheiterte an einem fehlenden Elternordner für
`--basetemp`. Nach Anlage von `.runtime/m31` lief die gesamte Suite erfolgreich
(48,41 Sekunden). Kein Produktfehler aus diesem Setupfehler abgeleitet.
Bestehende Starlette/httpx-DeprecationWarning bleibt ohne Testfehler.
Die automatische Freigabeprüfung war einmal wegen eines Nutzungslimits nicht
verfügbar; der Test wurde damals nicht ausgeführt. Nach Aufforderung zur
Fortsetzung funktionierte der reguläre Freigabeweg wieder.
JUnit-Nachweis `.runtime/m31/backend.xml`, redigierte Gitleaks-Berichte und
Manifeste bleiben lokal/ignoriert. Browser-Fixtures sind keine Live-Abnahme.

## 9. Fortsetzung und lokale Startanleitung

Nach Schlüssel-/Rechtebestätigung zuerst **nur AAPL**, keine automatische
Watchlist-Schleife. Vor dem Live-Test einen kleinen aktuellen Zeitraum,
z. B. sieben Tage, im vorhandenen Adapterpfad kontrolliert festlegen; dessen
aktueller Standard ist 30 Tage. HTTP-Metadaten/Counts ohne Authheader oder
Payload-Logs erfassen. Bei leerem Ergebnis keine vollständige Abnahme behaupten.

Anschließend denselben Abruf nach der mindestens 60-sekündigen Pause und nur
innerhalb des Abrufbudgets wiederholen. Unveränderte News-/Analyse-IDs,
`first_seen_at`, Modellwahrscheinlichkeiten und Aggregationsgrundlage prüfen.
Keine Hintergrundaktualisierung aktivieren. MSFT/NVDA erst nach AAPL-Erfolg.

Nach abgeschlossener kontrollierter Ingestion die bestehende App starten:

```powershell
Set-Location C:\Dev\KI\LAB\stock-ai
.\.venv\Scripts\python.exe -m uvicorn src.platform.api:app --host 127.0.0.1 --port 8000
```

Browser: `http://127.0.0.1:8000/#news`, `/#stock/AAPL`, `/#dashboard`.
Frontend-Produktionsbuild wurde bereits erstellt. Newsherkunft, Aktualität,
Original-URLs, Filter und analysierte/deduplizierte Anzahl mit Store/API
vergleichen. Danach echten Backend-Prozess neu starten und dieselben IDs,
Zuordnungen und Ergebnisse nachweisen. Diese Schritte sind **noch offen**.

## 10. Offene Probleme und nächster Meilenstein

- API-Key, Kontingent/Endpoint-Zugang und Inhaltsrechte noch nicht bestätigt.
- Noch kein vollständiger Echt-News → FinBERT → SQLite → API → Browser-Test.
- Kleinerer Ersttest-Zeitraum gegenüber dem Adapterstandard vor Abruf festlegen.
- Keine geeignete bestätigte Quelle für SAP.DE/ALV.DE.
- PostgreSQL-Laufzeit weiterhin nicht abgenommen.
- Titelanalyse und kurze Texte können unsichere Spracherkennung liefern;
  `unknown`/nicht englisch wird nicht künstlich klassifiziert.

**Empfehlung:** zuerst M3.1 mit einem zulässigen kostenlosen AAPL-Abruf,
CPU-Analyse und echtem Neustart-/Browsernachweis abschließen. Erst danach
weitere US-Aktien und freigegebene europäische Quellen prüfen. Docker/Proxmox,
Trading, neue Prognosemodelle und GitHub-Veröffentlichung bleiben außerhalb
dieses Prüflaufs.
