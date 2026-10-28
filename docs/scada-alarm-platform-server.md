# SCADA Alarm Platform Server

**Design description and component requirements**
Linker Enterprise Inc. | 26 October 2026 | Draft version 1.0

---

## 1 Purpose and design boundary

The central server receives alarm and event data from multiple SCADA projects, preserves its source and machine identity, and provides authorized access through dashboards and a read-only API. It calculates defined analytics and sends configured notifications to technical teams.

This document defines the proposed server components and their responsibilities for developers, commissioning engineers, and system administrators. It is a design baseline, not evidence of a built or tested service. Hosting selection and workload limits remain to be confirmed.

### Fixed scope requirements

- SCADA collectors initiate uploads on their own local schedules. The server issues no collection requests, commands, settings, or software updates to those PCs.
- Customer data is isolated by authorization at the API and database layers. External integrations receive read-only access to explicitly permitted data.
- The cloud reports historical and latest known conditions. It neither controls machinery nor changes SCADA alarm acknowledgement or clearing.

VPS and local-server deployments use the same application structure. Development on a dedicated local i7 and production on a VPS are proposed options; neither has been purchased or selected by this document.

---

## 2 Components and deployment

Use one application codebase with clear modules, plus a separate worker process. Deploy with Docker Compose on a supported Linux host. Keep database and worker services on private container networks; expose only the intended HTTPS application routes.

| Component | Proposed implementation | Responsibility |
|---|---|---|
| HTTPS gateway | Caddy | TLS, routing, request size limits, and connection timeouts. |
| Backend API | Python and FastAPI | Ingestion, validation, identity mapping, customer authorization, read endpoints, and administration. |
| Database | PostgreSQL | Alarm data, registry, configuration, audit records, and durable work queue. |
| Worker and scheduler | Python service | Process committed uploads, calculate summaries, evaluate rules, and deliver queued notifications. |
| Customer portal | React frontend | Machine navigation, historical alarms, summaries, and permitted downloads through the backend API. |
| Internal analytics | Grafana | Engineering dashboards using an approved read-only database connection. |
| Identity integration | Established OIDC provider | User login and MFA; provider choice remains open. Application stores role and customer memberships. |
| Notification delivery | Transactional email provider | Email delivery, bounce reporting, and provider message references. |
| Operational tooling | Backup jobs and external monitor | Database recovery, service/disk monitoring, and independent outage detection. |

### Hosting choices

Hostinger Premium shared web hosting does not fit the proposed PostgreSQL and Python stack. Use a VPS or a dedicated local server. Hostinger KVM 1 is a pilot candidate; KVM 2 offers more headroom for a database, API, worker, and Grafana. Published plan specifications are referenced in Section 9; actual capacity requires load testing [1].

A local i7 requires adequate RAM and SSD storage, a UPS for the PC and network equipment, reliable internet, secure public routing, and network isolation. Keep it separate from operating SCADA PCs and daily-use workstations. A single local PC or single VPS remains a single point of failure.

MQTT, Redis, Kubernetes, and a separate analytics database are not required for the initial design. Add infrastructure only when measured volume or availability requirements justify it.

---

## 3 Identity and central data model

### Machine and source identity

Use a generated UUID as the permanent `machine_id` and a readable `machine_tag` such as `TOR-LINE01-OVEN01`. Scope tag uniqueness to a site and preserve tag changes in the audit history. The UUID remains unchanged when the tag is renamed.

Maintain customer, site, project, machine, and collector/source registries. One collector may serve multiple machines. Bind each collector credential to an approved source and machine set; never infer access rights from identifiers supplied in an upload.

Map source equipment fields or alarm tags to machines through an approved, versioned mapping. Record the mapping version used. Unknown mappings are quarantined for review and excluded from customer summaries until resolved. Source resets receive a new source generation to prevent reused record IDs colliding with earlier history.

### Logical database entities

| Entity group | Information retained |
|---|---|
| Registry and mappings | Customers, sites, projects, machines, readable tags, collector/source IDs, source generations, and mapping versions. |
| Upload batches | Source and batch ID, payload hash, schema version, receipt time, durable acceptance, and processing state. |
| Alarm and event revisions | Source record key/revision, machine ID, event type, original timestamps, normalized time, severity, description, lifecycle details, and original payload. |
| Latest known alarm state | Latest verified state per alarm occurrence, effective source time, last observation, and freshness/quality indicators. |
| Analytics summaries | Machine/alarm/time-bucket measures with calculation version and last recomputation time. |
| Notification workflow | Rules, recipients, durable jobs, deduplication keys, delivery attempts, outcomes, and cloud follow-up records. |
| Access and audit | Users, memberships, API credentials, permissions, configuration changes, and relevant access events. |

