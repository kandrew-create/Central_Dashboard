# WSL / Docker package installer

The separate **Linker Central Server - WSL Docker** installer prepares Ubuntu, Docker, a private Linux Python/Qt environment and the Central Server. No Windows Python installation is required. The existing Windows Central Server and Collector packages remain separate.

This is an **online installer** for Windows 11 23H2 or newer on x64. First setup needs internet access for Ubuntu, Docker Desktop if missing, Linux Python, Qt and container images. It contains the application, SHA-256 manifests and verified uv setup archive; customer settings, credentials, database files and Docker Desktop are excluded.

## Install and open

1. Run `Linker-Central-Server-WSL-Docker-Setup-0.6.2.exe`. Keep **Set up WSL, Docker and the Central Server** selected at the end.
2. Keep the default Ubuntu distribution, Linux folder `central-server`, Docker project `linker-scada-wsl`, HTTPS port 443 and HTTP port 80 unless another application uses those ports. An existing Ubuntu WSL 2 distribution is selected when available; otherwise setup offers `Ubuntu-24.04`.
3. Click **Start / resume setup**. Approve Windows elevation for WSL if requested. Save your work and restart Windows if instructed; setup never restarts automatically. Reopen **Finish WSL Docker Setup** from Start to continue.
4. Complete Ubuntu's private username/password prompts and Docker Desktop's first-run prompts when requested. Enable **Settings → Resources → WSL Integration** for the selected Ubuntu distribution. Keep Docker Desktop running, then resume setup.
5. When ready, click **Open server GUI**. Later, use the desktop shortcut **Central Server - WSL Docker** or Start menu **Central Server GUI**.

The server runs inside Docker; the native Qt window runs through WSLg. See [GUI usage](wsl-deployment.md). Fresh installation defaults to local testing on loopback. Reruns preserve an existing valid [Network configuration](wsl-deployment.md#match-the-saved-windows-network-endpoint), its hostname/listener and certificate volumes. Remote collector access and migration of an existing Windows database require separate commissioning.

On custom HTTPS port 9444, exported collector setups use `https://localhost:9444/v1/uploads`. HTTP redirects to that HTTPS port. PostgreSQL and the API have no directly published ports. The HTTPS root returns 404 by design.

## Rerun, upgrade and uninstall

Close the selected manager before rerunning setup. Keep the same Ubuntu distribution, Linux folder and Docker project. Setup retains `.env` and its saved ports, stops only that project before replacing application files, then recreates containers to refresh Docker Desktop's WSL file mounts. PostgreSQL and Caddy volumes, source registrations, protected credential keys/vaults and collector identities are retained.

Replaced application files are backed up under the private Linux `secrets/code-backup-*` directory. This does not replace a database backup. Setup rejects data without matching settings, a PostgreSQL major-version mismatch, an unrelated Docker project, occupied unrelated ports, or a nonempty unrecognized target folder. It never resets WSL or Docker. Failed startup stops newly started API/worker components and retains settings and data for repair/retry.

The per-user launcher installs under `%LOCALAPPDATA%\Programs\Linker\Central Server WSL Docker`. Its nonsecret selection state is private under `%LOCALAPPDATA%\Linker\WslDockerSetup`. Application files, `.env`, exports and manager state remain in the selected Linux home directory. Back up Linux settings and `secrets/docker-manager` together with PostgreSQL and certificate volumes; see [operations](operations.md).

Uninstalling **Linker Central Server - WSL Docker (Windows launcher)** removes its Windows files and Start menu entries. It preserves Ubuntu, Docker Desktop, Linux files, credentials, exports and database/certificate volumes. Remove the wizard-created desktop shortcut manually if no longer needed. Uninstall does not stop the server; use its GUI stop control first if needed.

## Build and verify

With the documented development environment, PyInstaller and Inno Setup 6:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File deploy/wsl/build-installer.ps1
```

Pass `-Compiler` for another Inno Setup location. Each build creates a fresh `dist/wsl-docker/0.6.2-*` directory containing the EXE installer, portable ZIP, SHA-256 sidecars and build metadata. Earlier builds and `dist/installer` Windows packages are preserved. For portable use, extract the whole ZIP and run `Setup.cmd`, keeping its payload beside the launcher.

Compare an artifact's `Get-FileHash -Algorithm SHA256` output with its adjacent `.sha256` file. The local development package is unsigned and has not been published as an X3 release. Bundled files are checked before installation. Prerequisite downloads use pinned hashes; Docker Desktop also requires a valid Docker signature. Bundled third-party notices accompany the package.

## Verification — 2026-10-31

The frozen setup wizard opened successfully. Silent installation into a disposable Windows directory and verification of the installed package both succeeded. The installed launcher opened the actual Qt manager for the selected workspace. A separate Ubuntu workspace and Docker project used HTTP 9080 / HTTPS 9444. Verification covered fresh installation, rerun through the frozen installer, encrypted custom-port setup export, and retention of database/source identities, `.env`, CA and protected credential key/vault. The disposable launcher was uninstalled and its project stopped; Linux files and volumes remain intact. No live collector or existing Central data was used. Local reports are outside Git at `%LOCALAPPDATA%\Linker\wsl-setup\installer-*.json`.

Linux installer, Docker adapter, vault and Qt checks passed on Ubuntu (32 checks). Five administration integration checks passed on each disposable PostgreSQL 17 and 18 cluster, including encrypted custom-port export; nine Windows manager regression checks passed on disposable PostgreSQL 18. Windows passed 14 package/adapter checks and skipped four Linux filesystem checks; those executed on Ubuntu. The repository Compose template passed `config --quiet` without starting services.

First-time Windows feature enablement, restart, Ubuntu account creation and Docker installation were not repeated on this configured PC. Validate these paths on a clean supported Windows machine before customer distribution. Remote connectivity and Windows-to-Linux data migration remain separate work.
