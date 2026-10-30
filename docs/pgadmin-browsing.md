# Simple Central Server browsing in pgAdmin

Central Server 0.6.1 provides this layout for each registered source:

The schema name below is an example; your registered source name is used. Duplicate, reserved or long labels receive the safe adjustments described in [storage details](source-table-layout.md).

```text
Schemas
└── Oven Line SCADA
    └── Tables
        ├── alarmhistory
        └── eventhistory
```

Each source uses its registered SCADA PC/source name. Select a source in the manager to see its SQL schema. These are real tables, maintained by Central Server. Right-click a table and choose **View/Edit Data → All Rows** to read its records. Direct row changes are blocked to preserve collected history.

For bounded SQL reads, quote the schema name exactly:

```sql
SELECT id, al_message, equipment, identification_status
FROM "Oven Line SCADA".alarmhistory
ORDER BY generation_id, id, received_at
LIMIT 100;

SELECT id, ev_message, equipment, identification_status
FROM "Oven Line SCADA".eventhistory
ORDER BY generation_id, id, received_at
LIMIT 100;
```

All native fields, separate milliseconds and saved revisions remain available. Unchanged repeat collection adds no revision. A changed record can retain multiple rows with the same native ID; `revision_id` identifies each stored content version. See [storage and synchronization](source-table-layout.md).

In **scada_platform → Properties → Advanced → Schema restriction**, enter the wanted schemas, such as `Oven Line SCADA,Packaging SCADA`, then refresh **Schemas** or reopen pgAdmin. Restrict the Central Server connection's database list to `scada_platform` if desired. Add newly registered source schemas to this restriction to display them. Existing window contents can remain cached until refreshed.

Internal `platform` tables and the earlier `logs` views remain preserved and hidden by this preference. Clear the restriction and refresh to browse them again. Hiding schemas changes navigation only; authorized SQL access and permissions remain unchanged. Other server connections remain untouched. Back up the private pgAdmin profile before changing its stored preferences.
