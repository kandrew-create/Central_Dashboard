"""Bounded read-only alarm summaries for the trusted local manager."""
from uuid import UUID

from collector.errors import CollectorError


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
    result = db.execute('''WITH selected AS MATERIALIZED (
            SELECT f.*,s.name source_name,m.machine_tag,
                (SELECT string_agg(DISTINCT candidate->>'label', ', ' ORDER BY candidate->>'label')
                 FROM jsonb_array_elements(f.ai_candidates) candidate) ai_suggestion
            FROM warehouse.fact_alarm_occurrence f
            JOIN warehouse.dim_source s USING(customer_id,source_id)
            LEFT JOIN warehouse.dim_machine m ON (m.customer_id,m.machine_id)=(f.customer_id,f.machine_id)
            WHERE (%(days)s=0 OR f.first_saved_at>=statement_timestamp()-(%(days)s * interval '1 day'))
              AND (%(source)s::uuid IS NULL OR f.source_id=%(source)s::uuid)
              AND (%(customer)s::uuid IS NULL OR f.customer_id=%(customer)s::uuid)
        ), issues AS (
            SELECT source_id,source_name,tag,message,count(*) occurrences,
                string_agg(DISTINCT machine_tag, ', ' ORDER BY machine_tag) confirmed_equipment,
                string_agg(DISTINCT ai_suggestion, '; ' ORDER BY ai_suggestion) ai_suggestions,
                count(*) FILTER (WHERE ordering_uncertain) uncertain_order,
                count(*) FILTER (WHERE source_time_uncertain) uncertain_time
            FROM selected GROUP BY source_id,source_name,tag,message
            ORDER BY count(*) DESC,source_name,source_id,tag NULLS LAST,message NULLS LAST LIMIT 50
        ), daily AS (
            SELECT occurrence_date_utc AS day,count(*) occurrences FROM selected
            WHERE occurrence_date_utc IS NOT NULL GROUP BY occurrence_date_utc
            ORDER BY occurrence_date_utc DESC LIMIT 366
        )
        SELECT jsonb_build_object(
            'summary',(SELECT jsonb_build_object('occurrences',count(*),
                'saved_versions',COALESCE(sum(saved_versions),0),
                'confirmed_equipment',count(DISTINCT machine_id),
                'uncertain_order',count(*) FILTER (WHERE ordering_uncertain),
                'uncertain_time',count(*) FILTER (WHERE source_time_uncertain),
                'unmapped',count(*) FILTER (WHERE machine_id IS NULL)) FROM selected),
            'issues',COALESCE((SELECT jsonb_agg(to_jsonb(issues)) FROM issues),'[]'::jsonb),
            'daily',COALESCE((SELECT jsonb_agg(to_jsonb(daily)) FROM daily),'[]'::jsonb)) report''',
                      dict(days=days, source=source, customer=customer)).fetchone()['report']
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
