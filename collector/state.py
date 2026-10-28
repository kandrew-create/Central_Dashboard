"""Crash-safe local queue. Staging progress and confirmed delivery are distinct."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

from collector.errors import CollectorError
from collector.records import canonical_bytes
from collector.secrets import restrict_access
from shared.protocol import make_batch, record_content_hash, validate_batch


def now():
    return datetime.now(timezone.utc).isoformat()


class State:
    def __init__(self, config):
        self.config = config
        self.path = config.state_path
        if self.path.is_symlink() or self.path.parent.is_symlink():
            raise CollectorError('Collector state must not use symbolic links.')
        self.path.parent.mkdir(exist_ok=True)
        if os.name == 'nt':
            restrict_access(self.path.parent)
        try:
            self.db = sqlite3.connect(self.path, timeout=1, isolation_level=None)
            self.db.row_factory = sqlite3.Row
            self.db.execute('PRAGMA journal_mode=DELETE')
            self.db.execute('PRAGMA synchronous=FULL')
            self.db.executescript('''
                CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS generation_history (generation TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS queue (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT, batch_id TEXT UNIQUE NOT NULL,
                    payload BLOB NOT NULL, after_state TEXT NOT NULL, created_at TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0, retry_at REAL NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS seen (
                    generation TEXT NOT NULL, source_table TEXT NOT NULL, source_id INTEGER NOT NULL,
                    hash TEXT NOT NULL, PRIMARY KEY(generation,source_table,source_id,hash));
                CREATE TABLE IF NOT EXISTS observed (
                    generation TEXT NOT NULL,source_table TEXT NOT NULL,source_id INTEGER NOT NULL,
                    hash TEXT NOT NULL,PRIMARY KEY(generation,source_table,source_id));
            ''')
            self.db.execute('INSERT OR IGNORE INTO generation_history SELECT DISTINCT generation FROM seen')
            prior_binding=self.get('binding')
            if prior_binding and prior_binding.get('generation_id'):
                self.db.execute('INSERT OR IGNORE INTO generation_history VALUES (?)',(prior_binding['generation_id'],))
            if os.name == 'nt':
                restrict_access(self.path)
        except (OSError, sqlite3.Error):
            raise CollectorError('Cannot open durable collector state; check disk and permissions.') from None

    def close(self):
        self.db.close()

    @contextmanager
    def lock(self, scheduler=False):
        path = self.path.with_suffix('.scheduler.lock' if scheduler else '.lock')
        with path.open('a+b') as handle:
            try:
                if os.fstat(handle.fileno()).st_size == 0:
                    handle.write(b'0')
                    handle.flush()
                handle.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise CollectorError('Another collection/upload cycle is already running.') from None
            try:
                yield
            finally:
                handle.seek(0)
                if os.name == 'nt':
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle, fcntl.LOCK_UN)

    @contextmanager
    def transaction(self):
        try:
            self.db.execute('BEGIN IMMEDIATE')
            yield
            self.db.execute('COMMIT')
        except Exception as error:
            if self.db.in_transaction:
                self.db.execute('ROLLBACK')
            if isinstance(error, (sqlite3.Error, OSError)):
                raise CollectorError('Durable storage failed; unconfirmed work and progress were preserved.') from None
            raise

    def get(self, key, default=None):
        row = self.db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def put(self, key, value):
        self.db.execute('INSERT INTO meta VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                        (key, json.dumps(value, separators=(',', ':'))))

    def guard_space(self, additional=0):
        usage = sum(p.stat().st_size for p in self.path.parent.iterdir() if p.is_file())
        if usage + additional + 65536 > self.config.queue_bytes or shutil.disk_usage(self.path.parent).free < self.config.min_free_bytes + additional:
            raise CollectorError('Collector storage limit reached; pending work is retained. Free space or raise the approved quota.')

    def stage(self, records, after_state, backfill=False):
        fresh = []
        observations=[]
        for record in records:
            identity = (self.config.generation_id, record['table'], record['original']['id'], record_content_hash(record['original']))
            prior=self.db.execute('SELECT hash FROM observed WHERE generation=? AND source_table=? AND source_id=?',identity[:3]).fetchone()
            # A -> B -> A is a new ordering observation even though the server
            # deduplicates the repeated A content into the same revision row.
            if self.db.execute('SELECT 1 FROM seen WHERE generation=? AND source_table=? AND source_id=? AND hash=?', identity).fetchone() is None or prior is None or prior['hash'] != identity[3]:
                fresh.append((record, identity))
            observations.append(identity)
        batch = make_batch(self.config.source_id, self.config.generation_id, str(uuid4()), [r for r, _ in fresh], self.config.privacy, backfill) if fresh else None
        if batch:
            validate_batch(batch)
        payload = canonical_bytes(batch) if batch else b''
        self.guard_space(len(payload) * 2 + len(records) * 256)
        with self.transaction():
            if batch:
                self.db.execute('INSERT INTO queue(batch_id,payload,after_state,created_at) VALUES (?,?,?,?)',
                                (batch['batch_id'], payload, json.dumps(after_state), now()))
                self.db.executemany('INSERT OR IGNORE INTO seen VALUES (?,?,?,?)', [identity for _, identity in fresh])
            self.db.executemany('''INSERT INTO observed VALUES (?,?,?,?) ON CONFLICT(generation,source_table,source_id)
                DO UPDATE SET hash=excluded.hash''',observations)
            self.put('staged', after_state)
            self.put('last_collection', now())
        return len(fresh)

    def pending(self):
        row = self.db.execute('SELECT * FROM queue ORDER BY sequence LIMIT 1').fetchone()
        return dict(row) if row else None

    def confirm(self, receipt):
        with self.transaction():
            first = self.pending()
            if first is None:
                raise CollectorError('No pending batch matches this confirmation.')
            batch = json.loads(first['payload'])
            expected = {k: batch[k] for k in ('batch_id', 'payload_hash')}
            expected['status'] = 'committed'
            if receipt != expected or set(receipt) != set(expected):
                raise CollectorError('Upload receipt does not match the pending batch.')
            self.put('confirmed', json.loads(first['after_state']))
            self.put('confirmed_generation',batch['generation_id'])
            self.put('last_receipt',receipt)
            self.put('last_upload', now())
            self.put('latest_confirmed_source', max([self.get('latest_confirmed_source') or '',
                *(r['original'].get('last_update') or '' for r in batch['records'])]) or None)
            self.db.execute('DELETE FROM queue WHERE sequence=?', (first['sequence'],))

    def status(self):
        count, size = self.db.execute('SELECT count(*),coalesce(sum(length(payload)),0) FROM queue').fetchone()
        return dict(pending_batches=count, pending_bytes=size, state_bytes=self.path.stat().st_size,
                    last_collection=self.get('last_collection'), last_successful_upload=self.get('last_upload'),
                    latest_confirmed_source_timestamp=self.get('latest_confirmed_source'),
                    next_run=self.get('next_run'), latest_error=self.get('latest_error'),
                    generation_id=self.get('binding', {}).get('generation_id'), confirmed_generation_id=self.get('confirmed_generation'),
                    cycle_in_progress=bool(self.get('staged', {}).get('cycle')))
