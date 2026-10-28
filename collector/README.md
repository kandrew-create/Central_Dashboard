# SCADA Collector 0.4

The native Windows GUI and CLI provide protected connection setup, bounded previews, automatic collection, durable staging, confirmed delivery and status. A native Windows service wrapper and installer are included. Installation, startup under a dedicated account, and representative customer commissioning still require separate verification.

## Desktop use

Open **Launch Collector.cmd**, or run:

```powershell
& .venv/Scripts/python.exe -m collector gui
```

1. Save the source connection and store its password. Use a dedicated read-only PostgreSQL login with CONNECT, schema USAGE and SELECT only on the approved `alarmhistory` and `eventhistory` tables. Both the role and collector sessions must be read-only; ownership, write/admin and schema CREATE privileges are rejected.
2. Test the connection and inspect the bounded preview. Original strings, codes, flags, nullable times and separate milliseconds are preserved. Timezone selection is available in the GUI; unknown, ambiguous and invalid times are flagged without guessed UTC.
3. On **Collection & upload**, enter the provisioned source/generation IDs and locally approve an initial date range or all history. Choose the privacy policy, resource limits and schedule. Enable collection and save settings.
4. Enter the fixed HTTPS destination. Public CA verification is the default. An explicit local CA file supports the isolated commissioning server without installing global trust. Store the upload credential, enable upload and save settings.
5. Use **Collect now**, or **Start automatic collection**. Refresh status for queue usage, last successful upload, latest confirmed source time, next run and errors. **Stop** and window closing wait for the current bounded operation. GUI scheduling ends when the window closes.

Opening settings clears credential entry fields. Editing connection/settings invalidates the preview connection check. External file changes require reopening settings before manual operations. Do not run the GUI scheduler and service together for the same setup; process locks prevent concurrent schedules/cycles.

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

## CLI

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

Global `--config PATH` goes before the subcommand. Secrets are hidden prompts and current-user DPAPI blobs, never TOML values or password arguments. Scheduled interval/daily/weekly runs persist their next occurrence, coalesce missed runs into one catch-up, and claim the occurrence before work. DST folds run at their first occurrence; gaps use the first valid minute after the gap.

For a reviewed source reset, provision a new generation centrally, then authorize it locally:

```powershell
& .venv/Scripts/python.exe -m collector new-generation --generation-id YOUR-PROVISIONED-UUID --authorization YOUR-LOCAL-TICKET
```

Old pending batches retain their original generation and bytes. The central server accepts backlog for known provisioned generations, including retired generations. Unknown generations are rejected. A journal recovers a crash between local settings replacement and state transition. See [operations](../docs/operations.md) for commissioning and recovery.

## Development verification

```powershell
uv pip install --python .venv/Scripts/python.exe -e '.[collector,server,test,local,build]'
& .venv/Scripts/python.exe -m pytest -q
```

PostgreSQL integration requires `SCADA_TEST_POSTGRES=1`, `PSQL`, `PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD` and `PGDATABASE` for an explicitly disposable test cluster. Never use a SCADA/customer database or cluster. Tests create/remove fixture databases and temporary roles. Windows/Tk/DPAPI tests need a desktop session. The measured evidence and remaining acceptance gates are recorded in the [implementation report](../docs/collector-server-implementation-2026-10-28.md).

## Central Server provisioning files (v0.3)

In **3 Collection & upload**, use **Import server setup** to load a password-encrypted `.linker-collector` file exported from the Central Server window. Save local edits and stop automatic collection before importing. This supplies the source/generation IDs, destination, protected upload credential and CA certificate; database access, history approval, limits and schedules remain local. A file for different source/generation IDs cannot replace an assigned collector's state. See the [Central Server Windows guide](../docs/central-server-windows.md).

Version 0.4 supports network destinations exported by Central Server **4 Connection & mode**. **Test server** verifies HTTPS, upload credential and the active source/generation without uploading records or advancing state. Source database testing remains a separate **Test connection** action. Use Local testing for one PC and Network server for collectors on other PCs; setup changes require a fresh local import.
