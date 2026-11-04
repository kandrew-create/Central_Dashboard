# SCADA Collector 0.4 — revision X3

[Download the X3 SCADA Collector installer](https://github.com/kandrew-create/Central_Dashboard/releases/download/X3/Linker-SCADA-Collector-Setup.exe). [Release notes and checksums](https://github.com/kandrew-create/Central_Dashboard/releases/tag/X3).

The current source GUI manages a single Docker Collector, with protected setup, bounded previews, automatic collection, durable staging, confirmed delivery and status. The published X3 Windows package remains the earlier native application; its service wrapper is retained for existing installations.

The separate local **0.4.1** package adds automatic Docker startup for an existing commissioned setup, a hidden upload URL and mode-specific schedule controls. It contains its own Collector-only Docker context without Central Server or Ollama. See [installation and safe upgrades on the Collector PC](../docs/collector-installation.md) and [update evidence and AI RAM measurement](../docs/collector-update-2026-11-04.md). This package is intended for the other PC; the Collector remains stopped on the Central development PC. Published X3 downloads are unchanged.

## Desktop use

For the Linux CLI/scheduler, including Docker Desktop on WSL 2, see [Collector WSL and Docker setup](../docs/collector-wsl-docker.md). The separate Collector Compose project preserves its queue and uses a separately mounted credential key. Native Windows operation continues to use DPAPI.

Open **Launch Collector.cmd**, or run:

The source-checkout GUI uses the Central Server's dark sidebar, light workspace, page headings and persistent activity/status footer. Choose **Connection & setup**, **Alarm & event preview**, **Collection & upload** or **Docker deployment**. Every page manages the same Docker Collector, including its saved source connection and Linux-protected credentials. Switching pages preserves unsaved edits. The GUI does not start a native Windows or notification-area scheduler.

The Collector uses a navy database-and-upload icon with a teal SCADA signal, drawn for Windows sizes from 16 to 256 pixels. The source window and shortcut share `deploy/collector/collector.ico`; future Windows builds also embed it in executables and the installer. Rebuild the icon and its PNG preview with `deploy/collector/build-icon.ps1` (Windows drawing APIs; no additional dependencies).

After changing the icon, run `deploy/collector/install-shortcut.ps1` to refresh the Start menu entry. It stores a copy under `%LOCALAPPDATA%\Linker\Collector\Icons` with a filename derived from the icon's hash. The shortcut lives in the **Linker SCADA Collector** Start menu group; the script removes the former root-level entry and notifies Windows of the new entry. This also replaces the old shortcut identity whose artwork Windows Search could retain even after the icon file changed.

The shortcut and Windows GUI share the explicit application identity `Linker.SCADA.Collector`. If Search still shows previous artwork while the Start app list and taskbar show the new icon, reopen Windows Search after its UI process refreshes; changing the icon file alone may leave Search's in-memory image unchanged. The corrected icon was verified in both the Search result list and its large preview.

**Reload Docker settings** reloads the single Docker configuration. The location reads `Docker: /var/lib/linker-collector/setup/config.toml`; local Windows profile files are retained as migration evidence, not used for collection. Importing a setup for a different source/generation cannot replace an assigned Docker identity or pending queue. See the [WSL setup handoff and connection verification](../deploy/collector-setups/README.md).

```powershell
& .venv/Scripts/python.exe -m collector gui
```

1. Save the source connection and store its password. Use a dedicated read-only PostgreSQL login with CONNECT, schema USAGE and SELECT only on the approved `alarmhistory` and `eventhistory` tables. Both the role and collector sessions must be read-only; ownership, write/admin and schema CREATE privileges are rejected.
2. In **Alarm & event preview**, choose **Alarms** or **Events** and click **Load preview**. It verifies the saved database connection and read-only permissions automatically before reading the bounded sample; a separate **Test connection** remains available on **Connection & setup**. **Test server** checks HTTPS upload authentication and does not enable database previews. Save database edits and store any newly entered database password first. Original strings, codes, flags, nullable times and separate milliseconds are preserved. Timezone selection is available in the GUI; unknown, ambiguous and invalid times are flagged without guessed UTC.
3. On **Collection & upload**, enter the provisioned source/generation IDs and locally approve an initial date range or all history. Choose the privacy policy, resource limits and schedule. Enable collection and save settings.
4. Import the encrypted Central Server setup to supply its HTTPS destination, upload credential and CA. The fixed URL has no visible editor and Test server does not echo it. Stored keys stay encrypted and hidden; a manually supplied replacement credential uses a masked entry that is cleared after storage. Certificate/hostname verification remains enabled. Save settings and use **Test server** on the actual Collector PC.
5. Use **Start Collector** to run the saved Docker schedule. **Stop Collector** stops that container normally after bounded work, retaining pending uploads. With it stopped, **Collect now** runs one bounded Docker cycle using the same configuration and queue. Status refreshes while the manager is idle; **Refresh status** is also available. Closing the GUI leaves the scheduled container running. Closing during a manual one-off requests cancellation and waits for bounded work to finish.

Opening settings clears credential entry fields. Editing connection/settings invalidates the preview connection check. External changes require reopening Docker settings before manual operations. Configuration and credentials pass through local Docker CLI stdin, with management-container logging disabled; no administration port or Collector listener is added. Stop the container before importing server setup.

## Background operation with Docker

Opening the updated manager starts an already-installed Docker Desktop if needed and resumes only an existing, enabled, identified Collector setup with required stored credentials. It reuses an already-running Collector. Fresh disabled or missing setups are not started or silently initialized. Close the manager whenever desired: the single Docker Collector keeps collecting and uploading on its saved schedule. No separate Windows tray Collector is needed. Interval controls are hidden for daily/weekly schedules without changing their saved value.

Keep Docker Desktop running; its restart policy resumes the container when the engine restarts, unless the Collector was explicitly stopped. First installation, license prompts, approved host networking and host reboot/sign-in behavior remain commissioning work. Closing the manager does not stop Docker Desktop or change the saved schedule. Refresh never restarts a Collector stopped in the current session; reopening an enabled setup resumes it.

On this PC, Docker Desktop host networking reaches the existing loopback SCADA PostgreSQL connection without changing the database listener, permissions or TLS settings. The native identity, full SQLite state, receipts and checkpoints were transferred intact; credentials were re-encrypted with the preserved Linux key. The original native setup and old unassigned Docker setup are retained. A local migration marker blocks accidental reuse of the migrated native runtime. See [Docker deployment and migration](../docs/collector-wsl-docker.md).

## Collection modes and coverage

`id_range` is the safe default for unknown or NULL/non-advancing change markers. Each cycle persists a fixed maximum ID and reads an ID-ordered reconciliation sweep in bounded pages. It detects changed content at previously seen IDs, including negative IDs. Large sweeps span multiple runs using durable progress. An insert or change behind the current cursor is seen on the next sweep if it remains in the source.

`marker` requires locally verified change-marker semantics. It uses a fixed `(last_update,last_update_ms,id)` upper bound, keyset pagination, a configurable overlap, a supplementary new-ID pass, and recent-ID reconciliation. Missing/invalid markers and content-only changes are covered within the configured reconciliation range. Changes older than that range and overlap are not guaranteed; use ID-range mode or commission a sufficient reconciliation policy. A timestamp LIMIT does not bound scan work without an index. Query timeouts fault without advancing the failed page; the collector never creates source indexes.

An initial date range remains the scope for pre-existing IDs on subsequent scans; new IDs after commissioning are eligible regardless of that initial historical window. Undated records are included with uncertainty. Date bounds use source-local time, with an exclusive end. New/changed rows are observations of mutable source rows; transitions overwritten between reads cannot be reconstructed.

Reset/gap checks use only the configured tables' filtered catalog identities (database OID, table OID, relfilenode) and bounded maximum-ID queries. Identity changes, ID regression or an empty formerly populated table latch a fault before pending uploads are attempted. Some maintenance operations, including a table rewrite, conservatively require review. This cannot identify every restore retaining identical metadata, manual ID reuse, hard deletion, or change outside the supported scan horizon. Source retention and reset evidence must be commissioned.

## Durability, privacy and delivery

SQLite transactions with FULL synchronous mode atomically stage immutable batches, content identities and extraction progress. Confirmed delivery progress is separate and advances only with an exact matching `{batch_id,payload_hash,status:"committed"}` receipt. Queue removal and delivery checkpoint updates share one transaction. A lost reply reuses the same batch ID, hash and bytes after restart.

Consecutive unchanged content is skipped. A return to a previously observed value after another state is sent as a new ordering observation, while central revision deduplication still preserves one occurrence. An interrupted scheduled occurrence resumes after restart; missed timer slots are coalesced.

Queue and state quotas plus minimum free space stop new staging while retaining pending work. Seen-content identities are retained for deduplication and count toward disk usage. Review capacity/retention before a long installation. Never delete queue/state files to clear a fault.

Default collection preserves all approved operator fields under `upload_all`. `omit` excludes the personal fields from transmitted records; `hash` replaces non-NULL personal values with keyed HMAC-SHA256. Store the hashing key with `set-privacy-key`; keep key ownership and rotation under local maintenance. Changing collection identity, timezone, history scope or privacy policy requires a reviewed new generation/setup. Local previews still omit operator fields unless explicitly selected.

HTTPS uses certificate/hostname verification, fixed locally configured URLs, no redirects or HTTP fallback, and bounded uncompressed JSON receipts. Proxy environment variables are ignored. Authentication/schema/receipt faults use a one-hour retry delay; transient transport faults use bounded exponential backoff. Rotating local logs contain counts and redacted faults, not passwords, raw records or operator text. The collector opens no listener and accepts no cloud commands or configuration.

## CLI (existing native installations)

```powershell
& .venv/Scripts/python.exe -m collector init
& .venv/Scripts/python.exe -m collector set-password
& .venv/Scripts/python.exe -m collector check-config
& .venv/Scripts/python.exe -m collector test-connection
& .venv/Scripts/python.exe -m collector preview --table alarmhistory --limit 5
& .venv/Scripts/python.exe -m collector set-upload-token
& .venv/Scripts/python.exe -m collector collect
& .venv/Scripts/python.exe -m collector status
& .venv/Scripts/python.exe -m collector run
```

Global `--config PATH` goes before the subcommand. Secrets use hidden prompts and current-user DPAPI blobs on Windows, never TOML values or password arguments. Linux uses encrypted `.fernet` files with a separately supplied private key; see the [WSL/Docker guide](../docs/collector-wsl-docker.md). `import-setup PATH` and `test-server` provide setup import and authenticated server testing through the CLI. Scheduled interval/daily/weekly runs persist their next occurrence, coalesce missed runs into one catch-up, and claim the occurrence before work. DST folds run at their first occurrence; gaps use the first valid minute after the gap.

For a reviewed source reset, provision a new generation centrally, then authorize it locally:

```powershell
& .venv/Scripts/python.exe -m collector new-generation --generation-id YOUR-PROVISIONED-UUID --authorization YOUR-LOCAL-TICKET
```

Old pending batches retain their original generation and bytes. The central server accepts backlog for known provisioned generations, including retired generations. Unknown generations are rejected. A journal recovers a crash between local settings replacement and state transition. See [operations](../docs/operations.md) for commissioning and recovery.

## Development verification

See the [3 November 2026 Collector QA review](../docs/collector-qa-2026-11-03.md)
for feature coverage, corrected Docker controls and remaining commissioning gates.

```powershell
uv pip install --python .venv/Scripts/python.exe -e '.[collector,server,test,local,build]'
& .venv/Scripts/python.exe -m pytest -q
```

PostgreSQL integration requires `SCADA_TEST_POSTGRES=1`, `PSQL`, `PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD` and `PGDATABASE` for an explicitly disposable test cluster. Never use a SCADA/customer database or cluster. Tests create/remove fixture databases and temporary roles. Windows/Tk/DPAPI tests need a desktop session. The measured evidence and remaining acceptance gates are recorded in the [implementation report](../docs/collector-server-implementation-2026-10-28.md).

## Central Server provisioning files (v0.3)

In **3 Collection & upload**, use **Import server setup** to load a password-encrypted `.linker-collector` file exported from the Central Server window. Save local edits and stop automatic collection before importing. This supplies the source/generation IDs, destination, protected upload credential and CA certificate; database access, history approval, limits and schedules remain local. A file for different source/generation IDs cannot replace an assigned collector's state. See the [Central Server Windows guide](../docs/central-server-windows.md).

In the current rebuilt Collector, pending edits to the Source ID, Generation ID, HTTPS URL, upload enable flag or upload CA path do not disable import: the selected server setup supplies those fields using the last saved local configuration. This resolves the case where enabling uploads with a blank URL prevents saving and previously disabled import. Unsaved local database/history/schedule changes or a typed unstored database password must still be saved/stored first. New setups explain the required local save when Import is clicked. Busy operations and automatic collection still block import.

After import, the **Upload credential** entry stays blank because the secret is stored in protected credential storage (Linux encryption for Docker; DPAPI in existing native Windows packages). **Test server** verifies that it can be unlocked and accepted. Do not enter the setup-file encryption password in the upload-credential field.

Completed server checks, credential storage and collection-status refreshes now replace their in-progress footer messages, so a successful action does not continue showing “Testing…” or “Protecting…”.

Version 0.4 supports network destinations exported by Central Server **4 Connection & mode**. **Test server** verifies HTTPS, upload credential and the active source/generation without uploading records or advancing state. Source database testing remains a separate **Test connection** action. Use Local testing for one PC and Network server for collectors on other PCs; setup changes require a fresh local import.

Use the single **SCADA Collector - WSL Docker** Start menu shortcut. Its sidebar manages the same Docker configuration and durable queue throughout. The shortcut installer removes obsolete separate manager shortcuts.
