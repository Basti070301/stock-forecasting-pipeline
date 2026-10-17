# M4.0 – Forecast Foundation und versionierte Modellartefakte

Stand: 17.10.2026. Branch **`codex/m4-ai-forecasting-engine`**, Basis/HEAD
**`0eb1aa03ee6ce74f74f5553f5eb1b7024cd25b66`**. Änderungen lokal, noch nicht
committed. Kein Push, Merge, Docker-/Proxmox-Zugriff oder automatischer Datenabruf.

## 1. Umfang und Architektur

Die vorhandenen sechs technischen Features, sklearn-Modellbuilder,
LR-/Random-Forest-Hyperparameter, Kalibrierung und Forschungsmetriken werden
wiederverwendet. Die bestehende React-/FastAPI-Oberfläche bleibt unverändert.
M4.0 veröffentlicht keine operativen Forecasts und schreibt keine Prognosen
oder Modellfreigaben in die bestehende Datenbank.

| Datei | Änderung |
|---|---|
| `src/platform/forecast_contract.py` | Neuer Datenvertrag, Kalender-/OHLCV-/Feature-/Aktualitätsprüfung |
| `src/platform/model_training.py` | Finales Cutoff-Training, separate Holdout-Auswertungsschnittstelle, lokale CLI |
| `src/platform/model_artifacts.py` | Versionierte Artefakte, Registry, Prüfsummen, Kompatibilitätsprüfung und interne Forschungsinferenz |
| `src/platform/research.py` | Bestehenden Estimatorbuilder und Kalibrierungsbins als gemeinsame Funktionen herausgezogen; Backtest-Verhalten/Hyperparameter erhalten |
| `tests/test_forecast_foundation.py` | 43 neue gezielte Fälle |
| `frontend/e2e/platform.spec.ts` | Nur die erste Dashboard-Datenassertion wartet gezielt 15 s auf den gemessenen Kaltstart; übrige Assertions unverändert |
| `docs/LOCAL_SETUP.md`, `README.md` | M4-Verweis und überholte News-Einstiegshinweise korrigiert; vorhandene `.env` beim Setup nicht überschreiben |
| Dieser Bericht | Vertrag, Bedienung, tatsächliche Nachweise und Grenzen |

Keine neuen Abhängigkeiten, Datenbanktabellen, APIs oder Frontendkomponenten.
Die neue Registry ist ein Index lokaler Modellartefakte unter dem bereits
ignorierten Laufzeitverzeichnis, keine zweite Kurs-/News-/ETL-Datenarchitektur.
Die bekannte M2.4-Dokumentation und der M3.2-Bericht bleiben erhalten.

## 2. Forecast-Ziel und Datenvertrag

Ziel: **`Close(t+1) > Close(t)`**, binäre Richtung einer Aktie. `t` ist eine
abgeschlossene Börsensitzung; `t+1` die nächste Sitzung ihres Kalenders,
einschließlich Wochenenden, Feiertagen und verkürzten Handelstagen.

`FeatureSnapshot` definiert die validierte Eingabe; `ResearchPrediction`
ergänzt das isolierte Testergebnis:

| Feld | Bedeutung |
|---|---|
| `ticker`, `exchange`, `calendar` | Bestätigtes Instrument und Kalenderzuordnung des Modelluniversums |
| `feature_as_of` | Börsenlokales Kalenderdatum der Feature-Sitzung |
| `data_available_at` | Maximum aus Sitzungsschluss + konfigurierter Verzögerung und tatsächlicher deklarierter Quellenbeobachtung |
| `decision_at` | Referenzzeitpunkt, zu dem die Prognose sachlich gestellt wird |
| `prepared_at`, `generated_at` | Tatsächliche Eingabevorbereitung/Ergebnisberechnung, UTC |
| `target_session` | Nächste echte Handelssitzung; kein beliebiger nächster Kalendertag |
| `horizon`, `target_definition` | `next_session`; `Close(t+1) > Close(t)` |
| `model_id`, `model_version` | Konkrete Artefakt-ID und vollständiger Versionsfingerprint |
| `artifact_sha256` | Hash der geladenen Modellbytes |
| `contract_version`, `feature_version` | `next-session-close-direction-v1`, `pipeline-six-v1` |
| `data_version` | SHA256 des tatsächlich verwendeten normalisierten Kurspräfixes |
| `features` | Exakt sechs endliche technische Werte; keine News- oder Zukunftsfeatures |
| `source` | Quelle, historische/gespeicherte Herkunft, UTC-Beobachtung, Snapshot-Prüfsummen |
| `probability` | Kalibrierte Wahrscheinlichkeit der definierten Zielklasse; keine Rendite-/Gewinnwahrscheinlichkeit |
| `mode`, `data_status` | `current` oder ausdrücklich `historical_replay` |
| `status`, `forecast_enabled` | Immer `research_only`, immer `false` |
| `model_created_at`, `model_knowledge_available_at` | Tatsächliche Artefakterstellung und früheste deklarierte Daten-/Labelverfügbarkeit des Modells |
| `counterfactual_model_replay` | Wahr, wenn das tatsächlich später erzeugte Modell auf einen historischen Entscheidungszeitpunkt angewendet wird |

