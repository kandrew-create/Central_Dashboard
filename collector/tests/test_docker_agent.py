"""Exercise the stdin management boundary with disposable private local state."""
import base64
from dataclasses import replace
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from collector import docker_agent, secrets
from collector.desktop import DesktopService, config_document, default_config
from collector.errors import CollectorError
from collector.tests.test_setup_import import payload
from shared.setup_bundle import encode_setup


class DockerAgentTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        root = Path(folder.name)
        if os.name == 'posix':
            from collector.posix_secrets import create_key
            key = root / 'collector.key'
            create_key(key)
            environment = patch.dict(os.environ, COLLECTOR_SECRET_KEY_FILE=str(key))
            environment.start()
            self.addCleanup(environment.stop)
        self.config = DesktopService().save(default_config(root / 'setup/config.toml'))
        location = patch.object(docker_agent, 'CONFIG', self.config.path)
        location.start()
        self.addCleanup(location.stop)
        self.stop = threading.Event()
        self.document = config_document(self.config)

    def dispatch(self, action, **arguments):
        return docker_agent.dispatch(action, arguments, self.stop)

    def test_settings_and_credential_storage_never_return_plaintext(self):
        self.assertEqual(self.dispatch('load')['credentials'], dict(database=False, upload=False))
        for action, kind, secret in (('store_password', 'database', 'QA-ONLY-source-password'),
                                    ('store_upload_token', 'upload', 'T' * 43)):
            response = self.dispatch(action, expected=self.document, password=secret)
            self.assertTrue(response['credentials'][kind])
            self.assertNotIn(secret, json.dumps(response))
        self.assertEqual(secrets.load_password(self.config.password_path), 'QA-ONLY-source-password')
        self.assertEqual(secrets.load_password(self.config.upload_password_path), 'T' * 43)

    def test_stale_request_is_rejected_before_source_or_collection_work(self):
        stale = config_document(replace(self.config, port=55555))
        for action, method in (('check', 'check'), ('preview', 'preview'), ('collect', 'cycle'),
                               ('test_server', 'check_upload'), ('store_password', 'store_password')):
            with self.subTest(action=action), patch.object(DesktopService, method) as work:
                with self.assertRaisesRegex(CollectorError, 'changed outside'):
                    self.dispatch(action, expected=stale)
                work.assert_not_called()

    def test_save_preserves_external_changes_and_rejects_stale_previous_document(self):
        updated = config_document(replace(self.config, port=55555))
        saved = self.dispatch('save', document=updated, previous=self.document)
        self.assertEqual(saved['document'], updated)
        before = self.config.path.read_bytes()
        with self.assertRaisesRegex(CollectorError, 'changed outside'):
            self.dispatch('save', document=self.document, previous=self.document)
        self.assertEqual(self.config.path.read_bytes(), before)

    def test_collection_forwards_cancellation_without_starting_a_scheduler(self):
        with patch.object(DesktopService, 'cycle', return_value={'pending_batches': 1}) as cycle:
            self.assertEqual(self.dispatch('collect', expected=self.document), {'pending_batches': 1})
        cycle.assert_called_once_with(self.config, stop=self.stop)

    def test_encrypted_setup_import_preserves_local_settings_and_stores_credential(self):
        document = payload()
        encoded = encode_setup(document, 'QA-ONLY-file-password')
        response = self.dispatch('import_setup', expected=self.document,
                                 bundle=base64.b64encode(encoded).decode(), password='QA-ONLY-file-password')
        self.assertEqual(response['document']['database'], self.document['database'])
        self.assertEqual(response['document']['schedule'], self.document['schedule'])
        self.assertEqual(response['document']['collection']['source_id'], document['source_id'])
        self.assertTrue(response['credentials']['upload'])
        self.assertNotIn(document['upload_token'], json.dumps(response))

    def test_import_refuses_oversize_bundle_without_changing_settings(self):
        before = self.config.path.read_bytes()
        with self.assertRaisesRegex(CollectorError, 'size limit'):
            self.dispatch('import_setup', bundle=base64.b64encode(b'x' * 65537).decode(), password='unused')
        self.assertEqual(self.config.path.read_bytes(), before)
        self.assertFalse(self.config.upload_password_path.exists())

    def run_main(self, request):
        output = io.StringIO()
        with patch.object(docker_agent.sys, 'stdin', Mock(buffer=io.BytesIO(request))), patch.object(
                docker_agent.sys, 'stdout', output), patch.object(docker_agent.signal, 'signal'):
            code = docker_agent.main()
        return code, json.loads(output.getvalue())

    def test_stdin_rejects_malformed_unknown_and_oversize_requests_before_dispatch(self):
        requests = [b'[]', b'not-json', b'{"action":"unknown","arguments":{}}',
                    b'{"action":"load","arguments":{},"extra":"QA-ONLY-secret"}']
        with patch.object(docker_agent, 'dispatch') as dispatch:
            for request in requests:
                code, response = self.run_main(request)
                self.assertEqual(code, 1)
                self.assertFalse(response['ok'])
                self.assertNotIn('QA-ONLY-secret', json.dumps(response))
            with patch.object(docker_agent, 'MAX_REQUEST', 10):
                code, response = self.run_main(b'x' * 11)
                self.assertEqual(code, 1)
                self.assertFalse(response['ok'])
        dispatch.assert_not_called()

    def test_unexpected_failure_redacts_native_details(self):
        with patch.object(docker_agent, 'dispatch', side_effect=OSError('QA-ONLY-private-details')):
            code, response = self.run_main(b'{"action":"load","arguments":{}}')
        self.assertEqual(code, 1)
        self.assertNotIn('QA-ONLY-private-details', json.dumps(response))
