# AI-Assisted Agile Development Plan

**Project:** SCADA Alarm Reporting Platform for Linker Enterprise Inc.
**Application Type:** Windows service with local desktop GUI and CLI; cloud ingestion API and worker
**Language:** Python 3.12; PostgreSQL SQL
**GUI / Framework:** Tkinter/ttk collector desktop GUI; FastAPI, SQLAlchemy 2, Alembic; psycopg, httpx, pywin32; pytest
**Development:** VS Code (proposed) + Codex
**Packaging / Deployment:** Windows installer using PyInstaller + Inno Setup (proposed); Docker Compose and Caddy on a supported Linux host; SQLite collector state
**Final Deliverable:** Windows collector service/installer and local CLI; containerized Phase 1 server, migrations, deployment configuration, tests, and operating guides
**Sprint Duration:** 5 Working Days

---

## Phase 1 — Project Planning

**Objective:** Build a reporting foundation that safely uploads SCADA alarm/event history and lifecycle revisions to Linker Enterprise Inc.'s cloud platform. Preserve source evidence, enforce customer isolation, and recover from retries and outages without controlling SCADA or silently losing data.

**Software packages and installation locations:**

| Software package | Includes | Where installed |
|---|---|---|
| **1. SCADA Collector** | Windows collector service, protected local desktop setup/status GUI and CLI, and Windows installer. | Each approved **SCADA PC**. |
| **2. Central Server** | FastAPI backend, background worker, database migrations, and deployment configuration for central PostgreSQL and Caddy. | **Central Linux server**: a VPS or dedicated company server. |
| **3. Web Portal** | React customer dashboards, alarm/event history, and authorized administration screens. | Hosted by Caddy on the **central server**; users access it through a browser. |

The backend and worker share one codebase and application image but run as separate processes/containers. PostgreSQL and Caddy are existing products configured as part of the Central Server package.

**Development order:** Build the SCADA Collector and Central Server upload flow first, including durable storage, safe retries, and batch processing. Add the Web Portal and authenticated read APIs in server-design Phase 2. Add internal Grafana views, analytics, and Postmark email integration in server-design Phase 3. These package groupings preserve the delivery boundaries in `docs/scada-alarm-platform-server.md`, Section 9; the backlog and sprints below cover the Phase 1 foundation.

