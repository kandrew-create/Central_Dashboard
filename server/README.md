# Central Server 0.6.1 — revision X3

The local 0.6.2 update [loads saved AI state and interpretations automatically](../docs/ai-display-refresh.md); enabling AI again is unnecessary. Published X3 downloads below remain 0.6.1.

The updated WSL/Docker manager also provides [alarm trends and issue summaries](../docs/central-server-analysis.md), a read-only warehouse layer, refresh settings in minutes and automatic Docker/server startup. Upload credentials stay protected and the fixed upload URL is hidden from routine screens. Local AI suggests equipment names; root-cause diagnosis remains outside its scope. Alarm analysis supports [Edit / override equipment](../docs/equipment-suggestions.md), retaining original AI results and native records.

The current source adds a [stored warehouse](../docs/central-server-analysis.md#stored-warehouse-architecture): shared alarm/event occurrence facts, live UUID dimensions and maintained hourly/daily/equipment/upload summaries. Migration `0013_remove_source_copies` verifies and removes legacy per-source duplicates; originals and receipts remain intact. Migrations apply only to Central storage. See [upgrade safeguards](../docs/source-table-layout.md). The current VMware deployment uses HTTPS `187.17.53.216:8443`; published X3 installers remain unchanged. Named read-only reporting views add project/source labels for direct filtering; see [pgAdmin queries](../docs/pgadmin-browsing.md).

The current WSL/Docker manager uses **Alarm analysis** for saved AI suggestions, equipment-name overrides and original-message/tag evidence. Its **AI settings** panel contains model and Enable/Disable controls; the duplicate Equipment Identification navigation page is removed. Viewing or refreshing never calls a model or changes the saved AI choice. Original results stay stored. Native Windows/published builds retain their older Equipment Identification page. See [equipment suggestions and editing](../docs/equipment-suggestions.md).

Version 0.5.2 separates equipment from the alarm condition (`Conveyor VFD Connect Error` identifies `Conveyor VFD`), rechecks earlier alarm results and shows the original message when a result is selected. Suggestions remain reviewable; literal inclusion in a message alone does not prove an accurate machine name.

Published version 0.6.1 names each source schema from its registered SCADA PC/source name, each with two physical tables: `alarmhistory` and `eventhistory`. Current migration 0013 removes these verified duplicate copies in favor of shared warehouse tables. See [pgAdmin browsing](../docs/pgadmin-browsing.md) and [storage details](../docs/source-table-layout.md).

The Central Server receives authenticated HTTPS uploads from SCADA Collectors and stores/processes alarm and event history in its own PostgreSQL database. Install it on the central server PC, or alongside the Collector for local testing.

The separate [SCADA Collector](../collector/README.md) runs on the SCADA PC. It uses source database credentials and an outbound upload connection. The two applications share protocol definitions in `shared/`.

Current source-registration forms ask for customer, site, project and SCADA source name only. They create no machine assignment; uploads remain scoped to the source and process without mapping approval; unassigned event identity remains uncertain. Existing assignments are retained. See [source registration](../docs/source-registration.md) and [processing without mappings](../docs/source-scoped-processing.md).

Network mode accepts multiple collector PCs at one Central Server HTTPS endpoint. Register each SCADA database source separately and give each collector its own encrypted setup file and upload credential. Allow all intended collector PCs through the server firewall. The current manager labels this **Network server (multiple collector PCs)**; the older **two PCs** label did not enforce a two-PC limit.

## Windows package

[Download the X3 Central Server installer](https://github.com/kandrew-create/Central_Dashboard/releases/download/X3/Linker-Central-Server-Setup.exe). [Release notes and checksums](https://github.com/kandrew-create/Central_Dashboard/releases/tag/X3).

- Installer: `dist/installer/Linker-Central-Server-Setup.exe`.
- Standalone executable: `dist/central-server/central-server.exe`.
- Development launcher: `Launch Central Server.cmd` in the repository root.
- Build script: `deploy/windows/build-server.ps1`.

The rebuilt installer stops the configured server before updating files, closes remaining Central Server processes, and preserves settings and database files. Save unsaved edits before starting Setup. Stop failures block the upgrade; reopen the application and start the server after installation.

PostgreSQL 17 or 18 is a prerequisite for X2. The older X1 installer supports PostgreSQL 17 only. New setups detect an installed version, preferring 18. Choose **4 Connection & mode** for Local testing or Network server mode, confirm the PostgreSQL bin folder and save the hostname/listener settings, then initialize/start the server. Existing databases require binaries of the same major version; changing the bin folder does not upgrade data. Register the SCADA source and export an encrypted collector setup file. Import that file in the Collector and use **Test server** before collecting history.

Follow the [Windows setup guide](../docs/central-server-windows.md) for certificates, firewall access and testing from another PC. See [operations and recovery](../docs/operations.md) for Linux deployment, backup and processing retries.

The source checkout also provides a native **WSL / Docker management GUI** through WSLg: server controls, source registration, encrypted collector setup export, editable deployment settings and local AI enable/disable/model controls with saved identification results. Use **Deployment → Validate settings**, then **Save settings** with the server stopped, or confirmed **Apply and restart**. It manages the separate Linux Compose deployment; published Windows installers are unchanged. See [WSL setup and usage](../docs/wsl-deployment.md).

The separate [WSL / Docker online installer](../docs/wsl-installer.md) prepares this deployment and GUI without Windows Python. Build it with `deploy/wsl/build-installer.ps1`; it retains earlier Windows packages and existing Linux settings/data when rerun.

The [VMware Linux desktop build](../docs/vmware-linux.md) provides a separate Ubuntu/Xfce VM with Docker Engine and the same management window. The guest is a fresh Central Server environment; current data, registrations and Collector identities require a separate reviewed migration if they are to be continued there.

The current source checkout adds **Delete selected source** under **Sources & collector setup**. After confirmation it removes a registration from use, revokes its upload credentials and retains received history and audit records. It works in both operating modes; use a newly rebuilt package for this button because the published X2 installer predates it. See [source deletion](../docs/central-server-windows.md#delete-a-registered-source) for retained data and collector queue behavior.

## Source layout

| Folder/file | Purpose |
|---|---|
| `management/` | Windows manager, native WSL/Docker GUI, protected credentials and local process control |
| `app/` | HTTPS ingestion and authenticated collector connection check |
| `worker/` | Durable job processing and alarm/event normalization |
| `migrations/` | PostgreSQL schema and migration history |
| `admin.py` | Trusted central administration commands |
| `tests/` | Unit and disposable PostgreSQL integration tests |

Operational data, secrets and generated installers are kept outside Git. Customer portal/reporting features remain later phases; network and unattended operation still require commissioning on the destination PCs.
