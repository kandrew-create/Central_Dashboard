# SCADA Collector and Central Server

Repository revision: **X1**. Application package version: **0.4.0**.

Download ready-to-install Windows packages from the [X1 release](https://github.com/kandrew-create/Central_Dashboard/releases/tag/X1). SHA-256 checksum files are included with the downloads.

This repository contains two applications with separate Windows installers:

| Application | Source and guide | Installed on | Installer |
|---|---|---|---|
| SCADA Collector | [collector/](collector/README.md) | SCADA PC | [Download installer](https://github.com/kandrew-create/Central_Dashboard/releases/download/X1/Linker-SCADA-Collector-Setup.exe) |
| Central Server | [server/](server/README.md) | Central server PC; same PC for local tests | [Download installer](https://github.com/kandrew-create/Central_Dashboard/releases/download/X1/Linker-Central-Server-Setup.exe) |

`shared/` contains the common upload protocol and encrypted setup-file format. `deploy/` contains deployment and build scripts; `docs/` contains specifications and operating guides. Keeping the applications in one repository lets changes to their shared interface be reviewed together. Each PC installs only its required application.

Build the Collector with `deploy/windows/build.ps1` and the Central Server with `deploy/windows/build-server.ps1`. Build outputs are written to `dist/installer` and published as GitHub Release assets. Operational credentials, databases, logs and local build directories are excluded from the source history.

Pending automation work is tracked in the [CI/CD pipeline punchlist](docs/ci-cd-punchlist.md).

Version 0.4 adds Local testing and Network server modes, saved listener/hostname settings, managed matching HTTPS certificates, and an authenticated collector connection test. Collection, durable queueing and encrypted setup export/import remain available. Customer read APIs, the Web Portal, analytics, Grafana, OIDC and notifications remain later phases.

Open **Launch Central Server.cmd** for Software 2 on this PC. Use **Server status** to start/stop the central database, HTTPS API and worker; **Register SCADA source** to create IDs and a protected credential; and **Sources & collector setup** to export a password-encrypted `.linker-collector` file. In the updated collector, open **3 Collection & upload → Import server setup**. See the [Central Server Windows guide](docs/central-server-windows.md). The existing `LOCAL-SCADA` source can be selected and exported directly; registering it again is unnecessary.

For another central PC, choose **4 Connection & mode → Network server (two PCs)**, enter its hostname or stable IPv4 address and HTTPS listener/port, save and start the server, then export/import the collector setup. Use **Test server** in the Collector before collecting. Mode/address changes require the server to be stopped. Windows firewall access for the selected HTTPS port must be configured on the server PC; the application does not add firewall rules.

On this development PC, open **Launch Collector.cmd**. Reopen the saved settings after an external configuration update. The **Collection & upload** tab provides **Collect now**, **Start automatic collection**, **Stop**, protected upload-credential storage and status. GUI scheduling runs while the GUI stays open. Native service operation is a separate installation under a commissioned Windows account.

The user-authorized local commissioning server uses `https://localhost:8443/v1/uploads` and a separate PostgreSQL cluster on port 55441. It is bound only to this PC. It does not use the SCADA database as its storage database. Credentials and local data are excluded from Git and Docker build contexts.

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
