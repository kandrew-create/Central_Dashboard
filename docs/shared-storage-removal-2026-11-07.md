# Shared-storage removal - 7 November 2026

The user requested removal of the old per-source database design on this Central Server PC. Migration `0013_remove_source_copies` is now applied to the existing **`linker-scada-wsl`** project in `/home/station7/central-server`. The registered source's `ELT250330DB.alarmhistory` and `eventhistory` copies, their schema, `platform.source_storage`, and their legacy synchronizers were removed. New and existing sources use shared tables.

## Preservation and backup

The manager closed normally and the configured API/worker stopped before the backup. An AES-GCM encrypted custom-format PostgreSQL dump was decrypted in memory and fully restored into an isolated PostgreSQL 17.6 container with no external networking, no logging and tmpfs database storage. Required role attributes and memberships were reproduced without exporting password verifiers. All retained Central table fingerprints matched the stopped server. The candidate image migrated that restored database to 0013, with all retained table fingerprints still matching. The disposable container was removed.

Only then was the stopped project's allowlisted application replaced and the live Central database migrated once. The database system identifier, every retained `platform`/`warehouse`/`reporting` table fingerprint, one source, **five committed batches and 61 saved versions** matched before/after. This includes originals, receipts, credentials, source/generation identity, scope, mappings, jobs, audit history, facts, summaries and queues. The encrypted backup, key, before-state fingerprints, previous application files and private diagnostics remain under the mode-0700 local `~/central-server/secrets/legacy-removal-20261107` directory; key files remain mode 0600 and outside Git/releases.

The saved environment, endpoint, CA and manager key/vault hashes were unchanged. All named volumes, including AI settings and Ollama models, were preserved. Existing runtime logins were reused without invoking password provisioning. The API, database and worker became ready. The manager was reopened using its existing Windows shortcut launcher. Windows verified the HTTPS certificate using the saved CA, the public health path remained hidden (404), and unauthenticated uploads were rejected.

No SCADA source database, Collector, Windows installation, unrelated Docker project or separate VMware Central database was migrated. Remote-PC commissioning, cold reboot and production load behavior were not re-tested.

## pgAdmin

The existing account, login password, database reader and protected passfile remain unchanged. The database reader received direct limited grants and fixed-customer restrictive SELECT policies on its permitted base dimensions, facts and summaries. No role memberships were added. A restored-database fixture containing another customer proved that changing the session customer did not grant access; original payload/credential reads, writes and role switching were rejected. These denials and successful shared-table reads were also checked using the live saved passfile.

The profile was backed up in its existing protected volume before setting the database navigation restriction to `warehouse,reporting`. Existing web login, database connection and reconnect without entering a password all passed. The reader could see **nine alarm occurrences and 52 event occurrences**, accounting for all 61 saved versions at verification time. Source/generation UUIDs remain available for identifying origins. Counts may increase with later legitimate uploads. Refresh the browser tree if it still shows old cached objects. See [browsing](pgadmin-browsing.md).

## Automated checks

- Fresh disposable PostgreSQL **17 and 18** clusters: **138 passed, seven Linux-only skips on each version**. Coverage includes fresh Alembic initialization, complete downgrade/re-upgrade, corrupt/missing-copy rejection, unexpected object/column/dependency rollback, two-customer isolation, unchanged retained tables, new shared registrations/renames, and upload replay/processing after removal.
- Isolated Linux container with fresh disposable PostgreSQL 17.6: **12 passed, no skips**, including the seven Linux vault/agent checks skipped on Windows, removal safety, fresh migration and upload replay/processing.
- Windows Docker-manager/GUI checks: **19 passed**.
- Central Compose validation passed without starting services; Git whitespace checks passed.

The suites emit an existing Starlette/httpx deprecation warning. They did not enable AI or call a model. No customer/raw records or credentials were copied into source-controlled test evidence.

## Recovery

Migration failures are transactional. Different legacy/native evidence or extra dependencies block removal; investigate instead of bypassing validation. Earlier migrations remain unchanged. Downgrading 0013 reconstructs per-source copies from canonical originals but assigns new OIDs and cannot recreate former custom grants; use the protected pre-change backup for exact old objects/permissions. Restoring over operational storage requires a separate explicit recovery decision. See [storage safeguards](source-table-layout.md).

## Project/source filtering follow-up

After the user reported difficulty filtering by a project such as ELT250330, Central-only migration **0014_named_warehouse_views** added `reporting.alarm_occurrences` and `reporting.event_occurrences`. Each is a security-invoker view over the shared fact and dimension tables, with current customer/site/project/source names first and all fact fields/UUIDs retained. No per-source/project copies or new stored rows were introduced. Labels follow registration renames immediately; approved mapping, uncertainty and saved-version behavior remain unchanged.

The active registration contains ELT250330 in the **source name**, not the project label. Verified queries use `source_name ILIKE 'ELT250330%'`; `project_name` displays the registered project and supports its own exact-name filter. The existing fact tables can also be queried by joining `warehouse.dim_project` and `warehouse.dim_source` on their full customer/site/project/source keys. See [ready-to-run queries](pgadmin-browsing.md#filter-by-project-or-source-name).

The local WSL project was upgraded from 0013 to 0014 after a new encrypted full backup restore and candidate migration in an isolated tmpfs PostgreSQL 17.6 container. Every retained Central table fingerprint, database identity, one source, five batches, 61 versions, settings/CA/vault hashes and named volumes matched. The existing reader received direct SELECT on the two views; its fixed-customer restrictive policies and absence of memberships remain unchanged. Real saved-passfile queries returned nine matching alarms and 52 matching events, with both labels present; setting a different customer exposed no named-view rows. Browser login/reconnect, denied writes/credentials/raw payload/role switching, and CA-verified HTTPS/auth rejection passed. API/database/worker are ready and the manager was reopened. The new protected backup/evidence directory is `~/central-server/secrets/project-views-20261107`; its key remains outside Git.

Current verification: **141 passed, seven Linux-only skips on each fresh PostgreSQL 17 and 18 cluster**; **15 passed without skips** in an isolated Linux container/disposable PostgreSQL 17.6. Coverage includes matching project/source filters, duplicate labels across customers, live label changes, invoker RLS, denied writes and view-only downgrade/re-upgrade. The existing Starlette/httpx warning remains. No separate VMware server, Collector, published installer or Git push changes; no reboot/load or new remote-PC commissioning claim.

## Machine-mapping requirement removed

At the user's subsequent request, the local project advanced to **0015_source_scoped_processing**. Source-authenticated uploads now process without machine-mapping approval; the command and analysis prompts are removed and new registrations create no draft mappings. The five completed-job holds and all 61 quarantined versions were released with preserved originals/receipts and an audited workflow-status transition. Historical metadata remains inactive; optional AI and accepted event identity stay separate. A fresh full encrypted-backup restore/candidate migration, database preservation checks, API/database/worker readiness and real pgAdmin/manager/HTTPS checks passed. See [current behavior, full evidence and recovery](source-scoped-processing.md).
