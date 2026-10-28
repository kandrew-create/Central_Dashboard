"""Actual TLS handshake checks, separate from HTTP mock-transport tests."""
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import ssl
import tempfile
import threading
import unittest
from unittest.mock import patch
from uuid import uuid4

from collector.desktop import default_config
from collector.errors import CollectorError
from collector.state import State
from collector.tests.test_delivery import wire
from collector.uploader import deliver


@unittest.skipUnless(__import__('os').name=='nt','local certificate helper requires Windows private ACLs')
class RealTlsTests(unittest.TestCase):
    def test_unknown_ca_fails_and_explicit_ca_succeeds_without_disabling_verification(self):
        from deploy.local_server import certificates
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)
            with patch('deploy.local_server.LOCAL',directory): certificates()
            config=replace(default_config(directory/'config.toml'),source_id=str(uuid4()),generation_id=str(uuid4()),
                           upload_enabled=True,min_free_bytes=0)
            state=State(config)
            try:
                state.stage([wire()],{'completed':{},'cycle':None})
                batch=json.loads(state.pending()['payload'])
                receipt=dict(batch_id=batch['batch_id'],payload_hash=batch['payload_hash'],status='committed')
                class Handler(BaseHTTPRequestHandler):
                    def do_POST(self):
                        self.rfile.read(int(self.headers['Content-Length']))
                        body=json.dumps(receipt).encode()
                        self.send_response(200)
                        self.send_header('Content-Type','application/json')
                        self.send_header('Content-Length',str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                    def log_message(self,*_): pass
                server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
                context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                context.load_cert_chain(directory/'localhost.pem',directory/'localhost-key.pem')
                server.socket=context.wrap_socket(server.socket,server_side=True)
                thread=threading.Thread(target=server.serve_forever,daemon=True)
                thread.start()
                try:
                    config=replace(config,upload_url=f'https://localhost:{server.server_port}/v1/uploads')
                    with patch('collector.uploader.load_password',return_value='TEST_ONLY_TOKEN'):
                        with self.assertRaises(CollectorError): deliver(config,state)
                        self.assertIsNotNone(state.pending())
                        state.db.execute('UPDATE queue SET retry_at=0')
                        self.assertTrue(deliver(replace(config,upload_ca_file=str(directory/'ca.pem')),state))
                    self.assertIsNone(state.pending())
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(5)
            finally:
                state.close()
