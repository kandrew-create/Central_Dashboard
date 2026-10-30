-- Read-only browsing facade for Central storage; no copies or source changes.
CREATE SCHEMA logs;
REVOKE ALL ON SCHEMA logs FROM PUBLIC;

CREATE VIEW logs.alarmhistory WITH (security_invoker=true,security_barrier=true) AS
SELECT native.*, names.equipment, COALESCE(i.status,'pending') AS identification_status,
    r.mapping_status,r.source_id,r.generation_id,r.revision_id,r.customer_id,
    s.name AS source_name,r.received_at,r.ordering_uncertain
FROM platform.alarm_event_revisions r
JOIN platform.sources s ON s.source_id=r.source_id
LEFT JOIN platform.machine_interpretations i ON i.revision_id=r.revision_id
CROSS JOIN LATERAL jsonb_to_record(r.original_payload) AS native(
        id integer,
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
        al_type integer)
LEFT JOIN LATERAL (
    SELECT string_agg(DISTINCT candidate->>'label', ', ' ORDER BY candidate->>'label') AS equipment
    FROM jsonb_array_elements(COALESCE(i.candidates,'[]'::jsonb)) candidate
) names ON true
WHERE r.source_table='alarmhistory';
COMMENT ON VIEW logs.alarmhistory IS 'Original native fields and equipment identification, one row per saved content version. Read-only; internal storage remains in platform. Suggestions are not approved mappings.';

CREATE VIEW logs.eventhistory WITH (security_invoker=true,security_barrier=true) AS
SELECT native.*, names.equipment, COALESCE(i.status,'pending') AS identification_status,
    r.mapping_status,r.source_id,r.generation_id,r.revision_id,r.customer_id,
    s.name AS source_name,r.received_at,r.ordering_uncertain
FROM platform.alarm_event_revisions r
JOIN platform.sources s ON s.source_id=r.source_id
LEFT JOIN platform.machine_interpretations i ON i.revision_id=r.revision_id
CROSS JOIN LATERAL jsonb_to_record(r.original_payload) AS native(
        id integer,
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
        ev_prev_value character varying)
LEFT JOIN LATERAL (
    SELECT string_agg(DISTINCT candidate->>'label', ', ' ORDER BY candidate->>'label') AS equipment
    FROM jsonb_array_elements(COALESCE(i.candidates,'[]'::jsonb)) candidate
) names ON true
WHERE r.source_table='eventhistory';
COMMENT ON VIEW logs.eventhistory IS 'Original native fields and equipment identification, one row per saved content version. Read-only; internal storage remains in platform. Suggestions are not approved mappings.';
