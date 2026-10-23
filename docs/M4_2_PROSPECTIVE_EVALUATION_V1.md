# M4.2 – Prospektives Evaluationsprotokoll v1

Eingefrorener Forschungsplan, keine aktive Automatisierung und keine Modellfreigabe.
Dieses Dokument erläutert das maschinenlesbare Protokoll
`reports/research/m4_2_prospective_protocol_v1.json`. Dieses JSON bleibt unverändert.

Freeze: `2026-10-23T17:58:02.583987+00:00`; SHA256 `9d9aaf888b02e09206c9d7a83c10e9b53da351296ffd8c40d3ee2c400e32a272`.
Die retrospektive Diagnose wurde erst danach abgeschlossen: `2026-10-23T17:58:43.995186+00:00`.
Der Plan wurde vor Betrachtung dieser Kennzahlen geschrieben; er wird aus ihnen weder
optimiert noch nachträglich angepasst. Die Git-Sicherung der Dokumente folgt anschließend.

## Fixierte Modelle und Universum

| Modell | Artefakt | Gewichts-SHA256 |
|---|---|---|
| LR | `m4-logistic-7a1a9e04acd8586ca379f2f1` | `504c50dfeb2091bd87c6ad4045dd02e27a27e871f582962c4c9bed6944f3ad71` |
| RF | `m4-random_forest-9bd3dc5bccedd47a2eb9c07c` | `97d3e0c1ebed1b2d9be59b9ee6e16208de816d23446b50d3fa8338bcf0744614` |

Vollständige Modellversion, Metadaten-SHA, Code-Fingerprint und Laufzeitversionen stehen
im JSON. Beide Modelle werden parallel als getrennte Forschungsmodelle geführt.
Kein Modell wird aufgrund retrospektiver Kennzahlen ausgewählt, ersetzt oder neu kalibriert.
Bei Library-/Code-Inkompatibilität stoppen; keine Gewichte heimlich unter gleicher Version neu erzeugen.

Fixes Universum: **AAPL, MSFT, NVDA, SAP.DE, ALV.DE**. Kalender laut eingefrorenem
Modellvertrag: US-Titel `XNYS` / America/New_York; deutsche Titel `XETR` / Europe/Berlin.
Keine nachträgliche Entfernung schwacher oder nicht mehr verfügbarer Titel aus der Auswertung.
Ausfälle und fehlende Daten bleiben als solche im Nenner sichtbar.

## Start, Entscheidung und Ziel

**T0 ist noch nicht erreicht.** Er ist der erste künftig tatsächlich erzeugte und
dauerhaft gespeicherte Current-Forecast nach Protokoll-Freeze und nach Abnahme von
Datenrechten, Beobachtungszeitpunkten und Datenqualität in M4.2. Keine Datumsrücksetzung
auf April/August 2026 und kein Import historischer Replays in diese Kohorte.

Ziel: `Close(t+1) > Close(t)` für die unmittelbar nächste gültige Börsensitzung.
Es geht um adjustierte Schlusskurse in nachweislich kompatibler Preisbasis, wie bei
den bestehenden Modellen; keine Umdeutung in Handelsrendite oder Gewinnwahrscheinlichkeit.
Klasse 1 genau bei strengem Anstieg; unveränderte Klassifikationsschwelle **0,5**.
Alle sechs Features und ihre Einheiten bleiben unverändert.

Entscheidungszeit D: nach Börsenschluss der Featuresitzung plus mindestens
`max(900 Sekunden, belegter Provider-Verzögerung)` und erst nach tatsächlicher
Beobachtung, Validierung und Speicherung aller verwendeten Eingangsdaten.
`data_available_at <= D <= generated_at`; Speicherung vor Öffnung der Zielbörse.
Die Ausführung muss innerhalb von 300 Sekunden nach D erfolgen. Erneute verspätete
Anläufe bekommen einen tatsächlichen neuen Entscheidungszeitpunkt oder werden abgelehnt;
kein rückdatiertes Nachholen nach Öffnung der Zielsitzung.

US-/DE-Feiertage, vorzeitige Schlüsse, Sommerzeit und verschiedene DST-Wechselwochen
werden über die bereits verwendeten Börsenkalender behandelt. Keine festen UTC-Uhrzeiten.

## Daten- und Revisionsregeln

- Tatsächliche UTC-Zeiten für Request-Start, Response-Empfang, erste Beobachtung und
  dauerhafte Speicherung separat halten. Provider-Zeitstempel nur zusätzlich speichern.
  Ein späterer DB-Lesezeitpunkt ersetzt keine historische Beobachtung.
- Für einen Forecast nur Daten nutzen, deren konkrete Revision spätestens bei D
  verfügbar war; Feature-Stichtag und nächste Zielsitzung müssen dem Vertrag entsprechen.
- As-of-Kurspräfix, Featurewerte, Quelle, Adjustierungsmodus, Datenversion, Artefakt-
  und Metadatenprüfsummen vor Eintritt des Outcomes unveränderlich sichern.
