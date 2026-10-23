# M4.2 – Current Market Data & Forecast Automation

Planungsstand 23.10.2026. **Noch keine operativen Funktionen implementiert oder aktiviert.**
Keine Provider-Anmeldung, kostenpflichtigen Zugänge, Serveränderungen oder Live-Abrufe
im Rahmen dieses Abschlusses. Das vor der retrospektiven Diagnose eingefrorene
[Evaluationsprotokoll v1](M4_2_PROSPECTIVE_EVALUATION_V1.md) ist die verbindliche
Grundlage. Seine Regeln werden durch die M4.1-Kennzahlen nicht verändert.

## Bestehende Komponenten und konkrete Wiederverwendung

| Bestehender Baustein | Wiederverwenden | Vor Automatisierung ergänzen |
|---|---|---|
| `src/ingestion.py`: `download_ticker`, `run_ingestion`, `save_raw_data` | vorhandene Yahoo-Symbolzuordnung, Tages-OHLCV, Corporate Actions und Raw-Layer | Rechteprüfung, kontrollierter Provider-Adapter, tatsächliche Request-/Response-Zeiten je Aufruf, eindeutige Snapshot-IDs, Timeout/Budget/Retry |
| `src/preprocessing.py`: `clean_price_frame` | Normalisierung lokaler Handelsdaten und OHLCV-Felder | ungültige/verworfene Originalzeilen auditieren; keine stillen Lücken oder Revisionen verlieren |
| `src/feature_engineering.py`: `FEATURE_COLUMNS`, `calculate_features` | exakt die sechs bestehenden Features | as-of-Präfix und Quellrevision explizit übergeben; Zielvariable nie als Inferenzfeature verwenden |
| `fact_stock_price`, `fact_stock_features` | vorhandene kuratierte Ansichten und Legacy-Pipeline erhalten | aktuelle Upserts überschreiben bei normalen Aufrufen frühere Werte; daher kein revisionssicherer Forecast-Quellenspeicher |
| `src/platform/market.py`: `MarketService`, `session_close`, `digest` | API-Datenformen, Börsenkalender und Datenhashes | Originalbeobachtung, aktuelle as-of-Daten und Revisionen; Cache je Datenversion statt nur Ticker |
| `forecast_contract.py`, `model_artifacts.py` | Kalender, Featurevertrag, Current-/Stale-Schutz, vertraute lokale Registry | diese eingefrorenen Module nicht ändern; neue Quellen über Adapter anbinden |
| `research_forecasts.py` | explizite Artefakte, DB-Leases, Fingerprints, atomare Forecast-/Modellpersistenz, Outcome-Prüfung | interne Anbindung an belegte Current-Snapshots und Kohortenreferenz; keine clientseitigen Datei-/Feature-Uploads |
| `Store`, bestehende `si_models`, `si_forecasts`, `si_outcomes`, `si_jobs` | SQLite/PostgreSQL, additive Tabellen, vorhandene Job-/Forecast-API | Beobachtungs-/Revisionsdokumente im selben Store und kontrollierte Migration |
| `Jobs` und Muster aus `NewsScheduler` | ein Worker, persistente Zustände, begrenzte Zyklen, kontrollierte Jobs | separater Kursjob mit Kalenderplanung und Budget; News-Schleife nicht zweckentfremden oder aktivieren |
| Aktienanalyse, Research-Panel, Model Analytics | bestehende Anzeige und Zugriffskontrolle | aktuelle Datenalter, Beobachtungszeiten, Forecast/Outcome, Quellenfehler; kein Redesign |

Wichtige Befunde: Der Ingestion-Zeitstempel wird aktuell **vor** dem gesamten Batch
erzeugt und gilt zugleich als Dateiname. Er ist weder individuelle Empfangszeit noch
erster tatsächlicher Beobachtungszeitpunkt. Zweite Aufrufe innerhalb derselben Sekunde
können denselben Namen erzeugen. `find_latest_raw_file` wählt nach Dateimtime; das ist
kein Point-in-Time-Nachweis. `created_at` der Legacy-Kurstabelle ist ebenfalls kein
Beleg für einen bestimmten Provider-Abruf oder dessen Revision. Diese Felder werden
nicht rückwirkend in glaubwürdige Beobachtungszeiten umgedeutet.

## Anbieter, Nutzungsbedingungen und Datenverzögerung

Quellenprüfung am 23.10.2026, ausschließlich offizielle Anbieter-/Projektseiten:

