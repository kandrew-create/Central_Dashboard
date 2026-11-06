from pathlib import Path
from dataclasses import replace
import tempfile
import threading
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
    def test_identity_references_are_read_only_and_save_preserves_full_ids(self):
        for name in ('source_id', 'generation_id'):
            self.assertEqual(self.app.identity_references[name].get(), 'Not configured')
            self.assertEqual(self.app.fields[name][1].winfo_class(), 'TLabel')
        assigned = replace(self.config, source_id='11111111-1111-4111-8111-11111111a3f9',
                           generation_id='22222222-2222-4222-8222-22222222c812')
        self.app._settings_loaded(assigned)
        self.app._refresh_actions()
        self.assertEqual(self.app.identity_references['source_id'].get(), '…a3f9')
        self.assertEqual(self.app.identity_references['generation_id'].get(), '…c812')
        self.app.variables['database'].set('edited_scada')
        self.service.save.return_value = replace(assigned, database='edited_scada')
        self.app.save_settings()
        self.wait_idle()
        candidate, previous = self.service.save.call_args.args
        self.assertEqual(previous, assigned)
        self.assertEqual(candidate.source_id, assigned.source_id)
        self.assertEqual(candidate.generation_id, assigned.generation_id)
        self.assertEqual(self.app.variables['source_id'].get(), assigned.source_id)
        self.assertEqual(self.app.variables['generation_id'].get(), assigned.generation_id)
        self.assertEqual(self.app.identity_references['source_id'].get(), '…a3f9')
        self.assertEqual(self.app.identity_references['generation_id'].get(), '…c812')

    def test_schedule_hides_interval_and_retains_its_value(self):
        self.app.variables['interval_seconds'].set('180')
        for mode in ('daily', 'weekly'):
            self.app.variables['schedule_mode'].set(mode)
            for widget in self.app.fields['interval_seconds']:
                self.assertFalse(widget.grid_info())
            self.assertEqual(self.app.variables['interval_seconds'].get(), '180')
        self.app.variables['schedule_mode'].set('interval')
        self.assertTrue(all(widget.grid_info() for widget in self.app.fields['interval_seconds']))
        self.assertFalse(any(widget.grid_info() for widget in self.app.fields['schedule_time']))
        self.app.variables['schedule_mode'].set('weekly')
        self.assertTrue(all(widget.grid_info() for widget in self.app.fields['schedule_weekday']))

    def test_url_has_no_visible_editor_and_test_server_does_not_echo_it(self):
        self.assertNotIn('upload_url', self.app.fields)
        self.app.saved = self.app.base = replace(self.config, upload_url='https://private-central.example/v1/uploads')
        self.app._populate(self.app.saved)
        self.service.check_upload.return_value = dict(upload_url=self.app.saved.upload_url)
        self.app.test_server()
        self.wait_idle()
        self.assertNotIn(self.app.saved.upload_url, self.app.collection_status.get())
        self.assertNotIn(self.app.saved.upload_url, self.app.status.get())
        self.assertEqual(self.app.variables['upload_url'].get(), self.app.saved.upload_url)
        self.assertEqual(self.app.upload_token.get(), '')

    def test_app_startup_runs_off_tk_thread_without_native_collection(self):
        self.app._destroy()
        self.root = tk.Tk()
        self.root.withdraw()
        calls = []
        gui_thread = threading.get_ident()
        self.service.startup.side_effect = lambda path: calls.append(threading.get_ident()) or dict(
            config=self.config, status=dict(running=False, engine_ready=True), message='Setup retained')
        from collector.docker_gui import DockerCollectorWindow
        with patch('collector.runtime.run') as native:
            self.app = DockerCollectorWindow(self.root, self.config.path, self.service, auto_start=True)
            self.root.update()
            self.wait_idle()
        self.service.startup.assert_called_once()
        self.assertNotEqual(calls[0], gui_thread)
        native.assert_not_called()
        self.assertIsNone(self.app.auto_thread)

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
        button_labels = [widget.cget('text') for widget, _ in self.app.controls
                         if widget.winfo_class() == 'TButton']
        self.assertNotIn('Reload Docker settings', button_labels)
        self.assertIn('Refresh status', button_labels)
        self.assertEqual(len(self.app.notebook.tabs()), 3)
        self.app.saved = self.app.base = replace(self.config, collection_enabled=True, all_history=True)
        self.app._populate(self.app.saved)
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

    def test_import_accepts_unsaved_fields_supplied_by_server_setup(self):
        self.app.variables['upload_enabled'].set('True')
        self.app.variables['upload_url'].set('')
        self.app.variables['source_id'].set('unsaved-source')
        self.app.variables['generation_id'].set('unsaved-generation')
        self.app.variables['upload_ca_file'].set('unsaved-ca.pem')
        self.assertFalse(self.app.import_button.instate(('disabled',)))
        self.service.import_setup.return_value = self.config
        with patch('collector.gui.filedialog.askopenfilename', return_value='selected.linker-collector'), patch(
                'collector.gui.simpledialog.askstring', return_value='TEST-ONLY-unlock'):
            self.app.import_button.invoke()
            self.wait_idle()
        self.service.import_setup.assert_called_once_with(self.config, 'selected.linker-collector', 'TEST-ONLY-unlock')

    def test_import_reports_unsaved_local_settings_and_never_discards_them(self):
        self.app.variables['host'].set('edited-source.example')
        with patch('collector.gui.messagebox.showinfo') as info, patch('collector.gui.filedialog.askopenfilename') as choose:
            self.app.import_button.invoke()
        info.assert_called_once()
        choose.assert_not_called()
        self.service.import_setup.assert_not_called()
        self.assertEqual(self.app.variables['host'].get(), 'edited-source.example')

    def test_import_is_blocked_while_docker_scheduler_is_running(self):
        self.app.docker_running = True
        with patch('collector.gui.filedialog.askopenfilename', return_value='') as choose:
            self.app.import_server_setup()
        choose.assert_not_called()
        self.service.import_setup.assert_not_called()

    def test_start_requires_saved_enabled_collection(self):
        self.assertTrue(self.app.auto_button.instate(('disabled',)))
        self.app.docker_action('start')
        self.service.start.assert_not_called()
        self.app.saved = self.app.base = replace(self.config, collection_enabled=True, all_history=True)
        self.app._populate(self.app.saved)
        self.app._refresh_actions()
        self.assertFalse(self.app.auto_button.instate(('disabled',)))
        self.app.variables['host'].set('edited-source.example')
        self.assertTrue(self.app.auto_button.instate(('disabled',)))
        self.app.docker_action('start')
        self.service.start.assert_not_called()

    def test_manual_stop_signals_cancellation_and_disables_repeat_stop(self):
        started, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        def collect(_config, stop):
            started.set()
            release.wait(2)
            return dict(running=False, engine_ready=True, pending_batches=1)
        self.service.cycle.side_effect = collect
        self.app.collect_now()
        self.assertTrue(started.wait(1))
        self.app.stop_auto()
        self.assertTrue(self.app.cycle_stop.is_set())
        self.assertTrue(self.app.stop_button.instate(('disabled',)))
        self.service.stop.assert_not_called()
        release.set()
        self.wait_idle()
