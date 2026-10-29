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

from collector.desktop import DesktopService, default_config, serialize_config
from collector.profiles.ecostruxure import COLUMNS
from collector.records import preview_record


@unittest.skipIf(tk is None, "Tk is not installed")
class DesktopWindowTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError:
            self.skipTest("desktop display unavailable")
        self.root.withdraw()
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "setup" / "config.toml"
        self.path.parent.mkdir()
        self.config = default_config(self.path)
        self.service = Mock(spec=DesktopService)
        self.service.load.return_value = self.config
        self.service.save.return_value = self.config
        self.service.check.return_value = {"status": "connected", "read_only": True}
        self.service.preview.return_value = [self.record()]
        self.addCleanup(self.destroy)

    def destroy(self):
        try:
            if hasattr(self, "app"):
                self.root.after_cancel(self.app.poll_id)
            self.root.destroy()
        except tk.TclError:
            pass

    def record(self):
        row = {name: None for name in COLUMNS["alarmhistory"]}
        row.update(id=1, al_message="Sample alarm", al_tag="DEMO", al_tag_value="001.20", al_user="private")
        return preview_record("alarmhistory", row, "")

    def create(self, saved=True):
        from collector.gui import CollectorWindow
        if saved:
            self.path.write_text(serialize_config(self.config), encoding="utf-8")
            self.config.password_path.parent.mkdir()
            self.config.password_path.write_bytes(b"test-only-marker-not-a-real-secret")
        self.app = CollectorWindow(self.root, self.path, service=self.service)
        self.wait_idle()
        return self.app

    def wait_idle(self, timeout=5):
        deadline = time.monotonic() + timeout
        while self.app.busy and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.root.update()
        self.assertFalse(self.app.busy, "desktop operation did not complete")

    def test_new_setup_cannot_test_or_preview_before_it_is_saved(self):
        app = self.create(saved=False)
        self.assertTrue(app.test_button.instate(("disabled",)))
        self.assertTrue(app.password_entry.instate(("disabled",)))
        self.assertTrue(app.preview_button.instate(("disabled",)))
        app.test_connection()
        self.service.check.assert_not_called()

    def test_connection_and_preview_run_on_a_worker_thread(self):
        app = self.create()
        started, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        caller_thread = threading.get_ident()
        worker_threads = []

        def delayed_check(_config):
            worker_threads.append(threading.get_ident())
            started.set()
            release.wait(2)
            return {"status": "connected", "read_only": True}

        self.service.check.side_effect = delayed_check
        app.test_connection()
        self.assertTrue(started.wait(1))
        self.assertTrue(app.busy)
        self.assertTrue(app.test_button.instate(("disabled",)))
        self.root.update()  # The UI remains responsive while the source call is blocked.
        release.set()
        self.wait_idle()
        self.assertNotEqual(worker_threads[0], caller_thread)
        self.assertTrue(app.connected)
        app.load_preview()
        self.wait_idle()
        self.assertEqual(len(app.tree.get_children()), 1)
        self.assertEqual(app.tree.item("0", "values")[4], "001.20")
        self.service.preview.assert_called_once_with(self.config, "alarmhistory", 20, None, False)

    def test_connection_edits_clear_records_and_require_another_test(self):
        app = self.create()
        app.connected = True
        app.records = [self.record()]
        app.tree.insert("", "end", iid="0", values=(1,))
        app.variables["host"].set("127.0.0.1")
        self.assertFalse(app.connected)
        self.assertEqual(app.tree.get_children(), ())
        self.assertTrue(app.test_button.instate(("disabled",)))

    def test_privacy_changes_remove_existing_previews_and_open_details(self):
        app = self.create()
        app.records = [self.record()]
        app.tree.insert("", "end", iid="0", values=(1,))
        app.tree.selection_set("0")
        app.view_details()
        details = app.detail_windows[0]
        app.include_users.set(True)
        self.assertEqual(app.tree.get_children(), ())
        self.assertEqual(details.winfo_exists(), 0)

    def test_password_is_cleared_from_the_form_before_background_storage(self):
        app = self.create()
        app.password.set("TEST-ONLY-password")
        app.store_password()
        self.assertEqual(app.password.get(), "")
        self.wait_idle()
        self.service.store_password.assert_called_once_with(self.config, "TEST-ONLY-password")
        self.assertNotIn("TEST-ONLY-password", app.status.get())
        self.assertFalse(app.connected)

    def test_typed_password_cannot_silently_test_an_older_saved_password(self):
        app = self.create()
        app.connected = True
        app.password.set("TEST-ONLY-new-password")
        self.assertFalse(app.connected)
        self.assertTrue(app.test_button.instate(("disabled",)))
        self.assertIn("Store password", app.password_status.get())
        app.test_connection()
        self.service.check.assert_not_called()
        app.store_password()
        self.wait_idle()
        self.assertFalse(app.test_button.instate(("disabled",)))
        self.service.store_password.assert_called_once_with(self.config, "TEST-ONLY-new-password")

    def test_unexpected_database_error_is_redacted(self):
        app = self.create()
        self.service.check.side_effect = RuntimeError("password=TEST-ONLY-do-not-display")
        with patch("collector.gui.messagebox.showerror") as error:
            app.test_connection()
            self.wait_idle()
        self.assertFalse(app.connected)
        self.assertNotIn("TEST-ONLY", app.status.get())
        self.assertNotIn("TEST-ONLY", str(error.call_args))

    def test_invalid_settings_do_not_start_a_save(self):
        app = self.create()
        app.variables["port"].set("invalid")
        with patch("collector.gui.messagebox.showerror"):
            app.save_settings()
        self.service.save.assert_not_called()

    def test_closing_waits_for_an_in_progress_operation(self):
        app = self.create()
        app.busy = True
        app.close()
        self.assertTrue(app.closing)
        self.assertTrue(self.root.winfo_exists())
        app.busy = False
        app.closing = False

    def test_collection_controls_use_background_cycle_and_clear_upload_credential(self):
        self.config=replace(self.config,collection_enabled=True)
        self.service.load.return_value=self.config
        self.service.cycle.return_value={'pending_batches':0,'pending_bytes':0,'last_successful_upload':'test success'}
        app=self.create()
        self.assertFalse(app.collect_button.instate(('disabled',)))
        app.collect_now()
        self.wait_idle()
        self.service.cycle.assert_called_once_with(self.config)
        self.assertIn('test success',app.collection_status.get())
        self.assertEqual(app.status.get(),'Collection status updated.')
        app.upload_token.set('TEST_ONLY_UPLOAD_CREDENTIAL')
        app.store_upload_token()
        self.assertEqual(app.upload_token.get(),'')
        self.wait_idle()
        self.service.store_upload_token.assert_called_once_with(self.config,'TEST_ONLY_UPLOAD_CREDENTIAL')
        self.assertEqual(app.status.get(),'Upload credential protected for this Windows account.')

    def test_import_server_setup_updates_saved_identity_and_clears_credential_fields(self):
        app=self.create()
        updated=replace(self.config,source_id='00000000-0000-0000-0000-000000000001',
                        generation_id='00000000-0000-0000-0000-000000000002',
                        upload_enabled=True,upload_url='https://localhost:8443/v1/uploads')
        self.service.import_setup.return_value=updated
        with patch('collector.gui.filedialog.askopenfilename',return_value='setup.linker-collector'),patch('collector.gui.simpledialog.askstring',return_value='file password only'):
            app.import_server_setup();self.wait_idle()
        self.service.import_setup.assert_called_once_with(self.config,'setup.linker-collector','file password only')
        self.assertEqual(app.saved,updated)
        self.assertEqual(app.variables['source_id'].get(),updated.source_id)
        self.assertEqual(app.password.get(),'');self.assertEqual(app.upload_token.get(),'')
        self.assertFalse(app.connected)

    def test_pending_upload_fields_do_not_block_setup_import(self):
        app=self.create()
        app.variables['upload_enabled'].set('True')
        self.assertFalse(app.import_button.instate(('disabled',)))
        updated=replace(self.config,source_id='00000000-0000-0000-0000-000000000001',
                        generation_id='00000000-0000-0000-0000-000000000002',
                        upload_enabled=True,upload_url='https://central-pc:8443/v1/uploads')
        self.service.import_setup.return_value=updated
        with patch('collector.gui.filedialog.askopenfilename',return_value='setup.linker-collector'),patch('collector.gui.simpledialog.askstring',return_value='test setup password'):
            app.import_server_setup();self.wait_idle()
        self.service.import_setup.assert_called_once_with(self.config,'setup.linker-collector','test setup password')
        self.service.save.assert_not_called()
        self.assertEqual(app.saved,updated)

    def test_new_setup_explains_required_save_instead_of_disabling_import(self):
        app=self.create(saved=False)
        self.assertFalse(app.import_button.instate(('disabled',)))
        with patch('collector.gui.messagebox.showinfo') as info,patch('collector.gui.filedialog.askopenfilename') as choose:
            app.import_server_setup()
        info.assert_called_once();choose.assert_not_called()
        self.service.import_setup.assert_not_called()
        self.assertIn('First save the local database settings',app.status.get())

    def test_unsaved_local_edits_and_database_password_are_preserved_on_import(self):
        app=self.create()
        app.variables['host'].set('127.0.0.1')
        with patch('collector.gui.messagebox.showinfo') as info,patch('collector.gui.filedialog.askopenfilename') as choose:
            app.import_server_setup()
        info.assert_called_once();choose.assert_not_called()
        self.service.import_setup.assert_not_called()
        self.assertEqual(app.variables['host'].get(),'127.0.0.1')
        app.variables['host'].set(self.config.host)
        app.password.set('TEST-ONLY-unsaved-database-password')
        with patch('collector.gui.messagebox.showinfo') as info:
            app.import_server_setup()
        info.assert_called_once()
        self.assertIn('Store the entered database password',app.status.get())
        self.assertEqual(app.password.get(),'TEST-ONLY-unsaved-database-password')

    def test_import_remains_blocked_during_automatic_collection(self):
        app=self.create()
        app.auto_thread=Mock();app.auto_thread.is_alive.return_value=True
        app._refresh_actions()
        self.assertTrue(app.import_button.instate(('disabled',)))
        with patch('collector.gui.filedialog.askopenfilename') as choose:app.import_server_setup()
        choose.assert_not_called();self.service.import_setup.assert_not_called()
        self.assertIn('Stop automatic collection',app.setup_import_status.get())

    def test_protected_upload_credential_has_a_visible_status_without_showing_the_secret(self):
        app=self.create()
        self.assertIn('No protected upload credential',app.upload_credential_status.get())
        self.config.upload_password_path.parent.mkdir(exist_ok=True)
        self.config.upload_password_path.write_bytes(b'test-only-protected-marker')
        app._refresh_actions()
        self.assertEqual(app.upload_token.get(),'')
        self.assertIn('Protected upload credential found',app.upload_credential_status.get())
        app.upload_token.set('TEST-ONLY-pending-credential')
        self.assertIn('not stored',app.upload_credential_status.get())
        self.assertNotIn('TEST-ONLY',app.upload_credential_status.get())

    def test_server_connection_test_runs_in_background_without_collecting(self):
        self.config=replace(self.config,upload_url='https://central-pc:8443/v1/uploads')
        self.service.load.return_value=self.config
        self.service.check_upload.return_value={'status':'ready','upload_url':self.config.upload_url}
        app=self.create();app.test_server();self.wait_idle()
        self.service.check_upload.assert_called_once_with(self.config)
        self.service.cycle.assert_not_called()
        self.assertIn('no records were uploaded',app.collection_status.get())
        self.assertEqual(app.status.get(),app.collection_status.get())
