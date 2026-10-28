# Network settings and testing modes — version 0.4

The Windows package now supports the requested Local testing and Network server configurations. Setup instructions are in the [Windows operator guide](central-server-windows.md). Earlier 0.3 documentation describes the local-only starting point; this report supersedes that limitation.

## Implemented

- Central Server **4 Connection & mode** selects Local testing (one PC) or Network server (two PCs), HTTPS listen IPv4, central PC hostname/IPv4 and HTTPS port. The form previews the collector upload URL. Save/start/export reject unsaved or invalid configurations. Changing active settings requires stopping the selected server first.
- Local testing remains the default and uses `127.0.0.1` / `localhost`. Network mode presets `0.0.0.0` and requires a reachable hostname/IPv4; it rejects loopback and unspecified destination addresses. A specific adapter IPv4 can be selected instead of all adapters.
- Runtime settings propagate to the API, readiness checks and worker child processes. Central PostgreSQL always binds loopback, independently of the HTTPS listener.
- Managed certificates cover the advertised hostname/IPv4 and local health-check address. Private CA signing material is retained for normal renewal/address changes, so leaf renewal does not require replacing collector CA trust. Existing valid local certificates are preserved. Export refuses stale/mismatched certificate material.
- Encrypted collector setup exports contain the selected network URL and CA. Imports continue to preserve source database access, history approval, privacy, limits and schedule. Source/generation IDs are independent of a destination-address change.
- Collector **Test server** performs a bounded authenticated HTTPS preflight. `/v1/collector-check` verifies the credential-derived source scope and active generation and returns a fixed identity/status response. No alarm/event data, receipt, job, audit entry or checkpoint is created by this test. No server-supplied configuration or extraction instruction is accepted.
- Caddy's POST allowlist includes the preflight route for the separate Linux deployment. There is no remote management API.
- Both Windows installers are version 0.4.0. Operating guides cover firewall/hostname setup, fresh registry versus migration, mode switching and matching package versions.

## Verification

Final automated suite: **170 passed, zero skipped**, with one existing Starlette/httpx test-harness deprecation warning. Temporary Tk initialization skips in an earlier concurrent run were cleared by the complete sequential rerun. Results are in `.tools/collector-acceptance-results.xml`.

Automated tests cover settings v1 compatibility/v2 round trips, invalid network addresses, certificate names and retained CA, local/network setup exports, cross-customer scope, invalid/retired generation, invalid credential, oversized or extra-field preflight requests, bounded response validation, no-upload behavior and GUI controls.

The isolated network smoke test uses a private non-loopback interface on this PC, port 8445 for HTTPS and a separate PostgreSQL cluster on loopback 55443. It never reads or modifies the real SCADA database. It exercises both development components and the packaged Central Server executable:

1. Start Network mode bound to the selected private adapter.
2. Register an isolated fixture source, export/import its encrypted setup and verify the exported network destination.
3. Authenticate the collector preflight over verified HTTPS; reject an incorrect TLS hostname.
4. Upload one bounded fixture batch and obtain a durable receipt.
5. Stop the server, attempt another upload and verify its immutable pending payload remains queued.
6. Restart with the same source identity, recheck credentials, deliver the pending batch and verify two unique revisions with no failed jobs.
7. Stop all isolated components and retain their fixture database for repeatability.

Reports are `.tools/network-server-smoke/development-result.json` and `packaged-result.json`. The existing real local server was restarted into the updated API without changing its source IDs or 10 stored revisions; the installed collector configuration passed the new authenticated preflight. Its local mode was retained.

GUI controls are rendered and inspected. The full acceptance suite uses disposable PostgreSQL databases and real Windows DPAPI/Tk checks. Release checks inspect nine artifacts for private operational data and write SHA-256 sidecars.

## Practical limits

The actual second PC is not connected in this session. Its hostname resolution, firewall/network route and end-to-end behavior must be checked using the packaged **Test server** and a bounded real upload when available. Firewall rules are not added automatically. The non-loopback interface test proves this package's network path on the current PC; it does not assert that another PC's network is commissioned.

New generated certificates are for commissioning with explicit private-CA trust, not a replacement for production TLS/hardening policy. Windows service startup/reboot/account commissioning, clean Linux deployment, off-server recovery and representative SCADA load checks remain separate gates. Machine mapping approval and customer portal/reporting are unchanged.
