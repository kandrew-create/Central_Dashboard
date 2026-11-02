from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
try:
    import tkinter as tk
except ImportError:
    tk = None

from collector.desktop import default_config
from deploy.collector.desktop import DockerDesktopService


@unittest.skipIf(tk is None, 'Tk is not installed')
class DockerManagerWindowTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError:
            self.skipTest('desktop display unavailable')
        self.root.withdraw()
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.config = default_config(Path(self.folder.name) / 'config.toml')
        self.service = Mock(spec=DockerDesktopService)
        self.service.docker_managed = True
        self.service.load.return_value = self.config
        self.service.credential_present.return_value = True
        self.service.status.return_value = dict(running=False, engine_ready=True)
        self.service.start.return_value = dict(running=True, engine_ready=True)
        self.service.stop.return_value = dict(running=False, engine_ready=True)
        from collector.docker_gui import DockerCollectorWindow
        self.app = DockerCollectorWindow(self.root, self.config.path, self.service)
        self.wait_idle()
        self.addCleanup(self.cleanup)

    def cleanup(self):
        if not self.app.closed:
            self.app._destroy()

    def wait_idle(self):
        deadline = time.monotonic() + 3
        while self.app.busy and time.monotonic() < deadline:
            self.root.update()
            time.sleep(.01)
        self.assertFalse(self.app.busy)

    def test_start_uses_docker_service_and_never_starts_native_scheduler(self):
        with patch('collector.runtime.run') as native:
            self.app.start_auto()
            self.wait_idle()
        self.service.start.assert_called_once()
        native.assert_not_called()
        self.assertIsNone(self.app.auto_thread)
        self.assertTrue(self.app.docker_running)

    def test_close_running_manager_leaves_docker_running(self):
        self.app.docker_running = True
        self.app.close()
        self.service.stop.assert_not_called()
        self.assertTrue(self.app.closed)

    def test_stop_is_a_scoped_docker_service_action(self):
        self.app.docker_running = True
        self.app.stop_auto()
        self.wait_idle()
        self.service.stop.assert_called_once()
        self.assertFalse(self.app.docker_running)

    def test_linux_credential_status_does_not_require_native_dpapi_files(self):
        self.assertFalse(self.config.password_path.exists())
        self.assertFalse(self.app.preview_button.instate(('disabled',)))
        self.assertIn('Docker:', self.app.location.get())
