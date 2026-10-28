# Collector and central server operations

## Commission locally

Version 0.4 provides **Launch Central Server.cmd** with start/stop, health, registry, **4 Connection & mode** and encrypted collector setup export. Choose Local testing for one PC or Network server for a separate central PC. Collector **3 Collection & upload → Import server setup → Test server** verifies HTTPS and source registration before collection. Follow the [Windows guide](central-server-windows.md) for addresses, certificates and firewall setup. Existing local settings load as Local testing without changing source IDs or data.

The development environment uses Windows/Python 3.13 and PostgreSQL 17. The local server helper is separate from collector runtime. It creates its own SCRAM-authenticated PostgreSQL cluster on 127.0.0.1:55441 and a verified HTTPS API on 127.0.0.1:8443. Source PostgreSQL remains on its existing port and is never migrated, restored, indexed or modified by these helpers.

```powershell
uv pip install --python .venv/Scripts/python.exe -e '.[collector,server,test,local,build]'
& .venv/Scripts/python.exe -m deploy.local_server start
& .venv/Scripts/python.exe -m collector gui
```

Local credentials are DPAPI-protected under `.tools/local-server`; the database, logs, TLS keys and encrypted backups inherit private Windows ACLs. A private CA file is explicitly configured in the collector; no certificate is installed globally. New commissioning leaf certificates last 90 days, and the signing CA is retained across normal renewal. Existing valid legacy local certificates are preserved. Start renews certificates near expiry and restarts API/worker. Stop retains data, queue and protected credentials.

The first real-history test was explicitly authorized by the user. It copied the existing 9 alarm and 1 event rows over verified HTTPS, found zero source/server field mismatches and queued no duplicate records on the next scan. Source fields and credentials are not reproduced in test logs or release artifacts. Unknown machine mappings remain quarantined, with raw evidence retained.

## Central Linux deployment

Use the same application image for API and worker with separate restricted login credentials. Copy `.env.example` to a protected `.env` and replace every placeholder. Keep passwords high entropy and URL-encode them in connection URLs. API/worker URLs must use the corresponding `scada_api_login`/`scada_worker_login` passwords. Set the approved HTTPS hostname and its DNS first.

```sh
chmod 600 .env
docker compose -f deploy/docker-compose.yml config --quiet
docker compose -f deploy/docker-compose.yml up --build -d
```

Compose performs migrations and provisions separate restricted runtime logins before starting API/worker. PostgreSQL has no published port. API and worker containers run as UID 10001 with read-only filesystems and dropped capabilities. Only Caddy publishes ports 80/443; HTTPS ingestion is `/v1/uploads`, with a credential-authenticated, bounded `/v1/collector-check` preflight in 0.4. No administration, collector polling, portal or customer read API route is exposed. Review component pins against supported/security-approved versions before deployment; the supplied pinned environment is development evidence, not a security-update guarantee.

The migration administrator and the NOLOGIN `scada_bootstrap_owner` must never be application logins. Bootstrap ownership has narrowly granted credential/source SELECT and job SELECT/UPDATE rights plus two fixed SECURITY DEFINER functions. API authentication resolves credential scope through one function; worker claiming uses the other. RLS remains forced on application tables and tenant context is transaction-local. Changing schema/role definitions requires migration review.

On an authorized central administration connection, provision a registry, source/generation, initial machine, credential and exact-match mappings:

```sh
python -m server.admin provision --customer "Customer" --site "Site" \
  --project "Project" --machine-tag "SITE-LINE01" \
  --alarm-tag "APPROVED_SOURCE_TAG" --event-source "APPROVED_EVENT_SOURCE" \
  --output /secure/handoff/source.json
```

`MIGRATION_DATABASE_URL` must point to the central database. For a container command, mount a private handoff directory writable by UID 10001. The output is created exclusively with private permissions, contains the one-time upload token and must be transferred through an approved secure path. Enter the IDs in local collector settings and store the token via the GUI/hidden CLI prompt. Credential verifiers alone are retained centrally. Do not paste tokens into commands, source control or logs.

`rotate-credential --source-id UUID --output NEW_PRIVATE_FILE` provisions a replacement; optional `--revoke-prior` explicitly disables old tokens. Update the local protected token through authorized maintenance. Provision machine scope and approved mappings before customer reporting; no severity/code meanings are guessed.

## Quarantine and reprocessing

```sh
python -m server.admin status --source-id SOURCE_UUID
python -m server.admin approve-mapping --source-id SOURCE_UUID \
  --machine-id MACHINE_UUID --alarm-tag EXACT_TAG --reason APPROVAL_REFERENCE
python -m server.admin reprocess --upload-id UPLOAD_UUID --reason APPROVAL_REFERENCE
```

Mapping approval creates an immutable new version and preserves other exact-match rules. A single unambiguous approved match to a machine authorized when the batch was accepted is required. Unknown, ambiguous or unauthorized mappings remain quarantined. Reprocessing is audited and idempotent; original payloads and receipts are retained. Later batches do not make older source evidence newer. Equal-marker content conflicts and unverifiable markers keep latest state uncertain.

