from pathlib import Path
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import Mock,patch
from uuid import uuid4
from collector.errors import CollectorError
import io
import os

from server.management.gui import ManagerWindow,NEW
from server.management.service import ManagerService
from server.management.settings import ServerSettings


class ManagementRuntimeTests(unittest.TestCase):
    def test_component_start_does_not_create_a_demo_source_by_default(self):
        from server.management.entry import _main
        with patch.dict(os.environ):
            os.environ.pop('LINKER_SERVER_CREATE_DEMO_SOURCE',None)
            with patch('deploy.local_server.main') as control:
                self.assertEqual(_main(['--component','start']),0)
                self.assertEqual(os.environ['LINKER_SERVER_CREATE_DEMO_SOURCE'],'0')
        control.assert_called_once_with(['start'])

    @unittest.skipUnless(os.name=='nt','Windows process identity')
    def test_stale_process_metadata_is_harmless_on_repeated_stop(self):
        from deploy.local_server import stop_process
        stop_process(dict(pid=0,created='already stopped'))

    def test_stop_allows_bootloader_cleanup_after_child_exits(self):
        from deploy.local_server import stop_process
        root=Mock();child=Mock()
        root.children.return_value=[child]
        with patch('deploy.local_server.process_identity',return_value='owned'),patch('psutil.Process',return_value=root),patch('psutil.wait_procs',return_value=([child],[])):
            stop_process(dict(pid=123,created='owned'))
        child.terminate.assert_called_once_with()
        root.terminate.assert_not_called()
        root.wait.assert_called_once_with(timeout=15)

    def test_component_failure_returns_exit_code_without_secret_or_native_error_dialog(self):
        from server.management.entry import main
        output=io.StringIO()
        with patch('server.management.entry._main',side_effect=ValueError('password=private')),patch('sys.stderr',output):
            self.assertEqual(main(['--component','start']),1)
        self.assertNotIn('private',output.getvalue())
        self.assertIn('ValueError',output.getvalue())


