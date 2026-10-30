-- Central storage only. Two real, automatically maintained tables per registered source.
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='scada_storage_owner') THEN
        CREATE ROLE scada_storage_owner NOLOGIN BYPASSRLS;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='scada_storage_owner'
        AND (rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR NOT rolbypassrls)) THEN
        RAISE EXCEPTION 'Invalid source storage function owner';
    END IF;
END $$;
DO $$ BEGIN
    EXECUTE format('GRANT CREATE ON DATABASE %I TO scada_storage_owner',current_database());
END $$;
GRANT USAGE,CREATE ON SCHEMA platform TO scada_storage_owner;
GRANT SELECT ON platform.sources,platform.alarm_event_revisions,platform.machine_interpretations TO scada_storage_owner;
GRANT REFERENCES(customer_id,source_id,generation_id,source_table,source_record_id,revision_id)
    ON platform.alarm_event_revisions TO scada_storage_owner;

CREATE TABLE platform.source_storage (
    source_id uuid PRIMARY KEY,
    customer_id uuid NOT NULL,
    storage_number bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
    schema_name text GENERATED ALWAYS AS ('SCADA_PC' || storage_number::text) STORED UNIQUE,
    FOREIGN KEY (customer_id,source_id) REFERENCES platform.sources(customer_id,source_id)
);
ALTER TABLE platform.source_storage ENABLE ROW LEVEL SECURITY;
ALTER TABLE platform.source_storage FORCE ROW LEVEL SECURITY;
CREATE POLICY customer_scope ON platform.source_storage
    USING (customer_id=nullif(current_setting('app.customer_id',true),'')::uuid)
    WITH CHECK (customer_id=nullif(current_setting('app.customer_id',true),'')::uuid);
GRANT SELECT,INSERT ON platform.source_storage TO scada_storage_owner;
GRANT USAGE,SELECT ON SEQUENCE platform.source_storage_storage_number_seq TO scada_storage_owner;
GRANT SELECT ON platform.source_storage TO scada_worker,scada_registry;

CREATE FUNCTION platform.guard_source_table_write() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,platform AS $$
BEGIN
    IF current_user<>'scada_storage_owner' THEN
        RAISE EXCEPTION 'These collected-data tables are maintained automatically; edit source configuration through the management tools.' USING ERRCODE='42501';
    END IF;
    IF TG_OP='DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END $$;
ALTER FUNCTION platform.guard_source_table_write() OWNER TO scada_storage_owner;
REVOKE ALL ON FUNCTION platform.guard_source_table_write() FROM PUBLIC;

