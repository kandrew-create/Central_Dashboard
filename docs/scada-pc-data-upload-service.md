# SCADA PC Data Upload Service

**Service description and installation requirements**
Linker Enterprise Inc. | 26 October 2026 | Draft version 1.0

---

## 1 Purpose and agreed design

The service collects alarm and event records already logged by EcoStruxure Machine SCADA Expert in a local PostgreSQL database and uploads them to a central cloud VPS. The VPS stores records from multiple projects for dashboards, analytics, external API access, and email notifications.

The agreed design uses strict upload-only operation. A Windows service on the SCADA PC determines when to collect and submit data using a locally configured schedule. The VPS cannot request an upload, change local settings, or control the SCADA PC through this service.

### Service responsibilities

- Read approved alarm and event data without modifying SCADA records.
- Upload new records and supported record changes through an authenticated HTTPS API.
- Track confirmed delivery, retry failures, and provide local status and diagnostic logs.
- Operate within bounded database, network, memory, and disk usage limits.

### System boundary

SCADA remains responsible for alarm detection, operator display, acknowledgement, and database logging. The collector is a reporting component. It has no PLC control functions and does not acknowledge, clear, or reset alarms in SCADA.

The cloud is responsible for data storage, customer access, analytics, and email/report configuration. Cloud notifications reflect the last successfully uploaded data; a nightly or weekly upload is not an immediate alarm notification channel.

### Meaning of upload only

The collector initiates every cloud connection. No inbound listener, command subscription, cloud polling for jobs, remote shell, or port forwarding is introduced. HTTPS still carries server responses and network acknowledgements; this is an application restriction, not a physically one-way connection or a guarantee of zero cybersecurity risk.

---

## 2 Installation and local configuration

Install one collector instance per approved SCADA PC or database source. Installation requires an authorized Windows administrator; normal operation uses a dedicated account with limited permissions. Exact Windows and PostgreSQL versions must be recorded and tested before deployment.

| Setting | Local requirement |
|---|---|
| Database connection | Host, port, database name, and a dedicated read-only username and password. Use localhost when the database is on the same PC. |
| Database profile | Approved schemas, tables or views, field mappings, record identity, timestamp interpretation, and change detection method. |
| Cloud destination | Fixed HTTPS hostname and API path provisioned during installation. Destination changes require authorized local action. |
| Site identity and credential | Customer, site, project, and source identity, plus a unique upload credential provisioned through an authorized setup process. |
| Upload schedule | Daily, weekly, or an approved interval; local time and timezone; initial history range; missed-run policy. |
| Resource limits | Batch size, query and upload timeouts, retry limits, queue/log quotas, minimum free disk space, and workload limits. |
| Network settings | Approved outbound HTTPS access to the VPS, normally TCP 443; proxy settings where required. No new inbound rule. |
| Local storage | Protected folders for configuration, checkpoint state, pending batches, and rotating logs. |

### Database preparation

An authorized database administrator creates the collector account and grants only the connection, schema, and SELECT permissions needed for approved tables or views. The collector must not receive database ownership, write, schema-change, or administrative privileges. Any index or schema changes require separate review.

### Commissioning sequence

1. Install the service.
2. Configure the database and site credential.
3. Test connectivity.
4. Select and validate the database profile.
5. Set the schedule.
6. Run an authorized local test upload.
7. Verify cloud storage.
8. Enable automatic startup and service recovery.

No change inside the SCADA application is expected if its existing logging contains all required data. Credentials and settings must not be embedded in a generally distributed installer.

---

## 3 Collection and delivery behavior

### Scheduled execution

The service starts with Windows without requiring an interactive login. It waits for the local schedule, opens a bounded database read, and prepares an upload batch. Only one collection/upload cycle may run at a time. A local status utility may offer *Test connection* and *Upload now* to authorized users; no remotely accessible web interface is required.

After a missed schedule or reboot, perform one catch-up run and then resume the schedule. Do not replay every missed timer occurrence. Define timezone and daylight-saving behavior locally and prevent duplicate runs for the same scheduled occurrence.

### Record selection and mapping

Each uploaded record includes a stable source record identifier, source/site identity, record type, event timestamp, and the alarm/event fields available in the approved mapping. Preserve relevant alarm identity, description, severity, active/cleared status, acknowledgement details, and quality where the source provides them. Do not invent unavailable fields.

Normalize timestamps to UTC only when the source timezone is known; preserve the original timestamp and its interpretation where needed. Ambiguous local timestamps must be flagged rather than silently assigned an assumed offset.

The extraction method must match the actual schema. If SCADA updates existing alarm rows on acknowledgement or clearing, the collector must capture those updates. A strategy that only selects IDs greater than the last ID is insufficient unless completeness, including late commits, has been demonstrated. Use a verified change marker or a defined reconciliation method, with cloud deduplication.

### Upload and confirmation

Send bounded batches over HTTPS to the configured ingestion API. Each batch has a stable identifier and payload hash; a retry reuses the same identifier and content. The cloud binds the upload credential to its allowed site and handles repeated records or batches without creating duplicate events.

