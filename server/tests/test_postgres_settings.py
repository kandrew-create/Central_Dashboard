import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock,patch

from collector.errors import CollectorError
from server.management.postgres import default_postgres_bin,postgres_major,REQUIRED_TOOLS
from server.management.settings import ServerSettings,load_settings,save_settings


class PostgresSettingsTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.root=Path(self.folder.name)
        self.bin=self.root/'bin';self.bin.mkdir()
        for name in REQUIRED_TOOLS:(self.bin/name).touch()
        self.settings=ServerSettings(self.root/'data',self.bin)

    def version(self,major):
        return Mock(returncode=0,stdout=f'postgres (PostgreSQL) {major}.1\n')

    def cluster(self,major):
        (self.settings.data_dir/'database').mkdir(parents=True)
        (self.settings.data_dir/'database/PG_VERSION').write_text(str(major))
        (self.settings.data_dir/'credentials.dpapi').write_bytes(b'protected-placeholder')

    def test_new_and_existing_17_and_18_clusters_are_accepted(self):
        for major in (17,18):
            with self.subTest(major=major),patch('server.management.postgres.subprocess.run',return_value=self.version(major)):
                self.assertIs(self.settings.validate(),self.settings)
                self.cluster(major)
                self.assertIs(self.settings.validate(),self.settings)
                (self.settings.data_dir/'database/PG_VERSION').unlink()
                (self.settings.data_dir/'database').rmdir()
                (self.settings.data_dir/'credentials.dpapi').unlink()
                self.settings.data_dir.rmdir()

    def test_mismatching_binaries_reject_without_changing_data(self):
        for stored,selected in ((17,18),(18,17)):
            with self.subTest(stored=stored,selected=selected):
                if not self.settings.data_dir.exists():self.cluster(stored)
                else:(self.settings.data_dir/'database/PG_VERSION').write_text(str(stored))
                before={p.name:p.read_bytes() for p in self.settings.data_dir.rglob('*') if p.is_file()}
                with patch('server.management.postgres.subprocess.run',return_value=self.version(selected)):
                    with self.assertRaisesRegex(CollectorError,'separate database migration'):self.settings.validate()
                self.assertEqual(before,{p.name:p.read_bytes() for p in self.settings.data_dir.rglob('*') if p.is_file()})

    def test_unsupported_and_corrupt_cluster_versions_are_rejected(self):
        self.cluster(16)
        with patch('server.management.postgres.subprocess.run',return_value=self.version(18)):
            with self.assertRaisesRegex(CollectorError,'Migrate other major versions separately'):self.settings.validate()
            (self.settings.data_dir/'database/PG_VERSION').write_text('invalid')
            with self.assertRaisesRegex(CollectorError,'Cannot read'):self.settings.validate()

    def test_missing_server_binary_and_relative_bin_are_rejected(self):
        (self.bin/'postgres.exe').unlink()
        with self.assertRaisesRegex(CollectorError,'postgres.exe'):postgres_major(self.bin)
        with self.assertRaises(CollectorError):postgres_major(Path('relative/bin'))

    def test_unsupported_mixed_or_unparseable_tools_are_rejected(self):
        for outputs in ((16,16,16),(19,19,19),(18,17,18),('invalid','invalid','invalid')):
            with self.subTest(outputs=outputs),patch('server.management.postgres.subprocess.run',side_effect=[self.version(n) for n in outputs]):
                with self.assertRaises(CollectorError):postgres_major(self.bin)

    def test_failed_or_hanging_binaries_give_actionable_errors(self):
        for failure in (OSError('missing DLL'),subprocess.TimeoutExpired('postgres',5)):
            with self.subTest(failure=failure),patch('server.management.postgres.subprocess.run',side_effect=failure):
                with self.assertRaisesRegex(CollectorError,'Cannot verify'):postgres_major(self.bin)
        with patch('server.management.postgres.subprocess.run',return_value=Mock(returncode=1,stdout='')):
            with self.assertRaisesRegex(CollectorError,'Cannot verify'):postgres_major(self.bin)

    def test_new_default_prefers_18_but_existing_cluster_keeps_17(self):
        with patch.dict(os.environ,{'ProgramFiles':str(self.root)}):
            for major in (17,18):
                folder=self.root/'PostgreSQL'/str(major)/'bin';folder.mkdir(parents=True)
                for name in REQUIRED_TOOLS:(folder/name).touch()
            self.assertEqual(default_postgres_bin(),self.root/'PostgreSQL/18/bin')
            self.cluster(17)
            self.assertEqual(default_postgres_bin(self.settings.data_dir),self.root/'PostgreSQL/17/bin')
            (self.root/'PostgreSQL/17/bin/postgres.exe').unlink()
            self.assertEqual(default_postgres_bin(self.settings.data_dir),self.root/'PostgreSQL/17/bin')
            (self.root/'PostgreSQL/18/bin/postgres.exe').unlink()
            self.assertEqual(default_postgres_bin(),self.root/'PostgreSQL/18/bin')

    def test_detection_falls_back_to_installed_17(self):
        with patch.dict(os.environ,{'ProgramFiles':str(self.root)}):
            folder=self.root/'PostgreSQL/17/bin';folder.mkdir(parents=True)
            for name in REQUIRED_TOOLS:(folder/name).touch()
            self.assertEqual(default_postgres_bin(),folder)

    @unittest.skipUnless(os.name=='nt','Windows private settings storage')
    def test_saved_18_location_roundtrips_without_silent_redetection(self):
        path=self.root/'manager/manager.json'
        with patch('server.management.postgres.subprocess.run',return_value=self.version(18)):
            save_settings(self.settings,path)
        with patch('server.management.settings.default_postgres_bin',side_effect=AssertionError('saved settings must be retained')):
            self.assertEqual(load_settings(path),self.settings)
        self.assertEqual(json.loads(path.read_text())['postgres_bin'],str(self.bin))

    def test_direct_start_checks_version_before_any_database_changes(self):
        from deploy import local_server
        self.cluster(17)
        with patch.object(local_server,'LOCAL',self.settings.data_dir),patch.object(local_server,'BIN',self.bin),patch('server.management.postgres.subprocess.run',return_value=self.version(18)),patch('deploy.local_server.save_password') as save:
            with self.assertRaisesRegex(CollectorError,'separate database migration'):local_server.setup_database()
        save.assert_not_called()
