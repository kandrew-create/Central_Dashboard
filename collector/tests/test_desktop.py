from dataclasses import replace
import os
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from collector.config import load_config
from collector.desktop import (DesktopService, EDITABLE_FIELDS, config_document, default_config,
                               form_config, serialize_config, table_values)
from collector.errors import CollectorError
from collector.profiles.ecostruxure import COLUMNS
from collector.records import preview_record


class DesktopFormTests(unittest.TestCase):
    def setUp(self):
        self.base = default_config(Path("collector-local/config.toml"))
        self.fields = {name: str(getattr(self.base, name)) for name in EDITABLE_FIELDS}

    def test_form_uses_the_same_schema_tls_and_numeric_validation(self):
        for field, value in (("port", "not-a-number"), ("port", "65536"), ("host", "192.168.1.2"),
                             ("schema", "public; drop table x"), ("alarm_table", "Heartbeat"),
                             ("timezone", "not/a/timezone")):
            with self.subTest(field=field, value=value), self.assertRaises(CollectorError):
                form_config(self.base, {**self.fields, field: value})

    def test_roundtrip_preserves_advanced_limits_and_quoted_unicode_names(self):
        base = replace(self.base, max_field_bytes=8192, preview_rows=7, statement_timeout_ms=1250)
        result = form_config(base, {**self.fields, "database": 'SCADA "ligné"', "port": "55440"})
        document = tomllib.loads(serialize_config(result))
        self.assertEqual(document, config_document(result))
        self.assertEqual(document["limits"]["preview_rows"], 7)
        self.assertEqual(document["limits"]["max_field_bytes"], 8192)
        self.assertEqual(document["database"]["statement_timeout_ms"], 1250)
        self.assertEqual(document["database"]["name"], 'SCADA "ligné"')

    def test_form_cannot_persist_a_password_or_extra_fields(self):
        with self.assertRaises(CollectorError):
            form_config(self.base, {**self.fields, "password": "must-not-be-saved"})
        with self.assertRaises(CollectorError):
            form_config(self.base, {name: value for name, value in self.fields.items() if name != "host"})
        self.assertNotIn("password =", serialize_config(self.base))

    def test_record_summary_preserves_zero_strings_and_unknown_flags(self):
        row = {name: None for name in COLUMNS["alarmhistory"]}
        row.update(id=1, al_tag="TAG", al_message="Message", al_tag_value="000.0", al_ack=False)
        values = table_values(preview_record("alarmhistory", row, ""))
        self.assertEqual(values[4], "000.0")
        self.assertEqual(values[5:8], ("Unknown", "No", "Missing"))


class SourceTimezoneSaveTests(unittest.TestCase):
    def test_bound_timezone_change_is_rejected_before_config_or_queue_changes(self):
        from collector.collection import binding
        from collector.state import State
        with tempfile.TemporaryDirectory() as folder:
            service = DesktopService()
            config = service.save(default_config(Path(folder) / 'setup/config.toml'))
            state = State(config)
            state.put('binding', binding(config))
            state.close()
            original_config = config.path.read_bytes()
            original_state = config.state_path.read_bytes()
            with self.assertRaisesRegex(CollectorError, 'provisioned new generation'):
                service.save(replace(config, timezone='America/New_York', use_pc_timezone=True), config)
            self.assertEqual(config.path.read_bytes(), original_config)
            self.assertEqual(config.state_path.read_bytes(), original_state)

    def test_uncollected_setup_can_save_pc_local_choice_and_later_choose_manual(self):
        with tempfile.TemporaryDirectory() as folder:
            service = DesktopService()
            config = service.save(default_config(Path(folder) / 'setup/config.toml'))
            local = service.save(replace(config, timezone='America/New_York', use_pc_timezone=True), config)
            self.assertTrue(local.use_pc_timezone)
            self.assertEqual(local.timezone, 'America/New_York')
            manual = service.save(replace(local, use_pc_timezone=False), local)
            self.assertFalse(manual.use_pc_timezone)
            self.assertEqual(manual.timezone, 'America/New_York')


@unittest.skipUnless(os.name == "nt", "requires actual Windows private-file ACLs")
class DesktopPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "private" / "config.toml"
        self.service = DesktopService()

    def test_create_and_edit_settings_without_touching_the_password(self):
        initial = self.service.save(default_config(self.path))
        self.service.store_password(initial, "TEST-ONLY-desktop-password")
        encrypted_before = initial.password_path.read_bytes()
        updated = self.service.save(replace(initial, port=55440, preview_rows=7), initial)
        self.assertEqual(updated.port, 55440)
        self.assertEqual(updated.preview_rows, 7)
        self.assertEqual(updated.password_path.read_bytes(), encrypted_before)
        self.assertNotIn("TEST-ONLY-desktop-password", self.path.read_text(encoding="utf-8"))

    def test_manual_cycle_forwards_its_stop_signal(self):
        import threading
        initial = self.service.save(default_config(self.path))
        stop = threading.Event()
        with patch('collector.runtime.cycle', return_value={'pending_batches': 0}) as cycle:
            self.assertEqual(self.service.cycle(initial, stop=stop), {'pending_batches': 0})
        cycle.assert_called_once_with(initial, stop=stop)

    def test_new_setup_cannot_overwrite_an_existing_file(self):
        initial = self.service.save(default_config(self.path))
        with self.assertRaisesRegex(CollectorError, "already exists"):
            self.service.save(replace(initial, port=55440))
        self.assertEqual(load_config(self.path).port, 5432)

    def test_external_edits_are_preserved_and_prevent_a_database_connection(self):
        initial = self.service.save(default_config(self.path))
        external = replace(initial, port=55440)
        self.path.write_text(serialize_config(external), encoding="utf-8")
        with self.assertRaisesRegex(CollectorError, "changed outside"):
            self.service.save(replace(initial, port=55555), initial)
        with patch("collector.desktop.SourceReader") as reader:
            with self.assertRaisesRegex(CollectorError, "changed outside"):
                self.service.check(initial)
            reader.assert_not_called()
        self.assertEqual(load_config(self.path).port, 55440)

    def test_private_write_failure_preserves_original_and_removes_temporary_file(self):
        initial = self.service.save(default_config(self.path))
        with patch("collector.secrets.restrict_access", side_effect=CollectorError("permission failure")):
            with self.assertRaises(CollectorError):
                self.service.save(replace(initial, port=55440), initial)
        self.assertEqual(load_config(self.path), initial)
        self.assertEqual(list(self.path.parent.glob(".settings-*")), [])