### Data preservation and indexing

Keep all agreed source fields in the original JSONB payload, alongside normalized columns used for filtering. Preserve both source event time and server receipt time. Retain source timezone assumptions and flag ambiguous timestamps. Do not invent missing acknowledgement or clearing times.

Use unique constraints for source generation, record identity and revision, plus source/batch identity. Index customer, machine, and event time for expected queries. Start with ordinary tables; introduce time partitioning and archival policies after volume is measured. Preserve revision history when source rows change.

---

## 4 Upload processing and worker reliability

### Ingestion sequence

1. Authenticate the collector over HTTPS. Derive the allowed customer/source from its credential and verify every submitted identity against that scope.
2. Validate payload size, record count, schema version, field types, timestamps, and batch hash. Reject unsupported or structurally invalid batches with a bounded error response.
3. Check the source and batch ID. An identical retry returns the prior acceptance result; the same batch ID with different content is a conflict.
4. Atomically store the complete accepted batch, source payload, acceptance receipt, and processing job in PostgreSQL. Unknown business mappings may enter a durable quarantine state with an operator-visible fault.
5. Return the fixed confirmation only after durable commit. The response contains the matching batch ID, payload hash, and committed status. It contains no local cursor, command, destination, or configuration.
6. Process committed batches asynchronously. Normalize records, resolve approved mappings, update latest known state, and queue summary/rule evaluation. Track processing completion separately from upload acceptance.

Upload acceptance means the server durably owns the data, including its obligation to recover processing failures. It does not mean all analytics or notifications have finished. A processing failure must remain visible and recoverable from the retained accepted payload.

### Ordering and duplicate handling

Source revisions or another validated ordering method determine whether an update is newer. Receipt order is not a reliable substitute. Replaying older batches must not regress current alarm state. Where the schema cannot establish order, preserve the observations and flag uncertainty rather than inventing a current state.

Separate an alarm definition from individual alarm occurrences and lifecycle events. Count occurrences rather than uploaded rows so repeated snapshots and acknowledgements do not inflate alarm frequency.

### Durable work execution

Use database jobs with transaction-safe claiming, leases, bounded retries, and visible failed states. A worker crash releases work for retry after its lease expires. Each processing step must tolerate repeat execution; concurrency must not duplicate event records or apply a rule twice for the same logical transition.

Create notification jobs in the same database transaction as the qualifying rule outcome. Use provider idempotency where available and reconcile ambiguous delivery results. Do not promise exactly-once email delivery when a provider cannot guarantee it.

### Backfills and corrections

Mark historical imports and late records explicitly. Recalculate affected summaries and retain calculation versions. Suppress routine per-event notifications for historical backfills by default; report a digest or processing exception instead. Failed batches and quarantine items require a documented review and reprocessing workflow.

---

## 5 Secure API and customer access

### Separate permission boundaries

| Actor | Allowed operation | Restriction |
|---|---|---|
| SCADA collector | POST approved upload batches | Only its assigned source and machines; no read/admin access. |
| External integration | GET approved data and summaries | Explicit customer/project scope and field allowlist; no mutations or arbitrary SQL. |
| Customer viewer | View assigned dashboard data | API enforces membership on every request and export. |
| Technical responder | Record cloud follow-up status | Separate permission; never acknowledges or clears alarms in SCADA. |
| Linker administrator | Manage registry, access, rules, and mappings | MFA, least privilege, and audited changes; cross-customer access explicitly assigned. |

### External read endpoints

Proposed versioned routes are:

- `GET /v1/machines`
- `GET /v1/alarms`
- `GET /v1/events`
- `GET /v1/analytics/alarm-summary`

Ingestion uses `POST /v1/ingest/batches`. Administrative and follow-up routes are separate and are never granted to read-only integration credentials.

Issue a separate high-entropy API credential per external integration. Store a secure verifier rather than the plaintext key; allow revocation, expiry, and rotation. Use HTTPS headers for credentials, never query strings. Browser users authenticate through the chosen identity provider; do not embed integration keys in frontend code.

Enforce server-side customer scope for object lookups, list queries, analytics, and exports. Validate filters, use parameterized SQL, and provide bounded date ranges, pagination, request rates, and query timeouts. Return an explicit response-field allowlist; original payloads may contain information not suitable for external access.

### Database enforcement

