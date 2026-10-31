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
- Encrypted `.linker-collector` setup exports remain ignored. Keep their unlock passwords and decrypted contents outside Git.
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

Central Server labels use "Saved record versions" (including first copies) and "Batches awaiting machine mapping" (data already saved). Local AI interprets alarms only and must separate equipment from alarm conditions: "Conveyor VFD Connect Error" identifies "Conveyor VFD". A literal text match alone does not establish a correct equipment name. Show original-message evidence and leave unverified/condition-only labels uncertain. Events use the machine tag selected in Register SCADA source, constrained by the accepted upload scope; never infer events from messages or `ev_source`. Store results separately from native revisions and retain mapping approval. Apply identification migrations `0004`–`0006` only to Central storage.

Registration names are single-line labels: trim surrounding whitespace and fold pasted CR/LF/tab separators to spaces before enforcing the 1–255 character limit. Distinguish empty, overlength and unsupported-control-character errors. Validate new registration names before database work and preserve existing-item reuse and transaction rollback.

Source deletion is a confirmed registration removal in both operating modes: set `sources.deleted_at`, revoke its credentials and append an audit event atomically. Hide deleted sources from the manager; preserve identities, generations, mappings, committed data, jobs and protected setup files. Block setup export/credential replacement and authentication for deleted sources. Apply migration `0003_source_deletion` only to Central Server storage. Management startup must not create demo sources by default.

Collector setup import must not be blocked by unsaved fields supplied by the setup file itself (IDs, URL, upload enable flag and CA path). Import against the last saved local configuration; preserve unsaved database/history/schedule changes by requiring an explicit save, and retain identity/queue/scheduler-lock guards. Explain missing local setup and show protected-credential presence without displaying secrets; Test server verifies validity.

Validate the Docker Compose template without starting services:

```powershell
docker compose --env-file .env.example -f deploy/docker-compose.yml config --quiet
```

The WSL deployment uses Docker Desktop, project `linker-scada-wsl`, and `/home/station7/central-server` (0700; `.env` 0600). Its Qt/WSLg GUI launches with `bash deploy/wsl/launch-manager.sh`; the desktop shortcut is **Central Server - WSL Docker**. Use Python 3.13 in `.venv-gui` with the optional `docker-gui` extra. Keep I/O outside the GUI thread and retain activity/operation feedback. Management uses scoped commands with logging disabled and no admin port. Preserve `secrets/docker-manager`, its key/vaults, both installations, volumes and Collector identities. Explicit Network settings use the Windows host listener and matching Caddy internal-CA certificate; exports must carry the saved endpoint and `local_test_only=false`. Keep the Windows server stopped when WSL uses its endpoint. PostgreSQL 17 stays private and separate from Windows PostgreSQL 18. Verify every actual remote Collector PC before declaring commissioning complete. See [WSL deployment](docs/wsl-deployment.md).

## Working conventions

- Build the separate online WSL/Docker installer with `deploy/wsl/build-installer.ps1`; use fresh `dist/wsl-docker/0.6.2-*` outputs and checksums, preserving Windows packages. Package only allowlisted application files and verified setup tools. Retain saved ports, `.env`, Linux vaults and named volumes; stop only the selected project before code replacement and recreate containers to refresh WSL mounts. Test fresh setup/reruns on disposable workspaces/projects, never by resetting operational state. See [installer guide](docs/wsl-installer.md).

- Central Server 0.6.1 uses registered SCADA PC/source names for its two managed physical native tables (`alarmhistory`, `eventhistory`). Migration `0009_source_schema_names` renames existing schemas in place; preserve table OIDs, native values, permissions, replay and revision behavior. Quote identifiers; shorten at UTF-8 boundaries and disambiguate collisions without merging sources. Runtime roles must never inherit the private storage owner. Update pgAdmin schema restrictions after a rename. Apply migrations only to Central storage. See [source storage](docs/source-table-layout.md).
- Preserve unrelated working-tree changes and keep edits scoped to the requested task.
- Follow existing Python, Tk, SQL, and PowerShell patterns. Keep database, network, and process work off the GUI thread.
- Run checks appropriate to the change. For protocol, ingestion, database, or queue changes, include the relevant disposable PostgreSQL tests. State what ran, what skipped, and what remains unverified.
- Update the relevant usage/operations documentation when behavior or setup changes. Keep README as the overview and link to detailed guides in `docs/`.
- Track CI/CD work in [docs/ci-cd-punchlist.md](docs/ci-cd-punchlist.md). It is a backlog, not an instruction to implement pipelines during unrelated tasks.
- Check implementation before describing planned features as available. Customer read APIs, portal, analytics, Grafana, OIDC, and notifications are documented as later phases.
- Update `AGENTS.md` in the same task whenever project files change, including code, configuration, tests, builds, or documentation. Revise affected guidance and refresh the latest project change note before reporting completion, even when existing instructions remain valid.
- Keep this file concise and current. Replace the latest project change note rather than accumulating a history here; put detailed procedures, change history, and implementation evidence in linked documentation.

## Latest project change

2026-10-31: Matched WSL to the saved Windows Network endpoint at HTTPS port 8443. Added explicit Docker mode/hostname/listener support, network-safe collector exports, matching internal-CA certificates, GUI mode labels and preservation of Network settings on setup reruns. Existing WSL identities, credentials, database/certificate volumes and Windows installation remain preserved. Linux checks and disposable PostgreSQL 17/18 export/regression checks cover the change; actual remote-PC connectivity remains unverified. See [network configuration and evidence](docs/wsl-deployment.md#match-the-saved-windows-network-endpoint).
