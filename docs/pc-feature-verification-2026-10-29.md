# Current-PC feature and startup verification

## Startup fault and repair

The installed Central Server had Network mode configured with an HTTPS listener address that was not assigned to this PC. `api.log` reported that it could not bind. PostgreSQL 18 and the worker had started, but the API exited; the startup health loop continued waiting for it. This was a failed startup, not slow database initialization.

The local Tailscale interface address was `100.111.173.111`, which already matched the saved collector-facing server hostname. Only the listener was corrected, from `100.111.65.53` to `100.111.173.111`, after stopping the configured central components. Existing database, credentials, source IDs and other settings were preserved. The manager was reopened normally to load the corrected settings.

The installed executable SHA-256 matched the rebuilt executable: `425511524fff9d796a47175c43d8cea3c8cf8af19e09ffc479f3e49fef125154`.

Measured on this PC after repair (individual observations, not a performance benchmark):

| Operation | Result |
|---|---|
| Source-mode start of the configured server | 6.34 seconds |
| Installed executable start of the configured server | 12.57 seconds |
| Manager status refresh | 0.41 seconds |
| HTTPS health check over the configured Tailscale address, with certificate verification | HTTP 200, `ready`, 0.024 seconds |

The installed manager was left open and the configured server running with HTTPS API Ready, PostgreSQL Ready and Worker Running. The live registry had **zero registered sources and zero uploaded batches/revisions**; real SCADA collection still requires registration and collector commissioning.

## Full automated suites

Both suites used fresh disposable PostgreSQL clusters, never the live Central Server or a SCADA/customer database:

| Database | Full-suite result |
|---|---|
| PostgreSQL 17.11 | 180 passed, zero skipped |
| PostgreSQL 18.6 | 179 passed, one desktop-display skip |

The skipped manager GUI start/stop check was rerun individually: **1 passed, zero skipped**. Each full suite emitted one Starlette/httpx deprecation warning. Coverage includes settings and credentials, GUI actions, bounded read-only extraction, alarm/event field preservation, privacy, collection, scheduling/DST, durable queue/replay, protocol validation, authentication, customer isolation/RLS, receipt durability, processing, mapping/quarantine, encrypted setup import/export and PostgreSQL compatibility.

Both versions also passed fresh initialization, migrations, verified HTTPS and repeated starts using disposable manager data.

## Installed-server workflow checks

A separate disposable Central Server was run with the **actual installed executable**, PostgreSQL 18, a separate data directory/ports, and Network mode bound to this PC's Tailscale address. The test created an explicitly disposable source fixture database and a dedicated read-only fixture login. No live registry entries or customer records were created.

All nine workflow groups passed:

1. Installed server starts on the configured local network address.
2. Customer/site/project/machine/source registration and registry listing work.
3. Encrypted setup export/import, Windows-protected credentials, authenticated HTTPS connection testing and read-only alarm/event previews work.
4. Actual fixture collection uploads over HTTPS, confirms durable acceptance, and quarantines unknown mappings.
5. Exact mapping approval and explicit reprocessing allow the background worker to complete the fixture batches.
6. Upload credential rotation and replacement setup export/import authenticate successfully.
7. During a server outage, the queue retains identical payload bytes across reopen; after server restart, retry delivery confirms and clears the pending batch.
8. Source fixture table counts remain unchanged by collection.
9. Unauthenticated HTTPS requests are rejected.

Every disposable database/application process was stopped afterward. The live server stayed healthy and its registry remained empty.

## Remaining commissioning checks

These results cover implemented features under local automated and installed-server fixture tests. They do not establish:

- Connection from a second physical PC, including its Tailscale access rules and Windows/network firewall path.
- Native unattended Collector service operation under a commissioned dedicated Windows account or after reboot.
- Representative real SCADA load, real source schema/timezone approval or off-server backup/restore.

Customer reporting/portal, analytics, Grafana, OIDC and notifications remain documented later phases, not features that passed this verification. Existing installer lock/stop-failure checks are recorded in [upgrade verification](central-server-upgrade-verification-2026-10-29.md).