**Requirements:**
- The original planning invocation produced this plan only. Version 0.2 now implements bounded collection, durable local state, HTTPS delivery, authenticated ingestion, leased processing, local scheduling, recovery commands and packaging/deployment files. The user-authorized local HTTPS test copied actual source history and verified fidelity/deduplication. See `docs/collector-server-implementation-2026-10-28.md` for current evidence. Customer installation, clean Windows service operation, clean Linux deployment and representative equipment/recovery acceptance remain commissioning gates.
- Read `docs/scada-pc-data-upload-service.md` and `docs/scada-alarm-platform-server.md` fully before implementation; both were read in preparing this plan. Treat these documents as authoritative over conflicting prompt details. Record conflicts and decisions in `docs/OPEN_QUESTIONS.md` during Sprint 1.
- Resolve the known scope conflict in favor of server design Section 9: Phase 1 covers registry, mapping, ingestion, replay protection, and raw-history recovery; authenticated external read APIs belong to Phase 2. Prepare the field allowlist and isolation contracts now, but defer live read endpoints, including `/v1/machines`, `/v1/alarms`, `/v1/events`, and analytics routes. Portal, Grafana, notifications, OIDC, and analytics receive empty module stubs and TODOs only.
- Establish `/docs`, `/server` with app/worker/migrations/tests, `/collector` with service/profiles/tests, `/deploy`, `/tests/e2e`, `/tests/fixtures`, and `README.md`. Use Python 3.12, FastAPI, PostgreSQL, SQLAlchemy 2, Alembic, a separate Python worker, Docker Compose, Caddy, psycopg, httpx, SQLite, and pytest. Do not introduce MQTT, Redis, Kubernetes, or a separate analytics database.
- Preserve strict upload-only behavior: every collector connection originates locally; no listener, job/config polling, remote shell, automatic updater, or cloud-supplied extraction instructions. Fixed locally provisioned HTTPS destination; certificate and hostname validation; no redirects or HTTP fallback. Local maintenance alone changes credentials, destination, schedule, or source generation.
- Provide a dedicated read-only Windows service account, DPAPI-protected credentials, restrictive permissions, redacted rotating logs, and a minimal authorized local configuration/status CLI. The PostgreSQL role receives only required connection/schema access and SELECT on the two approved tables; set `default_transaction_read_only = on` for collector sessions. The collector never creates indexes, writes source data, or acknowledges/clears alarms.
- Create `tests/fixtures/scada_schema.sql` with the exact supplied `alarmhistory` and `eventhistory` column definitions, nullable timestamps, separate integer milliseconds, raw integer codes, varchar values, and respective ALWAYS/BY DEFAULT identity modes. All collector integration tests use this fixture on real PostgreSQL. Preserve all specified fields; never coerce varchar values into numbers.
- Implement the built-in `ecostruxure_machine_scada_expert_v1` profile with configurable approved schema/table identifiers, defaulting to `public.alarmhistory` and `public.eventhistory`. Reject additional table mappings in Phase 1. Never query or upload `Heartbeat` or unidentified tables. Quote validated identifiers and parameterize values.
- Detect updates using a sortable combined `last_update`/`last_update_ms` marker, configurable overlap window (10 minutes proposed), and deterministic keyset pagination on `(last_update, last_update_ms, id)`. Persist a fixed scan bound per cycle; preserve same-millisecond ties and re-read overlap after confirmation. Supplement each cycle with new-ID scanning and bounded recent-ID reconciliation. Handle NULL/non-advancing markers explicitly with ID fallback, best available source timestamp, content hashing, and `ordering_uncertain`.
- Define revision identity as `(source_generation, table, id, revision_key)`, where the key includes the original change marker and SHA-256 row content hash. Specify canonical serialization, NULL representation, millisecond validation, and separate row/batch hashing contracts. Deduplicate identical content for the same occurrence even across marker changes; retain changed content under an unchanged marker as an uncertain revision. Source reset detection must stop uploads until an authorized local generation change is completed.
- Preserve every original naive timestamp and millisecond value; combine precisely and convert to UTC only with a configured IANA source timezone and an unambiguous interpretation. Flag ambiguous and nonexistent DST times without choosing an offset; preserve NULL normalization/acknowledgement times. Missing/invalid milliseconds and uncertain revision order must have documented, tested outcomes rather than guessed precision or state.
- Upload soft-delete flags as ordinary state; never hard-delete on receipt. Exclude flagged records and unknown mappings from eventual customer summaries by default. Preserve operator fields in original JSONB under the default upload-all policy; support locally selected omission or keyed hashing (proposed) and exclude user fields/raw payloads from the default external response contract. Retain raw codes in configurable empty lookup tables; derive severity only from approved mappings.
- Model customers, sites, projects, machines with UUID identity and site-scoped tags, collectors/sources/generations, approved mapping versions, upload batches, revisions, latest alarm state, jobs, audit log, and code lookups. Normalized fields cover source identity/revision, original/ms/UTC/ambiguity representations for lifecycle/event/update times, flags, mapping inputs, messages, string values, integer codes, and user fields. Record mapping version; quarantine unknown mappings with a visible recovery path.
- Authenticate ingestion using high-entropy credentials with stored hash verifiers; derive all customer/site/project/source/machine authority from credentials. Validate submitted scope, schema version, types, counts, byte limits, and hash. Apply customer isolation at API and PostgreSQL RLS layers using distinct restricted roles and transaction-scoped context; reset pooled context reliably and audit sensitive changes.
- Atomically commit accepted batch, original payload, durable receipt, and processing job before returning exactly `{batch_id, payload_hash, status:"committed"}`. Identical retries return prior acceptance; source + batch ID reuse with different content conflicts. Collector retries reuse immutable ID/hash/content, strictly validate bounded JSON responses, and atomically secure checkpoints before deleting confirmed temporary batches.
- Claim DB jobs with `SELECT ... FOR UPDATE SKIP LOCKED`, leases, bounded retries, and visible terminal failures. Processing must survive repeated execution and lease expiry, preserve uncertain observations, and update latest state only when source ordering establishes precedence. Receipt order never determines current state. Treat each alarm ID within a generation as one occurrence; lifecycle revisions do not inflate occurrence counts. Do not implement analytics metrics in Phase 1.
- Use a durable pending queue with disk quota/free-space checks, bounded reads and uploads, statement timeouts, batch limits, bounded retry backoff, and non-aggressive handling of auth/TLS/schema faults. Pending batches survive outage/restart; storage faults stop staging without removing unconfirmed work. Local scheduling supports configured timezone/DST rules, one catch-up run, durable occurrence deduplication, and one cycle at a time. Initial history uses an approved local date range and the same resource limits.
- Status reports last successful upload, latest confirmed source timestamp, next run, pending count, queue usage, versions, and latest error. Benchmark normal/peak/backlog reads on a large generated fixture with no `last_update` index; record dataset, plans, latency, rows examined/returned, timeout behavior, and resource observations. Provide bounded fallback ID-range mode, state its completeness limits, and fault on unresolved gaps. A LIMIT does not bound database scan cost; customer-specific acceptable limits require measurement.
- During Sprint 1, log all required open questions: actual schema; `Heartbeat` contents and separately approved future use; two unidentified tables; whether every change advances `last_update`, whether NULL occurs, and whether it is indexed; hard-delete behavior; source timezone; Windows/PostgreSQL/SCADA versions; daily/peak volume; retention; upload interval; initial history range. Also log proposed defaults, ID reuse/reset visibility, permitted reconciliation horizon, DST schedule policy, backup recovery gap, hosting/region, credential lifecycle, data-scope agreement, mapping/code approvals, and numeric resource/recovery limits. No Heartbeat inspection is authorized.
- Chosen safe implementation direction where unspecified: use durable SQLite transactions for queue/checkpoint/schedule state, stop on unresolved reset evidence, and preserve incomparable revisions without guessing latest state. A bounded scan cannot guarantee detection of arbitrary old manually reused IDs or content-only changes outside its reconciliation range; document that limitation and require commissioning evidence. Reset signals based on table size or identity metadata must not introduce reads of unapproved source tables; document the approved metadata strategy before implementation.
- Work in small reviewed commits with clear messages and relevant passing checks before each. Do not claim production readiness. A five-day sprint is a planning timebox, not a capacity guarantee; carry incomplete acceptance work forward rather than reducing safety requirements. Customer deployment remains gated by representative Windows/SCADA, load, security, installation, and recovery evidence.

