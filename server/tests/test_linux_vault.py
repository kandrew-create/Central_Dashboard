import os
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from collector.errors import CollectorError
from server.management.linux_vault import LinuxVault, private_directory


@unittest.skipUnless(os.name == 'posix', 'Linux ownership and permissions')
class LinuxVaultTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.folder = Path(self.directory.name) / 'secrets'
        self.vault = LinuxVault(self.folder)
        self.path = self.folder / (str(uuid4()) + '.vault')

    def test_encrypts_credential_with_private_key_and_rejects_swapped_ciphertext(self):
        self.vault.save(self.path, {'upload_token': 'private-test-token'})
        self.assertNotIn(b'private-test-token', self.path.read_bytes())
        self.assertEqual(self.vault.load(self.path)['upload_token'], 'private-test-token')
        self.assertEqual(self.folder.stat().st_mode & 0o777, 0o700)
        for path in (self.path, self.folder / 'vault.key'):
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        other = self.folder / (str(uuid4()) + '.vault')
        other.write_bytes(self.path.read_bytes())
        other.chmod(0o600)
        with self.assertRaises(CollectorError):
            self.vault.load(other)

    def test_missing_key_never_reinitializes_existing_credentials(self):
        self.vault.save(self.path, {'upload_token': 'private-test-token'})
        before = self.path.read_bytes()
        (self.folder / 'vault.key').unlink()
        with self.assertRaisesRegex(CollectorError, 'key is missing'):
            self.vault.save(self.path, {'upload_token': 'replacement'})
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse((self.folder / 'vault.key').exists())

    def test_rejects_shared_key_permissions_tampering_and_symlink_directory(self):
        self.vault.save(self.path, {'upload_token': 'private-test-token'})
        key = self.folder / 'vault.key'
        key.chmod(0o644)
        with self.assertRaises(CollectorError):
            self.vault.load(self.path)
        key.chmod(0o600)
        content = self.path.read_bytes()
        self.path.write_bytes(content[:-1] + bytes([content[-1] ^ 1]))
        with self.assertRaises(CollectorError):
            self.vault.load(self.path)
        linked = self.folder.parent / 'linked'
        linked.symlink_to(self.folder, target_is_directory=True)
        with self.assertRaises(CollectorError):
            private_directory(linked)
