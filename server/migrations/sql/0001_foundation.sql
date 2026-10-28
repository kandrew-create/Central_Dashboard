-- Immutable initial cloud schema. Never run against a SCADA source database.
CREATE SCHEMA platform;
REVOKE ALL ON SCHEMA platform FROM PUBLIC;

CREATE TABLE platform.customers (
    customer_id uuid PRIMARY KEY,
    name text NOT NULL CHECK (length(btrim(name)) > 0),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE platform.sites (
    site_id uuid PRIMARY KEY,
    customer_id uuid NOT NULL REFERENCES platform.customers,
    name text NOT NULL CHECK (length(btrim(name)) > 0),
    UNIQUE (customer_id, site_id)
);

CREATE TABLE platform.projects (
    project_id uuid PRIMARY KEY,
    customer_id uuid NOT NULL,
    site_id uuid NOT NULL,
    name text NOT NULL CHECK (length(btrim(name)) > 0),
    FOREIGN KEY (customer_id, site_id) REFERENCES platform.sites (customer_id, site_id),
    UNIQUE (customer_id, site_id, project_id)
);

CREATE TABLE platform.machines (
    machine_id uuid PRIMARY KEY,
    customer_id uuid NOT NULL,
    site_id uuid NOT NULL,
    project_id uuid NOT NULL,
    machine_tag text NOT NULL CHECK (length(btrim(machine_tag)) > 0),
    name text NOT NULL,
    FOREIGN KEY (customer_id, site_id, project_id)
        REFERENCES platform.projects (customer_id, site_id, project_id),
    UNIQUE (customer_id, site_id, machine_tag),
    UNIQUE (customer_id, site_id, project_id, machine_id)
);

CREATE TABLE platform.collectors (
    collector_id uuid PRIMARY KEY,
    customer_id uuid NOT NULL,
    site_id uuid NOT NULL,
    name text NOT NULL,
    revoked_at timestamptz,
    FOREIGN KEY (customer_id, site_id) REFERENCES platform.sites (customer_id, site_id),
    UNIQUE (customer_id, site_id, collector_id)
);

CREATE TABLE platform.sources (
    source_id uuid PRIMARY KEY,
    customer_id uuid NOT NULL,
    site_id uuid NOT NULL,
    project_id uuid NOT NULL,
    collector_id uuid NOT NULL,
    name text NOT NULL,
    profile text NOT NULL CHECK (profile = 'ecostruxure_machine_scada_expert_v1'),
    expected_upload_seconds integer CHECK (expected_upload_seconds > 0),
    -- Monitoring only. No cloud field is delivered as collector configuration.
    FOREIGN KEY (customer_id, site_id, project_id)
        REFERENCES platform.projects (customer_id, site_id, project_id),
    FOREIGN KEY (customer_id, site_id, collector_id)
        REFERENCES platform.collectors (customer_id, site_id, collector_id),
    UNIQUE (customer_id, site_id, project_id, source_id),
    UNIQUE (customer_id, source_id)
);

CREATE TABLE platform.source_generations (
    generation_id uuid PRIMARY KEY,
    customer_id uuid NOT NULL,
    source_id uuid NOT NULL,
    generation_number integer NOT NULL CHECK (generation_number > 0),
    database_identifier text NOT NULL,
    authorized_by text NOT NULL CHECK (length(btrim(authorized_by)) > 0),
    local_authorization_reference text NOT NULL CHECK (length(btrim(local_authorization_reference)) > 0),
    authorized_at timestamptz NOT NULL,
    retired_at timestamptz,
    FOREIGN KEY (customer_id, source_id) REFERENCES platform.sources (customer_id, source_id),
    UNIQUE (source_id, generation_number),
    UNIQUE (customer_id, source_id, generation_id),
    CHECK (retired_at IS NULL OR retired_at >= authorized_at)
);
CREATE UNIQUE INDEX one_active_generation ON platform.source_generations (source_id)
    WHERE retired_at IS NULL;

CREATE TABLE platform.collector_credentials (
    credential_id uuid PRIMARY KEY,
    customer_id uuid NOT NULL,
    site_id uuid NOT NULL,
    project_id uuid NOT NULL,
    source_id uuid NOT NULL,
    verifier bytea NOT NULL CHECK (octet_length(verifier) = 32),
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz,
    revoked_at timestamptz,
    FOREIGN KEY (customer_id, site_id, project_id, source_id)
        REFERENCES platform.sources (customer_id, site_id, project_id, source_id),
    UNIQUE (customer_id, site_id, project_id, source_id, credential_id),
    UNIQUE (verifier),
    CHECK (expires_at IS NULL OR expires_at > created_at)
);

CREATE TABLE platform.credential_machines (
    customer_id uuid NOT NULL,
    site_id uuid NOT NULL,
    project_id uuid NOT NULL,
    source_id uuid NOT NULL,
    credential_id uuid NOT NULL,
    machine_id uuid NOT NULL,
    PRIMARY KEY (credential_id, machine_id),
    FOREIGN KEY (customer_id, site_id, project_id, source_id, credential_id)
        REFERENCES platform.collector_credentials (customer_id, site_id, project_id, source_id, credential_id),
    FOREIGN KEY (customer_id, site_id, project_id, machine_id)
        REFERENCES platform.machines (customer_id, site_id, project_id, machine_id)
);

CREATE TABLE platform.mapping_versions (
    mapping_version_id uuid PRIMARY KEY,
    customer_id uuid NOT NULL,
    site_id uuid NOT NULL,
    project_id uuid NOT NULL,
    source_id uuid NOT NULL,
    version integer NOT NULL CHECK (version > 0),
    status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'approved', 'retired')),
    approved_by text,
    approved_at timestamptz,
    FOREIGN KEY (customer_id, site_id, project_id, source_id)
        REFERENCES platform.sources (customer_id, site_id, project_id, source_id),
    UNIQUE (source_id, version),
    UNIQUE (customer_id, site_id, project_id, source_id, mapping_version_id),
    CHECK ((status = 'draft' AND approved_by IS NULL AND approved_at IS NULL)
        OR (status IN ('approved', 'retired') AND approved_by IS NOT NULL AND approved_at IS NOT NULL))
);

