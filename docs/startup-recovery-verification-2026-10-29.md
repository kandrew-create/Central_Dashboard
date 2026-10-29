# Startup failure prevention and feature recheck

## Repeated failure

The saved listener had again been set to the collector PC's address, `100.111.65.53`. This server's Tailscale address is `100.111.173.111`. The installed API exited with a bind error, while the older startup loop kept polling. The server and collector address fields had been confused; the UI previously accepted an address absent from this PC.

The configured central components were stopped, only the listener was corrected, and the installed application restarted successfully in **11.79 seconds**. This preserved the dedicated PostgreSQL 18 database and all saved credentials/settings. The stale manager window was closed normally so that it could not write the old listener back.

## Changes

- Saving or starting probes the listener address with an ephemeral local bind. Unavailable addresses get a specific explanation before settings replacement, credentials creation, database initialization or component launch.
- Loading an old unavailable listener remains allowed so the operator can repair it. Stopping deliberately skips listener availability checks, so a disconnected adapter cannot prevent shutdown.
- Stopping a new, uninitialized setup creates no directory/log files that would later prevent initialization.
- Startup detects an exited API or worker and cleans up the components it launched. A failed start retains its database and credentials for recovery.
- Readiness requires the expected JSON health response. Expected startup errors remain actionable in component logs; unexpected errors still hide native/credential-bearing details.
- The connection form explains that the listener belongs to the server and collectors connect outward using their imported setup.

## Full suites and packaged checks

| Check | Result |
|---|---|
| Full suite, disposable PostgreSQL 18.6 | 192 passed, zero skipped |
| Full suite, disposable PostgreSQL 17.11 | 191 passed, one desktop-display skip |
| Skipped GUI health-refresh check rerun individually | 1 passed, zero skipped |
| Fresh initialization, migrations, verified HTTPS, repeated start on both source versions | Passed |
| Rebuilt frozen executable on PostgreSQL 17, including stop/start | Passed |
| Rebuilt frozen PostgreSQL 18 Network-mode workflow checks | Nine groups passed |
| Actual unavailable local listener, save and start | Rejected in 0.002 seconds, without settings/data writes |
| Occupied HTTPS port | Failed in 21.92 seconds including first initialization; new API/worker were cleaned up, unrelated listener retained |
| Same data after releasing the HTTPS port | Started successfully in 13.08 seconds with identical protected credentials |

Each full suite emitted one Starlette/httpx deprecation warning. The nine rebuilt-executable workflow groups covered registration/catalog, encrypted setup export/import, DPAPI credentials, authenticated HTTPS preflight, read-only source previews, actual fixture collection/upload and durable receipts, unknown-mapping quarantine, approval/reprocessing, background worker completion, credential rotation, offline queue retention/retry, source preservation and unauthenticated-request rejection. The selected rebuilt executable was used; the helper script's default installed-executable path was overridden for these checks.

All test clusters and fixture data were isolated under ignored `.tools/` paths with separate ports. No SCADA/customer database was modified. The live registry still required real source commissioning; second-PC connectivity, firewall/Tailscale access, dedicated-account unattended service operation and representative customer load remain separate acceptance checks.

The executable/installer build completed and its SHA-256 sidecars were verified. Windows administrator approval was granted and the verified installer completed successfully. The installed Program Files executable matched the rebuilt executable SHA-256: `d5a521343b4101fcffe44e1f52806da347e263ed67e21ee97aee09a2fb6ea737`.

The updated installed application then started the configured server in **13.26 seconds** with API Ready, PostgreSQL Ready, Worker Running and no reported error. The live registry remained empty (zero sources, batches and revisions). Its listener and collector-facing server host were both `100.111.173.111`; PostgreSQL remained the dedicated local version-18 cluster on port 55441. The updated manager was reopened for the operator. See [Windows settings and recovery](central-server-windows.md) and [earlier current-PC verification](pc-feature-verification-2026-10-29.md).
