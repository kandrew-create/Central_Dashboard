# Collector on WSL 2 and Docker

[Verification and remaining commissioning steps](collector-wsl-docker-verification-2026-11-01.md).

The Collector can run its CLI and scheduler on Linux, including Docker Desktop's WSL 2 engine. The separate Central Server remains on its own PC. Use `deploy/docker-compose.collector.yml` on the Collector PC; the Central Server uses `deploy/docker-compose.yml` on the server PC. This does not install PostgreSQL or migrate the SCADA database.

The Docker Collector runs as UID/GID 10001, opens no network listener, and retains settings, checkpoints, logs and unconfirmed uploads in a named volume. A second named volume holds its encryption key and is mounted read-only during normal operation. Windows credentials continue to use current-user DPAPI; Linux credentials use authenticated Fernet encryption and private file permissions. Copying Windows DPAPI files into a Linux container will not unlock them.

The Collector Compose services use Docker init forwarding so Stop also reaches a
process still starting Python. The separate `test` image includes packaging inputs
and runs as UID/GID 10001; use it with an explicitly disposable PostgreSQL cluster.
See the [Collector QA review](collector-qa-2026-11-03.md) for verification and limits.

Future Windows GUI and CLI builds bundle an allowlisted Docker build context and
both Collector Compose files, including support for the CLI's `gui` command. Their handoff mount uses
`%LOCALAPPDATA%\Linker\Collector\handoff`, which remains available after the onefile
manager closes. The source checkout keeps its existing `collector-handoff/` path.
Building this GUI does not initialize Docker volumes or publish a new installer.

## Prepare this Collector PC

