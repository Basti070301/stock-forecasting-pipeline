# M4.3 – privater historischer Docker-Test

Stand: 29.10.2026. Branch `codex/m4-3-docker-preview`, Basis
`f089a87d9d0f9691ca9fbd12ef52695ef305ef7e` (M4.2b). Den endgültigen lokalen
M4.3-Commit zeigt `git log -1 --format='%H %s'` auf diesem Branch.

**Lokal praktisch getestet:** Linux-Container unter Docker Desktop/WSL2,
PostgreSQL, HTTPS/Anmeldung, React → Nginx → FastAPI → PostgreSQL, historische
Research-Replays und FinBERT-CPU-Inferenz einschließlich Cache nach Neuerstellung.
**Noch offen / BLOCKED für die Server-Abnahme:** Ubuntu-VM, SSH-Tunnel und
Portainer-Übernahme wurden nicht auf dem Server ausgeführt. Keine SSH-Verbindung,
kein GitHub-Push, kein Proxmox-Deployment und keine fremden Stacks verändert.

## 1. Architektur und Grenzen

Die bestehenden `compose.yaml`, `compose.build.yaml`, Dockerfiles und
Wartungsskripte bleiben die Grundlage. Das kleine `compose.preview.yaml` ergänzt
ein ausdrücklich historisches Profil. Immer beide Compose-Dateien verwenden.

| Service | Laufzeit | Zugriff / Grenze |
| --- | --- | --- |
| `si-frontend` | React-Produktionsbuild, Nginx, UID 101 | ausschließlich `127.0.0.1:8086` → HTTPS 8443; Basic Auth |
| `si-backend` | Python 3.12, Uvicorn, ein Worker, UID 10001 | Port 8000 nur im Compose-Netz, PostgreSQL-Leserolle |
| `si-postgres` | PostgreSQL 17, Digest fixiert, UID 999 | Port 5432 ausschließlich im internen Datenbanknetz |

Alle drei Services: `restart: unless-stopped`, Healthchecks, schreibgeschütztes
Root-Dateisystem, `cap_drop: ALL`, `no-new-privileges`, begrenzte PIDs und
rotierende JSON-Logs (3 × 10 MiB). Keine Host-Netzwerke, Bind-Mounts fremder
Daten, privilegierten Container oder Docker-Socket-Mounts.

Projektname auf Ubuntu: **`stockintelligence-m43-test`**. Compose erzeugt eigene
Netze mit diesem Präfix: `si-edge`, `si-app` (intern), `si-database` (intern),
`si-egress`. Egress bleibt für ausdrücklich ausgelöste Downloads technisch
vorhanden; das Profil ist keine Firewall gegen ausgehenden Verkehr.

Fünf projektbezogene Volumes:

| Suffix | Inhalt | Containerpfad |
| --- | --- | --- |
| `si-pgdata` | ausschließlich diese PostgreSQL-Testinstanz | `/var/lib/postgresql/data` |
| `si-runtime` | Registry, Preview-Modelle, Laufzeitdateien | `/app/.runtime` |
| `si-data` | eigene Kopien historischer Raw-Snapshots / Pipelineausgaben | `/app/data` |
| `si-cache` | Hugging-Face-Cache | `/app/.cache` |
| `si-tls` | selbst signiertes Zertifikat und privater Schlüssel | `/var/lib/si-tls` |

Beispiel: `stockintelligence-m43-test_si-pgdata`. Kein `container_name`, kein
global fest benanntes Netzwerk, keine Bindung an vorhandene PostgreSQL-Instanzen.

Das Profil erzwingt `SI_HISTORICAL_PREVIEW=true`, Schema v4 und
`SI_ALLOW_MUTATIONS=false`. News-/Marktdatenprovider, Current-Forecasts und
Scheduler sind deaktiviert; Provider-Schlüssel werden nicht weitergereicht.
Die Oberfläche zeigt **DEMO / HISTORIE**. Der interne Modus `live` bezeichnet
hier den PostgreSQL-Speicherbereich, ausdrücklich keine aktuellen Marktdaten.
`data_profile=historical_preview` stellt dies in der API klar.

Nginx schützt HTML und `/api` mit der vorhandenen Anmeldung, setzt den internen
Proxy-Token selbst und leitet `/api` innerhalb des Stacks weiter. Der Browser
kennt keinen Backend-Containernamen. Host-/Origin-Listen sind auf den
konfigurierten lokalen Host begrenzt, API-Dokumentation und Schreibendpunkte
bleiben gesperrt. Der Server vertraut keinen frei eingespeisten Proxy-Headern.
LAN/Tailscale oder ein bestehender HTTPS-Proxy werden hier nicht umkonfiguriert.

## 2. Ressourcen und Voraussetzungen

Vorhandene Docker Engine mit Compose-Plugin, Git und Python 3 auf Ubuntu;
Zielarchitektur **linux/amd64**. Das Projekt verwendet CPU-PyTorch und benötigt
keine GPU. Für ARM ist dieser Stand nicht abgenommen.