CREATE TABLE platform.mapping_rules (
    rule_id uuid PRIMARY KEY,
    customer_id uuid NOT NULL,
    site_id uuid NOT NULL,
    project_id uuid NOT NULL,
    source_id uuid NOT NULL,
    mapping_version_id uuid NOT NULL,
    machine_id uuid NOT NULL,
    record_type text NOT NULL CHECK (record_type IN ('alarm', 'event')),
    -- Exact-match rules only in the first profile; NULL match fields are wildcards.
    tag text, station text, selection text, group_code integer, event_source text,
    severity text,
    FOREIGN KEY (customer_id, site_id, project_id, source_id, mapping_version_id)
        REFERENCES platform.mapping_versions (customer_id, site_id, project_id, source_id, mapping_version_id),
    FOREIGN KEY (customer_id, site_id, project_id, machine_id)
        REFERENCES platform.machines (customer_id, site_id, project_id, machine_id),
    CHECK (tag IS NOT NULL OR station IS NOT NULL OR selection IS NOT NULL
        OR group_code IS NOT NULL OR event_source IS NOT NULL)
);

CREATE TABLE platform.upload_batches (
    upload_id uuid PRIMARY KEY,
    customer_id uuid NOT NULL,
    source_id uuid NOT NULL,
    generation_id uuid NOT NULL,
    batch_id uuid NOT NULL,
    payload_hash text NOT NULL CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
    schema_version integer NOT NULL CHECK (schema_version = 1),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    record_count integer NOT NULL CHECK (record_count > 0),
    payload_bytes integer NOT NULL CHECK (payload_bytes > 0),
    receipt jsonb NOT NULL,
    received_at timestamptz NOT NULL DEFAULT now(),
    is_backfill boolean NOT NULL DEFAULT false,
    processing_status text NOT NULL DEFAULT 'pending'
        CHECK (processing_status IN ('pending', 'processing', 'completed', 'quarantined', 'failed')),
    processed_at timestamptz,
    FOREIGN KEY (customer_id, source_id, generation_id)
        REFERENCES platform.source_generations (customer_id, source_id, generation_id),
    UNIQUE (source_id, batch_id),
    UNIQUE (customer_id, source_id, generation_id, upload_id),
    CHECK (receipt = jsonb_build_object('batch_id', batch_id::text,
        'payload_hash', payload_hash, 'status', 'committed'))
);