Keep PostgreSQL off the public internet. Use distinct roles for ingestion, processing, API reads, administration, and Grafana. Apply row-level security to customer data accessed by restricted roles and use transaction-scoped customer context that is reliably reset with connection pooling. Restricted roles must not own protected tables or have superuser/BYPASSRLS privileges.

PostgreSQL row-level security complements application authorization; it does not replace it. Test direct object-ID manipulation and pooled-connection reuse across customers. Database owners normally bypass row policies unless additional enforcement is configured [2].

### Web and credential controls

Restrict CORS to approved browser origins, apply secure session cookies and CSRF protection where relevant, and protect administration with MFA. Store secrets outside source code, redact them from logs, and audit permission changes and exports. OIDC login proves identity; application memberships determine data access.

---

## 6 Dashboard and analytics design

### Customer website

The customer website uses authorized backend endpoints for its overview, machine directory, alarm/event history, machine timeline, and reports. Show customer/site/machine, time range, timezone, latest source time, and last successful upload.

Show latest known state and flag stale or unknown data. The server's expected-upload interval is only a monitoring setting; it does not change the collector schedule.

### Initial metrics

| Measure | Required interpretation |
|---|---|
| Alarm frequency and top alarms | Count distinct occurrences by machine/alarm and period, not uploaded rows or revisions. |
| Alarm duration | Match activation and clearing for the same occurrence; show unresolved/uncertain intervals separately. |
| Acknowledgement delay | Use valid source activation and acknowledgement times. Keep cloud review timestamps separate. |
| Repeated or chattering alarms | Use explicit frequency/window rules, configurable by machine or alarm type. |
| Unresolved alarms | Show latest verified state together with its observation time and freshness. |
| Upload health | Expected versus received batches, last successful upload, processing lag, and quarantine/failure counts. |
| Period and machine comparisons | Use equivalent definitions and periods; distinguish missing data from zero alarms. |

### Calculation approach

Use tested SQL calculations and persist useful daily/hourly summaries. Recompute affected periods after late uploads. Define overlap, shift, and timezone handling. Alarm duration is not machine downtime; availability and OEE require production and operating-state data.

### Dashboard tool selection

Use Grafana for internal charts and service health. It supports PostgreSQL time-series alerting [3]; keep business notification rules in the worker to avoid duplicate logic.

Grafana Viewers can query accessible sources beyond dashboard queries [4]. Keep shared cross-customer sources internal. Customers use the custom portal/API; dashboard filters are not security boundaries.

Metabase is optional for later exploration; built-in row/column security requires Pro or Enterprise [5]. Any later AI explanations must be distinguished from measured results.

---

## 7 Notifications and technical follow up

### Rule configuration

Configure notification rules on the server by customer, site, machine, alarm type, severity, and recipient group. Each rule defines its condition, time window, freshness requirement, repeat interval, maintenance suppression, delivery channel, and any escalation target. Version and audit rule changes.

| Condition | Initial channel | Behavior |
|---|---|---|
| Daily or weekly review | Email digest | Group occurrences, top alarms, unresolved conditions, and data freshness with a dashboard link. |
| Repeated alarm threshold | Grouped email | Notify once per defined incident/window; apply cooldown and recovery rules. |
| Missed expected upload | Email | Identify the collector, last receipt, expected interval, and grace period. |
| Condition needing on-call action | Optional incident provider | Push/SMS/phone escalation after freshness and service-response requirements are agreed. |
| Processing or delivery failure | Administrator notification | Track failures and retry; use an independent monitor when this server is unavailable. |

### Email delivery

Use a transactional provider such as Postmark through HTTPS. Configure sender-domain authentication and verified sender addresses. Store provider message IDs and delivery/bounce outcomes; authenticated provider callbacks terminate on the cloud server only. Provider delivery does not prove the recipient has read or acted on a message [6].

Use a durable queue with retry backoff, deduplication, and bounded delivery attempts. Group bursts to prevent an alarm flood from becoming an email flood. Restrict notification content to what recipients are permitted to see, and require login for dashboard links.

### Cloud follow up workflow

Where enabled, technical staff may mark a cloud notification as reviewed, assigned, or resolved and add notes. Record actor and time. These actions update cloud workflow records only; they never modify the original alarm or issue commands to SCADA. External read-only credentials cannot perform these actions.

### Freshness and escalation

A nightly or weekly collector cannot support immediate alarm response. Notifications must show both event time and receipt/data age. Do not escalate stale historical alarms as current emergencies. Rules for currently unresolved conditions must require sufficiently recent evidence and handle missing data explicitly.