class ManagerWindowTests(unittest.TestCase):
    def setUp(self):
        try:self.root=tk.Tk()
        except tk.TclError:self.skipTest('desktop display unavailable')
        self.root.withdraw()
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.service=Mock(spec=ManagerService)
        self.service.settings=ServerSettings(Path(self.folder.name))
        self.status=dict(api_ready=True,database_ready=True,worker_running=True,sources=0,batches=0,revisions=0,
                         quarantined_batches=0,failed_jobs=0,upload_url='https://localhost:8443/v1/uploads',error=None)
        self.service.status.return_value=self.status
        self.service.start.return_value=self.status
        self.service.catalog.return_value={k:[] for k in ('customers','sites','projects','machines')}
        self.service.sources.return_value=[]
        self.app=ManagerWindow(self.root,self.service)
        self.addCleanup(self.destroy)
        self.wait_idle()

    def destroy(self):
        self.root.after_cancel(self.app.poll_id)
        self.root.destroy()

    def wait_idle(self):
        deadline=time.monotonic()+5
        while self.app.busy and time.monotonic()<deadline:
            self.root.update();time.sleep(.01)
        self.assertFalse(self.app.busy)

    def test_start_and_stop_run_and_refresh_registry(self):
        self.app.start_button.invoke();self.wait_idle()
        self.service.start.assert_called_once_with()
        with patch('server.management.gui.messagebox.askyesno',return_value=True):self.app.stop_server()
        self.wait_idle();self.service.stop.assert_called_once_with()
        self.assertIn('Ready',self.app.health_text.get())

    def select_source(self):
        row=dict(source_id=uuid4(),name='Network SCADA PC',customer_name='Customer',site_name='Site',project_name='Project',
                 generation_id=uuid4(),last_received=None,quarantined_batches=0)
        self.service.sources.return_value=[row]
        self.app.refresh();self.wait_idle()
        self.app.tree.selection_set(str(row['source_id']));self.app.selected()
        return row

    def test_delete_requires_selection_and_confirmation_and_respects_busy_state(self):
        with patch('server.management.gui.messagebox.showinfo') as info:self.app.delete_button.invoke()
        info.assert_called_once();self.service.delete_source.assert_not_called()
        row=self.select_source()
        with patch('server.management.gui.messagebox.askyesno',return_value=False) as confirm:
            self.app.delete_button.invoke()
        self.service.delete_source.assert_not_called()
        self.assertIn(str(row['source_id']),confirm.call_args.args[1])
        self.assertIn('Customer',confirm.call_args.args[1])
        self.assertIn('Unsent batches remain',confirm.call_args.args[1])
        self.assertEqual(confirm.call_args.kwargs['default'],'no')
        self.app.busy=True
        try:
            with patch('server.management.gui.messagebox.askyesno') as confirm:self.app.delete_source()
            confirm.assert_not_called()
        finally:self.app.busy=False

    def test_delete_in_network_mode_refreshes_list_and_preserves_success_message(self):
        self.service.settings=ServerSettings(Path(self.folder.name),mode='network',listen_address='0.0.0.0',server_host='central-pc')
        row=self.select_source()
        self.service.delete_source.side_effect=lambda source:self.service.sources.return_value.clear()
        with patch('server.management.gui.messagebox.askyesno',return_value=True):self.app.delete_button.invoke()
        self.wait_idle()
        self.service.delete_source.assert_called_once_with(row['source_id'])
        self.assertEqual(self.app.tree.get_children(),())
        self.assertNotIn(str(row['source_id']),self.app.details.get())
        self.assertIn('SCADA source deleted',self.app.status_text.get())

    def test_delete_failure_keeps_selected_source_and_reports_error(self):
        row=self.select_source()
        self.service.delete_source.side_effect=CollectorError('Cannot delete this source.')
        with patch('server.management.gui.messagebox.askyesno',return_value=True),patch('server.management.gui.messagebox.showerror') as error:
            self.app.delete_button.invoke();self.wait_idle()
        error.assert_called_once()
        self.assertTrue(self.app.tree.exists(str(row['source_id'])))
        self.assertEqual(self.app.status_text.get(),'Cannot delete this source.')

    def test_registration_hierarchy_and_generated_identity_display(self):
        customer_id=uuid4();site_id=uuid4()
        self.app.registry['customers']=[dict(customer_id=customer_id,name='Existing customer')]
        self.app.registry['sites']=[dict(customer_id=customer_id,site_id=site_id,name='Existing site')]
        self.app._cascade()
        self.app.choices['customer'].set(next(iter(self.app.choice_maps['customer'])))
        self.app._cascade('customer')
        self.assertEqual(len(self.app.choice_maps['site']),1)
        self.app.choices['site'].set(next(iter(self.app.choice_maps['site'])))
        self.app.names['project'].set('New project');self.app.names['machine'].set('M-1');self.app.names['source'].set('SCADA PC')
        self.app.register_source();self.wait_idle()
        params=self.service.register.call_args.kwargs
        self.assertEqual(params['customer_id'],customer_id)
        self.assertEqual(params['site_id'],site_id)
        self.assertIsNone(params['project_id'])
        self.assertEqual(params['source_name'],'SCADA PC')

    def test_registration_normalizes_pasted_names_before_sending_them(self):
        for name,value in dict(customer=' Customer\r\n',site='Site',project='Project\r\nName',machine='M-1',source='SCADA PC').items():
            self.app.names[name].set(value)
        with patch('server.management.gui.messagebox.showerror') as error:
            self.app.register_source();self.wait_idle()
        error.assert_not_called()
        values=self.service.register.call_args.kwargs
        self.assertEqual(values['project_name'],'Project Name')
        self.assertEqual(values['customer_name'],'Customer')
        self.assertEqual(self.app.names['project'].get(),'Project Name')

    def test_registration_invalid_project_is_rejected_before_database_work(self):
        for name,value in dict(customer='Customer',site='Site',project='Project\x00Name',machine='M-1',source='SCADA PC').items():
            self.app.names[name].set(value)
        with patch('server.management.gui.messagebox.showerror') as error:
            self.app.register_source();self.wait_idle()
        self.service.register.assert_not_called()
        error.assert_called_once()
        self.assertIn('project name',self.app.status_text.get())
        self.assertIn('control character',self.app.status_text.get())

    def test_refuses_location_change_while_server_running(self):
        self.app.https_port.set('8444')
        with patch('server.management.gui.save_settings') as save,patch('server.management.gui.messagebox.showerror') as error:
            self.app.save_locations();self.wait_idle()
        save.assert_not_called();error.assert_called_once()

    def test_save_confirmation_survives_refresh_when_database_is_stopped(self):
        self.app.https_port.set('8444')
        settings=self.app._form_settings()
        self.status.update(api_ready=False,database_ready=False,worker_running=False,
                           error='Central database is stopped or unavailable under this Windows account.')
        updated=Mock(spec=ManagerService)
        updated.settings=settings
        updated.status.return_value=dict(self.status,upload_url=settings.upload_url)
        with patch('server.management.gui.save_settings') as save,patch('server.management.gui.ManagerService',return_value=updated),patch('server.management.gui.messagebox.showerror') as error:
            self.app.save_locations();self.wait_idle()
        save.assert_called_once_with(settings)
        error.assert_not_called()
        self.assertEqual(self.app.status_text.get(),'Server settings saved successfully.')
        self.assertIn('PostgreSQL: Stopped',self.app.health_text.get())
        self.assertIn(':8444/',self.app.endpoint.get())

    def test_save_failure_keeps_error_without_showing_success(self):
        message='Cannot save settings; check local file permissions.'
        with patch('server.management.gui.save_settings',side_effect=CollectorError(message)),patch('server.management.gui.ManagerService') as manager,patch('server.management.gui.messagebox.showerror') as error:
            self.app.save_locations();self.wait_idle()
        manager.assert_not_called()
        error.assert_called_once()
        self.assertEqual(self.app.status_text.get(),message)

    def test_manual_refresh_still_reports_database_status_errors(self):
        self.status.update(api_ready=False,database_ready=False,worker_running=False,
                           error='Central database is stopped or unavailable under this Windows account.')
        self.app.refresh();self.wait_idle()
        self.assertEqual(self.app.status_text.get(),self.status['error'])

    def test_network_mode_sets_listener_and_previews_destination_without_starting(self):
        self.app.mode.set('Network server (multiple collector PCs)');self.app._mode_changed()
        self.assertEqual(self.app.listen_address.get(),'0.0.0.0')
        self.assertEqual(self.app.server_host.get(),'')
        self.app.server_host.set('central-pc')
        self.assertIn('https://central-pc:8443/v1/uploads',self.app.url_preview.get())
        with patch('server.management.gui.messagebox.showerror') as error:self.app.start_server()
        error.assert_called_once();self.service.start.assert_not_called()
        self.app.mode.set('Local testing (one PC)');self.app._mode_changed()
        self.assertEqual(self.app.listen_address.get(),'127.0.0.1')
        self.assertEqual(self.app.server_host.get(),'localhost')