CREATE TABLE platform.alarm_event_revisions (
    revision_id uuid PRIMARY KEY,
    customer_id uuid NOT NULL,
    site_id uuid NOT NULL,
    project_id uuid NOT NULL,
    source_id uuid NOT NULL,
    generation_id uuid NOT NULL,
    upload_id uuid NOT NULL,
    source_table text NOT NULL CHECK (source_table IN ('alarmhistory', 'eventhistory')),
    record_type text NOT NULL CHECK (record_type IN ('alarm', 'event')),
    source_record_id integer NOT NULL,
    revision_key text NOT NULL CHECK (length(revision_key) BETWEEN 1 AND 256),
    content_hash text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    original_payload jsonb NOT NULL CHECK (jsonb_typeof(original_payload) = 'object'),
    source_timezone text NOT NULL,
    ordering_uncertain boolean NOT NULL,
    mapping_status text NOT NULL CHECK (mapping_status IN ('mapped', 'quarantined')),
    mapping_version_id uuid,
    machine_id uuid,
    severity text,
    start_time_local timestamp, start_time_ms integer, start_time_utc timestamptz,
    start_time_quality text NOT NULL,
    norm_time_local timestamp, norm_time_ms integer, norm_time_utc timestamptz,
    norm_time_quality text NOT NULL,
    ack_time_local timestamp, ack_time_ms integer, ack_time_utc timestamptz,
    ack_time_quality text NOT NULL,
    event_time_local timestamp, event_time_ms integer, event_time_utc timestamptz,
    event_time_quality text NOT NULL,
    last_update_local timestamp, last_update_ms integer, last_update_utc timestamptz,
    last_update_quality text NOT NULL,
    active boolean, ack boolean, ack_required boolean, deleted boolean,
    tag text, message text, station text, selection text, custom1 text,
    group_code integer, priority_code integer, type_code integer,
    value text, previous_value text, event_info text, event_source text,
    user_name text, user_full text, user_comment text,
    received_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (customer_id, site_id, project_id, source_id)
        REFERENCES platform.sources (customer_id, site_id, project_id, source_id),
    FOREIGN KEY (customer_id, source_id, generation_id, upload_id)
        REFERENCES platform.upload_batches (customer_id, source_id, generation_id, upload_id),
    FOREIGN KEY (customer_id, site_id, project_id, source_id, mapping_version_id)
        REFERENCES platform.mapping_versions (customer_id, site_id, project_id, source_id, mapping_version_id),
    FOREIGN KEY (customer_id, site_id, project_id, machine_id)
        REFERENCES platform.machines (customer_id, site_id, project_id, machine_id),
    UNIQUE (generation_id, source_table, source_record_id, revision_key),
    UNIQUE (generation_id, source_table, source_record_id, content_hash),
    UNIQUE (customer_id, source_id, generation_id, source_table, source_record_id, revision_id),
    CHECK ((record_type = 'alarm' AND source_table = 'alarmhistory')
        OR (record_type = 'event' AND source_table = 'eventhistory')),
    CHECK ((mapping_status = 'mapped' AND machine_id IS NOT NULL AND mapping_version_id IS NOT NULL)
        OR (mapping_status = 'quarantined' AND machine_id IS NULL AND mapping_version_id IS NULL AND severity IS NULL)),
    CHECK (last_update_local IS NOT NULL OR ordering_uncertain),
    CHECK (start_time_quality IN ('missing', 'known', 'ambiguous', 'nonexistent', 'invalid', 'timezone_unknown')),
    CHECK (norm_time_quality IN ('missing', 'known', 'ambiguous', 'nonexistent', 'invalid', 'timezone_unknown')),
    CHECK (ack_time_quality IN ('missing', 'known', 'ambiguous', 'nonexistent', 'invalid', 'timezone_unknown')),
    CHECK (event_time_quality IN ('missing', 'known', 'ambiguous', 'nonexistent', 'invalid', 'timezone_unknown')),
    CHECK (last_update_quality IN ('missing', 'known', 'ambiguous', 'nonexistent', 'invalid', 'timezone_unknown')),
    CHECK ((start_time_quality = 'known') = (start_time_utc IS NOT NULL)),
    CHECK ((norm_time_quality = 'known') = (norm_time_utc IS NOT NULL)),
    CHECK ((ack_time_quality = 'known') = (ack_time_utc IS NOT NULL)),
    CHECK ((event_time_quality = 'known') = (event_time_utc IS NOT NULL)),
    CHECK ((last_update_quality = 'known') = (last_update_utc IS NOT NULL)),
    CHECK ((start_time_local IS NULL) = (start_time_quality = 'missing')),
    CHECK ((norm_time_local IS NULL) = (norm_time_quality = 'missing')),
    CHECK ((ack_time_local IS NULL) = (ack_time_quality = 'missing')),
    CHECK ((event_time_local IS NULL) = (event_time_quality = 'missing')),
    CHECK ((last_update_local IS NULL) = (last_update_quality = 'missing'))
);
CREATE INDEX revision_customer_machine_event ON platform.alarm_event_revisions
    (customer_id, machine_id, event_time_utc);
