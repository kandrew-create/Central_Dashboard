-- Central storage only. Shared UUID dimensions remain live, invoker-security
-- views of the authoritative registration tables; facts are now stored.
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='scada_warehouse_owner') THEN
        CREATE ROLE scada_warehouse_owner NOLOGIN NOSUPERUSER NOBYPASSRLS;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='scada_warehouse_owner'
        AND (rolcanlogin OR rolsuper OR rolbypassrls OR rolcreatedb OR rolcreaterole OR rolreplication)) THEN
        RAISE EXCEPTION 'Invalid warehouse maintenance owner';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles r WHERE r.rolname IN
        ('scada_ingest','scada_worker','scada_reader','scada_registry')
        AND pg_has_role(r.oid,'scada_warehouse_owner','MEMBER')) THEN
        RAISE EXCEPTION 'Runtime roles must not inherit warehouse ownership';
    END IF;
END $$;
CREATE SCHEMA reporting;
REVOKE ALL ON SCHEMA reporting FROM PUBLIC;
GRANT USAGE ON SCHEMA warehouse,reporting TO scada_warehouse_owner,scada_reader;
GRANT USAGE ON SCHEMA platform TO scada_warehouse_owner;
GRANT SELECT ON platform.sources,platform.source_generations,platform.machines,
    platform.alarm_event_revisions,platform.latest_alarm_state,
    platform.machine_interpretations,platform.upload_batches TO scada_warehouse_owner;
DO $$ DECLARE name text; BEGIN
    FOREACH name IN ARRAY ARRAY['sources','source_generations','machines',
        'alarm_event_revisions','latest_alarm_state','machine_interpretations','upload_batches'] LOOP
        EXECUTE format('CREATE POLICY warehouse_maintenance ON platform.%I TO scada_warehouse_owner USING(true)',name);
    END LOOP;
END $$;

-- Keep the old projection as a private, scoped reconstruction query. The
-- existing public fact name becomes a table with the same safe columns.
ALTER VIEW warehouse.fact_alarm_occurrence RENAME TO alarm_occurrence_projection;
REVOKE ALL ON warehouse.alarm_occurrence_projection FROM scada_reader;
GRANT SELECT ON warehouse.alarm_occurrence_projection TO scada_warehouse_owner;
CREATE TABLE warehouse.fact_alarm_occurrence AS
    SELECT p.*,clock_timestamp() refreshed_at FROM warehouse.alarm_occurrence_projection p WITH NO DATA;
ALTER TABLE warehouse.fact_alarm_occurrence
    ALTER customer_id SET NOT NULL, ALTER site_id SET NOT NULL, ALTER project_id SET NOT NULL,
    ALTER source_id SET NOT NULL, ALTER generation_id SET NOT NULL, ALTER source_record_id SET NOT NULL,
    ALTER saved_versions SET NOT NULL, ALTER first_saved_at SET NOT NULL, ALTER last_saved_at SET NOT NULL,
    ALTER source_time_uncertain SET NOT NULL, ALTER ordering_uncertain SET NOT NULL,
    ALTER refreshed_at SET NOT NULL,
    ADD PRIMARY KEY(customer_id,source_id,generation_id,source_record_id),
    ADD FOREIGN KEY(customer_id,source_id,generation_id)
        REFERENCES platform.source_generations(customer_id,source_id,generation_id) ON DELETE CASCADE,
    ADD FOREIGN KEY(customer_id,site_id,project_id,machine_id)
        REFERENCES platform.machines(customer_id,site_id,project_id,machine_id),
    ADD CHECK(saved_versions>0),
    ADD CHECK(NOT ordering_uncertain OR (verified_latest_revision_id IS NULL AND machine_id IS NULL
        AND active IS NULL AND ack IS NULL AND deleted IS NULL)),
    ADD CHECK(source_time_uncertain=(occurrence_started_utc IS NULL));
CREATE INDEX alarm_fact_received ON warehouse.fact_alarm_occurrence(customer_id,source_id,first_saved_at);
CREATE INDEX alarm_fact_date ON warehouse.fact_alarm_occurrence(customer_id,source_id,occurrence_date_utc,machine_id);

