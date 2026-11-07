# Shared warehouse storage

Current Central storage uses fixed schemas shared by every registered source:

| Schema | Responsibility |
| --- | --- |
| `platform` | Authoritative registrations, generations, committed receipts, original revisions, historical mapping metadata, jobs and audit history. |
| `warehouse` | Stored alarm/event occurrence facts, UUID dimension views and durable refresh queues. |
| `reporting` | Maintained hourly, daily, equipment and source-upload summaries, a dirty-day queue and named read-only occurrence views. |

```text
Central PostgreSQL
|-- platform: source identities, originals, receipts and processing
|-- warehouse
|   |-- fact_alarm_occurrence
|   |-- fact_event_occurrence
|   `-- dim_customer / dim_site / dim_project / dim_source / dim_machine / dim_date
`-- reporting: hourly / daily / equipment / source-upload summaries
```

Rows retain `customer_id`, `source_id` and `generation_id`; each source is a separately registered SCADA database. One collector PC can host multiple sources. UUIDs distinguish reused native IDs; alarm and event identities remain separate. Facts count one occurrence per source/generation/native ID within each record type. Changed copies increase saved-version counts. Original fields, source-local timestamps, separate milliseconds and revision history remain in `platform.alarm_event_revisions`.

Dimension views use existing registration tables, so current labels stay consistent without duplicated dimensions. Historical dimension-label versioning is not implemented. AI suggestions and registered event identity remain separate from inactive historical mapping annotations. Migration 0015 removes machine-mapping approval and releases completed mapping holds; see [source-scoped processing](source-scoped-processing.md). See [refresh and security](central-server-analysis.md#stored-warehouse-architecture).

## Removing the old per-source design

Published Central Server 0.6.1 created a schema named for each source, with physical `alarmhistory` and `eventhistory` copies. Migration `0012_shared_source_storage` stopped creating these for new registrations. **`0013_remove_source_copies`** verifies and removes the remaining copies, their metadata and synchronization functions/triggers. Source renames now change registration labels without schema DDL.

Apply migrations only to Central storage, with the configured API/worker/manager stopped and an encrypted, restore-verified backup available. Migration 0013 locks the relevant tables, verifies both legacy tables against canonical evidence (native values, metadata and retained identification candidates), and removes them in one transaction. Missing/different rows, unexpected columns, unrecognized ownership, extra schema objects or external dependencies block removal. No cascading deletion is used. Investigate failures; do not drop data to bypass validation.

Originals, identity, credentials, receipts, mappings, jobs, audit history, facts and summaries remain intact. Existing `logs` compatibility views contain no duplicate physical storage and remain available to authorized readers. The cluster-wide NOLOGIN `scada_storage_owner` role remains for other databases/historical downgrades, with its former privileges revoked in this database; runtime identities must never inherit it or the private warehouse owner.

Downgrading 0013 rebuilds copies from retained originals. It needs additional storage and assigns **new OIDs**; it cannot restore custom grants or external dependencies. Restore the pre-upgrade backup for exact old objects/permissions. Earlier migrations remain unchanged. Published installers and separate Central Server installations are not updated by this local deployment.

## Browsing safely

Browse shared facts and summaries in [pgAdmin](pgadmin-browsing.md). Migration `0014_named_warehouse_views` adds read-only `reporting.alarm_occurrences` and `reporting.event_occurrences` with customer/site/project/source names for direct filtering. These are invoker views over shared facts/dimensions, with no copied rows or new tenant privileges. Join `warehouse.dim_source` on both `customer_id` and `source_id` to display source names. Another source for the authorized customer needs no new SQL schema or navigation filter.

Stored warehouse/reporting tables enforce forced customer RLS. An arbitrary-SQL reader needs fixed customer authorization in database policies, not merely a changeable `app.customer_id` setting. Schema restrictions simplify navigation; they do not provide isolation or grant access.
