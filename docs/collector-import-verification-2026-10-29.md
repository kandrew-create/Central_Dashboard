# Collector setup import and credential-status verification

## Reproduced issue

A saved local Collector configuration had no HTTPS destination. Turning **Enable uploads** on created an unsaved edit. Saving then failed because the URL was blank, while the previous GUI disabled **Import server setup** for any unsaved edit. This blocked the very import that supplies the URL. Separately, the upload-credential entry deliberately stayed blank after import, but the old screen had no clear indication that its protected credential had been stored.

## Behavior change

- Import remains available while idle and automatic collection is stopped. Pending edits to the IDs, HTTPS URL, upload enable flag and CA path no longer block import because these are the fields supplied by the selected setup file.
- Import operates on the last saved local configuration. Unsaved database/history/schedule edits and typed unstored database passwords are preserved by explaining that they must be saved/stored first. A new setup explains the required initial local save instead of silently disabling Import.
- The new credential-status text distinguishes no credential file, a present protected credential and a newly typed unstored credential. It never displays the saved secret. File presence is not proof of validity; **Test server** verifies unlock, identity scope, certificate and authentication.
- Busy operations and automatic collection still block import. Backend source/generation, pending-queue, scheduler-lock and rollback protections are unchanged.
- Server tests, credential storage and collection-status refreshes now replace in-progress footer text on completion. A successful test no longer leaves the footer saying “Testing…”.

## Executed checks

The actual exported `.linker-collector` file was imported through production Collector GUI callbacks with the real desktop service, Windows DPAPI and a private temporary setup. File/password dialogs were supplied locally; no database, source reader or upload-credential storage behavior was mocked. The imported IDs, HTTPS URL, enabled uploads and protected credential matched the authenticated encrypted bundle. The credential box was blank as designed while its protected file existed and decrypted correctly. **Test server** authenticated against the running Central Server successfully.

The rebuilt native `collector-gui.exe` was also opened with that private test configuration. Its **Collection & upload** tab showed **Protected upload credential found**, an enabled Import button and populated IDs. Clicking its actual **Test server** button completed successfully with verified certificate, accepted credential/source/generation and success text in both the section and footer. Collection remained disabled and no records were uploaded by these checks. The temporary GUI was closed afterward.

| Check | Result |
|---|---|
| Initial targeted GUI/import/connection/repository checks | 29 passed |
| Full suite, disposable PostgreSQL 17 | 201 passed, two desktop-display skips |
| Full suite, disposable PostgreSQL 18 | 202 passed, one desktop-display skip |
| Three skipped full-suite GUI checks rerun individually | 3 passed, zero skipped |
| Final targeted checks after completion-message changes | 28 passed, one desktop-display skip |
| Final skipped collection-controls check rerun individually | 1 passed, zero skipped |
| Actual encrypted file import and live authenticated HTTPS preflight | Passed |
| Rebuilt native Collector GUI credential preflight and displayed completion | Passed |
| Four Collector executables, Inno installer and generated checksum sidecars | Built and verified |

Each full suite emitted one Starlette/httpx deprecation warning. All database tests used separate disposable clusters. The live Central Server remained ready and no source database access or automatic collection was started by the import checks.

## Delivery

Install `dist/installer/Linker-SCADA-Collector-Setup.exe` on the SCADA PC after stopping automatic collection and closing its Collector. Existing settings/queue/credentials are retained. Reopen the existing local settings, import the encrypted setup file and use **Test server**. The setup-file password belongs only in the import password prompt; the upload-credential entry is for a manually supplied server-issued token.

Installer SHA-256: `d0b5921ec491df0bc6076b94b06013ba002589509201c9bf1ef5dddd35f74809`.

The SCADA PC installation and its Windows-account-specific import were not performed remotely. Only the encrypted setup file is intended for transfer; copying the temporary verification TOML/DPAPI files to another PC is not a credential migration. Published X1 release assets are unchanged.
