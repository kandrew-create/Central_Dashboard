# SCADA implementation decisions and open questions

The collector and server design documents remain authoritative. The three software packages are SCADA Collector, Central Server, and Web Portal. Initial work covers the upload foundation; read APIs/portal follow in server-design Phase 2, and analytics/internal Grafana/notifications follow in Phase 3.

## Recorded implementation decisions

| Decision | Current implementation or boundary |
|---|---|
| Start collector development locally | Version 0.2 adds bounded change collection, durable queue/checkpoints, verified HTTPS delivery, local scheduling and a packaged service wrapper. Central ingestion, leased processing and recovery commands are implemented. See the current implementation report for verified local evidence and remaining deployment gates. |
| Local desktop interface | User requested a GUI. Native Tkinter/ttk desktop setup and record previews supplement the CLI, using the same protected configuration and read-only source operations. No local web server or additional inbound access is introduced. |
| Source profile | Only `ecostruxure_machine_scada_expert_v1`, with the exact supplied alarm/event fields and identity modes. No Heartbeat inspection or unidentified-table discovery. |
| Source credentials | Current-user Windows DPAPI and private ACLs for the collector account; no plaintext fallback. Dedicated source account, configured by the DBA. |
| Unknown source timezone | Preserve local timestamps and report `timezone_unknown`; never use the PC timezone implicitly. |
| Timestamp precision conflict | Preserve fractional source timestamps, but mark normalization invalid if both fractional seconds and a separate millisecond field are present, pending confirmation. |
| Preview semantics | Preview pagination remains diagnostic and does not change checkpoints. Collection is a separate operation with bounded scans, durable staging/confirmation, reset faults and explicit coverage limitations. |
| Local preview privacy | Operator fields omitted unless explicitly requested locally. This does not change the eventual upload-all default or decide the commissioned upload privacy policy. |
| Metadata boundary | Filtered PostgreSQL role/catalog and information-schema reads for the current account and approved schema/tables only. No source writes or automatic index/schema changes. |
| Runtime deployment boundary | Cloud cannot request uploads or send configuration/control instructions. Portal/read API, OIDC, Grafana, analytics, and notifications remain deferred. |

## To be confirmed before commissioning

| Topic | Required confirmation |
|---|---|
| Actual schema and samples | Sanitized representative rows for alarm activation, normalization, acknowledgement, and events; confirm the supplied fixture and nullable fields. |
| Other tables | Contents/purpose of Heartbeat and the two unidentified tables require separate approval before any future inspection. They remain excluded. |
| Change marker | Does every lifecycle/content change advance `last_update` and its milliseconds? Are they nullable, indexed, second-aligned, or non-advancing? |
| Identity and resets | ID reuse/manual inserts, database replacement/restoration signals, authorized local generation changes, and an approved reset-metadata strategy. |
| Deletes and retention | Hard-delete behavior, source retention, missing-history detection, and permissible reconciliation horizon. |
| Source time | Actual IANA timezone, fractional timestamp semantics, missing/invalid milliseconds, and DST handling. |
| Supported environment | Target Windows/PostgreSQL/SCADA versions, account permissions, packaging prerequisites, and service account lifecycle. |
| Read workload | Daily/peak volume, database size/indexes, normal/burst/backlog measurements, acceptable latency and SCADA resource limits. |
| Upload schedule | Local interval/day/time, DST policy, one catch-up occurrence, approved initial history range, and outage allowance. |
| Numerical limits | Batch/field/query/response limits, disk/free-space/log quotas, retry/backoff limits, and recovery targets; current preview defaults are proposed starting values only. |
| Identity/mappings/codes | Registry scope, source generation, approved machine mappings and mapping versions, severity and code lookup approvals. |
| Customer data agreement | Approved source fields, operator-data upload/omit/hash policy, keyed-hash ownership/rotation, and external response allowlist. |
| Hosting and destination | VPS or dedicated Linux host, region, fixed HTTPS hostname, certificate trust, proxy, and permitted outbound network access. |
| Upload credentials and contract | Secure provisioning/revocation/rotation, exact envelope/revision/batch hash contracts, schema version, and fixed receipt validation. |
| Recovery | Central backup/restore gap, local re-export process, retention/deduplication assumptions, and measured recovery time/point objectives. |
| Customer-environment acceptance | Representative SCADA independence/load tests, clean Windows installation, no listener runtime evidence, security/outage/restart/restore drills, and limited-pilot approval. |
