-- Central storage only. Never run against a SCADA source database.
-- Validation and removal share the Alembic transaction. RESTRICT deliberately
-- refuses unexpected objects/dependencies rather than deleting customer work.
SET LOCAL lock_timeout='10s';
LOCK TABLE platform.sources,platform.source_storage,
    platform.alarm_event_revisions,platform.machine_interpretations
    IN SHARE ROW EXCLUSIVE MODE;

DO $$
DECLARE
    item record; kind text; expected_columns text[]; actual_columns text[];
    destination regclass; mismatch boolean;
    metadata_columns constant text[] := ARRAY['revision_id','customer_id','source_id',
        'generation_id','source_table','content_hash','received_at','source_timezone',
        'ordering_uncertain','mapping_status','equipment','identification_status'];
BEGIN
    FOR item IN SELECT * FROM platform.source_storage ORDER BY source_id LOOP
        IF item.schema_name IN ('platform','warehouse','reporting','public','logs','information_schema')
            OR left(item.schema_name,3)='pg_'
            OR NOT EXISTS (SELECT 1 FROM pg_namespace n JOIN pg_roles r ON r.oid=n.nspowner
                WHERE n.nspname=item.schema_name AND r.rolname='scada_storage_owner') THEN
            RAISE EXCEPTION 'Legacy storage schema requires manual review';
        END IF;
        FOREACH kind IN ARRAY ARRAY['alarmhistory','eventhistory'] LOOP
            destination := to_regclass(format('%I.%I',item.schema_name,kind));
            IF destination IS NULL OR NOT EXISTS (
                SELECT 1 FROM pg_class c JOIN pg_roles r ON r.oid=c.relowner
                WHERE c.oid=destination AND c.relkind='r' AND r.rolname='scada_storage_owner') THEN
                RAISE EXCEPTION 'Legacy storage table requires manual review';
            END IF;
            EXECUTE format('LOCK TABLE %s IN ACCESS EXCLUSIVE MODE',destination);
            expected_columns := CASE kind WHEN 'alarmhistory' THEN ARRAY[
                'id','al_start_time','al_norm_time','al_ack_time','al_event_time','last_update',
                'al_start_time_ms','al_norm_time_ms','al_ack_time_ms','al_event_time_ms','last_update_ms',
                'al_ack','al_active','al_ack_req','al_deleted','al_tag','al_message','al_selection',
                'al_station','al_custom1','al_user','al_user_full','al_user_comment',
                'al_tag_value','al_prev_tag_value','al_group','al_priority','al_type']
            ELSE ARRAY['id','ev_type','ev_time','last_update','ev_time_ms','last_update_ms',
                'ev_info','ev_source','ev_message','ev_station','ev_user','ev_user_full',
                'ev_comment','ev_deleted','ev_value','ev_prev_value'] END || metadata_columns;
            SELECT array_agg(attname::text ORDER BY attnum) INTO actual_columns
                FROM pg_attribute WHERE attrelid=destination AND attnum>0 AND NOT attisdropped;
            IF actual_columns IS DISTINCT FROM expected_columns THEN
                RAISE EXCEPTION 'Unexpected legacy storage columns require manual review';
            END IF;
            -- Populate the native row type exactly as the old synchronizer did.
            -- Override every metadata field and native ID with canonical evidence.
            -- A processing claim intentionally does not update the old display
            -- status; its candidates still have to match the retained evidence.
            EXECUTE format($check$
                SELECT EXISTS (
                    SELECT 1 FROM %1$s old
                    FULL JOIN (SELECT * FROM platform.alarm_event_revisions
                        WHERE source_id=$1 AND customer_id=$2 AND source_table=$3) r
                        USING (revision_id)
                    LEFT JOIN platform.machine_interpretations i ON i.revision_id=r.revision_id
                    LEFT JOIN LATERAL (
                        SELECT string_agg(DISTINCT c->>'label',', ' ORDER BY c->>'label') equipment
                        FROM jsonb_array_elements(COALESCE(i.candidates,'[]'::jsonb)) c
                    ) names ON true
                    WHERE old.revision_id IS NULL OR r.revision_id IS NULL OR
                        to_jsonb(old) IS DISTINCT FROM to_jsonb(jsonb_populate_record(NULL::%1$s,
                            r.original_payload || jsonb_build_object(
                                'id',r.source_record_id,'revision_id',r.revision_id,
                                'customer_id',r.customer_id,'source_id',r.source_id,
                                'generation_id',r.generation_id,'source_table',r.source_table,
                                'content_hash',r.content_hash,'received_at',r.received_at,
                                'source_timezone',r.source_timezone,'ordering_uncertain',r.ordering_uncertain,
                                'mapping_status',r.mapping_status,'equipment',names.equipment,
                                'identification_status',CASE WHEN i.status='processing'
                                    THEN old.identification_status ELSE COALESCE(i.status,'pending') END))))
            $check$,destination) INTO mismatch USING item.source_id,item.customer_id,kind;
            IF mismatch THEN
                RAISE EXCEPTION 'Legacy copies differ from canonical evidence; removal cancelled';
            END IF;
        END LOOP;
    END LOOP;

    FOR item IN SELECT schema_name FROM platform.source_storage ORDER BY source_id LOOP
        EXECUTE format('DROP TABLE %I.alarmhistory, %I.eventhistory RESTRICT',
            item.schema_name,item.schema_name);
        EXECUTE format('DROP SCHEMA %I RESTRICT',item.schema_name);
    END LOOP;
END $$;

DROP TRIGGER IF EXISTS source_storage_registration ON platform.sources;
DROP TRIGGER source_storage_name_changed ON platform.sources;
DROP TRIGGER source_storage_revision ON platform.alarm_event_revisions;
DROP TRIGGER source_storage_identification ON platform.machine_interpretations;
DROP FUNCTION platform.source_storage_registration();
DROP FUNCTION platform.source_storage_name_changed();
DROP FUNCTION platform.source_storage_revision();
DROP FUNCTION platform.sync_source_revision(uuid);
DROP FUNCTION platform.ensure_source_storage(uuid);
DROP FUNCTION platform.rename_source_storage(uuid,text);
DROP FUNCTION platform.source_schema_name(text,uuid);
DROP FUNCTION platform.guard_source_table_write();
DROP TABLE platform.source_storage RESTRICT;

-- Roles are cluster-wide: leave the inert NOLOGIN role for other databases and
-- historical downgrades, but remove its former privileges in this database.
DO $$ BEGIN
    EXECUTE format('REVOKE CREATE ON DATABASE %I FROM scada_storage_owner',current_database());
END $$;
REVOKE ALL ON SCHEMA platform FROM scada_storage_owner;
REVOKE ALL ON platform.sources,platform.alarm_event_revisions,platform.machine_interpretations
    FROM scada_storage_owner;
REVOKE REFERENCES(customer_id,source_id,generation_id,source_table,source_record_id,revision_id)
    ON platform.alarm_event_revisions FROM scada_storage_owner;
