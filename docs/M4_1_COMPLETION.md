# M4.1 – Technischer Abschluss, retrospektive Diagnose und M4.2-Vorbereitung

Stand 23.10.2026. Repository `Basti070301/stock-forecasting-pipeline`, lokaler Branch
`codex/m4-ai-forecasting-engine`. Keine Veröffentlichung, kein Merge, kein Deployment.

## Git-Sicherung und Umfang

M4.0-Grundlage: `341fb6d388df84647812df398866ec293dcdc74f`.
Die 14 geprüften M4.1-Projektdateien wurden vor der Diagnose lokal in
**`e04191d6e2819fc5c5a5d972bf6bbe8b02de83eb`** gesichert:
`feat: implement persistent research forecasts and model evaluation`.
Arbeitsdateien waren identisch mit der vorherigen vollständigen Prüfung; zusätzlich
wurden der gesamte Git-Diff und tatsächliche Index-Blobs mit Gitleaks geprüft.

Der anschließende Abschlussstand ergänzt ausschließlich die genehmigte Kennzeichnung
`retrospective_diagnostic` in Report/UI/Tests, die Klarstellung der Modell-ECE-
Beschriftung, den neuen Diagnosebericht und die
Planungs-/Abschlussdokumente. Er wird in einem weiteren lokalen Abschlusscommit
festgehalten (Hash über `git log -1` und im abschließenden Chat-Bericht).
Keine neuen operativen Funktionen. Für genau die beiden neuen JSON-Berichte wird
Git-Zeilenendennormalisierung in `.gitattributes` deaktiviert, damit die vorab
festgehaltenen SHA256-Byteprüfsummen auch nach Commit/Checkout unverändert bleiben. Die vorhandenen unversionierten Dokumente
`M24_RUNTIME_ACCEPTANCE.md`, `M24_RUNTIME_PREFLIGHT.md` und
`M3_2_DEVELOPMENT_ASSESSMENT.md` bleiben erhalten und außerhalb dieser Commits.

## Tatsächlich ausgeführte retrospektive Diagnose

Die ausdrückliche Nutzerfreigabe bezieht sich auf 01.04.–25.08.2026 und bezeichnet
diesen zuvor betrachteten Zeitraum ausdrücklich nicht als unabhängigen Holdout.
Der vorhandene Evaluator `src/platform/holdout_evaluation.py` ruft unverändert
`model_training.evaluate_holdout` auf. Die fixierten Modelle wurden ausschließlich
geladen; kein Fit, Refitting, Kalibrieren, Threshold-Tuning oder Hyperparametervergleich
an diesen Daten. Beide Artefakte behalten ihre ursprünglichen Gewichte und Metadaten.

Bericht: `reports/research/m4_1_retrospective_diagnostic_v1.json`

Evaluations-ID: `eval-9a8dd3938ca930ab8cee59d078f2864a28d749a5b30e1bf2058d0ee1283ac767`.
Erstellt: `2026-10-23T17:58:43.995186+00:00`; Scope `retrospective_diagnostic`,
`research_only`, `forecast_enabled=false`, unabhängige Abnahme `blocked`.

Training einschließlich Label bis 31.12.2025, Kalibrierung einschließlich Label bis
31.03.2026, Diagnostik mit Featuretagen 01.04.–24.08.2026 und letzten Labels vom
25.08.2026. Für Features vom 25.08. fehlt der Zielkurs vom 26.08.; diese werden
nicht als beobachtetes Ergebnis erfunden. Der Split folgt exakt der bestehenden
zeitlich getrennten Definition beider Artefakte, kein rückwirkend neu gewählter Cutoff.

Beide Modelle: **501 identische Instrument-/Session-Beobachtungen auf 103 unterschiedlichen
Kalendertagen**. AAPL 100, MSFT 100, NVDA 100, SAP.DE 101, ALV.DE 100. Die vorhandene
Feature-Validierung schließt ALV.DE am 22.07.2026 wegen nicht endlichem `volume_change`
aus; die Diagnose hat diese Regeln weder verändert noch Werte imputiert. 282 positive,
219 nichtpositive Ziele. Gemeinsamer Holdout-Zeilenhash:
`c3fcc920d058b93e93dc183931bc512ee3dcc8c640d521c36bce45247e62e066`.

### Unveränderte Ergebnisse und Baselines

Klasse 1 = `Close(t+1) > Close(t)`, Klassifikation mit Schwelle 0,5. Höhere Accuracy
ist keine Rendite. Beim Brier Score ist ein kleinerer Wert besser.

