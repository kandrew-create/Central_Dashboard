from pathlib import Path
import tempfile
import unittest

from collector.config import EXAMPLE, load_config
from collector.errors import CollectorError


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "config.toml"

    def load(self, text=EXAMPLE):
        self.path.write_text(text, encoding="utf-8")
        return load_config(self.path)

    def test_example_is_valid_and_never_contains_password(self):
        config = self.load()
        self.assertEqual(config.table("alarmhistory"), "alarmhistory")
        self.assertEqual(config.timezone, "")
        self.assertEqual(config.password_path, self.path.parent.resolve() / "secrets/database-password.dpapi")
        self.assertNotIn("password =", EXAMPLE)
        shipped = Path(__file__).resolve().parents[1] / "config.example.toml"
        self.assertEqual(load_config(shipped).preview_rows, config.preview_rows)

    def test_unknown_settings_and_plaintext_password_are_rejected(self):
        for text in (EXAMPLE.replace('port = 5432', 'port = 5432\npassword = "secret-value"'),
                     EXAMPLE + '\n[extra_tables]\nHeartbeat = "Heartbeat"',
                     EXAMPLE.replace('[limits]', '[limit]')):
            with self.subTest(text=text), self.assertRaises(CollectorError) as result:
                self.load(text)
            self.assertNotIn("secret-value", str(result.exception))

    def test_resource_limits_require_bounded_integers(self):
        for old, new in (("preview_rows = 20", "preview_rows = 101"),
                         ("preview_rows = 20", "preview_rows = true"),
                         ("statement_timeout_ms = 5000", "statement_timeout_ms = 0"),
                         ("max_field_bytes = 4096", "max_field_bytes = 999999999")):
            with self.subTest(new=new), self.assertRaises(CollectorError):
                self.load(EXAMPLE.replace(old, new))

    def test_schema_and_table_identifiers_cannot_inject_sql(self):
        for bad in ('public; DROP TABLE alarmhistory', 'public.other', 'Heartbeat', 'x' * 64):
            with self.subTest(bad=bad), self.assertRaises(CollectorError):
                self.load(EXAMPLE.replace('schema = "public"', f'schema = "{bad}"'))

    def test_only_two_mappings_and_one_profile_are_supported(self):
        config = self.load()
        with self.assertRaises(CollectorError):
            config.table("Heartbeat")
        for text in (EXAMPLE.replace('event_table = "eventhistory"', 'event_table = "alarmhistory"'),
                     EXAMPLE.replace('alarm_table = "alarmhistory"', 'alarm_table = "Heartbeat"'),
                     EXAMPLE.replace('profile = "ecostruxure_machine_scada_expert_v1"', 'profile = "other"')):
            with self.subTest(text=text), self.assertRaises(CollectorError):
                self.load(text)

    def test_locally_approved_identifiers_can_be_configured(self):
        config = self.load(EXAMPLE.replace('schema = "public"', 'schema = "SCADA"')
                           .replace('alarm_table = "alarmhistory"', 'alarm_table = "ApprovedAlarms"'))
        self.assertEqual(config.schema, "SCADA")
        self.assertEqual(config.table("alarmhistory"), "ApprovedAlarms")

    def test_no_remote_plaintext_connection_or_connection_string(self):
        for text in (EXAMPLE.replace('host = "localhost"', 'host = "192.168.1.20"'),
                     EXAMPLE.replace('host = "localhost"', 'host = "host=secret password=leak"'),
                     EXAMPLE.replace('sslmode = "disable"', 'sslmode = []')):
            with self.subTest(text=text), self.assertRaises(CollectorError):
                self.load(text)

    def test_timezone_is_explicit_and_validated(self):
        self.assertEqual(self.load(EXAMPLE.replace('timezone = ""', 'timezone = "America/Toronto"')).timezone,
                         "America/Toronto")
        with self.assertRaises(CollectorError):
            self.load(EXAMPLE.replace('timezone = ""', 'timezone = "not/a/zone"'))

    def test_missing_bad_or_oversized_config_fails_safely(self):
        with self.assertRaises(CollectorError):
            load_config(self.path)
        for text in ('[database', 'x' * 16385, 'version = true'):
            with self.subTest(text=text[:20]), self.assertRaises(CollectorError):
                self.load(text)
