# Collector and server 0.2 - implementation and acceptance evidence

Version 0.3 adds the requested Central Server Windows window and collector provisioning import/export. See the [management implementation and verification report](central-server-manager-implementation-2026-10-28.md) for the newer scope; this report preserves the earlier core-runtime evidence.

The local collection-to-server path is implemented and verified on this PC. The earlier preview-only limitations have been replaced by bounded collection, durable delivery and central processing. Customer deployment acceptance remains conditional on the explicit commissioning checks below.

## Implemented behavior

| Area | Version 0.2 behavior |
|---|---|
| Incremental collection | Persisted fixed bounds, marker overlap/keyset paging, new-ID scans and recent-ID reconciliation; bounded ID-range sweeps for unverified/NULL markers; approved historical scope. |
| Local durability | SQLite FULL synchronous transactions; immutable pending batches; separate staged and confirmed progress; FIFO matching receipts; queue/free-space limits; process locks; restart recovery. |
| Content and ordering | Preserve approved strings, codes, flags and nullable original/ms/timezone/UTC representations. Skip consecutive unchanged content; transmit returns to earlier content as ordering observations. Deduplicate central revisions/occurrences without regressing latest state. |
| Privacy and secrets | Upload-all, omit or keyed HMAC policies; current-user DPAPI database/upload/hash secrets; private file ACLs; redacted rotating logs. |
| Delivery | Fixed locally provisioned HTTPS URL, certificate and hostname validation, explicit optional CA file, no redirects or HTTP fallback, bounded uncompressed JSON receipt, immutable retries and capped backoff. |
| Central ingestion | Credential verifiers and credential-derived scope; strict version/type/field/hash/count/byte checks; atomic original-payload, receipt and job commit; identical replay receipts and content conflicts. |
| Tenant boundaries | Forced PostgreSQL RLS, transaction-local tenant context, separate restricted API/worker logins, and narrow fixed authentication/job-claim functions. Bounded connection pools and connection/statement/lock timeouts. |
| Processing | SKIP LOCKED job claiming, leases/retries/terminal faults, idempotent normalization, approved versioned exact-match mappings, durable quarantine, audited reprocessing and source-ordered latest state. |
| Scheduling/status | Local interval/daily/weekly schedule, durable occurrence claims/resumption, one missed-run catch-up, DST gap/fold policy, single-cycle exclusion, queue/delivery/next-run/error status. |
| Source reset/recovery | Filtered approved-table identity/max-ID checks, latched reset faults before delivery, journaled local generation authorization, retained old-generation pending batches and authorized same-generation history re-export. |
| Packaging/operations | Windows GUI/CLI/service/administration executables and Inno installer; Python wheel/source distribution; pinned application dependencies; Compose/Caddy files; local HTTPS server helper; encrypted backup/restore scripts and operating guide. |

Customer read APIs, the Web Portal, analytics, Grafana, OIDC and notifications remain deferred by the approved server phases. They were not part of this remaining Phase 1 collector/server implementation.

## Verification performed

### Automated regression

The release suite contains **144 passing tests with zero skips** in the Windows desktop and disposable PostgreSQL environment. The fixture database is on loopback port 55440, and its data-directory identity is checked before testing. It is separate from both the real SCADA source and the local central database. The fixture server is stopped after each run.

Tests cover native Tk workflows and protected credentials; actual PostgreSQL read-only sessions/schema checks; paging/ties; lower-ID late commits recovered by overlap outside the recent-ID window; NULL/non-advancing markers; older-row lifecycle changes; raw type/null/flag preservation; timestamp/DST behavior; privacy omission/HMAC; quotas and checkpoint rollback; hard process exit during staging; immutable lost-reply retry and restart; real TLS unknown-CA rejection and explicit-CA acceptance; concurrent replay; cross-customer API/RLS boundaries; worker retry/lease recovery; out-of-order and equal-marker conflicts; mapping approval/quarantine recovery; interrupted scheduling; generation journaling; re-export; and a fresh Alembic upgrade through runtime role bootstrap.

The machine-readable result is `.tools/collector-acceptance-results.xml`. The test harness emits one Starlette/httpx deprecation warning; it does not affect the passing application/TLS checks. Python 3.12 and Linux execution have not been demonstrated in this environment.

### Actual source to local server

The user explicitly selected this PC for server testing and authorized reading its current real alarm/event history. A separate SCRAM-authenticated central PostgreSQL cluster runs on 127.0.0.1:55441, and the HTTPS API is bound only to 127.0.0.1:8443. Its private CA is configured explicitly in the collector; no global trust-store change was made.

The saved dedicated `Scada_Collector` source login passed account/schema checks. The test copied **9 alarm rows and 1 event row**, in two initial committed batches. Comparing stored original fields to the source found **zero field mismatches**. A second scan staged zero repeated observations and left zero pending batches. Authorized recovery re-export subsequently retained **10 central source revisions**, with zero mismatches and no duplicate occurrence/revision rows.

The tested rows have no usable change markers, so the local configuration uses bounded ID-range reconciliation. It preserves uncertain ordering. Actual source timezone configuration remains as the user commissioned it; the GUI timezone/UTC conversion capability was accepted by the user, and known-zone/DST conversions pass automated checks. No source timezone is guessed.

