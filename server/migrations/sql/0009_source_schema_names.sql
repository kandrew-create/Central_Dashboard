-- Central storage only: retain table OIDs/data and name schemas from source labels.
ALTER TABLE platform.source_storage ALTER COLUMN schema_name DROP EXPRESSION;
ALTER TABLE platform.source_storage ALTER COLUMN schema_name SET NOT NULL;
GRANT UPDATE(schema_name) ON platform.source_storage TO scada_storage_owner;
GRANT CREATE ON SCHEMA platform TO scada_storage_owner;

CREATE FUNCTION platform.source_schema_name(label text,source uuid) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,platform SET row_security=off AS $$
DECLARE base text; candidate text; suffix text; attempt integer:=0;
BEGIN
    -- Serialize allocation/rename across sources to avoid cross-source DDL races.
    PERFORM pg_advisory_xact_lock(hashtextextended('source-schema-names',0));
    base:=btrim(regexp_replace(replace(label,',','_'),'[[:cntrl:]]',' ','g'));
    IF base IS NULL OR base='' THEN base:='SCADA'; END IF;
    IF left(base,3)='pg_' THEN base:='SCADA_'||base; END IF;
    WHILE octet_length(base)>63 LOOP base:=left(base,length(base)-1); END LOOP;
    candidate:=base;
    LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname=candidate)
            AND NOT EXISTS (SELECT 1 FROM platform.source_storage WHERE schema_name=candidate AND source_id<>source)
            OR EXISTS (SELECT 1 FROM platform.source_storage WHERE schema_name=candidate AND source_id=source) THEN
            RETURN candidate;
        END IF;
        attempt:=attempt+1;
        suffix:='_'||replace(source::text,'-','')||CASE WHEN attempt=1 THEN '' ELSE '_'||attempt::text END;
        candidate:=base;
        WHILE octet_length(candidate||suffix)>63 LOOP candidate:=left(candidate,length(candidate)-1); END LOOP;
        candidate:=candidate||suffix;
    END LOOP;
END $$;
ALTER FUNCTION platform.source_schema_name(text,uuid) OWNER TO scada_storage_owner;
REVOKE ALL ON FUNCTION platform.source_schema_name(text,uuid) FROM PUBLIC;

CREATE FUNCTION platform.rename_source_storage(source uuid,label text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,platform SET row_security=off AS $$
DECLARE previous text; destination text;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended('source-storage:'||source::text,0));
    SELECT schema_name INTO previous FROM platform.source_storage WHERE source_id=source;
    IF previous IS NULL THEN RETURN; END IF;
    destination:=platform.source_schema_name(label,source);
    IF previous<>destination THEN
        EXECUTE format('ALTER SCHEMA %I RENAME TO %I',previous,destination);
        UPDATE platform.source_storage SET schema_name=destination WHERE source_id=source;
    END IF;
END $$;
ALTER FUNCTION platform.rename_source_storage(uuid,text) OWNER TO scada_storage_owner;
REVOKE ALL ON FUNCTION platform.rename_source_storage(uuid,text) FROM PUBLIC;

CREATE OR REPLACE FUNCTION platform.ensure_source_storage(source uuid) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,platform SET row_security=off AS $$
DECLARE destination text; cid uuid; label text;
BEGIN
    SELECT schema_name INTO destination FROM platform.source_storage WHERE source_id=source;
    IF destination IS NOT NULL THEN RETURN destination; END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended('source-storage:'||source::text,0));
    SELECT schema_name INTO destination FROM platform.source_storage WHERE source_id=source;
    IF destination IS NOT NULL THEN RETURN destination; END IF;
    SELECT customer_id,name INTO cid,label FROM platform.sources WHERE source_id=source;
    IF cid IS NULL THEN RAISE EXCEPTION 'Unknown source identity' USING ERRCODE='23503'; END IF;
    destination:=platform.source_schema_name(label,source);
    INSERT INTO platform.source_storage(source_id,customer_id,schema_name) VALUES (source,cid,destination);
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

CREATE FUNCTION platform.source_storage_name_changed() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,platform SET row_security=off AS $$
BEGIN
    PERFORM platform.rename_source_storage(NEW.source_id,NEW.name);
    RETURN NEW;
END $$;
ALTER FUNCTION platform.source_storage_name_changed() OWNER TO scada_storage_owner;
REVOKE ALL ON FUNCTION platform.source_storage_name_changed() FROM PUBLIC;
CREATE TRIGGER source_storage_name_changed AFTER UPDATE OF name ON platform.sources
    FOR EACH ROW WHEN (OLD.name IS DISTINCT FROM NEW.name)
    EXECUTE FUNCTION platform.source_storage_name_changed();

DO $$ DECLARE item record; BEGIN
    FOR item IN SELECT st.source_id,s.name FROM platform.source_storage st
        JOIN platform.sources s USING(source_id) ORDER BY st.storage_number LOOP
        PERFORM platform.rename_source_storage(item.source_id,item.name);
    END LOOP;
END $$;
REVOKE CREATE ON SCHEMA platform FROM scada_storage_owner;
