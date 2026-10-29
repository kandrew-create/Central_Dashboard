# PostgreSQL 17 and 18 compatibility verification

The Central Server source and rebuilt local Windows installer support PostgreSQL 17 and 18. The published X1 release has not been replaced and still requires PostgreSQL 17.

## Behavior

- New setups detect complete installations under `%ProgramFiles%\PostgreSQL`, preferring 18 and falling back to 17. Saved locations are preserved. An existing data directory's major version takes precedence over newer installed versions when recovering a setup without saved manager settings.
- The selected `postgres.exe`, `pg_ctl.exe` and `initdb.exe` must report one supported major version. Existing `database/PG_VERSION` must match that version.
- Mismatches, unsupported versions, unreadable version files, incomplete folders and unresponsive binaries are rejected before database initialization. No automatic database upgrade or state reset occurs.
- Settings validation executes in the GUI's background save operation. The direct commissioning start path also checks binary/data compatibility.
- Frozen Windows executables reset the DLL search directory while invoking PostgreSQL, retaining the existing isolation from bundled application DLLs.

## Executed checks

Windows 11, Python 3.13.18, PostgreSQL 17.11 and PostgreSQL 18.6:

| Check | PostgreSQL 17 | PostgreSQL 18 |
|---|---|---|
| Full pytest suite, including real PostgreSQL integration | 178 passed, 2 desktop-display skips | 179 passed, 1 desktop-display skip |
| Fresh manager initialization and Alembic migrations | Passed | Passed |
| Certificate-verified HTTPS health and repeated start | Passed | Passed |
| Rebuilt frozen executable through the GUI controller's child-launch path | Passed | Passed |
| Frozen executable stop/start and verified HTTPS after restart | Passed | Passed |

The two skipped GUI checks (rejecting settings changes while running and collector collection controls) were rerun separately: **2 passed, zero skipped**. Each full suite emitted one Starlette/httpx deprecation warning. New regression cases cover matching and mismatching major versions, unsupported/corrupt versions, missing/mixed/failed/timed-out tools, automatic detection, saved-path preservation and rejection before direct startup writes.

All database checks used fresh, separate disposable clusters under ignored `.tools/` folders, with allocated loopback ports. Existing PostgreSQL services, SCADA/customer databases and installed Central Server state were not used. Existing passwordless test-role fixtures ran only against a loopback-bound disposable cluster; actual manager initialization used its normal SCRAM credentials. Every started verification cluster and application component was stopped afterward. No existing database was migrated.

## Build and delivery

`deploy/windows/build-server.ps1` completed with PyInstaller 6.22.3 and Inno Setup 6.7.3. Outputs:

- `dist/central-server/central-server.exe`
- `dist/installer/Linker-Central-Server-Setup.exe`
- Refreshed `dist/installer/Linker-Central-Server-Setup.exe.sha256`

The installer has subsequently been rebuilt with [automatic upgrade shutdown handling](central-server-upgrade-verification-2026-10-29.md). Use the `.sha256` file beside the current installer; the server build refreshes it on each build.

The installed application was not replaced during verification. Save unsaved edits before upgrading; the current installer stops the configured server and closes remaining executable locks. For a new PostgreSQL 18 setup, select `C:\Program Files\PostgreSQL\18\bin` in **4 Connection & mode**, save and initialize/start. Existing PostgreSQL 17 data requires matching 17 binaries until a separately planned backup/migration is completed. See [Windows setup](central-server-windows.md#storage-and-credentials) and [PostgreSQL major upgrades](https://www.postgresql.org/docs/18/upgrading.html).