The cloud confirms a batch only after durable database storage. The collector accepts a small, fixed response schema containing the matching batch identifier, hash, and committed status. HTTP success alone is insufficient. Do not accept a cloud-supplied extraction cursor, destination, query, or instruction.

Advance the local checkpoint atomically only after valid confirmation. A crash or lost response must allow safe resubmission. Remove the confirmed temporary batch after the checkpoint is secured. The collector must never delete source SCADA records.

### Initial history and retention

Initial historical uploads use a locally approved date range and the same workload limits as normal uploads. Source retention must exceed the expected outage and catch-up period. Detect and report missing history or database replacement/reset; never silently skip a gap or restart under an incorrect source identity.

---

## 4 Security and operational protection

### Restricted communication

- Use HTTPS with server certificate and hostname validation. Reject invalid certificates and unexpected redirects; never fall back to unencrypted HTTP.
- Use a unique credential restricted to uploading for one authorized site/source. It must not grant cloud database administration or access to other customers.
- Store credentials with Windows-supported protection and restrictive file permissions. Exclude secrets and unnecessary customer data from logs.
- Enforce response size, content type, schema, and processing time limits. Unexpected content produces a failed upload; it is never executed or used as configuration.
- Accept no remote SQL, scripts, commands, schedule changes, credential changes, or executable downloads through the upload channel. No automatic updater is included in this service.

### Failure and retry behavior

Internet loss, VPS downtime, and transient database failures trigger locally bounded retry backoff. Authentication, certificate, or schema failures are reported and must not cause aggressive retry loops. Pending work survives a normal service restart and power loss through durable state management.

Set explicit disk quotas for pending batches and logs, plus a minimum free-space threshold. At a limit, stop staging additional data and show a local fault. Leave unread data in PostgreSQL for later collection. Do not silently discard unconfirmed batches. If source retention expires before recovery, report the resulting gap.

### Protecting SCADA operation

Use short reads, query timeouts, small batches, and controlled concurrency. Avoid long transactions and unbounded scans. Validate query load against representative alarm volume, including an alarm burst and a large backlog. The collector must not stop, restart, or alter SCADA, PostgreSQL, PLC communications, or their configurations.

SCADA must remain operational when the collector is stopped or its cloud connection fails. This is an acceptance requirement to demonstrate during testing, not an assumption based on the service being read-only.

### Status and maintenance

Local status shows last successful upload, latest confirmed source timestamp, next run, pending batch count, queue usage, service/profile version, and the latest error. Logs rotate within a fixed quota. The VPS may flag stale data from missed expected uploads without sending requests back to the PC.

Credential renewal, configuration changes, and signed software updates require an authorized local maintenance process. Stopping or uninstalling the collector must not change SCADA logging or delete source records. Preserve or remove collector state only through an explicit maintenance choice.

---

## 5 Verification and implementation handoff

This document describes required behavior; it does not represent an installed or tested product. The following checks must pass before a customer deployment.

| Check | Required evidence |
|---|---|
| Normal collection | Known alarms/events arrive with correct identity, timestamps, mapped fields, and site isolation. |
| Alarm lifecycle | Activation, acknowledgement, and clearing are collected correctly, including updates to older rows. |
| Duplicate and crash recovery | Lost responses, replayed batches, and crashes before/after confirmation create no duplicate events or skipped records. |
| Outage and storage limits | An outage and restart preserve pending work; quota and free-space limits stop staging safely and report the condition. |
| Security boundary | No inbound listener or cloud job polling; remote commands/configuration and malformed, oversized, or mismatched responses are rejected. |
| Authentication and TLS | Invalid credentials and certificates fail safely; one site credential cannot submit to another site. |
| Scheduling and source changes | Reboot, missed run, timezone transition, database reset, late records, and source retention gaps have defined outcomes. |
| SCADA performance | Representative normal and peak loads meet agreed resource limits; stopping the collector leaves SCADA logging and control unaffected. |

### Information required before implementation

- Sample database schema and sanitized records showing alarm activation, acknowledgement, clearing, and events; record keys and update behavior.
- Windows, PostgreSQL, and SCADA versions; source database size, daily/peak record volume, retention policy, and timestamp conventions.
- Approved upload interval, initial history range, tolerable outage, resource limits, destination hostname, proxy needs, and customer data scope.
- Final ingestion API contract, per-site credential provisioning/renewal process, mapping version rules, and durable acknowledgement behavior.

### Expected implementation deliverables

A Windows installer and service; an authorized local configuration/status utility; approved database profiles; a documented ingestion interface; an installation and recovery guide; and recorded acceptance-test results. Central dashboards, analytics, and email generation are separate VPS components.

### Design basis

Prepared from the architecture decisions agreed with Linker Enterprise Inc. on 26 October 2026. Local scheduling and strict upload-only communication are fixed scope requirements. Exact schema handling and numerical resource limits remain subject to inspection and commissioning tests.