Alle Zeitpunkte sind zeitzonenbewusst und werden intern als UTC verglichen;
Handelstage sind lokale Kalenderdaten. Beispielsweise ist der 03.07.2026
in New York kein Handelstag, während XETR geöffnet ist. Early Close und
Datenverzögerung werden separat berücksichtigt.

**Close-to-Close ist keine Open-to-Close-Strategie:** Die Zielvariable enthält
auch die Bewegung zwischen Schlusskurs und nächster Eröffnung. Eine erst zur
nächsten Eröffnung ausführbare Strategie erfasst diesen Anteil nicht. Der
bestehende Backtest benennt diese Abweichung ausdrücklich. M4.0 macht keine
Aussage über Handelbarkeit oder mögliche Gewinne.

## 3. Verfügbarkeit und veraltete Daten

`latest_available_session` bestimmt aus Börsenkalender und Entscheidungszeit
die letzte Sitzung, deren Schlusskurs nach der deklarierten Datenverzögerung
verfügbar sein kann. Standardverzögerung: **900 Sekunden**. Dies ist eine
konservative konfigurierbare Annahme, keine vom Provider zugesicherte SLA.
Die zusätzlich deklarierte tatsächliche Quellenbeobachtung hat Vorrang.

Die Validierung:

1. verlangt vollständige, eindeutige OHLCV-Daten mit gültigen Preisen/Volumina;
2. akzeptiert nur echte, lückenlose Sitzungen des jeweiligen Kalenders;
3. verwendet keine nach dem Stichtag liegenden Kurszeilen;
4. verlangt vollständige technische Features ohne NaN/Inf oder zusätzliche Felder;
5. lehnt veraltete letzte Sitzungen ab, statt fehlende Sitzungen aufzufüllen;
6. verlangt Datenverfügbarkeit spätestens zum Entscheidungszeitpunkt;
7. weist historische Snapshot-Quellen im Modus `current` ab;
8. verbietet rückdatierte oder mehr als fünf Minuten alte aktuelle Inferenzanforderungen.

Der letzte Repository-Kurs vom **25.08.2026** ist daher keine Grundlage einer
aktuellen NVDA-Prognose vom **17.10.2026**. Ein entsprechender CLI-Test wurde
für beide Modelltypen mit `stale_data` abgewiesen.

Für einen Replay wird nicht nur das Feature-Datum geprüft: Trainings- und
Kalibrierungslabels sowie die deklarierte Quelle müssen vor `decision_at`
verfügbar sein. Eine Inferenz innerhalb des Kalibrierungszeitraums wird abgelehnt.

**Ein heute trainiertes Modell hat historisch nicht tatsächlich existiert.**
Ein isolierter August-Replay ist deshalb ausdrücklich kontrafaktisch markiert,
mit heutigem `generated_at`/`model_created_at` und historischem `decision_at`.
Es wird nicht behauptet, dass damals eine echte Prognose vorlag. Adjustierte
Archivkurse sind außerdem kein vollständiger Point-in-Time-Nachweis historischer
Corporate Actions oder des damaligen Aktienuniversums.

## 4. Finale Trainings- und Zeitgrenzen

