# Collector WSL/Docker verification — 2026-11-01

The Collector CLI/scheduler now supports Linux credentials and a separate Docker Compose deployment. See the [setup guide](collector-wsl-docker.md). The existing native Windows settings, DPAPI credentials, source identities and queue were preserved. Published X2 installers are unchanged; the new runtime was built as the local Docker image `linker-scada-collector:local`.

## Implementation

- Added authenticated credential encryption on Linux using a separately supplied key, strict ownership/private permissions and atomic file replacement. Windows retains DPAPI and its existing filenames; Linux uses `.fernet` filenames. Missing/wrong/insecure keys fail without replacing credentials or generating a new key.
- Added CLI `create-key`, `import-setup` and `test-server`. Setup import reuses the existing source identity, pending-queue, policy preservation and scheduler-lock checks. Server testing does not read/upload records or advance checkpoints.
- Added a non-root Collector image target, separate state/key volumes, a read-only key mount and filesystem, dropped capabilities, bounded logs and no published ports. Initialization refuses to overwrite existing setup/key material.
- CLI scheduling handles SIGINT/SIGTERM through its cancellation event. Docker Stop allows 120 seconds for bounded work; pending uploads survive normal stop/restart.
- Selected the runtime `base` image target explicitly for Central Server Compose services. The Dockerfile's final `test` stage runs as root and contains test dependencies; the server services now select the intended unprivileged runtime stage. The existing test service still explicitly selects `test`.
- Updated the Linux test image with test-only Tk/local dependencies and deployment helpers. Disposable source-scan tests use `PGHOST` instead of hard-coded loopback. Live HTTPS verification now runs on Linux as well as Windows.

## Executed checks

| Check | Result |
|---|---|
| Final Windows acceptance suite, verified disposable PostgreSQL 17 cluster | **218 passed, 4 skipped** |
| Linux suite as UID/GID 10001 against a separate disposable PostgreSQL 17.6 container | **164 passed, 58 skipped** |
| Collector Linux image builds | Passed |
| Collector and Central Server Compose configuration validation | Passed |
| Actual container start, Stop, restart and immutable pending-payload check | Passed; Stop exit code 0 |
| Container non-root user, read-only root/key mount, no published ports | Passed |
| New operational Docker key/configuration initialization and configuration validation | Passed; collection/upload disabled |

Windows skips are the four Linux credential tests, which passed in the Linux run. Linux skips cover Windows DPAPI/private ACL/manager process checks and GUI tests needing a desktop display. The final Windows run executed the desktop checks. Both suites reported an existing Starlette/httpx test-harness deprecation warning.

The integration fixtures cover committed receipts, replay/conflicts, lost replies, tenant isolation, revisions, worker processing/quarantine, source read-only permissions, bounded extraction and durable queue recovery. Live TLS checks reject an unknown CA and accept explicit matching CA trust. Linux credential tests cover encryption/rotation, wrong/missing/insecure keys, ciphertext tampering, symlinks and refusal to overwrite initialization.

The Docker runtime check used its own uniquely named Compose project and synthetic queued record, without contacting a source database or Central Server. It verified encryption and pending payload hashes through stop/restart, then removed only that test project's volumes. Operational Collector volumes were retained. The PostgreSQL container used only an isolated test network with no published database port; fixture-only trust was enabled because test roles have no passwords. No customer or active Central Server database was used.

Local-only evidence/helpers remain under ignored `.tools/`, including `collector-container-check-result.json`, `remote-network-check-result.json` and `collector-acceptance-results.xml`. They are development-PC evidence, not portable CI infrastructure.

## Actual two-PC connection

The operator confirmed that this PC runs Collector and the other PC runs Central Server. TCP connection to the supplied server IPv4 on port 8443 succeeded. HTTPS verification using the installed Collector's existing CA failed with an unknown issuer. Both saved Collector configurations still target localhost.

The encrypted setup file in Downloads was unlocked through a local masked dialog. It advertised a different server address, so the check stopped before credential authentication or upload. No saved Collector configuration or operational queue was changed. Per the operator's request, a fresh setup export/import will follow completion of this setup work.

Remaining commissioning: export the existing source's setup with the correct Network-mode address/certificate on the Central Server, import it locally, verify `test-server` and the read-only source connection, then perform a bounded upload and confirm processing/quarantine on the server. A representative live upload, remote outage/recovery, Docker source database TLS access and boot/login operation remain unverified. Automatic Windows-to-Linux state migration and native WSL-distribution installation were not performed; the tested Linux runtime uses Docker Desktop's WSL 2 engine.