- Provider-Korrekturen und Corporate Actions append-only protokollieren. Alte Daten,
  Forecasts und Labels nicht überschreiben. Fehlversuche ebenfalls auditieren.
- Bei unklarer Split-/Dividenden- oder Adjustierungsbasis Outcome sperren und den
  Konflikt ausweisen. Keine Richtung aus inkompatiblen Preisbasen berechnen.
  Die bestehende strikte Prüfung historischer Präfix-Hashes wird nicht umgangen.
- Kein synthetischer Ersatz für Lücken, keine nachträglich berechneten historischen
  Forecasts als prospektive Beobachtungen und keine unbemerkte Änderung des Universums.

## Baselines und Metriken

Feste **Trainingsprävalenz** pro Artefakt aus dessen Metadaten; derzeit für beide
`0.5337951694439244`. Kein Nachführen mit den neuen Labels. Zweite feste Baseline:
Trainingsmehrheitsklasse, hier Klasse 1 mit Wahrscheinlichkeit 1. Die Prävalenzbaseline
ist die probabilistische Vergleichsgröße; die deterministische Mehrheit hat eine andere
Brier-Interpretation und ersetzt sie nicht.

Primär: Brier Score und gepaarte Differenz gegenüber Trainingsprävalenz.
Sekundär: Accuracy, Balanced Accuracy, Precision, Recall, F1, ROC-AUC, Konfusionsmatrix,
ECE mit zehn disjunkten Bins, Kalibrierung, Beobachtungszahl, Abdeckung und fehlende Outcomes.
Je Modell immer Gesamtuniversum **und** alle vorab fixierten Titel berichten.
Klassenverteilung und positive/negative Fallzahlen offenlegen; undefinierte Kennzahlen
nicht durch künstlich günstige Werte ersetzen.

Unsicherheit: gepaarter zirkulärer Bootstrap über Fünf-Sitzungs-Blöcke,
1.000 Wiederholungen, Seed 42, deskriptive 95%-Intervalle. Alle Titel eines Datums
zusammen resampeln. Korrelation und die geringe Anzahl unabhängiger Marktregime
bleiben Grenzen. Keine automatische Signifikanz-, Gewinner- oder Produktionsentscheidung.

## Mindeststichprobe und einmalige Hauptauswertung

Vor der vorab geplanten Hauptauswertung müssen gleichzeitig vorliegen:

- **250 gereifte, gepaarte Prognosen je Titel und Modell**; somit mindestens
  **1.250 je Modell** und zwei Prognosen pro zugelassenem Instrument/Entscheidungspunkt.
- Mindestens **zwölf Kalendermonate seit T0**; alle Zielzeitpunkte müssen abgelaufen sein.
- Mindestens **90 % Abdeckung** der protokollierten zulässigen Sessions; Ausfälle
  und deren Gründe ebenfalls je Titel berichten, nicht nachträglich wegfiltern.
- Mindestens 20 positive und 20 negative gereifte Fälle je Titel; sonst nur
  deskriptiv berichten und die Mindestanforderung als unerfüllt ausweisen.

Gepaarte Aufnahme verlangt, dass beide Modelle zum selben D aus derselben Datenbasis
vor der Zielsitzung gespeichert wurden. Ein fehlgeschlagener Partner wird nicht im
Nachhinein ergänzt; der Ausfall zählt für Abdeckung und Betriebsstatistik.

Eine einzige geplante Hauptauswertung nach Erfüllung aller Grenzen. Frühere Dashboards
sind ausschließlich deskriptiver Betriebsstatus; kein optionales Stoppen beim günstigen
Zwischenstand. Falls ein Titel dauerhaft ausfällt, bleibt der Plan unerfüllt; ein neuer
Plan benötigt eine neue, getrennte Kohorte statt rückwirkender Regeländerung.

## Forecasts und Outcomes strikt trennen

Forecasts bleiben in `si_forecasts` unveränderlich; echte Erstellungs- und Entscheidungszeiten
werden erhalten. Outcomes erst nach Zielschluss plus Datenverzögerung und tatsächlicher
Beobachtung separat in `si_outcomes` speichern. Den zum Forecast gehörenden Kursstand
archivieren. Ersten akzeptierten Outcome-Stand und spätere Korrekturen unterscheidbar halten;
Korrekturen überschreiben weder Forecast noch frühere Ergebnisberichte.

Historische Replays und `counterfactual_model_replay=true` sind ausgeschlossen.
Für Protokoll-, Modell-, Feature-, Threshold- oder Providersemantikänderungen gilt:
**v2 mit neuer Kohorte vor weiteren Prognosen**, v1 und seine Ergebnisse erhalten.
Keine Optimierung aus der retrospektiven Diagnose oder aus v1-Zwischenständen.

Der Plan ist eingefroren, die unabhängige Validierung hat noch nicht begonnen.
Auch nach Erreichen der Mindestzahlen ist keine automatische Modellfreigabe vorgesehen.
