from dataclasses import replace
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch

from cryptography import x509

from collector.errors import CollectorError
from server.management.settings import ServerSettings,load_settings,save_settings
from server.management.tls import ensure_certificates,validate_certificate


class NetworkSettingsTests(unittest.TestCase):
    def test_local_listener_probe_accepts_loopback_and_all_adapters(self):
        base=ServerSettings(Path('C:/central-server'))
        self.assertIs(base.validate_listener(),base)
        replace(base,mode='network',listen_address='0.0.0.0',server_host='central-pc').validate_listener()

    def test_unassigned_listener_blocks_save_and_start_before_changing_state(self):
        from server.management.runtime import control
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary)
            path=folder/'manager.json';path.write_text('preserve existing settings')
            settings=ServerSettings(folder/'data',mode='network',listen_address='203.0.113.45',server_host='central-pc')
            with patch('server.management.settings.socket.socket') as socket_factory,patch('server.management.settings.postgres_major') as postgres,patch('server.management.runtime.subprocess.run') as run:
                socket_factory.return_value.__enter__.return_value.bind.side_effect=OSError('not a local address')
                with self.assertRaisesRegex(CollectorError,'not available on this server PC'):save_settings(settings,path)
                with self.assertRaisesRegex(CollectorError,'collector PC address'):control(settings,'start')
            postgres.assert_not_called();run.assert_not_called()
            self.assertEqual(path.read_text(),'preserve existing settings')
            self.assertFalse(settings.data_dir.exists())

    def test_invalid_local_listener_can_still_be_loaded_for_repair(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'manager.json'
            settings=ServerSettings(Path(temporary)/'data',mode='network',listen_address='203.0.113.45',server_host='central-pc')
            path.write_text(json.dumps(settings.document()))
            with patch('server.management.settings.socket.socket',side_effect=AssertionError('Loading settings must allow repair')):
                self.assertEqual(load_settings(path),settings)

    @unittest.skipUnless(os.name=='nt','Windows controller')
    def test_stop_works_after_a_saved_listener_disappears(self):
        from server.management.runtime import control
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary)
            (folder/'credentials.dpapi').write_bytes(b'protected-placeholder')
            settings=ServerSettings(folder,mode='network',listen_address='203.0.113.45',server_host='central-pc')
            with patch('server.management.settings.socket.socket',side_effect=AssertionError('Stopping must not probe the listener')),patch('server.management.settings.postgres_major',return_value=18),patch('server.management.runtime.subprocess.run',return_value=Mock(returncode=0)) as run:
                control(settings,'stop')
            run.assert_called_once()

    def test_stopping_a_new_setup_does_not_create_a_folder_that_blocks_initialization(self):
        from server.management.runtime import control
        with tempfile.TemporaryDirectory() as temporary:
            settings=ServerSettings(Path(temporary)/'new-data')
            with patch('server.management.settings.postgres_major',return_value=18),patch('server.management.runtime.subprocess.run') as run:
                control(settings,'stop')
            run.assert_not_called()
            self.assertFalse(settings.data_dir.exists())

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