-- Events use their native event timestamp and source update markers. Equal or
-- uncertain markers never select a latest revision by upload/arrival order.
CREATE VIEW warehouse.event_occurrence_projection WITH(security_invoker=true) AS
WITH observations AS (
    SELECT r.*,row_number() OVER(
        PARTITION BY customer_id,source_id,generation_id,source_record_id
        ORDER BY last_update_local DESC NULLS LAST,last_update_ms DESC NULLS LAST) position,
        count(*) OVER(PARTITION BY customer_id,source_id,generation_id,source_record_id,
            last_update_local,last_update_ms) marker_ties
    FROM platform.alarm_event_revisions r WHERE source_table='eventhistory'
), history AS (
    SELECT customer_id,site_id,project_id,source_id,generation_id,source_record_id,
        count(*) saved_versions,min(received_at) first_saved_at,max(received_at) last_saved_at,
        CASE WHEN bool_and(event_time_quality='known') AND count(DISTINCT event_time_utc)=1
            THEN min(event_time_utc) END occurrence_occurred_utc,
        bool_and(NOT ordering_uncertain AND last_update_local IS NOT NULL AND last_update_ms IS NOT NULL) order_known,
        CASE WHEN count(message)=count(*) AND count(DISTINCT message)=1 THEN min(message) END agreed_message
    FROM observations GROUP BY customer_id,site_id,project_id,source_id,generation_id,source_record_id
)
SELECT h.customer_id,h.site_id,h.project_id,h.source_id,h.generation_id,h.source_record_id,
    h.saved_versions,h.first_saved_at,h.last_saved_at,h.occurrence_occurred_utc,
    (h.occurrence_occurred_utc AT TIME ZONE 'UTC')::date occurrence_date_utc,
    h.occurrence_occurred_utc IS NULL source_time_uncertain,r.revision_id IS NULL ordering_uncertain,
    CASE WHEN r.revision_id IS NOT NULL THEN r.message ELSE h.agreed_message END message,
    r.revision_id verified_latest_revision_id,r.mapping_status,r.machine_id,r.deleted,
    registered.machine_id registered_machine_id,registered.machine_tag registered_machine_tag
FROM history h
LEFT JOIN observations r ON
    (r.customer_id,r.source_id,r.generation_id,r.source_record_id)=
    (h.customer_id,h.source_id,h.generation_id,h.source_record_id)
    AND r.position=1 AND h.order_known AND r.marker_ties=1
LEFT JOIN platform.machine_interpretations i ON i.revision_id=r.revision_id AND i.status='registered'
LEFT JOIN platform.upload_batches b ON b.upload_id=r.upload_id
LEFT JOIN LATERAL (
    SELECT m.machine_id,m.machine_tag
    FROM platform.machines m
    WHERE jsonb_array_length(COALESCE(i.candidates,'[]'::jsonb))=1
      AND i.candidates->0->>'field'='registered_machine_tag'
      AND m.machine_id::text=i.candidates->0->>'machine_id'
      AND (m.customer_id,m.site_id,m.project_id)=(h.customer_id,h.site_id,h.project_id)
      AND b.payload->'allowed_machines' ? m.machine_id::text
) registered ON true;
GRANT SELECT ON warehouse.event_occurrence_projection TO scada_warehouse_owner;
CREATE TABLE warehouse.fact_event_occurrence AS
    SELECT p.*,clock_timestamp() refreshed_at FROM warehouse.event_occurrence_projection p WITH NO DATA;
ALTER TABLE warehouse.fact_event_occurrence
    ALTER customer_id SET NOT NULL, ALTER site_id SET NOT NULL, ALTER project_id SET NOT NULL,
    ALTER source_id SET NOT NULL, ALTER generation_id SET NOT NULL, ALTER source_record_id SET NOT NULL,
    ALTER saved_versions SET NOT NULL, ALTER first_saved_at SET NOT NULL, ALTER last_saved_at SET NOT NULL,
    ALTER source_time_uncertain SET NOT NULL, ALTER ordering_uncertain SET NOT NULL,
    ALTER refreshed_at SET NOT NULL,
    ADD PRIMARY KEY(customer_id,source_id,generation_id,source_record_id),
    ADD FOREIGN KEY(customer_id,source_id,generation_id)
        REFERENCES platform.source_generations(customer_id,source_id,generation_id) ON DELETE CASCADE,
    ADD FOREIGN KEY(customer_id,site_id,project_id,machine_id)
        REFERENCES platform.machines(customer_id,site_id,project_id,machine_id),
    ADD FOREIGN KEY(customer_id,site_id,project_id,registered_machine_id)
        REFERENCES platform.machines(customer_id,site_id,project_id,machine_id),
    ADD CHECK(saved_versions>0),
    ADD CHECK(NOT ordering_uncertain OR (verified_latest_revision_id IS NULL AND machine_id IS NULL
        AND registered_machine_id IS NULL AND deleted IS NULL)),
    ADD CHECK(source_time_uncertain=(occurrence_occurred_utc IS NULL));
