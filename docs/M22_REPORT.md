# M2.2 – Technischer Abschlussstand

Stand: 09.10.2026. Branch: `codex/docker-portainer-m22`, lokal erstellt auf
Basis von `codex/stock-intelligence-platform`. **Deployment vorbereitet;
M2.2 noch nicht vollständig praktisch abgenommen.** Docker CLI/Compose sind
vorhanden, der Linux-Daemon ist nicht erreichbar. Image-Builds wurden versucht,
konnten aber keine Verbindung zur Docker-API herstellen. Es wurden keine
Container, produktiven Stacks oder Proxmox-/Serverkonfigurationen verändert.
Kein GitHub-Push und keine kostenpflichtigen Dienste.

## Architekturübersicht

Der bestehende React-Build wird separat durch Nginx ausgeliefert. Ein
Multi-Stage-Frontend-Dockerfile baut ihn mit Node/pnpm; im Runtime-Image läuft
kein Entwicklungsserver. Relative `/api`-Aufrufe gehen über Nginx an FastAPI.
Das Backend-Image enthält die Pipeline-Abhängigkeiten und CPU-PyTorch/FinBERT,
Uvicorn läuft mit genau einem Worker. PostgreSQL 17 verwendet ein eigenes
persistentes Volume und wird nicht am Host veröffentlicht.

HTTPS und Basic Auth schützen UI/API auch im privaten Netz. Der Standard ist
`127.0.0.1:8085`; für LAN/Tailscale muss eine konkrete private Hostadresse
konfiguriert werden. Nginx prüft den Host, überschreibt Proxyheader und setzt
einen eigenen Backend-Schlüssel. FastAPI verwendet explizite Hosts/Origins,
vertraut keinen ungeprüften Forwarded-Headern und deaktiviert API-Dokumentation
und Mutationen ausschließlich im Dockerprofil.

Die drei Schutzebenen für schreibende Netzwerkaktionen sind Nginx-Methodenfilter,
FastAPI-Mutationssperre und eine PostgreSQL-Leserolle. Migrationen/Importe/
News-Analysen erfolgen ausschließlich als explizite CLI-Wartung am Docker-Host.
Die bestehende Oberfläche wurde nicht verändert; ihre Aktionsschaltflächen
können im Serverprofil deshalb weiterhin sichtbar sein, werden aber abgewiesen.
Die native Windows-App behält ihre bisherigen Aktionen.

## Neue Dateien dieses Meilensteins

| Datei | Zweck |
|---|---|
| `.env.docker.example` | Separate Dokumentation der Deploymentvariablen, ohne Kennwörter |
| `.gitattributes` | LF-Zeilenenden für Linux-Shellskripte/Docker-Konfiguration |
| `compose.build.yaml` | Lokale Build-Kontexte getrennt vom Portainer-Stack |
| `deploy/frontend/Dockerfile` | React-Build und nichtprivilegierter Nginx |
| `deploy/frontend/nginx.conf` | Schreibgeschützte Nginx-Runtime mit tmpfs |
| `deploy/frontend/site.conf.template` | HTTPS, Auth, Hostprüfung und API-Proxy |
| `deploy/frontend/start.sh` | Validierte Konfiguration, Passwort-Hash und persistentes TLS-Zertifikat |
| `requirements-docker.in` | Fixierte direkte Linux-/CPU-Abhängigkeiten |
| `requirements-docker.lock` | Aufgelöste transitive Versionen und SHA256-Prüfsummen |
| `sql/migrations/001_reference.sql` | Additive ursprüngliche Börsendatentabellen |
| `sql/migrations/002_platform.sql` | Additive Plattformtabellen |
| `src/platform/maintenance.py` | Explizite versionierte Migration, Seed und Modell-/Rechteprüfung |
| `scripts/configure_docker.py` | Private Konfiguration, zufällige getrennte Secrets, kein Überschreiben |
| `scripts/docker_admin.py` | Wartungsaufrufe ohne Kennwörter in Befehlsargumenten |
| `scripts/docker_smoke.py` | Isolierte Container-/Auth-/Persistenzprüfung |
| `scripts/docker_browser_smoke.mjs` | Prüfung der bestehenden UI gegen den Docker-Stack |
| `tests/test_deployment.py` | Konfiguration, Auth, Hosts, Readiness, Cache und Testprojekt-Isolation |
| `.github/workflows/docker.yml` | Manuell auslösbare Docker-Prüfung; nicht ausgeführt/gepusht |
| `docs/M22_PLAN.md` | Bestandsaufnahme und Implementierungsplan |
| `docs/docker-deployment.md` | Schnellstart und vollständige Betriebsanleitung |
| `docs/M22_REPORT.md` | Dieser Bericht |

