# Saved Local AI state and results

Central Server 0.6.2 loads its saved Local AI configuration and stored interpretations when the manager opens and whenever **5 Local AI** is selected. It also includes these results in the normal server refresh. Selecting the tab during another operation defers the read until that operation finishes. All reads run off the GUI thread.

The earlier display initially showed no saved results until **Refresh interpretations** was clicked. **Enable local AI** also refreshed them, which made it appear that AI needed enabling again. The enabled setting was already persisted in the private Central data folder, and background alarm inference continued independently of that window.

**Enable local AI** and **Disable** change processing settings. Opening the window, selecting the tab and **Refresh interpretations** only read saved settings/results; they do not enable AI, call the model or create SCADA revisions. Results saved while AI was enabled remain viewable when it is disabled. With PostgreSQL stopped, the saved setting/model are still shown and the tab explains that Central Server must start to load its stored results. A model typed but not yet enabled is preserved across automatic reads.

An AI settings/read failure is displayed in the AI tab without replacing a successful server-settings save confirmation or the normal server-health result. Original alarm/event records, equipment identifications, source names, queue behavior and approved mappings are unchanged. There is no database migration.

The local 0.6.2 package is separate from published revision X3 (0.6.1). Earlier release installers and checksums remain unchanged.

## Verification — 2026-10-30

The targeted GUI/configuration/validation/repository suite passed 40 checks with two Windows desktop skips; both skipped checks passed on targeted desktop reruns. Coverage includes constructor loading of saved state/results, disabled-state viewing, tab selection during other work, stopped-database configuration reads without a connection, preservation of an unsaved model, and optional AI failures preserving successful settings-save feedback. This display fix changes no SQL schema, upload protocol or queue behavior; the PostgreSQL 17/18 database suites were not repeated for it.

A read-only check against the live Central database opened the production manager twice and selected its AI tab. Both openings automatically showed the saved state and all ten stored interpretations. Enable, Disable and model-check calls were blocked and remained unused; the saved AI configuration fingerprint was unchanged.

Built and installed the verified 0.6.2 executable/installer with matching SHA-256 sidecars and retained local packages under `dist/releases/X3-local-0.6.2`. The installer stopped the configured Central Server before replacing files, and the server returned API/database/worker readiness. All ten original payload/identification fingerprints, registry identities, native table/schema OIDs, nineteen internal tables, native fields, saved settings and protected credentials were preserved. The existing migration head remains `0009_source_schema_names`; no new migration was applied. Protected pre-upgrade backups and published X3 packages remain intact.