---

## Phase 2 — Product Backlog

| ID | Feature | Priority |
|----|---------|----------|
| US-001 | Establish repository structure, documented design precedence, OPEN_QUESTIONS, Phase 1 boundary, exact source fixtures, and acceptance traceability. | High |
| US-002 | Implement PostgreSQL/Alembic registry, generations, mappings, revision/latest-state storage, receipts/jobs/audit/code lookup tables, constraints, and indexes. | High |
| US-003 | Implement credential provisioning/verifiers, credential-derived scope, restricted roles, tenant RLS, pooled-context isolation, and external field allowlist contract. | High |
| US-004 | Deliver strict ingestion validation, canonical hashing, atomic durable acceptance, fixed receipt, replay deduplication, and content-conflict detection. | High |
| US-005 | Deliver lease-based DB worker, idempotent processing, source-ordered latest state, uncertain revision preservation, occurrence identity, quarantine, and reprocessing. | High |
| US-006 | Implement bounded two-table extraction profile with marker overlap/keyset paging, ID fallback/reconciliation, reset faults, and locally authorized generations. | High |
| US-007 | Implement precise timestamp/DST handling, NULL preservation, raw strings/codes, soft-delete state, personal-field policies, and versioned approved machine mappings. | High |
| US-008 | Implement durable pending batches/checkpoints, crash-safe confirmations, restart recovery, queue quotas/free-space faults, and bounded rotating logs. | High |
| US-009 | Implement strict HTTPS uploader, response limits/validation, immutable retries, backoff, TLS/redirect rejection, and fault classification. | High |
| US-010 | Implement protected local configuration, DPAPI/permissions, service lifecycle, CLI/status, durable local scheduling/catch-up, and approved initial history export. | High |
| US-011 | Prove real-schema lifecycle, late commits, ties, older-ID updates, uncertain markers, reset behavior, timestamp policies, and table/read-only boundaries on PostgreSQL. | High |
| US-012 | Prove end-to-end replay/crash/outage recovery, worker lease recovery, tenant isolation, hostile response rejection, storage limits, and no listening sockets. | High |
| US-013 | Benchmark large unindexed source datasets, bounded fallback behavior, burst/backlog capacity, and SCADA independence; record measured limitations. | High |
| US-014 | Package Windows installer and Linux Compose/Caddy deployment; provide migration, commissioning, restore/rollback, credential renewal, local re-export, and run/test guides; add deferred module stubs. | High |
| US-015 | Complete clean-environment security/recovery/acceptance review, evidence report, unresolved-question register, and limited-pilot release decision. | High |

