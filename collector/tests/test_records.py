from datetime import datetime
import unittest

from collector.profiles.ecostruxure import COLUMNS
from collector.records import preview_record, source_time


class TimestampTests(unittest.TestCase):
    def test_milliseconds_and_known_utc_conversion(self):
        value = source_time(datetime(2026, 10, 28, 10), 123, "America/Toronto")
        self.assertEqual(value, {"local": "2026-10-28T10:00:00.000000", "milliseconds": 123,
                                 "utc": "2026-10-28T14:00:00.123Z", "quality": "known"})

    def test_dst_ambiguity_and_nonexistent_times_have_no_guessed_offset(self):
        for local, quality in ((datetime(2026, 11, 1, 1, 30), "ambiguous"),
                               (datetime(2026, 3, 8, 2, 30), "nonexistent")):
            with self.subTest(local=local):
                value = source_time(local, 0, "America/Toronto")
                self.assertEqual(value["quality"], quality)
                self.assertIsNone(value["utc"])

    def test_unknown_timezone_does_not_assume_machine_timezone(self):
        value = source_time(datetime(2026, 10, 28, 10), 0, "")
        self.assertEqual(value["quality"], "timezone_unknown")
        self.assertIsNone(value["utc"])

    def test_invalid_or_missing_milliseconds_are_preserved(self):
        for ms in (None, -1, 1000, True, "1"):
            with self.subTest(ms=ms):
                value = source_time(datetime(2026, 10, 28), ms, "UTC")
                self.assertEqual(value["quality"], "invalid")
                self.assertEqual(value["milliseconds"], ms)
                self.assertIsNone(value["utc"])

    def test_fractional_source_timestamp_is_not_silently_double_counted(self):
        value = source_time(datetime(2026, 10, 28, microsecond=123000), 123, "UTC")
        self.assertEqual(value["quality"], "invalid")
        self.assertEqual(value["local"], "2026-10-28T00:00:00.123000")

    def test_missing_lifecycle_time_remains_null(self):
        self.assertEqual(source_time(None, None, "UTC"),
                         {"local": None, "milliseconds": None, "utc": None, "quality": "missing"})


class RecordTests(unittest.TestCase):
    def row(self):
        row = {key: None for key in COLUMNS["alarmhistory"]}
        row.update(id=1, al_tag_value="0001.20", al_prev_tag_value="true", al_type=999,
                   al_deleted=True, al_user="operator", al_user_full="Private Name", al_user_comment="private",
                   last_update=datetime(2026, 10, 28, 10), last_update_ms=1)
        return row

    def test_strings_raw_codes_flags_and_nulls_are_preserved(self):
        row = self.row()
        result = preview_record("alarmhistory", row, "UTC")
        self.assertEqual(result["original"]["al_tag_value"], "0001.20")
        self.assertEqual(result["original"]["al_prev_tag_value"], "true")
        self.assertEqual(result["original"]["al_type"], 999)
        self.assertIs(result["original"]["al_deleted"], True)
        self.assertIsNone(result["original"]["al_ack_time"])
        self.assertTrue(result["ordering_uncertain"])

    def test_operator_fields_require_explicit_local_preview_option(self):
        row = self.row()
        omitted = preview_record("alarmhistory", row, "UTC")
        included = preview_record("alarmhistory", row, "UTC", include_user_fields=True)
        self.assertNotIn("al_user", omitted["original"])
        self.assertEqual(included["original"]["al_user"], "operator")
        self.assertEqual(omitted["content_hash"], included["content_hash"])
        self.assertEqual(row["al_user"], "operator")

    def test_marker_only_change_does_not_change_content_hash(self):
        row = self.row()
        before = preview_record("alarmhistory", row, "UTC")
        row["last_update_ms"] = 2
        after = preview_record("alarmhistory", row, "UTC")
        self.assertEqual(before["content_hash"], after["content_hash"])
        self.assertNotEqual(before["times"]["last_update"], after["times"]["last_update"])

    def test_changed_content_with_same_marker_is_distinguishable(self):
        row = self.row()
        before = preview_record("alarmhistory", row, "UTC")
        row["al_ack"] = True
        after = preview_record("alarmhistory", row, "UTC")
        self.assertNotEqual(before["content_hash"], after["content_hash"])
        self.assertEqual(before["times"]["last_update"], after["times"]["last_update"])

    def test_hashing_is_independent_of_column_order(self):
        row = self.row()
        self.assertEqual(preview_record("alarmhistory", row, "UTC")["content_hash"],
                         preview_record("alarmhistory", dict(reversed(list(row.items()))), "UTC")["content_hash"])
