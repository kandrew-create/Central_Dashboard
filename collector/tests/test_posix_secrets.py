import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from collector import secrets
from collector.config import EXAMPLE
from collector.errors import CollectorError


@unittest.skipUnless(os.name == 'posix', 'requires Linux file ownership and permissions')
class PosixSecretTests(unittest.TestCase):
    def setUp(self):
        from collector.posix_secrets import create_key
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.key = self.root / 'collector.key'
        create_key(self.key)
        env = patch.dict(os.environ, COLLECTOR_SECRET_KEY_FILE=str(self.key))
        env.start()
        self.addCleanup(env.stop)
        self.config = self.root / 'setup/config.toml'
        secrets.initialize(self.config, EXAMPLE)
        self.secret = self.config.parent / 'secrets/database-password.fernet'

    def test_encrypted_roundtrip_rotation_and_private_modes(self):
        for value in ('test-only-password-é', 'test-only-replacement'):
            secrets.save_password(self.secret, value)
            self.assertNotIn(value.encode(), self.secret.read_bytes())
            self.assertEqual(secrets.load_password(self.secret), value)
        for path in (self.key, self.config, self.secret):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.secret.parent.stat().st_mode), 0o700)

    def test_missing_wrong_and_insecure_keys_never_replace_existing_secret(self):
        from collector.posix_secrets import create_key
        secrets.save_password(self.secret, 'test-only-original')
        before = self.secret.read_bytes()
        other = self.root / 'other.key'
        create_key(other)
        for key in (other, self.root / 'missing.key'):
            with patch.dict(os.environ, COLLECTOR_SECRET_KEY_FILE=str(key)), self.assertRaises(CollectorError):
                secrets.load_password(self.secret)
        self.key.chmod(0o644)
        with self.assertRaises(CollectorError):
            secrets.save_password(self.secret, 'test-only-replacement')
        self.assertEqual(self.secret.read_bytes(), before)
        with self.assertRaises(FileExistsError):
            create_key(self.key)

    def test_tampering_plaintext_and_symbolic_links_are_rejected(self):
        secrets.save_password(self.secret, 'test-only-password')
        for content in (b'test-only-plaintext', b'invalid-encrypted-data'):
            self.secret.write_bytes(content)
            with self.assertRaises(CollectorError):
                secrets.load_password(self.secret)
        target = self.root / 'untouched'
        target.write_bytes(b'original')
        self.secret.unlink()
        self.secret.symlink_to(target)
        with self.assertRaises(CollectorError):
            secrets.save_password(self.secret, 'test-only-password')
        self.assertEqual(target.read_bytes(), b'original')

    def test_initialization_preserves_existing_configuration(self):
        before = self.config.read_bytes()
        with self.assertRaises(CollectorError):
            secrets.initialize(self.config, 'replacement')
        self.assertEqual(self.config.read_bytes(), before)
