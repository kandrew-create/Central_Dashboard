# Processing without machine mappings

The user removed the machine-mapping requirement. Central-only migration **0015_source_scoped_processing**, together with the updated API, worker and managers, makes collection and processing depend on authenticated customer/source/generation identity. Machine mapping approval is no longer part of the workflow.

## Current behavior

- Valid uploads are committed and receive the same durable batch ID/hash receipt as before. Unknown or revoked credentials, foreign source IDs, unauthorized generations, invalid payloads and batch-ID/hash conflicts remain rejected. Removal of mapping checks does not grant any new source or customer access.
- The API and worker never look up mapping rules. New revisions have `mapping_status='not_required'`, with no invented machine, mapping version or interpreted severity. Native priority/type fields and original payloads remain preserved. A fully processed job completes its batch even when no equipment is identified.
- Registration creates no draft mapping version. The `approve-mapping` administration command and its matching-rule provisioning options were removed. Alarm analysis no longer displays approved-mapping columns or missing-mapping counts.
- Historical unmapped revisions move from `quarantined` to `not_required`. A quarantined batch becomes completed only when its matching processing job already completed. Pending, leased and failed jobs retain their actual status and must finish/retry normally. The migration appends per-customer release counts to the audit log.
- Original fields/times/milliseconds, revision IDs/hashes, receipts, source/generation identity, credentials, scope and job evidence remain intact. Existing mapping tables and previously mapped annotations remain inactive historical metadata; no runtime capability can read or administer those tables, and new/replayed data does not rewrite old annotations. They are retained to avoid deleting historical evidence and to support reviewed recovery.

Optional alarm AI remains a separate equipment suggestion feature. It does not approve mappings or assign authoritative machine identity. Viewing results never enables AI or calls a model. Existing registered event identity remains constrained by the immutable machine scope saved when that upload was accepted; empty/multiple scopes remain uncertain. No event identity is inferred from messages or `ev_source`.

Time and revision-order uncertainty remain visible. A fact's latest-state fields, including its historical mapping-status field, can remain NULL when no latest revision is verified; this does not block storage or processing.

## Check received data

The existing named reporting views still support project/source filters:

```sql
SELECT * FROM reporting.alarm_occurrences
WHERE source_name='ELT250330DB'
ORDER BY source_record_id LIMIT 100;
```

Use `reporting.event_occurrences` for events. The stored source is ELT250330DB (ELT, not ETL). Project labels remain separate; no registrations were renamed. Read processing totals through `reporting.source_upload_summary`; zero mapping holds is expected after completed historical jobs are released. A committed upload is distinct from completed processing and from optional identification.

## Upgrade and recovery

Apply Alembic through 0015 to **Central storage only**, with its configured writers/manager stopped, after an encrypted restore-verified backup. Deploy the matching API, worker and manager code before resuming. Older binaries still query mapping tables and must not be mixed with the retired runtime privileges. Preserve settings, private credentials, local queues and named volumes. No Collector or SCADA database change is required.

The migration updates workflow statuses and queues derived refreshes; it does not delete or manufacture source records. Worker maintenance refreshes facts and summaries independently of ingestion and AI. Before declaring the upgrade complete, verify preserved immutable evidence, expected release counts, empty/retry-free refresh queues and API/database/worker readiness.

Downgrading 0015 restores the old mapping constraints/permissions and changes source-only records back to quarantined for the older workflow. It never invents an approved mapping. Match application binaries to the migration level and use the protected pre-change backup for exact recovery. Do not downgrade merely to hide an operational fault.

## Local deployment and verification - 7 November 2026

The existing local WSL/Docker project `linker-scada-wsl` now runs 0015 with the matching API, worker and manager. The manager closed normally before the selected writers stopped. An encrypted custom-format backup was decrypted in memory and fully restored into an isolated PostgreSQL 17.6 tmpfs container with no external networking/logging. The candidate image migrated this copy, bounded refresh finished and release/security checks passed before operational migration. Private backup, key, pre-change code, before-state fingerprints and diagnostics remain under mode-0700 `~/central-server/secrets/source-processing-20261107`; key files remain mode 0600 and outside Git/releases.

All **61 previously quarantined saved versions** now have `mapping_status='not_required'`. All **five previously held batches** are completed, with zero mapping holds, failed batches or pending/retrying refreshes at verification time. Their jobs were already completed; no job was fabricated or reset. Exact original/normalized revision evidence (excluding only the intended workflow status), receipt/batch evidence (excluding only processing status), identities, credentials, scope, jobs, historical annotations and prior audit rows matched. Derived fingerprints matched after excluding intended status counters and maintenance timestamps; original occurrence/version counts stayed **nine alarms and 52 events**. The migration appended the expected release audit entry. No source, project or machine identity was renamed or inferred.

Database system identity, `.env`, endpoint, CA, manager keys/vaults and named volumes matched. Runtime login provisioning was not rerun. API/database/worker are ready; the manager reopened. Actual manager analysis omits mapping metrics/columns. The existing pgAdmin passfile/account, named-view filtering and login/reconnect passed. Fixed-customer scope remained enforced; writes, credential/raw-payload access and role switching were denied. Windows verified the saved HTTPS CA and unauthenticated ingestion was rejected.

Checks performed:

- Fresh disposable PostgreSQL **17 and 18**: **146 passed, seven Linux-only skips each**. Coverage includes source-only acceptance, ignored historical rules, no mapping approval/reprocessing requirement, durable replay, cross-source/generation rejection, migration release only for completed jobs, preserved historical annotations and downgrade/re-upgrade.
- Isolated Linux container/disposable PostgreSQL 17.6: **24 passed, no skips**, covering Linux vault/agent behavior, mapping retirement, historical-copy removal, named views, concurrent AI/replay locking and source-only delivery.
- WSL Qt offscreen checks against an isolated source copy: **24 passed, no skips**, including the five-column analysis layout without mapping prompts and preserved background I/O/status behavior.
- Windows Docker manager/GUI: **19 passed; 24 optional Qt checks skipped**, covered by the WSL Qt run.
- Central Compose template validation and Git whitespace checks passed. Existing Starlette/httpx deprecation warnings remain.

Only the current local Central project was upgraded. No SCADA database writes, Collector installation/run, pending-queue changes, credential rotation, separate VMware server migration, published installer rebuild or Git push was performed. Existing remote upload identity remains valid, but fresh remote-PC delivery, reboot and production load were not re-commissioned as part of this change.

## Equipment label edits

The later 0016 update adds [equipment suggestions and manual label overrides](equipment-suggestions.md) in Alarm analysis. This does not reintroduce mapping approval: labels are source/tag/message annotations, with independent audit/version checks and no changes to source identity, machine UUIDs, accepted credential scope, native records or upload processing.