CREATE INDEX event_fact_received ON warehouse.fact_event_occurrence(customer_id,source_id,first_saved_at);
CREATE INDEX event_fact_date ON warehouse.fact_event_occurrence(customer_id,source_id,occurrence_date_utc);

CREATE TABLE warehouse.refresh_queue (
    customer_id uuid NOT NULL,source_id uuid NOT NULL,generation_id uuid NOT NULL,
    source_table text NOT NULL CHECK(source_table IN ('alarmhistory','eventhistory')),source_record_id integer NOT NULL,
    queued_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    available_at timestamptz NOT NULL DEFAULT clock_timestamp(),attempts integer NOT NULL DEFAULT 0,
    last_error_code text,
    PRIMARY KEY(customer_id,source_id,generation_id,source_table,source_record_id),
    FOREIGN KEY(customer_id,source_id,generation_id)
        REFERENCES platform.source_generations(customer_id,source_id,generation_id) ON DELETE CASCADE
);
CREATE INDEX warehouse_refresh_ready ON warehouse.refresh_queue(available_at,queued_at);
CREATE TABLE warehouse.source_refresh_queue (
    customer_id uuid NOT NULL,source_id uuid NOT NULL,
    queued_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(customer_id,source_id),
    FOREIGN KEY(customer_id,source_id) REFERENCES platform.sources(customer_id,source_id) ON DELETE CASCADE
);
CREATE TABLE reporting.refresh_queue (
    customer_id uuid NOT NULL,source_id uuid NOT NULL,occurrence_date_utc date,
    queued_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE NULLS NOT DISTINCT(customer_id,source_id,occurrence_date_utc),
    FOREIGN KEY(customer_id,source_id) REFERENCES platform.sources(customer_id,source_id) ON DELETE CASCADE
);
CREATE TABLE reporting.alarm_hourly_summary (
    customer_id uuid NOT NULL,source_id uuid NOT NULL,occurrence_hour_utc timestamptz,
    occurrences bigint NOT NULL,saved_versions bigint NOT NULL,
    uncertain_order_occurrences bigint NOT NULL,uncertain_time_occurrences bigint NOT NULL,
    refreshed_at timestamptz NOT NULL,
    UNIQUE NULLS NOT DISTINCT(customer_id,source_id,occurrence_hour_utc),
    FOREIGN KEY(customer_id,source_id) REFERENCES platform.sources(customer_id,source_id) ON DELETE CASCADE
);
CREATE TABLE reporting.alarm_daily_summary (
    customer_id uuid NOT NULL,source_id uuid NOT NULL,occurrence_date_utc date,
    occurrences bigint NOT NULL,saved_versions bigint NOT NULL,
    uncertain_order_occurrences bigint NOT NULL,uncertain_time_occurrences bigint NOT NULL,
    refreshed_at timestamptz NOT NULL,
    UNIQUE NULLS NOT DISTINCT(customer_id,source_id,occurrence_date_utc),
    FOREIGN KEY(customer_id,source_id) REFERENCES platform.sources(customer_id,source_id) ON DELETE CASCADE
);
CREATE TABLE reporting.equipment_alarm_summary (
    customer_id uuid NOT NULL,source_id uuid NOT NULL,occurrence_date_utc date,machine_id uuid,
    occurrences bigint NOT NULL,saved_versions bigint NOT NULL,refreshed_at timestamptz NOT NULL,
    UNIQUE NULLS NOT DISTINCT(customer_id,source_id,occurrence_date_utc,machine_id),
    FOREIGN KEY(customer_id,source_id) REFERENCES platform.sources(customer_id,source_id) ON DELETE CASCADE,
    FOREIGN KEY(machine_id) REFERENCES platform.machines(machine_id)
);
CREATE TABLE reporting.source_upload_summary (
    customer_id uuid NOT NULL,source_id uuid NOT NULL,committed_batches bigint NOT NULL,
    declared_records bigint NOT NULL,payload_bytes bigint NOT NULL,last_received_at timestamptz,
    awaiting_processing_batches bigint NOT NULL,completed_batches bigint NOT NULL,
    quarantined_batches bigint NOT NULL,failed_batches bigint NOT NULL,refreshed_at timestamptz NOT NULL,
    PRIMARY KEY(customer_id,source_id),
    FOREIGN KEY(customer_id,source_id) REFERENCES platform.sources(customer_id,source_id) ON DELETE CASCADE
);
CREATE INDEX warehouse_upload_source ON platform.upload_batches(customer_id,source_id,received_at);

