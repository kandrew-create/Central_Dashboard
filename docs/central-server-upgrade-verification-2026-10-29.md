# Central Server installer upgrade verification

An installed PyInstaller launcher remained alive after its GUI child exited. Its executable was still locked, and the previous installer could not close it automatically. The observed leftover process had the exact installed Central Server executable path, no component arguments and no child processes. It was closed individually; unrelated PostgreSQL processes were not stopped.

## Installer changes

- `PrepareToInstall` invokes the installed `central-server.exe --component stop` when the selected installation and common manager settings file exist. A launch error or nonzero result blocks installation before file replacement.
- `CloseApplications=force` lets Windows Restart Manager close remaining processes locking the destination `central-server.exe`, including a windowless leftover launcher. The filter is limited to that executable; no process-name-wide termination or PostgreSQL service shutdown is used.
- `RestartApplications=no` keeps the server stopped after replacement. Reopen the manager and start it when ready.
- The server build regenerates SHA-256 sidecars for both generated binaries, preventing an old downloaded checksum from describing a newly rebuilt installer.

Save unsaved GUI edits before upgrading. In interactive Setup, accept the automatic-close option. Operational data is not included in the installer payload and is retained. The installed stop command uses the saved Central Server settings; use the Windows account that manages that installation. This does not change uninstall behavior or add unattended services.

## Executed verification

The production installer compiled successfully with Inno Setup 6.7.3. Its Central Server executable was unchanged from the PostgreSQL 17/18 build that passed [database and packaged lifecycle verification](postgresql-18-verification-2026-10-29.md).

A disposable, per-user copy of the same installer script was compiled to exercise its real Pascal shutdown hook and Restart Manager behavior without touching the installed application, registry registration, shortcuts or databases. Only test isolation settings were substituted: application ID, install/output paths, privileges, uninstall registration, icon creation and manager-settings path. The payload was the actual rebuilt Central Server executable. A compiled windowless old-program fixture held its own executable open and accepted the same stop-command arguments.

| Scenario | Result |
|---|---|
| Fresh install, no old executable | Passed; no stop command attempted and installed payload hash matched |
| Old stop command returned an error | Passed; upgrade failed before replacement/automatic closing, and old bytes/process and state markers remained intact |
| Old executable remained running after a successful stop command | Passed; stop command ran, Restart Manager closed the lock holder, replacement hash matched, and saved-state markers remained intact |

All three checks ran without skips. The disposable test process was stopped afterward. These checks verify installer behavior with the lock-holder fixture; they do not claim an automated upgrade of the user's active server installation.

Current installer: `dist/installer/Linker-Central-Server-Setup.exe`. Verify it against its adjacent `.sha256` file. Published X1 release assets are unchanged.
