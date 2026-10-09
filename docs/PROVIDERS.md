# Anbieter, Lizenzen und Grenzen

Quellenprüfung: 08.10.2026. Keine kostenpflichtige Buchung vorgenommen.

## Yahoo Finance / yfinance

Die vorhandene Ingestion wird unverändert genutzt: tägliches OHLCV,
`auto_adjust=True`, unveränderte Raw-Snapshots. Die Repository-Snapshots stammen
vom 25.08.2026. Historische Daten sind keine Echtzeitversorgung; keine SLA und
keine garantierte Datenverzögerung. Die Oberfläche bezeichnet den letzten
gespeicherten Schlusskurs und dessen Handelstag ausdrücklich.

## Alpha Vantage

Implementiert: `GET https://www.alphavantage.co/query` mit
`function=NEWS_SENTIMENT`, genau einem bestätigten Provider-Ticker,
`sort=LATEST`, `limit=50`, backendseitigem `apikey`.
Mehrere Ticker in einer Anfrage bedeuten beim Anbieter eine UND-Verknüpfung;
deshalb erfolgen lokale Abrufe instrumentweise.

[Offizielle API-Dokumentation](https://www.alphavantage.co/documentation/#news-sentiment)
kennzeichnet diesen Endpoint derzeit als Premium. Ein gültiger Key allein
garantiert keine Berechtigung. [Allgemeine Kontingentangaben](https://www.alphavantage.co/support/)
nennen für viele kostenlose Endpunkte 25 Anfragen/Tag; das ist keine Zusage
für kostenlose News. Die Anwendung begrenzt zusätzlich auf 25 logische Abrufe
pro UTC-Tag und mindestens 60 Sekunden Abstand, über Neustarts hinweg.
Pro Abruf maximal drei Versuche bei Transport-/5xx-Fehlern (1 und 2 Sekunden
Backoff, 20 Sekunden HTTP-Timeout). 429 sowie Note/Information/Error Message
brechen verständlich ab; keine unendlichen Retries oder Tarifumgehung.
Wiederholte HTTP-Versuche können beim Anbieter ebenfalls Kontingent verbrauchen.

Nachrichten speichern Quelle, Titel, verfügbare Beschreibung, Original-URL,
Veröffentlichung in UTC, erstmalige lokale Erfassung in UTC, Sprache und
Ticker-Zuordnung. URL-Hashes entfernen Fragment und bekannte Trackingparameter.
Ereignistypen nur aus passenden Provider-Themen. Keine Paywalls werden geöffnet
oder umgangen; Nachrichtentexte werden nicht extern nachgescrapt.

[Nutzungsbedingungen](https://www.alphavantage.co/terms_of_service/)
sehen standardmäßig persönlichen, nicht kommerziellen Gebrauch vor; andere
Nutzung erfordert passende Vereinbarung. Keine pauschale Freigabe zur
Weiterverteilung angenommen. Der lokale Forschungsbetrieb veröffentlicht nichts.

Default-Zuordnung: AAPL, MSFT, NVDA. SAP.DE und ALV.DE bleiben ohne News-Symbol,
bis die konkrete Wertpapier-/Handelsplatzzuordnung des gewählten Tarifs geprüft
wurde. Ein ADR-Ticker wird nicht still als deutsche Stammaktie ausgegeben.

## ProsusAI/finbert

[Modellkarte](https://huggingface.co/ProsusAI/finbert): englisches Finanzsentiment,
drei Softmax-Labels positive/negative/neutral. Sentiment = positive − negative.
Spracherkennung mit deterministischem langdetect-Seed; unter 90 % Konfidenz
`unknown`. Die Spracherkennung ist heuristisch, keine perfekte Sprachgarantie.
Nur `en` wird analysiert; keine automatische Übersetzung.

Lazy-Prozesscache, serialisierte Inferenz, maximal 512 Token und Truncation.
Lange Artikel werden somit nicht vollständig bewertet. Modellrevision wird
mit dem Ergebnis gespeichert. Optionale Transformers/PyTorch-Abhängigkeiten,
CPU-Standard und optionaler GPU-Fallback. Lokaler CPU-Smoke-Test erfolgreich
mit Revision `4556d13015211d73dccd3fdd39d39232506f3e43`.

Der [Upstream-Code](https://github.com/ProsusAI/finBERT/blob/master/LICENSE)
steht unter Apache 2.0. Die geprüfte Hugging-Face-Modellkarte enthält jedoch
keinen ausdrücklichen Lizenz-Metadateneintrag für die Gewichte. Daraus wird
keine zusätzliche kommerzielle Rechtezusage abgeleitet. Vor Redistribution
oder kommerzieller Nutzung Rechte an Modellgewichten/Trainingsmaterial klären;
hier werden Gewichte nur lokal vom Nutzer heruntergeladen und nicht versioniert.

## Nicht angeschlossen

- Twelve Data / SEC EDGAR: keine vorgetäuschte Implementierung; die
  `NewsProvider`-Schnittstelle erlaubt weitere Adapter.
- Minuten-OHLCV: kein geeigneter historischer Feed vorhanden. Intraday enthält
  nur separate Daten-/Kalendergrenzen, keine trainierte Vorhersagepipeline.
- Index-/FX-Daten: kein validierter Referenzbestand, daher keine berechnete
  Index-Überschussrendite oder währungsbereinigte Portfoliorendite.