-- Maintenance ownership never escapes through runtime role membership.
DO $$ DECLARE item record; BEGIN
    FOR item IN SELECT n.nspname,c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname IN ('warehouse','reporting') AND c.relkind='r' LOOP
        EXECUTE format('ALTER TABLE %I.%I ENABLE ROW LEVEL SECURITY',item.nspname,item.relname);
        EXECUTE format('ALTER TABLE %I.%I FORCE ROW LEVEL SECURITY',item.nspname,item.relname);
        EXECUTE format('CREATE POLICY customer_scope ON %I.%I USING
            (customer_id=nullif(current_setting(''app.customer_id'',true),'''')::uuid)
            WITH CHECK(customer_id=nullif(current_setting(''app.customer_id'',true),'''')::uuid)',item.nspname,item.relname);
        EXECUTE format('CREATE POLICY warehouse_maintenance ON %I.%I TO scada_warehouse_owner USING(true) WITH CHECK(true)',item.nspname,item.relname);
        EXECUTE format('ALTER TABLE %I.%I OWNER TO scada_warehouse_owner',item.nspname,item.relname);
        EXECUTE format('REVOKE ALL ON %I.%I FROM PUBLIC',item.nspname,item.relname);
        EXECUTE format('GRANT SELECT ON %I.%I TO scada_reader',item.nspname,item.relname);
    END LOOP;
END $$;

CREATE FUNCTION warehouse.queue_occurrence() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,warehouse SET row_security=on AS $$
DECLARE item jsonb;
BEGIN
    item:=CASE WHEN TG_OP='DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
    INSERT INTO warehouse.refresh_queue(customer_id,source_id,generation_id,source_table,source_record_id)
    VALUES((item->>'customer_id')::uuid,(item->>'source_id')::uuid,(item->>'generation_id')::uuid,
        item->>'source_table',(item->>'source_record_id')::integer)
    ON CONFLICT(customer_id,source_id,generation_id,source_table,source_record_id)
        DO UPDATE SET available_at=clock_timestamp(),attempts=0,last_error_code=NULL;
    RETURN NULL;
END $$;
CREATE FUNCTION warehouse.queue_source() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,warehouse SET row_security=on AS $$
DECLARE item jsonb;
BEGIN
    item:=CASE WHEN TG_OP='DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
    INSERT INTO warehouse.source_refresh_queue(customer_id,source_id)
        VALUES((item->>'customer_id')::uuid,(item->>'source_id')::uuid)
    ON CONFLICT(customer_id,source_id) DO NOTHING;
    RETURN NULL;
END $$;
CREATE TRIGGER warehouse_revision_changed AFTER INSERT OR UPDATE OR DELETE ON platform.alarm_event_revisions
    FOR EACH ROW EXECUTE FUNCTION warehouse.queue_occurrence();
CREATE TRIGGER warehouse_latest_inserted AFTER INSERT OR DELETE ON platform.latest_alarm_state
    FOR EACH ROW EXECUTE FUNCTION warehouse.queue_occurrence();
CREATE TRIGGER warehouse_latest_changed AFTER UPDATE OF revision_id,ordering_uncertain ON platform.latest_alarm_state
    FOR EACH ROW WHEN (OLD.revision_id IS DISTINCT FROM NEW.revision_id OR OLD.ordering_uncertain IS DISTINCT FROM NEW.ordering_uncertain)
    EXECUTE FUNCTION warehouse.queue_occurrence();
CREATE TRIGGER warehouse_identification_changed AFTER INSERT OR UPDATE OF status,candidates OR DELETE
    ON platform.machine_interpretations FOR EACH ROW EXECUTE FUNCTION warehouse.queue_occurrence();
CREATE TRIGGER warehouse_upload_changed AFTER INSERT OR UPDATE OF processing_status OR DELETE
    ON platform.upload_batches FOR EACH ROW EXECUTE FUNCTION warehouse.queue_source();

CREATE FUNCTION warehouse.refresh_occurrence(c uuid,s uuid,g uuid,t text,r integer) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,warehouse,reporting SET row_security=on AS $$
DECLARE previous_day date; next_day date; had_previous boolean; has_next boolean;
BEGIN
    IF t='alarmhistory' THEN
        SELECT occurrence_date_utc INTO previous_day FROM warehouse.fact_alarm_occurrence
            WHERE (customer_id,source_id,generation_id,source_record_id)=(c,s,g,r);
        had_previous:=FOUND;
        DELETE FROM warehouse.fact_alarm_occurrence WHERE (customer_id,source_id,generation_id,source_record_id)=(c,s,g,r);
        INSERT INTO warehouse.fact_alarm_occurrence
            SELECT p.*,clock_timestamp() FROM warehouse.alarm_occurrence_projection p
            WHERE (customer_id,source_id,generation_id,source_record_id)=(c,s,g,r);
        SELECT occurrence_date_utc INTO next_day FROM warehouse.fact_alarm_occurrence
            WHERE (customer_id,source_id,generation_id,source_record_id)=(c,s,g,r);
        has_next:=FOUND;
        IF had_previous THEN
            INSERT INTO reporting.refresh_queue(customer_id,source_id,occurrence_date_utc) VALUES(c,s,previous_day)
                ON CONFLICT(customer_id,source_id,occurrence_date_utc) DO NOTHING;
        END IF;
        IF has_next THEN
            INSERT INTO reporting.refresh_queue(customer_id,source_id,occurrence_date_utc) VALUES(c,s,next_day)
                ON CONFLICT(customer_id,source_id,occurrence_date_utc) DO NOTHING;
        END IF;
    ELSIF t='eventhistory' THEN
        DELETE FROM warehouse.fact_event_occurrence WHERE (customer_id,source_id,generation_id,source_record_id)=(c,s,g,r);
        INSERT INTO warehouse.fact_event_occurrence
            SELECT p.*,clock_timestamp() FROM warehouse.event_occurrence_projection p
            WHERE (customer_id,source_id,generation_id,source_record_id)=(c,s,g,r);
    ELSE
        RAISE EXCEPTION 'Unsupported warehouse record type';
    END IF;
END $$;

CREATE FUNCTION reporting.refresh_alarm_day(c uuid,s uuid,d date) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,warehouse,reporting SET row_security=on AS $$
BEGIN
    DELETE FROM reporting.alarm_hourly_summary WHERE customer_id=c AND source_id=s
        AND (occurrence_hour_utc AT TIME ZONE 'UTC')::date IS NOT DISTINCT FROM d;
    INSERT INTO reporting.alarm_hourly_summary
        SELECT customer_id,source_id,date_trunc('hour',occurrence_started_utc,'UTC'),
            count(*),sum(saved_versions),count(*) FILTER(WHERE ordering_uncertain),
            count(*) FILTER(WHERE source_time_uncertain),clock_timestamp()
        FROM warehouse.fact_alarm_occurrence
        WHERE customer_id=c AND source_id=s AND occurrence_date_utc IS NOT DISTINCT FROM d
        GROUP BY customer_id,source_id,date_trunc('hour',occurrence_started_utc,'UTC');
    DELETE FROM reporting.alarm_daily_summary
        WHERE customer_id=c AND source_id=s AND occurrence_date_utc IS NOT DISTINCT FROM d;
    INSERT INTO reporting.alarm_daily_summary
        SELECT customer_id,source_id,occurrence_date_utc,count(*),sum(saved_versions),
            count(*) FILTER(WHERE ordering_uncertain),count(*) FILTER(WHERE source_time_uncertain),clock_timestamp()
        FROM warehouse.fact_alarm_occurrence
        WHERE customer_id=c AND source_id=s AND occurrence_date_utc IS NOT DISTINCT FROM d
        GROUP BY customer_id,source_id,occurrence_date_utc;
    DELETE FROM reporting.equipment_alarm_summary
        WHERE customer_id=c AND source_id=s AND occurrence_date_utc IS NOT DISTINCT FROM d;
    INSERT INTO reporting.equipment_alarm_summary
        SELECT customer_id,source_id,occurrence_date_utc,machine_id,count(*),sum(saved_versions),clock_timestamp()
        FROM warehouse.fact_alarm_occurrence
        WHERE customer_id=c AND source_id=s AND occurrence_date_utc IS NOT DISTINCT FROM d
        GROUP BY customer_id,source_id,occurrence_date_utc,machine_id;
END $$;
CREATE FUNCTION reporting.refresh_upload_source(c uuid,s uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,platform,reporting SET row_security=on AS $$
BEGIN
    INSERT INTO reporting.source_upload_summary
        SELECT c,s,count(*),COALESCE(sum(record_count),0),COALESCE(sum(payload_bytes),0),max(received_at),
            count(*) FILTER(WHERE processing_status='pending'),
            count(*) FILTER(WHERE processing_status='completed'),
            count(*) FILTER(WHERE processing_status='quarantined'),
            count(*) FILTER(WHERE processing_status='failed'),clock_timestamp()
        FROM platform.upload_batches WHERE customer_id=c AND source_id=s
    ON CONFLICT(customer_id,source_id) DO UPDATE SET
        committed_batches=EXCLUDED.committed_batches,declared_records=EXCLUDED.declared_records,
        payload_bytes=EXCLUDED.payload_bytes,last_received_at=EXCLUDED.last_received_at,
        awaiting_processing_batches=EXCLUDED.awaiting_processing_batches,completed_batches=EXCLUDED.completed_batches,
        quarantined_batches=EXCLUDED.quarantined_batches,failed_batches=EXCLUDED.failed_batches,refreshed_at=EXCLUDED.refreshed_at;
END $$;

CREATE FUNCTION warehouse.refresh_pending(batch_limit integer DEFAULT 200) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,warehouse,reporting SET row_security=on AS $$
DECLARE item record; processed integer:=0;
BEGIN
    IF batch_limit<1 OR batch_limit>1000 OR batch_limit IS NULL THEN
        RAISE EXCEPTION 'Choose a warehouse refresh limit from 1 to 1000';
    END IF;
    FOR item IN SELECT * FROM warehouse.refresh_queue WHERE available_at<=clock_timestamp()
        ORDER BY available_at,queued_at,customer_id,source_id,generation_id,source_table,source_record_id
        LIMIT batch_limit FOR UPDATE SKIP LOCKED LOOP
        BEGIN
            PERFORM warehouse.refresh_occurrence(item.customer_id,item.source_id,item.generation_id,item.source_table,item.source_record_id);
            DELETE FROM warehouse.refresh_queue WHERE
                (customer_id,source_id,generation_id,source_table,source_record_id)=
                (item.customer_id,item.source_id,item.generation_id,item.source_table,item.source_record_id);
            processed:=processed+1;
        EXCEPTION WHEN query_canceled OR lock_not_available THEN RAISE;
        WHEN OTHERS THEN
            UPDATE warehouse.refresh_queue SET attempts=attempts+1,last_error_code='refresh_failed',
                available_at=clock_timestamp()+make_interval(secs=>least(300,5*(attempts+1)))
            WHERE (customer_id,source_id,generation_id,source_table,source_record_id)=
                (item.customer_id,item.source_id,item.generation_id,item.source_table,item.source_record_id);
        END;
    END LOOP;
    FOR item IN SELECT * FROM reporting.refresh_queue
        ORDER BY queued_at,customer_id,source_id,occurrence_date_utc NULLS LAST
        LIMIT greatest(1,batch_limit/10) FOR UPDATE SKIP LOCKED LOOP
        -- Facts and summaries commit together; another in-flight writer queues
        -- a fresh bucket after this row is released.
        PERFORM reporting.refresh_alarm_day(item.customer_id,item.source_id,item.occurrence_date_utc);
        DELETE FROM reporting.refresh_queue WHERE customer_id=item.customer_id AND source_id=item.source_id
            AND occurrence_date_utc IS NOT DISTINCT FROM item.occurrence_date_utc;
        processed:=processed+1;
    END LOOP;
    FOR item IN SELECT * FROM warehouse.source_refresh_queue ORDER BY queued_at,customer_id,source_id
        LIMIT greatest(1,batch_limit/10) FOR UPDATE SKIP LOCKED LOOP
        PERFORM reporting.refresh_upload_source(item.customer_id,item.source_id);
        DELETE FROM warehouse.source_refresh_queue WHERE (customer_id,source_id)=(item.customer_id,item.source_id);
        processed:=processed+1;
    END LOOP;
    RETURN processed;
END $$;

DO $$ DECLARE item record; BEGIN
    FOR item IN SELECT n.nspname,p.proname,pg_get_function_identity_arguments(p.oid) arguments
        FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        WHERE (n.nspname='warehouse' AND p.proname IN ('queue_occurrence','queue_source','refresh_occurrence','refresh_pending'))
           OR (n.nspname='reporting' AND p.proname IN ('refresh_alarm_day','refresh_upload_source')) LOOP
        EXECUTE format('ALTER FUNCTION %I.%I(%s) OWNER TO scada_warehouse_owner',item.nspname,item.proname,item.arguments);
        EXECUTE format('REVOKE ALL ON FUNCTION %I.%I(%s) FROM PUBLIC',item.nspname,item.proname,item.arguments);
    END LOOP;
END $$;
GRANT USAGE ON SCHEMA warehouse TO scada_worker;
GRANT EXECUTE ON FUNCTION warehouse.refresh_pending(integer) TO scada_worker;
GRANT SELECT ON warehouse.fact_alarm_occurrence,warehouse.fact_event_occurrence TO scada_reader;

-- Redirect existing public views to stored facts; no reporting call scans raw
-- revisions. Missing/uncertain source dates retain a distinct NULL bucket.
CREATE OR REPLACE VIEW warehouse.dim_date WITH(security_invoker=true) AS
    SELECT DISTINCT calendar_date,extract(year FROM calendar_date)::integer calendar_year,
        extract(month FROM calendar_date)::integer calendar_month,extract(day FROM calendar_date)::integer calendar_day,
        extract(isoyear FROM calendar_date)::integer iso_year,extract(week FROM calendar_date)::integer iso_week
    FROM (SELECT occurrence_date_utc calendar_date FROM warehouse.fact_alarm_occurrence
        UNION SELECT occurrence_date_utc FROM warehouse.fact_event_occurrence) dates
    WHERE calendar_date IS NOT NULL;
CREATE OR REPLACE VIEW warehouse.alarm_daily WITH(security_invoker=true) AS
    SELECT customer_id,site_id,project_id,source_id,occurrence_date_utc,count(*) occurrences,
        sum(saved_versions) saved_versions,count(*) FILTER(WHERE ordering_uncertain) uncertain_order_occurrences,
        count(*) FILTER(WHERE source_time_uncertain) uncertain_time_occurrences
    FROM warehouse.fact_alarm_occurrence GROUP BY customer_id,site_id,project_id,source_id,occurrence_date_utc;

INSERT INTO warehouse.refresh_queue(customer_id,source_id,generation_id,source_table,source_record_id)
    SELECT DISTINCT customer_id,source_id,generation_id,source_table,source_record_id FROM platform.alarm_event_revisions;
INSERT INTO warehouse.source_refresh_queue(customer_id,source_id)
    SELECT DISTINCT customer_id,source_id FROM platform.upload_batches;
-- An atomic migration backfill is restartable by PostgreSQL transaction rollback.
DO $$ BEGIN
    WHILE warehouse.refresh_pending(1000)>0 LOOP END LOOP;
    IF EXISTS(SELECT 1 FROM warehouse.refresh_queue) THEN
        RAISE EXCEPTION 'Warehouse backfill failed; original storage is retained by rollback';
    END IF;
END $$;
COMMENT ON TABLE warehouse.fact_alarm_occurrence IS
    'One alarm occurrence per customer/source/generation/native ID. Original versions remain in platform. Eventually refreshed after committed changes; AI never approves mappings.';
COMMENT ON TABLE warehouse.fact_event_occurrence IS
    'One native event occurrence per customer/source/generation/native ID. Registered equipment is separate from approved mapping. Unknown order/time remain uncertain.';
COMMENT ON SCHEMA reporting IS 'Derived summaries with explicit refresh timestamps; original records and durable receipts remain authoritative in platform.';
