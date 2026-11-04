# Shared warehouse and legacy source tables

Current Central storage uses three fixed schemas:

| Schema | Objects and responsibility |
| --- | --- |
| `platform` | Authoritative registrations, generations, upload receipts, original alarm/event revisions, mappings, jobs and audit history. |
| `warehouse` | Stored `fact_alarm_occurrence` and `fact_event_occurrence`, shared live dimension views and durable refresh queues. |
| `reporting` | Maintained `alarm_hourly_summary`, `alarm_daily_summary`, `equipment_alarm_summary`, `source_upload_summary` and a dirty-day queue. |

Migration `0011_stored_warehouse` backfills facts and summaries without rewriting original records. Migration `0012_shared_source_storage` stops creating physical schemas/tables for new source registrations. Source and generation UUIDs keep independent SCADA databases and reused native IDs separate. Alarm/event table identity is preserved, so an alarm ID and event ID with the same integer remain different occurrences. Facts contain one row per source/generation/native ID **within their record type**; changed copies increase saved-version counts rather than occurrence counts.

The UUID dimension views refer to existing registration tables, so labels stay current without duplicated dimensions or changed identities. This is a shared star model with stored facts; historical dimension-label versioning is not implemented. Source-specific views are not automatically created for each new source. Existing physical source tables remain synchronized as a compatibility layer, with their OIDs, grants and history intact. They still consume additional storage; this upgrade does not silently drop them or convert them to views.

All new stored tables enforce forced customer RLS. The private NOLOGIN, NOBYPASSRLS `scada_warehouse_owner` has explicit maintenance policies and narrowly exposed refresh entry points; runtime accounts must never inherit it. Reporting readers receive safe derived columns and cannot read original payload/operator fields or mutate data. See [refresh, summaries and security](central-server-analysis.md#stored-warehouse-architecture).

## Legacy source-specific layout

Central Server 0.6.1 names each source schema from the **SCADA PC/source name entered at registration**. For example, a source registered as `Oven Line SCADA` has `"Oven Line SCADA".alarmhistory` and `"Oven Line SCADA".eventhistory`. The source details in the manager show its SQL schema. Each schema contains exactly these two physical tables. Deleting a registration preserves its schema and history.

Migration `0009_source_schema_names` renames existing source schemas in place, preserving table OIDs, permissions, data and revision identity. New registrations use their source label immediately; a later administrative source-name update renames the schema in the same transaction. Registered labels remain unchanged. PostgreSQL identifiers are limited to 63 UTF-8 bytes: longer labels are shortened at character boundaries. Commas become underscores for pgAdmin's comma-separated restriction; control characters are replaced and surrounding whitespace trimmed. Reserved `pg_` names get a `SCADA_` prefix. A collision with another source or an existing schema adds the source UUID as a suffix, shortening the label as needed. Sources with the same name remain separate even across customers. Dynamic identifiers are always quoted.

Migration `0008_source_tables` applies only to Central storage. It backfills existing saved revisions and equipment identifications, then synchronizes new revisions and identification updates transactionally. The earlier migration assigned numbered schemas to active sources first; migration `0009` replaces those names with registered labels. Previously deleted registrations without history need no schema; historical records and future accepted backlog remain supported.

Native columns retain uploaded values, source-local timestamps and separate milliseconds. Additional columns retain customer/source/generation/revision identity, content hash, receipt time, timezone/ordering uncertainty, mapping status and equipment identification. Alarm equipment remains a suggestion; events use the registered machine tag. These results do not approve reporting mappings or clear quarantine.

One row represents one saved content version. Replayed unchanged content does not create another row. Changed content retains another revision, so the native `id` alone is not a unique central identifier; use `revision_id` and source/generation identity.

The original ledger, receipts, credentials, jobs and audit history remain in `platform`. Source tables are an additional stored representation and consume additional space. Transactional triggers synchronize them: a failed write rolls back processing and leaves the accepted upload available for retry. Direct row edits are blocked; use the collector/application workflow. Internal database objects are preserved.

Tables enforce customer row policies, fixed source/customer constraints and a foreign key to the canonical revision. A private non-login storage owner performs synchronization; runtime identities must not inherit that role. No extra raw-data access is granted to reporting readers. A pgAdmin schema restriction simplifies navigation but is not access control.

See [pgAdmin browsing](pgadmin-browsing.md). Never apply this migration to a SCADA source database.
