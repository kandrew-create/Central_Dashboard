# Alarm equipment suggestions and overrides

Alarm analysis shows **Equipment** beside **AI suggestions - unverified**. Existing saved suggestions appear even when an alarm has uncertain timestamps/revision ordering, provided the saved original message and tag match the displayed alarm. The time/order warning stays visible; an equipment suggestion never establishes a latest machine state or fault cause. Report reads use saved results and never call a model or change the saved AI choice.

## Edit equipment

1. Open **Alarm analysis**, load the desired customer/source/time scope and select an alarm group.
2. Choose **Edit / override equipment**. The editor shows the source, tag, read-only original message and original saved AI suggestion.
3. Enter the corrected equipment name and select **Save override**. The Equipment column shows the user label; the saved AI suggestion remains alongside it for comparison.
4. To remove the correction, reopen the editor and select **Use AI again**. This restores the saved AI display without running the model.

The AI controls follow confirmed saved state: **Enable local AI** is gray and disabled while AI is enabled; **Disable** is disabled while AI is off. Both wait while settings are loading or an operation is running. A failed enable leaves Enable available to retry. To change the active model, Disable AI, edit the model entry, then Enable it; an unsaved model entry is retained through status refreshes.

Edits apply to the exact customer/source/tag/message condition, including future matching alarms and source generations. Different sources or messages retain independent labels. A human label is a display correction, not a machine UUID, credential authorization or mapping approval. No original SCADA fields, alarm timestamps/milliseconds, receipt, content hash or saved AI candidates are rewritten.

The editor requires an original message or tag and matching retained evidence. A row with unresolved conflicting messages cannot borrow another group's label or be edited as though its original condition were known. Empty/overlength/control-character names are rejected; pasted line separators are folded to spaces. The limit is 255 characters. If saving fails, entered text stays in the editor. An open editor blocks parent-window closure and pauses automatic display refresh. Saves run outside the GUI thread. A stale version is rejected rather than overwriting a newer edit; cancel/refresh/reopen to review that change before resubmitting.

## Storage and security

Central-only migration **0016_equipment_overrides** creates `platform.alarm_equipment_overrides`, keyed by customer, source and a SHA-256 key of the exact nullable tag/message pair. Matching original tag/message evidence is checked before saving. The table enforces source/customer foreign keys, forced customer RLS and label checks. Saves and clear operations append the previous/new label and version to Central audit history. Clearing stores a NULL-label versioned tombstone, so an older editor cannot silently recreate a cleared correction.

Only the trusted local management path exposes editing, using stdin-only scoped Docker management requests; no network administration endpoint is added. The registry capability may edit its customer rows. API/worker/reader capabilities receive no override write privilege. AI continues writing only its separate saved interpretations and cannot replace human labels. Source/customer/generation authentication and retired mapping behavior remain unchanged.

The current Qt WSL/Docker manager has one Alarm analysis page for equipment review, original-message evidence, AI suggestions and manual editing. The separate Equipment identification tab is removed. Expand AI settings on Alarm analysis to change the model or Enable/Disable AI; reading settings or opening the panel never calls a model or changes its saved enabled state. The original per-record AI results remain stored. Stored warehouse facts keep their existing conservative latest-state fields; the live analysis overlay supplies evidence-matched suggestions and user equipment labels without changing those facts. The normal reporting SQL views retain their existing layout. A new read API or model-training feedback loop is not introduced.

Upgrade with matching local manager/backend images and Alembic through 0016 on Central storage only. Stop the configured project before code replacement and retain an encrypted, restore-verified backup. Downgrading 0016 removes current override rows while retaining audit history; exact recovery of labels requires the pre-change backup. No Collector upgrade or SCADA source write is needed.

## Local deployment evidence - 7 November 2026

