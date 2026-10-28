-- Cloud database administrator runs AFTER migration, never on the SCADA DB.
-- Roles are NOLOGIN capability groups. Provision separate secret-bearing LOGIN
-- accounts outside source control; do not grant membership across components.
DO $$
DECLARE role_name text;
BEGIN
    FOREACH role_name IN ARRAY ARRAY['scada_ingest', 'scada_worker', 'scada_reader', 'scada_registry']
    LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
            EXECUTE format('CREATE ROLE %I NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS', role_name);
        END IF;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name
            AND (rolsuper OR rolbypassrls OR rolcreaterole OR rolcreatedb OR rolreplication OR rolcanlogin)) THEN
            RAISE EXCEPTION 'existing capability role % is unexpectedly privileged or LOGIN', role_name;
        END IF;
    END LOOP;
END $$;

GRANT USAGE ON SCHEMA platform TO scada_ingest, scada_worker, scada_reader, scada_registry;

GRANT SELECT ON platform.customers, platform.sites, platform.projects,
    platform.machines, platform.collectors, platform.sources, platform.source_generations,
    platform.credential_machines, platform.mapping_versions, platform.mapping_rules
    TO scada_ingest;
GRANT SELECT, INSERT ON platform.upload_batches, platform.jobs TO scada_ingest;
GRANT INSERT ON platform.audit_log TO scada_ingest;

GRANT SELECT ON platform.customers, platform.sites, platform.projects, platform.machines,
    platform.sources, platform.source_generations, platform.credential_machines,
    platform.mapping_versions, platform.mapping_rules, platform.upload_batches,
    platform.alarm_event_revisions, platform.latest_alarm_state, platform.jobs,
    platform.code_lookup TO scada_worker;
GRANT INSERT ON platform.alarm_event_revisions, platform.latest_alarm_state, platform.audit_log TO scada_worker;
GRANT UPDATE ON platform.latest_alarm_state, platform.jobs TO scada_worker;
GRANT UPDATE (processing_status, processed_at) ON platform.upload_batches TO scada_worker;
GRANT UPDATE (mapping_status, mapping_version_id, machine_id, severity)
    ON platform.alarm_event_revisions TO scada_worker;

-- No raw revision payloads, user fields or credential verifiers granted to reads.
-- Phase 2 will expose explicit safe views/column grants after API contract review.
GRANT SELECT ON platform.machines TO scada_reader;

GRANT SELECT, INSERT, UPDATE ON platform.customers, platform.sites, platform.projects,
    platform.machines, platform.collectors, platform.sources, platform.source_generations,
    platform.collector_credentials, platform.credential_machines, platform.mapping_versions,
    platform.mapping_rules, platform.code_lookup TO scada_registry;
GRANT SELECT, INSERT ON platform.audit_log TO scada_registry;
GRANT USAGE ON SEQUENCE platform.audit_log_audit_id_seq TO scada_ingest, scada_worker, scada_registry;

-- No application role gets DELETE, TRUNCATE, DDL, ownership or audit UPDATE.
-- Tenant discovery/authentication bootstrap is deliberately NOT implemented here.
