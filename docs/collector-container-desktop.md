# Collector interface and runtime in Docker

The Docker desktop deployment runs **all Collector application code in Linux
containers**, including the setup interface. Windows only provides Docker Desktop,
WSL/WSLg display integration and a shortcut launcher. It needs no Windows Python,
Collector executable, tray scheduler or Windows Collector service at runtime.
The Central Server and VMware installation remain separate.

The interface follows the Central Server's dark Linker sidebar, light workspace,
blue actions, page headings and persistent white status footer. It has three pages:
Connection & setup, Alarm & event preview, and Collection & upload. Collection &
upload retains Start Collector, Stop Collector and Refresh status. The separate
Docker deployment page and Reload Docker settings toolbar button were removed.
Source and generation references show only their last four characters as
read-only labels (for example `…a3f9`), or **Not configured** before setup import.
The full IDs remain unchanged internally for configuration, queueing and uploads;
the short references are never used as collection identities.

The reference update passed all 44 focused Windows checks and all 44 GUI/routing/
recovery checks in isolated Linux desktop-image containers without skips. Checks
include setup import and preserving full IDs when saving unrelated settings.
The image and launchers were updated and the interface reopened after the user
closed the previous window normally. The identity-reference/save check also
passed in the running image, with unchanged data/key volume fingerprints.
Unsaved edits are not discarded automatically.

