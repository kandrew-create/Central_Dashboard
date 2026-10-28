# Central Server for Windows — local and network testing

Software 2 has a native Windows management window. Version 0.4 provides Local testing and Network server modes. PostgreSQL 17 must already be installed; the executable includes the application dependencies but not PostgreSQL itself. Central storage always uses a separate PostgreSQL database on the server PC's loopback address. SCADA source storage is not initialized or changed.

| Setting | Local testing (one PC) | Network server (two PCs) |
|---|---|---|
| Collector location | Same PC as the server | SCADA PC on a reachable network |
| HTTPS listen address | `127.0.0.1` | `0.0.0.0` for all IPv4 adapters, or a specific server LAN IPv4 |
| Central PC hostname / IPv4 | `localhost` | Reachable DNS/PC name or stable IPv4, for example `192.168.10.5` |
| HTTPS port | Default 8443 | Default 8443; configurable |
| Exported upload URL | `https://localhost:8443/v1/uploads` | `https://192.168.10.5:8443/v1/uploads` in this example |
| HTTPS trust | Private commissioning CA in setup file | Private commissioning CA in setup file; certificate matches the saved hostname/IP |

These are working deployment settings, not a simulated-upload switch. Both modes use authenticated HTTPS, durable receipts, queueing and normal worker processing. No setting disables TLS verification.

## Open the software

On this development PC, double-click `Launch Central Server.cmd`. The standalone executable is `dist/central-server/central-server.exe`; the installer is `dist/installer/Linker-Central-Server-Setup.exe`. Install the updated collector using `dist/installer/Linker-SCADA-Collector-Setup.exe` to get the Import server setup button in the installed Collector. Close the collector window and stop its scheduler/service before updating it. Configuration and pending state are retained by the installer.

For a source checkout, install dependencies with `uv pip install -e ".[collector,server,manager]"` in the project environment. Build the server using `deploy/windows/build-server.ps1`; build the collector using `deploy/windows/build.ps1`. Inno Setup 6 is required to produce either installer. These test builds are unsigned.

## Set up this PC

1. Open **1 Server status**. The existing local test installation should report HTTPS API Ready, PostgreSQL Ready and Worker Running. Its ports are 8443 and 55441. Use **Initialize / start server** if stopped. The first start of a new data folder initializes a separate SCRAM-authenticated PostgreSQL database, applies migrations, creates restricted runtime logins and creates local TLS certificates.
2. Open **3 Sources & collector setup**. The existing source is `LOCAL-SCADA`; select it. Its existing IDs and data are preserved. It does not need to be registered again.
3. Choose **Export encrypted collector setup**. Select a new filename and a password of at least 12 characters. Keep the file password separate from the file.
4. Open the updated Collector, load its saved local configuration, and stop automatic collection before importing. Open **3 Collection & upload → Import server setup**, select the file, and enter its file password.
5. The import fills Source ID, Generation ID, HTTPS destination, upload credential and trusted CA. It enables uploads. The local database password, source connection, history approval, read limits, privacy policy and schedule are preserved. Use **Test server** to verify HTTPS, credential and active source/generation without uploading records. Verify **Enable collection**, save any intended local edits, test the source database connection, then use **Collect now** and **Refresh status**.
6. Use **Start automatic collection** for the configured interval/daily/weekly schedule while the Collector window is open. An unattended Windows service still needs separate account commissioning. Closing the Central Server window leaves its background components running; use **Stop server** to stop them.

## Register a future source

On the central server PC, open **2 Register SCADA source**. Select existing customer/site/project/machine entries or create the missing entries, then supply a distinct SCADA PC/database source name. **Register source and generate IDs** creates the source, generation, protected upload credential and draft mapping version. Export that source's setup from tab 3.

On the SCADA PC, the operator imports the file into its local collector configuration. Source ID identifies the registered SCADA database; it is not a PostgreSQL server ID. Generation ID identifies one continuous incarnation of that source history. Database replacement/reset is an explicit recovery operation, not automatic reassignment during import. An import with different IDs is rejected if the configuration is already assigned or has incompatible durable state.

## Set up a separate central PC