Als Ausgangspunkt mindestens 4 vCPU, 8 GiB VM-RAM und 30–40 GiB freier Platz für
Builds, Images, Daten und Modellcache einplanen, **zusätzlich zur Reserve anderer
Anwendungen**. Containerlimits: Backend 4 GiB / 2 CPU, PostgreSQL 1 GiB / 1 CPU,
Frontend 192 MiB / 0,5 CPU. Limits reservieren keinen RAM. Auf einem ausgelasteten
Host zuerst Kapazität schaffen; keine fremden Dienste stoppen.

Gemessen im lokalen Test: FinBERT-Wartungsprozess etwa 892–894 MiB Peak-RSS.
Im Leerlauf lagen die drei Container zusammen bei etwa 221 MiB. Das sind
Momentaufnahmen, keine garantierten VM-Maximalwerte; Training/Build laufen
zusätzlich. Modellgewichte rund 440 MB, Python-Wheels und Images deutlich größer.

## 3. Ubuntu-Preflight – ausschließlich lesend

Diese Befehle auf der VM selbst ausführen. Bestehende Engine und Portainer
weiterverwenden; keine Installation, kein Neustart der Engine erforderlich.
Bei fehlenden Rechten gezielt `sudo docker ...` nutzen; die Docker-Gruppe hat
weitreichende Hostrechte.

```bash
docker version
docker compose version
uname -m
nproc
free -h
df -h "$HOME" /var/lib/docker
docker info --format 'OS={{.OSType}} Arch={{.Architecture}} CPUs={{.NCPU}} RAM={{.MemTotal}} Root={{.DockerRootDir}}'
docker system df
docker compose ls
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Ports}}\t{{.Status}}'
docker network ls
docker volume ls
ss -lnt '( sport = :8086 )'
git --version
python3 --version
```

Bei anderem Docker-Datenpfad dessen freies Dateisystem ebenfalls prüfen. Port
8086 muss frei sein. Für eine Erstinstallation müssen diese Abfragen leer sein:

```bash
docker ps -a --filter label=com.docker.compose.project=stockintelligence-m43-test --format '{{.Names}}'
docker network ls --filter label=com.docker.compose.project=stockintelligence-m43-test
docker volume ls --filter label=com.docker.compose.project=stockintelligence-m43-test
```

Vorhandene Ressourcen bedeuten **anhalten und Identität prüfen**, nicht löschen.
Bei einer späteren Fortsetzung desselben eigenen Teststacks sind sie erwartet.
Kein `prune`, keine globalen Stop-/Restart-Befehle, keine Volumenlöschung.

## 4. GitHub erst nach gesonderter Freigabe

Der M4.3-Branch enthält die vorhandene lokale M3-/M4-Commit-Historie. Ein neues
Repository und Merges nach `main` sind nicht nötig. **Dieser Push wurde nicht
ausgeführt.** Erst nach ausdrücklicher Freigabe auf Windows:

```powershell
git -C C:\Dev\KI\LAB\stock-ai status --short
git -C C:\Dev\KI\LAB\stock-ai log -1 --format="%H %s"
git -C C:\Dev\KI\LAB\stock-ai push --set-upstream origin codex/m4-3-docker-preview
```

Keine Force-Option. Danach lokalen und Remote-Hash vergleichen. Private
`.env`-Dateien, `.runtime`, Modelle, Cache und Volumes werden nicht veröffentlicht.
Vorher ist die folgende GitHub-Installation für diesen neuen Branch noch blockiert.

## 5. Erstinstallation – Schritt für Schritt auf Ubuntu

In einer Bash-Sitzung arbeiten. Ab hier entstehen ausschließlich Ressourcen des
neuen Testprojekts. Befehle einzeln prüfen; bei einem Fehler nicht fortfahren.
Keine Debug-Shell mit `set -x` verwenden.

### Repository holen und privates Profil erstellen

```bash
set -euo pipefail
set +x
umask 077
PREVIEW_DIR="$HOME/stock-ai-preview"
test ! -e "$PREVIEW_DIR"
git clone --branch codex/m4-3-docker-preview --single-branch \
  https://github.com/Basti070301/stock-forecasting-pipeline.git "$PREVIEW_DIR"
cd "$PREVIEW_DIR"
git status --short
git log -1 --format='%H %s'
```

HEAD mit dem nach Freigabe veröffentlichten lokalen M4.3-Commit vergleichen.
Nicht über eine bestehende Arbeitskopie klonen oder Dateien zurücksetzen.