Central migration 0016 and its matching equipment editor were deployed to the existing `linker-scada-wsl` project after a full encrypted PostgreSQL backup restore and candidate migration on an isolated tmpfs PostgreSQL 17.6 container. Every pre-existing Central table fingerprint, database identity, source/generation/credential/scope, originals/receipts, AI results, settings/CA/vaults and named volumes matched. The backup/key, prior code and private diagnostics remain in mode-0700 `~/central-server/secrets/equipment-editor-20261107`, outside Git, with key files mode 0600. No real equipment correction was invented for verification.

The user's follow-up removed the duplicate Equipment Identification page. A matching five-page Qt interface was deployed with no further schema change. A second encrypted full restore and exact pre-start table comparison included the override table, so existing corrections would be retained. Its protected backup/evidence is in `~/central-server/secrets/unified-analysis-20261107`. At verification, **eight batches and 81 saved versions** were present: **24 alarm occurrences and 57 events**, with zero mapping quarantine. Later legitimate uploads can increase these counts. Original records/receipts, AI state/results, identities, credentials, settings and named volumes remained preserved.

Live backend/UI checks showed **11 recurring alarm groups with saved AI suggestions**, including alarms with uncertain source ordering. The actual Qt window had five pages, no identification-results table, a working AI settings panel in Alarm analysis, an enabled editor for an evidence-matched selection and a prefilled equipment name. The editor was canceled without saving. The saved AI enabled/model choice matched before/after. Existing pgAdmin login/reconnect, warehouse counts, fixed-customer isolation and denied writes/credentials/raw payload/role switching passed. Windows verified the saved HTTPS CA and unauthenticated ingestion remained rejected. API/database/worker were ready and the normal manager was reopened.

Executed checks:

- Full disposable PostgreSQL 17 and 18 regression runs: **153 passed and seven Linux-only skips on each**.
- After tightening conflicting-message evidence matching, focused override/warehouse runs on fresh PostgreSQL 17 and 18: **29 passed on each, no skips**.
- Isolated Linux container/disposable PostgreSQL 17.6: **32 passed, no skips**, including the eight override tests, replay/security, frozen migration history and Linux vault/agent checks.
- Revised five-page Qt interface against isolated source: **30 passed, no skips**, covering source-scoped save/clear, failure input retention, protected close, uncertain evidence, background I/O, configuration-only AI reads, no enable on refresh, unsaved model entry and persistent feedback/footer.
- Windows Docker-manager/GUI checks: **19 passed**. Windows lacks the optional Qt dependency; the Qt checks were executed in WSL.
- Git whitespace and Central Compose template checks passed. Existing Starlette/httpx deprecation warnings remain.

No Collector/source database change, separate VMware migration, published package rebuild, Git push, actual remote-PC recommissioning, cold reboot or production load test was performed. The current desktop received the updated source/images; published installers retain their earlier interface until separately rebuilt.

## AI button state follow-up

At the user's request, Enable local AI now stays gray/disabled once the saved enabled state is true. Disable is unavailable when the saved state is false; unknown/busy states disable both. Unrelated refresh/work cannot re-enable an already enabled action, direct repeated requests are guarded, failed enables remain retryable and unsaved model entries remain intact. A scoped style renders the disabled Enable button gray without changing other primary actions.

The local interface/images were updated without schema changes after protected backup/full disposable restore and preservation checks. Eight batches/81 versions, existing overrides/AI results, identity/credentials, settings/CA/vaults and named volumes matched. The live Qt check loaded the actual enabled choice, confirmed Enable disabled/Disable available, sampled the rendered gray background (`#f4f6fa`) and verified the saved model/enabled state was unchanged; it did not invoke a model or toggle AI. API/database/worker are ready and the manager reopened.

Focused verification: **33 isolated WSL Qt tests passed**, including confirmed-state transitions, duplicate-click suppression, successful Disable reversal and failed-enable retry; **19 Windows Docker-manager/GUI checks passed**. No database/protocol behavior changed, so the earlier PostgreSQL integration evidence remains applicable without repeating the full matrix. Backup/evidence is protected under `~/central-server/secrets/ai-button-state-20261107`; keep recovery keys outside Git. No Collector/SCADA/VMware, release-package or Git-push changes.
