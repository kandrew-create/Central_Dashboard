"""Trusted local edits of equipment display labels, never native alarm data."""
import re
from uuid import UUID

from collector.errors import CollectorError


def condition_sql(alias):
    # Aliases are fixed by callers, never supplied through management requests.
    if alias not in ('r','f'):
        raise ValueError('Unknown alarm alias')
    return f"encode(sha256(convert_to(jsonb_build_array({alias}.tag,{alias}.message)::text,'UTF8')),'hex')"


def available(db):
    return db.execute("SELECT to_regclass('platform.alarm_equipment_overrides') relation").fetchone()['relation'] is not None


def save_override(db,customer_id,source_id,condition_key,equipment_label,expected_version):
    from server.management.service import text
    try:
        customer,source=str(UUID(str(customer_id))),str(UUID(str(source_id)))
    except (ValueError,TypeError,AttributeError):
        raise CollectorError('Select a valid alarm source and customer.') from None
    if not isinstance(condition_key,str) or re.fullmatch('[0-9a-f]{64}',condition_key) is None:
        raise CollectorError('Refresh alarm analysis and select an alarm group before editing equipment.')
    if type(expected_version) is not int or expected_version<0:
        raise CollectorError('Refresh the saved equipment version before editing.')
    label=text(equipment_label,'equipment name') if equipment_label is not None else None
    if not available(db):
        raise CollectorError('Apply Central migration 0016_equipment_overrides before editing equipment.')
    source_row=db.execute('SELECT customer_id FROM platform.sources WHERE source_id=%s AND deleted_at IS NULL',
                          (source,)).fetchone()
    if source_row is None or str(source_row['customer_id'])!=customer:
        raise CollectorError('The selected alarm source is unavailable for this customer.')
    db.execute("SELECT set_config('app.customer_id',%s,true)",(customer,))
    db.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",('equipment:'+source+':'+condition_key,))
    evidence=db.execute(f'''SELECT DISTINCT r.tag,r.message FROM platform.alarm_event_revisions r
        WHERE r.customer_id=%s AND r.source_id=%s AND r.source_table='alarmhistory'
          AND {condition_sql('r')}=%s LIMIT 2''',(customer,source,condition_key)).fetchall()
    if len(evidence)!=1 or not any((evidence[0][key] or '').strip() for key in ('tag','message')):
        raise CollectorError('Select an alarm with a saved original message or tag. Unknown groups cannot be edited together.')
    params=dict(customer=customer,source=source,key=condition_key,tag=evidence[0]['tag'],message=evidence[0]['message'],label=label)
    current=db.execute('''SELECT equipment_label,version FROM platform.alarm_equipment_overrides
        WHERE customer_id=%(customer)s AND source_id=%(source)s AND condition_key=%(key)s FOR UPDATE''',params).fetchone()
    version=current['version'] if current else 0
    if version!=expected_version:
        raise CollectorError('Equipment was edited since this result was loaded. Refresh before saving your change.')
    if label is None and (current is None or current['equipment_label'] is None):
        return dict(equipment_label=None,version=version)
    saved=db.execute('''INSERT INTO platform.alarm_equipment_overrides
        (customer_id,source_id,condition_key,tag,message,equipment_label)
        VALUES(%(customer)s,%(source)s,%(key)s,%(tag)s,%(message)s,%(label)s)
        ON CONFLICT(customer_id,source_id,condition_key) DO UPDATE
            SET equipment_label=EXCLUDED.equipment_label,version=platform.alarm_equipment_overrides.version+1,updated_at=now()
        RETURNING equipment_label,version''',params).fetchone()
    db.execute('''INSERT INTO platform.audit_log(customer_id,actor,action,entity_type,entity_id,details)
        VALUES(%(customer)s,'local-manager',%(action)s,'alarm_equipment_override',%(source)s,
            jsonb_build_object('condition_key',%(key)s::text,'previous_label',%(previous)s::text,
                'equipment_label',%(label)s::text,'version',%(version)s::bigint))''',dict(params,
        action='equipment_override_saved' if label is not None else 'equipment_override_cleared',
        previous=current['equipment_label'] if current else None,version=saved['version']))
    return dict(saved)