1. Install PostgreSQL 17 and Central Server 0.4 on the central PC. Open **4 Connection & mode**. Stop an existing running server before changing mode, addresses, ports or storage location.
2. Choose **Network server (two PCs)**. The listen address defaults to `0.0.0.0`. Use a specific LAN IPv4 address if the server should accept connections only on that adapter.
3. Enter the central PC's stable IPv4 or resolvable hostname in **Central PC hostname / IPv4**. Enter only the name/address, without `https://`, a port, or a path. `localhost`, loopback destinations and unspecified destination addresses are rejected in Network mode. Confirm the HTTPS port and the URL preview.
4. Save server settings, then return to **1 Server status → Initialize / start server**. This prepares a certificate with the saved hostname/IP and starts the selected listener. PostgreSQL remains on loopback even when HTTPS accepts network connections.
5. Configure Windows Firewall and any network firewall to allow collector PCs to reach the selected HTTPS TCP port. Limit access to the intended network/collector PCs. The application does not change firewall rules. Do not expose the central PostgreSQL port for collection.
6. Register the SCADA source on the central PC, or select an existing source if its registry was migrated. Export its encrypted setup. The export now contains the saved network address and CA certificate; it cannot be exported with a stale certificate for a different address.
7. On the SCADA PC, open Collector 0.4, import the setup and choose **Test server**. Success confirms the destination, certificate/hostname, upload credential and active source/generation. This test uploads no history and advances no checkpoints. Then test the source database connection and use **Collect now**.
8. Enable the intended schedule and start automatic collection. Stop the central server briefly during testing, verify that the collector retains pending work, restart it and verify delivery completes. Check both delivery status and central processing/quarantine status.

Changing a destination requires a fresh export/import; settings do not synchronize in the background. Use the central PC's reachable address, not the SCADA PC's address. A hostname must resolve from the SCADA PC. Changing a server address does not change source/generation IDs.

If the second PC starts with a new central database, it has a new registry. An already assigned collector cannot import unrelated IDs over its existing state. For a fresh test, use **New setup** in the Collector and configure its source access/history approval separately, preserving the original setup and pending queue. To keep existing IDs/history, migrate central data and re-provision Windows-protected credentials through the recovery workflow; copying a DPAPI-protected folder between PCs/accounts is not a migration procedure.

Both the server and collector must be updated to 0.4 for **Test server**; an older server reports that this test endpoint is unavailable. No remote administration listener is added. The API exposes ingestion and a bounded credential-authenticated connection check; responses do not carry extraction instructions or settings changes.

New registrations have a draft mapping. Received raw alarm/event data remains quarantined until an authorized exact machine mapping is approved and the batches are reprocessed. The existing administration commands cover mapping approval, generation recovery, credential revocation and reprocessing; see [operations](operations.md). The setup window does not approve mappings automatically. The Web Portal and customer reporting remain later work.

## Storage and credentials

Manager settings are in `%ProgramData%\Linker\CentralServer\manager.json`. New standalone installations default to a dedicated `data` folder alongside that file. On this development PC, manager settings point to the existing `.tools/local-server` folder so the original source IDs, receipts and records remain available. Do not delete or move that folder while using this test installation. Moving it to permanent server storage requires a stopped-server migration and verification.

The local Windows account owns the private files; administrator/runtime passwords and recoverable collector upload credentials use current-user DPAPI. Exported setup files use password-derived authenticated encryption. The central registry stores upload credential hashes. A replacement upload credential leaves prior credentials valid to avoid disrupting an existing collector; revocation is a separate explicit administration action.

Stop the server before changing its mode/addresses/data folder/ports or updating/uninstalling the application. Uninstall retains database, queue, settings and credentials. Do not run a second manager against the same data folder concurrently. This is a commissioning package, not a Windows service or a completed production deployment. An actual test from the second PC, clean-account unattended service checks, off-server restore and representative SCADA load checks remain commissioning gates.

New commissioning certificates have a 90-day leaf lifetime; the private CA is retained across normal leaf renewal and hostname/IP changes. Starting the server renews the leaf near expiry. Existing valid local certificates are preserved. Moving an older local-only installation to a new hostname may generate a new CA if its signing key was never stored; export and import the new setup afterward. CA replacement or eventual CA expiry also requires fresh setup trust. Production TLS and server hardening follow the separate deployment design.
