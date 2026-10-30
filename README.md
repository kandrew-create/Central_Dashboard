# SCADA Collector and Central Server

Repository revision: **X2**. Application package version: **0.4.0**.

Download ready-to-install Windows packages from the [X2 release](https://github.com/kandrew-create/Central_Dashboard/releases/tag/X2). SHA-256 checksum files are included with the downloads. See the [X2 release notes](docs/release-X2.md) for the fixes and verification evidence.

This repository contains two applications with separate Windows installers:

| Application | Source and guide | Installed on | Installer |
|---|---|---|---|
| SCADA Collector | [collector/](collector/README.md) | SCADA PC | [Download installer](https://github.com/kandrew-create/Central_Dashboard/releases/download/X2/Linker-SCADA-Collector-Setup.exe) |
| Central Server | [server/](server/README.md) | Central server PC; same PC for local tests | [Download installer](https://github.com/kandrew-create/Central_Dashboard/releases/download/X2/Linker-Central-Server-Setup.exe) |

`shared/` contains the common upload protocol and encrypted setup-file format. `deploy/` contains deployment and build scripts; `docs/` contains specifications and operating guides. Keeping the applications in one repository lets changes to their shared interface be reviewed together. Each PC installs only its required application.

Build the Collector with `deploy/windows/build.ps1` and the Central Server with `deploy/windows/build-server.ps1`. Build outputs are written to `dist/installer` and published as GitHub Release assets. Operational credentials, databases, logs and local build directories are excluded from the source history.

The X2 Central Server supports PostgreSQL 17 and 18, detects installed binaries for new setups, and rejects binaries that do not match an existing database's major version. X2 also checks the local HTTPS listener before startup, handles installed application locks during upgrades, and fixes misleading save/registration messages. The X2 Collector fixes setup import blocked by incomplete upload edits and shows protected-credential status. X1 remains available as an older release. See the [Windows setup guide](docs/central-server-windows.md#storage-and-credentials).

Pending automation work is tracked in the [CI/CD pipeline punchlist](docs/ci-cd-punchlist.md).

Version 0.4 adds Local testing and Network server modes, saved listener/hostname settings, managed matching HTTPS certificates, and an authenticated collector connection test. Collection, durable queueing and encrypted setup export/import remain available. Customer read APIs, the Web Portal, analytics, Grafana, OIDC and notifications remain later phases.

Open Central Server from its installed shortcut, or use **Launch Central Server.cmd** with a configured source-checkout Python environment. Use **Server status** to start/stop the central database, HTTPS API and worker; **Register SCADA source** to create IDs and a protected credential; and **Sources & collector setup** to export a password-encrypted `.linker-collector` file. In the Collector, open **3 Collection & upload → Import server setup**. See the [Central Server Windows guide](docs/central-server-windows.md). Reuse an existing registered source when appropriate; registering the same source again is unnecessary.

For multiple collector PCs connecting to one Central Server, choose **4 Connection & mode → Network server (multiple collector PCs)**, enter the central server's hostname or stable IPv4 address and HTTPS listener/port, save and start the server. Register each SCADA database source separately and export/import its own collector setup. All collectors use the same central HTTPS endpoint with their own source identity and credential. Use **Test server** on each Collector before collecting. Mode/address changes require the server to be stopped. Allow the intended collector PCs through the server firewall for the selected HTTPS port; the application does not add firewall rules. Older packages label this same mode **Network server (two PCs)**; that wording is not a two-PC limit.

On this development PC, open **Launch Collector.cmd**. Reopen the saved settings after an external configuration update. The **Collection & upload** tab provides **Collect now**, **Start automatic collection**, **Stop**, protected upload-credential storage and status. GUI scheduling runs while the GUI stays open. Native service operation is a separate installation under a commissioned Windows account.

Local testing mode uses `https://localhost:8443/v1/uploads` and a separate central PostgreSQL cluster on loopback port 55441 by default. Network mode uses the saved HTTPS listener and collector-facing server address. Central storage always remains separate from the SCADA source database. Credentials and local data are excluded from Git and Docker build contexts.

```powershell
& .venv/Scripts/python.exe -m deploy.local_server status
& .venv/Scripts/python.exe -m collector status
& .venv/Scripts/python.exe -m collector collect
```

To restart or stop that local server:

```powershell
& .venv/Scripts/python.exe -m deploy.local_server start
& .venv/Scripts/python.exe -m deploy.local_server stop
```

See [collector usage](collector/README.md), [operations and recovery](docs/operations.md), [network-mode verification](docs/network-mode-implementation-2026-10-28.md), [management verification](docs/central-server-manager-implementation-2026-10-28.md), [core-runtime evidence](docs/collector-server-implementation-2026-10-28.md), and [open commissioning questions](docs/OPEN_QUESTIONS.md). Windows installer outputs are under `dist/installer`; executable outputs are under `dist/collector` and `dist/central-server`. They are development artifacts, not an approved customer deployment.
