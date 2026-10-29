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
- Central Server owns a separate PostgreSQL database. Preserve customer/source/machine identity and enforce customer isolation in application queries and database permissions.
- Preserve original alarm/event fields, source timestamps, separate milliseconds, and revision history. Flag uncertain ordering, timezones, and mappings instead of guessing values or current state.
- Preserve durable acceptance and replay behavior: acknowledge uploads only after commit, validate matching batch ID/hash/committed receipts, and retain unconfirmed local batches through faults and restarts.
- Keep unknown machine mappings quarantined until approved. Receipt and storage do not imply successful mapping or completed processing.
- Add new Alembic migrations for schema changes; preserve existing migration history.

## Credentials and local state

- Keep passwords, upload tokens, private TLS keys, raw customer records, and operator text out of source control, logs, and release artifacts. Use the existing protected credential and encrypted setup mechanisms.
- Preserve existing collector settings, IDs, checkpoints, pending batches, and central data during routine development. Do not clear state to bypass a fault.
- `.tools/`, `collector-local/`, `.env`, and DPAPI files contain local operational state. `.tools/` helpers are ignored and may depend on this development PC; do not treat them as portable CI infrastructure.
- Consult [docs/central-server-windows.md](docs/central-server-windows.md) and [docs/operations.md](docs/operations.md) for commissioning and recovery. Development defaults are central PostgreSQL on loopback port `55441` and HTTPS on `8443`; check saved settings before assuming these values.

## Development commands

Use Python 3.12 or 3.13; PostgreSQL integration and local commissioning use PostgreSQL 17. The following commands assume PowerShell, the repository root, and an existing `.venv`.

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

Validate the Docker Compose template without starting services:

```powershell
docker compose --env-file .env.example -f deploy/docker-compose.yml config --quiet
```

## Working conventions

- Preserve unrelated working-tree changes and keep edits scoped to the requested task.
- Follow existing Python, Tk, SQL, and PowerShell patterns. Keep database, network, and process work off the GUI thread.
- Run checks appropriate to the change. For protocol, ingestion, database, or queue changes, include the relevant disposable PostgreSQL tests. State what ran, what skipped, and what remains unverified.
- Update the relevant usage/operations documentation when behavior or setup changes. Keep README as the overview and link to detailed guides in `docs/`.
- Track CI/CD work in [docs/ci-cd-punchlist.md](docs/ci-cd-punchlist.md). It is a backlog, not an instruction to implement pipelines during unrelated tasks.
- Check implementation before describing planned features as available. Customer read APIs, portal, analytics, Grafana, OIDC, and notifications are documented as later phases.
- Update `AGENTS.md` in the same task whenever project files change, including code, configuration, tests, builds, or documentation. Revise affected guidance and refresh the latest project change note before reporting completion, even when existing instructions remain valid.
- Keep this file concise and current. Replace the latest project change note rather than accumulating a history here; put detailed procedures, change history, and implementation evidence in linked documentation.

## Latest project change

2026-10-29: Added repository guidance, the rule to update `AGENTS.md` with every project change, and the CI/CD punchlist linked from README.