Start Docker Desktop, enable its WSL 2 engine and select Linux containers. Commands below run from the repository root in PowerShell or an integrated WSL distribution. Docker Desktop also supports these Docker commands from Windows without installing an additional Linux distribution. See [Docker's WSL 2 setup](https://docs.docker.com/desktop/features/wsl/).

Run `powershell.exe -NoProfile -ExecutionPolicy Bypass -File deploy/collector/install-shortcut.ps1` to install the single **SCADA Collector - WSL Docker** Start menu shortcut. Its setup, source previews, credentials, collection/upload and Docker status pages all manage the same container configuration and volumes. **Start Collector** starts its schedule; **Stop Collector** stops it normally; closing the GUI leaves the container running. No native Windows/tray scheduler is started. The installer removes the earlier separate manager shortcuts. Complete first-time Docker commissioning below before collecting.

Open Docker Desktop and wait for its Linux engine before using the manager. Refresh reports an unavailable engine as status rather than a generic alarm. Stop with an unavailable engine reports that no stop command was sent and cannot claim a confirmed stop. Start/Stop remain disabled after an unavailable-engine result until Refresh finds the engine ready. Actual container-stop failures still report errors. Raw Docker output is private. The local management helper runs one request from stdin with logging disabled and no administration port; source reads stay read-only. Reopening settings detects edits made by another manager before further actions.

Management commands pin the local Docker Desktop Linux named pipe on Windows (the local Unix socket on Linux) and project `linker-collector`. Inherited Docker/Compose routing overrides cannot redirect credentials or select different operational volumes. Local routing regression checks passed on both Windows and Linux.

The source GUI uses `deploy/docker-compose.collector.yml` plus `deploy/docker-compose.collector.host.yml`. Enable **Docker Desktop → Settings → Resources → Network → Enable host networking** for a source on this Windows PC. This allows the container to use the existing `localhost` source connection without changing SCADA listeners, access rules or TLS settings. Both Compose files must be selected for equivalent CLI operations:

```powershell
docker compose -f deploy/docker-compose.collector.yml -f deploy/docker-compose.collector.host.yml config --quiet
docker compose -f deploy/docker-compose.collector.yml -f deploy/docker-compose.collector.host.yml ps
```

The base Compose file alone remains usable for separately commissioned bridged deployments to remote sources with TLS. Do not enable host networking as a substitute for remote-source TLS or start a second Collector for the same identity.

```powershell
docker info
docker compose -f deploy/docker-compose.collector.yml config --quiet
docker compose -f deploy/docker-compose.collector.yml build collector
docker compose -f deploy/docker-compose.collector.yml run --rm key-init
docker compose -f deploy/docker-compose.collector.yml run --rm collector init
docker compose -f deploy/docker-compose.collector.yml run --rm collector check-config
```

Run `key-init` and `init` only for a new installation. Both refuse to overwrite existing material. Collection and upload start disabled. The container's configuration is `/var/lib/linker-collector/setup/config.toml`. Its named volumes are `linker-collector_collector-data` and `linker-collector_collector-key`. Changing the Compose project name selects different volumes; use the same project name for normal maintenance. Keep both volumes and securely back up the key separately from encrypted credentials. Never use `down --volumes` for an operational Collector.

The ignored `collector-handoff/` folder is mounted read-only at `/handoff`. Use this folder for a password-encrypted `.linker-collector` file exported for the existing source on the Central Server. Keep its unlock password outside the folder and enter it only at the hidden prompt. `COLLECTOR_HANDOFF_DIR` can select a different host directory before running Compose.

## Configure the local source

For a new installation, copy `collector/config.example.toml` to `collector-handoff/config.toml` and edit its database, timezone, history/privacy policy, limits and schedule. Leave source/generation IDs blank and collection disabled until commissioning. Do not put passwords in TOML. The existing GUI guide explains the [collection policies](../collector/README.md#collection-modes-and-coverage).

Apply this locally edited configuration before importing server setup. This command validates TOML and saves through the same service as the GUI. Stop the Docker scheduler first if it is running. Use it for initial commissioning only; later edits must preserve source identity and collection policy for existing state.

```powershell
docker compose -f deploy/docker-compose.collector.yml run --rm --entrypoint python collector -c "from pathlib import Path; from dataclasses import replace; from collector.config import load_config; from collector.desktop import DesktopService; old=load_config('/var/lib/linker-collector/setup/config.toml'); edited=load_config('/handoff/config.toml'); DesktopService().save(replace(edited,path=old.path),old)"
docker compose -f deploy/docker-compose.collector.yml run --rm collector set-password
docker compose -f deploy/docker-compose.collector.yml run --rm collector test-connection
```

Inside a container, `localhost` means the container. With Docker Desktop, use `host.docker.internal` for an approved database on the Windows host, or the database's actual reachable hostname. Non-loopback source connections require TLS (`verify-full` is preferred); keep the existing restriction that `sslmode = "disable"` is allowed only on loopback. A Windows database bound only to loopback or without approved TLS is not automatically reachable from a container. Commission this access separately or continue using the native Windows Collector. Do not change a SCADA database's listeners, access rules, indexes or schema as part of this application setup. WSL native networking differs by NAT/mirrored mode; see [Microsoft's WSL networking guide](https://learn.microsoft.com/en-us/windows/wsl/networking).

Do not run the Windows Collector and Docker Collector against the same source at the same time. Their separate state directories cannot share a scheduler lock. Moving an existing installation requires an explicitly authorized, stopped transfer of the entire queue/checkpoints and re-protection of credentials, not an empty replacement state directory. The migration receiver refuses assigned Docker identities, bound state, pending target uploads or an active target scheduler. An unassigned initial Docker setup is archived in its volume before the complete transferred setup replaces it; the existing Linux key is retained.

The 2026-11-02 commissioning on this PC transferred the native profile's SQLite state with an exact SHA-256 match, including its identity, receipts, checkpoints and schedule. Database/upload credentials were re-encrypted in memory/stdin using the existing Linux key. The original Windows state and old Docker setup remain preserved. A `docker-runtime.json` marker and disabled native collection prevent accidental reuse of the old runtime. Docker-side source checks, alarm/event previews and HTTPS authentication passed. See [handoff evidence](../deploy/collector-setups/README.md). Private PC-specific transfer helpers and reports remain under ignored `.tools/`; they are not portable CI infrastructure.

The actual Docker-backed GUI loaded 5 alarms and 1 event and passed **Test server**. Closing the real manager left the container running and another 60-second cycle completed with no error or pending batches. The container runs as UID/GID 10001 with a read-only root filesystem, preserved data/key volumes, `unless-stopped` restart policy and no published ports. Windows checks passed 53 tests, with 5 Linux-only migration tests skipped; those migration tests ran in the Linux suite against a separate disposable PostgreSQL 17 cluster (139 passed, 43 Windows/desktop checks skipped). A new live source change's Docker upload, detailed machine mapping and outage/reboot recovery remain unverified; existing records were deduplicated rather than resent to manufacture upload evidence.

## Connect to the Central Server PC

On the Central Server PC, keep the existing source registration. In Network mode, save that PC's reachable hostname/IP and port, start it, then export fresh encrypted setup for this source. The certificate must cover the advertised address, for example `https://192.168.10.5:8443/v1/uploads`. Do not use the Collector PC address as the server listener or disable certificate verification.

Place the exported file in `collector-handoff/`, then run, replacing `source.linker-collector` with its filename:

```powershell
docker compose -f deploy/docker-compose.collector.yml run --rm collector import-setup /handoff/source.linker-collector
docker compose -f deploy/docker-compose.collector.yml run --rm collector test-server
```

Import retains the local source connection and extraction policy, protects the upload token using the mounted key and saves the CA with a Linux path. Identity, pending-queue and scheduler-lock guards remain in effect. `test-server` verifies TLS, the credential and active source/generation without reading source records, uploading history or advancing checkpoints. The CLI also exposes this command on Windows.

After source and server checks pass, locally approve the collection history and enable collection in the saved configuration. For a single bounded cycle and status:

```powershell
docker compose -f deploy/docker-compose.collector.yml run --rm collector collect
docker compose -f deploy/docker-compose.collector.yml run --rm collector status
```

For the automatic scheduler:

```powershell
docker compose -f deploy/docker-compose.collector.yml up -d collector
docker compose -f deploy/docker-compose.collector.yml logs --tail 30 collector
docker compose -f deploy/docker-compose.collector.yml stop collector
```

Stop sends SIGTERM; the scheduler signals cancellation between bounded operations and retains pending batches. Compose gives it 120 seconds to exit. Check actual bounded-operation settings if shutdown exceeds that allowance. Docker restart policy takes effect while Docker Desktop/its engine is running; Windows boot/login startup of Docker Desktop must also be commissioned. See [Compose stop behavior](https://docs.docker.com/reference/compose-file/services/#stop_grace_period).

Confirm both delivery and Central Server processing/quarantine status. A committed receipt confirms storage; unknown mappings remain quarantined. Perform outage/recovery checks on an isolated fixture server, or arrange a maintenance window before stopping an active shared server. Multiple Collector PCs remain supported, each with its own source registration/setup.

## Native WSL CLI

In an approved Linux distribution with Python 3.12/3.13, install `.[collector]` in a Linux virtual environment. Keep the private setup and key on the Linux filesystem, where ownership and mode 600/700 are enforced. An example after activating that environment:

```sh
mkdir -m 700 -p "$HOME/.config/linker-collector"
python -m collector create-key "$HOME/.config/linker-collector/collector.key"
export COLLECTOR_SECRET_KEY_FILE="$HOME/.config/linker-collector/collector.key"
python -m collector --config "$HOME/.local/share/linker-collector/setup/config.toml" init
```

Edit the new configuration, run `set-password`, `import-setup PATH`, `test-connection` and `test-server` with the same global `--config` argument, then commission `collect`/`run`. Missing, incorrect or overly permissive key files fail closed. The application never generates a replacement key during credential loading.