```bash
PROJECT=stockintelligence-m43-test
REV=$(git rev-parse --short=12 HEAD)
python3 scripts/configure_docker.py --output .env.preview --preview \
  --project "$PROJECT" --bind 127.0.0.1 --host 127.0.0.1 --port 8086 \
  --image-tag "m43-$REV"
chmod 600 .env.preview

# Nur die selbst erzeugte private Datei laden; keine fremde Env-Datei sourcen.
# Subshell: eindeutige Dateikonfiguration gewinnt vor gleichnamigen Shellvariablen.
dc() {
  (
    set +x
    set -a
    . ./.env.preview
    set +a
    docker compose --env-file .env.preview --project-name "$COMPOSE_PROJECT_NAME" \
      -f compose.yaml -f compose.preview.yaml "$@"
  )
}
dc config --quiet
dc -f compose.build.yaml config --quiet
```

Der Generator erzeugt getrennte zufällige Auth-, Proxy-, Owner- und
Leserpasswörter und verweigert das Überschreiben vorhandener Dateien. Anmeldung:
Benutzer `research`, Passwort `SI_AUTH_PASSWORD` aus **dieser** privaten Datei.
Die Datei nur mit einem privaten lokalen Editor ansehen; niemals in Chat,
GitHub, Tickets oder geteilte Logs kopieren. Auch aufgelöstes `compose config`
kann Secrets enthalten; deshalb oben `--quiet` verwenden.

Keine API-Keys erforderlich. `SI_FINBERT_ENABLED=false` verhindert im API-Prozess
eine unnötige Modellinitialisierung. Die explizite Modellprüfung funktioniert
unabhängig davon. Private Konfiguration aufbewahren, beim Neustart nicht neu erzeugen.

### Images und PostgreSQL

```bash
dc -f compose.build.yaml build --pull
dc up -d --wait --wait-timeout 120 si-postgres
python3 scripts/docker_admin.py init-db --env-file .env.preview
python3 scripts/docker_admin.py import-reference --env-file .env.preview
python3 scripts/docker_admin.py import-reference --env-file .env.preview
python3 scripts/docker_admin.py check-writes --env-file .env.preview
```

Der erste Build lädt Basisimages und fixierte Abhängigkeiten, **keine
Modellgewichte**. Python verwendet `requirements-docker.lock` mit Paket-Hashes
und CPU-Torch, React `pnpm-lock.yaml` mit `--frozen-lockfile`. Basisimages sind
per Digest fixiert. Betriebssystempakete der vorhandenen Dockerfiles stammen
weiter aus den Paketquellen; ein vollständig bitidentischer OS-Build ist damit
nicht zugesichert.

`init-db` führt unter Transaktion/Advisory-Lock die unveränderten Migrationen
001–003 und die neue additive `004_market_observations.sql` aus. Prüfsummen
verhindern unbemerkte Änderungen bereits angewendeter Migrationen. Schema v4
enthält `dim_stock`, `fact_stock_price`, `fact_stock_features` und die vorhandenen
News-, Modell-, Forecast-, Outcome- und Provider-Dokumenttabellen, ergänzt um
`si_market_runs`, `si_market_observations`, `si_price_revisions`.

Die API verwendet ausschließlich `si_reader` mit SELECT-Rechten. Nur explizite
Wartungscontainer erhalten das Owner-Passwort über die Prozessumgebung, nicht
als Passwort in der Kommandozeile. Kein pauschales Freischalten der HTTP-API.

Der Import ergänzt fehlende Zeilen und überschreibt keine vorhandenen Kurse
oder Features. Erwartet: 5 Aktien und jeweils 6.312 Kurs-/Featurezeilen. Zweiter
Import: `stocks=0, prices=0, features=0`. Raw-Snapshots werden nur fehlend in das
eigene Datenvolume kopiert; abweichende bestehende Dateien führen zum Abbruch.

### Historische Modelle, Bericht und Replays ausdrücklich vorbereiten

```bash
python3 scripts/docker_admin.py seed-reports --env-file .env.preview
python3 scripts/docker_admin.py prepare-research --env-file .env.preview
python3 scripts/docker_admin.py replay-research --env-file .env.preview
python3 scripts/docker_admin.py replay-research --env-file .env.preview
python3 scripts/docker_admin.py verify-preview --env-file .env.preview
```

`prepare-research` nutzt die vorhandene Offline-Trainingsimplementierung für LR
und RF mit Training bis 31.12.2025, Kalibrierung bis 31.03.2026 und historischer
Grenze 25.08.2026. Universum: AAPL, MSFT, NVDA, SAP.DE, ALV.DE. Persistenz in
`si-runtime:/app/.runtime/preview-models`, einschließlich Registry und exklusiv
angelegtem `preview-artifacts.json`. Wiederholung prüft und verwendet vorhandene
Artefakte. Kein Training beim normalen Backend-Start, keine Optimierung und
keine automatische Auswahl/Freigabe eines Modells.