The real records are retained in quarantine because actual machine mappings have not been approved. Receipt commitment means the server owns the raw evidence durably; it does not mean mappings or customer reporting are complete. The approved mapping/reprocessing path is separately verified on the disposable fixture.

### Scheduling and listener observation

A temporary scheduler completed the local scheduled collection check without pending batches or errors and then stopped. Windows IPv4/IPv6 TCP-table observations found **no listening sockets owned by the collector process** before or after the check. Code guards also reject listener/process-execution paths in collector runtime. The central API/database listeners are separate, deliberately provisioned local server components.

The scheduler evidence is `.tools/scheduler-check-results.json`. GUI scheduling is currently stopped following testing; use the new Collection & upload tab to start it. Native Windows service installation has not been performed.

### Synthetic source workload

The explicit disposable benchmark generated **150,000 alarm rows and 150,000 event rows**, with primary keys only and no `last_update` index. Environment: Windows 10 build 19045, Python 3.13.17, PostgreSQL 17.6, eight logical CPUs.

| Operation | Measured result |
|---|---|
| Read both fixed bounds | 344.987 ms |
| Alarm ID page, 50 records | 189.939 ms |
| Alarm marker page, 50 records | 144.534 ms |
| Event ID page, 50 records | 52.977 ms |
| Event marker page, 50 records | 254.448 ms |
| 10,000-row alarm burst, bounds plus 50-record page | 426.361 ms |
| Unindexed ordered query with 1 ms statement timeout | Cancelled as required |

EXPLAIN ANALYZE/BUFFERS JSON, returned rows and environment details are retained in `.tools/source-benchmark-results.json`. Marker sorting scans more than the returned LIMIT; the ID fallback avoids that sort but a large reconciliation sweep spans multiple scheduled runs. Detection latency depends on the sweep size and configured page/run budget. These synthetic measurements do not establish acceptable SCADA CPU, memory, control-cycle or peak-load behavior on customer equipment.

### Encrypted restore and re-export

A real local central backup was encrypted without writing an unencrypted dump, then restored into a newly named temporary recovery database on the separate local central cluster. All ten original revision payloads and the two receipts present at that snapshot matched by content digest. Measured backup time was **415.129 ms**, and restore time **540.811 ms**. The temporary recovery database was removed after verification; the original source and central databases were retained.

Evidence is `.tools/local-restore-results.json`. The local backup key is DPAPI-protected for this Windows account. This is a local drill; the age-encrypted off-server scripts, portable recovery-material custody and clean-host restoration remain deployment checks. Re-export can recover currently retained source content but cannot reconstruct overwritten historical revisions or hard-deleted rows.

### Build and deployment artifacts

`dist/collector` contains the GUI, CLI, native SCM service wrapper and service administration executables. `dist/installer/Linker-SCADA-Collector-Setup.exe` is the Windows installer. `dist` also contains version 0.2 wheel/source archives. Build logs and checksum/contents evidence are retained under `.tools`. Packages are unsigned development artifacts.

The packaged CLI reported version 0.2.0, opened the saved private setup, reported status and completed a bounded read-only collection with zero new records, pending batches or errors. Administration usage loaded without installing a service. The native collection tab was rendered and visually inspected. The seven-artifact audit found no bundled private configuration/state/DPAPI/log files and no literal upload token. SHA-256 sidecars accompany the artifacts; `.tools/package-audit.json` records archive and source-code fingerprints.

Compose configuration validation passed with the supplied environment template. The Docker Linux engine is not running on this PC, so Linux image builds, Caddy runtime validation and clean Linux deployment are not claimed. The native local HTTPS path was tested instead.

## Acceptance decision and remaining gates

The functional local collector/server path passes the checks described above. This is **local development acceptance**, not customer deployment approval.

| Gate | Current status |
|---|---|
| Actual machine mappings, code meanings and customer privacy/scope approval | Pending; real records remain quarantined. |
| Source timezone/precision, marker, reset and retention commissioning | Capability implemented; source-specific evidence/approval still required. |
| Representative SCADA independence, control/logging and workload demonstration | Not performed; source reads and fixture benchmarks do not substitute for it. |
| Clean Windows install under dedicated service identity; reboot/recovery/uninstall | Service/installer built; clean-machine execution and DPAPI identity commissioning pending. |
| Linux containers/Caddy/approved public hostname | Files prepared and Compose parsed; runtime deployment pending. |
| Off-server encrypted backup, clean-host restore, agreed RPO/RTO | Local encrypted restore passed; external custody/restore and recovery targets pending. |
| Installer signing, approved supported versions, operations ownership and pilot decision | Pending. |

Backlog traceability: US-003 through US-012 now have implementation and local fixture evidence for the upload path; US-013 has synthetic benchmark evidence; US-014 has build/deployment/recovery artifacts. US-015 and customer-specific commissioning portions of those stories remain open. `collector/README.md` documents the supported scan horizons, mutation/retention limits and conservative reset detection; no universal history-completeness or zero-loss claim is made.

See [operations](operations.md) for exact commands and [open questions](OPEN_QUESTIONS.md) for customer decisions.
