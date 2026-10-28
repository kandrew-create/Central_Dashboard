import os
from pathlib import Path
import tempfile
import unittest

from collector import secrets
from collector.errors import CollectorError


@unittest.skipUnless(os.name == "nt", "requires real Windows DPAPI and NTFS ACLs")
class WindowsSecretTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "collector" / "config.toml"

    def test_private_setup_refuses_to_reuse_an_existing_directory(self):
        secrets.initialize(self.path, "version = 1\n")
        with self.assertRaises(CollectorError):
            secrets.initialize(self.path, "replacement")
        self.assertEqual(self.path.read_text(encoding="utf-8"), "version = 1\n")

    def test_real_dpapi_roundtrip_and_rotation_never_store_plaintext(self):
        secrets.initialize(self.path, "version = 1\n")
        secret_path = self.path.parent / "secrets/database-password.dpapi"
        password = "TEST-ONLY-collector-secret-\u00e9"
        secrets.save_password(secret_path, password)
        self.assertNotIn(password.encode("utf-8"), secret_path.read_bytes())
        self.assertEqual(secrets.load_password(secret_path), password)
        secrets.save_password(secret_path, "TEST-ONLY-replacement")
        self.assertEqual(secrets.load_password(secret_path), "TEST-ONLY-replacement")
        self.assertEqual(list(secret_path.parent.glob(".password-*")), [])

    def test_configuration_and_secret_acls_are_protected_and_private(self):
        import win32security
        secrets.initialize(self.path, "version = 1\n")
        secret_path = self.path.parent / "secrets/database-password.dpapi"
        secrets.save_password(secret_path, "TEST-ONLY-password")
        for path in (self.path.parent, self.path, secret_path.parent, secret_path):
            descriptor = win32security.GetNamedSecurityInfo(str(path), win32security.SE_FILE_OBJECT,
                win32security.DACL_SECURITY_INFORMATION)
            acl = descriptor.GetSecurityDescriptorDacl()
            self.assertEqual(acl.GetAceCount(), 2)
            self.assertTrue(descriptor.GetSecurityDescriptorControl()[0] & win32security.SE_DACL_PROTECTED)

    def test_plaintext_or_damaged_password_is_rejected_without_echo(self):
        self.path.parent.mkdir()
        self.path.write_bytes(b"TEST-ONLY-should-not-appear-in-error")
        with self.assertRaises(CollectorError) as result:
            secrets.load_password(self.path)
        self.assertNotIn("should-not-appear", str(result.exception))

    def test_empty_password_is_rejected(self):
        with self.assertRaises(CollectorError):
            secrets.save_password(self.path, "")