**Warum separate Preview-Artefakte:** Die ursprünglichen Windows-Artefakte wurden
mit Python 3.14.7 erzeugt. Python 3.12 und die Linux-Code-Fingerprints stimmen
nicht mit deren streng geprüftem Laufzeitvertrag überein. Originale Registry,
SHA256 und Modelle bleiben unverändert lokal. Die Prüfung wird nicht abgeschwächt.
Im Image werden ausschließlich kopierte Python-Quelldateien auf LF normalisiert;
die Hostdateien werden dabei nicht geändert. Auf der VM Modelle im jeweiligen
Image erzeugen; nicht ungeprüft lokale Joblib-Dateien kopieren. Bereits bestehende
Preview-Artefakte bei inkompatibler neuer Laufzeit führen zur Ablehnung. Für
einen solchen Test eine neue eigene Projektidentität und einen freien Port
verwenden, statt bestehende Artefakte zu überschreiben.

Die neuen Artefakte gehören **nicht** zum eingefrorenen prospektiven v1-Protokoll.
Sie dienen ausschließlich der historischen Containerprüfung. Ein späterer
Current-Betrieb benötigt kompatible eingefrorene Artefakte oder einen separat
genehmigten neuen Plan. Preview-Modelle nicht stillschweigend an deren Stelle setzen.

`replay-research` persistiert beide Modelle × fünf Aktien = zehn unveränderliche
`historical_replay`-Prognosen, Entscheidung `2026-08-25T21:45:00Z`. Sie sind als
kontrafaktische, erst später erzeugte Replays markiert, bleiben `research_only`
und `forecast_enabled=false`. Der zweite Lauf muss für alle `reused=true` melden.
Es entstehen keine aktuellen Forecasts und kein prospektiver Startzeitpunkt T0.

`seed-reports` importiert den vorhandenen, per SHA256 geprüften Bericht
`m4_1_retrospective_diagnostic_v1.json` unverändert. Das sind Ergebnisse der
ursprünglichen eingefrorenen Modelle, keine neu berechnete unabhängige Bewertung
der Preview-Modelle. Die Oberfläche kennzeichnet `retrospective_diagnostic` und
die weiterhin offene unabhängige Abnahme. Keine Profitabilitätsbestätigung.

`verify-preview` prüft Migrationen, Leserrechte, Tabellen und stabile Research-
Fingerprints. Es legt zusätzlich deterministische **Speicherproben** in einem
separaten `mode=preview` an (News, Forecasts, Outcomes, Beobachtungen, Revisionen).
Sie enthalten keine Finanzwerte und werden nie von Live-/Demo-Abfragen angezeigt.
Das belegt Speicherrundlauf und Neustartpersistenz, nicht reale Marktdaten oder
eine fachliche Live-Outcome-Abnahme. Die echten News-/Marktdaten-/Outcome-
Bestände bleiben leer. Keine späteren Kurse werden erfunden.

### Optional: FinBERT einmal explizit laden

```bash
python3 scripts/docker_admin.py download-model --env-file .env.preview
python3 scripts/docker_admin.py check-model --env-file .env.preview
```

Bekanntes Modell: `ProsusAI/finbert`, Revision
`4556d13015211d73dccd3fdd39d39232506f3e43`. Nur `download-model` erlaubt den
Download. Danach Offline-Betrieb über `HF_HOME=/app/.cache/huggingface` und
`HF_HUB_OFFLINE=1`. Cache gehört zum eigenen persistenten `si-cache`-Volume.
`check-model` prüft synthetischen englischen Finanztext, drei Wahrscheinlichkeiten,
Score und zweite Inferenz aus demselben Prozesscache. Das ist kein Live-News-Abruf.
Ein fehlender Cache wird verständlich gemeldet und nicht automatisch nachgeladen.

### Starten, Anmeldung und Logs

```bash
dc up -d --wait --wait-timeout 180
dc ps
dc logs --no-color --tail 80 si-backend si-frontend si-postgres
dc exec -T si-frontend openssl x509 -in /var/lib/si-tls/server.crt \
  -noout -sha256 -fingerprint -dates
```

Nur Frontend `127.0.0.1:8086` veröffentlicht. `8000/tcp` und `5432/tcp` ohne
Hostadresse in `docker ps` sind interne Ports. Healthchecks prüfen PostgreSQL,
Backend-Readiness und den internen Nginx-Healthpfad. Keine Zugangsdaten in Logs
ausgeben. Selbst signiertes Zertifikat bleibt beim Neustart erhalten.

## 6. Windows-Browser über SSH-Tunnel

Auf dem Laptop Port 8086 ebenfalls auf Belegung prüfen. Ein hier bereits
laufender lokaler M4.3-Stack belegt diesen Port; diesen nur bewusst und mit
seiner eigenen Konfiguration stoppen oder einen anderen freien lokalen
Tunnelport wählen. Keine fremden Prozesse beenden.

```powershell
Get-NetTCPConnection -LocalPort 8086 -State Listen -ErrorAction SilentlyContinue
ssh -N -o ExitOnForwardFailure=yes -L 8086:127.0.0.1:8086 BENUTZER@PRIVATE_VM_IP
```

