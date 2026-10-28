# Central Server management implementation — 2026-10-28

Version 0.4 adds saved Local testing/Network server modes and an authenticated collector connection test. See the [network-mode report](network-mode-implementation-2026-10-28.md); it supersedes the same-PC-only limitation recorded below.

Version 0.3 adds the Windows management and collector handoff workflow requested for local testing. See the [operator guide](central-server-windows.md) for launch and setup steps. The earlier [collector/server evidence](collector-server-implementation-2026-10-28.md) continues to apply to the collection and ingestion design.

## Delivered behavior

| Requirement | Result |
|---|---|
| Separate Software 2 window | Native Windows GUI with server status, source registration and collector setup tabs. |
| Local lifecycle | Initializes separate PostgreSQL 17 storage, runs migrations, creates restricted runtime logins, starts verified loopback HTTPS API and worker; stops owned process trees and the selected central cluster. Data and IDs survive restart. |
| Safe process ownership | PID creation identities prevent targeting reused PIDs. Packaged components use independent runtimes; PostgreSQL uses its own DLL search path. Bootloader cleanup is allowed after child termination. |
| Registry | Create or reuse customer/site/project/machine entries; validate scope before registration; generate source/generation IDs and a collector credential; create draft mapping and audit entry. |
| Credential storage | Only SHA-256 verifiers in registry; recoverable upload credentials and local database passwords protected by Windows current-user DPAPI and private ACLs. |
| Collector handoff | Password-encrypted authenticated setup files with strict bounded format, source/generation IDs, destination, credential and optional CA. Export does not include source database access or extraction instructions. |
| Local import | Collector tab 3 imports the file, protects the credential locally, installs explicit CA trust, enables uploads and preserves source connection, password, history approval, limits, privacy and schedule. |
| State protection | Reject different assigned identities and incompatible pending batches; scheduler/cycle locks prevent live import; failed normal imports restore prior settings/credential bytes. Wrong passwords make no settings changes. |
| Replacement credential | Explicit creation, audited and exportable; prior credentials remain valid. Failed database operations restore the protected previous credential file. |
| Existing local data | Existing `LOCAL-SCADA` and generation retained; manager config selects existing local test storage. No new registry entry or SCADA database change was needed. |
| Packaging | Separate Central Server executable and Inno Setup installer; updated Collector installer with import. No external administration listener. |

## Verification

Final automated result: **159 passed, zero skipped** on the local Windows/Python 3.13/PostgreSQL 17 environment. Temporary Tk initialization failures during concurrent build runs were cleared and the complete final suite was rerun sequentially; the final result XML contains no failures.

The automated suite exercises real disposable PostgreSQL, DPAPI, Tk callbacks, authenticated handoff encryption, malformed/wrong-password rejection, registry parent scope, credential rotation, rollback, import identity/state locks and source-setting preservation. The acceptance result XML is `.tools/collector-acceptance-results.xml`. One existing Starlette/httpx test-harness deprecation warning remains; it does not affect these runtime checks.

The packaged executable is tested against an isolated cluster on port 55442 and HTTPS on 8444. The test initializes/starts the native components, registers a fixture source, exports and imports its encrypted setup, uploads a bounded fixture batch over verified TLS, receives a durable receipt, observes worker processing, stops all components, restarts and verifies the same source ID. The result is `.tools/manager-package-smoke/result.json`.

The real-history handoff test exported the existing source through ManagerService, imported into a separate temporary collector configuration, copied the protected existing source password under the same Windows account, and collected the approved current history. It staged 10 records in two reads, uploaded two batches, left zero pending/error state, and kept the central revision count at 10. The installed collector configuration bytes were unchanged. Detailed status is in `.tools/manager-real-handoff/*/result.json`; raw history and passwords are not included in that report.

All three management tabs and the collector import control were rendered and inspected. Native packaged window startup/closure is also checked. Release archives are checked for private configuration, credentials, databases, logs, handoff files and the literal existing upload token; SHA-256 sidecars accompany release artifacts.

## Remaining acceptance gates

This is the requested same-PC commissioning package. Exports use localhost; another PC needs commissioned networking, hostname and TLS. PostgreSQL 17 is an external prerequisite. Application windows are not Windows services, and unattended startup after reboot is not supplied by the manager.

The real alarm/event data is retained in quarantine pending an approved exact machine mapping and audited reprocessing. Mapping approval/reprocessing/generation recovery/revocation remain available through the existing server administration commands. No machine assignment was inferred from real data.

Customer Web Portal, OIDC, customer read APIs, analytics, Grafana and notifications remain later phases. Clean-account Windows service commissioning, clean Linux deployment/Caddy, off-server recovery and representative SCADA load/independence checks remain required before customer acceptance. The local builds are unsigned.