`TrainingSpec` verlangt explizit `train_end < calibration_end < holdout_end`.
Der Seed ist fest 42. Pro Aktie mindestens 120 nutzbare Trainings- und
30 Kalibrierungssitzungen sowie insgesamt beide Zielklassen.

| Partition | Regel |
|---|---|
| Training | `label_end <= train_end` |
| Kalibrierung | `feature_session > train_end` und `label_end <= calibration_end` |
| Späterer unabhängiger Holdout | `feature_session > calibration_end` und `label_end <= holdout_end` |

Kurse werden **vor** Feature-/Labelerzeugung auf `calibration_end` begrenzt.
Der Holdout beeinflusst weder Preprocessing-Fit, Klassifikator noch Kalibrator.
Über eine Grenze reichende Labels werden verworfen. Technische Features dürfen
zulässige frühere Kurse als Anlaufhistorie verwenden.

Das finale Modell nutzt dieselben festen Estimatoren wie Walk-Forward:
vollständige Pipeline aus StandardScaler, Ticker-OneHotEncoder und LR bzw.
Random Forest (100 Bäume, Tiefe 5, mindestens 20 Samples/Leaf, Seed 42,
ein Worker). Kalibrierung: separate logistische Abbildung der Modell-Logits,
ausschließlich mit der Kalibrierungsmenge. Kein anschließendes Refit auf dem Holdout.

Der CLI-Quellmanifest-Hash beschreibt zur Nachvollziehbarkeit die vollständigen
Archivdateien. Trainings-/Kalibrierungs-/Eingabehashes beschreiben separat nur
die tatsächlich zulässigen Präfixe. Das Lesen/Hashen einer Quelldatei ist keine
Verwendung ihrer späteren Zeilen beim Fit.

## 5. Artefaktstruktur und Versionierung

Standardpfad: `.runtime/research-models/`, alternativ explizites `--root`.

```text
research-models/
  registry.json
  m4-logistic-<24 Zeichen des Versionshashs>/
    metadata.json
    model.joblib
  m4-random_forest-<24 Zeichen des Versionshashs>/
    metadata.json
    model.joblib
```

`model.joblib` enthält die vollständige gefittete sklearn-Pipeline, den
gefitteten Kalibrator, Eingabespalten, Formatkennung, Artefakt-ID und Version.
Format: `m4-final-calibrated-v1`; Typ: `final_research`. Die vorhandenen
`fold-*.joblib` haben dieses Format/Registry-Metadaten nicht und werden nicht
als finales Inferenzmodell übernommen. Ihre bestehende Backtest-Struktur bleibt erhalten.

`metadata.json` enthält Schema/Status, Zeiträume und Zeilen-/Sitzungszahlen,
Seed/Hyperparameter, Quelle und Datenhashes, Instrumente/Kalender,
Featurevertrag, Daten-/Codeversion, Erstellungs-/Verfügbarkeitszeit und die
vorbereitete Evaluationsplanung. Python, sklearn, NumPy, pandas, SciPy,
joblib und exchange_calendars werden mit exakten Versionen erfasst.

Die volle Modellversion ist ein SHA256-Fingerprint aus Trainingsspezifikation,
genutzten Datenhashes, Stammdaten, Feature-Schema, Quelle, Code- und
Libraryversionen. Die Erstellungsuhrzeit gehört nicht zum Fingerprint.
Die Registry speichert SHA256 für Modellbytes und Metadaten. Ein gleicher
Trainingslauf erhält dieselbe ID; bestehende Artefakte werden nicht überschrieben.
Unterbrochene Schreibvorgänge können `.building-*` oder eine `.writer-lock`
hinterlassen; kein automatisches Löschen oder Reparieren wissenschaftlicher Artefakte.

**Sicheres Laden:** Nur IDs, keine beliebigen Dateipfade/URLs; Registry und
Dateihashes, Schema, Modellart, gewünschte Version, Featurevertrag sowie
Python-/Library-/Codeversion vor dem Deserialisieren prüfen. Joblib benötigt
explizit `trusted=True` bzw. `--trust-local-artifacts`. Das bestätigt eine vom
Nutzer selbst kontrollierte lokale Quelle. Hashes sind keine Signatur und
schützen nicht vor einem Angreifer, der Registry und Modell gemeinsam ersetzen
kann. Keine fremden Downloads, Uploads oder automatisches Deserialisieren.

