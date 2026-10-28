from dataclasses import replace
import json
import os
from pathlib import Path
import tempfile
import unittest

from cryptography import x509

from collector.errors import CollectorError
from server.management.settings import ServerSettings,load_settings,save_settings
from server.management.tls import ensure_certificates,validate_certificate


class NetworkSettingsTests(unittest.TestCase):
    def test_modes_reject_unreachable_or_ambiguous_destinations(self):
        base=ServerSettings(Path('C:/central-server'))
        base.validate_network()
        network=replace(base,mode='network',listen_address='0.0.0.0',server_host='scada-central.example')
        network.validate_network()
        self.assertEqual(network.upload_url,'https://scada-central.example:8443/v1/uploads')
        for values in (dict(mode='bad'),dict(listen_address='0.0.0.0'),dict(server_host='10.0.0.4')):
            with self.subTest(values=values),self.assertRaises(CollectorError):replace(base,**values).validate_network()
        for host in ('localhost','127.0.0.1','127.0.0.2','0.0.0.0','https://server','server:8443','server/path','user@server','bad..host','999.999.1.1','::1'):
            with self.subTest(host=host),self.assertRaises(CollectorError):replace(network,server_host=host).validate_network()
        with self.assertRaises(CollectorError):replace(network,listen_address='127.0.0.1').validate_network()
        replace(network,server_host='192.168.10.5',listen_address='192.168.10.5').validate_network()

    def test_version_one_settings_load_as_local_testing(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'manager.json'
            doc=dict(version=1,data_dir=temporary,postgres_bin='C:/PostgreSQL/bin',database_port=55441,https_port=8443)
            path.write_text(json.dumps(doc))
            settings=load_settings(path)
            self.assertEqual(settings.mode,'local');self.assertEqual(settings.server_host,'localhost')
            self.assertEqual(settings.document()['version'],2)
            self.assertEqual(json.loads(path.read_text())['version'],1)

    def test_version_two_roundtrip_preserves_mode_and_rejects_unknown_fields(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'manager.json'
            settings=ServerSettings(Path(temporary),mode='network',listen_address='0.0.0.0',server_host='central-pc')
            path.write_text(json.dumps(settings.document()))
            self.assertEqual(load_settings(path),settings)
            value=settings.document();value['disable_tls']=True
            path.write_text(json.dumps(value))
            with self.assertRaises(CollectorError):load_settings(path)

    @unittest.skipUnless(os.name=='nt','Windows ACL certificate storage')
    def test_network_certificates_cover_hostname_ip_and_reuse_ca(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary)
            ensure_certificates(folder,'scada-central.test','0.0.0.0')
            validate_certificate(folder,'scada-central.test','0.0.0.0')
            original=(folder/'ca.pem').read_bytes()
            with self.assertRaises(CollectorError):validate_certificate(folder,'wrong-central.test','0.0.0.0')
            ensure_certificates(folder,'192.168.10.5','192.168.10.5')
            validate_certificate(folder,'192.168.10.5','192.168.10.5')
            self.assertEqual((folder/'ca.pem').read_bytes(),original)
            cert=x509.load_pem_x509_certificate((folder/'localhost.pem').read_bytes())
            self.assertIn(x509.IPAddress(__import__('ipaddress').ip_address('192.168.10.5')),cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value)
            key=(folder/'localhost-key.pem').read_bytes()
            ensure_certificates(folder,'192.168.10.5','192.168.10.5')
            self.assertEqual((folder/'localhost-key.pem').read_bytes(),key)