`BENUTZER@PRIVATE_VM_IP` ersetzen. Die Sitzung offen lassen; dann
**https://127.0.0.1:8086** öffnen. Zertifikatsfingerprint mit der VM-Ausgabe
vergleichen und nur dieses bekannte Testzertifikat akzeptieren. Mit `research`
und dem privaten `SI_AUTH_PASSWORD` anmelden. Keine Router-Portweiterleitung,
öffentliche IP oder Cloudflare-Veröffentlichung konfigurieren.

Prüfen: historisches Banner; Dashboard mit fünf Titeln; Apple-Detail mit Kursen
und technischen Features; Stock Radar; Model Analytics mit unverändertem
Diagnosebericht; zehn gespeicherte Research-Replays (zwei je Aktie). News bleiben
leer, Current-Status gesperrt, T0 nicht vorhanden. Vorhandene Backtestansichten
sind lesbar; neue Backtest- oder Forecast-Jobs aus dem Browser bleiben gesperrt.
Vorhandene Backtestberichte werden nicht durch erfundene Testläufe ergänzt.

Wichtige lesende API-Pfade: `/api/ready`, `/api/settings`, `/api/stocks`,
`/api/stocks/AAPL/history`, `/api/radar`, `/api/research/models`,
`/api/forecasts?kind=research_forecast`, `/api/research/evaluations`,
`/api/research/current/status`. Zugriff ausschließlich über den angemeldeten
HTTPS-Proxy; API-Docs sind deaktiviert.

## 7. Kurzer Abnahmelauf und Persistenz

Der vorhandene Smoke-Test wurde erweitert, keine zweite Testinfrastruktur.
Er darf nur im eigenen markierten Loopback-Testprojekt laufen. Er initialisiert
additiv, prüft idempotenten Import, Modelle/Replays, HTTPS mit Zertifikatsprüfung,
401 ohne Anmeldung, 200 für Lesezugriffe, 403 für Schreibzugriffe und erstellt
ausschließlich die drei eigenen Container neu. Alle Volumes bleiben erhalten.

```bash
python3 scripts/docker_smoke.py --env-file .env.preview
# Nach dem ausdrücklich abgeschlossenen Modell-Download zusätzlich:
python3 scripts/docker_smoke.py --env-file .env.preview --cached-model
```

`--build` baut zusätzlich; `--model` löst ausdrücklich einen Modelldownload aus.
Ohne diese Optionen kein automatischer FinBERT-Download. Evidenz liegt privat
in `.runtime/m43-docker/`, einschließlich Logs und öffentlichem Testzertifikat.

Manuelle Alternative (kein neuer Import nötig):

```bash
python3 scripts/docker_admin.py verify-preview --env-file .env.preview
dc up -d --force-recreate --wait --wait-timeout 180
python3 scripts/docker_admin.py verify-preview --env-file .env.preview
dc ps
```

Counts und `research_fingerprint` müssen gleich sein. Erneut anmelden,
Kursansicht und Replays prüfen; Zertifikat muss unverändert sein. Bei vorhandenem
Cache `check-model` erneut offline ausführen.

Optionaler automatischer Browser-Smoke auf einem separaten Testclient mit Node,
installierten gelockten Frontend-Dev-Abhängigkeiten und Playwright Chromium:
`node scripts/docker_browser_smoke.mjs .env.preview`. Er benötigt privaten
Zugriff auf die selbst erzeugte Konfigurationsdatei. Auf Windows ist alternativ
`$env:SI_TEST_EDGE='1'` für vorhandenes Edge nutzbar. Der produktive Frontend-
Container selbst benötigt weder Node noch Playwright.

## 8. Portainer Standalone – optional, kein zweiter Stack

Für die erste Abnahme **CLI-Management beibehalten**. Portainer kann die
vorhandenen Container, Logs und Ressourcen anzeigen; extern erstellte Stacks
haben je nach Version nur begrenzte Verwaltungsfunktionen. Eine automatische
vollständige Übernahme wird nicht vorausgesetzt.

Für vollständige Portainer-Verwaltung erst Backup erstellen, dann einen
geplanten Wechsel ausschließlich für dieses eigene Projekt durchführen:

```bash
mkdir -p .runtime
dc config --no-interpolate > .runtime/portainer-preview.yaml
chmod 600 .runtime/portainer-preview.yaml
docker compose --env-file .env.preview --project-name "$PROJECT" \
  -f .runtime/portainer-preview.yaml config --quiet
```

Dieser Export enthält **keine Build-Kontexte**, übernimmt das Preview-Overlay
und behält die Variablen. Er wurde lokal mit derselben Env-Datei erneut
aufgelöst und auf vollständige Gleichheit geprüft. Export trotzdem privat
behandeln. `.env.preview` wird separat in Portainer benötigt.

1. Prüfen, dass beide versionierten lokalen Images auf **demselben Docker-Host**
   vorhanden sind; andernfalls dort zuerst per CLI bauen.
2. Backup nach Abschnitt 9; exakte fünf Volumennamen festhalten.
3. Nur dieses eigene CLI-Projekt mit `dc down` beenden. **Kein `-v`**, keine
   Volume-Entfernung. Das entfernt eigene Container/Netze, erhält eigene Daten.
