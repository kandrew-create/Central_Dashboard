from copy import deepcopy
from dataclasses import replace
from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from collector.collection import binding, collect, preflight
from collector.desktop import default_config
from collector.errors import CollectorError
from collector.profiles.ecostruxure import COLUMNS
from collector.state import State
from collector.timezone_policy import first_assignment
from shared.protocol import validate_batch


def source_row(native_id, table='alarmhistory'):
    row = {name: None for name in COLUMNS[table]}
    row.update(id=native_id, last_update=datetime(2026, 11, 7, 11), last_update_ms=0)
    if table == 'alarmhistory':
        row.update(al_start_time=datetime(2026, 11, 7, 10), al_start_time_ms=0,
                   al_tag='TAG', al_message='Synthetic alarm', al_active=True)
    else:
        row.update(ev_time=datetime(2026, 11, 7, 10), ev_time_ms=0, ev_message='Synthetic event')
    return row


class MemorySource:
    def __init__(self):
        self.rows = dict(alarmhistory=[source_row(1)], eventhistory=[])
        self.fingerprint = [1, 2, 3]

    def bounds(self):
        return {table: dict(fingerprint=list(self.fingerprint),
                           high_id=max((row['id'] for row in rows), default=None), marker=None)
                for table, rows in self.rows.items()}

    def scan_page(self, table, phase, bound, cursor, lower, history):
        return sorted((dict(row) for row in self.rows[table]
                       if row['id'] <= bound['high_id'] and (cursor is None or row['id'] > cursor)),
                      key=lambda row: row['id'])


class ProspectiveTimezoneTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.config = replace(default_config(Path(self.folder.name) / 'config.toml'),
                              source_id=str(uuid4()), generation_id=str(uuid4()),
                              collection_enabled=True, all_history=True, min_free_bytes=0)
        self.state = State(self.config)
        self.addCleanup(lambda: self.state.close())
        self.reader = MemorySource()
        collect(self.config, self.reader, self.state)
        self.known = replace(self.config, timezone='America/New_York', schedule_timezone='America/New_York')

    def payloads(self):
        return [row[0] for row in self.state.db.execute('SELECT payload FROM queue ORDER BY sequence')]

    def test_cutover_preserves_pending_history_and_dates_only_future_ids(self):
        original_payloads = self.payloads()
        # Uncollected rows already present at cutover are historical too.
        self.reader.rows['alarmhistory'].append(source_row(2))
        collect(self.known, self.reader, self.state)
        policy = self.state.get('timezone_policy')
        self.assertEqual(policy['historical_high_ids'], dict(alarmhistory=2, eventhistory=None))
        self.assertEqual(self.state.get('binding'), binding(self.known))
        self.assertEqual(self.payloads()[:len(original_payloads)], original_payloads)
        self.state.close()
        self.state = State(self.known)
        self.reader.rows['alarmhistory'][0]['al_active'] = False
        self.reader.rows['alarmhistory'].extend([source_row(3), source_row(-1)])
        self.reader.rows['eventhistory'].append(source_row(-5, 'eventhistory'))
        collect(self.known, self.reader, self.state)
        decoded = [record for payload in self.payloads() for record in validate_batch(json.loads(payload))]
        historical = [row for row in decoded if row['source_table'] == 'alarmhistory' and row['source_record_id'] <= 2]
        self.assertTrue(historical)
        self.assertTrue(all(row['source_timezone'] is None for row in historical))
        new_alarm = next(row for row in decoded if row['source_table'] == 'alarmhistory' and row['source_record_id'] == 3)
        self.assertEqual(new_alarm['times']['al_start_time']['quality'], 'known')
        self.assertEqual(new_alarm['times']['al_start_time']['utc'], '2026-11-07T15:00:00.000Z')
        new_event = next(row for row in decoded if row['source_table'] == 'eventhistory')
        self.assertEqual(new_event['source_timezone'], 'America/New_York')
        self.assertEqual(self.payloads()[:len(original_payloads)], original_payloads)
        self.assertEqual(self.state.get('binding')['generation_id'], self.config.generation_id)

    def test_cutoff_and_binding_are_atomic_and_retryable_after_failure(self):
        prior = deepcopy(self.state.get('staged'))
        payloads = self.payloads()
        original_put = self.state.put
        def fail(key, value):
            if key == 'binding':
                raise OSError('synthetic interrupted cutoff commit')
            original_put(key, value)
        with patch.object(self.state, 'put', side_effect=fail), self.assertRaises(CollectorError):
            preflight(self.known, self.reader, self.state)
        self.assertIsNone(self.state.get('timezone_policy'))
        self.assertEqual(self.state.get('binding'), binding(self.config))
        self.assertEqual(self.state.get('staged'), prior)
        self.assertEqual(self.payloads(), payloads)
        preflight(self.known, self.reader, self.state)
        self.assertEqual(self.state.get('binding'), binding(self.known))

    def test_reset_and_relation_changes_cannot_be_bypassed_by_timezone_selection(self):
        self.reader.fingerprint = [9, 9, 9]
        with self.assertRaisesRegex(CollectorError, 'local review'):
            preflight(self.known, self.reader, self.state)
        self.assertTrue(self.state.get('reset_fault'))
        self.assertIsNone(self.state.get('timezone_policy'))
        self.assertEqual(self.state.get('binding'), binding(self.config))
        with self.assertRaisesRegex(CollectorError, 'fault is latched'):
            preflight(self.known, self.reader, self.state)

    def test_only_first_timezone_assignment_is_eligible(self):
        prior = binding(self.config)
        current = binding(self.known)
        self.assertTrue(first_assignment(prior, current))
        self.assertFalse(first_assignment(current, binding(replace(self.known, timezone='UTC'))))
        self.assertFalse(first_assignment(current, prior))
        self.assertFalse(first_assignment(prior, binding(replace(self.known, source_id=str(uuid4())))))
        self.assertFalse(first_assignment(prior, binding(replace(self.known, privacy='omit'))))
        self.assertFalse(first_assignment(None, current))

    def test_preview_keeps_historical_times_unknown_before_and_after_activation(self):
        from collector.records import preview_record
        from collector.timezone_policy import preserve_preview_history
        pending = preview_record('alarmhistory', source_row(1), self.known.timezone)
        result = preserve_preview_history(self.known, binding(self.config), None, [pending])
        self.assertIsNone(result[0]['source_timezone'])
        self.assertEqual(result[0]['times']['al_start_time']['quality'], 'timezone_unknown')
        preflight(self.known, self.reader, self.state)
        old = preview_record('alarmhistory', source_row(1), self.known.timezone)
        new = preview_record('alarmhistory', source_row(2), self.known.timezone)
        result = preserve_preview_history(self.known, binding(self.known), self.state.get('timezone_policy'), [old, new])
        self.assertIsNone(result[0]['source_timezone'])
        self.assertEqual(result[1]['times']['al_start_time']['quality'], 'known')
