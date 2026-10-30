-- Keep accepted history and identity while removing a registration from use.
ALTER TABLE platform.sources ADD COLUMN deleted_at timestamptz;

CREATE OR REPLACE FUNCTION platform.authenticate_upload(candidate bytea)
RETURNS TABLE(credential_id uuid,customer_id uuid,site_id uuid,project_id uuid,source_id uuid)
LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,platform SET row_security=off AS $$
    SELECT cr.credential_id,cr.customer_id,cr.site_id,cr.project_id,cr.source_id
    FROM platform.collector_credentials cr
    JOIN platform.sources s ON s.source_id=cr.source_id
    JOIN platform.collectors c ON c.collector_id=s.collector_id
    WHERE cr.verifier=candidate AND cr.revoked_at IS NULL
      AND (cr.expires_at IS NULL OR cr.expires_at>now()) AND c.revoked_at IS NULL
      AND s.deleted_at IS NULL
$$;