Die Kompatibilitätsprüfung ist bewusst strikt: Nach relevanten Code- oder
Libraryänderungen explizit neu trainieren; keine stillschweigende Migration
alter Pickles oder automatische Freigabe. Modellgewichte und Registry bleiben
ignoriert und gehören nicht in Git.

Nach der ausdrücklich erlaubten Deserialisierung werden zusätzlich der
tatsächliche LR-/RF-Estimatortyp, die Pipeline-Eingaben, Hyperparameter und
binären Zielklassen gegen die Metadaten geprüft. Ein inkompatibler
serialisierter Dummy-Klassifikator wird im automatisierten Test abgewiesen.

## 6. Unabhängige Evaluation vorbereiten

`evaluate_holdout(loaded, prices, instruments)` bietet die spätere explizite
Auswertung ohne `fit`, ohne Modellmutation und ohne Promotion. Der verwendete
Trainingspräfix muss zum registrierten Datenhash passen.

Die Schnittstelle verwendet die bestehenden `research.metrics` und
`calibration_bins`: Accuracy, Balanced Accuracy, Precision/Recall/F1,
ROC-AUC, Brier Score, Confusion Matrix und Kalibrierungsbins. Dummy-Referenzen
verwenden die **Trainingsprävalenz/Trainingsmehrheit**, keine aus dem Holdout
ausgewählte optimale Klasse. LR und RF können auf derselben festgelegten
Holdout-Definition getrennt geprüft werden. Walk-Forward-Ergebnisse bleiben
in der vorhandenen Forschungs-API; kein Fold wird automatisch finalisiert.

Standardmetadaten: Evaluation `not_evaluated`, Modell `research_only`,
`forecast_enabled=false`. Die Holdout-Schnittstelle wurde mit lokalen
Testausschnitten und echten sklearn-Modellen getestet. Eine neue umfassende
unabhängige Modellfreigabe/-bewertung der fünf Aktien wurde nicht durchgeführt.
Kein Holdout wurde zur Parameteroptimierung ausgewertet.

Der ursprüngliche PoC-Referenzbericht bleibt erhalten: Accuracy ca. **51,9 %**,
Mehrheitsreferenz **53,4 %**, ROC-AUC ca. **0,528**. Das ist kein Nachweis einer
zuverlässigen Kursprognose. Die neuen Artefakte werden dadurch nicht freigegeben.

## 7. Lokales Training und isolierter Inferenztest unter Windows

Keine neuen Pakete oder Netzwerkzugriffe erforderlich, wenn die bestehenden
Web-/ML-Abhängigkeiten installiert sind. PowerShell im Repository:

```powershell
.\.venv\Scripts\python.exe -m src.platform.model_training train `
  --model logistic `
  --train-end 2025-12-31 --calibration-end 2026-03-31 --holdout-end 2026-08-25

# Derselbe feste Plan, zweiter vorhandener Modelltyp:
.\.venv\Scripts\python.exe -m src.platform.model_training train `
  --model random_forest `
  --train-end 2025-12-31 --calibration-end 2026-03-31 --holdout-end 2026-08-25
```

Standarduniversum: AAPL, MSFT, NVDA, SAP.DE, ALV.DE. Mit `--tickers AAPL`
gezielt verkleinern. CLI benutzt die fixierten Repository-Snapshots;
keine Yahoo-/News-Abfragen und keine DB-Schreiboperationen.
Die Ausgabe nennt die Artefakt-ID. Diese für weitere Befehle übernehmen:

```powershell
$artifactId = 'm4-logistic-HIER_DIE_AUSGEGEBENE_ID_EINSETZEN'
.\.venv\Scripts\python.exe -m src.platform.model_training inspect --artifact-id $artifactId
.\.venv\Scripts\python.exe -m src.platform.model_training smoke `
  --artifact-id $artifactId --ticker AAPL `
  --as-of 2026-08-25T21:45:00Z --historical-replay --trust-local-artifacts
```

