# Central Server 0.4 — revision X1

The Central Server receives authenticated HTTPS uploads from SCADA Collectors and stores/processes alarm and event history in its own PostgreSQL database. Install it on the central server PC, or alongside the Collector for local testing.

The separate [SCADA Collector](../collector/README.md) runs on the SCADA PC. It uses source database credentials and an outbound upload connection. The two applications share protocol definitions in `shared/`.

## Windows package

- Installer: `dist/installer/Linker-Central-Server-Setup.exe`.
- Standalone executable: `dist/central-server/central-server.exe`.
- Development launcher: `Launch Central Server.cmd` in the repository root.
- Build script: `deploy/windows/build-server.ps1`.

PostgreSQL 17 is a prerequisite. Choose **4 Connection & mode** for Local testing or Network server mode, save the hostname/listener settings, then initialize/start the server. Register the SCADA source and export an encrypted collector setup file. Import that file in the Collector and use **Test server** before collecting history.

Follow the [Windows setup guide](../docs/central-server-windows.md) for certificates, firewall access and testing from another PC. See [operations and recovery](../docs/operations.md) for Linux deployment, backup, mapping approval and reprocessing.

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
