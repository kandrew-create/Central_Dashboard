# Collector on WSL 2 and Docker

[Verification and remaining commissioning steps](collector-wsl-docker-verification-2026-11-01.md).

The Collector can run its CLI and scheduler on Linux, including Docker Desktop's WSL 2 engine. The separate Central Server remains on its own PC. Use `deploy/docker-compose.collector.yml` on the Collector PC; the Central Server uses `deploy/docker-compose.yml` on the server PC. This does not install PostgreSQL or migrate the SCADA database.

The Docker Collector runs as UID/GID 10001, opens no network listener, and retains settings, checkpoints, logs and unconfirmed uploads in a named volume. A second named volume holds its encryption key and is mounted read-only during normal operation. Windows credentials continue to use current-user DPAPI; Linux credentials use authenticated Fernet encryption and private file permissions. Copying Windows DPAPI files into a Linux container will not unlock them.

## Prepare this Collector PC

Start Docker Desktop, enable its WSL 2 engine and select Linux containers. Commands below run from the repository root in PowerShell or an integrated WSL distribution. Docker Desktop also supports these Docker commands from Windows without installing an additional Linux distribution. See [Docker's WSL 2 setup](https://docs.docker.com/desktop/features/wsl/).

Run `powershell.exe -NoProfile -ExecutionPolicy Bypass -File deploy/collector/install-shortcut.ps1` to install the single **SCADA Collector - WSL Docker** Start menu shortcut. Open its **Docker deployment** page for Start, Stop and Refresh controls. It also contains local connection setup, source previews and collection/upload pages. Docker settings/queue remain separate from local Windows settings/queue. The installer removes the earlier separate Docker-manager shortcuts. Complete first-time Docker commissioning below before collecting.

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

Do not run the Windows Collector and Docker Collector against the same source at the same time. Their separate state directories cannot share a scheduler lock. Moving an existing installation requires a stopped, reviewed transfer of the entire queue/checkpoints and re-protection of credentials, not an empty replacement state directory. No automatic Windows-to-Linux state migration is provided.

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
