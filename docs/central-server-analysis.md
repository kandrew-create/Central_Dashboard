# Central Server analysis and security punchlist

## Implemented scope

The WSL/Docker manager adds **Analysis** for recurring alarms, affected equipment and daily trends. Counts are calculated from saved records. The optional local model continues to suggest equipment names; it does not diagnose root causes or establish authoritative machine identity. Mapping approval is retired by [source-scoped processing](source-scoped-processing.md). Equipment review and AI settings now share Analysis; the duplicate Identification page is removed. Viewing or refreshing never enables AI or calls a model.

| Requested item | Implementation |
| --- | --- |
| Standard warehouse structure | `0010` introduced reporting views; `0011_stored_warehouse` stores alarm/event facts and summaries; `0012` shares new-source storage; `0013_remove_source_copies` verifies and removes legacy duplicates; `0014` adds named occurrence views for project/source filtering. |
| Alarm issue analysis | Customer/source filters, first-saved time windows, top 50 exact message/tag groups, separate AI suggestions and daily alarm/event descriptions/equipment by source and UTC date (or Uncertain date). |
| Identity and API credential security | IDs identify data; the bearer credential authorizes customer/source/machine scope. Existing hashing, encryption, TLS and revocation are retained and tested. |
| Encrypted, hidden API key | PostgreSQL stores a SHA-256 verifier. Local setup credentials remain encrypted and GUI/RPC operation responses omit the token. |
| Refresh in minutes | New profiles default to one minute; existing second-based intervals are retained as fractional minutes. Off remains available. |
| Hidden upload URL | Removed URL labels, preview and Copy URL. The real saved endpoint remains in encrypted exports; Settings & Configuration still permits hostname/listener/port repair. |
| Automatic Docker startup | Windows launchers start Docker Desktop if needed. Opening the WSL GUI starts its configured project once, reuses a ready project and leaves it running on close. |

Published X3 packages remain unchanged. Packaged-launcher changes require a future rebuild. The Windows source shortcut uses the checkout immediately; Linux GUI/backend changes require deployment and migration.

## Column filters and CSV export

The former **Deployment** page is named **Settings & Configuration** in the sidebar and page heading; its saved settings and actions are unchanged.

Click the **▾** in an Analysis table column heading to open its Excel-style value checklist. Search within the checklist, check the values to keep, then select **Apply**. **Select all shown** checks/unchecks the values in the current checklist search; **Cancel** retains the previous filter. A dot marks an active column filter. Filters on different columns are combined, and each table keeps its own choices across refresh and scope changes in the current session. Menu choices reflect other column filters and the text search. Use **Clear filter** for one column or **Clear column filters** for that table; the separate text search remains available. Relative activity bars have no value filter. Filters operate only on the loaded top 50 recurring alarm groups and up to 1,000 daily groups, with matching/loaded counts shown. Hidden selections cannot be edited.

Each table has **Export .csv**. Choose a filename to export a snapshot of its currently visible rows, with column names and equipment origin (manual, unverified AI, registered or unavailable). Activity bars and filter decorations are omitted. Exports retain descriptions, Unicode, quotes, line breaks and uncertain-date labels; UTF-8 with a BOM supports Excel. Cells that resemble spreadsheet formulas are prefixed with an apostrophe so Excel treats them as text; stored source fields are unchanged. Files are written outside the GUI thread using an atomic replacement, so a failed write retains an existing destination. Export is disabled for an empty filtered table; cancellation does not create a file. The file dialog defaults to the private workspace `exports` folder; choose a Windows-accessible location if opening it from Windows Excel. CSV files contain the displayed data and should remain outside source control.

Verification on 7 November 2026: all 43 Qt checks passed without skips. Tests cover checklist search/select/cancel/clear, combined filters and refresh persistence, hidden-row equipment identity, navigation caption fit, visible-row CSV snapshots, off-thread writes, UTF-8/quotes/newlines, formula-safe cells, cancellation and failed-write preservation. The deployed local WSL/Docker manager passed live header-menu, persisted-filter, both-table CSV and Settings & Configuration checks against the existing 72 daily groups; typing/filtering/export performed no report reads and saved AI configuration was unchanged. The footer remained visible at minimum size. An encrypted full backup restore and pre-start table/identity comparisons preserved all 12 batches/201 saved versions, credentials, named volumes and settings. Protected prior-code/backup/test-export evidence is outside Git at `~/central-server/secrets/excel-csv-20261107`. No database query/schema change required new PostgreSQL compatibility tests; published installers and remote Collector/VMware deployments were not updated. Actual Excel application import was not exercised.

## Table text filters