`--as-of` erfordert ausdrücklich `--historical-replay`. Ein normaler Smoke-Lauf
ohne Replay scheitert mit den Augustdaten heute verständlich an `stale_data`.
Es wird kein Ergebnis ins Dashboard geschrieben. Die gleiche interne Prüfung
ist für einen künftig explizit übergebenen aktuellen lokalen Kursbestand nutzbar;
M4.0 stellt dafür noch keinen laufenden Datenfeed oder Forecast-Service bereit.

Optionale spätere, ausdrücklich einmalige Holdout-Auswertung (kein Training):

```powershell
.\.venv\Scripts\python.exe -m src.platform.model_training evaluate-holdout `
  --artifact-id $artifactId --trust-local-artifacts
```

Ein benutzerdefiniertes `--root` muss bei allen Befehlen gleich angegeben
werden. Die CLI lädt nicht automatisch ein „neuestes“ Modell.

## 8. Tatsächlich ausgeführte Prüfungen

| Prüfung | Ergebnis |
|---|---|
| Gesamte Backend-Suite inkl. echter FinBERT-CPU-Inferenz | **99 bestanden, 2 PostgreSQL-Tests übersprungen**, 112,60 s |
| Neue M4-Fälle darin | **43 bestanden**; Kalender/Feiertage/Early Close, Daten-/Featurefehler, Zeitgrenzen, kein Holdout-Fit, unveränderte frühere Features, SHA256, falsche Modelle/Versionen/Trust/Estimatoren, LR/RF-Roundtrip/Reproduzierbarkeit, Research-Status |
| Frontend/Vitest | **11 bestanden** |
| TypeScript / Vite-Produktionsbuild | **Bestanden** |
| Ursprüngliche komplette CLI in isolierter Kopie | **Bestanden**, 6312 Featurezeilen; alle Referenzmetriken außer Erstellungszeit identisch |
| Echtes finales CLI-Training | **LR und RF, alle fünf Aktien**, feste Grenzen wie oben, Registry `.runtime/m4/reference-models` |
| Separate Prozess-/Replay-Nachweise | **8 erfolgreiche CLI-Inferenzen**, je zweimal LR/RF × AAPL/SAP.DE; Werte/IDs/Datenhash/Modellchecksum identisch. Beide aktuellen NVDA-Versuche korrekt als `stale_data` abgewiesen |
| Browser-Regression | **3 bestanden**, 55,4 s, separater Store/Port 18040; gezielte 15-s-Wartezeit nur für die erste Dashboard-Datenassertion, übrige Assertions mit Standardwartezeit. Zwei vorherige Läufe mit der ursprünglichen 5-s-Wartezeit hatten jeweils einen Dashboard-Timeout; siehe unten |
| PostgreSQL-Laufzeit | **BLOCKED**, keine ausdrücklich konfigurierte Testinstanz |
| Docker-/Portainer-Laufzeit, reale News-Abrufe | Nicht ausgeführt; außerhalb M4.0 |

Die Backend-Suite enthält die bisherigen 56 bestandenen Tests und die 43
M4-Fälle. Bestehende News-Tests verwenden Mocks; der reale FinBERT-Test
verwendet synthetische Texte, keinen Live-News-Zugang.
Die bestehende Starlette/httpx-DeprecationWarning bleibt ohne Fehler.

Aktuelle lokale Artefakt-IDs dieses Prüflaufs:

- LR: `m4-logistic-7a1a9e04acd8586ca379f2f1`
- RF: `m4-random_forest-9bd3dc5bccedd47a2eb9c07c`

Modell-SHA256:

- LR: `504c50dfeb2091bd87c6ad4045dd02e27a27e871f582962c4c9bed6944f3ad71`
- RF: `97d3e0c1ebed1b2d9be59b9ee6e16208de816d23446b50d3fa8338bcf0744614`

Die Inhalte der Browser-Assertions und die gesamte Frontendanwendung blieben
unverändert. Ein diagnostischer Zwischenlauf mit global 15 Sekunden war
erfolgreich; anschließend wurde diese globale Verlängerung entfernt und nur
die erste Dashboard-Datenassertion im vorhandenen Test gezielt auf 15 Sekunden
gesetzt. Der abschließende Lauf besteht mit den sonstigen Standardwartezeiten.
Der Diagnostiktrace belegt für die normale initiale
Radar-Anfrage **HTTP 200 nach 6,38 s**, Folgeanfragen unter einer Sekunde;
die 503-Antworten gehören ausschließlich zum absichtlichen Fehlerzustandstest.
Eine separate kalte API-Messung ergab 1,895 s, danach 0,158 s mit jeweils fünf
Aktien und HTTP 200. Die zwei vorherigen 5-s-Timeouts werden damit nicht als
erfolgreiche Standardläufe dargestellt. Die Ursache der unterschiedlichen
Latenz unter parallelen Dashboard-Anfragen ist nicht abschließend optimiert.
Das ist eine offene Test-/Kaltstartgrenze, kein für M4 vorgenommenes UI-Redesign.

JUnit-Nachweis `.runtime/m4/backend.xml`, Pipeline-Log und Modellartefakte
bleiben lokal/ignoriert. Reproduzierbarkeit bedeutet hier gleiche Eingaben,
gleiche Versionen und gleiche Modell-/Inferenzergebnisse; keine Zusage
binärgleicher Dateien zwischen unterschiedlichen Plattformen/Libraryversionen.

Bestandsschutz: 116 vorhandene Dateien vor Beginn erfasst. Ausschließlich
`research.py`, `README.md`, `LOCAL_SETUP.md` und die erste Wartezeit im
vorhandenen Browser-Test wurden gezielt geändert;
die übrigen **112 Dateien sind byteidentisch**, einschließlich Raw-Daten,
Referenzmetriken, ursprünglicher Pipeline, API/Frontend-Anwendung, SQL/Docker,
unversionierter M2.4-/M3.2-Dokumente und `.env`. Gitleaks prüft ausschließlich
die neun M4-Kandidatendateien; keine Modellbytes oder Secrets werden gestaged.

## 9. Bekannte Grenzen und Vorbereitung für M4.1

- `research_only` ist der einzige erzeugbare Modellstatus; kein Approval-
  Endpunkt, kein Produktionsmodell und keine automatische Modellwahl.
- Keine neuen Forecasts in SQLite/PostgreSQL, kein Dashboard-Publishing oder
  Outcome-Job. Die vorhandene Persistenz bleibt für M4.1 verfügbar.
- Keine News-Features im Modell; dafür fehlen genügend zeitkorrekt beobachtete
  historische Meldungen. M3.1-Live-Abnahme bleibt separat offen.
- Strenge lückenlose Kursprüfung kann unvollständige externe Datenbestände
  zurückweisen; keine versteckte Reparatur oder Auffüllung.
- Beobachtungszeit und Datenverzögerung sind ein expliziter Quellenvertrag,
  kein automatischer Nachweis von Provider-Latenz oder Point-in-Time-Preisen.
- Historische adjustierte Daten, festes Universum, keine Währungs-/Index-
  Mehrertragsvalidierung; Close-to-Close-Ziel nicht mit Handelsrendite verwechseln.
- Lokale Registry mit Schreibsperre ist keine Multiuser-Modellplattform.
- PostgreSQL-/Docker-Prüfungen bleiben offen, ohne diese Funktionen als
  erfolgreich getestet auszugeben.
- Die ursprüngliche 5-Sekunden-Wartezeit war beim ersten Dashboard-Laden
  auf dieser Umgebung zweimal zu knapp. Die gezielt korrigierte Datenassertion
  wartet jetzt 15 Sekunden; Kaltstartlatenz separat prüfen, keine UI-Optimierung behauptet.

**M4.1-Empfehlung:** Zunächst einen unveränderten Holdout-Plan und unabhängige
Evaluation der vorhandenen Modelltypen dokumentieren. Danach einen expliziten
geschützten Research-Forecast-Job mit idempotentem Schlüssel aus Modell,
Aktie, Horizont und Stichtag an die vorhandenen Forecast-/Outcome-Tabellen
anschließen. Aktuelle Daten nur mit bestätigtem Aktualitäts-/Quellenvertrag;
historische Replays sichtbar getrennt. Modellfreigabe bleibt ein eigener
nachvollziehbarer Vorgang; keine automatische Kauf-/Verkaufsentscheidung.
