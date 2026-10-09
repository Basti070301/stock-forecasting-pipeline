# M2.2 – Bestandsaufnahme und Plan

Branch: `codex/docker-portainer-m22`, abgeleitet von
`codex/stock-intelligence-platform`. Vorhandene uncommittete Dateien bleiben
erhalten; lokales Baseline-Archiv und SHA256-Manifest unter `.runtime/m22-baseline`.

## Bestandsaufnahme

- Native Entwicklung: Uvicorn auf 127.0.0.1:8000; optional Vite auf 5173.
- Browser nutzt relative `/api`-URLs. Keine UI-Änderung erforderlich.
- Vorhandener Dockerfile kombiniert UI/Backend; Compose veröffentlicht bisher
  optional PostgreSQL und enthält weder Nginx noch vollständige Härtung.
- PoC-Schema verwendet ausschließlich CREATE IF NOT EXISTS. Plattformtabellen
  `si_*` werden additiv initialisiert, jedoch bisher nicht transaktional zusammen
  mit dem PoC-Schema versioniert.
- FinBERT lädt lazy, aber ignoriert bislang HF_HOME zugunsten eines Projektpfads.
- FastAPI erlaubt bisher nur localhost-Hostheader; Mutationenschutz ist lokal.
- Docker CLI 29.8.1 / Compose 5.5.1 vorhanden. Linux-Daemon zunächst nicht
  erreichbar. Keine produktiven Stacks oder Serverkonfigurationen angefasst.

## Umsetzung

1. Ausgangstests erneut ausführen und Baseline sichern.
2. Drei Services: Nginx-Frontend mit HTTPS/Basic Auth, nichtprivilegiertes
   CPU-Backend, interne PostgreSQL-Instanz. Getrennte projektbezogene Netzwerke
   und persistente Volumes; keine festen container_name-Werte.
3. Konfigurierbare Hosts/Origins, Proxy-Vertrauensgrenze, Readiness,
   abgeschaltete HTTP-Mutationen im Deployment; Windows-Defaults beibehalten.
4. HF_HOME respektieren, Modellrevision fixieren, expliziter Download und
   Offline-Inferenz aus persistentem Cache. Keine Gewichte beim Image-Build.
5. Explizite versionierte Migration und idempotenter Referenzimport ohne
   Rebuilds; CLI-Wartung über Docker-Host, keine Netzwerk-Adminfunktionen.
6. Build-Override für CLI und imagebasierte Compose-Datei für Portainer.
   Backup-/Restore-/Update-/Rollback-Abläufe dokumentieren.
7. Regressionen und statische Compose-Prüfung; soweit Docker verfügbar Images,
   PostgreSQL, Browser, Inferenz, Rechte und Neustart-Persistenz praktisch testen.
   Nicht ausgeführte Prüfungen ausdrücklich als BLOCKED kennzeichnen.