On **Analysis**, use the search field above either table to filter its loaded rows immediately. Recurring alarms search source, tag, original description, equipment and saved AI suggestion; daily occurrences also search UTC day (including **Uncertain date**) and Alarm/Event type. Matching is case-insensitive literal text, with surrounding spaces ignored. Each search is independent; use its clear icon to show all loaded rows again. The counter shows matching groups out of loaded groups, rather than occurrence totals.

Search text remains in place after analysis refresh and customer/source/time changes during the current window session. The top report totals retain the selected report scope. Searches apply only to the loaded top 50 recurring groups and up to 1,000 daily groups; adjust customer/source/time filters and analyze again to change that scope. Searches never fetch additional records, call AI or change stored data. A selected alarm hidden by search is deselected and cannot be edited; choose a visible row to edit equipment.

Verification on 7 November 2026: all 36 Qt checks passed, including independent literal searches, clear/no-match counts, refresh/scope persistence and hidden-row editing safeguards. The deployed WSL/Docker UI passed the same checks against 72 loaded daily groups (26 alarms/175 events); typing and clearing performed no report I/O, explicit refresh retained the search, and the footer remained visible at minimum size. Existing data/AI settings were preserved after an encrypted full restore check. Protected backup/prior-code evidence is outside Git in `~/central-server/secrets/analysis-filter-20261107`. No query/schema change required a new PostgreSQL compatibility run; prior daily-report PostgreSQL 17/18 evidence remains below. Published installers and remote Collector/VMware installations were not updated.

## Warehouse and analysis contract

`warehouse.dim_customer`, `dim_site`, `dim_project`, `dim_source`, `dim_machine` and `dim_date` provide named dimension views. `fact_alarm_occurrence` has one row per `(customer_id, source_id, generation_id, source_record_id)` for processed alarms; `alarm_daily` groups those facts by source and UTC source-start date. Since `0011`, alarm/event facts are physical tables refreshed from committed revisions. Registration dimensions remain live views of authoritative UUIDs/labels. This does not copy or modify a SCADA source database.

Saved versions never count as repeat occurrences. Generations separate reused record IDs. Mapping approval is not required; 0015 releases completed historical mapping holds. Unknown revision order still leaves latest state unavailable. Source dates are used only when all saved versions agree on a known UTC start timestamp; conflicting/missing/unknown times are flagged and shown in an explicit **Uncertain date** bucket, outside dated trends. Raw fields, separate milliseconds and history remain unchanged.

The time window uses when each occurrence was **first saved in Central**. Backfill may show older source dates. Results are bounded to 50 recurring alarm groups and 1,000 daily alarm/event groups, newest confirmed UTC dates first; the manager warns when daily results are truncated. Daily rows separate source, record type, original alarm/event description and effective equipment name. Alarm names use an audited override or evidence-matched saved AI suggestion; event names use accepted registered-machine identity only. Missing equipment stays uncertain/unavailable, and tooltips identify manual, unverified AI or registered origins. Unknown source times never acquire an invented date. Recurrence groups use exact messages/tags and do not prove a common cause. AI equipment labels remain in an unverified column and do not gate processing. Migration 0016 adds an Equipment column with an audited user override and clear-to-AI control; see [equipment editing](equipment-suggestions.md). Evidence-matched saved suggestions remain visible with uncertain time/order, without inventing latest state. No alarm duration, root cause or maintenance action is inferred.