---

## Phase 3 — Sprint Planning

| Sprint | Duration | Goal |
|--------|----------|------|
| Sprint 1 | 5 Working Days | Complete US-001 and US-002: source-document conflict register, repository scaffold, exact shared SQL fixtures, contract decisions, registry/data migrations, constraints, and database checks. |
| Sprint 2 | 5 Working Days | Complete US-003, US-004, and US-005: credential/RLS boundaries, atomic ingestion and replay receipts, safely claimed jobs, idempotent source-ordered processing, and quarantine recovery. |
| Sprint 3 | 5 Working Days | Complete US-006 and US-007: bounded profile extraction, overlap/tie handling, fallback/reconciliation and reset faults, timestamp/privacy transformations, approved mappings, and focused PostgreSQL tests. |
| Sprint 4 | 5 Working Days | Complete US-008, US-009, and US-010: durable queue/checkpoints, strict HTTPS and retries, protected local setup, single-cycle service/CLI, scheduling, status, and history upload. |
| Sprint 5 | 5 Working Days | Complete US-011, US-012, and US-013: integrated PostgreSQL/E2E fault tests, security boundaries, large-dataset benchmarks and fallback limits, and representative SCADA independence evidence where customer equipment is available. |
| Sprint 6 | 5 Working Days | Complete US-014 and US-015: final regression/security/recovery testing, Windows packaging, Compose/Caddy deployment, clean-environment verification, operating documentation, explicit untested items, and final limited-pilot approval. |

---

## Phase 4 — AI Development & Testing

**Daily Workflow:**
1. Review approved Sprint tasks.
2. Assign tasks to Codex.
3. AI proposes an implementation plan.
4. Product Owner approves the plan.
5. AI develops the feature.
6. AI runs automated tests.
7. IT Engineer verifies functionality.
8. Update the Sprint Backlog.
9. Commit reviewed changes using Git.

