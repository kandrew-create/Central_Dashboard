"""Validate actual PostgreSQL constraints/roles, not SQL text approximations."""
import unittest

from tests.pg_support import DOWN, ROLES, UP, PostgresCase, batch_sql, revision_sql, uid


class FoundationTests(PostgresCase):
    def test_all_customer_tables_force_rls(self):
        result = self.sql("""SELECT count(*), bool_and(c.relrowsecurity AND c.relforcerowsecurity)
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'platform' AND c.relkind = 'r';""")
        self.assertEqual(result.stdout.strip().splitlines()[-1], "17|t")

    def test_read_role_only_sees_its_customer(self):
        result = self.sql("SELECT machine_id FROM platform.machines;", role="scada_reader")
        self.assertEqual(result.stdout.strip().splitlines(), [uid(1), uid(4)])

    def test_missing_context_denies_all_rows(self):
        result = self.sql("SELECT count(*) FROM platform.machines;", role="scada_reader", customer=None)
        self.assertEqual(result.stdout.strip(), "0")

    def test_context_resets_after_commit_on_reused_connection(self):
        result = self._run(f"""BEGIN; SET LOCAL ROLE scada_reader;
            SELECT set_config('app.customer_id', '{uid(1)}', true);
            SELECT count(*) FROM platform.machines; COMMIT;
            BEGIN; SET LOCAL ROLE scada_reader;
            SELECT count(*) FROM platform.machines; COMMIT;""")
        self.assertEqual(result.stdout.strip().splitlines(), [uid(1), "1", "0"])

    def test_rls_rejects_cross_customer_insert(self):
        self.rejected(f"INSERT INTO platform.sites VALUES ('{uid(300)}', '{uid(101)}', 'Intrusion');",
                      "42501", role="scada_registry")

    def test_composite_foreign_keys_reject_cross_customer_site(self):
        self.rejected(f"INSERT INTO platform.projects VALUES ('{uid(300)}', '{uid(1)}', '{uid(102)}', 'Wrong site');", "23503")

    def test_same_site_machine_tag_is_unique(self):
        self.rejected(f"INSERT INTO platform.machines VALUES ('{uid(300)}', '{uid(1)}', '{uid(2)}', '{uid(3)}', 'LINE-01', 'Duplicate');", "23505")

    def test_machine_tags_can_repeat_between_sites(self):
        result = self.sql("SELECT count(*) FROM platform.machines WHERE machine_tag = 'LINE-01';")
        self.assertEqual(result.stdout.strip().splitlines()[-1], "2")

    def test_machine_rename_keeps_uuid_and_audits_old_tag(self):
        result = self.sql(f"""SELECT set_config('app.actor', 'test-admin', true);
            UPDATE platform.machines SET machine_tag = 'LINE-RENAMED' WHERE machine_id = '{uid(4)}';
            SELECT machine_id FROM platform.machines;
            SELECT actor, details->>'old_tag', details->>'new_tag' FROM platform.audit_log;""", role="scada_registry")
        self.assertEqual(result.stdout.strip().splitlines()[-2:], [uid(4), "test-admin|LINE-01|LINE-RENAMED"])

    def test_only_one_active_generation_per_source(self):
        self.rejected(f"""INSERT INTO platform.source_generations VALUES
            ('{uid(300)}', '{uid(1)}', '{uid(6)}', 2, 'new-db', 'local-admin', 'ticket-2', now(), NULL);""", "23505")

    def test_new_generation_requires_local_authorization_reference(self):
        self.rejected(f"""UPDATE platform.source_generations SET retired_at = now();
            INSERT INTO platform.source_generations VALUES
            ('{uid(300)}', '{uid(1)}', '{uid(6)}', 2, 'new-db', 'local-admin', '', now(), NULL);""", "23514")

    def test_generation_cannot_be_reused_by_another_source(self):
        self.rejected(batch_sql(customer=101, source=106, generation=7), "23503")

    def test_batch_identity_is_unique_per_source(self):
        self.rejected(batch_sql() + batch_sql(upload=22), "23505")

    def test_batch_id_can_repeat_for_different_sources(self):
        self.sql(batch_sql() + batch_sql(upload=22, customer=101, source=106, generation=107))

    def test_receipt_rejects_extra_fields_and_mismatched_hash(self):
        for expression in ("receipt || '{\"cursor\":1}'::jsonb", "receipt || '{\"payload_hash\":\"wrong\"}'::jsonb"):
            with self.subTest(expression=expression):
                self.rejected(batch_sql() + f"UPDATE platform.upload_batches SET receipt = {expression};", "23514")

    def test_hash_shape_is_enforced(self):
        self.rejected(batch_sql(digest="not-a-sha256"), "23514")

    def test_revisions_deduplicate_identity_and_content(self):
        for key, digest in (("revision-1", "c" * 64), ("revision-2", "b" * 64)):
            with self.subTest(key=key):
                self.rejected(batch_sql() + revision_sql() + revision_sql(revision=31, key=key, digest=digest), "23505")

    def test_changed_content_with_same_marker_can_be_retained(self):
        self.sql(batch_sql() + revision_sql(key="same-marker:hash-1")
                 + revision_sql(revision=31, key="same-marker:hash-2", digest="c" * 64))

    def test_null_update_requires_ordering_uncertainty(self):
        self.rejected(batch_sql() + revision_sql()
                      + "UPDATE platform.alarm_event_revisions SET ordering_uncertain = false;", "23514")

    def test_unknown_mapping_cannot_claim_machine_or_severity(self):
        self.rejected(batch_sql() + revision_sql()
                      + "UPDATE platform.alarm_event_revisions SET severity = 'critical';", "23514")

    def test_missing_norm_and_ack_times_remain_null(self):
        result = self.sql(batch_sql() + revision_sql() + """SELECT norm_time_local IS NULL,
            norm_time_ms IS NULL, norm_time_utc IS NULL, ack_time_local IS NULL,
            ack_time_ms IS NULL, ack_time_utc IS NULL FROM platform.alarm_event_revisions;""")
        self.assertEqual(result.stdout.strip().splitlines()[-1], "t|t|t|t|t|t")

    def test_ambiguous_time_cannot_have_guessed_utc(self):
        self.rejected(batch_sql() + revision_sql() + """UPDATE platform.alarm_event_revisions
            SET event_time_local = '2026-11-01 01:30:00', event_time_quality = 'ambiguous',
                event_time_utc = '2026-11-01 05:30:00+00';""", "23514")

    def test_latest_pointer_cannot_reference_a_different_occurrence(self):
        self.rejected(batch_sql() + revision_sql() + f"""INSERT INTO platform.latest_alarm_state
            (customer_id, source_id, generation_id, source_record_id, revision_id, last_observed_at)
            VALUES ('{uid(1)}', '{uid(6)}', '{uid(7)}', 999, '{uid(30)}', now());""", "23503")

    def test_worker_cannot_mutate_original_payload_or_delete_history(self):
        for statement in ("UPDATE platform.upload_batches SET payload = '{}'::jsonb;",
                          "DELETE FROM platform.upload_batches;",
                          "UPDATE platform.alarm_event_revisions SET original_payload = '{}'::jsonb;",
                          "DELETE FROM platform.alarm_event_revisions;",
                          "UPDATE platform.audit_log SET actor = 'rewrite';"):
            with self.subTest(statement=statement):
                self.rejected(statement, "42501", role="scada_worker")

    def test_reader_cannot_read_personal_payloads_or_write(self):
        for statement in ("SELECT original_payload FROM platform.alarm_event_revisions;",
                          "SELECT verifier FROM platform.collector_credentials;",
                          "UPDATE platform.machines SET machine_tag = 'write';"):
            with self.subTest(statement=statement):
                self.rejected(statement, "42501", role="scada_reader")

    def test_credential_machines_cannot_cross_sites(self):
        self.rejected(f"""INSERT INTO platform.collector_credentials
            (credential_id, customer_id, site_id, project_id, source_id, verifier)
            VALUES ('{uid(50)}', '{uid(1)}', '{uid(2)}', '{uid(3)}', '{uid(6)}', decode(repeat('ab',32),'hex'));
            INSERT INTO platform.credential_machines VALUES
            ('{uid(1)}', '{uid(2)}', '{uid(3)}', '{uid(6)}', '{uid(50)}', '{uid(104)}');""", "23503")

    def test_approved_mapping_rules_are_immutable(self):
        base = f"""INSERT INTO platform.mapping_rules
            (rule_id, customer_id, site_id, project_id, source_id, mapping_version_id, machine_id, record_type, tag)
            VALUES ('{uid(60)}', '{uid(1)}', '{uid(2)}', '{uid(3)}', '{uid(6)}', '{uid(8)}', '{uid(4)}', 'alarm', 'TAG');
            UPDATE platform.mapping_versions SET status = 'approved', approved_by = 'engineer', approved_at = now()
            WHERE mapping_version_id = '{uid(8)}';"""
        for change in ("UPDATE platform.mapping_rules SET tag = 'other';", "DELETE FROM platform.mapping_rules;"):
            with self.subTest(change=change):
                self.rejected(base + change, "23514")

    def test_approved_mapping_version_can_only_retire(self):
        base = f"""UPDATE platform.mapping_versions SET status = 'approved', approved_by = 'engineer', approved_at = now()
            WHERE mapping_version_id = '{uid(8)}';"""
        self.sql(base + f"UPDATE platform.mapping_versions SET status = 'retired' WHERE mapping_version_id = '{uid(8)}';")
        self.rejected(base + f"UPDATE platform.mapping_versions SET version = 2 WHERE mapping_version_id = '{uid(8)}';", "23514")

    def test_job_requires_lease_and_bounded_attempts(self):
        job = f"""INSERT INTO platform.jobs
            (job_id, customer_id, source_id, generation_id, upload_id, kind)
            VALUES ('{uid(40)}', '{uid(1)}', '{uid(6)}', '{uid(7)}', '{uid(20)}', 'process_batch');"""
        for change in ("UPDATE platform.jobs SET status = 'leased';", "UPDATE platform.jobs SET attempts = 6;"):
            with self.subTest(change=change):
                self.rejected(batch_sql() + job + change, "23514")

    def test_code_lookup_starts_empty(self):
        result = self.sql("SELECT count(*) FROM platform.code_lookup;")
        self.assertEqual(result.stdout.strip().splitlines()[-1], "0")

    def test_migration_can_downgrade_and_upgrade_in_disposable_transaction(self):
        self.sql(DOWN.read_text(encoding="utf-8") + UP.read_text(encoding="utf-8") + ROLES.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
