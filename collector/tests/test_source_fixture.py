"""Tests of the supplied schema fixture, not yet a collector integration suite."""
import json
import unittest

from tests.pg_support import PostgresCase


ALARM_COLUMNS = {
    "id": "integer",
    **{name: "timestamp without time zone" for name in (
        "al_start_time", "al_norm_time", "al_ack_time", "al_event_time", "last_update")},
    **{name: "integer" for name in (
        "al_start_time_ms", "al_norm_time_ms", "al_ack_time_ms", "al_event_time_ms",
        "last_update_ms", "al_group", "al_priority", "al_type")},
    **{name: "boolean" for name in ("al_ack", "al_active", "al_ack_req", "al_deleted")},
    **{name: "text" for name in (
        "al_tag", "al_message", "al_selection", "al_station", "al_custom1",
        "al_user", "al_user_full", "al_user_comment")},
    "al_tag_value": "character varying", "al_prev_tag_value": "character varying",
}
EVENT_COLUMNS = {
    "id": "integer", "ev_type": "integer", "ev_time_ms": "integer", "last_update_ms": "integer",
    "ev_time": "timestamp without time zone", "last_update": "timestamp without time zone",
    "ev_deleted": "boolean",
    **{name: "text" for name in (
        "ev_info", "ev_source", "ev_user", "ev_user_full", "ev_message", "ev_station", "ev_comment")},
    "ev_value": "character varying", "ev_prev_value": "character varying",
}


class SourceFixtureTests(PostgresCase):
    def test_exact_columns_types_nullability_and_identity_modes(self):
        for table, expected, identity in (
            ("alarmhistory", ALARM_COLUMNS, "ALWAYS"),
            ("eventhistory", EVENT_COLUMNS, "BY DEFAULT"),
        ):
            with self.subTest(table=table):
                result = self.sql(f"""SELECT json_agg(json_build_object('name', column_name,
                    'type', data_type, 'nullable', is_nullable, 'identity', identity_generation))
                    FROM information_schema.columns WHERE table_schema = 'public' AND table_name = '{table}';""")
                columns = json.loads(result.stdout.strip().splitlines()[-1])
                self.assertEqual({col["name"]: col["type"] for col in columns}, expected)
                for column in columns:
                    self.assertEqual(column["nullable"], "NO" if column["name"] == "id" else "YES")
                    self.assertEqual(column["identity"], identity if column["name"] == "id" else None)

    def test_fixture_has_only_two_approved_tables_and_primary_indexes(self):
        result = self.sql("""SELECT string_agg(tablename, ',' ORDER BY tablename) FROM pg_tables
            WHERE schemaname = 'public';
            SELECT string_agg(indexname, ',' ORDER BY indexname) FROM pg_indexes WHERE schemaname = 'public';""")
        self.assertEqual(result.stdout.strip().splitlines()[-2:], [
            "alarmhistory,eventhistory", "alarmhistory_pkey,eventhistory_pkey"])

    def test_alarm_identity_disallows_manual_insert(self):
        self.rejected("INSERT INTO public.alarmhistory (id) VALUES (999);", "428C9")

    def test_event_identity_allows_manual_insert_and_reuse_after_delete(self):
        # Test fixture setup simulates customer behavior; the collector never deletes.
        result = self.sql("""INSERT INTO public.eventhistory (id, ev_value) VALUES (10, '001.00');
            DELETE FROM public.eventhistory WHERE id = 10;
            INSERT INTO public.eventhistory (id, ev_value) VALUES (10, 'true');
            SELECT id, ev_value FROM public.eventhistory;""")
        self.assertEqual(result.stdout.strip().splitlines()[-1], "10|true")

    def test_alarm_lifecycle_is_one_mutable_source_row(self):
        result = self.sql("""INSERT INTO public.alarmhistory
            (al_start_time, al_start_time_ms, al_active, al_ack, last_update, last_update_ms, al_tag_value)
            VALUES ('2026-10-27 10:00:00', 123, true, false, '2026-10-27 10:00:00', 123, '0001.20');
            UPDATE public.alarmhistory SET al_active = false, al_norm_time = '2026-10-27 10:01:00',
                last_update = '2026-10-27 10:01:00';
            UPDATE public.alarmhistory SET al_ack = true, al_ack_time = '2026-10-27 10:02:00',
                last_update = '2026-10-27 10:02:00';
            SELECT count(*), bool_and(al_ack), bool_and(NOT al_active), min(al_tag_value) FROM public.alarmhistory;""")
        self.assertEqual(result.stdout.strip().splitlines()[-1], "1|t|t|0001.20")

    def test_missing_lifecycle_times_and_update_are_nullable(self):
        result = self.sql("""INSERT INTO public.alarmhistory (al_active) VALUES (true);
            SELECT al_norm_time IS NULL, al_ack_time IS NULL, last_update IS NULL FROM public.alarmhistory;""")
        self.assertEqual(result.stdout.strip().splitlines()[-1], "t|t|t")

    def test_fixture_read_only_session_rejects_write(self):
        # Transaction setting is tested against the fixture, not a customer DB.
        result = self._run("""SET default_transaction_read_only = on;
            BEGIN; SELECT count(*) FROM public.alarmhistory;
            INSERT INTO public.alarmhistory (al_message) VALUES ('must fail');""", succeeds=False)
        self.assertIn("25006", result.stderr)

    def test_soft_delete_flags_do_not_remove_rows(self):
        result = self.sql("""INSERT INTO public.alarmhistory (al_deleted) VALUES (true);
            INSERT INTO public.eventhistory (ev_deleted) VALUES (true);
            SELECT count(*) FROM public.alarmhistory WHERE al_deleted;
            SELECT count(*) FROM public.eventhistory WHERE ev_deleted;""")
        self.assertEqual(result.stdout.strip().splitlines()[-2:], ["1", "1"])


if __name__ == "__main__":
    unittest.main()