CREATE INDEX revision_source_update ON platform.alarm_event_revisions
    (customer_id, source_id, last_update_local, last_update_ms);
CREATE INDEX quarantined_revisions ON platform.alarm_event_revisions (customer_id, received_at)
    WHERE mapping_status = 'quarantined';

-- One row per alarm occurrence, including occurrences with no verified latest revision.
CREATE TABLE platform.latest_alarm_state (
    customer_id uuid NOT NULL,
    source_id uuid NOT NULL,
    generation_id uuid NOT NULL,
    source_table text NOT NULL DEFAULT 'alarmhistory' CHECK (source_table = 'alarmhistory'),
    source_record_id integer NOT NULL,
    revision_id uuid,
    effective_source_time timestamp,
    effective_source_ms integer,
    ordering_uncertain boolean NOT NULL DEFAULT true,
    last_observed_at timestamptz NOT NULL,
    PRIMARY KEY (generation_id, source_record_id),
    FOREIGN KEY (customer_id, source_id, generation_id)
        REFERENCES platform.source_generations (customer_id, source_id, generation_id),
    FOREIGN KEY (customer_id, source_id, generation_id, source_table, source_record_id, revision_id)
        REFERENCES platform.alarm_event_revisions
        (customer_id, source_id, generation_id, source_table, source_record_id, revision_id),
    CHECK (revision_id IS NOT NULL OR ordering_uncertain)
);

CREATE TABLE platform.jobs (
    job_id uuid PRIMARY KEY,
    customer_id uuid NOT NULL,
    source_id uuid NOT NULL,
    generation_id uuid NOT NULL,
    upload_id uuid NOT NULL,
    kind text NOT NULL CHECK (kind = 'process_batch'),
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'leased', 'completed', 'failed')),
    available_at timestamptz NOT NULL DEFAULT now(),
    lease_expires_at timestamptz,
    lease_token uuid,
    attempts integer NOT NULL DEFAULT 0,
    max_attempts integer NOT NULL DEFAULT 5 CHECK (max_attempts BETWEEN 1 AND 100),
    last_error_code text,
    created_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    FOREIGN KEY (customer_id, source_id, generation_id, upload_id)
        REFERENCES platform.upload_batches (customer_id, source_id, generation_id, upload_id),
    UNIQUE (upload_id, kind),
    CHECK (attempts BETWEEN 0 AND max_attempts),
    CHECK ((status = 'leased') = (lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)),
    CHECK (status = 'leased' OR (lease_token IS NULL AND lease_expires_at IS NULL)),
    CHECK ((status = 'completed') = (completed_at IS NOT NULL))
);
CREATE INDEX jobs_ready ON platform.jobs (customer_id, available_at, job_id) WHERE status = 'pending';
CREATE INDEX jobs_expired ON platform.jobs (customer_id, lease_expires_at) WHERE status = 'leased';

CREATE TABLE platform.audit_log (
    audit_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    customer_id uuid NOT NULL REFERENCES platform.customers,
    actor text NOT NULL,
    action text NOT NULL,
    entity_type text NOT NULL,
    entity_id uuid NOT NULL,
    details jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(details) = 'object'),
    occurred_at timestamptz NOT NULL DEFAULT now()
);