The `desktop` container displays the existing setup/preview/collection controls
through the local WSLg X11 socket. This follows Microsoft's
[container GUI guidance](https://github.com/microsoft/wslg/blob/main/samples/container/Containers.md).
It has no network and publishes no ports; there is no browser server, VNC or
remote management listener. It runs as UID 10001 with a read-only filesystem.
Only this trusted local administration container mounts the Docker socket, using
the existing socket's group. Socket access grants Docker administration authority;
read-only mounting does not make the Docker API read-only. Source-reader,
scheduler and stdin management containers never receive that socket.

The interface uses the same local stdin RPC as the earlier Windows interface.
Credentials remain masked and are transferred only through stdin to management
containers with logging disabled. The scheduler keeps the existing
`linker-collector_collector-data` and `linker-collector_collector-key` volumes.
Its container-specific Compose override removes the host handoff bind mount;
encrypted setup imports already travel through stdin. Database/SCADA settings,
TLS, identity, checkpoints, pending uploads and receipts are not reset or migrated
by this desktop change. The allowlisted build context excludes Central Server,
Ollama, credentials, records, tests and Windows binaries.

## Install from the development checkout

Docker Desktop with Linux containers, its existing Ubuntu WSL integration and
WSLg must already be installed. The existing build environment stages the
allowlisted context; that Python environment is not used to run the installed app.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File deploy/collector/install-docker-desktop.ps1
```

The installer builds the separate desktop and Collector runtime images on the
host and creates **SCADA Collector -
Docker** shortcuts in Start and on the desktop. Each installation uses a fresh
directory under `%LOCALAPPDATA%\Linker\Collector\docker-desktop`. Earlier packages
and all data/key volumes remain intact. Building requires access to Debian,
Docker Hub and the Python package index; normal launch uses installed images.
The former **SCADA Collector - WSL Docker** Start menu shortcut is archived in
the new installation directory and removed from Start, so it cannot reopen the
Windows interface against an unrelated native profile. If Windows denies desktop
shortcut creation, installation reports a warning; use the Start menu shortcut or
**Launch Collector.cmd**. Desktop folder permissions are retained.

Open the shortcut. The launcher starts an already-installed Docker Desktop if
necessary, starts WSLg, and opens only the `desktop` service in `linker-collector`.
It never installs Windows features, changes source networking, creates keys,
initializes data volumes or starts collection. Use **Start Collector** explicitly
after commissioning. Start uses the installed runtime image with `--no-build
--pull never`; it does not build images or contact a registry from the isolated
interface. Reinstall the updated context to build new images before an upgrade.
**Stop Collector** stops the scheduler normally; closing
the interface leaves the scheduler's current state unchanged. Reopening starts
only the interface and preserves an explicit scheduler stop.

For an existing deployment, stop and close the old Windows interface before
switching. After verifying the Docker interface, the Windows Collector package
can be uninstalled normally; its uninstaller retains operational state. Do not
remove native state or migration guards to bypass a missing-setup fault.

Put an encrypted Central Server setup file in the installed context's
`collector-handoff` directory. It appears as `/handoff` in the Linux file picker.
Keep its unlock password separate. Existing file-import/identity guards remain.

If original setup or key material is unavailable, the interface displays the
recovery message with Save/Import/Start disabled. Restore/review the original
state instead of creating an empty replacement. Fresh unassigned installations
still follow the explicit [initialization procedure](collector-wsl-docker.md).

## Local verification on 5 November 2026

The Docker desktop image was built and launched through the existing WSLg
display. Docker routing is pinned to the local Unix socket and project. The
separate scheduler remains stopped, as does Windows/WSL Central Server; VMware
was not changed. The existing Docker data/key volumes were empty when inspected
and were preserved without initialization. This does not commission source
access, credentials, HTTPS delivery or collection.

The three-page interface refresh passed 42 focused Windows UI checks with one
display skip, and all 43 GUI/routing/recovery checks inside the actual Linux
desktop container without skips. It was visually checked against the Central
Server interface and reopened through its normal close guards. Data/key volume
fingerprints remained unchanged; only the desktop container was replaced.

Windows Collector tests and Linux-container UI checks cover interface loading,
Start/Stop, normal close, configuration privacy and missing-state behavior. No
SCADA database was accessed and no PostgreSQL integration was required for this
desktop-only change. Detailed final test counts are recorded in `AGENTS.md`.

The replacement Start/desktop shortcuts and `Launch Collector.cmd` launched only
the Docker interface. At that time, removal of the old native Windows package was
awaiting Windows administrator/UAC approval; it completed on 6 November as noted
below. Cold Docker startup and reboot recovery were not tested by interrupting
other local projects.

## Station2 Docker desktop update — 6 November 2026

Station2 was updated from `28ddcf7` to `8495d9b` with a clean fast-forward pull.
Its existing Docker Collector already held the migrated source ending `633b`
and generation ending `a25a`, with both database and upload credentials present.
The old Windows shortcut opened a different native profile without a migration
marker and correctly triggered the migration guard. No second migration was
applied and no profile identity was replaced.

The existing scheduler was stopped normally. Ubuntu was installed into the
existing WSL 2 environment for WSLg, selected as the default distribution and
enabled in Docker Desktop integration. The separate desktop and Collector
runtime images were built from the allowlisted context. **SCADA Collector -
Docker** in Start and **Launch Collector.cmd** open the Linux container interface;
the former Windows shortcut is archived. Windows denied desktop shortcut creation,
so the installer now warns while retaining the working Start launcher.

The desktop window was detected as **SCADA Collector - Linux Docker (Ubuntu)**.
Its container runs as `10001:10001`, with a read-only filesystem, no network and
no published ports. Before/after fingerprints matched for all 12 files in the
data volume and the one encryption-key file. Native profiles and their queues
remain preserved. Collection remains stopped and opening the interface does not
start it.

Focused Windows checks passed **55 tests**, with one display-related skip.
The actual Linux desktop image passed **44 GUI/routing/recovery checks** without
skips using mocks and disposable profiles. Collector Compose validation and
PowerShell installer syntax validation passed. PostgreSQL integration, source
connection, HTTPS credential validity, live delivery and reboot recovery were
not tested as part of this desktop update. Private build logs and fingerprints
remain under ignored `.tools/`.

## Start failure correction — 6 November 2026

Station2's first Start attempt exposed a missing acceptance check: the interface
called Compose with `--build` even though its container has no network. Registry
authentication failed before the scheduler could start. The earlier GUI tests
mocked that operation and did not cover the actual nested image build.

Container-interface Start now uses only the installed runtime image, with builds
and pulls disabled. The Windows installation script builds both images before
publishing the launcher. The interface retains its network isolation and no
registry credentials are added to it. Legacy Windows-interface builds retain
their existing host build behavior.

The corrected image passed 58 focused Windows checks and 46 Linux desktop
checks, without skips. A real Docker check inside the network-isolated desktop
image started, inspected and stopped a separate disposable project using a local
image and an intentionally unavailable Dockerfile. The check mounted no
operational data/key volumes and removed its disposable container afterward.
The user closed the old interface normally before its replacement opened;
the running replacement loaded both the corrected Start implementation and the
original setup. Data/key fingerprints matched before and after. The operational
scheduler remains stopped; live source delivery and reboot recovery remain
unverified. Private diagnostics and disposable check helpers remain in `.tools/`.

## Local removal — 6 November 2026

The user selected this development PC for Docker Central Server and a separate
PC for the Collector. The standard Windows Collector uninstaller completed with
exit code 0. Its installed Program Files directory and installed-app registration
are gone. The stopped `linker-collector-desktop` container and all four dedicated
Collector runtime/desktop/test image tags were removed, as were the active Start
and desktop shortcuts. The installed Docker desktop context was moved into a
private recovery directory outside Git, so `current-launch.vbs` is no longer
installed. No Collector containers or dedicated image tags remain in Docker
Desktop. No Collector service, scheduled collection or Linux desktop entry was
found running.

Both `linker-collector_collector-data` and `linker-collector_collector-key` remain
preserved. They contain no files; read-only before/after fingerprints matched.
No source setup, key or replacement queue was initialized. Protected local
recovery material is retained under ignored `secrets/local-collector-removal-*`.
Source checkout files and earlier installers remain available for development and
the other PC; they are not installed/running Collector applications.

The retained `dist/installer/collector/0.4.1-b2f43dd017` installer and companion
Docker context ZIP were checked against their SHA-256 sidecars. They retain the
earlier native Windows interface; use this guide for a container-only interface.
Installation and source/HTTPS commissioning on the other PC remain separate
work. Existing SCADA software, drivers, source databases and unrelated Docker
projects were not removed. See [the running local Central Server](wsl-deployment.md#local-central-only-installation--6-november-2026).
