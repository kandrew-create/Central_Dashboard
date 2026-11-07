-- Central storage only. Retire the mapping approval gate, retaining old mapping
-- tables/annotations as historical evidence rather than deleting record history.
SET LOCAL lock_timeout='10s';
LOCK TABLE platform.upload_batches,platform.alarm_event_revisions,platform.jobs
    IN SHARE ROW EXCLUSIVE MODE;
ALTER TABLE platform.alarm_event_revisions
    DROP CONSTRAINT alarm_event_revisions_mapping_status_check,
    DROP CONSTRAINT alarm_event_revisions_check1,
    ADD CONSTRAINT alarm_event_revisions_mapping_status_check
        CHECK(mapping_status IN ('mapped','quarantined','not_required')),
    ADD CONSTRAINT alarm_event_revisions_check1 CHECK (
        (mapping_status='mapped' AND machine_id IS NOT NULL AND mapping_version_id IS NOT NULL)
        OR (mapping_status IN ('quarantined','not_required') AND machine_id IS NULL
            AND mapping_version_id IS NULL AND severity IS NULL));

WITH released AS (
    UPDATE platform.alarm_event_revisions SET mapping_status='not_required'
    WHERE mapping_status='quarantined' RETURNING customer_id
), counts AS (
    SELECT customer_id,count(*) records FROM released GROUP BY customer_id
)
INSERT INTO platform.audit_log(customer_id,actor,action,entity_type,entity_id,details)
    SELECT customer_id,current_user,'mapping_requirement_removed','customer',customer_id,
        jsonb_build_object('released_record_versions',records) FROM counts;

-- Only completed processing jobs justify releasing a historical mapping hold.
-- Failed, pending and leased jobs must still finish their actual processing.
UPDATE platform.upload_batches b SET processing_status='completed'
WHERE b.processing_status='quarantined' AND EXISTS (
    SELECT 1 FROM platform.jobs j WHERE j.upload_id=b.upload_id
        AND j.customer_id=b.customer_id AND j.source_id=b.source_id
        AND j.generation_id=b.generation_id AND j.status='completed');

-- Matching/approval is no longer a runtime capability. Registration identities,
-- credential scope and accepted event-machine snapshots remain independent.
REVOKE ALL ON platform.mapping_versions,platform.mapping_rules
    FROM scada_ingest,scada_worker,scada_registry;
REVOKE UPDATE(mapping_status,mapping_version_id,machine_id,severity)
    ON platform.alarm_event_revisions FROM scada_worker;