**Sprint 6 — Testing and Packaging/Release Tasks:**
1. Run pytest unit, real-PostgreSQL integration, and E2E suites with the shared exact schema fixture. Prove an active alarm updated to normalized then acknowledged produces three revisions, one occurrence, and correct latest state; older batches never regress it. Recheck older-ID updates, late commits, equal-marker ties, NULL/non-advancing markers, identical-content deduplication, and uncertain changed content.
2. Re-run fault injection for lost replies, replayed batches, conflicting batch content, crashes before/after confirmation and checkpoint commit, outage/restart, concurrent workers, and lease expiry after mid-job failure. Verify no skipped records or duplicate occurrences and that every accepted batch remains recoverable from retained payloads.
3. Verify known UTC conversions and millisecond composition, DST ambiguity/nonexistence flags, NULL norm/ack timestamps, soft-delete preservation, raw varchar/code handling, personal-field omit/hash/default policies, and external allowlist exclusion. Verify quarantine and source reset faults, including local generation authorization and safe handling of manually inserted/reused IDs within supported detection bounds.
4. Run security checks for cross-site uploads and cross-customer database access, object scope and pooled RLS context, stored verifiers, DPAPI/permissions, secret redaction, and read-only source sessions with failed write attempts. Assert issued source SQL never accesses Heartbeat/unidentified tables. Run static architecture checks and runtime socket observation for no collector listener/polling path; reject wrong ID/hash, extra fields, oversized/wrong-content-type replies, redirects, invalid TLS, and HTTP downgrade.
5. Verify quota/minimum-free-space faults preserve pending work; validate rotation, durable scheduling across reboot/DST/missed runs, one catch-up occurrence, and single-cycle exclusion. Review measured large unindexed fixture benchmarks, batch/timeout limits, fallback coverage, peak/backlog behavior, and representative proof that stopping the collector leaves SCADA control/logging unaffected. Record unavailable customer-environment evidence as untested.
6. Build the Windows service/installer and local CLI without embedded customer secrets. On a clean supported Windows host verify administrator installation, dedicated-account operation, timezone data, DPAPI scope, local configuration/test upload, startup/recovery, status, authorized generation change, and uninstall with explicit state-retention choice. Record versions, build provenance, signing status, and packaging assumptions.
7. Build pinned application/worker images and validate Compose/Caddy configuration on a clean supported Linux host: private PostgreSQL/worker networks, HTTPS gateway, migrations under the correct role, least-privilege runtime identities, readiness, and durable volumes. Document configured hostname/certificate prerequisites, secret provisioning, `docker compose -f deploy/docker-compose.yml up --build`, and the exact `pytest` setup/commands and platform-specific exclusions after they exist.
8. Exercise encrypted off-server backup and restoration, worker recovery, migration-compatible rollback, and authorized local history re-export for confirmed uploads absent after restore. Record measured recovery time, recovery-point limitations, retention/deduplication assumptions, disk monitoring, and the single-host availability boundary; do not claim zero data loss.
9. Complete README, installation/commissioning/recovery guides, deferred portal/Grafana/notification/OIDC/analytics stubs, test/benchmark evidence, and `docs/OPEN_QUESTIONS.md`. IT Engineer and Product Owner review the concrete package and remaining risks for a limited pilot; unresolved required acceptance or missing customer-environment evidence blocks deployment approval. Publish only an explicitly authorized release with clear non-production status.

---

## Phase 5 — Sprint Review & Retrospective

- Demonstrate completed features.
- Review testing results.
- Approve completed work.
- Identify problems and improvements.
- Update the Product Backlog.
- Plan the next Sprint.
- Repeat Phases 3–5 until the application meets its release requirements.

---

## Final Deliverable

**Phase 1 Collector and Cloud Reporting Foundation** — SCADA Alarm Reporting Platform

**Requirements:**
- Windows collector service/installer with protected local configuration/status CLI, approved two-table profile, bounded history/change collection, durable scheduling/queue/checkpoints, and strictly validated outbound HTTPS delivery.
- Containerized ingestion API and separate DB-backed worker with PostgreSQL migrations, registry/generations, approved machine mappings, original JSONB revisions, normalized fields, non-regressing latest state, durable receipts, quarantine/reprocessing, customer authorization/RLS, and audit evidence.
- Docker Compose/Caddy deployment, exact shared SQL fixtures, pytest integration/E2E suites, measured source-query benchmark, and run/install/recovery/rollback documentation. Authenticated external read APIs follow server-design Phase 2; later portal, analytics, Grafana, notifications, and OIDC remain explicit stubs/TODOs.
- A release report stating what was built, actual Compose/pytest commands, tests and environments exercised, remaining untested behavior, open questions/conflicts, and approval status. Customer operating-system/database/SCADA versions, source behavior, acceptable resource limits, and real-equipment safety/performance remain To be confirmed until measured; no production-readiness claim.

**Final Release Status:** Subject to successful installation, deployment, security and acceptance testing.
