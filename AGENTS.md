# AGENTS.md

## Project context

This repository contains the Linker SCADA Collector and Central Server. Read [README.md](README.md) for the overview and the relevant application guide before changing behavior.

- `collector/`: Windows GUI, CLI, service wrapper, read-only SCADA extraction, durable local queue, and outbound HTTPS delivery. See [collector/README.md](collector/README.md).
- `server/`: Central Server management GUI, FastAPI ingestion, PostgreSQL storage, background worker, and migrations. See [server/README.md](server/README.md).
- `shared/`: Upload protocol and encrypted collector setup format. Changes here affect both applications.
- `deploy/`: Docker deployment, local commissioning helpers, and separate Windows builds for both applications.
- `tests/`, `collector/tests/`, `server/tests/`: Repository, unit, GUI, and disposable PostgreSQL integration checks.
- `docs/`: Specifications, operating guides, implementation evidence, and planned work.

## Architecture and data rules

- Keep SCADA source access read-only. Never apply migrations, restore backups, create indexes, alter schemas, or modify records in a SCADA source database. Collection must not affect machinery or SCADA operation.
- Collectors initiate uploads on locally configured schedules. Keep the collector free of network listeners and remote command/configuration mechanisms.
- Network mode supports multiple collector PCs uploading to one central HTTPS endpoint. Register each SCADA database source separately, provision its own setup/credential, and allow every intended collector PC through the firewall. Do not describe this mode as limited to two PCs.
- Central Server owns a separate PostgreSQL database. Preserve customer/source/machine identity and enforce customer isolation in application queries and database permissions.
- Preserve original alarm/event fields, source timestamps, separate milliseconds, and revision history. Flag uncertain ordering, timezones, and mappings instead of guessing values or current state.
- Preserve durable acceptance and replay behavior: acknowledge uploads only after commit, validate matching batch ID/hash/committed receipts, and retain unconfirmed local batches through faults and restarts.
- Keep unknown machine mappings quarantined until approved. Receipt and storage do not imply successful mapping or completed processing.
- Add new Alembic migrations for schema changes; preserve existing migration history.

## Credentials and local state

- Keep passwords, upload tokens, private TLS keys, raw customer records, and operator text out of source control, logs, and release artifacts. Use the existing protected credential and encrypted setup mechanisms.
- Encrypted `.linker-collector` setup exports remain ignored by default. The user explicitly authorized the single encrypted export `deploy/collector-setups/wsl-network-20261101-235729.linker-collector` in Git; stage this exception by exact filename only. Keep all unlock passwords, private viewers and decrypted contents outside Git. See [export handoff](deploy/collector-setups/README.md).
- Preserve existing collector settings, IDs, checkpoints, pending batches, and central data during routine development. Do not clear state to bypass a fault.
- `.tools/`, `collector-local/`, `.env`, and DPAPI files contain local operational state. `.tools/` helpers are ignored and may depend on this development PC; do not treat them as portable CI infrastructure.
- Consult [docs/central-server-windows.md](docs/central-server-windows.md) and [docs/operations.md](docs/operations.md) for commissioning and recovery. Development defaults are central PostgreSQL on loopback port `55441` and HTTPS on `8443`; check saved settings before assuming these values.

## Development commands

Use Python 3.12 or 3.13. Central Server supports PostgreSQL 17 and 18; run integration tests on disposable clusters for both versions when changing compatibility. Selected server tools must share a supported major version and match any existing `database/PG_VERSION`; changing binaries is not a data migration. Saved paths and existing data must be preserved. The following commands assume PowerShell, the repository root, and an existing `.venv`.

Install development dependencies:

```powershell
uv pip install --python .venv/Scripts/python.exe -e '.[collector,server,manager,test,local,build]'
```

Run tests:

```powershell
& .venv/Scripts/python.exe -m pytest -q
```