When latest state is marked uncertain, any revision pointer is a verified baseline among orderable observations, not a claim that it supersedes incomparable observations. Keep the uncertainty visible and retain the raw variants. A later known marker alone cannot resolve a different missing/unverified-marker observation; a demonstrably newer verified marker can resolve an equal-marker conflict.

## Windows service installation and removal

Build locally with `deploy/windows/build.ps1`; it generates four executables and the Inno Setup installer under `dist`. The installer installs binaries and a configuration template. It neither provisions source credentials nor creates a Windows service account. Installation requires a Windows administrator and prior account/SCADA commissioning. Executables/installer are currently unsigned.

1. Create an approved dedicated standard Windows account. Grant it only the local folder/network access needed for this collector and read-only PostgreSQL credentials. A database role and a Windows service account are separate accounts.
2. Allow that account to create its dedicated `C:\ProgramData\Linker\Collector` directory. Under that Windows identity, run the collector with `--config C:\ProgramData\Linker\Collector\config.toml init`, configure settings and protect database/upload credentials. DPAPI must be initialized under the actual runtime identity. Test connection and one upload under that same account.
3. As a Windows administrator, use the packaged administration executable. It prompts for the service-account password locally, grants service-logon rights and configures delayed startup and bounded restart recovery:

```powershell
& 'C:\Program Files\Linker\SCADA Collector\collector-admin.exe' install --account '.\scada_collector'
& 'C:\Program Files\Linker\SCADA Collector\collector-admin.exe' start
```

`stop` waits for bounded work to finish. Installer removal invokes `remove` and retains configuration, credentials, queue and logs. An explicit `remove --delete-state` is available only after pending work and retention are reviewed. No service/account installation has been performed on this development PC; a clean-machine, dedicated-account install/reboot/recovery/uninstall test remains required.

Service APIs and recovery configuration follow the [pywin32 service API](https://mhammond.github.io/pywin32/win32service__ChangeServiceConfig2_meth.html). Installer removal uses the documented [Inno Setup uninstall sequence](https://jrsoftware.org/ishelp/topic_runsection.htm).

## Faults and source reset

For TLS/auth/schema faults, correct local settings and credentials; pending bytes are unchanged. Receipt errors never advance delivery. Transient retry backoff is capped; persistent protocol/auth faults wait one hour. For queue quota or minimum-space faults, free space or raise an approved quota. Never discard unconfirmed queue files or silently clear a source reset fault.

A source identity/ID-regression fault stops collection and delivery before new uploads. Investigate whether it is retention, maintenance, restoration or replacement. If a new generation is justified, provision it centrally with `new-generation --source-id UUID --authorization REFERENCE`, then use collector `new-generation --generation-id UUID --authorization REFERENCE`. The old generation remains valid for immutable outage backlog; a new generation prevents reused IDs colliding with prior occurrences. Local authorization is journaled across crashes.

## Backup and recovery

For deployment, install approved `age` encryption tooling, provision the public recipient and keep its private recovery identity outside the server. Set `AGE_RECIPIENT` and `BACKUP_DIRECTORY`, then run `bash deploy/backup.sh`. It streams a custom PostgreSQL dump into encryption, produces a checksum and never writes an unencrypted dump. Copy the encrypted output/checksum and separately encrypted required configuration/recovery material to the approved off-server location; the script does not select or contact a storage provider.

Restore on a clean recovery host after initializing its database/roles. Validate the checksum, set `AGE_IDENTITY` and explicitly set `SCADA_RESTORE_CONFIRMED=clean-recovery-host`, then run `bash deploy/restore.sh BACKUP_FILE`. It stops API/worker and replaces database objects only under that explicit operator confirmation. Verify counts, hashes, credentials, retained jobs, leases and customer isolation before restarting runtime services. Downgrading schema is not a data-restoration or binary-rollback strategy; keep migration-compatible application artifacts and a tested backup.

The local Windows drill separately encrypts a dump with a DPAPI-protected key, restores into a temporary recovery database and compares retained source content and receipts. This proves a local restore, not off-server or clean-Linux recovery. Its key remains tied to this Windows identity; deployment uses separately managed portable recovery material.

If restoration predates confirmed uploads, the collector may have already removed those temporary batches. Under authorized local maintenance:

```powershell
& .venv/Scripts/python.exe -m collector re-export --authorization YOUR-RECOVERY-TICKET
& .venv/Scripts/python.exe -m collector collect
```

This resets local observation deduplication/progress for the existing approved history scope and generation while preserving pending batches. Reset checks still run. The server deduplicates records already retained; currently available missing source content can be imported again. Re-export cannot reconstruct hard-deleted rows or intermediate revisions overwritten in the source. State the resulting recovery-point gap; do not promise zero loss.

## Remaining commissioning gates

Before customer installation, confirm actual source timezone/precision/change behavior, mappings/code meanings/privacy, retention and supported reset evidence, acceptable workload/recovery targets, production hostname/region and credential lifecycle. Demonstrate representative SCADA independence and normal/peak/backlog load, clean Windows service operation, Linux deployment, off-server restore and operational ownership. Local fixture results and passing tests do not replace those demonstrations.
