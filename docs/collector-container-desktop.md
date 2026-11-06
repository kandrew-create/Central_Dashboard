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

The installer builds a separate desktop image and creates **SCADA Collector -
Docker** shortcuts in Start and on the desktop. Each installation uses a fresh
directory under `%LOCALAPPDATA%\Linker\Collector\docker-desktop`. Earlier packages
and all data/key volumes remain intact. Building requires access to Debian,
Docker Hub and the Python package index; normal launch uses installed images.

Open the shortcut. The launcher starts an already-installed Docker Desktop if
necessary, starts WSLg, and opens only the `desktop` service in `linker-collector`.
It never installs Windows features, changes source networking, creates keys,
initializes data volumes or starts collection. Use **Start Collector** explicitly
after commissioning. **Stop Collector** stops the scheduler normally; closing
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

The replacement Start/desktop shortcuts and `Launch Collector.cmd` launch only
the Docker interface. Removal of the old native Windows package was requested
through its standard uninstaller; its Windows administrator/UAC approval remains
pending. That package is not running or used by the new launchers. Cold Docker
startup and reboot recovery were not tested by interrupting other local projects.