PostgreSQL tests require `SCADA_TEST_POSTGRES=1`, `PSQL`, `PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD`, and `PGDATABASE` configured for an explicitly disposable test cluster. They create/drop fixture databases and temporary roles. Never point them at a SCADA, customer, or active Central Server cluster. Windows/Tk/DPAPI checks require the appropriate Windows desktop environment; report skipped checks separately from executed checks.

Build Python distributions:

```powershell
uv build
```

Build Windows packages with PyInstaller and Inno Setup 6 installed:

```powershell
& deploy/windows/build.ps1
& deploy/windows/build-server.ps1
```

Both scripts accept `-Compiler` for a non-default Inno Setup compiler location. Collector executables go to `dist/collector`, Central Server to `dist/central-server`, and installers to `dist/installer`.

Current download links target revision X3: Central Server 0.6.1 with equipment identification and source-named alarm/event tables; Collector remains 0.4.0 with upload protocol v1. Publish installers and matching SHA-256 sidecars with release notes and verification links. Preserve earlier releases and local operational state. Tailscale uses the supported Network mode/HTTPS path; verify connectivity on each actual remote PC before describing it as commissioned.

The local 0.6.2 manager loads saved AI state/results on open and Equipment Identification tab selection (Local AI in earlier builds), including disabled state and configuration while the database is stopped. AI runs on the Central Server PC; the view includes up to 200 results from registered sources uploading to that server, including other collector PCs, and does not combine separate Central Servers. These reads must never enable AI or call a model. Defer tab reads during other work, keep I/O off Tk, preserve an unsaved model entry and successful settings-save feedback, and isolate optional AI read errors. See [AI display fix](docs/ai-display-refresh.md).

Central Server upgrades must stop the configured server before replacing files and preserve operational state. The installer uses the installed stop command before Restart Manager closes remaining processes; stop errors block the upgrade. Do not replace this with process-name-wide termination or stop an unrelated PostgreSQL service. Both Windows builds refresh SHA-256 sidecars for their executables and installer.

For Network mode startup faults, verify that the saved listener is assigned to this PC; the collector PC address is not a valid server listener. Inspect protected API/control logs before interpreting a long health wait as database initialization. Correct addresses with the configured server stopped, preserve data, and reopen a manager whose settings were changed externally.

Validate local listener availability before saving or starting, but never require it for loading/repairing settings or stopping the server. Failed starts must clean up their own newly launched API/worker components, retain data/credentials, and fail when either component exits. A stop on a never-initialized setup must not create state that blocks initialization.

Keep settings-save confirmation separate from server readiness: a post-save refresh must not overwrite successful persistence with an expected stopped-database message. Actual save errors and explicit status-refresh errors must still be shown.

Keep the Central Server bottom status bar visible across tabs and at minimum window size. Animate its activity indicator during background work, stop it on success or failure, and retain the final message, including settings-save confirmation after refresh.

Central Server labels use "Saved record versions" (including first copies). Managers omit the mapping-backlog counter and source-list count column; preserve backend counts, quarantine and mapping approval. Local AI interprets alarms only and must separate equipment from alarm conditions: "Conveyor VFD Connect Error" identifies "Conveyor VFD". A literal text match alone does not establish a correct equipment name. Show original-message evidence and leave unverified/condition-only labels uncertain. Events use the machine tag selected in Register SCADA source, constrained by the accepted upload scope; never infer events from messages or `ev_source`. Store results separately from native revisions and retain mapping approval. Apply identification migrations `0004`–`0006` only to Central storage.

Registration names are single-line labels: trim surrounding whitespace and fold pasted CR/LF/tab separators to spaces before enforcing the 1–255 character limit. Distinguish empty, overlength and unsupported-control-character errors. Validate new registration names before database work and preserve existing-item reuse and transaction rollback.

Source-registration GUIs select an existing machine only; do not restore the New machine tag entry or invent a fallback tag. Keep the customer/site/project filter and require a selected machine before backend work. Preserve existing machine IDs, credential scope and registered event identity; administrative/backend provisioning remains separate.