CREATE FUNCTION platform.ensure_source_storage(source uuid) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,platform SET row_security=off AS $$
DECLARE destination text; cid uuid;
BEGIN
    SELECT schema_name INTO destination FROM platform.source_storage WHERE source_id=source;
    IF destination IS NOT NULL THEN RETURN destination; END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended('source-storage:'||source::text,0));
    SELECT schema_name INTO destination FROM platform.source_storage WHERE source_id=source;
    IF destination IS NOT NULL THEN RETURN destination; END IF;
    SELECT customer_id INTO cid FROM platform.sources WHERE source_id=source;
    IF cid IS NULL THEN RAISE EXCEPTION 'Unknown source identity' USING ERRCODE='23503'; END IF;
    INSERT INTO platform.source_storage(source_id,customer_id) VALUES (source,cid) RETURNING schema_name INTO destination;
    IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname=destination) THEN
        RAISE EXCEPTION 'The generated source schema name is already in use' USING ERRCODE='42P06';
    END IF;
    EXECUTE format('CREATE SCHEMA %I AUTHORIZATION scada_storage_owner',destination);
    EXECUTE format('REVOKE ALL ON SCHEMA %I FROM PUBLIC',destination);
    EXECUTE format($ddl$CREATE TABLE %I.alarmhistory (
        id integer NOT NULL,
        al_start_time timestamp without time zone,
        al_norm_time timestamp without time zone,
        al_ack_time timestamp without time zone,
        al_event_time timestamp without time zone,
        last_update timestamp without time zone,
        al_start_time_ms integer,
        al_norm_time_ms integer,
        al_ack_time_ms integer,
        al_event_time_ms integer,
        last_update_ms integer,
        al_ack boolean,
        al_active boolean,
        al_ack_req boolean,
        al_deleted boolean,
        al_tag text,
        al_message text,
        al_selection text,
        al_station text,
        al_custom1 text,
        al_user text,
        al_user_full text,
        al_user_comment text,
        al_tag_value character varying,
        al_prev_tag_value character varying,
        al_group integer,
        al_priority integer,
        al_type integer,
        revision_id uuid PRIMARY KEY,
        customer_id uuid NOT NULL,
        source_id uuid NOT NULL,
        generation_id uuid NOT NULL,
        source_table text NOT NULL,
        content_hash text NOT NULL,
        received_at timestamptz NOT NULL,
        source_timezone text NOT NULL,
        ordering_uncertain boolean NOT NULL,
        mapping_status text NOT NULL,
        equipment text,
        identification_status text NOT NULL,
        CHECK (source_table='alarmhistory'),
        CHECK (source_id=%L::uuid AND customer_id=%L::uuid),
        FOREIGN KEY (customer_id,source_id,generation_id,source_table,id,revision_id) REFERENCES platform.alarm_event_revisions(customer_id,source_id,generation_id,source_table,source_record_id,revision_id))$ddl$,destination,source,cid);
    EXECUTE format('ALTER TABLE %I.alarmhistory ENABLE ROW LEVEL SECURITY',destination);
    EXECUTE format('ALTER TABLE %I.alarmhistory FORCE ROW LEVEL SECURITY',destination);
    EXECUTE format($ddl$CREATE POLICY customer_scope ON %I.alarmhistory
        USING (customer_id=nullif(current_setting('app.customer_id',true),'')::uuid)
        WITH CHECK (customer_id=nullif(current_setting('app.customer_id',true),'')::uuid)$ddl$,destination);
    EXECUTE format('CREATE INDEX ON %I.alarmhistory(generation_id,id)',destination);
    EXECUTE format('CREATE TRIGGER managed_records BEFORE INSERT OR UPDATE OR DELETE ON %I.alarmhistory FOR EACH ROW EXECUTE FUNCTION platform.guard_source_table_write()',destination);
    EXECUTE format($ddl$CREATE TABLE %I.eventhistory (
        id integer NOT NULL,
        ev_type integer,
        ev_time timestamp without time zone,
        last_update timestamp without time zone,
        ev_time_ms integer,
        last_update_ms integer,
        ev_info text,
        ev_source text,
        ev_message text,
        ev_station text,
        ev_user text,
        ev_user_full text,
        ev_comment text,
        ev_deleted boolean,
        ev_value character varying,
        ev_prev_value character varying,
        revision_id uuid PRIMARY KEY,
        customer_id uuid NOT NULL,
        source_id uuid NOT NULL,
        generation_id uuid NOT NULL,
        source_table text NOT NULL,
        content_hash text NOT NULL,
        received_at timestamptz NOT NULL,
        source_timezone text NOT NULL,
        ordering_uncertain boolean NOT NULL,
        mapping_status text NOT NULL,
        equipment text,
        identification_status text NOT NULL,
        CHECK (source_table='eventhistory'),
        CHECK (source_id=%L::uuid AND customer_id=%L::uuid),
        FOREIGN KEY (customer_id,source_id,generation_id,source_table,id,revision_id) REFERENCES platform.alarm_event_revisions(customer_id,source_id,generation_id,source_table,source_record_id,revision_id))$ddl$,destination,source,cid);
    EXECUTE format('ALTER TABLE %I.eventhistory ENABLE ROW LEVEL SECURITY',destination);
    EXECUTE format('ALTER TABLE %I.eventhistory FORCE ROW LEVEL SECURITY',destination);
    EXECUTE format($ddl$CREATE POLICY customer_scope ON %I.eventhistory
        USING (customer_id=nullif(current_setting('app.customer_id',true),'')::uuid)
        WITH CHECK (customer_id=nullif(current_setting('app.customer_id',true),'')::uuid)$ddl$,destination);
    EXECUTE format('CREATE INDEX ON %I.eventhistory(generation_id,id)',destination);
    EXECUTE format('CREATE TRIGGER managed_records BEFORE INSERT OR UPDATE OR DELETE ON %I.eventhistory FOR EACH ROW EXECUTE FUNCTION platform.guard_source_table_write()',destination);
    RETURN destination;
