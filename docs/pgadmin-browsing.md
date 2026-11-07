# Simple Central Server browsing in pgAdmin

Current installations through `0014_named_warehouse_views` use **warehouse -> Tables -> fact_alarm_occurrence / fact_event_occurrence** and **reporting -> Tables**. The old per-source duplicate schemas/tables have been removed after canonical-evidence validation. Original revisions and receipts remain in `platform`, with shared facts separated by customer/source/generation UUIDs. See [storage and upgrade safeguards](source-table-layout.md).

## Docker browser on this Central Server PC

Open **Central Server Data - pgAdmin** from the desktop/Start menu, or visit **http://localhost:5050**. The browser runs pgAdmin 9.19 in the separate `linker-central-pgadmin` Compose project, using [the official container](https://www.pgadmin.org/docs/pgadmin4/latest/container_deployment.html). It connects to the existing private Central database network; PostgreSQL has no published host port, and pgAdmin is published on IPv4 loopback only.

Sign in at the browser's username/password prompt as **Linkent**, using the existing generated pgAdmin password. The password entry is masked. On this PC, open `%LOCALAPPDATA%\Linker\pgadmin-docker\Show pgAdmin passwords.cmd` to view it privately; that viewer also keeps passwords masked until Show is selected. Windows DPAPI protects this handoff; passwords remain outside Git. The login password and PostgreSQL reader password are separate. The configured connection uses a protected passfile within the user's private pgAdmin storage, and reconnecting without entering the database password was verified.

Username sign-in uses Caddy HTTP Basic authentication and pgAdmin's supported [webserver authentication](https://www.pgadmin.org/docs/pgadmin4/latest/webserver.html). The proxy verifies a bcrypt hash of the existing generated password, overwrites the asserted identity header and supplies a private shared secret. pgAdmin accepts only the proxy's exact IPv4 address and its IPv6-mapped equivalent. The backend has no published host port; only the proxy publishes loopback port 5050. The original account ID, administrator role, saved server and database reader remain preserved. Email remains bootstrap metadata and is no longer the sign-in identifier. Browsers can cache Basic authentication until closed; pgAdmin's Logout button alone does not clear those browser credentials.

Expand **Servers -> Linker Central Server -> Central Server - read only -> Databases -> scada_platform -> Schemas -> warehouse -> Tables**. Right-click **fact_alarm_occurrence** or **fact_event_occurrence**, then **View/Edit Data -> All Rows**. Open **reporting -> Tables** for maintained summaries and **warehouse -> Views** for dimensions. Refresh **Schemas**, or disconnect/reconnect the saved server, if the browser still shows the removed schema.

```sql
SELECT s.name AS source_name, f.source_id, f.generation_id,
       f.source_record_id, f.saved_versions, f.source_time_uncertain
FROM warehouse.fact_alarm_occurrence f
JOIN warehouse.dim_source s USING (customer_id, source_id)
ORDER BY s.name, f.generation_id, f.source_record_id
LIMIT 100;
```

## Filter by project or source name

Migration `0014_named_warehouse_views` adds **reporting -> Views -> alarm_occurrences / event_occurrences**. These read-only views include `customer_name`, `site_name`, `project_name` and `source_name` before the unchanged fact fields. They join shared dimensions without creating per-project/source copies. Current labels update immediately; UUIDs remain the identity, and caller permissions/RLS still apply.

For the source whose name starts with ELT250330, open **Query Tool** and run:

```sql
SELECT *
FROM reporting.alarm_occurrences
WHERE source_name ILIKE 'ELT250330%'
ORDER BY source_record_id
LIMIT 100;
```

For events, use `reporting.event_occurrences`. ELT250330 currently matches a registered **source** name, not a project label. To find the actual project and available sources:

```sql
SELECT DISTINCT project_name, source_name, project_id, source_id
FROM reporting.alarm_occurrences
UNION
SELECT DISTINCT project_name, source_name, project_id, source_id
FROM reporting.event_occurrences
ORDER BY project_name, source_name;
```

