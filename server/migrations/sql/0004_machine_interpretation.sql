-- Central storage only. AI suggestions are never authoritative machine mappings.
CREATE TABLE platform.machine_interpretations (
    revision_id uuid PRIMARY KEY,
    customer_id uuid NOT NULL,
    source_id uuid NOT NULL,
    generation_id uuid NOT NULL,
    source_table text NOT NULL,
    source_record_id integer NOT NULL,
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','processing','suggested','uncertain','unavailable')),
    candidates jsonb NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(candidates)='array'),
    model text,
    model_digest text,
    policy_version text,
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts>=0),
    available_at timestamptz NOT NULL DEFAULT now(),
    lease_token uuid,
    lease_expires_at timestamptz,
    interpreted_at timestamptz,
    error_code text CHECK (error_code IS NULL OR error_code='local_ai_unavailable_or_invalid'),
    CHECK ((status='processing') = (lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)),
    FOREIGN KEY (customer_id,source_id,generation_id,source_table,source_record_id,revision_id)
        REFERENCES platform.alarm_event_revisions
        (customer_id,source_id,generation_id,source_table,source_record_id,revision_id)
);
ALTER TABLE platform.machine_interpretations ENABLE ROW LEVEL SECURITY;
ALTER TABLE platform.machine_interpretations FORCE ROW LEVEL SECURITY;
CREATE POLICY customer_scope ON platform.machine_interpretations
    USING (customer_id = nullif(current_setting('app.customer_id',true),'')::uuid)
    WITH CHECK (customer_id = nullif(current_setting('app.customer_id',true),'')::uuid);
CREATE INDEX machine_interpretation_queue ON platform.machine_interpretations(available_at)
    WHERE status IN ('pending','processing','unavailable');
GRANT SELECT,INSERT,UPDATE ON platform.machine_interpretations TO scada_worker;
GRANT SELECT,UPDATE ON platform.machine_interpretations TO scada_bootstrap_owner;
INSERT INTO platform.machine_interpretations(revision_id,customer_id,source_id,generation_id,source_table,source_record_id)
    SELECT revision_id,customer_id,source_id,generation_id,source_table,source_record_id
    FROM platform.alarm_event_revisions;

GRANT CREATE ON SCHEMA platform TO scada_bootstrap_owner;
CREATE FUNCTION platform.claim_machine_interpretation()
RETURNS SETOF platform.machine_interpretations
LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,platform SET row_security=off AS $$
    WITH candidate AS (
        SELECT revision_id FROM platform.machine_interpretations
        WHERE (status IN ('pending','unavailable') AND available_at<=clock_timestamp())
            OR (status='processing' AND lease_expires_at<=clock_timestamp())
        ORDER BY available_at,revision_id FOR UPDATE SKIP LOCKED LIMIT 1
    ) UPDATE platform.machine_interpretations t SET status='processing',
        lease_token=gen_random_uuid(),lease_expires_at=clock_timestamp()+interval '90 seconds',attempts=attempts+1
        FROM candidate WHERE t.revision_id=candidate.revision_id RETURNING t.*;
$$;
ALTER FUNCTION platform.claim_machine_interpretation() OWNER TO scada_bootstrap_owner;
REVOKE CREATE ON SCHEMA platform FROM scada_bootstrap_owner;
REVOKE ALL ON FUNCTION platform.claim_machine_interpretation() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION platform.claim_machine_interpretation() TO scada_worker;
