# M3 – Bestandsaufnahme und Umsetzung

Ausgangspunkt: f8fac37, neuer lokaler Branch `codex/m3-live-news-intelligence`.
Uncommittete M2.4-Dokumente bleiben erhalten; keine Docker-Laufzeitprüfung.

Vorhanden: relative React-/api-Aufrufe, News-Liste/Detailansicht, Alpha-Vantage-
Adapter, lazy CPU-FinBERT mit fester Revision, SQLAlchemy-Dokumenttabellen,
SQLite-Demomodus/PostgreSQL-Livemodus und ein kontrollierter Jobexecutor.
Lücken: Providerstatus/Pagination, Updates/Revisionen, Batchinferenz,
Deduplizierung über URLs hinaus, nachvollziehbare Aggregation und Scheduler.

1. Finnhub Company News (US) und explizit erlaubte RSS-Feeds als Adapter;
   vorhandenes Alpha Vantage wiederverwenden. Keine Zugänge erfinden.
2. Nachrichten-Engine auf bestehendem Store: UTC, erste Beobachtung unveränderlich,
   Revisionen, Mapping-Belege, persistente Requestbudgets und DB-Lease.
3. FinBERT-Batches auf bestehendem Cache; Sprachprüfung und input-hash-gebundene
   Analysen. Keine fremdsprachigen Ersatzscores oder Kursprognosen.
4. Versionierte additive Migration; SQLite lokal auch mit echten News bei
   weiterhin historischen Kursen. Keine neue ETL-/Datenarchitektur.
5. Bestehende API beibehalten, paginierte Übersicht/Status/Aggregate ergänzen;
   vorhandenen Mutationsschutz und Docker-Lesebetrieb erhalten.
6. Bestehendes UI erweitern: Feedfilter, Status, Aktien-Sentiment und kompakte
   Dashboardübersicht; vorhandene Komponenten und Styles wiederverwenden.
7. Opt-in Scheduler/CLI ohne neue Infrastruktur; bounded cycles und gemeinsame
   DB-Sperre gegen parallele Abrufe. Tests, echte CPU-Batchinferenz und Bericht.

Provider-Nutzungsrechte werden getrennt vom technischen Zugang konfiguriert.
Standardmäßig keine Vollartikel und keine Provider-Zusammenfassungen speichern.
Ohne konfigurierten, zulässigen Zugang bleibt Live-Integration BLOCKED.