Email and dashboard history are the initial channels. Add an incident-management service only when responsibility, schedules, acknowledgement, and escalation expectations are defined. Local safety functions and operator alarms remain independent of this reporting platform.

---

## 8 Operations capacity and recovery

### Deployment and administration

Keep application code, container definitions, database migrations, and configuration templates under version control. Use separate test and production credentials and data. Pin supported component versions, apply reviewed security updates, and maintain a rollback plan compatible with database migrations.

The public application entry point is HTTPS. Restrict administrative access to approved management paths, and expose neither PostgreSQL nor container management interfaces publicly. A local deployment additionally requires segmented networking, appropriate internet routing, a UPS, and hardware recovery arrangements.

### Capacity and retention

Size from machine count, daily and peak event volume, average record size, revision frequency, retention, concurrent users, and acceptable processing delay. Measure peak upload bursts and catch-up imports. Indexes, retained payloads, database logs, temporary queries, and backups consume space beyond the raw alarm data.

Set request/batch limits, connection pools, worker concurrency, query timeouts, and disk thresholds. Stagger local upload schedules during commissioning if many sites otherwise submit together. The server must not remotely alter those schedules. Retention must preserve agreed audit/history needs and deduplication information for the permitted replay period.

### Backup and restoration

Use encrypted off-server backups of PostgreSQL, required configuration, and recovery material, with controlled access. Select full-backup and transaction-log recovery arrangements to meet the agreed recovery point objective. Test restoration onto a clean host and measure recovery time; a VPS snapshot alone is not a complete recovery plan.

If a backup is restored to a point before already confirmed uploads, source collectors may no longer retain those temporary batches. Document this recovery gap and an authorized local re-export process where source retention permits it. Do not claim zero data loss without an architecture that supports that commitment.

### Monitoring

- Monitor upload receipt and processing lag per source, failed/quarantined work, notification delivery, API errors, and authentication failures.
- Monitor CPU, RAM, disk free space, database growth, backup age, and certificate expiry. Rotate logs and cap temporary storage.
- Use monitoring outside the server to detect a complete VPS, office power, or internet outage. The failed server cannot reliably send its own outage email.

### Availability boundary

One host is a deliberate initial simplicity choice, not high availability. A host outage makes dashboards/API unavailable and delays notifications; SCADA continues logging locally subject to its own retention. Higher availability would require additional database, hosting, and failover design.

---

## 9 Delivery phases and acceptance

### Implementation sequence

- **Phase 1** establishes registry, machine mapping, PostgreSQL, ingestion, replay protection, and raw-history recovery.
- **Phase 2** adds authenticated read APIs and the customer portal.
- **Phase 3** adds tested metrics, internal Grafana views, and email delivery.
- **Phase 4** completes load/security testing, restoration drills, deployment documentation, and a limited customer pilot.

### Acceptance evidence

- Known source records and lifecycle changes retain the correct customer, source, machine, timestamps, and original fields.
- Retries, lost replies, out-of-order batches, and worker crashes create neither duplicate occurrences nor regressed state; accepted data remains recoverable.
- A customer or API credential cannot access another customer through IDs, filters, exports, summaries, or pooled database connections; read-only keys cannot mutate data.
- No server mechanism requests uploads or sends operational commands/configuration to SCADA collectors. Upload replies comply with the fixed schema.
- Metrics match hand-checked examples, stale data is visible, and backfills do not trigger an uncontrolled notification burst.
- Peak workload meets agreed limits; disk/queue faults are visible; backups restore within agreed recovery targets and any recovery gap is documented.

### Decisions required before production

Confirm hosting and region, initial projects/machines, sample schemas, event volume, retention, upload intervals, source ordering/identity rules, identity provider, customer role model, notification recipients, and recovery/availability targets. Exact resource limits and the final API schema follow these decisions. No hardware capacity or service-level commitment is implied by this draft.

### Technical references

Official documentation consulted during design on 26 October 2026. Product capabilities and plans should be rechecked before purchase or deployment.

1. Hostinger VPS plans: <https://www.hostinger.com/ca/vps-hosting>
2. PostgreSQL row security: <https://www.postgresql.org/docs/current/ddl-rowsecurity.html>
3. Grafana PostgreSQL integration: <https://grafana.com/docs/grafana/latest/datasources/postgres/>
4. Grafana data source permissions: <https://grafana.com/docs/grafana/latest/administration/data-source-management/>
5. Metabase row and column security: <https://www.metabase.com/docs/latest/permissions/row-and-column-security>
6. Postmark delivery integration: <https://postmarkapp.com/developer/user-guide/send-email-with-api>
