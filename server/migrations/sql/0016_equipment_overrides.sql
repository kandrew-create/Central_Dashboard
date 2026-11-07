-- Central storage only. An equipment label is not a machine assignment or a
-- mapping approval; immutable alarms, receipts and AI candidates remain intact.
CREATE TABLE platform.alarm_equipment_overrides (
    customer_id uuid NOT NULL,
    source_id uuid NOT NULL,
    condition_key text NOT NULL CHECK(condition_key ~ '^[0-9a-f]{64}$'),
    tag text,
    message text,
    equipment_label text CHECK(equipment_label IS NULL OR (
        length(equipment_label) BETWEEN 1 AND 255 AND equipment_label=btrim(equipment_label)
        AND equipment_label !~ '[[:cntrl:]]')),
    version bigint NOT NULL DEFAULT 1 CHECK(version>0),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(customer_id,source_id,condition_key),
    FOREIGN KEY(customer_id,source_id) REFERENCES platform.sources(customer_id,source_id),
    CHECK(coalesce(btrim(tag),'')<>'' OR coalesce(btrim(message),'')<>''),
    CHECK(condition_key=encode(sha256(convert_to(jsonb_build_array(tag,message)::text,'UTF8')),'hex'))
);
ALTER TABLE platform.alarm_equipment_overrides ENABLE ROW LEVEL SECURITY;
ALTER TABLE platform.alarm_equipment_overrides FORCE ROW LEVEL SECURITY;
CREATE POLICY customer_scope ON platform.alarm_equipment_overrides
    USING(customer_id=nullif(current_setting('app.customer_id',true),'')::uuid)
    WITH CHECK(customer_id=nullif(current_setting('app.customer_id',true),'')::uuid);
GRANT SELECT,INSERT,UPDATE ON platform.alarm_equipment_overrides TO scada_registry;
COMMENT ON TABLE platform.alarm_equipment_overrides IS
    'Manual equipment labels for an exact source/tag/message alarm group, including future matching alarms. '
    'NULL label restores saved AI display. Versioned edits are audited; workers have no write privileges.';
