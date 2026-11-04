"""VM bundle input, secret and resource boundaries; never start a VM."""
import hashlib
import io
import json
from pathlib import Path
import tempfile
import runpy
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from deploy.vmware.build import cloud_config, download, vmx
from deploy.vmware.verify import inputs
from deploy.vmware.package import FILES, package
from zipfile import ZipFile
from server.management.desktop_identity import runtime_caption


class VMwareBundleTests(unittest.TestCase):
    def test_vm_health_grace_preserves_network_settings_and_custom_healthchecks(self):
        root = Path(__file__).resolve().parents[1]
        fake_setup = SimpleNamespace(Installer=object, SetupError=ValueError)
        with patch.dict('sys.modules', {'linux_setup': fake_setup}), patch('sys.path', sys.path.copy()):
            adjust = runpy.run_path(str(root/'deploy/vmware/install_guest.py'))['vm_health_settings']
        for name in ('docker-compose.wsl.yml.template', 'docker-compose.network.yml.template'):
            original = (root/'deploy/wsl'/name).read_text()
            result = adjust(original)
            self.assertEqual(adjust(result), result)
            self.assertEqual(result.replace('    healthcheck: {timeout: 30s, start_period: 120s}\n', '', 1), original)
        custom = 'services:\n  api:\n    healthcheck: {timeout: 45s}\n  db:\n    image: TEST-ONLY\n'
        self.assertEqual(adjust(custom), custom)
        with self.assertRaises(ValueError):
            adjust('services:\n  unknown: {}\n')

    def test_transfer_archive_excludes_private_credentials_and_initialized_test_disk(self):
        with tempfile.TemporaryDirectory() as folder:
            bundle = Path(folder)/'fixture'
            bundle.mkdir()
            artifacts = {}
            for name in ('Central Server.vmx', 'central-server.vmdk', 'seed.iso'):
                content = ('TEST-ONLY-'+name).encode()
                (bundle/name).write_bytes(content)
                checksum = hashlib.sha256(content).hexdigest()
                artifacts[name] = checksum
                (bundle/(name+'.sha256')).write_text(checksum+'  '+name+'\n')
            (bundle/'build.json').write_text(json.dumps({'artifacts': artifacts}))
            (bundle/'Read me.md').write_text('TEST-ONLY guide')
            for name in ('id_ed25519', 'login.txt', 'validation.qcow2', 'validation-provision-error.log'):
                (bundle/name).write_text('TEST-ONLY private state')
            archive = package(bundle)
            with ZipFile(archive) as check:
                self.assertEqual(set(check.namelist()), set(FILES))
            with self.assertRaises(FileExistsError):
                package(bundle)
            (bundle/'seed.iso').write_bytes(b'altered')
            with self.assertRaisesRegex(ValueError, 'integrity'):
                package(bundle)

    def test_validation_refuses_a_private_key_inside_a_distributable_bundle(self):
        with tempfile.TemporaryDirectory() as folder:
            key = Path(folder)/'id_ed25519'
            key.write_text('TEST-ONLY-private-placeholder')
            with self.assertRaisesRegex(ValueError, 'outside'):
                inputs(folder,key)

    def test_manager_caption_distinguishes_native_linux_from_wsl(self):
        with patch.dict('os.environ', {'WSL_DISTRO_NAME': ''}):
            self.assertEqual(runtime_caption(), 'Linux / Docker')
        with patch.dict('os.environ', {'WSL_DISTRO_NAME': 'Ubuntu'}):
            self.assertEqual(runtime_caption(), 'WSL / Docker')

    def test_configuration_uses_a_desktop_guest_and_isolates_networking(self):
        result = vmx()
        settings = dict(line.split(' = ', 1) for line in result.splitlines())
        # VMXNET3 requires PCIe capacity; legacy slots cannot host this NIC.
        root_ports = [key[:-11] for key, value in settings.items()
                      if key.endswith('.virtualDev') and value == '"pcieRootPort"']
        self.assertTrue(root_ports, 'The network adapter needs a PCIe root port.')
        self.assertTrue(any(settings.get(port+'.present') == '"TRUE"'
                            and int(settings[port+'.functions'].strip('"')) > 0 for port in root_ports))
        self.assertNotIn('ethernet0.pciSlotNumber', settings)
        self.assertIn('firmware = "efi"', result)
        self.assertIn('memsize = "8192"', result)
        self.assertIn('ethernet0.connectionType = "nat"', result)
        self.assertIn('scsi0:0.fileName = "central-server.vmdk"', result)
        self.assertNotIn('sharedFolder', result)
        for memory, cpus in ((512, 4), (65536, 4), (8192, 0), (8192, 32)):
            with self.assertRaises(ValueError):
                vmx(memory, cpus)

    def test_first_boot_has_unique_identity_no_shared_password_and_ssh_key_auth(self):
        value = cloud_config('build-fixture', 'ssh-ed25519 TEST-ONLY-public-key', '$6$TEST-ONLY-hash')
        data = json.loads(value.split('\n', 1)[1])
        self.assertFalse(data['ssh_pwauth'])
        self.assertTrue(data['disable_root'])
        self.assertEqual(data['users'][0]['name'], 'linker')
        self.assertEqual(data['users'][0]['hashed_passwd'], '$6$TEST-ONLY-hash')
        self.assertNotIn('plain_text_passwd', value)
        self.assertNotIn('autologin', value)
        self.assertIn('component', data['write_files'][0]['content'])

    def test_download_hash_failure_never_publishes_a_boot_disk(self):
        with tempfile.TemporaryDirectory() as folder, patch('urllib.request.urlopen', return_value=io.BytesIO(b'changed image')):
            target = Path(folder)/'disk.img'
            with self.assertRaisesRegex(RuntimeError, 'SHA-256'):
                download('https://example.invalid/disk', '0'*64, target)
            self.assertFalse(target.exists())

    def test_download_verifies_cached_bytes_before_reuse(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)/'disk.img'
            target.write_bytes(b'verified image')
            with patch('urllib.request.urlopen') as request:
                self.assertEqual(download('https://example.invalid/disk', hashlib.sha256(target.read_bytes()).hexdigest(), target), target)
            request.assert_not_called()
