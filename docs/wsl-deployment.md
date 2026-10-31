# Central Server on WSL 2

For guided installation without Windows Python, use the separate [WSL / Docker package installer](wsl-installer.md). It prepares prerequisites, a private Linux GUI environment, the Docker server and its shortcut; the manual/development workflow below remains available.

This development deployment runs Central Server 0.6.2 in Linux containers through Docker Desktop's WSL 2 backend. PostgreSQL, the ingestion API, the worker and Caddy HTTPS run in Linux. The Windows Central Server installation and its operational data remain separate. The current WSL deployment uses Network mode with the same endpoint saved by Windows: `https://187.17.53.84:8443/v1/uploads`. The earlier loopback deployment is documented below as installation history.

The native **Central Server - WSL / Docker** management window uses Qt through WSLg, with smooth fonts, sidebar navigation, an overview of service health and saved-record counts, and clear source/setup actions. It controls this Compose project and supports source registration, encrypted collector setup export, credential replacement, confirmed source deletion and saved identification results. Alarm AI is not configured. Network mode supports multiple collector PCs; each actual remote PC still needs a successful Collector **Test server** check before commissioning is complete. There is no web dashboard. Mapping approval remains an administration CLI operation; see [Linux operations](operations.md#central-linux-deployment).

## Open and use the GUI

On this PC, double-click **Central Server - WSL Docker** on the Windows desktop. This opens the Linux manager, with a different title from the preserved Windows manager. Keep Docker Desktop running.

From Ubuntu, the equivalent command is:

```bash
bash ~/central-server/deploy/wsl/launch-manager.sh
```

1. **Overview:** refresh health and saved-record counts, start the Docker services, or stop this project. The overview also shows failed processing jobs, the upload endpoint and a Copy URL action. Closing the window leaves Docker services running. A stopped database remains available to start; opening the GUI does not start services or create sources automatically.
2. **Register source:** enter customer, site, project, machine tag and SCADA PC/database source name, or select existing registry items. Register each database source separately. Registration creates its IDs and an encrypted local credential without contacting a SCADA database. An unfinished registration is confirmed before closing the window.
3. **Sources & setup:** select the registered source and export a new `.linker-collector` file with a password of at least 12 characters. The default export folder is `/home/station7/central-server/exports`, accessible in Windows Explorer as `\\wsl.localhost\Ubuntu\home\station7\central-server\exports`. Transfer the file and password separately, then import it into a separately configured Windows Collector. Credential replacement preserves earlier credentials; confirmed deletion revokes credentials while retaining received data and audit history. A refresh preserves the selected identity when it still exists and clears selection when it has been removed.
4. **Deployment:** shows the saved connection mode, HTTPS listen address, project, workspace, collector endpoint and export folder. Database paths remain managed inside Docker. This page displays the saved configuration; it does not provide editable Windows settings controls.
5. **Identification:** reads up to 200 saved equipment results with original-message evidence. There are no model-enable controls in this Docker manager, and reading or selecting this page never calls a model. Event identification uses the registered machine tag.

The bottom status message and animated activity indicator remain visible across pages and at minimum window size. Docker/database work runs outside the GUI thread. Optional identification errors stay on that page without replacing successful operation feedback; selecting it during another operation defers its reads. Setup passwords are confirmed and cleared from their input fields after use or cancellation.

Keep an existing assigned Collector's IDs, local queue and configuration intact. Use a separate Collector setup for this fresh server, or plan a migration before changing a live Collector. Use **Test server** before **Collect now**. Successful receipt still does not imply approved machine mapping or completed processing.

## Install the GUI from source

The current PC uses a separate Python 3.13.18 environment at `.venv-gui`; Ubuntu's system Python 3.14 is not used for this application. Install [uv for Linux](https://docs.astral.sh/uv/getting-started/installation/) and WSLg support, then from the Linux workspace:

```bash
sudo apt-get install libegl1 libopengl0 libxcb-cursor0 libxcb-icccm4 \
  libxcb-image0 libxcb-keysyms1 libxcb-render-util0 libxcb-xinerama0 libxkbcommon-x11-0
bash deploy/wsl/install-gui.sh
bash deploy/wsl/launch-manager.sh
```

If uv is not on PATH, set `UV_BIN` to its Linux executable when running the installer. The script creates a supported Python environment, installs the application with the `docker-gui` extra (PySide6 Essentials), and builds the `migrate` image containing the management agent. It does not start services, register a demo source or replace Windows packages. Qt uses the system's smooth font rendering; the installed Ubuntu Sans fonts are used on this PC. The window was visually verified through WSLg's Wayland platform. The earlier Tk manager remains in the source as a fallback (`python -m server.management.docker_gui`), but the desktop shortcut and shell launcher open the modern Qt window.

Management uses the local Docker Unix socket and only the selected Compose project. Database operations run as short-lived commands in the migration image using its Central-only database connection. No management listener, public administration route or published PostgreSQL port is added. Command arguments never contain unlock passwords or upload tokens; requests use stdin. Logging is disabled for these management containers so displayed records and operator text are not copied into Docker logs. Actual errors are reduced to safe messages. Registration, export and credential changes retain the existing database transaction and rollback behavior.

Linux setup credentials are encrypted with AES-GCM in `secrets/docker-manager/*.vault`, with a private `vault.key`. The directory is mode 0700; key and vault files are mode 0600 and owned by the local Linux account. This protection relies on Linux filesystem ownership and trusted local Docker access; it does not use Windows DPAPI. Preserve the key and matching vault files in encrypted recovery material alongside database and configuration backups. Missing keys are never silently replaced when vault files exist. Exported `.linker-collector` files continue to use the shared password-encrypted setup format.

## Local installation

Docker Desktop 4.97.0 was installed per user on 2026-10-31. Its installer matched the WinGet SHA-256 and had a valid Docker Inc. signature. The Linux engine reports Docker 29.9.2; Compose reports 5.6.1. Installation and WSL integration are described in the [Docker guide](https://docs.docker.com/desktop/features/wsl/).

Ubuntu 26.04.1 LTS is initialized with local user `station7`, and Docker Desktop integration is enabled for Ubuntu. The active source workspace is in Ubuntu:

```text
/home/station7/central-server
```

From Windows Explorer, that workspace is available as `\\wsl.localhost\Ubuntu\home\station7\central-server`. It is a source snapshot outside the repository. Changes to the repository do not automatically update the deployed image. Docker Desktop stores the database and certificate volumes in its Linux storage; the application source and Caddy configuration are in Ubuntu's filesystem.

The dedicated Compose project is `linker-scada-wsl`. Its `.env` contains distinct random migration, API and worker passwords. The Linux workspace is mode 0700 and `.env` is mode 0600, owned by `station7`. The initial staging snapshot, public CA export and Windows management wrapper remain at `%LOCALAPPDATA%\Linker\central-server-wsl` with private Windows ACLs. Do not print `.env`, commit it, or copy it into release artifacts.

The saved override `deploy/docker-compose.wsl.yml` now publishes only `187.17.53.84:8443:443`, matching the Windows HTTPS listener. The initial local override used loopback ports 80/443. The database and API have no directly published ports. The existing Windows firewall allowance is retained; no additional firewall or port-forwarding rule was added.

## Start, stop and inspect

Keep Docker Desktop running. From Windows PowerShell:

```powershell
$wslServerManager = Join-Path $env:LOCALAPPDATA 'Linker\central-server-wsl\manage.ps1'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File $wslServerManager Status
powershell.exe -NoProfile -ExecutionPolicy Bypass -File $wslServerManager Stop
powershell.exe -NoProfile -ExecutionPolicy Bypass -File $wslServerManager Start
```

Or, from Ubuntu:

```bash
~/central-server/manage.sh status
~/central-server/manage.sh stop
~/central-server/manage.sh start
```

Use `Logs` in Windows or `logs` in Ubuntu to inspect recent component logs locally. The Windows wrapper delegates to Ubuntu's helper; both target only `linker-scada-wsl`. Stop preserves the database, credentials and certificates. Do not use `down --volumes`, remove the named volumes, reset Docker Desktop, or unregister its WSL distribution as routine troubleshooting.

Direct commands from a PowerShell window opened before Docker installation may need the installed Docker `resources\bin` directory added to their process PATH, including `docker-credential-desktop`. The management wrapper uses Ubuntu's Docker integration instead.

Container restart policies do not start Docker Desktop itself. Automatic launch at Windows sign-in has not been commissioned. After a restart, open Docker Desktop, then use `Start` and check `Status`.

## HTTPS and collector setup

The current upload endpoint, matching the saved Windows configuration, is:

```text
https://187.17.53.84:8443/v1/uploads
```

The exported public CA certificate is:

```text
%LOCALAPPDATA%\Linker\central-server-wsl\caddy-root.crt
```

Configure that file explicitly in a collector connecting to this server. The private CA key remains in the `linker-scada-wsl_caddy-data` volume. Certificate verification must remain enabled. Caddy's local certificate authority and client trust requirements are explained in the [Caddy guide](https://caddyserver.com/docs/automatic-https#local-https).

The HTTPS root and `/health` return 404 through Caddy: the gateway exposes only POST requests to `/v1/uploads` and `/v1/collector-check`. API health is checked internally by Compose. A browser opening `https://187.17.53.84:8443/` is not a server-management interface.

This database currently has one registered source and no uploaded records. Do not redirect an existing Windows-assigned collector or replace its IDs, queue or credentials to test this server. Reuse the existing WSL source when appropriate, register each additional database source separately, or use a planned migration that preserves the existing Windows identities and receipts.

For collectors on other PCs, use the current Network endpoint and export that source's setup from WSL. `localhost` on a remote collector refers to that collector. WSL NAT/mirrored networking and firewall requirements are described in [Microsoft's networking guide](https://learn.microsoft.com/en-us/windows/wsl/networking). Verify Test server on every actual collector PC before declaring remote operation commissioned.

The existing Windows database uses PostgreSQL 18; the Compose template uses PostgreSQL 17.6. Never copy the Windows database directory into this container. Moving its records and credentials requires a separate backup/restore and credential recovery procedure.

## Verification evidence — 2026-10-31

- Repository Compose template and the local configuration passed `config --quiet`.
- The application image built successfully with Python 3.12 and application version 0.6.2.
- Migration and runtime-login setup jobs exited with code 0; the schema is at `0009_source_schema_names`.
- PostgreSQL and the API became healthy. Internal API health returned `{"status":"ready"}`; the worker connected as `scada_worker_login`.
- API and worker logins are not members of the private storage-owner role.
- HTTPS requests from Windows verified the server certificate using the exported CA. The gateway root returned 404; unauthenticated uploads, unauthenticated collector checks and a synthetic invalid credential returned 401.
- Database queries confirmed zero source registrations and zero saved uploads. No customer records or live collector traffic were used.
- Scoped stop/start succeeded. Moving the workspace into Ubuntu reused the existing project volumes; only Caddy needed recreation for its new configuration mount. The PostgreSQL system identifier and CA certificate remained identical, and HTTPS checks passed again afterward.
- Native GUI, Docker command boundaries, Linux vault protection and inherited GUI behavior: 42 checks passed on Ubuntu; one Windows process-identity check was skipped. Four Linux administration integration checks passed on each disposable PostgreSQL 17 and 18 cluster. Nine Windows manager database regression checks passed on a disposable PostgreSQL 18 cluster.
- A separate disposable Compose project verified the actual Docker transport for registration, encrypted vault storage, mounted setup export, credential replacement and soft deletion. The real WSL project was then stopped and started through the new adapter; its database identity, CA, zero source registrations and zero uploads were retained.
- The native WSLg window was opened and its layout inspected. Windows application, installer, saved manager configuration and protected credentials are checked against their pre-GUI SHA-256 hashes. No Windows package was rebuilt or replaced.

Local evidence and source archives are under `%LOCALAPPDATA%\Linker\wsl-setup` and the deployment workspace. The GUI adds no database migration or upload-protocol change. No broad full-repository test suite was run. On Windows, two new Linux-window checks encountered the local Tcl initialization issue; the complete native GUI checks executed on Ubuntu. Successful real Collector uploads, source processing in this deployment, remote-PC connectivity, AI, migration of Windows data and unattended startup remain unverified.

### Qt visual refresh — 2026-10-31

The default WSL launcher now opens the Qt window with a dark navigation sidebar, light cards, service indicators, readable typography, source empty states, consistent forms and a fixed activity footer. Overview, registration, sources, deployment, identification and minimum-size layouts were rendered and inspected through WSLg. No bitmap theme assets or additional network services are used.

Eleven Qt workflow checks and eight Docker adapter checks passed on Ubuntu, covering background work, feedback preservation, registration validation/reuse, explicit stop/deletion confirmation, source-selection identity, password handling, export dispatch, original-message evidence and minimum-size navigation. The eleven Qt checks were skipped in the Windows environment because the optional Qt dependency is not installed there; all eleven executed on Ubuntu. The Docker administration layer, database schema and upload protocol are unchanged in this appearance update, so database integration suites were not repeated for it. The Qt dependency remains optional for Windows installations.

Ubuntu's user setup is complete as `station7`; it is separate from Docker Desktop's `docker-desktop` distribution. Both distributions are retained. Do not reset either distribution as routine troubleshooting.

## Match the saved Windows network endpoint

The WSL connection configuration now accepts explicit `LINKER_MODE=network`, `SCADA_HOSTNAME`, `LINKER_LISTEN_ADDRESS` and `LINKER_HTTPS_PORT` values from its private `.env`. Local mode remains the default for a fresh installer. The current saved Windows mode is Network, its host/listener is `187.17.53.84`, and its HTTPS port is 8443. Only these connection settings are matched; the Windows data directory, PostgreSQL binaries, database and identities are not copied into Linux.

For another approved deployment, stop the configured Docker project and close its manager before editing. Back up `.env`, the existing override and `secrets/docker-manager`, alongside database/certificate recovery material. Preserve all database passwords/URLs. Set only the connection fields:

```dotenv
LINKER_MODE=network
SCADA_HOSTNAME=187.17.53.84
LINKER_LISTEN_ADDRESS=187.17.53.84
LINKER_HTTPS_PORT=8443
```

The listener must belong to the Windows Docker host. Copy `deploy/wsl/docker-compose.network.yml.template` to `deploy/docker-compose.wsl.yml` after preserving the prior override, validate the selected Compose configuration and rebuild/recreate its containers. This template publishes only HTTPS on that explicit host address; PostgreSQL and API ports remain private. It mounts `deploy/wsl/Caddyfile.network`, which uses the existing Caddy internal CA to issue a certificate for the saved hostname/IP. Certificate verification remains enabled. Docker Desktop forwards published ports through its host backend; see [Docker networking](https://docs.docker.com/desktop/features/networking/) and [publishing to a specific host address](https://docs.docker.com/engine/network/port-publishing/).

The manager and encrypted collector exports use the saved hostname and port. Network exports set `local_test_only=false` and retain the selected source/generation/token; changing an endpoint does not replace source credentials. Setup reruns preserve an existing valid Network configuration and its override. The Caddy network configuration sets [default SNI](https://caddyserver.com/docs/caddyfile/options#default-sni) to the saved host so IP-based clients that omit SNI still receive the matching certificate; hostname/IP verification remains enabled.

The Windows server must remain stopped while WSL owns its endpoint. Preserve its installer and data for recovery. The same URL does not make the two databases interchangeable: the Windows CA, source identities and pending Collector batches are not migrated by a connection change. Do not overwrite a live Collector's assigned IDs/queue to switch servers. Use a planned data/identity migration when continuing an existing Windows-assigned Collector.

### Network verification — 2026-10-31

The change was exercised first on an isolated Docker project and alternate port, including certificate validation, network-mode encrypted setup export and retained source/credential state. The live project was then updated and reopened at `https://187.17.53.84:8443/v1/uploads`. TLS checks passed from Ubuntu and Windows, and an authenticated collector check returned ready without uploading records. Its single source, generation, credential verifier/vault/key, database identity, storage registry, unrelated settings and Caddy CA matched pre-change fingerprints; batches and record versions remain zero. The schema remains at `0009_source_schema_names`.

The existing deployment had stale Docker labels referring to the earlier Windows staging path. Matching credentials and the three expected named volumes were verified before recreating only the stopped project containers with current WSL paths. The owned `secrets` parent was restricted from 0755 to 0700; its protected files were retained. Protected pre-change configuration, credential state, fingerprints and a Central database dump remain under the private Linux `secrets/network-before-*` directory.

Thirty-five Linux installer/adapter/vault/Qt checks passed, including the Network deployment display. Six administration integration checks passed on each disposable PostgreSQL 17 and 18 cluster; nine Windows manager regression checks passed on disposable PostgreSQL 18. Fifteen Windows package/adapter checks passed, with five Linux filesystem checks skipped on Windows and executed on Ubuntu. The rebuilt WSL installer retains this Network configuration; earlier packages remain intact. The existing Windows firewall allowance for HTTPS 8443 from collector PC `187.17.53.218` was retained; no broad firewall rule was added. Connectivity from that actual remote PC remains unverified.