END $$;
ALTER FUNCTION platform.ensure_source_storage(uuid) OWNER TO scada_storage_owner;
REVOKE ALL ON FUNCTION platform.ensure_source_storage(uuid) FROM PUBLIC;

CREATE FUNCTION platform.sync_source_revision(revision uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,platform SET row_security=off AS $$
DECLARE destination text; source uuid; kind text;
BEGIN
    SELECT source_id,source_table INTO source,kind FROM platform.alarm_event_revisions WHERE revision_id=revision;
    IF source IS NULL THEN RETURN; END IF;
    destination:=platform.ensure_source_storage(source);
    IF kind='alarmhistory' THEN
        EXECUTE format($sync$INSERT INTO %I.alarmhistory (id, al_start_time, al_norm_time, al_ack_time, al_event_time, last_update, al_start_time_ms, al_norm_time_ms, al_ack_time_ms, al_event_time_ms, last_update_ms, al_ack, al_active, al_ack_req, al_deleted, al_tag, al_message, al_selection, al_station, al_custom1, al_user, al_user_full, al_user_comment, al_tag_value, al_prev_tag_value, al_group, al_priority, al_type, revision_id, customer_id, source_id, generation_id, source_table, content_hash, received_at, source_timezone, ordering_uncertain, mapping_status, equipment, identification_status)
        SELECT r.source_record_id, n.al_start_time, n.al_norm_time, n.al_ack_time, n.al_event_time, n.last_update, n.al_start_time_ms, n.al_norm_time_ms, n.al_ack_time_ms, n.al_event_time_ms, n.last_update_ms, n.al_ack, n.al_active, n.al_ack_req, n.al_deleted, n.al_tag, n.al_message, n.al_selection, n.al_station, n.al_custom1, n.al_user, n.al_user_full, n.al_user_comment, n.al_tag_value, n.al_prev_tag_value, n.al_group, n.al_priority, n.al_type, r.revision_id, r.customer_id, r.source_id, r.generation_id, r.source_table, r.content_hash, r.received_at, r.source_timezone, r.ordering_uncertain, r.mapping_status, names.equipment, COALESCE(i.status,'pending')
        FROM platform.alarm_event_revisions r
        LEFT JOIN platform.machine_interpretations i ON i.revision_id=r.revision_id
        CROSS JOIN LATERAL jsonb_to_record(r.original_payload) AS n(id integer, al_start_time timestamp without time zone, al_norm_time timestamp without time zone, al_ack_time timestamp without time zone, al_event_time timestamp without time zone, last_update timestamp without time zone, al_start_time_ms integer, al_norm_time_ms integer, al_ack_time_ms integer, al_event_time_ms integer, last_update_ms integer, al_ack boolean, al_active boolean, al_ack_req boolean, al_deleted boolean, al_tag text, al_message text, al_selection text, al_station text, al_custom1 text, al_user text, al_user_full text, al_user_comment text, al_tag_value character varying, al_prev_tag_value character varying, al_group integer, al_priority integer, al_type integer)
        LEFT JOIN LATERAL (
            SELECT string_agg(DISTINCT c->>'label',', ' ORDER BY c->>'label') equipment
            FROM jsonb_array_elements(COALESCE(i.candidates,'[]'::jsonb)) c
        ) names ON true WHERE r.revision_id=$1
        ON CONFLICT (revision_id) DO UPDATE SET id=EXCLUDED.id, al_start_time=EXCLUDED.al_start_time, al_norm_time=EXCLUDED.al_norm_time, al_ack_time=EXCLUDED.al_ack_time, al_event_time=EXCLUDED.al_event_time, last_update=EXCLUDED.last_update, al_start_time_ms=EXCLUDED.al_start_time_ms, al_norm_time_ms=EXCLUDED.al_norm_time_ms, al_ack_time_ms=EXCLUDED.al_ack_time_ms, al_event_time_ms=EXCLUDED.al_event_time_ms, last_update_ms=EXCLUDED.last_update_ms, al_ack=EXCLUDED.al_ack, al_active=EXCLUDED.al_active, al_ack_req=EXCLUDED.al_ack_req, al_deleted=EXCLUDED.al_deleted, al_tag=EXCLUDED.al_tag, al_message=EXCLUDED.al_message, al_selection=EXCLUDED.al_selection, al_station=EXCLUDED.al_station, al_custom1=EXCLUDED.al_custom1, al_user=EXCLUDED.al_user, al_user_full=EXCLUDED.al_user_full, al_user_comment=EXCLUDED.al_user_comment, al_tag_value=EXCLUDED.al_tag_value, al_prev_tag_value=EXCLUDED.al_prev_tag_value, al_group=EXCLUDED.al_group, al_priority=EXCLUDED.al_priority, al_type=EXCLUDED.al_type, customer_id=EXCLUDED.customer_id, source_id=EXCLUDED.source_id, generation_id=EXCLUDED.generation_id, source_table=EXCLUDED.source_table, content_hash=EXCLUDED.content_hash, received_at=EXCLUDED.received_at, source_timezone=EXCLUDED.source_timezone, ordering_uncertain=EXCLUDED.ordering_uncertain, mapping_status=EXCLUDED.mapping_status, equipment=EXCLUDED.equipment, identification_status=EXCLUDED.identification_status$sync$,destination) USING revision;
    END IF;
    IF kind='eventhistory' THEN
        EXECUTE format($sync$INSERT INTO %I.eventhistory (id, ev_type, ev_time, last_update, ev_time_ms, last_update_ms, ev_info, ev_source, ev_message, ev_station, ev_user, ev_user_full, ev_comment, ev_deleted, ev_value, ev_prev_value, revision_id, customer_id, source_id, generation_id, source_table, content_hash, received_at, source_timezone, ordering_uncertain, mapping_status, equipment, identification_status)
        SELECT r.source_record_id, n.ev_type, n.ev_time, n.last_update, n.ev_time_ms, n.last_update_ms, n.ev_info, n.ev_source, n.ev_message, n.ev_station, n.ev_user, n.ev_user_full, n.ev_comment, n.ev_deleted, n.ev_value, n.ev_prev_value, r.revision_id, r.customer_id, r.source_id, r.generation_id, r.source_table, r.content_hash, r.received_at, r.source_timezone, r.ordering_uncertain, r.mapping_status, names.equipment, COALESCE(i.status,'pending')
        FROM platform.alarm_event_revisions r
        LEFT JOIN platform.machine_interpretations i ON i.revision_id=r.revision_id
        CROSS JOIN LATERAL jsonb_to_record(r.original_payload) AS n(id integer, ev_type integer, ev_time timestamp without time zone, last_update timestamp without time zone, ev_time_ms integer, last_update_ms integer, ev_info text, ev_source text, ev_message text, ev_station text, ev_user text, ev_user_full text, ev_comment text, ev_deleted boolean, ev_value character varying, ev_prev_value character varying)
        LEFT JOIN LATERAL (
            SELECT string_agg(DISTINCT c->>'label',', ' ORDER BY c->>'label') equipment
            FROM jsonb_array_elements(COALESCE(i.candidates,'[]'::jsonb)) c
        ) names ON true WHERE r.revision_id=$1
        ON CONFLICT (revision_id) DO UPDATE SET id=EXCLUDED.id, ev_type=EXCLUDED.ev_type, ev_time=EXCLUDED.ev_time, last_update=EXCLUDED.last_update, ev_time_ms=EXCLUDED.ev_time_ms, last_update_ms=EXCLUDED.last_update_ms, ev_info=EXCLUDED.ev_info, ev_source=EXCLUDED.ev_source, ev_message=EXCLUDED.ev_message, ev_station=EXCLUDED.ev_station, ev_user=EXCLUDED.ev_user, ev_user_full=EXCLUDED.ev_user_full, ev_comment=EXCLUDED.ev_comment, ev_deleted=EXCLUDED.ev_deleted, ev_value=EXCLUDED.ev_value, ev_prev_value=EXCLUDED.ev_prev_value, customer_id=EXCLUDED.customer_id, source_id=EXCLUDED.source_id, generation_id=EXCLUDED.generation_id, source_table=EXCLUDED.source_table, content_hash=EXCLUDED.content_hash, received_at=EXCLUDED.received_at, source_timezone=EXCLUDED.source_timezone, ordering_uncertain=EXCLUDED.ordering_uncertain, mapping_status=EXCLUDED.mapping_status, equipment=EXCLUDED.equipment, identification_status=EXCLUDED.identification_status$sync$,destination) USING revision;
    END IF;
END $$;
ALTER FUNCTION platform.sync_source_revision(uuid) OWNER TO scada_storage_owner;
REVOKE ALL ON FUNCTION platform.sync_source_revision(uuid) FROM PUBLIC;

CREATE FUNCTION platform.source_storage_registration() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,platform SET row_security=off AS $$
BEGIN
    PERFORM platform.ensure_source_storage(NEW.source_id);
    RETURN NEW;
END $$;
ALTER FUNCTION platform.source_storage_registration() OWNER TO scada_storage_owner;
REVOKE ALL ON FUNCTION platform.source_storage_registration() FROM PUBLIC;
CREATE TRIGGER source_storage_registration AFTER INSERT ON platform.sources
    FOR EACH ROW EXECUTE FUNCTION platform.source_storage_registration();

CREATE FUNCTION platform.source_storage_revision() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,platform SET row_security=off AS $$
BEGIN
    PERFORM platform.sync_source_revision(NEW.revision_id);
    RETURN NEW;
END $$;
ALTER FUNCTION platform.source_storage_revision() OWNER TO scada_storage_owner;
REVOKE ALL ON FUNCTION platform.source_storage_revision() FROM PUBLIC;
CREATE TRIGGER source_storage_revision AFTER INSERT OR UPDATE ON platform.alarm_event_revisions
    FOR EACH ROW EXECUTE FUNCTION platform.source_storage_revision();
-- Claims do not rewrite the native row; completed identifications do.
CREATE TRIGGER source_storage_identification AFTER INSERT OR UPDATE ON platform.machine_interpretations
    FOR EACH ROW WHEN (NEW.status<>'processing') EXECUTE FUNCTION platform.source_storage_revision();
REVOKE CREATE ON SCHEMA platform FROM scada_storage_owner;

DO $$ DECLARE item record; BEGIN
    FOR item IN SELECT s.source_id FROM platform.sources s
        WHERE s.deleted_at IS NULL OR EXISTS (
            SELECT 1 FROM platform.alarm_event_revisions r WHERE r.source_id=s.source_id)
        ORDER BY s.deleted_at IS NOT NULL,s.source_id LOOP
        PERFORM platform.ensure_source_storage(item.source_id);
    END LOOP;
    FOR item IN SELECT revision_id FROM platform.alarm_event_revisions ORDER BY revision_id LOOP
        PERFORM platform.sync_source_revision(item.revision_id);
    END LOOP;
END $$;
