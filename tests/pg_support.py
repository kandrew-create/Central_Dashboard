"""Real PostgreSQL tests without requiring a Python database driver.

pytest collects these unittest cases too. The stdlib runner is useful when package
downloads are blocked. Every suite owns a randomly named disposable database;
source/customer databases are never used or modified.
"""
import os
from pathlib import Path
import shutil
import subprocess
import unittest
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[1]
UP = ROOT / "server/migrations/sql/0001_foundation.sql"
DOWN = ROOT / "server/migrations/sql/0001_foundation_down.sql"
ROLES = ROOT / "deploy/bootstrap_roles.sql"
FIXTURE = ROOT / "tests/fixtures/scada_schema.sql"


def uid(number):
    return str(UUID(int=number))


def seed_sql():
    statements = []
    for offset in (0, 100):
        c, s, p, m, collector, source, generation, mapping = [uid(offset + n) for n in range(1, 9)]
        statements.extend([
            f"INSERT INTO platform.customers VALUES ('{c}', 'Customer {offset}', now());",
            f"INSERT INTO platform.sites VALUES ('{s}', '{c}', 'Site');",
            f"INSERT INTO platform.projects VALUES ('{p}', '{c}', '{s}', 'Project');",
            f"INSERT INTO platform.machines VALUES ('{m}', '{c}', '{s}', '{p}', 'LINE-01', 'Machine');",
            f"INSERT INTO platform.collectors VALUES ('{collector}', '{c}', '{s}', 'PC', NULL);",
            f"INSERT INTO platform.sources VALUES ('{source}', '{c}', '{s}', '{p}', '{collector}', 'Source', 'ecostruxure_machine_scada_expert_v1', NULL);",
            f"INSERT INTO platform.source_generations VALUES ('{generation}', '{c}', '{source}', 1, 'test-db', 'local-admin', 'local-ticket-1', now(), NULL);",
            f"INSERT INTO platform.mapping_versions (mapping_version_id, customer_id, site_id, project_id, source_id, version) VALUES ('{mapping}', '{c}', '{s}', '{p}', '{source}', 1);",
        ])
    return "\n".join(statements)


def batch_sql(upload=20, batch=21, customer=1, source=6, generation=7, digest="a" * 64):
    return f"""INSERT INTO platform.upload_batches
        (upload_id, customer_id, source_id, generation_id, batch_id, payload_hash,
         schema_version, payload, record_count, payload_bytes, receipt)
        VALUES ('{uid(upload)}', '{uid(customer)}', '{uid(source)}', '{uid(generation)}',
            '{uid(batch)}', '{digest}', 1, '{{"records":[]}}', 1, 14,
            jsonb_build_object('batch_id', '{uid(batch)}', 'payload_hash', '{digest}', 'status', 'committed'));"""


def revision_sql(revision=30, source_record_id=1, key="revision-1", digest="b" * 64):
    return f"""INSERT INTO platform.alarm_event_revisions
        (revision_id, customer_id, site_id, project_id, source_id, generation_id, upload_id,
         source_table, record_type, source_record_id, revision_key, content_hash,
         original_payload, source_timezone, ordering_uncertain, mapping_status,
         start_time_quality, norm_time_quality, ack_time_quality, event_time_quality, last_update_quality)
        VALUES ('{uid(revision)}', '{uid(1)}', '{uid(2)}', '{uid(3)}', '{uid(6)}', '{uid(7)}', '{uid(20)}',
            'alarmhistory', 'alarm', {source_record_id}, '{key}', '{digest}', '{{}}', 'America/Toronto',
            true, 'quarantined', 'missing', 'missing', 'missing', 'missing', 'missing');"""


class PostgresCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get("SCADA_TEST_POSTGRES") != "1":
            raise unittest.SkipTest("set SCADA_TEST_POSTGRES=1 for disposable real-PostgreSQL tests")
        cls.psql = os.environ.get("PSQL") or shutil.which("psql")
        if not cls.psql:
            raise RuntimeError("psql required when PostgreSQL tests are enabled")
        cls.database = "scada_test_" + uuid4().hex
        cls.base_database = os.environ.get("PGDATABASE", "postgres")
        cls._run(f'CREATE DATABASE "{cls.database}";', database=cls.base_database)
        # Even a migration/fixture failure cleans up the disposable database.
        cls.addClassCleanup(cls._drop_database)
        cls._run("BEGIN;\n" + UP.read_text(encoding="utf-8") + "\n"
                 + ROLES.read_text(encoding="utf-8") + "\n"
                 + FIXTURE.read_text(encoding="utf-8") + "\n"
                 + seed_sql() + "\nCOMMIT;")

    @classmethod
    def _drop_database(cls):
        cls._run(f'DROP DATABASE "{cls.database}" WITH (FORCE);', database=cls.base_database)

    @classmethod
    def _run(cls, sql, database=None, succeeds=True):
        # PGPASSWORD is inherited in the environment, never included in argv/logs.
        result = subprocess.run(
            [str(cls.psql), "-X", "-q", "-A", "-t", "-w", "-v", "ON_ERROR_STOP=1",
             "-v", "VERBOSITY=verbose", "-d", database or cls.database],
            input=sql, text=True, encoding="utf-8", capture_output=True,
            env={**os.environ, "PGCLIENTENCODING": "UTF8"}, timeout=60,
        )
        if succeeds and result.returncode:
            raise AssertionError("PostgreSQL statement failed:\n" + result.stderr)
        if not succeeds and not result.returncode:
            raise AssertionError("PostgreSQL unexpectedly accepted invalid statement")
        return result

    def sql(self, body, role=None, customer=1, succeeds=True):
        prefix = "BEGIN;\n"
        if role:
            if role not in {"scada_ingest", "scada_worker", "scada_reader", "scada_registry"}:
                raise ValueError("unknown test role")
            prefix += f"SET LOCAL ROLE {role};\n"
        if customer is not None:
            prefix += f"SELECT set_config('app.customer_id', '{uid(customer)}', true);\n"
        result = self._run(prefix + body + "\nROLLBACK;", succeeds=succeeds)
        return result

    def rejected(self, body, sqlstate, **kwargs):
        result = self.sql(body, succeeds=False, **kwargs)
        self.assertIn(sqlstate, result.stderr)