-- Empty until a customer approves code meanings. No default severity is inferred.
CREATE TABLE platform.code_lookup (
    customer_id uuid NOT NULL REFERENCES platform.customers,
    profile text NOT NULL CHECK (profile = 'ecostruxure_machine_scada_expert_v1'),
    code_family text NOT NULL CHECK (code_family IN ('al_type', 'al_priority', 'al_group', 'ev_type')),
    code integer NOT NULL,
    meaning text NOT NULL,
    approved_by text NOT NULL,
    approved_at timestamptz NOT NULL,
    PRIMARY KEY (customer_id, profile, code_family, code)
);

-- The fail-closed tenant context is transaction-local, set only after authentication.
DO $$
DECLARE target record;
BEGIN
    FOR target IN SELECT tablename FROM pg_tables WHERE schemaname = 'platform'
    LOOP
        EXECUTE format('ALTER TABLE platform.%I ENABLE ROW LEVEL SECURITY', target.tablename);
        EXECUTE format('ALTER TABLE platform.%I FORCE ROW LEVEL SECURITY', target.tablename);
        EXECUTE format('CREATE POLICY customer_scope ON platform.%I USING '
            || '(customer_id = nullif(current_setting(''app.customer_id'', true), '''')::uuid) '
            || 'WITH CHECK (customer_id = nullif(current_setting(''app.customer_id'', true), '''')::uuid)',
            target.tablename);
    END LOOP;
END $$;

-- Lock parent mapping rows to serialize approval against concurrent rule edits.
CREATE FUNCTION platform.guard_mapping_rule() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, platform AS $$
DECLARE mapping_status text;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        SELECT status INTO mapping_status FROM platform.mapping_versions
            WHERE mapping_version_id = OLD.mapping_version_id FOR UPDATE;
        IF mapping_status IS DISTINCT FROM 'draft' THEN
            RAISE EXCEPTION 'approved mapping rules are immutable' USING ERRCODE = '23514';
        END IF;
    END IF;
    IF TG_OP <> 'DELETE' THEN
        SELECT status INTO mapping_status FROM platform.mapping_versions
            WHERE mapping_version_id = NEW.mapping_version_id FOR UPDATE;
        IF mapping_status IS DISTINCT FROM 'draft' THEN
            RAISE EXCEPTION 'rules may only be added to a draft mapping' USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    RETURN OLD;
END $$;
CREATE TRIGGER guard_mapping_rule BEFORE INSERT OR UPDATE OR DELETE ON platform.mapping_rules
    FOR EACH ROW EXECUTE FUNCTION platform.guard_mapping_rule();

CREATE FUNCTION platform.guard_mapping_version() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, platform AS $$
BEGIN
    IF OLD.status <> 'draft' THEN
        IF TG_OP = 'DELETE' OR NOT (OLD.status = 'approved' AND NEW.status = 'retired'
            AND (to_jsonb(OLD) - 'status') = (to_jsonb(NEW) - 'status')) THEN
            RAISE EXCEPTION 'create a new version instead of changing an approved mapping'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER guard_mapping_version BEFORE UPDATE OR DELETE ON platform.mapping_versions
    FOR EACH ROW EXECUTE FUNCTION platform.guard_mapping_version();

CREATE FUNCTION platform.audit_machine_tag() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, platform AS $$
BEGIN
    IF OLD.machine_tag IS DISTINCT FROM NEW.machine_tag THEN
        INSERT INTO platform.audit_log (customer_id, actor, action, entity_type, entity_id, details)
        VALUES (NEW.customer_id, coalesce(nullif(current_setting('app.actor', true), ''), session_user),
            'machine_tag_changed', 'machine', NEW.machine_id,
            jsonb_build_object('old_tag', OLD.machine_tag, 'new_tag', NEW.machine_tag));
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER audit_machine_tag AFTER UPDATE ON platform.machines
    FOR EACH ROW EXECUTE FUNCTION platform.audit_machine_tag();

REVOKE ALL ON ALL TABLES IN SCHEMA platform FROM PUBLIC;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA platform FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA platform FROM PUBLIC;