4. In Portainer auf dieser Docker-Standalone-Umgebung einen Stack mit exakt
   **`stockintelligence-m43-test`** anlegen. Inhalt des privaten Exports als
   Compose verwenden; eigene `.env.preview` über die privaten Stack-Variablen
   laden. Keine fremden Stack-Einstellungen ändern.
5. Vor Start Projektname, Loopback-Port, fünf vorhandene Volumennamen und beide
   versionierten Images vergleichen. Kein anderes Projektpräfix, kein zweiter
   konkurrierender Stack; kein Re-pull und kein `latest`. `pull_policy: never`
   für die selbst gebauten Images beibehalten.
6. Bei Konflikt mit einem bestehenden Stackeintrag oder nicht unterstütztem
   Import anhalten und CLI-Verwaltung fortsetzen. Keine Ressourcen löschen,
   um eine Übernahme zu erzwingen. Rückkehr: `dc up -d --wait`.
7. Nach Start Healthchecks, Anmeldung, Counts/Fingerprint, Zertifikat und Logs
   in Portainer prüfen. Anschließend Lebenszyklus über **eine** Verwaltung
   steuern; hostseitige explizite Wartungscontainer nur abgestimmt ausführen.

Git-Stack-Checkout allein garantiert keinen Image-Build. Deshalb ist der
nachvollziehbare CLI-Build mit image-only Compose der empfohlene Weg. Für diesen
Test keine Portainer-Webhooks oder automatischen Git-Updates aktivieren.

