# Collector acceptance review - 28 October 2026

This records the review before the remaining features were implemented. See the [version 0.2 implementation and acceptance evidence](collector-server-implementation-2026-10-28.md) for the current result.

The protected local setup and read-only preview increment passes the checks below. The complete collector and Phase 1 upload foundation do not yet meet their acceptance criteria. A successful connection and accurate preview do not establish automatic collection, delivery, or history completeness.

## Requirements reviewed

- `scada-pc-data-upload-service.md`, especially sections 3-5.
- `scada-alarm-platform-server.md`, especially sections 4 and 9.
- `plans/scada-alarm-reporting-platform-agile-plan.md`, including US-006 through US-015.
- `collector/README.md`, which defines the implemented local-preview increment.

## Evidence obtained in this review

The saved `Scada_Collector` login passed the collector's real connection, account-permission, and approved-schema checks against the configured local source. Both the role default and active session reported read-only mode. Verification used SELECT queries and did not modify source records, privileges, indexes, or settings.

Within one repeatable-read, read-only snapshot, 9 alarm preview rows and 1 event preview row were compared with the approved source fields read directly from PostgreSQL. All compared fields matched, including original timestamp serialization. Operator fields were omitted from preview output as configured. The check reported no field mismatches. These observations establish fidelity for those rows at that snapshot; they do not establish capture of changes between previews or correctness of the source's own logging.

The configured preview limit is 20 rows, with 4,096-byte text-field and 262,144-byte aggregate record-output limits. The source timezone is empty. The sampled alarm timestamps had 18 `timezone_unknown` and 27 `missing` results; event timestamps had 1 `timezone_unknown` and 1 `missing` result. Missing values were preserved. No UTC interpretation was assigned.

The user accepts GUI timezone configuration and UTC conversion capability for this increment. Known-timezone conversion and DST tests passed. Selecting the actual source timezone remains a commissioning setting, rather than a missing development feature or a prerequisite to starting incremental collection work. The earlier blank-timezone observation describes the configuration checked during this review.

The initial default test run produced **55 passed, 54 skipped** because PostgreSQL integration was not enabled. The full rerun produced **109 passed, zero skipped, in 14.54 seconds**, using the existing PostgreSQL 17 disposable cluster on loopback port 55440. Its data directory was checked against `.tools/collector-postgres-test` before testing. The suite used disposable fixture databases and roles, separately from the actual source on port 5432. The temporary test server was stopped afterward.

Machine-readable results from the full run are stored locally at `.tools/collector-acceptance-results.xml` (ignored by Git). The tests include native Tk workflows, Windows DPAPI and private ACLs, timestamp/DST handling, string/code/null/flag preservation, bounded previews, account rejection, attempted-write rejection on disposable PostgreSQL, lifecycle changes visible on repeated previews, and server foundation constraints/RLS. Passing foundation tests do not imply an implemented ingestion API or worker.

## Acceptance assessment

| Requirement | Result | Evidence or remaining work |
|---|---|---|
| Protected local setup, saved password, GUI and CLI | Pass for this increment | Native desktop, persistence, DPAPI, ACL, stale-settings, password handling, and redaction tests passed. Saved source credentials successfully unlocked. |
| Dedicated read-only source access | Pass for this increment | Actual login passed permission checks; read-only settings verified. Write rejection tested only on the disposable fixture. |
| Only approved alarm/event tables, bounded previews | Pass for this increment | Both schemas validated; two-table allowlist, pagination, field/output limits, and lock-timeout tests passed. |
| Preserve source fields and timestamp uncertainty | Pass for this increment | Live row comparisons matched; automated preservation and timestamp/DST tests passed. Source timezone remains unconfirmed. |
| Capture all supported lifecycle changes automatically | Not met | Preview re-reading can show changed rows, but marker scans, overlap, fixed bounds, late-commit handling, reconciliation, and reset/generation faults are not implemented. |
| Durable queue, receipts, checkpoints and crash recovery | Not met | No implemented collector queue/checkpoint or confirmed-delivery workflow. |
| Authenticated HTTPS ingestion, immutable retries and strict replies | Not met | Collector uploader and central ingestion endpoint remain unimplemented. |
| Server processing and recoverable source-ordered latest state | Not met | Database foundation exists; ingestion and leased worker processing remain pending. |
| Scheduling, service startup/recovery, operational status and logs | Not met | Desktop/CLI increment is not a Windows service and has no durable schedule or rotating operational log system. |
| GUI timezone configuration and UTC conversion capability | Accepted for this increment | GUI timezone configuration and known-timezone/DST tests passed; user accepts this capability. Actual source timezone selection remains a commissioning task. |
| Source change-marker commissioning | Incomplete | Confirm timestamp precision and demonstrate which lifecycle changes advance `last_update` and milliseconds. |
| Representative SCADA load, independence, outage and restore evidence | Not demonstrated | Small live previews and fixture tests do not establish peak-load safety, SCADA independence, recovery targets, or retention coverage. |
| Installer and clean-environment acceptance | Not met | Packaging, service-account commissioning, installation and recovery evidence remain outstanding. |

## Recommended next increment

1. Verify lifecycle/change-marker behavior and timestamp/millisecond conventions using an approved test fixture and representative source evidence. Do not modify the live SCADA database for test cases.
2. Implement US-006 and the remaining relevant US-007 work: fixed-bound marker scans with overlap and keyset paging; new-ID fallback/reconciliation; source generations/reset faults; and approved historical ranges. Test older-ID changes, equal markers, late commits, NULL/non-advancing markers, and resets.
3. Add the durable queue/checkpoint work before delivery, and complete the authenticated ingestion/receipt contract and worker. Then integrate strict HTTPS delivery and recovery tests.
4. Complete scheduling, service/installer work, measured load and security/recovery acceptance before a customer pilot. During commissioning, select the actual IANA source timezone through the existing GUI; preserve unknown time until it is confirmed.

The immediate next development objective is reliable change collection with verified change-marker semantics. GUI timezone configuration and UTC conversion capability are accepted for the current increment. Dashboard work follows the upload foundation under the documented phase boundary.
