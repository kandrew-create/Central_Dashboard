DROP TRIGGER warehouse_revision_changed ON platform.alarm_event_revisions;
DROP TRIGGER warehouse_latest_inserted ON platform.latest_alarm_state;
DROP TRIGGER warehouse_latest_changed ON platform.latest_alarm_state;
DROP TRIGGER warehouse_identification_changed ON platform.machine_interpretations;
DROP TRIGGER warehouse_upload_changed ON platform.upload_batches;
DROP VIEW warehouse.dim_date,warehouse.alarm_daily;
DROP TABLE reporting.alarm_hourly_summary,reporting.alarm_daily_summary,
    reporting.equipment_alarm_summary,reporting.source_upload_summary,reporting.refresh_queue;
DROP TABLE warehouse.refresh_queue,warehouse.source_refresh_queue,
    warehouse.fact_alarm_occurrence,warehouse.fact_event_occurrence;
DROP VIEW warehouse.alarm_occurrence_projection,warehouse.event_occurrence_projection;
DROP FUNCTION warehouse.queue_occurrence(),warehouse.queue_source(),
    warehouse.refresh_occurrence(uuid,uuid,uuid,text,integer),warehouse.refresh_pending(integer),
    reporting.refresh_alarm_day(uuid,uuid,date),reporting.refresh_upload_source(uuid,uuid);
DROP SCHEMA reporting;
DROP INDEX platform.warehouse_upload_source;
DO $$ DECLARE name text; BEGIN
    FOREACH name IN ARRAY ARRAY['sources','source_generations','machines',
        'alarm_event_revisions','latest_alarm_state','machine_interpretations','upload_batches'] LOOP
        EXECUTE format('DROP POLICY warehouse_maintenance ON platform.%I',name);
        EXECUTE format('REVOKE SELECT ON platform.%I FROM scada_warehouse_owner',name);
    END LOOP;
END $$;
REVOKE USAGE ON SCHEMA warehouse FROM scada_worker,scada_warehouse_owner;
REVOKE USAGE ON SCHEMA platform FROM scada_warehouse_owner;
-- Capability roles are cluster-wide and can own objects in another Central
-- database. Retain the protected NOLOGIN role rather than dropping it globally.
