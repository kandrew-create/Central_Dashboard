# Install the separate SCADA Collector 0.4.1

Install this package on the **Collector PC**, not the Central Server development PC. The Collector has its own installer, Docker image, Compose project (`linker-collector`), data volume and encryption-key volume. It does not install Central Server, PostgreSQL server, Ollama, PLC drivers, ODBC drivers or SCADA software. Local AI runs on the Central Server PC and consumes no Ollama RAM on the Collector PC.

## Before installation

1. Have the SCADA owner approve the PC, operating-system support, available CPU/RAM/disk, source database account, read limits and collection schedule. Record the existing SCADA/PLC/OPC/HMI/network driver versions and working configuration. Follow the site's normal backup/recovery and maintenance process.
2. Verify the supplied installer and Docker-context ZIP against their SHA-256 sidecars. Current development packages are unsigned. Keep earlier installers for recovery.
3. Verify that Docker Desktop/WSL 2 is vendor-approved on this PC. Installing or updating virtualization prerequisites may require a reboot or affect existing virtualization, security or networking software. Schedule that work with the SCADA owner; do not enable features, update drivers or reboot during production to satisfy this application. A separate approved Collector PC is an option where the existing source is already reachable through an approved connection.
4. Use Docker's [supported Windows installation procedure](https://docs.docker.com/desktop/setup/install/windows-install/). Select Linux containers and finish its first-run prompts. For an existing Windows loopback database, enable Docker Desktop host networking after approval. Never change the source PostgreSQL listener, TLS policy, access rules, schema or indexes to make Collector installation work.
5. Obtain a dedicated read-only PostgreSQL login with CONNECT, schema USAGE and SELECT only on approved alarm/event tables, with read-only sessions. The Collector uses its own psycopg/libpq inside Docker; it does not replace the Windows PostgreSQL, SCADA, PLC or ODBC driver installations. Source access remains bounded and read-only, but representative load and driver coexistence must still be tested on the actual PC.

## Fresh installation on the other PC

Run `Linker-SCADA-Collector-Setup.exe` on that PC. It installs Collector binaries and this guide under `C:\Program Files\Linker\SCADA Collector`; it does not launch collection, install a native service, install Docker or reboot. Keep its companion `Collector-Docker-Context-0.4.1.zip` for initial Docker setup. The ZIP contains only Collector/shared code and its build files; there are no Central Server services, models, credentials or records.

The first Docker image build needs approved access to the container registry and Python package index. The ZIP contains build inputs, not a prebuilt image. For an offline PC, arrange a separately verified Collector image transfer through the site's approved process; do not change SCADA networking or drivers to provide Internet access.

Extract the ZIP to a persistent folder, for example `%LOCALAPPDATA%\Linker\Collector\docker-context-0.4.1`. In PowerShell under the intended operator account:

```powershell
$collectorContext = Join-Path $env:LOCALAPPDATA 'Linker\Collector\docker-context-0.4.1'
$env:COLLECTOR_HANDOFF_DIR = Join-Path $env:LOCALAPPDATA 'Linker\Collector\handoff'
New-Item -ItemType Directory -Path $env:COLLECTOR_HANDOFF_DIR -Force
$collectorComposeArgs = @('--project-name','linker-collector',
    '-f',(Join-Path $collectorContext 'deploy\docker-compose.collector.yml'),
    '-f',(Join-Path $collectorContext 'deploy\docker-compose.collector.host.yml'))
docker compose @collectorComposeArgs config --quiet
docker compose @collectorComposeArgs build collector manager key-init
```

The second Compose file selects host networking for the unchanged Windows loopback source connection. It requires supported Docker Desktop with host networking enabled. On other approved Linux deployments, use only the base Collector Compose file and an already-authorized reachable source address; do not change SCADA networking as an installation shortcut.

**Only for a genuinely new, unassigned Collector setup**, create its private encryption key and disabled configuration:

```powershell
docker compose @collectorComposeArgs --profile setup run --rm key-init
docker compose @collectorComposeArgs run --rm collector init
```

Never run these commands to replace missing operational state. The key creator refuses to replace a key; initialization requires a new setup directory. Preserve both `linker-collector_collector-data` and `linker-collector_collector-key`. If either is missing after prior commissioning, restore/review the original state instead of creating an empty replacement queue. Windows DPAPI credentials cannot simply be copied into Linux; an assigned native Collector needs a reviewed stopped migration of the entire identity, queue, checkpoints and credentials.

Open **Collector** from Start. Opening starts Docker Desktop if necessary. A missing configuration/key/image produces an explanation; it is not initialized silently. Collection remains stopped for a fresh disabled setup.

1. In **Connection & setup**, enter the existing database host, port, database and dedicated read-only username. Store its password, then **Test connection**. Do not enable collection yet.
2. On Central Server, register this SCADA database source separately and export its password-encrypted `.linker-collector` setup. Transfer the file and unlock password separately through an approved channel. Import it under **Collection & upload**. It supplies the source/generation IDs, HTTPS destination, upload key and CA certificate; no URL entry is shown.
3. Use **Test server** on this actual remote PC. It checks HTTPS trust, credential and active registration; it does not collect records. Do not disable certificate verification or use a local-test-only export for a remote PC.
4. Approve the history/timezone/privacy policy and resource limits. Select interval, daily or weekly scheduling. Interval controls appear only for interval mode; the previous interval value is retained when hidden. Daily/weekly time is local to the saved schedule timezone, not a change to the SCADA PC clock.
5. Save settings, locally enable collection, then perform one approved bounded collection. Confirm the durable receipt and Central storage/processing/mapping status. A stored batch can still await mapping approval. Test source load and SCADA operation before leaving the schedule enabled.

Later app launches resume only an existing, enabled, identified setup with the required stored credentials. Already-running collection is reused. Stop Collector stops its own container normally and retains pending work; closing the manager leaves it running. Refresh does not restart a Collector stopped in the current session. The app opens no listener and accepts no remote configuration commands.

## Upgrade and recovery

Stop this Collector through its existing manager before upgrading; wait for bounded work to finish. Preserve both volumes, encrypted keys/vaults, settings, source/generation IDs, queues, receipts and checkpoints. Close the manager, install the updated Collector package and reopen it under the same Windows/Docker account and project. A normal stopped start rebuilds the separate Collector image from the bundled context while reusing existing volumes. Do not run a native scheduler and a Docker scheduler for the same source.

An existing native profile with saved state and no completed Docker migration marker blocks automatic Docker startup. Do not clear that state or delete the marker to bypass the guard. A missing setup, engine error, source identity fault or invalid credential needs investigation; do not reset Docker, remove volumes, change IDs or reinstall PostgreSQL/SCADA drivers to bypass it. Closing the GUI and rollback of binaries do not roll back database records or queue state.

The app only launches an already-installed Docker Desktop; first installation, license prompts, host-networking selection, Windows feature enablement and reboot remain approved operator work. Docker cold-start, real source load, actual remote-PC commissioning, driver coexistence and recovery acceptance must be checked on the target PC. Building and testing this package on the Central PC does not commission that remote installation.