| Metrik | LR | RF | Trainingsprävalenz | Trainingsmehrheit |
|---|---:|---:|---:|---:|
| Accuracy | 0.437126 | 0.439122 | 0.562874 | 0.562874 |
| Balanced Accuracy | 0.500000 | 0.501773 | 0.500000 | 0.500000 |
| Precision Klasse 1 | 0.000000 | 1.000000 | 0.562874 | 0.562874 |
| Recall Klasse 1 | 0.000000 | 0.003546 | 1.000000 | 1.000000 |
| F1 Klasse 1 | 0.000000 | 0.007067 | 0.720307 | 0.720307 |
| ROC-AUC | 0.548253 | 0.506833 | 0.500000 | 0.500000 |
| Brier Score | 0.256083 | 0.255426 | 0.246892 | 0.437126 |
| ECE (10 disjunkte Bins) | 0.102404 | 0.097339 | nicht separat berechnet | nicht separat berechnet |

Die Baselines sind ausschließlich aus Training festgelegt: positive Trainingsprävalenz
**0.5337951694439244**, Mehrheitsklasse 1. Beide haben deshalb dieselbe Klassifikation
und Accuracy **56,2874 %**, aber verschiedene Wahrscheinlichkeiten und Brier Scores.
Es ist keine nachträglich aus der Diagnose gewählte Mehrheitsklasse.

LR Accuracy **43,7126 %**, RF **43,9122 %**. Beide liegen hinter der festen
Trainingsmehrheit und beim Brier Score hinter der probabilistischen Trainingsprävalenz.
Der niedrigere Brier Score gegenüber der harten Wahrscheinlichkeit 1 der Mehrheitsbaseline
belegt keinen Vorteil gegenüber einer sinnvollen probabilistischen Dummy-Referenz.
Keine Wahl eines Produktionsgewinners; RF wird trotz minimal anderer Werte nicht bevorzugt.

Konfusionsmatrizen (Zeilen Ist 0/1, Spalten Prognose 0/1):

- LR: `[[219, 0], [282, 0]]` – alle Klassifikationen Klasse 0.
- RF: `[[219, 0], [281, 1]]` – genau eine als positiv klassifizierte Beobachtung.
- Beide Baselines: `[[0, 219], [0, 282]]`.

Die RF-Precision **1,0** beruht auf **einer einzigen positiven Klassifikation** und
ist kein belastbarer Qualitätsnachweis. LR Precision/Recall/F1 = 0 bei keiner positiven
Klassifikation; bestehende definierte Zero-Division-Konvention bleibt unverändert.

Kalibrierung: LR mittlere Wahrscheinlichkeit 0,460470 bei beobachtet 0,562874;
RF 0,465535 bei 0,562874. LR hat 501 Beobachtungen im Bin [0,4;0,5), RF dort 500
und eine in [0,5;0,6). Ein separater Bin mit n=1 liefert keine verlässliche Kalibrierung.
Alle Modellwahrscheinlichkeiten und Metriken bleiben unverändert, keine Nachkalibrierung.

### Bereits vorgesehene Unsicherheitsintervalle

Gepaarter zirkulärer Date-Block-Bootstrap, fünf Sitzungen je Block, alle Titel eines
Datums zusammen, 1.000 Wiederholungen, Seed 42. Deskriptive 95%-Intervalle:

| Kennzahl | LR | RF |
|---|---|---|
| Accuracy | [0.385820; 0.489005] | [0.386584; 0.493116] |
| Brier Score | [0.251762; 0.260357] | [0.251742; 0.259215] |
| Accuracy-Differenz zur Trainingsmehrheit | [-0.228361; -0.021991] | [-0.228009; -0.016089] |

Der automatische `low_sample`-Indikator bleibt unverändert `false`, weil 103 Datumsgruppen
über der ursprünglichen Schwelle 100 liegen. Das macht 501 korrelierte Aktienbeobachtungen
nicht zu 501 unabhängigen Marktperioden. Nur fünf ausgewählte Titel, ein kurzer Zeitraum,
Survivorship-/Adjustierungsgrenzen, Wiederverwendung früher betrachteter Daten und fehlende
Regime-/Mehrfachtestkorrektur begrenzen jede Interpretation. Keine unberechneten ROC-/F1-
Intervalle ergänzen, keine Signifikanz- oder Profitabilitätsbehauptung ableiten.

## Wissenschaftlicher Status und technische Abnahme

M4.1 ist **technisch abgeschlossen**: eingefrorene Modelle laden/inferieren,
Prognosen geschützt auslösen, unveränderlich und idempotent speichern, nach Neustart
lesen, in der bestehenden Oberfläche anzeigen und eine genehmigte retrospektive
Diagnose erstellen. Die endgültigen Abnahmetests stehen unten.

