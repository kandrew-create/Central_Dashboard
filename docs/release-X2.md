# X2 — Collector import and Central Server commissioning fixes

Repository revision **X2**, application package version **0.4.0**. These Windows builds include the tested commissioning fixes described below. X1 remains available as an older release.

## Downloads

| Application | Install on | Download |
|---|---|---|
| SCADA Collector | Each SCADA PC | [Windows installer](https://github.com/kandrew-create/Central_Dashboard/releases/download/X2/Linker-SCADA-Collector-Setup.exe) · [SHA-256](https://github.com/kandrew-create/Central_Dashboard/releases/download/X2/Linker-SCADA-Collector-Setup.exe.sha256) |
| Central Server | Central server PC | [Windows installer](https://github.com/kandrew-create/Central_Dashboard/releases/download/X2/Linker-Central-Server-Setup.exe) · [SHA-256](https://github.com/kandrew-create/Central_Dashboard/releases/download/X2/Linker-Central-Server-Setup.exe.sha256) |

Collector installer SHA-256: `d0b5921ec491df0bc6076b94b06013ba002589509201c9bf1ef5dddd35f74809`.

Central Server installer SHA-256: `94efa398210ebb83431225f5d666b6a0e976d103f92dcfb48168c8f8003d971b`.

## Collector fixes

- Incomplete unsaved upload settings no longer disable **Import server setup**. The selected setup supplies IDs, HTTPS URL, upload enable flag and CA path while retaining the saved local database/history/schedule configuration.
- New setups explain the required initial local save. Unsaved local changes and unstored database passwords remain protected; scheduler, identity and pending-queue import checks are retained.
- A visible status distinguishes a present Windows-protected upload credential from an empty configuration or a newly typed unstored credential. The secret entry stays blank after import; **Test server** verifies authentication.
- Successful server checks, credential storage and collection-status reads replace their in-progress footer messages.

Stop automatic collection and close the Collector before upgrading. Reopen existing settings afterward, import the source's encrypted `.linker-collector` file using its setup-file password, then click **Test server**. See [Collector usage](../collector/README.md) and [import verification](collector-import-verification-2026-10-29.md).

## Central Server fixes

- PostgreSQL 17 and 18 support, automatic discovery for new setups, and matching binary/data major-version validation. Changing binaries does not migrate an existing database.
- Local listener availability checks before save/start, early detection of API/worker exits, and cleanup of newly started components after a failed start. A missing adapter does not prevent stopping the configured server.
- Upgrade shutdown before file replacement and Restart Manager handling of leftover executable locks. Stop-command failures block replacement; saved data is retained.
- Save confirmation survives the automatic health refresh. Pasted registration names with CR/LF/tab separators are normalized, and empty/overlength/control-character errors are distinct.

See [Windows commissioning](central-server-windows.md), [PostgreSQL compatibility](postgresql-18-verification-2026-10-29.md), [upgrade verification](central-server-upgrade-verification-2026-10-29.md), [startup recovery](startup-recovery-verification-2026-10-29.md) and [registration validation](registration-input-verification-2026-10-29.md).

## Verification and deployment scope

The full suite contained 203 tests after the Collector import changes. On disposable PostgreSQL 17, 201 passed and two desktop-display checks skipped; on PostgreSQL 18, 202 passed and one skipped. All three skipped checks passed separately. After the final footer-text changes, targeted GUI/import/connection/repository checks passed with one transient desktop skip that also passed separately. Each full suite reported one Starlette/httpx deprecation warning.

The actual encrypted setup imported successfully through production GUI callbacks with Windows DPAPI. The rebuilt native Collector GUI accepted the imported credential/source/generation over certificate-verified HTTPS and showed completion correctly. Central Server fresh initialization, migrations, HTTPS, repeated starts and negative startup/recovery cases were checked independently. Both installers and their checksum sidecars were built and verified. The [verification reports](collector-import-verification-2026-10-29.md) record the executed scope.

These are unsigned commissioning builds. Second-PC firewall/Tailscale connectivity, dedicated-account unattended service operation, representative customer SCADA load and off-server restore remain deployment acceptance checks. Customer portal/reporting, analytics, Grafana, OIDC and notifications remain later phases.

Collectors read their local SCADA database and initiate outbound HTTPS uploads. Central Server keeps separate central PostgreSQL storage. Runtime credentials, databases, private keys, local commissioning files and per-source encrypted setup files are not release artifacts.
