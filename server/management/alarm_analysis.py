"""Bounded read-only alarm summaries for the trusted local manager."""
from uuid import UUID

from collector.errors import CollectorError
from server.management.equipment import available,condition_sql


def report(db, days=30, source_id=None, customer_id=None):
    if type(days) is not int or not 0 <= days <= 365:
        raise CollectorError('Choose all saved alarms (0), or a whole number of days from 1 to 365.')
    try:
        source = str(UUID(str(source_id))) if source_id is not None else None
        customer = str(UUID(str(customer_id))) if customer_id is not None else None
    except ValueError:
        raise CollectorError('Select a valid registered source or customer.') from None
    if db.execute("SELECT to_regclass('warehouse.fact_alarm_occurrence') relation").fetchone()['relation'] is None:
        raise CollectorError('Apply Central Server migration 0010_alarm_warehouse before loading alarm analysis.')
    editing=available(db)
    overrides=('LEFT JOIN platform.alarm_equipment_overrides o ON o.customer_id=f.customer_id '
               'AND o.source_id=f.source_id AND saved_ai.original_matches AND o.condition_key='+condition_sql('f')) if editing else ''
    override_fields='o.equipment_label equipment_override,COALESCE(o.version,0) override_version' if editing else 'NULL::text equipment_override,0::bigint override_version'
    result = db.execute(f'''WITH selected AS MATERIALIZED (
            SELECT f.*,s.name source_name,
                {condition_sql('f')} condition_key,{override_fields},
                saved_ai.ai_suggestion,saved_ai.original_matches
            FROM warehouse.fact_alarm_occurrence f
            JOIN warehouse.dim_source s USING(customer_id,source_id)
            LEFT JOIN LATERAL (
                SELECT string_agg(DISTINCT candidate->>'label', ', ' ORDER BY candidate->>'label') ai_suggestion,
                    count(r.revision_id)>0 original_matches
                FROM platform.alarm_event_revisions r
                LEFT JOIN platform.machine_interpretations i ON i.revision_id=r.revision_id AND i.status IN ('suggested','uncertain')
                LEFT JOIN LATERAL jsonb_array_elements(COALESCE(i.candidates,'[]'::jsonb)) candidate ON true
                WHERE (r.customer_id,r.source_id,r.generation_id,r.source_record_id)=
                      (f.customer_id,f.source_id,f.generation_id,f.source_record_id)
                  AND r.source_table='alarmhistory'
                  AND r.tag IS NOT DISTINCT FROM f.tag AND r.message IS NOT DISTINCT FROM f.message
            ) saved_ai ON true
            {overrides}
            WHERE (%(days)s=0 OR f.first_saved_at>=statement_timestamp()-(%(days)s * interval '1 day'))
              AND (%(source)s::uuid IS NULL OR f.source_id=%(source)s::uuid)
              AND (%(customer)s::uuid IS NULL OR f.customer_id=%(customer)s::uuid)
        ), issues AS (
            SELECT customer_id,source_id,source_name,tag,message,condition_key,count(*) occurrences,
                string_agg(DISTINCT ai_suggestion, '; ' ORDER BY ai_suggestion) ai_suggestions,
                equipment_override,override_version,
                bool_and(original_matches) equipment_editable,
                COALESCE(equipment_override,string_agg(DISTINCT ai_suggestion,'; ' ORDER BY ai_suggestion)) equipment_name,
                CASE WHEN equipment_override IS NOT NULL THEN 'manual'
                    WHEN count(ai_suggestion)>0 THEN 'ai' ELSE 'unavailable' END equipment_origin,
                count(*) FILTER (WHERE ordering_uncertain) uncertain_order,
                count(*) FILTER (WHERE source_time_uncertain) uncertain_time
            FROM selected GROUP BY customer_id,source_id,source_name,tag,message,condition_key,equipment_override,override_version
            ORDER BY count(*) DESC,source_name,source_id,tag NULLS LAST,message NULLS LAST LIMIT 50
        ), daily AS (
            SELECT occurrence_date_utc AS day,count(*) occurrences FROM selected
            WHERE occurrence_date_utc IS NOT NULL GROUP BY occurrence_date_utc
            ORDER BY occurrence_date_utc DESC LIMIT 366
        )
        SELECT jsonb_build_object(
            'summary',(SELECT jsonb_build_object('occurrences',count(*),
                'saved_versions',COALESCE(sum(saved_versions),0),
                'uncertain_order',count(*) FILTER (WHERE ordering_uncertain),
                'uncertain_time',count(*) FILTER (WHERE source_time_uncertain)) FROM selected),
            'issues',COALESCE((SELECT jsonb_agg(to_jsonb(issues)) FROM issues),'[]'::jsonb),
            'daily',COALESCE((SELECT jsonb_agg(to_jsonb(daily)) FROM daily),'[]'::jsonb)) report''',
                      dict(days=days, source=source, customer=customer)).fetchone()['report']
    result['equipment_editing_available']=editing
    if db.execute("SELECT to_regclass('warehouse.refresh_queue') relation").fetchone()['relation'] is None:
        result['freshness'] = dict(mode='live', pending_occurrences=0, pending_summaries=0, retrying_updates=0,
                                   last_updated_at=None)
    else:
        result['freshness'] = db.execute('''WITH pending AS (
                SELECT attempts FROM warehouse.refresh_queue
                WHERE (%(source)s::uuid IS NULL OR source_id=%(source)s::uuid)
                  AND (%(customer)s::uuid IS NULL OR customer_id=%(customer)s::uuid)
            ), summaries AS (
                SELECT customer_id,source_id FROM reporting.refresh_queue
                UNION ALL SELECT customer_id,source_id FROM warehouse.source_refresh_queue
            ), updated AS (
                SELECT customer_id,source_id,refreshed_at FROM warehouse.fact_alarm_occurrence
                UNION ALL SELECT customer_id,source_id,refreshed_at FROM warehouse.fact_event_occurrence
                UNION ALL SELECT customer_id,source_id,refreshed_at FROM reporting.source_upload_summary
            )
            SELECT jsonb_build_object('mode','stored',
                'pending_occurrences',(SELECT count(*) FROM pending),
                'retrying_updates',(SELECT count(*) FROM pending WHERE attempts>0),
                'pending_summaries',(SELECT count(*) FROM summaries
                    WHERE (%(source)s::uuid IS NULL OR source_id=%(source)s::uuid)
                      AND (%(customer)s::uuid IS NULL OR customer_id=%(customer)s::uuid)),
                'last_updated_at',(SELECT max(refreshed_at) FROM updated
                    WHERE (%(source)s::uuid IS NULL OR source_id=%(source)s::uuid)
                      AND (%(customer)s::uuid IS NULL OR customer_id=%(customer)s::uuid))) freshness''',
            dict(source=source, customer=customer)).fetchone()['freshness']
    return result