Zusätzlich lokal und bewusst ignoriert: `.env.docker` mit zufälligen
Testzugangsdaten, Baseline-Archiv/Manifest unter `.runtime/m22-baseline`,
bereinigtes Compose-Modell und Prüfarbeitsverzeichnisse. Keine Modellgewichte,
Secrets oder Laufzeitdaten in Git aufgenommen.

## Geänderte Dateien gegenüber dem gesicherten Ausgangsstand

- `Dockerfile`: eigenständiges Backend, CPU-Abhängigkeiten, Non-root, Healthcheck.
- `compose.yaml`: drei getrennte Services mit benannten Volumes, privaten
  Netzwerken, Abhängigkeiten, Limits, Restart-Policies und Logrotation.
- `.dockerignore`: Ausschluss von Secrets, Modellen und lokalen Laufzeitdaten;
  ausschließlich die bekannten Raw-Referenzen in den Build aufnehmen.
- `.gitignore`: Deployment-Secrets und Backups ausschließen.
- `src/platform/config.py`: additive Docker-Einstellungen; native Defaults erhalten.
- `src/platform/api.py`: konfigurierbare Hosts, Proxy-Prüfung, Readiness,
  abschaltbare Docs/Mutationen und keine Job-Schreibzugriffe im Lesebetrieb.
- `src/platform/news.py`: feste Modellrevision, HF_HOME/Cachekonfiguration,
  Offlinebetrieb und verständlicher Fehler bei fehlenden Gewichten.
- `scripts/check_finbert.py`: bisherige lokale Cacheposition erhalten,
  explizites HF_HOME respektieren.
- `tests/test_platform_postgres.py`: versionierte Migration, idempotenter Seed
  und Erhalt einer bereits veränderten Kurszeile als Integrationstest.
- `README.md`, `docs/LOCAL_SETUP.md`: Verweise und veralteten Docker-Start ersetzen.

Der vorherige Plattformstand war selbst noch weitgehend uncommittet. Er wurde
nicht zurückgesetzt oder überschrieben, sondern vorab vollständig archiviert.
Ein SHA256-Abgleich mit 78 Ausgangsdateien ergab keine verschwundenen Dateien.
**34 geschützte Dateien sind byteidentisch**, darunter Frontend-Quellen,
Raw-Snapshots, ursprüngliche Pipeline-Module, Referenzmetriken,
`scripts/start.ps1` und die native `.env.example`. Die Änderungen liegen
weiterhin lokal im Arbeitsverzeichnis; es wurde kein Sammelcommit fremder
vorheriger Änderungen angelegt.

## Services, Ports, Netzwerke und Volumes

| Service | UID | Ports | Persistenz |
|---|---|---|---|
| `si-frontend` | 101:101 | Nur Host-IP:8085 → 8443/TLS; Health 8081 nur Container-Loopback | `si-tls` |
| `si-backend` | 10001:10001 | 8000 intern, kein Published Port | `si-runtime`, `si-data`, `si-cache` |
| `si-postgres` | 999:999 | 5432 intern, kein Published Port | `si-pgdata` |

Netze: `si-app` und `si-database` intern; `si-edge` für Frontend-Anbindung,
`si-egress` für bewusste Backend-/Modellabrufe. Alle Netze/Volumes erhalten den
Compose-Projektpräfix. Keine festen Container-Namen oder Bind-Mount-Pfade,
kein Docker-Socket, kein privilegierter Modus. Alle Capabilities entfernt,
Root-Dateisysteme schreibgeschützt, tmpfs für temporäre Dateien,
`no-new-privileges`, Speicher-/CPU-/PID-Grenzen. Logs: drei Dateien à 10 MB
pro Container, stdout/stderr für Portainer.

## PostgreSQL-Integration

Neue Instanzen werden ausschließlich durch `init-db` initialisiert. Die
versionierten SQL-Dateien werden transaktional und unter Advisory-Lock
angewendet; Dateiprüfsummen verhindern nachträgliche stille Änderungen.
Bestehende `dim_stock`, `fact_stock_price`, `fact_stock_features` und `si_*`
bleiben erhalten. Der Backendstart führt keine Migration oder Befüllung aus.

`import-reference` liest die fünf festen historischen Snapshots. Es werden
nur fehlende Schlüssel eingefügt; bestehende Werte werden auch bei erneuter
Ausführung nicht aktualisiert. Fehlende Features werden aus den tatsächlich
erhaltenen Datenbankkursen abgeleitet. Es gibt weder Training noch Rebuild,
DROP/TRUNCATE oder automatisches Löschen. Bei Fehlern wird der gesamte Import
zurückgerollt. Dieser Ablauf ist implementiert; sein praktischer
PostgreSQL-Nachweis bleibt ohne laufende Testdatenbank offen.

