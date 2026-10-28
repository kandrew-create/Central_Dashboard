from dataclasses import replace
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import time
from uuid import uuid4
import unittest

from collector import secrets
from collector.cli import main
from collector.config import EXAMPLE, load_config
from collector.errors import CollectorError
from collector.source import SourceReader
from tests.pg_support import PostgresCase


class SourceReaderTests(PostgresCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.reader_role = "collector_reader_" + uuid4().hex
        cls._run(f'CREATE ROLE "{cls.reader_role}" LOGIN;')
        cls.addClassCleanup(cls._remove_reader)
        cls._run(f'''REVOKE CREATE ON SCHEMA public FROM PUBLIC;
            GRANT CONNECT ON DATABASE "{cls.database}" TO "{cls.reader_role}";
            GRANT USAGE ON SCHEMA public TO "{cls.reader_role}";
            GRANT SELECT ON public.alarmhistory, public.eventhistory TO "{cls.reader_role}";''')

    @classmethod
    def _remove_reader(cls):
        cls._run(f'DROP OWNED BY "{cls.reader_role}";')
        cls._run(f'DROP ROLE "{cls.reader_role}";', database=cls.base_database)

    def setUp(self):
        self._run("TRUNCATE public.alarmhistory, public.eventhistory RESTART IDENTITY;")
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "config.toml"
        path.write_text(EXAMPLE, encoding="utf-8")
        self.config = replace(load_config(path), host=os.environ.get("PGHOST", "localhost"),
            port=int(os.environ.get("PGPORT", "5432")), database=self.database, user=self.reader_role,
            timezone="America/Toronto")
        self.reader = SourceReader(self.config, password="")  # Trust is confined to the disposable test cluster.

    def test_connection_checks_approved_schema_and_dedicated_role(self):
        result = self.reader.check()
        self.assertEqual(result["status"], "connected")
        self.assertTrue(result["read_only"])
        self.assertEqual(result["approved_tables"], ["alarmhistory", "eventhistory"])

    def test_requiring_tls_on_a_non_tls_test_server_has_a_specific_error(self):
        with self.reader.session() as connection:
            if connection.execute("SHOW ssl").fetchone()["ssl"] != "off":
                self.skipTest("test server supports TLS")
        reader = SourceReader(replace(self.config, sslmode="require"), "")
        with self.assertRaisesRegex(CollectorError, "does not support TLS"):
            reader.check()

    def test_collector_sessions_reject_writes_on_real_postgresql(self):
        import psycopg
        with self.reader.session() as connection:
            self.assertEqual(connection.execute("SHOW transaction_read_only").fetchone()["transaction_read_only"], "on")
            with self.assertRaises(psycopg.errors.ReadOnlySqlTransaction):
                connection.execute("INSERT INTO public.alarmhistory (al_message) VALUES ('must fail')")

    def test_superuser_connection_is_rejected(self):
        reader = SourceReader(replace(self.config, user=os.environ.get("PGUSER", "postgres")),
                              os.environ.get("PGPASSWORD", ""))
        with self.assertRaisesRegex(CollectorError, "unprivileged"):
            reader.check()

    def test_write_privileges_are_rejected_even_with_read_only_session(self):
        self._run(f'GRANT UPDATE ON public.alarmhistory TO "{self.reader_role}";')
        try:
            with self.assertRaisesRegex(CollectorError, "must not own/write"):
                self.reader.check()
        finally:
            self._run(f'REVOKE UPDATE ON public.alarmhistory FROM "{self.reader_role}";')

    def test_only_two_approved_tables_can_be_selected(self):
        with self.assertRaisesRegex(CollectorError, "Only alarmhistory and eventhistory"):
            self.reader.preview("Heartbeat")
        with self.assertRaisesRegex(CollectorError, "Only alarmhistory and eventhistory"):
            self.reader.preview("unidentified_table")

    def test_real_rows_preserve_string_codes_privacy_and_null_lifecycle(self):
        self._run("""INSERT INTO public.alarmhistory
            (al_tag_value, al_prev_tag_value, al_priority, al_deleted, al_user, al_start_time, al_start_time_ms)
            VALUES ('0001.20', 'false', 999, true, 'operator', '2026-10-28 10:00:00', 123);""")
        record = self.reader.preview("alarmhistory")[0]
        self.assertEqual(record["original"]["al_tag_value"], "0001.20")
        self.assertEqual(record["original"]["al_priority"], 999)
        self.assertIs(record["original"]["al_deleted"], True)
        self.assertNotIn("al_user", record["original"])
        self.assertIsNone(record["original"]["al_ack_time"])
        self.assertEqual(record["times"]["al_start_time"]["utc"], "2026-10-28T14:00:00.123Z")
        self.assertEqual(self.reader.preview("alarmhistory", include_user_fields=True)[0]["original"]["al_user"], "operator")

    def test_alarm_lifecycle_updates_are_visible_without_new_ids(self):
        self._run("INSERT INTO public.alarmhistory (al_active, al_ack) VALUES (true, false);")
        active = self.reader.preview("alarmhistory")[0]
        self._run("UPDATE public.alarmhistory SET al_active = false, al_norm_time = '2026-10-28 10:01:00', al_norm_time_ms = 0;")
        normal = self.reader.preview("alarmhistory")[0]
        self._run("UPDATE public.alarmhistory SET al_ack = true, al_ack_time = '2026-10-28 10:02:00', al_ack_time_ms = 0;")
        acknowledged = self.reader.preview("alarmhistory")[0]
        self.assertEqual({row["source_record_id"] for row in (active, normal, acknowledged)}, {1})
        self.assertEqual(len({row["content_hash"] for row in (active, normal, acknowledged)}), 3)
        self.assertTrue(all(row["ordering_uncertain"] for row in (active, normal, acknowledged)))

    def test_preview_pagination_is_bounded_and_includes_negative_source_ids(self):
        self._run("INSERT INTO public.eventhistory (id, ev_value) VALUES (-1, 'a'), (1, 'b'), (2, 'c');")
        self.assertEqual(self.reader.preview("eventhistory", limit=1)[0]["source_record_id"], -1)
        self.assertEqual([r["source_record_id"] for r in self.reader.preview("eventhistory", after_id=-1)], [1, 2])
        for limit in (0, 21, True):
            with self.subTest(limit=limit), self.assertRaises(CollectorError):
                self.reader.preview("eventhistory", limit=limit)

    def test_oversized_field_is_not_silently_truncated(self):
        self._run("INSERT INTO public.eventhistory (ev_message) VALUES (repeat('x', 5000));")
        with self.assertRaisesRegex(CollectorError, "max_field_bytes"):
            self.reader.preview("eventhistory")

    def test_total_output_is_bounded(self):
        self._run("INSERT INTO public.eventhistory (ev_message) VALUES ('small');")
        reader = SourceReader(replace(self.config, max_output_bytes=100), "")
        with self.assertRaisesRegex(CollectorError, "max_output_bytes"):
            reader.preview("eventhistory")

    def test_schema_mismatch_is_rejected_without_source_changes(self):
        reader = SourceReader(replace(self.config, alarm_table="missing_alarm_table"), "")
        with self.assertRaisesRegex(CollectorError, "approved EcoStruxure v1 schema"):
            reader.check()

    def test_busy_table_releases_with_bounded_lock_wait(self):
        import psycopg
        blocker = psycopg.connect(host=self.config.host, port=self.config.port, dbname=self.database,
            user=os.environ.get("PGUSER", "postgres"), password=os.environ.get("PGPASSWORD", ""))
        try:
            blocker.execute("LOCK TABLE public.alarmhistory IN ACCESS EXCLUSIVE MODE")
            reader = SourceReader(replace(self.config, lock_timeout_ms=100), "")
            with self.assertRaisesRegex(CollectorError, "bounded lock wait"):
                reader.preview("alarmhistory")
        finally:
            blocker.rollback()
            blocker.close()

    @unittest.skipUnless(os.name == "nt", "requires real Windows DPAPI and ACLs")
    def test_cli_uses_protected_settings_for_a_real_database_preview(self):
        self._run("INSERT INTO public.eventhistory (ev_value, ev_user) VALUES ('0001.20', 'private operator');")
        path = self.config.path.parent / "private" / "config.toml"
        content = (EXAMPLE.replace('name = "scada"', f'name = "{self.database}"')
                   .replace('user = "scada_collector"', f'user = "{self.reader_role}"')
                   .replace('host = "localhost"', f'host = "{self.config.host}"')
                   .replace('port = 5432', f'port = {self.config.port}'))
        secrets.initialize(path, content)
        secrets.save_password(load_config(path).password_path, "TEST-ONLY-cli-secret")
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(["--config", str(path), "test-connection"]), 0)
        self.assertTrue(json.loads(output.getvalue())["read_only"])
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(["--config", str(path), "preview", "--table", "eventhistory"]), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["records"][0]["original"]["ev_value"], "0001.20")
        self.assertFalse(result["checkpoint_changed"])
        self.assertNotIn("private operator", output.getvalue())
        self.assertNotIn("TEST-ONLY-cli-secret", output.getvalue())

    @unittest.skipUnless(os.name == "nt", "requires real Windows desktop, DPAPI, and ACLs")
    def test_desktop_save_password_connect_and_preview_real_postgresql(self):
        import tkinter as tk
        from unittest.mock import patch
        from collector.desktop import EDITABLE_FIELDS
        from collector.gui import CollectorWindow

        self._run("""INSERT INTO public.alarmhistory
            (al_tag, al_message, al_tag_value, al_active, al_ack, al_user)
            VALUES ('GUI_DEMO', 'Desktop preview test', '0001.20', true, false, 'private operator');""")
        root = tk.Tk()
        root.withdraw()
        app = CollectorWindow(root, self.config.path.parent / "desktop" / "config.toml")
        try:
            def wait_idle():
                deadline = time.monotonic() + 10
                while app.busy and time.monotonic() < deadline:
                    root.update()
                    time.sleep(0.01)
                root.update()
                self.assertFalse(app.busy, "desktop operation timed out")

            with patch("collector.gui.messagebox.showerror") as errors:
                for name in EDITABLE_FIELDS:
                    app.variables[name].set(str(getattr(self.config, name)))
                app.save_button.invoke()
                wait_idle()
                self.assertIsNotNone(app.saved)
                self.assertEqual(load_config(app.config_path).database, self.database)
                app.password.set("TEST-ONLY-desktop-source-password")
                app.password_button.invoke()
                wait_idle()
                self.assertEqual(app.password.get(), "")
                self.assertTrue(app.saved.password_path.is_file())
                app.test_button.invoke()
                wait_idle()
                self.assertTrue(app.connected)
                app.notebook.select(1)
                app.preview_button.invoke()
                wait_idle()
                self.assertEqual(len(app.tree.get_children()), 1)
                values = app.tree.item("0", "values")
                self.assertEqual(values[2:7], ("GUI_DEMO", "Desktop preview test", "0001.20", "Yes", "No"))
                self.assertNotIn("private operator", json.dumps(app.records))
                self.assertNotIn("TEST-ONLY-desktop", app.config_path.read_text(encoding="utf-8"))
                errors.assert_not_called()
        finally:
            root.after_cancel(app.poll_id)
            root.destroy()
