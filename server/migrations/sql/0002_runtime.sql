-- Dedicated NOLOGIN owner for the two narrow cross-tenant bootstrap functions.
-- Run only with migration administration credentials on the central database.
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='scada_bootstrap_owner') THEN
        CREATE ROLE scada_bootstrap_owner NOLOGIN BYPASSRLS;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='scada_bootstrap_owner'
        AND (rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR NOT rolbypassrls)) THEN
        RAISE EXCEPTION 'invalid bootstrap function owner';
    END IF;
END $$;
GRANT USAGE,CREATE ON SCHEMA platform TO scada_bootstrap_owner;
GRANT SELECT ON platform.collector_credentials,platform.collectors,platform.sources TO scada_bootstrap_owner;
GRANT SELECT,UPDATE ON platform.jobs TO scada_bootstrap_owner;

CREATE FUNCTION platform.authenticate_upload(candidate bytea)
RETURNS TABLE(credential_id uuid,customer_id uuid,site_id uuid,project_id uuid,source_id uuid)
LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,platform SET row_security=off AS $$
    SELECT cr.credential_id,cr.customer_id,cr.site_id,cr.project_id,cr.source_id
    FROM platform.collector_credentials cr
    JOIN platform.sources s ON s.source_id=cr.source_id
    JOIN platform.collectors c ON c.collector_id=s.collector_id
    WHERE cr.verifier=candidate AND cr.revoked_at IS NULL
      AND (cr.expires_at IS NULL OR cr.expires_at>now()) AND c.revoked_at IS NULL
$$;
ALTER FUNCTION platform.authenticate_upload(bytea) OWNER TO scada_bootstrap_owner;
REVOKE ALL ON FUNCTION platform.authenticate_upload(bytea) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION platform.authenticate_upload(bytea) TO scada_ingest;

CREATE FUNCTION platform.claim_batch_job()
RETURNS SETOF platform.jobs
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,platform SET row_security=off AS $$
BEGIN
    UPDATE platform.jobs SET status='failed',lease_token=NULL,lease_expires_at=NULL,
        last_error_code='lease_attempt_limit'
    WHERE job_id IN (SELECT job_id FROM platform.jobs
        WHERE status='leased' AND lease_expires_at<=clock_timestamp() AND attempts>=max_attempts
        ORDER BY lease_expires_at FOR UPDATE SKIP LOCKED LIMIT 100);
    RETURN QUERY WITH candidate AS (
        SELECT job_id FROM platform.jobs WHERE attempts<max_attempts AND
            ((status='pending' AND available_at<=clock_timestamp()) OR
             (status='leased' AND lease_expires_at<=clock_timestamp()))
        ORDER BY available_at,job_id FOR UPDATE SKIP LOCKED LIMIT 1
    ) UPDATE platform.jobs j SET status='leased',attempts=j.attempts+1,
        lease_token=gen_random_uuid(),lease_expires_at=clock_timestamp()+interval '90 seconds'
        FROM candidate WHERE j.job_id=candidate.job_id RETURNING j.*;
END $$;
ALTER FUNCTION platform.claim_batch_job() OWNER TO scada_bootstrap_owner;
REVOKE ALL ON FUNCTION platform.claim_batch_job() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION platform.claim_batch_job() TO scada_worker;
REVOKE CREATE ON SCHEMA platform FROM scada_bootstrap_owner;
