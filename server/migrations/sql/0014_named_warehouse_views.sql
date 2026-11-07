-- Central storage only. Invoker views expose current labels without copying
-- facts or changing the caller's customer policies and underlying privileges.
CREATE VIEW reporting.alarm_occurrences WITH (security_invoker=true) AS
    SELECT c.name customer_name,si.name site_name,p.name project_name,s.name source_name,f.*
    FROM warehouse.fact_alarm_occurrence f
    JOIN warehouse.dim_customer c USING(customer_id)
    JOIN warehouse.dim_site si USING(customer_id,site_id)
    JOIN warehouse.dim_project p USING(customer_id,site_id,project_id)
    JOIN warehouse.dim_source s USING(customer_id,site_id,project_id,source_id);

CREATE VIEW reporting.event_occurrences WITH (security_invoker=true) AS
    SELECT c.name customer_name,si.name site_name,p.name project_name,s.name source_name,f.*
    FROM warehouse.fact_event_occurrence f
    JOIN warehouse.dim_customer c USING(customer_id)
    JOIN warehouse.dim_site si USING(customer_id,site_id)
    JOIN warehouse.dim_project p USING(customer_id,site_id,project_id)
    JOIN warehouse.dim_source s USING(customer_id,site_id,project_id,source_id);

COMMENT ON VIEW reporting.alarm_occurrences IS
    'Shared alarm facts with current customer/site/project/source labels for filtering. '
    'Retains UUID identity, uncertainty, saved-version counts and caller RLS; no duplicate storage.';
COMMENT ON VIEW reporting.event_occurrences IS
    'Shared event facts with current customer/site/project/source labels for filtering. '
    'Retains UUID identity, uncertainty, saved-version counts and caller RLS; no duplicate storage.';
GRANT SELECT ON reporting.alarm_occurrences,reporting.event_occurrences TO scada_reader;
