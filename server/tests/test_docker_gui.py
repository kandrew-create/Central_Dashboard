from pathlib import Path
import tempfile
import time
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import Mock, patch

from server.management.docker import DockerManagerService, DockerSettings
from server.management.docker_gui import DockerManagerWindow


class DockerWindowTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest('desktop display unavailable: ' + str(error))
        self.root.withdraw()
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.service = Mock(spec=DockerManagerService)
        self.service.settings = DockerSettings(Path(self.directory.name))
        self.service.export_directory = Path(self.directory.name)
        self.service.status.return_value = dict(api_ready=True, database_ready=True, worker_running=True,
                                               sources=0, batches=0, revisions=0, quarantined_batches=0,
                                               failed_jobs=0, upload_url='https://localhost/v1/uploads', error=None)
        self.service.catalog.return_value = {key: [] for key in ('customers', 'sites', 'projects', 'machines')}
        self.service.sources.return_value = []
        self.service.machine_interpretations.return_value = dict(configuration=dict(enabled=False, model='Not configured in Docker'),
                                                               rows=[], records_available=True)
        self.app = DockerManagerWindow(self.root, self.service)
        self.addCleanup(self.destroy)
        self.wait_idle()

    def destroy(self):
        self.root.after_cancel(self.app.poll_id)
        self.root.destroy()

    def wait_idle(self):
        deadline = time.monotonic() + 5
        while self.app.busy and time.monotonic() < deadline:
            self.root.update()
            time.sleep(.01)
        self.assertFalse(self.app.busy)

    def test_native_window_identifies_docker_and_has_no_windows_settings_or_ai_enable(self):
        self.assertIn('WSL / Docker', self.root.title())
        self.assertEqual(self.app.notebook.tab(3, 'text'), '4  Docker deployment')
        self.assertEqual(self.app.start_button['text'], 'Start Docker server')
        def texts(widget):
            result = []
            if isinstance(widget, (ttk.Label, ttk.Button)):
                result.append(str(widget.cget('text')))
            for child in widget.winfo_children():
                result.extend(texts(child))
            return result
        labels = texts(self.root)
        self.assertNotIn('Enable local AI', labels)
        self.assertNotIn('Save server settings', labels)
        self.assertNotIn('PostgreSQL 17 or 18 bin folder', labels)
        self.assertIn('Refresh saved results', labels)

    def test_start_and_confirmed_stop_delegate_without_changing_backend(self):
        self.app.start_button.invoke()
        self.wait_idle()
        self.service.start.assert_called_once_with()
        with patch('server.management.gui.messagebox.askyesno', return_value=True):
            self.app.stop_server()
        self.wait_idle()
        self.service.stop.assert_called_once_with()
        self.assertIs(self.app.service, self.service)

    def test_footer_stays_visible_at_minimum_size_and_progress_finishes(self):
        self.root.deiconify()
        self.root.geometry('1080x750')
        for tab in range(5):
            self.app.notebook.select(tab)
            self.root.update()
            self.wait_idle()
            self.assertTrue(self.app.footer.winfo_ismapped())
            self.assertLessEqual(self.app.footer.winfo_y() + self.app.footer.winfo_height(), self.root.winfo_height())
        self.assertEqual(str(self.app.progress['mode']), 'determinate')
        self.assertNotIn('enable_machine_ai', [call[0] for call in self.service.method_calls])