Source deletion is a confirmed registration removal in both operating modes: set `sources.deleted_at`, revoke its credentials and append an audit event atomically. Hide deleted sources from the manager; preserve identities, generations, mappings, committed data, jobs and protected setup files. Block setup export/credential replacement and authentication for deleted sources. Apply migration `0003_source_deletion` only to Central Server storage. Management startup must not create demo sources by default.

Collector setup import must not be blocked by unsaved fields supplied by the setup file itself (IDs, URL, upload enable flag and CA path). Import against the last saved local configuration; preserve unsaved database/history/schedule changes by requiring an explicit save, and retain identity/queue/scheduler-lock guards. Explain missing local setup and show protected-credential presence without displaying secrets; Test server verifies validity.

Collector Stop must signal both manual and automatic collection, wait for the current bounded operation, retain pending uploads, and refresh controls when the scheduler exits. Window closing must also signal a manual run; never terminate a process to bypass normal collection shutdown.

The current source Collector GUI manages one Docker runtime. Setup, credentials, previews, collection and status use the same Docker configuration/volumes through local stdin-only management containers with logging disabled. Pin the local Docker socket and `linker-collector` project; ignore inherited Docker/Compose routing overrides. Never start a native/tray scheduler from this manager. Closing it leaves Docker running; Stop Collector stops the selected container normally. Manual one-off closing must signal its scoped container and wait for bounded work.

Collector Docker Refresh/Stop report an unavailable engine as status without clearing source previews or falsely confirming a stop. Keep raw Docker output private. The Desktop deployment selects both Collector Compose files, including `deploy/docker-compose.collector.host.yml`, with Docker Desktop host networking enabled for the unchanged loopback SCADA connection. Never change a source listener/TLS setting to make migration work. A migrated Windows profile's `docker-runtime.json` blocks accidental native run/cycle reuse.

Both Docker Start buttons require saved, enabled collection and stored entered credentials. Import allows unsaved setup-supplied fields but blocks a running Docker scheduler and explains unsaved local edits. Collector containers use init forwarding. Windows GUI builds bundle an allowlisted Docker context through `deploy.collector.build_context`; use absolute PyInstaller data paths and a persistent handoff mount outside onefile extraction. See [Collector QA](docs/collector-qa-2026-11-03.md).

Collector 0.4.1 is installed on another PC; keep the operational Collector stopped on this Central development PC. Test only with mocked services or explicitly disposable profiles/clusters. Its separate Dockerfile is `deploy/collector/Dockerfile`; package only Collector/shared code and Collector dependencies, never Central Server or Ollama. Windows builds use fresh versioned `dist/collector/<version-id>` and `dist/installer/collector/<version-id>` folders with installer, context ZIP and SHA-256 sidecars, preserving earlier packages. Opening the app starts an installed Docker Desktop and resumes only a commissioned enabled setup; missing original volumes/key/configuration must never create an empty replacement. Existing native state without a migration marker blocks auto-start. Hide the upload URL and daily/weekly interval controls while retaining saved values; keys remain encrypted, masked on entry and never revealed. See [installation](docs/collector-installation.md) and [update evidence/RAM measurement](docs/collector-update-2026-11-04.md).

Collector Linux/WSL deployment uses `deploy/docker-compose.collector.yml`; see [setup and verification](docs/collector-wsl-docker.md). Preserve both state and encryption-key volumes. Linux credentials require a private, collector-owned `COLLECTOR_SECRET_KEY_FILE`; Windows DPAPI files are not portable to Linux. Never run native and container Collectors concurrently for one source or replace an existing queue with empty state. Validate the Collector Compose file separately; Central Server runtime builds select `base`, while test builds select `test`.

Validate the Docker Compose template without starting services:

```powershell
docker compose --env-file .env.example -f deploy/docker-compose.yml config --quiet
```