Views use `security_invoker=true` with existing forced customer RLS and explicit reader column grants. PostgreSQL describes [invoker privileges and row security](https://www.postgresql.org/docs/17/sql-createview.html). Readers receive no payloads, operator fields, credential verifiers or writes. The trusted local manager may review all customers and provides customer/source filters; it is not a public customer reporting API. Portal, OIDC, Grafana, notifications, event analytics and diagnostic AI remain future work. Aggregation retains management statement timeouts; production-sized workloads still require measurement.

## Stored warehouse architecture

The current Central database has three fixed schemas:

```mermaid
flowchart LR
    collectors[SCADA Collectors] -->|HTTPS and durable receipt| platform[platform: registrations, original revisions, receipts and jobs]
    platform -->|Durable occurrence queue| warehouse[warehouse: shared dimensions and stored alarm/event facts]
    warehouse -->|Dirty source/date buckets| reporting[reporting: hourly, daily and equipment summaries]
    platform -->|Committed batch/status changes| uploads[reporting.source_upload_summary]
```

This is a logical star model with shared UUID dimensions and stored occurrence facts. It does not generate a schema per new source. Migration 0013 removes verified legacy source copies; 0014 adds named invoker views, and 0015 retires mapping approval while retaining original history. Source/Generation IDs, table type and native ID preserve identity across collectors, database resets, replay and reused native integers. No migration is applied to a SCADA database.

| Object | Grain / meaning |
| --- | --- |
| `warehouse.fact_alarm_occurrence` | One processed alarm occurrence per customer/source/generation/native ID, including unmapped records. Versions are counted separately. |
| `warehouse.fact_event_occurrence` | One processed event occurrence using the same identity rule within eventhistory. Native event times and revision markers are preserved. |
| `reporting.alarm_hourly_summary` | Customer/source/UTC source-start hour, including a separate NULL bucket for uncertain times. |
| `reporting.alarm_daily_summary` | Customer/source/UTC source-start day, with occurrence/version and uncertainty totals. |
| `reporting.equipment_alarm_summary` | Historical customer/source/day/machine grouping; new source-only rows use the NULL machine bucket. AI labels never populate machine IDs. |
| `reporting.source_upload_summary` | One row per customer/source, with committed batch totals, declared record/byte counts, processing-state counts and last receipt time. Declared record totals are not unique occurrence counts. |

The worker has an independent warehouse-maintenance thread. Small transactional triggers coalesce committed revision, latest-alarm-state, identification and upload-status changes into durable queues. A bounded SQL maintenance call locks ready rows with SKIP LOCKED, reconstructs only changed occurrences and updates affected alarm day/hour/equipment buckets. Source upload summaries aggregate only changed sources using a source/receipt index. Queue entries are deleted only with committed derived updates. A failed occurrence retains its original history and retries with a bounded delay; SQL/lock timeouts roll back that maintenance transaction. Failures are logged without payload/operator text or secrets and do not discard accepted batches.

Alarm facts use the existing verified latest-state pointer. Event facts use native last-update markers, never arrival order; equal or uncertain markers leave latest fields unavailable. Event registered-machine identity is kept separately from historical mapping annotations and is checked against the source's customer/site/project and accepted upload scope. It is never inferred from event messages or `ev_source`. Conflicting source times remain NULL/uncertain. Original timestamps and separate milliseconds remain in `platform.alarm_event_revisions`.

Facts and summaries are eventually consistent with processed history. The manager's Analysis shows the last stored update, queued record/summary counts and retrying updates, scoped to its customer/source filter. Freshness is source-wide rather than limited to the first-saved time window. Reads never trigger model calls, enable AI or mutate processing status. Summary tables expose `refreshed_at`; reports must not present them as real-time while updates are pending. Original batch receipts remain authoritative for durable acceptance.

All nine new physical tables have forced customer RLS. A private NOLOGIN/NOBYPASSRLS `scada_warehouse_owner` has explicit maintenance policies, fixed search paths and access only to required source data. Only the worker capability can execute the bounded refresh entry point; readers/ingest cannot invoke maintenance or change facts/summaries. Runtime connection validation rejects membership in the warehouse owner and ownership of platform/warehouse/reporting tables. Derived readers gain no original payload, operator-field or credential access. The trusted local manager can still review all customers; a public customer API remains future work.

Apply Alembic through `0015_source_scoped_processing` on stopped Central services after an encrypted, restore-verified backup. Migration 0013 validates and removes old per-source copies and synchronizers atomically; originals and receipts remain intact. See [upgrade safeguards](source-table-layout.md). The first migration backfills stored facts/summaries atomically; failure rolls back without replacing original storage. A pre-existing `reporting` schema or conflicting warehouse object blocks installation for inspection. New sources then use shared tables. Downgrade restores the earlier alarm views and legacy new-source behavior without deleting original history; recreating legacy tables for sources added in shared mode can take additional time/storage. Downgrading 0013 recreates copies with new OIDs and does not restore custom grants; exact recovery requires the backup. Do not downgrade to bypass an operational fault.

Indexes cover source/time reporting and source-scoped refresh. Facts are not yet time-partitioned: volume, retention and peak backfill must be measured before introducing a partition key that preserves global occurrence/replay identity. Dimension views show current registration labels rather than historical label versions. Event facts are available through SQL; an event-analysis GUI, automatic retention, historical dimensions, replicas and production capacity certification are not part of this update.

## Credential boundaries

Source and Generation UUIDs do not authenticate requests. Upload keys are generated with `secrets.token_urlsafe(32)`, transported as HTTPS bearer credentials, hashed in PostgreSQL and checked before accepting a batch. Unknown generations and sources outside the credential scope are rejected.

Windows credentials use existing account-protected DPAPI storage. Linux credentials use AES-GCM with an owned private key and private files. Collector exports use AES-GCM with a password-derived scrypt key. Preserve vaults and keys together outside Git. Encryption does not prevent an authorized local account or administrator from unlocking its own credentials.

Source deletion revokes all its upload credentials atomically. Credential replacement currently adds a new valid credential and does not revoke earlier credentials automatically. Retired, locally authorized generations remain valid for immutable outage backlog and committed replay; retirement is not credential revocation. Do not block durable backlog delivery to treat IDs as secrets.

Keys are never displayed or copied. Export passwords remain masked and travel through stdin-only management containers with logging disabled. Native/Docker failure output stays private. Hiding a URL simplifies the screen; it does not authenticate requests. [OWASP REST guidance](https://cheatsheetseries.owasp.org/cheatsheets/REST_Security_Cheat_Sheet.html) covers the accompanying HTTPS and access controls.

## Startup and updates

The Windows launcher probes the selected WSL distribution's local Linux Docker socket and ignores inherited Docker/Compose routing. It starts Docker Desktop once without a console and waits for approximately two minutes. Missing installation, first-run prompts, disabled WSL integration and timeout produce safe errors; the launcher does not install software or change integration automatically.

The GUI checks/starts its project outside the UI thread. Existing startup cleanup and gateway-only mount recovery remain. Port conflicts remain errors; startup never stops the Windows server or changes its endpoint. Stop server still stops only the selected project; refresh never restarts a server stopped in the current session. Reopening the app starts it again.

Apply migration `0010_alarm_warehouse` only to Central storage. Stop the configured project before replacing deployed files. Preserve `.env`, vaults/keys, source identities, Collector queues, native table OIDs and all database/certificate/AI volumes. Reopen the manager after deploying code. Downgrading the new views does not delete collected records.

If a schema named `warehouse` already exists, inspect the collision before applying the migration; never overwrite or drop an existing source schema to make room.

## Verification

Focused checks passed on 2026-11-03: 42 database, ingestion, credential, migration-upgrade/downgrade and warehouse-isolation checks on each disposable PostgreSQL 17 and 18 cluster; 63 Linux/Qt/adapter/settings/package checks under the normal WSL user; 25 Windows checks with six Linux-only skips covered by the WSL run. Windows has no optional Qt dependency; its Qt checks ran in WSL. Existing Starlette/httpx test-client deprecation warnings remain. These checks use synthetic data and do not establish model accuracy, production capacity, remote-PC commissioning or clean-machine installation.

The live `linker-scada-wsl` project was upgraded after the checks. A private encrypted Central database backup and original application files were retained under its Linux `secrets/before-central-analysis-*` directory. Migration `0010_alarm_warehouse`, the new reporting RPC and API/database/worker readiness were verified. All 10 pre-existing original record versions, registration/credential/generation/mapping fingerprints, native table OIDs, saved settings/vaults/AI choice and all five named volumes were preserved. A final helper check initially compared Docker's unordered volume-name output as an ordered list; comparing the name sets resolved that verification error without another restart.

The updated desktop shortcut opened the actual manager without a new console window and its verification window closed normally. Existing managers should be reopened to load the new controls. Cold Docker Desktop startup/timeout paths were unit-tested; the operational Desktop engine was kept running. Published installers were not rebuilt or uploaded.

## Analysis display update - 7 November 2026

The sidebar and page title now read **Analysis**. **Daily alarm / event occurrences** includes the original description, effective equipment name, source, type and count. It counts occurrence facts rather than saved versions and applies the same customer/source/first-saved filters to alarms and events. Alarm summary totals and recurring groups remain alarm-only. All existing uncertainty, equipment-editing and saved AI controls remain available. This display/query change requires no schema migration, Collector update or timezone reinterpretation.

Verification: 31 focused warehouse/equipment checks passed on each disposable PostgreSQL 17 and 18 cluster; all 33 Qt checks passed. Windows manager checks: 24 passed, two skipped because the desktop was unavailable for those checks. The live WSL/Docker UI matched all seven daily columns to saved report data: 72 groups covering 26 alarm occurrences and 175 events, including 41 explicitly uncertain-date groups. Equipment was available for 13 groups; missing identity remains uncertain rather than inferred. The persistent footer remained visible at minimum window size and the saved AI configuration was unchanged.

The existing local project was updated after an encrypted full backup and isolated restore verification. Pre-start fingerprints and database identity matched; 12 committed batches/201 saved versions, existing overrides, original revisions/receipts, named volumes, settings and protected credentials were retained. Later legitimate uploads may increase counts. The server is ready; existing pgAdmin access, source/project filtering, fixed-customer isolation and CA-verified HTTPS passed. Protected backup/prior-code evidence remains outside Git at `~/central-server/secrets/daily-analysis-20261107`. No published installer was rebuilt, and no remote Collector, VMware, source timezone or SCADA database was changed.
