from dataclasses import replace
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from collector.desktop import DesktopService,default_config
from collector.errors import CollectorError
from collector.secrets import load_password
from collector.state import State
from shared.setup_bundle import decode_setup,encode_setup,SetupError


def payload():
    return dict(version=1,source_id=str(uuid4()),generation_id=str(uuid4()),source_name='SCADA PC',
                upload_url='https://localhost:8443/v1/uploads',upload_token='t'*43,
                ca_certificate_pem='',local_test_only=True)


class SetupBundleTests(unittest.TestCase):
    def test_authenticated_encryption_roundtrip_and_wrong_password(self):
        document=payload()
        encoded=encode_setup(document,'a long file password')
        self.assertNotIn(document['upload_token'].encode(),encoded)
        self.assertEqual(decode_setup(encoded,'a long file password'),document)
        with self.assertRaises(SetupError):decode_setup(encoded,'a wrong file password')
        envelope=json.loads(encoded)
        envelope['ciphertext']=envelope['ciphertext'][::-1]
        with self.assertRaises(SetupError):decode_setup(json.dumps(envelope).encode(),'a long file password')

    def test_policy_injection_local_remote_and_oversize_rejected(self):
        for changes in (dict(all_history=True),dict(upload_url='http://localhost/'),dict(upload_url='https://remote.example/'),dict(upload_url='https://localhost:0/')):
            with self.subTest(changes=changes),self.assertRaises(SetupError):encode_setup(dict(payload(),**changes),'a long file password')
        with self.assertRaises(SetupError):decode_setup(b'x'*65537,'a long file password')
        with self.assertRaises(SetupError):encode_setup(payload(),'short')


@unittest.skipUnless(os.name=='nt','Windows DPAPI provisioning')
class SetupImportTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.service=DesktopService()
        self.config=self.service.save(replace(default_config(Path(self.folder.name)/'collector/config.toml'),
                                              host='localhost',user='Scada_Collector',all_history=True,
                                              collection_enabled=True,interval_seconds=120,scan_mode='id_range'))
        self.service.store_password(self.config,'local source password only')
        self.document=payload()
        self.file=Path(self.folder.name)/'setup.linker-collector'
        self.file.write_bytes(encode_setup(self.document,'a long file password'))

    def test_import_preserves_source_policy_and_password_and_supports_refresh(self):
        before=self.config.password_path.read_bytes()
        result=self.service.import_setup(self.config,self.file,'a long file password')
        self.assertEqual(result,replace(self.config,source_id=self.document['source_id'],generation_id=self.document['generation_id'],
                                        upload_enabled=True,upload_url=self.document['upload_url']))
        self.assertEqual(result.password_path.read_bytes(),before)
        self.assertEqual(load_password(result.upload_password_path),self.document['upload_token'])
        self.assertEqual(self.service.import_setup(result,self.file,'a long file password'),result)

    def test_wrong_password_and_wrong_identity_preserve_everything(self):
        before=self.config.path.read_bytes()
        with self.assertRaises(CollectorError):self.service.import_setup(self.config,self.file,'wrong file password')
        self.assertEqual(self.config.path.read_bytes(),before)
        self.assertFalse(self.config.upload_password_path.exists())
        result=self.service.import_setup(self.config,self.file,'a long file password')
        old=result.path.read_bytes();old_token=result.upload_password_path.read_bytes()
        self.file.write_bytes(encode_setup(payload(),'a long file password'))
        with self.assertRaises(CollectorError):self.service.import_setup(result,self.file,'a long file password')
        self.assertEqual(result.path.read_bytes(),old)
        self.assertEqual(result.upload_password_path.read_bytes(),old_token)

    def test_import_refuses_scheduler_lock_and_rolls_back_disk_failure(self):
        state=State(self.config)
        try:
            with state.lock(scheduler=True),self.assertRaises(CollectorError):
                self.service.import_setup(self.config,self.file,'a long file password')
        finally:state.close()
        before=self.config.path.read_bytes()
        with patch.object(self.service,'save',side_effect=CollectorError('simulated storage failure')),self.assertRaises(CollectorError):
            self.service.import_setup(self.config,self.file,'a long file password')
        self.assertEqual(self.config.path.read_bytes(),before)
        self.assertFalse(self.config.upload_password_path.exists())

    def test_pending_identity_is_preserved_even_if_config_ids_were_cleared(self):
        from collector.tests.test_delivery import wire
        other=payload()
        state=State(replace(self.config,source_id=other['source_id'],generation_id=other['generation_id']))
        try:
            state.stage([wire()],{'completed':{},'cycle':None})
            before=state.pending()['payload']
            with self.assertRaises(CollectorError):self.service.import_setup(self.config,self.file,'a long file password')
            self.assertEqual(state.pending()['payload'],before)
        finally:state.close()