**Unabhängige Modellvalidierung bleibt ausdrücklich offen.** Der Diagnosezeitraum
überlappt frühere PoC-/Walk-Forward-Berichte. Ein aus finalem Training/Kalibrierung
ausgeschlossener Zeitraum ist hier kein projektweit unangetasteter Holdout.
Die Artefakte wurden zudem erst im Oktober erstellt; damalige operative Verfügbarkeit
wird nicht behauptet. Historische Replays bleiben kontrafaktisch gekennzeichnet.

Die unveränderten Artefaktmetadaten enthalten weiterhin den bei Erstellung gültigen
Evaluationsplan (`not_evaluated`). Aktuelle Diagnosen sind eigene versionierte,
prüfsummengebundene Berichte, keine nachträglich überschriebenen Modellmetadaten.
Auch der vorherige Blockadebericht `m4_1_holdout_preflight_v1.json` bleibt byteidentisch.

## Prospektiver Plan vor der Diagnose eingefroren

Protokoll: `reports/research/m4_2_prospective_protocol_v1.json`. Freeze `2026-10-23T17:58:02.583987+00:00`,
SHA256 `9d9aaf888b02e09206c9d7a83c10e9b53da351296ffd8c40d3ee2c400e32a272`.
Dieser Zeitpunkt liegt vor dem Evaluationsabschluss `2026-10-23T17:58:43.995186+00:00`.
Der Hash wurde zuvor protokolliert und danach erneut verifiziert; am JSON wurden
keine nachträglichen Änderungen aufgrund der Diagnose vorgenommen.

[Protokoll-Erläuterung](M4_2_PROSPECTIVE_EVALUATION_V1.md): beide unveränderten
Artefakte, fünf fixe Instrumente, sechs vorhandene Features, Schwelle 0,5, feste
Trainingsbaselines und Zieldefinition. T0 ist der erste künftig wirklich persistierte
Current-Forecast nach Daten-/Rechteabnahme; kein rückwirkender Start mit Replays.
Hauptauswertung erst nach mindestens 250 gereiften Paaren je Titel/Modell,
1.250 Beobachtungen je Modell, zwölf Monaten seit T0, 90 % Abdeckung und den
festgelegten Klassenmindestzahlen. Vorher nur deskriptive Betriebsinformationen.
Prognosen und spätere Outcomes bleiben strikt getrennt; neue Regeln benötigen eine
neue Kohorte/Protokollversion statt nachträglicher Anpassung historischer Einträge.

## Separates lokales Artefaktbackup

Backupordner: `.runtime\backups\m41-frozen-20261023T175522Z`.
ZIP: `research-models.zip`, 9 Dateien, 223312 Bytes,
SHA256 `0ef065c550a26b7bfe35d86ac367f5ff0b2689f170b0400a148e4cf8e1d85fb3`.
Nebenliegendes `manifest.json` bindet jede Datei an ihren Quell-SHA256. Sämtliche
ZIP-Inhalte wurden gegen diese Quellhashes zurückgelesen und verglichen.
Gewichte/Metadaten aller vorhandenen Artefaktordner plus Registry bleiben erhalten.
Das ist eine zusätzliche Kopie auf demselben lokalen Rechner, kein externes Backup.
ZIP, Manifest und Gewichte sind ignoriert und nicht Bestandteil eines Git-Commits.

## Tatsächlich ausgeführte Tests dieses Abschlusses

| Prüfung | Ergebnis / Nachweis |
|---|---|
| Gesamte Backend-Regression inklusive News und echter FinBERT-CPU-Inferenz | 126 bestanden, 2 PostgreSQL-Tests übersprungen; abschließender voller Lauf 145,13 s, `.runtime/m41-close/backend-final.xml` |
| Frontendtests | 17 bestanden; davon sechs Research-Tests, News-Fixtures ausdrücklich markiert |
| TypeScript | `tsc -b` bestanden |
| Produktionsbuild | Vite erfolgreich, einschließlich sichtbarer `retrospective_diagnostic`-Kennzeichnung |
| Originalpipeline | isolierte Kopie, 6.312 Featurezeilen; alle ursprünglichen numerischen Referenzmetriken identisch |
| Echte LR-/RF-Inferenz | beide vorhandenen Artefakte × fünf Titel = zehn HTTP-Forecasts, keine Modellattrappen |
| Reproduzierbarkeit | Wahrscheinlichkeiten, Daten-/Modellidentität und Artefakt-SHA identisch mit vorherigem unabhängigem HTTP-Lauf |
| Idempotenz / Neustart | zehn Wiederholungen ohne neue fachliche Forecasts; nach tatsächlichem Server-Prozessneustart zehn Originale exakt gleich |
| Browser | 4 bestanden (1,3 min), eigener Testserver; tatsächliche Diagnosekennzahlen und `retrospective_diagnostic` in Model Analytics geprüft |
| Wissenschaftliche Vorbedingungen | gleicher Zeilenhash für LR/RF, 501 Zeilen/Bin-Summen, Protokollhash und zeitliche Reihenfolge geprüft |
| Statische Prüfungen | Ruff und Git-Diff-Prüfung; Gitleaks auf geprüften Datei-/Index-Inhalten, keine Secrets |
| Bestandsintegrität | 130 Bestandsdateien byteidentisch; eingefrorene Gewichte/Metadaten, Registry, ursprüngliche Berichte, Referenzdaten und lokale `.env` erhalten |

