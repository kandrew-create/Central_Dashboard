from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

import httpx

from collector.connection import check_upload
from collector.desktop import default_config
from collector.errors import CollectorError


class ServerConnectionTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.config=replace(default_config(Path(self.folder.name)/'config.toml'),source_id=str(uuid4()),generation_id=str(uuid4()),
                            upload_url='https://central.example:8443/v1/uploads')

    def run_check(self,handler):
        client=httpx.Client(transport=httpx.MockTransport(handler))
        with patch('collector.connection.load_password',return_value='t'*43),patch('collector.connection.httpx.Client',return_value=client):
            return check_upload(self.config)

    def test_success_tests_only_identity_and_credential_with_no_record_or_state_writes(self):
        def handle(request):
            self.assertEqual(str(request.url),'https://central.example:8443/v1/collector-check')
            self.assertEqual(request.headers['authorization'],'Bearer '+'t'*43)
            value=json.loads(request.content)
            self.assertEqual(value,dict(source_id=self.config.source_id,generation_id=self.config.generation_id))
            return httpx.Response(200,json=dict(status='ready',**value))
        self.assertEqual(self.run_check(handle)['status'],'ready')
        self.assertEqual(list(Path(self.folder.name).iterdir()),[])

    def test_wrong_credentials_scope_redirect_and_mismatched_or_oversize_receipt_fail(self):
        for response in (httpx.Response(401),httpx.Response(403),httpx.Response(404),httpx.Response(302,headers={'Location':'https://elsewhere.example/'}),
                         httpx.Response(200,json={'status':'ready'}),httpx.Response(200,content=b'x'*4097,headers={'Content-Type':'application/json'})):
            with self.subTest(status=response.status_code),self.assertRaises(CollectorError):self.run_check(lambda _:response)

    def test_tls_transport_error_is_redacted_and_requires_saved_identity(self):
        def fail(_):raise httpx.ConnectError('private=do-not-display')
        with self.assertRaises(CollectorError) as error:self.run_check(fail)
        self.assertNotIn('do-not-display',str(error.exception))
        self.config=replace(self.config,source_id='')
        with self.assertRaises(CollectorError):self.run_check(lambda _:httpx.Response(200))
