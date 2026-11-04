# Simple Central Server browsing in pgAdmin

For current installations upgraded through `0012_shared_source_storage`, new sources use **warehouse → Tables → fact_alarm_occurrence / fact_event_occurrence** and **reporting → Tables** for summaries. Original revisions remain in `platform`. Existing source-specific tables described below remain compatible, but are no longer created for new registrations. Add `warehouse,reporting` to a connection's schema restriction only after its reader has the required customer-scoped privileges; changing a navigation filter does not grant access. The existing Windows/WSL browser connection below was not reprovisioned by the VMware warehouse deployment. See [current warehouse structure](source-table-layout.md).

## Docker browser on this Central Server PC

Open **Central Server Data - pgAdmin** from the desktop/Start menu, or visit **http://localhost:5050**. The browser runs pgAdmin 9.19 in the separate `linker-central-pgadmin` Compose project, using [the official container](https://www.pgadmin.org/docs/pgadmin4/latest/container_deployment.html). It connects to the existing private Central database network; PostgreSQL has no published host port, and pgAdmin is published on IPv4 loopback only.

Sign in at the browser's username/password prompt as **Linkent**, using the existing generated pgAdmin password. The password entry is masked. On this PC, open `%LOCALAPPDATA%\Linker\pgadmin-docker\Show pgAdmin passwords.cmd` to view it privately; that viewer also keeps passwords masked until Show is selected. Windows DPAPI protects this handoff; passwords remain outside Git. The login password and PostgreSQL reader password are separate. The configured connection uses a protected passfile within the user's private pgAdmin storage, and reconnecting without entering the database password was verified.

Username sign-in uses Caddy HTTP Basic authentication and pgAdmin's supported [webserver authentication](https://www.pgadmin.org/docs/pgadmin4/latest/webserver.html). The proxy verifies a bcrypt hash of the existing generated password, overwrites the asserted identity header and supplies a private shared secret. pgAdmin accepts only the proxy's exact IPv4 address and its IPv6-mapped equivalent. The backend has no published host port; only the proxy publishes loopback port 5050. The original account ID, administrator role, saved server and database reader remain preserved. Email remains bootstrap metadata and is no longer the sign-in identifier. Browsers can cache Basic authentication until closed; pgAdmin's Logout button alone does not clear those browser credentials.

Expand **Servers → Linker Central Server → Central Server - read only → Databases → scada_platform → Schemas → ELT250330DB → Tables**. Right-click **alarmhistory** or **eventhistory**, then choose **View/Edit Data → All Rows**. The current tables contain nine alarm rows and one event row. Use Query Tool for bounded checks:

```sql
SELECT count(*) FROM "ELT250330DB".alarmhistory;
SELECT count(*) FROM "ELT250330DB".eventhistory;
```

The dedicated reader has SELECT on only the intended customer's current source tables, no role memberships or storage ownership, a customer-scoped session default, and read-only transactions by default. Explicit write and upload-credential-table access checks were denied. New sources require an explicit scoped grant; a schema filter alone is not authorization. No SCADA source database settings were changed.

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

Central Server 0.6.1 provides this layout for each registered source:

The schema name below is an example; your registered source name is used. Duplicate, reserved or long labels receive the safe adjustments described in [storage details](source-table-layout.md).

```text
Schemas
└── Oven Line SCADA
    └── Tables
        ├── alarmhistory
        └── eventhistory
```

Each source uses its registered SCADA PC/source name. Select a source in the manager to see its SQL schema. These are real tables, maintained by Central Server. Right-click a table and choose **View/Edit Data → All Rows** to read its records. Direct row changes are blocked to preserve collected history.

For bounded SQL reads, quote the schema name exactly:

```sql
SELECT id, al_message, equipment, identification_status
FROM "Oven Line SCADA".alarmhistory
ORDER BY generation_id, id, received_at
LIMIT 100;

SELECT id, ev_message, equipment, identification_status
FROM "Oven Line SCADA".eventhistory
ORDER BY generation_id, id, received_at
LIMIT 100;
```

All native fields, separate milliseconds and saved revisions remain available. Unchanged repeat collection adds no revision. A changed record can retain multiple rows with the same native ID; `revision_id` identifies each stored content version. See [storage and synchronization](source-table-layout.md).

In **scada_platform → Properties → Advanced → Schema restriction**, enter the wanted schemas, such as `Oven Line SCADA,Packaging SCADA`, then refresh **Schemas** or reopen pgAdmin. Restrict the Central Server connection's database list to `scada_platform` if desired. Add newly registered source schemas to this restriction to display them. Existing window contents can remain cached until refreshed.

Internal `platform` tables and the earlier `logs` views remain preserved and hidden by this preference. Clear the restriction and refresh to browse them again. Hiding schemas changes navigation only; authorized SQL access and permissions remain unchanged. Other server connections remain untouched. Back up the private pgAdmin profile before changing its stored preferences.
