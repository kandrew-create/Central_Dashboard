from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from collector.records import source_time
from collector.time_display import windows_timezone, next_run_text


class TimeDisplayTests(unittest.TestCase):
    def test_windows_display_honors_historical_dst_without_changing_source_interpretation(self):
        with patch.dict('os.environ', COLLECTOR_WINDOWS_TIMEZONE='America/New_York'):
            for month, hour in ((1, '07:00:00 EST'), (7, '08:00:00 EDT')):
                stamp = datetime(2026, month, 1, 12, tzinfo=timezone.utc).timestamp()
                text, zone = next_run_text(stamp, 'America/New_York')
                self.assertIn(hour, text)
                self.assertEqual(zone, 'America/New_York')
            result = source_time(datetime(2026, 1, 1, 12), 0, '')
            self.assertEqual(result['quality'], 'timezone_unknown')
            self.assertIsNone(result['utc'])

    def test_custom_choice_controls_display_even_when_windows_uses_a_different_zone(self):
        stamp = datetime(2026, 1, 1, 12, tzinfo=timezone.utc).timestamp()
        with patch.dict('os.environ', COLLECTOR_WINDOWS_TIMEZONE='America/New_York'):
            text, zone = next_run_text(stamp, 'Europe/London')
        self.assertIn('12:00:00 GMT', text)
        self.assertEqual(zone, 'Europe/London')

    def test_missing_or_invalid_host_zone_uses_saved_schedule_zone_for_display(self):
        for name in ('', 'not/a/zone'):
            with patch.dict('os.environ', COLLECTOR_WINDOWS_TIMEZONE=name):
                self.assertEqual(windows_timezone(), '')
                self.assertEqual(next_run_text(None, 'UTC'), ('Not scheduled', 'UTC'))
