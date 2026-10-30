# Registered SCADA source deletion

The Central Server manager now provides **Delete selected source** in **3 Sources & collector setup**, in both Local and Network modes. The confirmation identifies the source and its customer/site/project, defaults to No, and explains credential revocation and retained collector queues.

Deletion sets `sources.deleted_at`, revokes every credential for that source and appends a `source_deleted` audit event in one transaction. The manager hides deleted registrations and excludes them from its source count. Export, credential replacement and new-generation creation reject deleted sources. Authentication also checks the deletion marker, so re-enabling an old credential alone cannot reactivate the source.

Source identities, generations, approved mappings, accepted uploads, receipts, revisions, processing jobs and protected setup files are retained. Other sources, including registrations sharing a machine, remain available. Already accepted work can finish processing. An upload already in progress may finish committing. This is not a history purge or a collector queue reset; there is no restore control.

Migration `0003_source_deletion` adds the marker and updates the existing narrow authentication function. Earlier migration files are unchanged. The management component startup now defaults to no demo-source creation; the separate development helper retains its explicit commissioning behavior.

## Verification

| Check | Result |
|---|---|
| Full suite, disposable PostgreSQL 17 | 210 passed, one desktop-display skip |
| Full suite, disposable PostgreSQL 18 | 210 passed, one desktop-display skip |
| Manager GUI and name validation checks | 19 passed |
| Skipped desktop checks rerun, including collector GUI checks | 18 passed, zero skipped |
| Migration upgrade/downgrade/re-upgrade on a disposable database | Passed |
| Deletion isolation, transaction rollback, retained history and approved mappings | Passed |
| Deleted credential rejection for uploads and connection tests; retained job processing | Passed |
| Packaged PostgreSQL 17 and 18 initialization, migrations, verified HTTPS and stop/start | Passed |
| All four source-action buttons at minimum 1080 × 750 window size | Visible without overlap |
| Central Server executable/installer builds and matching SHA-256 sidecars | Passed |

Each full suite emitted the existing Starlette/httpx deprecation warning. Test clusters and fixture records were isolated under ignored `.tools/` directories. No SCADA database was changed. Local verification helpers and logs are PC-specific and are not CI infrastructure.

The actual Windows installer completed with exit code 0. The installed executable matched the rebuilt executable SHA-256, and the installed application applied `0003_source_deletion` and restarted successfully. HTTPS API, PostgreSQL and worker were ready in Network mode at `https://187.17.53.84:8443/v1/uploads`. Saved settings, source/generation IDs, mappings, upload-credential verifiers, protected credentials and CA matched their pre-upgrade fingerprints; received-history counts were preserved. No source was deleted during this update, and the updated manager was reopened.

Local build checksums:

- `central-server.exe`: `1ada76b13563328ca7f3e37d59a3ba40e9661257702fae3624f4b462ce6a5b89`
- `Linker-Central-Server-Setup.exe`: `3a9a6224de438df0252d604e37a11dd90d2f212e2433d49c00602407693c1c7c`

Published GitHub X2 assets are unchanged and predate this button. See [usage and retention details](central-server-windows.md#delete-a-registered-source).
