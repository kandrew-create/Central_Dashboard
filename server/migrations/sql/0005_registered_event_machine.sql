-- Events use the machine selected at source registration, without AI.
ALTER TABLE platform.machine_interpretations DROP CONSTRAINT machine_interpretations_status_check;
ALTER TABLE platform.machine_interpretations ADD CONSTRAINT machine_interpretations_status_check
    CHECK (status IN ('pending','processing','suggested','uncertain','unavailable','registered'));

DROP FUNCTION platform.claim_machine_interpretation();
GRANT CREATE ON SCHEMA platform TO scada_bootstrap_owner;
CREATE FUNCTION platform.claim_machine_interpretation(include_alarms boolean DEFAULT true)
RETURNS SETOF platform.machine_interpretations
LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,platform SET row_security=off AS $$
    WITH candidate AS (
        SELECT revision_id FROM platform.machine_interpretations
        WHERE (include_alarms OR source_table='eventhistory') AND
            ((status IN ('pending','unavailable') AND available_at<=clock_timestamp())
            OR (status='processing' AND lease_expires_at<=clock_timestamp()))
        ORDER BY available_at,revision_id FOR UPDATE SKIP LOCKED LIMIT 1
    ) UPDATE platform.machine_interpretations t SET status='processing',
        lease_token=gen_random_uuid(),lease_expires_at=clock_timestamp()+interval '90 seconds',attempts=attempts+1
        FROM candidate WHERE t.revision_id=candidate.revision_id RETURNING t.*;
$$;
ALTER FUNCTION platform.claim_machine_interpretation(boolean) OWNER TO scada_bootstrap_owner;
REVOKE CREATE ON SCHEMA platform FROM scada_bootstrap_owner;
REVOKE ALL ON FUNCTION platform.claim_machine_interpretation(boolean) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION platform.claim_machine_interpretation(boolean) TO scada_worker;

-- Re-evaluate earlier event AI results only; immutable source revisions stay intact.
UPDATE platform.machine_interpretations SET status='pending',candidates='[]',model=NULL,
    model_digest=NULL,policy_version=NULL,available_at=now(),lease_token=NULL,lease_expires_at=NULL,
    interpreted_at=NULL,error_code=NULL WHERE source_table='eventhistory';
