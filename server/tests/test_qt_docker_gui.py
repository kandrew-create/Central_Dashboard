import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from collector.errors import CollectorError
from server.management.docker import DockerManagerService, DockerSettings

try:
    from PySide6.QtWidgets import QApplication, QDialog, QLabel
    from server.management.qt_docker_gui import DockerManagerWindow, ExportPasswordDialog
except ImportError:
    QApplication = None


@unittest.skipUnless(QApplication is not None, 'optional Qt Docker GUI dependency is not installed')
class ModernDockerWindowTests(unittest.TestCase):
    def test_minutes_display_preserves_all_existing_saved_second_intervals(self):
        for seconds in (0, *range(5, 3601)):
            self.app.refresh_interval.setValue(seconds / 60)
            self.assertEqual(self.app._refresh_seconds(), seconds)
        self.app._set_refresh_preference(dict(interval_seconds=30))
        self.assertEqual(self.app.refresh_interval.value(), 0.5)
        self.assertEqual(self.app.refresh_interval.suffix(), ' minutes')
        self.app.refresh_interval.setValue(2)
        self.app.save_refresh_preference()
        self.wait_idle()
        self.service.save_refresh_settings.assert_called_once_with(120)

    def test_application_startup_starts_selected_server_once_off_gui_thread(self):
        self.destroy()
        calls = []
        gui_thread = threading.get_ident()
        self.service.start_if_needed.side_effect = lambda: calls.append(threading.get_ident()) or self.status
        self.app = DockerManagerWindow(self.service, auto_start=True)
        self.app.show()
        self.application.processEvents()
        self.wait_idle()
        self.service.start_if_needed.assert_called_once()
        self.assertTrue(calls)
        self.assertNotEqual(calls[0], gui_thread)
        self.assertIn('server is ready', self.app.footer.text())
        self.service.enable_machine_ai.assert_not_called()

    def test_alarm_analysis_runs_off_gui_thread_and_keeps_ai_suggestions_separate(self):
        threads = []
        result = dict(summary=dict(occurrences=2, saved_versions=3, confirmed_equipment=1,
                                   uncertain_time=1, uncertain_order=1, unmapped=1),
                      issues=[dict(source_name='Fixture source', tag='TAG', message='Conveyor VFD Connect Error',
                                   occurrences=1, confirmed_equipment='LINE-01', ai_suggestions='Conveyor VFD')],
                      daily=[dict(day='2026-10-20', occurrences=1)])
        self.service.alarm_analysis.side_effect = lambda **kwargs: threads.append(threading.get_ident()) or result
        self.app.navigate(5)
        self.wait_idle()
        self.assertNotEqual(threads[0], threading.get_ident())
        self.assertEqual(self.app.analysis_issues.item(0, 4).text(), 'LINE-01')
        self.assertEqual(self.app.analysis_issues.item(0, 5).text(), 'Conveyor VFD')
        self.assertIn('2 alarm occurrences', self.app.analysis_summary.text())
        self.service.enable_machine_ai.assert_not_called()
        self.app.analysis_days.setCurrentIndex(2)
        self.assertEqual(self.app.analysis_issues.rowCount(), 0)

    def test_upload_url_is_absent_from_routine_labels_and_copy_controls(self):
        from PySide6.QtWidgets import QPushButton
        self.assertFalse(any('/v1/uploads' in item.text() for item in self.app.findChildren(QLabel)))
        self.assertFalse(any('Copy URL' == item.text() for item in self.app.findChildren(QPushButton)))

    def test_background_analysis_failure_preserves_save_feedback_and_server_status(self):
        self.app.navigate(5)
        self.wait_idle()
        self.app.footer.setText('Server settings saved successfully.')
        self.service.alarm_analysis.side_effect = CollectorError('Analysis unavailable')
        with patch('server.management.qt_docker_gui.QMessageBox.critical') as popup:
            self.app.refresh(quiet=True)
            self.wait_idle()
        self.assertEqual(self.app.footer.text(), 'Server settings saved successfully.')
        self.assertIn('Analysis unavailable', self.app.analysis_summary.text())
        self.assertTrue(self.app.status['database_ready'])
        popup.assert_not_called()

    def test_refresh_interval_waits_from_completion_and_pauses_during_work(self):
        self.app._set_refresh_preference(dict(interval_seconds=10))
        self.assertTrue(self.app.refresh_timer.isSingleShot())
        started, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        def status():
            started.set()
            release.wait(2)
            return self.status
        self.service.status.side_effect = status
        self.app._automatic_refresh()
        self.assertTrue(started.wait(1))
        self.assertFalse(self.app.refresh_timer.isActive())
        release.set()
        self.wait_idle()
        self.assertEqual(self.app.refresh_timer.interval(), 10000)
        self.assertGreater(self.app.refresh_timer.remainingTime(), 9500)

    def test_skipped_refresh_rearms_without_reading_or_changing_saved_interval(self):
        self.app._set_refresh_preference(dict(interval_seconds=10))
        self.app.names['source'].setText('Unfinished registration')
        self.service.status.reset_mock()
        self.app._automatic_refresh()
        self.service.status.assert_not_called()
        self.assertTrue(self.app.refresh_timer.isActive())
        self.assertEqual(self.app.refresh_timer.interval(), 10000)

    def test_automatic_refresh_updates_counts_and_preserves_success_feedback(self):
        self.app.footer.setText('Server settings saved successfully.')
        self.service.status.return_value = dict(self.status, revisions=8, batches=2)
        self.app._automatic_refresh()
        self.wait_idle()
        self.assertEqual(self.app.status['revisions'], 8)
        self.assertEqual(self.app.footer.text(), 'Server settings saved successfully.')
        self.assertTrue(self.app.refresh_timer.isActive())

    def test_automatic_refresh_skips_busy_and_unsaved_edits(self):
        self.service.status.reset_mock()
        self.app.busy = True
        self.app._automatic_refresh()
        self.app.busy = False
        self.app.names['source'].setText('Unsaved source')
        self.app._automatic_refresh()
        self.service.status.assert_not_called()

    def test_automatic_refresh_failure_is_quiet_and_off_setting_stops_timer(self):
        self.app.footer.setText('Saved successfully.')
        self.service.status.side_effect = CollectorError('Temporary Docker fault')
        with patch('server.management.qt_docker_gui.QMessageBox.critical') as popup:
            self.app._automatic_refresh()
            self.wait_idle()
        popup.assert_not_called()
        self.assertIn('Automatic refresh failed', self.app.refresh_note.text())
        self.assertEqual(self.app.footer.text(), 'Saved successfully.')
        self.app.refresh_interval.setValue(0)
        self.app.save_refresh_preference()
        self.wait_idle()
        self.assertFalse(self.app.refresh_timer.isActive())
        self.service.save_refresh_settings.assert_called_once_with(0)

    def test_deployment_save_keeps_success_feedback_when_database_is_stopped(self):
        from dataclasses import replace
        self.app.deployment_fields['https_port'].setText('9444')
        self.service.save_settings.side_effect = lambda candidate: setattr(self.service, 'settings', candidate) or candidate
        self.service.status.return_value = dict(self.status, database_ready=False, api_ready=False, worker_running=False,
                                              error='Server is stopped')
        self.service.machine_interpretations.side_effect = CollectorError('Optional AI read failed')
        self.app.save_deployment()
        self.wait_idle()
        self.assertEqual(self.service.settings.https_port, 9444)
        self.assertIn('saved successfully', self.app.footer.text())
        self.assertNotIn('https://', self.app.overview_endpoint.text())
        self.service.start.assert_not_called()

    def test_model_refresh_retains_unsaved_entry_and_never_enables_ai(self):
        self.app._show_ai_configuration(dict(enabled=False, model='saved-model'))
        self.app.ai_model.setText('unsaved-model')
        self.app._show_identification(dict(configuration=dict(enabled=False, model='saved-model'), rows=[], records_available=False))
        self.assertEqual(self.app.ai_model.text(), 'unsaved-model')
        self.service.enable_machine_ai.assert_not_called()
        self.app.ai_model.setText('saved-model')

    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])
        cls.application.setQuitOnLastWindowClosed(False)
        cls.application.setStyle('Fusion')

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.service = Mock(spec=DockerManagerService)
        self.service.settings = DockerSettings(Path(self.directory.name))
        self.service.export_directory = Path(self.directory.name)
        self.status = dict(initialized=True, api_ready=True, database_ready=True, worker_running=True,
                           sources=0, batches=0, revisions=0, quarantined_batches=0, failed_jobs=0,
                           upload_url='https://localhost/v1/uploads', error=None)
        self.service.status.return_value = self.status
        self.service.catalog.return_value = {key: [] for key in ('customers', 'sites', 'projects', 'machines')}
        self.service.sources.return_value = []
        self.service.load_refresh_settings.return_value = dict(interval_seconds=30)
        self.service.save_refresh_settings.side_effect = lambda seconds: dict(interval_seconds=seconds)
        self.service.machine_interpretations.return_value = dict(configuration=dict(enabled=False, model='Not configured'),
                                                               rows=[], records_available=True)
        self.service.alarm_analysis.return_value = dict(summary=dict(occurrences=0, saved_versions=0, confirmed_equipment=0,
            uncertain_time=0, uncertain_order=0, unmapped=0), issues=[], daily=[])
        self.app = DockerManagerWindow(self.service)
        self.app.show()
        self.addCleanup(self.destroy)
        self.wait_idle()

    def wait_idle(self):
        deadline = time.monotonic() + 5
        while self.app.busy and time.monotonic() < deadline:
            self.application.processEvents()
            time.sleep(.01)
        self.application.processEvents()
        self.assertFalse(self.app.busy)

    def destroy(self):
        self.wait_idle()
        self.app.form_dirty = False
        self.app.close()
        self.app.deleteLater()
        self.application.processEvents()

    def test_refresh_runs_off_gui_thread_and_optional_ai_error_keeps_success(self):
        gui_thread = threading.get_ident()
        threads = []
        self.service.status.side_effect = lambda: threads.append(threading.get_ident()) or self.status
        self.service.machine_interpretations.side_effect = CollectorError('Saved results unavailable')
        self.app.refresh('Settings saved successfully.')
        self.wait_idle()
        self.assertTrue(threads)
        self.assertTrue(all(thread != gui_thread for thread in threads))
        self.assertEqual(self.app.footer.text(), 'Settings saved successfully.')
        self.assertEqual(self.app.ai_note.text(), 'Saved results unavailable')
        self.assertIn('ready', self.app.health_pill.text())

    def test_network_deployment_displays_saved_endpoint_and_connection_mode(self):
        self.destroy()
        self.service.settings = DockerSettings(Path(self.directory.name), mode='network',
            server_host='192.0.2.10', listen_address='0.0.0.0', https_port=8443)
        self.status['upload_url'] = self.service.settings.upload_url
        self.app = DockerManagerWindow(self.service)
        self.app.show()
        self.wait_idle()
        self.app.navigate(3)
        labels = [item.text() for item in self.app.findChildren(QLabel)]
        self.assertIn('NETWORK DEPLOYMENT', labels)
        self.assertIn('Network server (multiple collector PCs)', labels)
        self.assertNotIn('https://192.0.2.10:8443/v1/uploads', labels)
        self.assertNotIn('LOCAL DEPLOYMENT', labels)

    def test_activity_and_final_failure_message_are_retained(self):
        started, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        def work():
            started.set()
            release.wait(3)
            raise CollectorError('Fixture operation failed')
        self.app._start('Working…', work, lambda value: None)
        self.assertTrue(started.wait(1))
        self.assertEqual(self.app.progress.maximum(), 0)
        self.assertFalse(self.app.refresh_button.isEnabled())
        release.set()
        with patch('server.management.qt_docker_gui.QMessageBox.critical'):
            self.wait_idle()
        self.assertEqual(self.app.progress.maximum(), 1)
        self.assertEqual(self.app.footer.text(), 'Fixture operation failed')

    def test_registration_validates_before_backend_and_normalizes_labels(self):
        for key, value in (('customer', 'Customer'), ('site', 'Site'), ('project', 'Bad\x01label'),
                           ('source', 'SCADA PC')):
            self.app.names[key].setText(value)
        with patch('server.management.qt_docker_gui.QMessageBox.warning'):
            self.app.register_source()
        self.service.register.assert_not_called()
        self.app.names['project'].setText('  Line\tProject  ')
        with patch('server.management.qt_docker_gui.QMessageBox.warning'):
            self.app.register_source()
        self.service.register.assert_not_called()
        self.assertIn('Select an existing machine', self.app.footer.text())
        self.select_registered_machine()
        self.app.names['source'].setText('  SCADA\tPC  ')
        self.app.register_source()
        self.wait_idle()
        self.service.register.assert_called_once()
        self.assertEqual(self.service.register.call_args.kwargs['source_name'], 'SCADA PC')
        self.assertEqual(self.app.pages.currentIndex(), 2)
        self.assertFalse(self.app.form_dirty)
        self.assertIn('Source registered', self.app.footer.text())

    def test_confirmation_guards_stop_and_source_deletion(self):
        source = dict(source_id='fixture-source', generation_id='fixture-generation', name='Fixture source',
                      customer_name='Customer', site_name='Site', project_name='Project', last_received=None, quarantined_batches=0)
        self.service.sources.return_value = [source]
        self.app.refresh()
        self.wait_idle()
        self.app.source_table.selectRow(0)
        with patch.object(self.app, 'confirm', return_value=False):
            self.app.stop_server()
            self.app.delete_source()
        self.service.stop.assert_not_called()
        self.service.delete_source.assert_not_called()
        with patch.object(self.app, 'confirm', return_value=True):
            self.app.delete_source()
        self.wait_idle()
        self.service.delete_source.assert_called_once_with('fixture-source')
        self.assertIn('history retained', self.app.footer.text())

    def test_selection_is_not_reassigned_to_a_different_source_after_refresh(self):
        def source(identifier):
            return dict(source_id=identifier, generation_id='fixture-generation', name=identifier, customer_name='Customer',
                        site_name='Site', project_name='Project', last_received=None, quarantined_batches=0)
        self.service.sources.return_value = [source('first'), source('second')]
        self.app.refresh()
        self.wait_idle()
        self.app.source_table.selectRow(0)
        self.assertTrue(self.app.export_button.isEnabled())
        self.service.sources.return_value = [source('second')]
        self.app.refresh()
        self.wait_idle()
        self.assertIsNone(self.app.selected_source())
        self.assertFalse(self.app.export_button.isEnabled())

    def test_password_confirmation_and_secret_clearing(self):
        dialog = ExportPasswordDialog(self.app)
        dialog.password.setText('fixture export password')
        dialog.confirmation.setText('different')
        dialog.accept()
        self.assertNotEqual(dialog.result(), QDialog.DialogCode.Accepted)
        dialog.confirmation.setText('fixture export password')
        dialog.accept()
        self.assertEqual(dialog.take_password(), 'fixture export password')
        self.assertEqual(dialog.password.text(), '')
        self.assertEqual(dialog.confirmation.text(), '')
        dialog.deleteLater()

    def select_registered_machine(self):
        customer = dict(customer_id='customer-id', name='Customer')
        site = dict(customer_id='customer-id', site_id='site-id', name='Site')
        project = dict(customer_id='customer-id', site_id='site-id', project_id='project-id', name='Project')
        machine = dict(customer_id='customer-id', site_id='site-id', project_id='project-id', machine_id='machine-id',
                       name='Machine', machine_tag='LINE-01')
        self.service.catalog.return_value = dict(customers=[customer], sites=[site], projects=[project], machines=[machine])
        self.app.refresh()
        self.wait_idle()
        for name in ('customer', 'site', 'project', 'machine'):
            self.app.choices[name].setCurrentIndex(1)
            if name != 'machine':
                self.assertFalse(self.app.names[name].isEnabled())

    def test_registry_reuse_keeps_parent_ids_and_disables_new_name_fields(self):
        self.select_registered_machine()
        self.app.names['source'].setText('Another fixture source')
        self.app.register_source()
        self.wait_idle()
        values = self.service.register.call_args.kwargs
        self.assertEqual(values['customer_id'], 'customer-id')
        self.assertEqual(values['site_id'], 'site-id')
        self.assertEqual(values['project_id'], 'project-id')
        self.assertEqual(values['machine_id'], 'machine-id')
        self.assertNotIn('machine_tag', values)

    def test_export_dispatches_selected_identity_and_password_without_replacing_existing_files(self):
        self.service.sources.return_value = [dict(source_id='fixture-source', generation_id='fixture-generation', name='Fixture',
                                                 customer_name='Customer', site_name='Site', project_name='Project',
                                                 last_received=None, quarantined_batches=0)]
        self.app.refresh()
        self.wait_idle()
        self.app.source_table.selectRow(0)
        path = str(Path(self.directory.name) / 'fixture.linker-collector')
        with (patch('server.management.qt_docker_gui.QFileDialog.getSaveFileName', return_value=(path, '')),
              patch('server.management.qt_docker_gui.ExportPasswordDialog') as dialog):
            dialog.return_value.exec.return_value = QDialog.DialogCode.Accepted
            dialog.return_value.take_password.return_value = 'fixture export password'
            self.app.export_setup()
        self.wait_idle()
        self.service.export.assert_called_once_with('fixture-source', path, 'fixture export password')
        Path(path).write_bytes(b'existing encrypted fixture')
        self.service.export.reset_mock()
        with (patch('server.management.qt_docker_gui.QFileDialog.getSaveFileName', return_value=(path, '')),
              patch('server.management.qt_docker_gui.QMessageBox.warning')):
            self.app.export_setup()
        self.service.export.assert_not_called()
        self.assertEqual(Path(path).read_bytes(), b'existing encrypted fixture')

    def test_identification_tab_defers_reads_during_work_and_preserves_feedback(self):
        started, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        self.service.machine_interpretations.reset_mock()
        def work():
            started.set()
            release.wait(3)
            return True
        self.app._start('Working…', work, lambda value: self.app.footer.setText('Operation completed.'))
        self.assertTrue(started.wait(1))
        self.app.navigate(4)
        self.assertTrue(self.app._ai_pending)
        self.service.machine_interpretations.assert_not_called()
        release.set()
        self.wait_idle()
        self.service.machine_interpretations.assert_called_once()
        self.assertEqual(self.app.footer.text(), 'Operation completed.')

    def test_identification_preserves_original_message_and_never_enables_ai(self):
        result = dict(records_available=True, rows=[dict(source_name='Fixture SCADA', source_table='alarmhistory',
                      source_record_id=1, status='suggested', candidates=[dict(label='Conveyor VFD')], model='fixture-local',
                      policy_version='fixture', original_message='Conveyor VFD <Connect Error>')])
        self.app._show_identification(result)
        self.app.ai_table.selectRow(0)
        self.assertEqual(self.app.ai_evidence.toPlainText(), 'Conveyor VFD <Connect Error>')
        self.assertNotIn('enable_machine_ai', [call[0] for call in self.service.method_calls])

    def test_footer_and_navigation_remain_available_at_minimum_window_size(self):
        self.app.resize(1100, 740)
        for index in range(5):
            self.app.navigate(index)
            self.wait_idle()
            self.assertTrue(self.app.footer_frame.isVisible())
            self.assertLessEqual(self.app.footer_frame.geometry().bottom(), self.app.centralWidget().height())
            self.assertTrue(self.app.nav_buttons[index].isVisible())