The WSL deployment uses Docker Desktop, project `linker-scada-wsl`, and `/home/station7/central-server` (0700; `.env` 0600). Its Qt/WSLg GUI launches with `bash deploy/wsl/launch-manager.sh`; the desktop shortcut is **Central Server - WSL Docker**. Use Python 3.13 in `.venv-gui` with the optional `docker-gui` extra. Keep I/O outside the GUI thread and retain activity/operation feedback. Management uses scoped commands with logging disabled and no admin port. Deployment settings are editable through the modern GUI; saves require a stopped project, while confirmed Apply/restart manages that interruption. Preserve the ai-settings and ollama-models volumes; reading AI settings/results never enables AI or calls a model. Preserve `secrets/docker-manager`, its key/vaults, both installations, volumes and Collector identities. Explicit Network settings use the Windows host listener and matching Caddy internal-CA certificate; exports must carry the saved endpoint and `local_test_only=false`. Keep the Windows server stopped when WSL uses its endpoint. PostgreSQL 17 stays private and separate from Windows PostgreSQL 18. Verify every actual remote Collector PC before declaring commissioning complete. See [WSL deployment](docs/wsl-deployment.md).

Docker manager startup reports safe engine/HTTPS-port/mount errors. A Caddyfile mount failure with an existing configuration file permits one gateway-only recreation and readiness retry, preserving named volumes. Never retry credential mutations or timeouts automatically, stop Windows processes by name, or change the saved endpoint to bypass a conflict. Check bound sockets as well as listeners when diagnosing port conflicts. See [startup recovery](docs/wsl-deployment.md#startup-errors-and-recovery).

The WSL Windows launcher bundles and verifies `deploy/wsl/central-server.ico`; its shortcuts and installer use this independent icon. Never reference the separate Windows server executable for a WSL shortcut icon. Windows source-checkout shortcuts use `pythonw.exe` with `deploy/wsl/launch-manager.pyw` and the existing distribution/workspace/project; suppress the WSL console with `CREATE_NO_WINDOW` rather than a PowerShell wrapper. See [installer guide](docs/wsl-installer.md).

The Windows WSL launchers start Docker Desktop if needed; opening the Qt manager starts only its configured project once and reuses a ready server. Stop remains effective until another launch. Display refresh uses minutes, retains legacy saved second intervals and never starts a stopped server. Keep fixed upload URLs and API tokens off routine screens; encrypted exports retain the actual endpoint. Central-only `0010` introduced warehouse views; `0011_stored_warehouse` adds stored alarm/event facts, durable refresh queues and reporting summaries; `0012_shared_source_storage` uses shared storage for new sources. Preserve canonical revisions/receipts and legacy source table OIDs. Refresh runs independently of ingestion/AI, with bounded retries and disclosed lag; report reads must not run maintenance or call models. Enforce forced customer RLS and reject runtime membership in private `scada_warehouse_owner`. Count occurrences per source/generation/type/native ID, retain uncertain times/order and keep AI/registered-event identity separate from approved mappings. Generation retirement preserves authorized immutable backlog; credential revocation controls access. See [warehouse, analysis and security](docs/central-server-analysis.md#stored-warehouse-architecture).

The VMware build is Ubuntu 24.04/Xfce → native Docker Engine → Central Server only (`linker-scada-vmware`); keep the Collector separate. Generate PCIe root ports for VMXNET3 and leave its slot automatically allocated; repair only a closed, powered-off VMX with a backup, preserving identity/network/disk settings. Build with `python -m deploy.vmware.build` into fresh `dist/vmware` folders, verifying the pinned Ubuntu image. First boot provisions the guest online; it does not migrate existing server state or change Windows/WSL virtualization. Separate runtime image downloads from service readiness; retain VM health grace and custom health settings in generated local/Network profiles. Initial password/private SSH key stay in ignored protected `secrets/vmware`, outside the bundle. Package verified boot files with `deploy.vmware.package`; exclude initialized test disks and private handoffs. Test with a disposable overlay, not the delivered disk or current operational installations; actual VMware boot/graphics and remote Collector commissioning require target-host verification. Linux GUI captions distinguish native Linux from WSL. See [VMware build and operation](docs/vmware-linux.md).

## Working conventions

- Build the separate online WSL/Docker installer with `deploy/wsl/build-installer.ps1`; use fresh `dist/wsl-docker/0.6.2-*` outputs and checksums, preserving Windows packages. Package only allowlisted application files and verified setup tools. Retain saved ports, `.env`, Linux vaults and named volumes; stop only the selected project before code replacement and recreate containers to refresh WSL mounts. Test fresh setup/reruns on disposable workspaces/projects, never by resetting operational state. See [installer guide](docs/wsl-installer.md).

- Legacy/published Central Server 0.6.1 uses registered source names for two managed native tables (`alarmhistory`, `eventhistory`). Preserve these schemas/tables, OIDs, values, permissions and replay on upgrade. Current `0012` registrations use fixed `platform`, `warehouse` and `reporting` schemas without per-source physical copies; UUIDs separate sources/generations. Existing legacy tables still synchronize and rename safely. Quote legacy identifiers, shorten at UTF-8 boundaries and disambiguate without merging sources. Runtime roles must never inherit private storage/warehouse owners. pgAdmin filters do not grant warehouse access. Apply migrations only to Central storage. See [shared and legacy storage](docs/source-table-layout.md).
- Preserve unrelated working-tree changes and keep edits scoped to the requested task.
- Follow existing Python, Tk, SQL, and PowerShell patterns. Keep database, network, and process work off the GUI thread.
- Run checks appropriate to the change. For protocol, ingestion, database, or queue changes, include the relevant disposable PostgreSQL tests. State what ran, what skipped, and what remains unverified.
- Update the relevant usage/operations documentation when behavior or setup changes. Keep README as the overview and link to detailed guides in `docs/`.
- Track CI/CD work in [docs/ci-cd-punchlist.md](docs/ci-cd-punchlist.md). It is a backlog, not an instruction to implement pipelines during unrelated tasks.
- Check implementation before describing planned features as available. Customer read APIs, portal, analytics, Grafana, OIDC, and notifications are documented as later phases.
- Update `AGENTS.md` in the same task whenever project files change, including code, configuration, tests, builds, or documentation. Revise affected guidance and refresh the latest project change note before reporting completion, even when existing instructions remain valid.
- Keep this file concise and current. Replace the latest project change note rather than accumulating a history here; put detailed procedures, change history, and implementation evidence in linked documentation.

## Latest project change

2026-11-04: Removed New machine tag from both source-registration GUIs. The user's selected behavior requires an existing scoped machine; forms validate before backend calls and preserve IDs, credentials and event identity. Applied checked GUI files to the native VMware manager after the user approved discarding its unfinished edits, then reopened it; server containers retained ten-hour uptime. Windows GUI: 24 passed/2 display skips; corrected Qt fixtures and all 24 Qt cases passed without skips. No database/protocol changes or new integration run. Warehouse head `0012_shared_source_storage`, HTTPS `187.17.53.216:8443`, environment/CA/volumes and ready services remain intact. The earlier warehouse PostgreSQL 17/18 and Linux checks retain their documented scope; remote Collector delivery, capacity, restore and fresh r3 acceptance remain unverified. Existing WSL/Windows installations and release artifacts were retained. See [registration/deployment evidence](docs/vmware-build-2026-11-04.md#existing-machine-registration-selection), [warehouse operation](docs/central-server-analysis.md#stored-warehouse-architecture) and [Collector evidence](docs/collector-update-2026-11-04.md). Keep the operational Collector stopped on this PC and all backup keys/private handoffs outside Git.