Die Web-API verbindet sich als `si_reader` ohne Schreibrechte. Der Owner wird
nur für explizite Wartung verwendet. Vorhandene Leserollen mit erhöhten
Rechten führen zum Abbruch der Einrichtung, nicht zu stillen Rechteänderungen.
Bestehende Passwörter werden nicht automatisch rotiert. PostgreSQL-Volume-
Upgrades und Übernahmen fremder Schemata brauchen vorherige Restore-Proben.

## FinBERT-Integration

`ProsusAI/finbert`, Revision `4556d13015211d73dccd3fdd39d39232506f3e43`.
CPU-Torch ist im Linux-Lock explizit als `2.14.1+cpu` aufgelöst.
`HF_HOME=/app/.cache/huggingface` liegt auf einem persistenten Volume.
Kein Gewichtsdownload beim Image-Build oder normalen Containerstart.
Der Download ist ein separater CLI-Schritt; anschließend ist Offlinebetrieb
Standard. Die vorhandene Cache-/Lock-Logik initialisiert das Modell einmal
pro Prozess, weitere Analysen verwenden dieselbe Instanz.

Native CPU-Inferenz mit synthetischem, nicht gespeichertem Satz praktisch
ausgeführt: zweiter Aufruf ergab einen Cachetreffer bei insgesamt einem
Ladevorgang. Gemessener Windows-Peak-Working-Set: **883,5 MiB**.
Docker-/Ubuntu-RAM und längere Texte/Parallelbetrieb wurden nicht gemessen.
VM-Startwert: 4 vCPU/8 GiB RAM/30 GiB freie SSD; vor Servereinsatz unter der
tatsächlichen Last prüfen, insbesondere parallele Wartungscontainer.

## Tatsächliche Testergebnisse

Prüfungen am 08./09.10.2026; keine Containerergebnisse aus statischer
Konfiguration abgeleitet.

| Prüfung | Status | Ergebnis / Grenze |
|---|---|---|
| Ausgangs-Backendtests | **Praktisch bestanden** | 26 bestanden, 1 PostgreSQL-Test übersprungen |
| Backend nach Änderungen | **Praktisch bestanden** | 32 bestanden, 2 PostgreSQL-Tests übersprungen |
| Frontendtests | **Praktisch bestanden** | 4 bestanden, vor und nach Umsetzung |
| TypeScript / Produktionsbuild | **Praktisch bestanden** | Typecheck und Vite-Build erfolgreich |
| Vorhandene Browser-E2E | **Praktisch bestanden** | 2 bestanden; nativer Windows-Server, Edge, Dashboard/Backtest/Responsivität/Fehlerzustand |
| Lokaler Appstart | **Praktisch bestanden** | E2E startete Uvicorn unter Windows erfolgreich |
| Native FinBERT-CPU-Inferenz | **Praktisch bestanden** | Offline, feste Revision, Wiederverwendung und Windows-RAM gemessen |
| Python-Lint / neues JS-Skript | **Praktisch bestanden** | Ruff und `node --check` ohne Fehler |
| Compose + Build-Override | **Statisch validiert** | `docker compose ... config --quiet` und geprüftes JSON-Modell |
| Image-Basisdigests | **Registry geprüft** | Öffentliche Manifeste mit Buildx aufgelöst; kein Image gebaut |
| Linux-Python-Lock | **Statisch aufgelöst** | uv 0.10.9, Linux amd64/Python 3.12, CPU-Paket und transitive Hashes |
| Frontend-Image bauen | **BLOCKED** | Build versucht, Docker-Linux-API/Pipe nicht vorhanden |
| Backend-Image bauen | **BLOCKED** | Gleicher fehlender Docker-Daemon |
| PostgreSQL init/Migration/Seed/Rollen | **Nicht praktisch getestet / BLOCKED** | Zwei Integrationstests vorhanden, keine laufende Testdatenbank |
| Container starten/Health/Logs | **Nicht getestet / BLOCKED** | Kein Docker-Daemon, keine Containerlogs vorhanden |
| Docker-Frontend → API → PostgreSQL | **Nicht getestet / BLOCKED** | Isoliertes Smoke- und Browserskript vorbereitet |
| FinBERT im Linux-Container | **Nicht getestet / BLOCKED** | Native Prüfung ersetzt diesen Nachweis nicht |
| Volume-Persistenz/Container-Neuerstellung | **Nicht getestet / BLOCKED** | Automatisierte Prüfung vorbereitet |
| Linux-UIDs/Volume-Schreibrechte | **Statisch vorbereitet, praktisch BLOCKED** | `check-writes` und Nginx-/DB-Startprüfung stehen aus |
| Portainer-Import/Update/Rollback | **Dokumentiert, nicht ausgeführt** | Kein Serverzugriff und keine laufende lokale Engine |
| Backup-/Restore-Probe und Image-CVE-Scan | **Nicht ausgeführt** | Vor echtem Deployment erforderlich |