Referenzen: [Portainer Stack anlegen](https://docs.portainer.io/user/docker/stacks/add),
[Stack bearbeiten](https://docs.portainer.io/user/docker/stacks/edit),
[Compose-Merge-Regeln](https://docs.docker.com/compose/how-tos/multiple-compose-files/merge/),
[Docker-Volumes](https://docs.docker.com/engine/storage/volumes/).

## 9. Backup, Wiederherstellung, Updates und Rollback

Vor Updates oder Portainer-Wechsel privates Backup anlegen. Keine gleichzeitigen
Trainings-/Wartungsjobs; API ist bereits read-only. Folgende Befehle betreffen
nur dieses Projekt; Secrets bleiben im Container bzw. in der privaten Datei.

```bash
umask 077
mkdir -p backups
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
( set -C; dc exec -T si-postgres sh -c \
  'PGPASSWORD="$POSTGRES_PASSWORD" exec pg_dump -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
  > "backups/pg-$STAMP.dump" )
dc exec -T si-postgres pg_restore --list < "backups/pg-$STAMP.dump" > /dev/null
( set -C; dc run --rm --no-deps -T si-backend python -c \
  "import sys,tarfile; t=tarfile.open(fileobj=sys.stdout.buffer,mode='w|gz'); t.add('/app/.runtime',arcname='.runtime'); t.close()" \
  > "backups/runtime-$STAMP.tar.gz" )
( set -C; cat .env.preview > "backups/config-$STAMP.env" )
sha256sum "backups/pg-$STAMP.dump" "backups/runtime-$STAMP.tar.gz"
dc images
git rev-parse HEAD
```

`set -C` verhindert Überschreiben gleichnamiger Ausgaben. Dump, Runtime, private
Konfiguration, Commit und Image-IDs zusammen sichern. Ein Dateicheck allein
ersetzt keine Wiederherstellungsprobe. TLS-Schlüssel separat vertraulich sichern,
falls identisches Zertifikat nach vollständiger Neuinstallation erforderlich
ist; FinBERT kann ausdrücklich erneut geladen werden. Keine Live-Kopie des
PostgreSQL-Dateisystems anstelle von `pg_dump` verwenden.

**Restore nur in ein neues eigenes Testprojekt mit frischen Volumes und freiem
Port**, z. B. `stockintelligence-m43-test-restore` auf 8087. Dafür Profil wie oben
neu erzeugen, kompatible Images bauen und nur PostgreSQL starten. Shellfunktion
`dc` muss auf dessen eigene `.env.preview` zeigen. Zuerst in die noch leere
Datenbank wiederherstellen, dann Migration/Leserrechte sicherstellen:

```bash
# BACKUP_DUMP und BACKUP_RUNTIME auf die eigenen geprüften Backupdateien setzen.
test -f "$BACKUP_DUMP"
test -f "$BACKUP_RUNTIME"
dc exec -T si-postgres sh -c \
  'PGPASSWORD="$POSTGRES_PASSWORD" exec pg_restore -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --no-privileges --exit-on-error' \
  < "$BACKUP_DUMP"
python3 scripts/docker_admin.py init-db --env-file .env.preview
dc run --rm --no-deps -T si-backend python -c \
  "import sys,tarfile; t=tarfile.open(fileobj=sys.stdin.buffer,mode='r|gz'); t.extractall('/app',filter='data')" \
  < "$BACKUP_RUNTIME"
python3 scripts/docker_admin.py verify-preview --env-file .env.preview
dc up -d --wait --wait-timeout 180
```

Nur selbst erstellte vertrauenswürdige Archive verwenden. Bestehende Registry
nie durch Restore überschreiben; bei nicht leerem Ziel anhalten. Das ist eine
vorbereitete Anleitung; eine vollständige Restore-Abnahme wurde in M4.3 noch
nicht ausgeführt.

**Update:** erst freigegebenen Commit abrufen, sauberen eigenen Checkout prüfen,
Backup und bisherige Image-IDs sichern. Keine lokalen Änderungen überschreiben.
Neue Tags `m43-<neuer Commit>` ausschließlich für `SI_FRONTEND_IMAGE` und
`SI_BACKEND_IMAGE` im privaten Editor eintragen, dieselben Zugangsdaten und
Projektidentität behalten. Mit `dc -f compose.build.yaml build --pull` bauen,
`init-db` ausdrücklich für additive Migrationen aufrufen, anschließend
`dc up -d --wait` und Smoke-Test. Bei Portainer-Verwaltung danach die beiden
Image-Tags dort abgestimmt aktualisieren, kein paralleler CLI-Lebenszyklus.

**Rollback:** bisherige versionierte Images behalten und beide Tags wieder
eintragen. Datenvolumes bleiben erhalten. Nur bei nachgewiesener Vorwärts-
Schema-Kompatibilität zurückrollen; sonst Backup in einem neuen eigenen Projekt
wiederherstellen. Kein automatischer Schema-Downgrade, keine History-Rewrites,
keine Volumenlöschung. Strenge Artefakt-/Code-Versionsprüfung bleibt aktiv.

## 10. Tatsächlich ausgeführte Prüfungen

Lokale Testumgebung: Windows, Docker Desktop 4.96.2, Engine 29.9.2,
Compose v5.6.1, Linux/amd64 unter WSL2, Engine-RAM etwa 7,6 GiB.
Vor Testbeginn waren keine Container/Compose-Projekte aktiv. Testprojekt:
`stockintelligence-m43-test-20261029`, Port 8086. Keine Server-VM angesprochen.

| Prüfung | Ergebnis / Evidenz |
| --- | --- |
| Backend inkl. CPU-FinBERT | **GETESTET:** 226 bestanden, 3 PostgreSQL-Pytests auf Windows übersprungen; `.runtime/m43/backend.log` / XML |
| Neue Preview-Schutztests | **GETESTET:** 11 bestanden, im Gesamtergebnis enthalten |
| Ruff / Git-Whitespace | **GETESTET:** bestanden |
| Sicherheitsprüfung / Bestandsschutz | **GETESTET:** Gitleaks 8.30.1 über den vollständigen Git-Index ohne Fund; Hashvergleich bestätigt unveränderte Originaldaten, Berichte, private Konfigurationen und 9 Modell-/Registry-Dateien |
| Frontend | **GETESTET:** 24 Tests, TypeScript und Produktionsbuild bestanden |
| Bestehende Browser-Regressionssuite | **GETESTET:** alle 5 bestanden; UI-Fixtures ausdrücklich Fixtures, lokales echtes Research-Artefakt separat geprüft |
| Originalpipeline | **GETESTET:** ursprüngliche CLI in isolierter Kopie, 6.312 Featurezeilen und identische Referenzkennzahlen |
| Compose und Portainer-Export | **GETESTET:** Konfiguration gültig; image-only Export mit gleicher Env vollständig identisch aufgelöst |
| Ubuntu-Anleitungsbefehle | **STATISCH GEPRÜFT:** Bash-Syntax im Linux-Container geprüft; keine Ausführung auf Ubuntu behauptet |
| Backend-/Frontend-Images | **GETESTET:** tatsächlich gebaut; hashgelockte CPU-Abhängigkeiten / gelocktes React-Frontend |
| PostgreSQL im eigenen Docker-Projekt | **GETESTET:** healthy, vier Migrationen, 5 Aktien, je 6.312 Preise/Features, wiederholter Import ohne Inserts |
| Datenbankrechte / Schreibpfade | **GETESTET:** API-SELECT-Rolle, Runtime/Daten/HF-Cache für UID 10001 schreibbar |
| Historische Research-Replays | **GETESTET:** 10 gespeichert, Wiederholung ausschließlich reused; research_only / kontrafaktischer Replay |
| News-/Outcome-/Revisionsspeicher | **GETESTET:** Schema und isolierter Speicherrundlauf; keine fachlichen Live-Datensätze behauptet |
| HTTPS / Anmeldung / API | **GETESTET:** Zertifikatsprüfung im HTTP-Smoke, 401 ohne Auth, 200 lesend, 403 schreibend, Docs 404 |
| React → Nginx → FastAPI → PostgreSQL | **GETESTET:** zusätzlicher echter Edge-Browser-Smoke, Screenshots `.runtime/m43-docker/` |
| Container-Neuerstellung | **GETESTET:** Kurshistorie, Research-Fingerprint, Counts und TLS-Zertifikat unverändert |
| FinBERT im Linux-Container | **GETESTET:** expliziter Download der fixierten Revision; CPU-Inferenz offline vor/nach Neuerstellung, Prozesscache hit beim zweiten Text |
| Provider-/Current-Aktivität | **GETESTET:** 0 protokollierte Providerabrufe, 0 Current-Forecasts, Scheduler inaktiv, T0 null |
| Ubuntu / Tunnel / Portainer-Übernahme | **BLOCKED / NICHT AUSGEFÜHRT:** echte Server-Abnahme steht aus |
| Vollständiger Backup-Restore / spätere Updates | **VORBEREITET:** Befehle dokumentiert, vollständiger Restore und Upgrade-Rollback noch nicht praktisch abgenommen |
| Reale News / aktuelle Marktdaten / prospektive Outcomes | **NICHT AUSGEFÜHRT:** absichtlich deaktiviert, keine Live-Abnahme |

FinBERT-Smoke mit synthetischem englischen Text: positiv `0.954476774`, negativ
`0.026258526`, neutral `0.019264739`, Summe ungefähr 1, Score `0.928218247`.
Peak-RSS initial 891,7 MiB, spätere Cacheprüfung nach Neuerstellung 894,3 MiB.
Die Inferenz ersetzt weder Provider-Integration noch Sprach-/Lizenzabnahme
echter Nachrichten.

PostgreSQL-Livebereich: News 0, Outcomes 0, Market-Runs/Beobachtungen/Revisionen 0,
Forecasts 10 ausschließlich historische Replays. Identischer Research-Fingerprint
vor/nach Neuerstellung:
`249e55df4f54a16e4fa831ce0e513487e5b591cd18ee3ce58ab5a64a33ac9412`.

Im ersten erweiterten Docker-Lauf war die Tabellenregistrierung der
Marktdaten-Speicherprobe unvollständig (`KeyError`). Der Import wurde korrigiert,
das Backend neu gebaut und beide vollständigen Smoke-Läufe einschließlich
Cacheprüfung bestanden. Ein initialer eingeschränkter lokaler Pytest-Lauf wurde
abgebrochen; die erfolgreiche Gesamtsuite lief anschließend mit den für lokale
Server-/Containerprüfungen erforderlichen Rechten. Keine fehlgeschlagenen
Zwischenläufe werden als bestandene Tests gewertet.

## 11. Geänderte Dateien und verbleibende Grenzen

Neu: `compose.preview.yaml`, `sql/migrations/004_market_observations.sql`,
`src/platform/docker_preview.py`, `tests/test_docker_preview.py`, dieses Dokument.
Erweitert: `Dockerfile`, `scripts/configure_docker.py`, `scripts/docker_admin.py`,
`scripts/docker_smoke.py`, `scripts/docker_browser_smoke.mjs`,
`src/platform/{config,api,market,current_forecasts,maintenance}.py`,
`frontend/src/{App.tsx,api.ts}`, PostgreSQL-Migrationserwartung im Test,
`README.md` und `docs/docker-deployment.md`.

Die sechs eingefrorenen Feature-/Modellmodule, ursprüngliche Raw-Snapshots,
Forschungsberichte, v1-Protokoll, lokale Modellartefakte und Registry bleiben
erhalten. Keine neuen Abhängigkeiten, keine neue Weboberfläche. Drei bereits
vorher untracked vorhandene Dokumente bleiben unverändert außerhalb dieses
Commits: `M24_RUNTIME_ACCEPTANCE.md`, `M24_RUNTIME_PREFLIGHT.md`,
`M3_2_DEVELOPMENT_ASSESSMENT.md`.

**Lokale Windows-Entwicklung bleibt unterstützt:** bestehende `.env`, `.venv`,
`SI_MODE=demo`, `python -m uvicorn src.platform.api:app --host 127.0.0.1 --port 8000`
und `pnpm dev` im Frontend verwenden. Kein Docker notwendig; vorhandene
Konfiguration nicht durch `.env.preview` ersetzen. Native Windows-Modelle
weiterhin nur mit ihrem passenden Laufzeitvertrag laden.

Für eine spätere Current-Aktivierung ist ein eigener Meilenstein nötig:
Providerrechte und echte Abrufe abnehmen, Point-in-Time-/Revisionsdaten prüfen,
kompatible eingefrorene Modellversionen und prospektiven Plan bestätigen,
manuellen Forecast-/Outcome-Durchlauf validieren, erst danach begrenzten
Scheduler aktivieren. Das Preview-Overlay bewusst beibehalten, solange diese
Abnahme fehlt. Keine Flags hier pauschal einschalten; keine Trading-Ausführung.

Nächster praktischer Schritt: nach GitHub-Push-Freigabe Preflight und
CLI-Erstinstallation auf Ubuntu durchführen, Abnahmelauf protokollieren und
erst anschließend optional dieselben eigenen Ressourcen in Portainer verwalten.
