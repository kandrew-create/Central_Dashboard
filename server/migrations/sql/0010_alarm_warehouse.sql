-- Central storage only. An analytical view layer; native records are never changed.
CREATE SCHEMA warehouse;
REVOKE ALL ON SCHEMA warehouse FROM PUBLIC;
GRANT USAGE ON SCHEMA warehouse TO scada_reader;

CREATE VIEW warehouse.dim_customer WITH (security_invoker=true) AS
    SELECT customer_id,name FROM platform.customers;
CREATE VIEW warehouse.dim_site WITH (security_invoker=true) AS
    SELECT customer_id,site_id,name FROM platform.sites;
CREATE VIEW warehouse.dim_project WITH (security_invoker=true) AS
    SELECT customer_id,site_id,project_id,name FROM platform.projects;
CREATE VIEW warehouse.dim_source WITH (security_invoker=true) AS
    SELECT customer_id,site_id,project_id,source_id,name,deleted_at FROM platform.sources;
CREATE VIEW warehouse.dim_machine WITH (security_invoker=true) AS
    SELECT customer_id,site_id,project_id,machine_id,machine_tag,name FROM platform.machines;

CREATE VIEW warehouse.fact_alarm_occurrence WITH (security_invoker=true) AS
WITH history AS (
    SELECT customer_id,site_id,project_id,source_id,generation_id,source_record_id,
        count(*) saved_versions,min(received_at) first_saved_at,max(received_at) last_saved_at,
        CASE WHEN bool_and(start_time_quality='known') AND count(DISTINCT start_time_utc)=1
             THEN min(start_time_utc) END occurrence_started_utc,
        CASE WHEN count(message)=count(*) AND count(DISTINCT message)=1 THEN min(message) END agreed_message,
        CASE WHEN count(tag)=count(*) AND count(DISTINCT tag)=1 THEN min(tag) END agreed_tag
    FROM platform.alarm_event_revisions
    WHERE source_table='alarmhistory'
    GROUP BY customer_id,site_id,project_id,source_id,generation_id,source_record_id
)
SELECT h.customer_id,h.site_id,h.project_id,h.source_id,h.generation_id,h.source_record_id,
    h.saved_versions,h.first_saved_at,h.last_saved_at,h.occurrence_started_utc,
    (h.occurrence_started_utc AT TIME ZONE 'UTC')::date occurrence_date_utc,
    h.occurrence_started_utc IS NULL source_time_uncertain,
    r.revision_id IS NULL ordering_uncertain,
    CASE WHEN r.revision_id IS NOT NULL THEN r.message ELSE h.agreed_message END message,
    CASE WHEN r.revision_id IS NOT NULL THEN r.tag ELSE h.agreed_tag END tag,
    r.revision_id verified_latest_revision_id,r.mapping_status,r.machine_id,
    r.active,r.ack,r.deleted,
    COALESCE(i.status,'not_available') ai_status,
    CASE WHEN i.status IN ('suggested','uncertain') THEN i.candidates ELSE '[]'::jsonb END ai_candidates
FROM history h
LEFT JOIN platform.latest_alarm_state l
    ON (l.customer_id,l.source_id,l.generation_id,l.source_record_id)=
       (h.customer_id,h.source_id,h.generation_id,h.source_record_id)
LEFT JOIN platform.alarm_event_revisions r
    ON r.revision_id=l.revision_id AND NOT l.ordering_uncertain AND NOT r.ordering_uncertain
LEFT JOIN platform.machine_interpretations i ON i.revision_id=r.revision_id;

COMMENT ON VIEW warehouse.fact_alarm_occurrence IS
    'One processed alarm occurrence per source/generation/record ID, including quarantined records. '
    'Saved versions are not repeat occurrences. Unknown latest state and conflicting source times remain null/uncertain. '
    'AI candidates are separate from approved machine_id. No alarm cause or duration is inferred.';

CREATE VIEW warehouse.dim_date WITH (security_invoker=true) AS
    SELECT DISTINCT occurrence_date_utc calendar_date,
        extract(year FROM occurrence_date_utc)::integer calendar_year,
        extract(month FROM occurrence_date_utc)::integer calendar_month,
        extract(day FROM occurrence_date_utc)::integer calendar_day,
        extract(isoyear FROM occurrence_date_utc)::integer iso_year,
        extract(week FROM occurrence_date_utc)::integer iso_week
    FROM warehouse.fact_alarm_occurrence WHERE occurrence_date_utc IS NOT NULL;

CREATE VIEW warehouse.alarm_daily WITH (security_invoker=true) AS
    SELECT customer_id,site_id,project_id,source_id,occurrence_date_utc,
        count(*) occurrences,sum(saved_versions) saved_versions,
        count(*) FILTER (WHERE ordering_uncertain) uncertain_order_occurrences,
        count(*) FILTER (WHERE source_time_uncertain) uncertain_time_occurrences
    FROM warehouse.fact_alarm_occurrence
    GROUP BY customer_id,site_id,project_id,source_id,occurrence_date_utc;

-- Invoker views retain the caller's fail-closed RLS context. No payloads, operator
-- fields, upload tokens or credential verifiers are added to the reader capability.
GRANT SELECT(customer_id,name) ON platform.customers TO scada_reader;
GRANT SELECT(customer_id,site_id,name) ON platform.sites TO scada_reader;
GRANT SELECT(customer_id,site_id,project_id,name) ON platform.projects TO scada_reader;
GRANT SELECT(customer_id,site_id,project_id,source_id,name,deleted_at) ON platform.sources TO scada_reader;
GRANT SELECT(customer_id,site_id,project_id,source_id,generation_id,source_record_id,source_table,
    received_at,start_time_quality,start_time_utc,message,tag,revision_id,ordering_uncertain,
    mapping_status,machine_id,active,ack,deleted) ON platform.alarm_event_revisions TO scada_reader;
GRANT SELECT(customer_id,source_id,generation_id,source_record_id,revision_id,ordering_uncertain)
    ON platform.latest_alarm_state TO scada_reader;
GRANT SELECT(revision_id,status,candidates) ON platform.machine_interpretations TO scada_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA warehouse TO scada_reader;
