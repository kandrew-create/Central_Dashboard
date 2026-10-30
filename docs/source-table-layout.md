# Per-source native tables

Central Server 0.6.1 names each source schema from the **SCADA PC/source name entered at registration**. For example, a source registered as `Oven Line SCADA` has `"Oven Line SCADA".alarmhistory` and `"Oven Line SCADA".eventhistory`. The source details in the manager show its SQL schema. Each schema contains exactly these two physical tables. Deleting a registration preserves its schema and history.

Migration `0009_source_schema_names` renames existing source schemas in place, preserving table OIDs, permissions, data and revision identity. New registrations use their source label immediately; a later administrative source-name update renames the schema in the same transaction. Registered labels remain unchanged. PostgreSQL identifiers are limited to 63 UTF-8 bytes: longer labels are shortened at character boundaries. Commas become underscores for pgAdmin's comma-separated restriction; control characters are replaced and surrounding whitespace trimmed. Reserved `pg_` names get a `SCADA_` prefix. A collision with another source or an existing schema adds the source UUID as a suffix, shortening the label as needed. Sources with the same name remain separate even across customers. Dynamic identifiers are always quoted.

Migration `0008_source_tables` applies only to Central storage. It backfills existing saved revisions and equipment identifications, then synchronizes new revisions and identification updates transactionally. The earlier migration assigned numbered schemas to active sources first; migration `0009` replaces those names with registered labels. Previously deleted registrations without history need no schema; historical records and future accepted backlog remain supported.

Native columns retain uploaded values, source-local timestamps and separate milliseconds. Additional columns retain customer/source/generation/revision identity, content hash, receipt time, timezone/ordering uncertainty, mapping status and equipment identification. Alarm equipment remains a suggestion; events use the registered machine tag. These results do not approve reporting mappings or clear quarantine.

One row represents one saved content version. Replayed unchanged content does not create another row. Changed content retains another revision, so the native `id` alone is not a unique central identifier; use `revision_id` and source/generation identity.

The original ledger, receipts, credentials, jobs and audit history remain in `platform`. Source tables are an additional stored representation and consume additional space. Transactional triggers synchronize them: a failed write rolls back processing and leaves the accepted upload available for retry. Direct row edits are blocked; use the collector/application workflow. Internal database objects are preserved.

Tables enforce customer row policies, fixed source/customer constraints and a foreign key to the canonical revision. A private non-login storage owner performs synchronization; runtime identities must not inherit that role. No extra raw-data access is granted to reporting readers. A pgAdmin schema restriction simplifies navigation but is not access control.

See [pgAdmin browsing](pgadmin-browsing.md). Never apply this migration to a SCADA source database.
