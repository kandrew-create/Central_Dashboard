# Central Server 0.6.1 — revision X3

The local 0.6.2 update [loads saved AI state and interpretations automatically](../docs/ai-display-refresh.md); enabling AI again is unnecessary. Published X3 downloads below remain 0.6.1.

The new local-AI release adds **5 Local AI** to interpret equipment names from alarm messages on the central PC. Version 0.5.1 identifies events directly from the machine tag selected at source registration; event messages are never sent to AI. Raw records and approved mapping behavior are preserved. See [X3 setup and verification](../docs/release-X3.md). X3 downloads below include Central Server 0.6.1; Collector remains 0.4.0.

Version 0.5.2 separates equipment from the alarm condition (`Conveyor VFD Connect Error` identifies `Conveyor VFD`), rechecks earlier alarm results and shows the original message when a result is selected. Suggestions remain reviewable; literal inclusion in a message alone does not prove an accurate machine name.

Version 0.6.1 names each source schema from its registered SCADA PC/source name, each with just two physical tables: `alarmhistory` and `eventhistory`. Internal tables and history remain preserved. See [pgAdmin browsing](../docs/pgadmin-browsing.md) and [storage details](../docs/source-table-layout.md).

The Central Server receives authenticated HTTPS uploads from SCADA Collectors and stores/processes alarm and event history in its own PostgreSQL database. Install it on the central server PC, or alongside the Collector for local testing.

The separate [SCADA Collector](../collector/README.md) runs on the SCADA PC. It uses source database credentials and an outbound upload connection. The two applications share protocol definitions in `shared/`.

Network mode accepts multiple collector PCs at one Central Server HTTPS endpoint. Register each SCADA database source separately and give each collector its own encrypted setup file and upload credential. Allow all intended collector PCs through the server firewall. The current manager labels this **Network server (multiple collector PCs)**; the older **two PCs** label did not enforce a two-PC limit.

## Windows package

[Download the X3 Central Server installer](https://github.com/kandrew-create/Central_Dashboard/releases/download/X3/Linker-Central-Server-Setup.exe). [Release notes and checksums](https://github.com/kandrew-create/Central_Dashboard/releases/tag/X3).

- Installer: `dist/installer/Linker-Central-Server-Setup.exe`.
- Standalone executable: `dist/central-server/central-server.exe`.
- Development launcher: `Launch Central Server.cmd` in the repository root.
- Build script: `deploy/windows/build-server.ps1`.

The rebuilt installer stops the configured server before updating files, closes remaining Central Server processes, and preserves settings and database files. Save unsaved edits before starting Setup. Stop failures block the upgrade; reopen the application and start the server after installation.

PostgreSQL 17 or 18 is a prerequisite for X2. The older X1 installer supports PostgreSQL 17 only. New setups detect an installed version, preferring 18. Choose **4 Connection & mode** for Local testing or Network server mode, confirm the PostgreSQL bin folder and save the hostname/listener settings, then initialize/start the server. Existing databases require binaries of the same major version; changing the bin folder does not upgrade data. Register the SCADA source and export an encrypted collector setup file. Import that file in the Collector and use **Test server** before collecting history.

Follow the [Windows setup guide](../docs/central-server-windows.md) for certificates, firewall access and testing from another PC. See [operations and recovery](../docs/operations.md) for Linux deployment, backup, mapping approval and reprocessing.

The current source checkout adds **Delete selected source** under **Sources & collector setup**. After confirmation it removes a registration from use, revokes its upload credentials and retains received history and audit records. It works in both operating modes; use a newly rebuilt package for this button because the published X2 installer predates it. See [source deletion](../docs/central-server-windows.md#delete-a-registered-source) for retained data and collector queue behavior.

## Source layout

| Folder/file | Purpose |
|---|---|
| `management/` | Windows setup/status GUI, settings, credentials and process control |
| `app/` | HTTPS ingestion and authenticated collector connection check |
| `worker/` | Durable job processing and alarm/event normalization |
| `migrations/` | PostgreSQL schema and migration history |
| `admin.py` | Trusted central administration commands |
| `tests/` | Unit and disposable PostgreSQL integration tests |

Operational data, secrets and generated installers are kept outside Git. Customer portal/reporting features remain later phases; network and unattended operation still require commissioning on the destination PCs.