Erster Backend-Gesamtlauf: 125 bestanden, zwei PostgreSQL-Tests übersprungen und
**ein temporärer Windows-Fehler `PermissionError [WinError 5]` beim Umbenennen eines
isolierten Testartefaktordners**. Der gezielte neue Roundtrip bestand anschließend
(1 Test). Die Ursache wird nicht als sicher diagnostiziert behauptet; die eingefrorenen
Modelle und deren Module wurden dafür nicht verändert. Der abschließende Gesamtlauf
ist separat in der Tabelle dokumentiert. Eine vorhandene Starlette/httpx-Deprecation-
Warnung bleibt bestehen; im Browser meldet exchange_calendars eine Performance-Warnung.

Lokale Nachweise: `.runtime/m41-close/backend-final.xml`, `rename-recheck.xml`,
`http/result.json`, `http/server.log`, `pipeline.log` und Browser-Screenshots unter
`frontend/test-results/`. Isolierte Testserver auf 18041/18042, keine fremden Server
oder produktiven Datenbanken. Reproduzierbare Backendtests verwenden Testmodelle
auf kleinen Teilmengen; daraus werden keine echten Diagnosekennzahlen abgeleitet.
Die eingefrorenen vollen Modelle werden im Diagnose-/HTTP-/Browser-Lauf nur geladen.
Die Legacy-Pipeline wurde ausschließlich in ihrer isolierten Regressionkopie ausgeführt.

Nicht praktisch geprüft: PostgreSQL ohne ausdrücklich isolierte Testinstanz; Docker/
Proxmox; echte Current-Marktdaten mit Originalbeobachtung und Zukunfts-Outcomes.
Keine Live-News-Abrufe, keine kostenpflichtigen APIs und keine Trading-Ausführung.
Die unabhängige prospektive Evaluation hat noch nicht begonnen.

## M4.2 – konkrete nächste Umsetzung

Der detaillierte [Implementierungsplan](M4_2_CURRENT_MARKET_DATA_PLAN.md) prüft zuerst
bestehende Ingestion, Parser, Features, Store, Jobs, Forecasts und Outcome-Struktur.
Kein neuer operativer Code wurde dafür angelegt. Reihenfolge:

1. Erlaubten Datenzugang, fünf tatsächliche Symbole, Adjustierungssemantik, Verzögerung
   und Budget belegen; vorhandenes yfinance allein ist keine Berechtigung zur Automatisierung.
2. Vorhandene Pipeline um echte Request-/Response-/Beobachtungszeiten und additive,
   unveränderliche Quellrevisionen im selben SQLite-/PostgreSQL-Store ergänzen.
3. Kalender-, Qualitäts-, as-of- und Feature-Prüfung; echte Beobachtung von historischen
   Demo-Kursen und vom Datenbankmodus unterscheiden.
4. Bestehende Research-Engine an den belegten Current-Snapshot anbinden, beide fixierten
   Modelle und gemeinsames D, ohne Gewichts-/Feature-/Threshold-Optimierung.
5. Erst nach manuellem echten E2E-Nachweis begrenzten kalenderbasierten Backend-Abruf
   aktivieren: Tagesbudget, Retry-Limit, Lease und kontrollierter Neustart.
6. Spätere gültige Zielkurse separat als Outcomes speichern, Revisions-/Corporate-Action-
   Konflikte offenlegen und Prognose/Ergebnis in bestehender Dashboardstruktur anzeigen.

Ein dokumentierter erlaubter Provider-Zugang ist Voraussetzung der Datenaktivierung.
Yahoo-Nutzungsbedingungen und yfinance-Hinweise sowie Alpha-Vantage-Dokumentation
wurden für den Plan geprüft; keine pauschale Genehmigung aus einem privaten Heimnetz
abgeleitet. Quellen und Einschränkungen stehen unmittelbar im M4.2-Plan.
