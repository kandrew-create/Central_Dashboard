# X3 — Central Server 0.6.1 equipment identification and source tables

Repository revision **X3** contains Central Server **0.6.1** and Collector **0.4.0**, with upload protocol v1. Earlier X1/X2 releases remain available.

## Downloads

| Application | Install on | Download |
|---|---|---|
| SCADA Collector 0.4.0 | Each SCADA PC | [Windows installer](https://github.com/kandrew-create/Central_Dashboard/releases/download/X3/Linker-SCADA-Collector-Setup.exe) · [SHA-256](https://github.com/kandrew-create/Central_Dashboard/releases/download/X3/Linker-SCADA-Collector-Setup.exe.sha256) |
| Central Server 0.6.1 | Central server PC | [Windows installer](https://github.com/kandrew-create/Central_Dashboard/releases/download/X3/Linker-Central-Server-Setup.exe) · [SHA-256](https://github.com/kandrew-create/Central_Dashboard/releases/download/X3/Linker-Central-Server-Setup.exe.sha256) |

Use the installer for the destination PC. Central Server upgrades stop the configured server before replacing files and preserve its data/settings/credentials; reopen the manager and start it afterward. Start applies migrations only to the separate Central database. Collector updates preserve local configuration and queued batches. Packages are unsigned commissioning builds. Follow [Windows commissioning](central-server-windows.md) and the verification scope below.

## Changes and operation

Version 0.6.1 uses the registered SCADA PC/source name for each schema, containing exactly two physical tables: `alarmhistory` and `eventhistory`. Migration `0009_source_schema_names` renames the earlier numbered schemas in place and uses source labels for new registrations, with safe identifier-length and collision handling. Native values, equipment identification and saved content revisions remain available. Internal history and the earlier browsing views remain preserved. See [simple pgAdmin browsing](pgadmin-browsing.md) and [transactional storage details](source-table-layout.md).

Central Server can extract equipment labels such as `Oven 1` and `MUA 1` from native alarm messages/tags using an installed local Ollama model. Events use the **machine tag entered in Register SCADA source**, without interpreting `ev_message` or `ev_source`. In **5 Local AI**, select the installed model, choose **Enable local AI**, and use **Refresh interpretations** to inspect results. Disabling stops new alarm inference after the current bounded operation finishes; event identification continues without AI. Closing the manager leaves background identification running with the server.

**Suggested** means AI proposed an alarm equipment name for review. **Registered** means an event uses its configured registered machine tag directly. Event identity comes from the single authorized machine recorded with the accepted upload, resolved within the source's customer/site/project. Zero or multiple authorized machines remain uncertain; the application does not guess from message text. These identification results remain separate from approved reporting mappings.

Version 0.5.2 corrects extraction of equipment versus alarm condition: **Conveyor VFD Connect Error → Conveyor VFD**. A returned name cannot end in a recognized alarm-condition phrase such as `Connect Error`, `fault` or `high temperature`. Such answers remain uncertain instead of being accepted merely because they occur literally in the text. Selecting a result displays its original message for comparison. Migration `0006_alarm_names_v2` rechecks earlier alarm suggestions with policy `equipment-names-v2`; it does not rewrite source messages, registered event tags or saved SCADA revisions.

The **Batches awaiting machine mapping** count is separate from runtime errors and AI name suggestions. A healthy server can still show this count while mappings await approval; better extraction does not silently approve machine identities or clear that review queue.

Install Ollama on the central PC and download `qwen3:4b` (or another compatible local structured-output model). Disable Ollama cloud features with `OLLAMA_NO_CLOUD=1` or `disable_ollama_cloud: true` in its server configuration, then restart Ollama. The application uses only `127.0.0.1:11434`, ignores environment proxies, follows no redirects and has no cloud fallback. Model downloads require Internet access; inference uses the downloaded model. See [Ollama local-only configuration](https://docs.ollama.com/faq#how-do-i-disable-ollamas-cloud-features) and [structured generation](https://docs.ollama.com/api/generate).

Inference uses CPU execution for compatibility with older Windows graphics hardware. Each returned name must occur verbatim at a word boundary in an allowed source field. Empty, multiple-name, truncated or unverified model answers are uncertain and require review. Transport failures and malformed API responses use a generic error and bounded retries. No self-reported confidence percentage is treated as proof. Prompt injection defenses and evidence validation reduce errors; suggestions still require review and are not verified machine identities.

AI suggestions live in `platform.machine_interpretations`, with model digest, interpretation-policy version, status, evidence field and audit reference. The existing `platform.alarm_event_revisions` remains unchanged. AI never approves machine mappings, changes credential scopes, creates machines or clears quarantine. An approved mapping and normal reprocessing remain necessary for authoritative machine assignments. AI faults do not block durable upload acceptance, normal batch processing or the GUI.

Migration `0004_machine_interpretation` queues existing saved revisions once; subsequent new records are queued during normal processing. Migration `0005_registered_event_machine` requeues earlier event identifications for direct registered-tag lookup without changing native records or alarm interpretations. Replayed unchanged content does not create extra identification jobs or saved SCADA versions. The queue is tenant-scoped, leased and restartable; expired leases can be reclaimed. SQL permissions do not grant the reporting reader access to raw text or suggestions. Only alarm message/tag fields enter the local prompt; event fields and operator identity/comment fields are excluded. Source text and model responses do not enter application logs.

Upgrade using the rebuilt installer. It stops the configured server before replacement and retains its data, setup files and credentials. Starting the updated server applies the new migration only to its separate Central Server database. Start Ollama independently, enable local AI and refresh the results. Never run migrations or AI on a SCADA source database.

## Initial 0.5.0 verification — 2026-10-30

- Disposable PostgreSQL 17: 223 checks passed; fresh initialization, Alembic upgrades/downgrades, HTTPS health and repeated startup passed.
- Disposable PostgreSQL 18: 222 passed, one Windows/Tk desktop check skipped; that check passed separately on rerun. Fresh initialization, migrations, health and repeated startup passed.
- Real local `qwen3:4b` model: Oven 1 and MUA 1 identified with exact source evidence; the multiple-machine and generic-alarm examples remained uncertain. The model digest was `359d7dd4bcdab3d86b87d73ac27966f4dbb9f5efdfcc75d34a8764a09474fae7`.
- Six adapter checks cover evidence boundaries, invented labels, malformed/oversize responses, truncated generation, cloud-model rejection and exclusion of operator identity/comment fields. PostgreSQL integration checks cover AI failures, replay, retained raw data, unchanged revision counts and tenant scope.
- The Central Server 0.5.0 executable and installer were rebuilt with matching SHA-256 sidecars. Earlier local 0.4.0 packages were retained under `dist/releases/X2-local-0.4.0`; published GitHub X2 assets are unchanged.
- Installed the tested 0.5.0 bytes, applied `0004_machine_interpretation` to the saved Central Server data folder, and restored API/database/worker readiness. Saved settings and protected credentials matched their pre-upgrade checksums; all 10 original payloads matched their pre-upgrade fingerprints.
- Enabled the local model and verified the installed background worker processed all 10 existing records: nine have equipment-name suggestions and one is uncertain. The saved SCADA revision count remains 10. Model results did not clear the two batches awaiting approved mapping. The local release artifacts are archived under `dist/releases/X3-local-0.5.0`; X3 has not been published to GitHub.

The existing Starlette/httpx deprecation warning remains unrelated to this change. These checks do not replace representative customer-message evaluation or production commissioning.

## 0.5.1 verification — 2026-10-30

Disposable PostgreSQL 17 and 18 each passed 225 checks with one Windows/Tk desktop skip per run. Both skipped checks passed on rerun. Fresh server initialization, migration upgrade/downgrade, HTTPS health and repeated startup passed on both versions. New checks verify that events use the registered `LINE-01` fixture tag despite different equipment names in their native message/source fields, make no model request, still identify with alarm AI disabled, and stay uncertain when more than one machine is authorized. The adapter also refuses to send event fields to the model. No SCADA schema or upload-protocol change is required.

Built and installed 0.5.1 with verified SHA-256 sidecars and installed bytes, then applied `0005_registered_event_machine` to Central storage. The stored event now has status `registered`, policy `registered-event-machine-v1` and no AI model. All 10 original payload fingerprints, nine alarm-interpretation fingerprints, saved settings, protected credentials and local-AI configuration were unchanged. The API, database and worker returned ready. Local artifacts are preserved under `dist/releases/X3-local-0.5.1`; GitHub X3 remains unpublished.

## 0.5.2 verification — 2026-10-30

Operator feedback exposed a semantic validation gap: six earlier suggestions were complete alarm descriptions, even though the text-evidence check passed. A literal match alone is not an accuracy test. The prompt now distinguishes equipment names from conditions, includes the operator's `Conveyor VFD Connect Error → Conveyor VFD` example, and rejects suggestions ending in recognized alarm-condition phrases.

Nine adapter checks passed, including rejection of condition-only names. Disposable PostgreSQL 17 passed 229 checks with one Windows/Tk desktop skip that passed on rerun; PostgreSQL 18 passed all 230 checks. Migration/backfill, preserved original payloads, event-tag behavior and original-message comparison were covered. Fresh initialization, migration upgrade/downgrade and repeated startup passed for both versions.

A local shadow run on the nine saved alarms changed no stored data: all nine produced suggestions, none was an entire alarm description or ended in a recognized alarm condition, and the supplied Conveyor VFD example matched its expected name. These checks validate the reported failure and structural guards; the remaining names still need operator review for semantic correctness.

Installed the verified 0.5.2 executable and applied `0006_alarm_names_v2` in Central storage. All nine alarm suggestions were recomputed under `equipment-names-v2`; the reported Conveyor VFD record now identifies `Conveyor VFD`, with zero entire-description or condition-suffix labels. All 10 original payload fingerprints, the registered event identification, saved settings, protected credentials and AI configuration were unchanged. API/database/worker returned ready with no runtime error. The interpretation-tab data path returns all 10 rows and original messages successfully. Local artifacts are archived under `dist/releases/X3-local-0.5.2`; previous local packages and published X2 assets remain intact.

## 0.5.3 verification — 2026-10-30

The user selected simpler pgAdmin browsing with all data preserved. Migration `0007_log_browsing_views` adds only the `logs` schema and two non-materialized, read-only views; internal storage remains in `platform`. PostgreSQL 17 passed 231 checks with one Windows/Tk desktop skip passed separately on rerun; PostgreSQL 18 passed all 232 checks. New checks cover original native strings and fields, view row counts, registered event identification, non-updatability, invoker security, tenant isolation and prevention of reporting-reader access to raw personal fields. Fresh initialization, migration upgrade/downgrade and repeated startup passed on both versions.

Installed verified 0.5.3 bytes and applied the migration only to the saved Central Server database. All 18 internal tables, original payload fingerprints, identification fingerprints, settings and protected credentials were preserved. Each native view field was compared with its stored original value; the views show nine alarms and one event. API/database/worker returned ready. Local artifacts are retained under `dist/releases/X3-local-0.5.3`.

Backed up the pgAdmin profile privately under `%APPDATA%/pgAdmin/linker-backups`, then restricted only the Linker Central Server registration to database `scada_platform` and schema `logs`. Other registrations and credential-command settings were verified unchanged. Refresh **Schemas** in pgAdmin to apply the browser display; clear **Schema restriction** to restore the full internal browser. No records were deleted or moved, no source database was touched, and published X2 assets remain unchanged.

## 0.6.0 verification — 2026-10-30

The source layout now uses physical tables under stable per-source schemas. Disposable PostgreSQL 17 passed 237 checks with two desktop skips; PostgreSQL 18 passed 238 checks with one desktop skip. All three distinct skipped checks passed together on a desktop rerun. Fresh manager initialization, migration upgrades/downgrades, HTTPS health and repeated startup passed on both versions. New coverage includes existing-data backfill, source registration/deletion, real table types, unchanged replay, changed-content revisions, native field values, direct-edit rejection, tenant policies, private function/role isolation, transactional failure/retry and concurrent mapping/identification updates.

Built and installed 0.6.0 with verified executable/installer SHA-256 sidecars; archived matching packages under `dist/releases/X3-local-0.6.0`. Before upgrading, created a private encrypted Central database archive, validated its archive listing and encryption round trip, and backed up saved settings, protected credentials and the pgAdmin profile. The database archive and its DPAPI-protected restore key remain in the private Central data folder; restoration requires the commissioning Windows account. No plaintext database dump was written to disk.

The installed server applied `0008_source_tables` to its existing Central storage and returned API/database/worker readiness. `SCADA_PC1` contains exactly two real tables: nine alarm rows and one event row. Every native field was compared with its stored original value. Original payload/identification fingerprints, registry identities, credentials and settings were preserved; all 18 prior internal tables remain, with one new internal source-storage registry. The two batches awaiting approved machine mapping remain unchanged and there are no failed jobs.

The Linker pgAdmin connection now restricts its browser to `scada_platform` and `SCADA_PC1`, with a saved tree path to its Tables collection. Other registrations and credential-command fields were verified unchanged. An already-open pgAdmin browser may retain its previous tree until **Schemas → Refresh** or a normal reopen; it was not force-closed when a normal close request left it open. Internal tables and earlier `logs` views remain available to authorized SQL but hidden from this connection's schema tree. Collector packages, SCADA source databases and published X2 assets are unchanged.

## 0.6.1 verification — 2026-10-30

Schema names now come from registered SCADA PC/source labels. Existing schemas are renamed in place, and new registrations allocate their labeled schema transactionally. Administrative label changes rename the schema without rewriting records. Exact names are retained within PostgreSQL identifier limits; reserved names, commas and collisions receive the documented safe adjustments without changing registered labels or merging source identities.

Disposable PostgreSQL 17 passed 239 checks with two desktop skips; PostgreSQL 18 passed 240 checks with one desktop skip. All three distinct desktop skips passed on rerun. Both versions passed fresh initialization, migration upgrade/downgrade, HTTPS health and repeated startup. Tests verify in-place schema/table identity, raw content, replay after renaming, duplicate names across registrations, quoted labels, reserved names and UTF-8 length limits. The existing unrelated Starlette/httpx warning remains.

Built and installed 0.6.1 with matching executable/installer SHA-256 sidecars and archived packages under `dist/releases/X3-local-0.6.1`. A fresh encrypted Central database backup and private pgAdmin profile backup were verified before upgrading. Installed migration `0009_source_schema_names` preserves all ten original payload/identification fingerprints, registry identities, native table/schema OIDs, nineteen internal tables, native field values, settings and credentials. The active schema exactly matches its existing registration and retains nine alarm rows and one event row. API/database/worker are ready with no failed jobs; mapping-review counts remain unchanged.

Updated only the Central pgAdmin connection's schema restriction and saved tree path to the registered source schema; other registrations and credential-command fields were preserved. Refresh **Schemas** in an already-open browser to load the renamed schema. Earlier packages and published X2 assets are unchanged, and no SCADA source database was modified.

## X3 release packaging

The X3 Central Server installer is the same verified 0.6.1 build installed locally. The Collector 0.4.0 executable set and installer were rebuilt for this release; Collector application behavior is unchanged. Both installers have matching SHA-256 sidecars, and local release copies are retained under `dist/releases/X3`. Runtime databases, credentials, keys, source setup exports and PC-specific helpers are excluded from Git and release assets.

Central-Server installer SHA-256: `7fd7d1e37e0c06d2a7f9b6fb04e9c491da222c1de9da414be9dde9d115f45f98`.

SCADA-Collector installer SHA-256: `d0b5921ec491df0bc6076b94b06013ba002589509201c9bf1ef5dddd35f74809`.
