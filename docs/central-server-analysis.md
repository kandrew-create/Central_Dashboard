# Central Server analysis and security punchlist

## Implemented scope

The WSL/Docker manager adds **Alarm analysis** for recurring alarms, affected equipment and daily trends. Counts are calculated from saved records. The optional local model continues to suggest equipment names; it does not diagnose root causes or establish approved machine mappings. Viewing either tab never enables AI or calls a model.

| Requested item | Implementation |
| --- | --- |
| Standard warehouse structure | Central migration `0010_alarm_warehouse` adds read-only dimensions and alarm occurrence facts. |
| Alarm issue analysis | Customer/source filters, first-saved time windows, top 50 exact message/tag groups, approved equipment, separate AI suggestions and UTC daily activity. |
| Identity and API credential security | IDs identify data; the bearer credential authorizes customer/source/machine scope. Existing hashing, encryption, TLS and revocation are retained and tested. |
| Encrypted, hidden API key | PostgreSQL stores a SHA-256 verifier. Local setup credentials remain encrypted and GUI/RPC operation responses omit the token. |
| Refresh in minutes | New profiles default to one minute; existing second-based intervals are retained as fractional minutes. Off remains available. |
| Hidden upload URL | Removed URL labels, preview and Copy URL. The real saved endpoint remains in encrypted exports; Deployment still permits hostname/listener/port repair. |
| Automatic Docker startup | Windows launchers start Docker Desktop if needed. Opening the WSL GUI starts its configured project once, reuses a ready project and leaves it running on close. |

Published X3 packages remain unchanged. Packaged-launcher changes require a future rebuild. The Windows source shortcut uses the checkout immediately; Linux GUI/backend changes require deployment and migration.

## Warehouse and analysis contract

`warehouse.dim_customer`, `dim_site`, `dim_project`, `dim_source`, `dim_machine` and `dim_date` provide named dimensions. `fact_alarm_occurrence` has one row per `(source_id, generation_id, source_record_id)` for processed alarms; `alarm_daily` groups those facts by source and UTC source-start date. These are live SQL views, not a materialized ETL service or a copy of the source database.

Saved versions never count as repeat occurrences. Generations separate reused record IDs. Quarantined alarms remain in totals. Unknown revision order leaves latest state and approved equipment unavailable. Source dates are used only when all saved versions agree on a known UTC start timestamp; conflicting/missing/unknown times are flagged and excluded from daily trends. Raw fields, separate milliseconds and history remain unchanged.

The time window uses when each occurrence was **first saved in Central**. Backfill may show older source dates. Results are bounded to 50 issue groups and 366 dated trend rows. Recurrence groups use exact messages/tags and do not prove a common cause. AI equipment labels remain in an unverified column and never increase approved-equipment counts. No alarm duration, root cause or maintenance action is inferred.

Views use `security_invoker=true` with existing forced customer RLS and explicit reader column grants. PostgreSQL describes [invoker privileges and row security](https://www.postgresql.org/docs/17/sql-createview.html). Readers receive no payloads, operator fields, credential verifiers or writes. The trusted local manager may review all customers and provides customer/source filters; it is not a public customer reporting API. Portal, OIDC, Grafana, notifications, event analytics and diagnostic AI remain future work. Aggregation retains management statement timeouts; production-sized workloads still require measurement.

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