- [yfinance-Dokumentation](https://ranaroussi.github.io/yfinance/): Das vorhandene
  Projektwerkzeug ist nicht von Yahoo autorisiert/abgenommen; es verweist selbst auf
  private Nutzung und die gesonderten Daten-Nutzungsbedingungen. Die Softwarelizenz
  erteilt keine eigenen Marktdatenrechte.
- [Yahoo-Nutzungsbedingungen](https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html?.intl=us&.lang=en):
  Die erfasste offizielle Textpassage untersagt automatisierten Zugriff bzw.
  Datensammlung ohne ausdrückliche vorherige Erlaubnis. **Ein automatischer yfinance-Betrieb wird deshalb nicht allein
  aufgrund vorhandenen Codes oder eines privaten Netzwerks freigegeben.** Anwendbare
  regionale Bedingungen, erlaubter API-Zugang, Speicherung, Analysen und private
  Anzeige müssen für den konkreten Zugang belegt sein. Keine Umgehung von Sperren.
- [Yahoo-Börsenabdeckung und Verzögerungen](https://help.yahoo.com/kb/finance/article-exchanges-data-delays-sln2310.html):
  Die Tabelle nennt für XETRA `.DE` 15 Minuten. Das ist kein Nachweis finaler Tagesbars
  oder einer Verfügbarkeits-SLA; nach Schluss zusätzlich tatsächlich empfangene,
  vollständige Daten und die Quelle prüfen. Die konkrete Verzögerung pro Zugang
  muss vor Aktivierung festgehalten werden.
- [Alpha-Vantage-Dokumentation](https://www.alphavantage.co/documentation/#dailyadj):
  Offizielle Tages-API als möglicher alternativer Zugang; `TIME_SERIES_DAILY_ADJUSTED`
  ist als Premium gekennzeichnet. Ein unadjustierter kostenloser Daily-Endpunkt ist
  kein austauschbarer Ersatz für die adjustierten Modellfeatures. US-/XETRA-Symbole,
  tatsächliche Verfügbarkeit, Tagesbudget und Adjustierungssemantik je Titel prüfen.
- [Alpha-Vantage-Bedingungen](https://www.alphavantage.co/terms_of_service/):
  persönlicher, nichtkommerzieller Zugang unter den dortigen Bedingungen; konkrete
  Endpunkt-, Speicher- und Anzeigerechte separat prüfen. Kein Tarif wird aktiviert.

**M4.2-Eingangskriterium:** Ein dokumentierter erlaubter Zugangsweg für die nötigen
Tagesdaten. Zuerst bestehenden Adapter technisch weiterverwenden, soweit die Rechte
das erlauben; andernfalls nur den Provider-Zugriff austauschen, nicht die gesamte ETL.
Ein Häkchen für „privat“ ersetzt keine fehlende Berechtigung. API-Keys ausschließlich
lokal/über Umgebungsvariablen, keine Ausgabe in Jobs/URLs/Logs.

Die vollständige Yahoo-Bedingungsseite und die frühere API-Spezialbedingungen-Seite
waren beim direkten Abruf nicht zugänglich (HTTP 999). Die genannte Einschränkung
wurde in der indexierten offiziellen Yahoo-Textfassung geprüft; eine vollständige
Vertragsprüfung wird nicht behauptet. Daraus wird keine zusätzliche Freigabe abgeleitet. Es gab keine
authentifizierten Datenzugriffe und keine Prüfung eines Nutzervertrags.

## Datenfluss und additive Persistenz

`kalenderbasierter Job → erlaubter Provider → unveränderlicher Raw-Snapshot +
Beobachtungsmanifest → Qualitätsprüfung → versionierter as-of-Präfix → vorhandene
sechs Features → beide explizit eingefrorenen Modelle → persistente Current-Forecasts
→ spätere tatsächliche Zielbeobachtung → separates Outcome → bestehende API/UI`.

Beobachtungsdaten im **selben Store**, nicht in einer zweiten unabhängigen Datenbank.
Für den lokalen Start SQLite verwenden; PostgreSQL über die bestehende Engine und
explizite additive Migration absichern. Mögliche neue Dokumenttabellen `si_market_runs`,
`si_price_revisions`, `si_feature_snapshots` sind Planungsnamen, noch kein Schema.
Keine produktive Migration und keine Änderung historischer Fact-Daten in diesem Meilenstein.

Manifest je Request/Antwort: Run-/Request-ID, Provider, tatsächliches Symbol,
Ticker/Handelsplatz, UTC-Request-Start, Response-Empfang, erster Beobachtungszeitpunkt,
Speicherzeit, Status/Fehlerklasse, Hash/Referenz des Payloads, Parser-/Bibliotheksversion,
Adjustierungsmodus, bekannte Provider-Verzögerung und Rechte-/Konfigurationsversion.
Provider-Publikationszeit nur speichern, wenn tatsächlich geliefert; sonst `null`.
Wiederholte identische Antworten dürfen `first_observed_at` nicht nach vorne verschieben.

Revisionen je Provider/Ticker/lokalem Handelstag mit Inhaltshash und `observed_at`:
identische Inhalte idempotent, geänderte Inhalte neue Revision. Keine stille Ersetzung.
Legacy-Upserts bleiben eine bewusst aktualisierbare kuratierte Sicht, niemals der
alleinige Nachweis der Forecast-Datenbasis. Alte Raw-/Referenzsnapshots bleiben bestehen.

Der lokale Datenbankmodus und der Marktdatenstatus müssen auseinandergehalten werden:
SQLite kann echte Beobachtungen speichern. Dafür darf nicht einfach `SI_MODE=live`
gesetzt werden, denn dieser Modus wählt derzeit PostgreSQL. Eine explizite zukünftige
Quellenauswahl `reference`/`observed` mit Default `reference` und klarem API-Datenstatus
vorsehen. Banner/Ansichten müssen diese Quelle anzeigen, nicht aus dem DB-Modus
auf Live-Kurse schließen. Demo, veraltete Beobachtung und echte Current-Daten getrennt halten.

## Datenqualität, Features und Corporate Actions

- Erwartete Handelssitzungen, Zeitzone, Instrument-/Währungszuordnung, vollständiges
  OHLCV, Eindeutigkeit, endliche positive Preise und gültige High-/Low-Beziehungen prüfen.
- Fehlende Bars nicht mit Null oder künstlichen Kursen auffüllen. Volumen null ist
  erkennbar zu markieren; ein daraus undefiniertes `volume_change` blockiert Inferenz.
- Kalendervergleich und Vollständigkeit müssen **vor** einer Entscheidung erfolgen;
  bloßes Fehlen einer Fehlermeldung im Download ist kein Qualitätsnachweis.
- `calculate_features` auf den tatsächlich verfügbaren Präfix anwenden. Für vollständige
  sechs Features mindestens 31 zusammenhängende Sitzungen vorhalten; kein neues Feature,
  keine Imputation und keine Nutzung von `target_next_day_up` in der Inferenz.
- Historien späterer Downloads können durch Splits/Dividenden oder Anbieter-Korrekturen
  verändert sein. Die bei D gültige adjustierte Version archivieren. Zielkurs nur in
  kompatibler Preisbasis vergleichen; Konflikte sperren und explizit ausweisen.
- Das vorhandene Outcome-Hash-Gate nicht durch einen zusammengebauten alten Präfix
  mit beliebigem neuen Zielkurs aushebeln. Kompatibilität des Zielkurses muss zusätzlich
  durch die Quelle/Corporate-Action-Daten belegt sein. Keine automatische Umdeutung
  des adjustierten Modellziels in unadjustierte Renditen.

Die bestehenden Code-/Runtime-Fingerprints und Modellversionen bleiben unverändert.
Neue Ingestion-/Provenance-Adapter und Store-Dokumente anbinden, ohne die sechs
fingerprintgebundenen M4.0-Module umzuschreiben. Eine notwendige Modellvertragsänderung
würde eine neue Protokoll-/Kohortenversion erfordern, keine stille Kompatibilitätskorrektur.

## Zeitplanung und kontrollierte Ausführung

Für jeden Titel erwarteten Schluss aus seinem fixierten Kalender bestimmen.
Frühester Abruf nach Schluss plus `max(900 Sekunden, belegter Provider-Verzögerung)`;
der Status „Session geschlossen“ allein beweist keine Datenfinalität. Früher Schluss,
Wochenenden, DE-/US-Feiertage und unterschiedliche DST-Wochen getrennt behandeln.

Vorgesehener Start: bestehender einzelner Job-Worker mit optionalem begrenztem
Backend-Scheduler. Persistente Tages-/Requestbudgets, Laufgrenzen, ein gemeinsamer
Lease-Schlüssel für denselben Instrument-/Session-Lauf, höchstens drei Versuche mit
begrenztem Backoff; `Retry-After` innerhalb eines harten Zeit-/Budgetlimits respektieren.
Kein unbegrenztes Polling, keine Retries bei fehlenden Rechten/ungültigen Keys und
keine zweite Infrastruktur wie Celery/Redis. Planung und Ausführung trennen, damit
Tests mit kontrollierter Uhr statt echten Wartezyklen laufen.

Nach valider Speicherung gemeinsamen tatsächlichen Entscheidungszeitpunkt D für
LR und RF festschreiben. Beide auf denselben Snapshot anwenden und unveränderlich
speichern. Scheitert ein Partner, Original erhalten; die Sitzung zählt nicht als
vollständiges prospektives Paar und wird nicht rückwirkend ergänzt. Idempotenz und
abweichende Eingaben über die vorhandenen Fingerprints/DB-Transaktionen behandeln.

Nach Neustart abgeschlossene Jobs erkennen; unterbrochene Läufe auditieren und nur
noch vor erlaubter Zielöffnung mit neuem tatsächlichem D erneut beginnen. Keine
automatische Übernahme laufender Locks nach bloßem Zeitablauf. Backend muss laufen;
geschlossener Browser darf keinen Einfluss haben. Dauerhaftes Hosting/Autostart
gehört in die spätere Betriebsabnahme, kein Proxmox-/Docker-Eingriff in M4.2-Planung.

## Outcomes und bestehendes Dashboard

Nach Zielschluss, Provider-Verzögerung und tatsächlicher gültiger Beobachtung
`record_outcome` wiederverwenden. Eingefrorenen Forecast-Präfix, Zielhandelstag,
Preis-/Adjustierungsbasis, Beobachtungszeit und tatsächliche Richtung prüfen.
Ergebnis separat und idempotent speichern; Korrekturen als Revision mit Begründung.
Vorzeitig beobachtete/ungültige/fehlende Ergebnisse bleiben unsichtbar bzw. ausstehend.

Bestehendes Research-Panel um Datenalter, letzte erfolgreiche Kursbeobachtung,
Zielsitzung, kalibrierte Klassenwahrscheinlichkeit, tatsächliche Klasse und gegebenenfalls
Revisionskonflikt ergänzen. Im Dashboard eine kompakte bestehende Tabelle nutzen;
keine Kauf-/Verkaufssignale oder Neugestaltung. `research_only` bleibt bestehen.
Alle manuell auslösbaren Mutationen behalten Token-/Origin-/Loopback-Schutz;
Docker-Leseprofil weiter ohne Mutation oder ungeschützten Schedulerbetrieb.

## Konkrete Implementierungsreihenfolge und Abnahme

1. **M4.2a – Quellenvertrag:** zugelassener Zugang, fünf geprüfte Symbol-/Börsenmappings,
   Adjustierungssemantik, Verzögerung und Budget dokumentiert. Kleine ausdrücklich
   autorisierte Provider-Integration; ohne gültigen Zugang `BLOCKED`, keine Ersatzkurse.
2. **M4.2b – Beobachtungen und Revisionen:** vorhandenen Download/Parser kapseln,
   eindeutige Raw-Snapshots, echte Zeiten, Payloadhashes, additive Store-Migration und
   idempotente Revisionen. Wiederholung und konkurrierende Requests praktisch prüfen.
3. **M4.2c – Qualität und Current-Snapshot:** Kalender-/Lücken-/Feature-Prüfung,
   as-of-Auswahl, Provenance-Adapter und klare Datenstatusanzeige für SQLite sowie
   später isoliert PostgreSQL. Der August-Snapshot muss weiter als Current abgelehnt werden.
4. **M4.2d – Explizite Current-Forecasts:** bestehende Engine/API, beide fixierten
   Modelle, gemeinsames D, persistenter Snapshot, keine Modelländerung oder Optimierung.
   Erst nach einem vollständigen manuellen E2E-Lauf begrenzte Automatisierung einschalten.
5. **M4.2e – Begrenzte Automatisierung:** Kalendertrigger, Budget, Retry, Lease und
   Restart-Verhalten auf dem bestehenden Worker; Offline-Uhrtests und anschließend
   kleiner echter Lauf bei laufendem Backend, unabhängig vom Browser.
6. **M4.2f – Outcomes und Anzeige:** tatsächliche gereifte Zielkurse, getrennte
   Outcome-Revisionen, korrekte Dashboarddarstellung; Protokoll-v1-Kohorte starten,
   fehlende Termine protokollieren. Keine vorgezogene unabhängige Validierung behaupten.

Je Phase: Mock-/Fixture-Tests von echten API-Aufrufen trennen. Zusätzlich testen:
Timeout/429/403, leere Antworten, unreife/fehlende/duplizierte Bars, Nullvolumen,
Quellenrevision, Split/Dividende, DST/Feiertage/Frühschluss, veraltete Daten,
konkurrierende Jobs, unveränderliche Forecasts, verspätete Anfragen, nicht verfügbare
Outcomes, SQLite-Neustart und Authentifizierung. Regression der 6.312 Referenzzeilen,
alten Metriken, FinBERT, News, TypeScript, Build und Browser bleibt verpflichtend.
PostgreSQL ausschließlich mit explizit geeigneter isolierter Testinstanz.

M4.2 ist funktional abnehmbar nach mindestens einem tatsächlichen aktuellen,
zeitlich zulässigen Forecast-/Outcome-Zyklus plus Fehler-/Neustartnachweis. Das
Erreichen der prospektiven Mindeststichprobe dauert länger und bleibt ein separater
Forschungsnachweis. Keine Aufträge, Broker, Paper Trading oder Modellfreigabe.