Die Python-Tests melden eine vorhandene Starlette/httpx-TestClient-
DeprecationWarning. Kein Laufzeitfehler, kein Umbau der bestehenden
Testabhängigkeiten für diesen Meilenstein. Die manuellen Docker-CI-Prüfungen
wurden nur angelegt; kein GitHub-Workflow wurde ausgelöst.

## Bekannte Grenzen und verbleibende Risiken

- Ohne Docker-Laufzeitprüfung sind insbesondere Linux-Builds, Nginx-Start,
  nichtprivilegierter PostgreSQL-Erststart, Datenbankmigration und tatsächliche
  Volume-Besitzer noch nicht bestätigt. Der Meilenstein ist daher nicht als
  vollständig abgenommen markiert.
- Das erste TLS-Zertifikat ist selbstsigniert und 365 Tage gültig. Interne CA
  beziehungsweise geprüfter Fingerabdruck und rechtzeitige Erneuerung sind nötig.
- Basic Auth ist für den privaten Einzelanwenderzugriff gedacht; keine
  Mehrbenutzerverwaltung. Docker-/Portainer-Administratoren können Env-Secrets
  sehen. Deren Rechte und die private Konfigurationsdatei müssen geschützt sein.
- `restart: unless-stopped` behandelt Prozessausfälle, startet einen lediglich
  als unhealthy markierten laufenden Container nicht automatisch neu.
- Zielarchitektur ist zunächst Linux/amd64. ARM ist nicht validiert.
- Paket-/Image-Digests sind fixiert; OS-Buildpakete und Wheel-Buildwerkzeuge
  machen Builds nicht vollständig bitidentisch. Für Rollbacks die konkret
  geprüften Images mit unveränderlichen Tags/Digests aufbewahren.
- `CREATE IF NOT EXISTS` konvertiert keine fremden inkompatiblen Schemata.
  Bestehende Datenbanken zuerst auf einer Restore-Kopie prüfen.

## Start und Portainer

Vollständiger [Schnellstart](docker-deployment.md#schnellstart): Konfiguration
generieren, beide Images per CLI bauen, nur PostgreSQL starten, `init-db`,
`import-reference`, Modell herunterladen/prüfen, gesamten Stack starten.
URL anschließend `https://127.0.0.1:8085` mit Anmeldung. Die bereits lokal
generierte `.env.docker` gehört zum isolierten Testprojekt
`stockintelligence-m22-test`; nicht als Serverkonfiguration wiederverwenden.

Für Portainer auf demselben Docker-Endpoint zuerst Images bauen oder geprüfte
Images laden. Danach die imagebasierte `compose.yaml`, exakt denselben
Projektnamen und private Stackvariablen verwenden. Bei Übergabe eines
CLI-Stacks nur dessen Container/Netze stoppen, Volumes behalten. Git-Installation
erst nach ausdrücklich genehmigtem Push eines freigegebenen Commits. Portainer
muss keine Images aus einem Git-Stack bauen; dies wird nicht vorausgesetzt.
Details zu Update/Backup/Restore/Rollback stehen im
[Betriebshandbuch](docker-deployment.md).

## Vor dem echten Proxmox-Deployment

1. Den vorbereiteten isolierten Docker-Smoke-Test einschließlich Modelltest
   und Browserprüfung auf einer laufenden lokalen/Test-Engine bestehen lassen.
2. PostgreSQL-Integrationstests, zweite Befüllung, Erhalt geänderter Bestandsdaten,
   Leserollenrechte, alle Healthchecks und Schreibrechte praktisch prüfen.
3. Container-Neuerstellung mit erhaltenen Daten/Modellcache und Backup-/Restore-
   Probe durchführen; danach erst produktive Datenübernahme planen.
4. Ubuntu/CPU-Architektur, VM-Speicher, freien Port 8085, lokale Docker-Netze und
   bereits laufende Stacks inventarisieren. Bestehende Konfigurationen erhalten.
5. Explizite private Bind-Adresse, Firewall/Router/IPv6, optional Tailnet-Regeln,
   TLS-Vertrauen und Anmeldung von erlaubtem und unerlaubtem Gerät testen.
6. Neue Server-Secrets, Zertifikat, Image-CVE-Prüfung, Release-Digests und
   Wiederherstellungsablauf festlegen; Portainer-Verwaltung in einem Teststack prüfen.

Bis dahin bleibt die native Windows-App unabhängig nutzbar. Für die übrige
Abnahme muss der lokale Docker-Dienst vom Nutzer gestartet bzw. sein Start
freigegeben werden; er wurde wegen möglicher automatisch startender fremder
Container nicht eigenmächtig aktiviert.