To filter a registered project, use `WHERE project_name = 'the registered project name'`. Names can repeat across customers/sites/projects; use the retained UUIDs when exact identity matters. In **View/Edit Data**, select the named view and use **Filter/Sort** with `source_name ILIKE 'ELT250330%'` or `project_name = 'the registered project name'` as the filter expression (omit `WHERE` in that dialog).

Without migration 0014, query `warehouse.fact_alarm_occurrence` or `warehouse.fact_event_occurrence` and join the existing dimensions:

```sql
SELECT p.name AS project_name, s.name AS source_name, f.*
FROM warehouse.fact_alarm_occurrence f
JOIN warehouse.dim_project p USING (customer_id, site_id, project_id)
JOIN warehouse.dim_source s USING (customer_id, site_id, project_id, source_id)
WHERE s.name ILIKE 'ELT250330%'
ORDER BY f.source_record_id
LIMIT 100;
```

The existing reader now has direct SELECT on shared facts/summaries and the dimension columns needed by invoker views. Fixed-customer **restrictive RLS policies** enforce its customer authorization even if arbitrary SQL changes `app.customer_id`. The reader has no role memberships, owner privileges or access to original payloads, upload credentials or writes. Default transactions remain read-only. Newly registered sources for this customer appear in shared tables; no per-source schema grants are needed. Additional customer access requires separate explicit provisioning.

The saved database schema restriction is `warehouse,reporting`. This is navigation only and does not grant access; it can still list internal refresh objects which the reader cannot query. The profile was backed up before changing this filter, and the account, passfile and connection were retained.

The service definition is `deploy/docker-compose.pgadmin.yml`, with proxy configuration in `deploy/pgadmin/Caddyfile`. This PC's private WSL `~/central-server/secrets/pgadmin/settings.env` selects the login username, unused private proxy subnet/address, bcrypt hash and shared secret; keep this file mode 0600 outside Git. Credentials and preconfigured server definitions live in the separate `linker-central-pgadmin_pgadmin-secrets` Docker volume, readable only by pgAdmin's UID 5050. Its profile is in `linker-central-pgadmin_pgadmin-data`. The profile also holds a mode-0400 copy of the reader passfile at `storage/Linkent/pgpass`; the saved server uses relative `passfile=pgpass` to satisfy pgAdmin's per-user file confinement. Preserve both volumes and the private pre-change profile backup; do not reset them to repair login. Container logging is disabled. Local commissioning helpers under `.tools/` are PC-specific and not portable installers. These templates require the privately provisioned account and passfile; they are not a fresh-install provisioning workflow.

From Ubuntu, start/stop only the optional browser with:

```bash
docker compose --project-name linker-central-pgadmin \
  --env-file ~/central-server/secrets/pgadmin/settings.env \
  -f ~/central-server/deploy/docker-compose.pgadmin.yml up -d

docker compose --project-name linker-central-pgadmin \
  --env-file ~/central-server/secrets/pgadmin/settings.env \
  -f ~/central-server/deploy/docker-compose.pgadmin.yml stop
```

Closing the browser does not stop Central Server. Stopping pgAdmin also leaves Central Server and Docker Ollama running. Verification covered the actual web login, server connection/reconnection, customer-scoped row counts, denied writes/credential reads and loopback-only configuration. No broad application suite was repeated for this optional browser setup.

## Earlier published installers

Published Central Server 0.6.1 uses a source-named schema with `alarmhistory` and `eventhistory`. Current migration 0013 removes those verified copies. Do not use old per-source queries after upgrading. Original native fields, separate milliseconds and saved content versions remain in the authoritative ledger, accessible only through appropriately authorized administrative workflows. The `logs` compatibility views also remain; they contain no physical copies.

The local 7 November 2026 update verified the existing browser login, connection and reconnect without a password prompt; all dimension views and shared summaries were readable. Changing the customer setting exposed no other customer, and credential/raw-payload reads, writes and role switching were denied. See [deployment and test evidence](shared-storage-removal-2026-11-07.md).
