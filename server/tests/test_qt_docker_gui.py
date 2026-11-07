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
    def test_ai_buttons_follow_saved_state_after_refresh_busy_work_and_model_edits(self):
        self.app._show_ai_configuration(dict(enabled=True,model='saved-model'))
        self.assertFalse(self.app.enable_ai_button.isEnabled())
        self.assertTrue(self.app.disable_ai_button.isEnabled())
        self.assertTrue(self.app.enable_ai_button.property('aiToggle'))
        self.app.ai_model.setText('unsaved-other-model')
        self.app._sync_controls()
        self.assertFalse(self.app.enable_ai_button.isEnabled())
        self.app.busy=True;self.app._sync_controls()
        self.assertFalse(self.app.enable_ai_button.isEnabled())
        self.assertFalse(self.app.disable_ai_button.isEnabled())
        self.app.busy=False;self.app._sync_controls()
        self.assertFalse(self.app.enable_ai_button.isEnabled())
        self.assertTrue(self.app.disable_ai_button.isEnabled())
        self.app._show_ai_configuration(dict(enabled=False,model='saved-model'))
        self.assertTrue(self.app.enable_ai_button.isEnabled())
        self.assertFalse(self.app.disable_ai_button.isEnabled())
        self.assertEqual(self.app.ai_model.text(),'unsaved-other-model')
        self.app.ai_model.setText('saved-model')

    def test_successful_enable_disables_repeat_clicks_and_disable_reverses_buttons(self):
        started,release=threading.Event(),threading.Event()
        self.addCleanup(release.set)
        def enable(model):
            started.set();release.wait(3)
            config=dict(enabled=True,model=model)
            self.service.machine_interpretations.return_value=dict(configuration=config,rows=[],records_available=False)
            return config
        def disable():
            config=dict(enabled=False,model=self.app._ai_saved_model)
            self.service.machine_interpretations.return_value=dict(configuration=config,rows=[],records_available=False)
            return config
        self.service.enable_machine_ai.side_effect=enable
        self.service.disable_machine_ai.side_effect=disable
        self.app.enable_ai_button.click()
        self.assertTrue(started.wait(1))
        self.app.enable_ai_button.click()
        release.set();self.wait_idle()
        self.assertFalse(self.app.enable_ai_button.isEnabled())
        self.assertTrue(self.app.disable_ai_button.isEnabled())
        self.app.enable_ai_button.click();self.app.enable_machine_ai()
        self.service.enable_machine_ai.assert_called_once()
        self.app.disable_ai_button.click();self.wait_idle()
        self.assertTrue(self.app.enable_ai_button.isEnabled())
        self.assertFalse(self.app.disable_ai_button.isEnabled())
        self.app.disable_machine_ai()
        self.service.disable_machine_ai.assert_called_once()

    def test_failed_enable_keeps_retry_available_and_does_not_change_saved_state(self):
        self.service.enable_machine_ai.side_effect=CollectorError('Local model unavailable')
        with patch('server.management.qt_docker_gui.QMessageBox.critical'):
            self.app.enable_ai_button.click();self.wait_idle()
        self.assertIs(self.app._ai_enabled,False)
        self.assertTrue(self.app.enable_ai_button.isEnabled())
        self.assertFalse(self.app.disable_ai_button.isEnabled())

    def equipment_result(self,manual=None,version=0):
        return dict(equipment_editing_available=True,summary=dict(occurrences=1,saved_versions=1,
            uncertain_time=1,uncertain_order=1),issues=[dict(customer_id='00000000-0000-0000-0000-000000000001',
            source_id='00000000-0000-0000-0000-000000000006',source_name='Fixture source',
            condition_key='a'*64,tag='VFD',message='Conveyor VFD Connect Error',occurrences=1,
            ai_suggestions='Conveyor VFD',equipment_name=manual or 'Conveyor VFD',
            equipment_override=manual,override_version=version,equipment_origin='manual' if manual else 'ai')],daily=[])

    def open_equipment_editor(self,result=None):
        self.service.alarm_analysis.return_value=result or self.equipment_result()
        self.app.navigate(4);self.wait_idle()
        self.assertFalse(self.app.edit_equipment_button.isEnabled())
        self.app.analysis_issues.selectRow(0)
        self.assertTrue(self.app.edit_equipment_button.isEnabled())
        self.app.edit_equipment_button.click()
        self.application.processEvents()
        return self.app._equipment_dialog

    def test_equipment_edit_runs_off_gui_thread_and_preserves_original_ai_display(self):
        threads=[]
        def save(**args):
            threads.append(threading.get_ident())
            self.service.alarm_analysis.return_value=self.equipment_result('Correct drive',1)
            return dict(equipment_label=args['equipment_label'],version=1)
        self.service.save_equipment_override.side_effect=save
        dialog=self.open_equipment_editor()
        self.assertEqual(dialog.entry.text(),'Conveyor VFD')
        dialog.entry.setText('Correct drive');dialog.accept();self.wait_idle()
        self.assertIsNone(self.app._equipment_dialog)
        self.assertNotEqual(threads[0],threading.get_ident())
        self.service.save_equipment_override.assert_called_once_with(customer_id='00000000-0000-0000-0000-000000000001',
            source_id='00000000-0000-0000-0000-000000000006',condition_key='a'*64,
            equipment_label='Correct drive',expected_version=0)
        self.assertEqual(self.app.analysis_issues.item(0,4).text(),'Correct drive')
        self.assertEqual(self.app.analysis_issues.item(0,5).text(),'Conveyor VFD')
        self.assertEqual(self.app.footer.text(),'Equipment override saved.')
        self.service.enable_machine_ai.assert_not_called()

    def test_failed_equipment_save_keeps_editor_input_and_blocks_parent_close(self):
        self.service.save_equipment_override.side_effect=CollectorError('Refresh before saving this stale edit.')
        dialog=self.open_equipment_editor()
        dialog.entry.setText('Retain this input');dialog.accept();self.wait_idle()
        self.assertTrue(dialog.isVisible())
        self.assertTrue(dialog.entry.isEnabled())
        self.assertEqual(dialog.entry.text(),'Retain this input')
        self.assertIn('Refresh',dialog.error.text())
        self.app.close();self.application.processEvents()
        self.assertTrue(self.app.isVisible())
        self.assertFalse(self.app.refresh_timer.isActive())
        dialog.reject()

    def test_clear_equipment_override_restores_saved_ai_without_a_model_call(self):
        self.service.save_equipment_override.return_value=dict(equipment_label=None,version=2)
        dialog=self.open_equipment_editor(self.equipment_result('User correction',1))
        self.assertTrue(dialog.use_ai.isEnabled())
        self.service.alarm_analysis.return_value=self.equipment_result(None,2)
        dialog.use_ai.click();self.wait_idle()
        self.assertIsNone(self.service.save_equipment_override.call_args.kwargs['equipment_label'])
        self.assertEqual(self.service.save_equipment_override.call_args.kwargs['expected_version'],1)
        self.assertEqual(self.app.analysis_issues.item(0,4).text(),'Conveyor VFD')
        self.service.enable_machine_ai.assert_not_called()

    def test_empty_equipment_name_does_not_issue_a_save(self):
        dialog=self.open_equipment_editor()
        dialog.entry.setText(' ');dialog.accept()
        self.assertTrue(dialog.isVisible())
        self.assertIn('equipment name',dialog.error.text())
        self.service.save_equipment_override.assert_not_called()
        dialog.reject()

    def test_unknown_alarm_group_has_no_edit_button_action(self):
        result=self.equipment_result()
        result['issues'][0].update(tag=None,message=None)
        self.app._show_analysis(result)
        self.app.analysis_issues.selectRow(0)
        self.assertFalse(self.app.edit_equipment_button.isEnabled())
        result['issues'][0].update(tag='VFD',message='Unresolved original',equipment_editable=False)
        self.app._show_analysis(result)
        self.app.analysis_issues.selectRow(0)
        self.assertFalse(self.app.edit_equipment_button.isEnabled())

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
                      daily=[dict(day='2026-10-20',record_type='Alarm',source_name='Fixture source',
                                  description='Conveyor VFD Connect Error',equipment_name='Conveyor VFD',equipment_origin='ai',occurrences=1),
                             dict(day=None,record_type='Event',source_name='Other source',description='Operator <Start>',
                                  equipment_name='LINE-01',equipment_origin='registered',occurrences=2)])
        self.service.alarm_analysis.side_effect = lambda **kwargs: threads.append(threading.get_ident()) or result
        self.app.navigate(4)
        self.wait_idle()
        self.assertNotEqual(threads[0], threading.get_ident())
        self.assertEqual(self.app.analysis_issues.columnCount(),6)
        self.assertEqual(self.app.analysis_issues.item(0, 4).text(), 'Conveyor VFD')
        self.assertEqual(self.app.analysis_issues.item(0, 5).text(), 'Conveyor VFD')
        self.assertNotIn('mapping',self.app.analysis_summary.text().lower())
        self.assertNotIn('mapping',self.app.analysis_note.text().lower())
        self.assertIn('2 alarm occurrences', self.app.analysis_summary.text())
        self.assertEqual(self.app.analysis_daily.columnCount(),7)
        self.assertEqual([self.app.analysis_daily.item(0,column).text() for column in range(6)],
                         ['2026-10-20','Alarm','Fixture source','Conveyor VFD Connect Error','Conveyor VFD','1'])
        self.assertEqual([self.app.analysis_daily.item(1,column).text() for column in range(6)],
                         ['Uncertain date','Event','Other source','Operator <Start>','LINE-01','2'])
        self.assertIn('Unverified',self.app.analysis_daily.item(0,4).toolTip())
        self.assertEqual(self.app.analysis_daily.item(1,4).toolTip(),'Registered source machine tag')
        self.service.enable_machine_ai.assert_not_called()
        self.app.analysis_days.setCurrentIndex(2)
        self.assertEqual(self.app.analysis_issues.rowCount(), 0)

    def test_upload_url_is_absent_from_routine_labels_and_copy_controls(self):
        from PySide6.QtWidgets import QPushButton
        self.assertFalse(any('/v1/uploads' in item.text() for item in self.app.findChildren(QLabel)))
        self.assertFalse(any('Copy URL' == item.text() for item in self.app.findChildren(QPushButton)))

    def test_background_analysis_failure_preserves_save_feedback_and_server_status(self):
        self.app.navigate(4)
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
        self.app._show_ai_settings(dict(configuration=dict(enabled=False, model='saved-model'), rows=[], records_available=False))
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
        if self.app._equipment_dialog is not None:self.app._equipment_dialog.reject()
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
        self.app.names['source'].setText('  SCADA\tPC  ')
        self.app.register_source()
        self.wait_idle()
        self.service.register.assert_called_once()
        self.assertEqual(self.service.register.call_args.kwargs['project_name'], 'Line Project')
        self.assertNotIn('machine_id', self.service.register.call_args.kwargs)
        self.assertNotIn('machine_tag', self.service.register.call_args.kwargs)
        self.assertEqual(set(self.app.choices), {'customer', 'site', 'project'})
        self.assertEqual(set(self.app.names), {'customer', 'site', 'project', 'source'})
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

    def select_registered_hierarchy(self):
        customer = dict(customer_id='customer-id', name='Customer')
        site = dict(customer_id='customer-id', site_id='site-id', name='Site')
        project = dict(customer_id='customer-id', site_id='site-id', project_id='project-id', name='Project')
        self.service.catalog.return_value = dict(customers=[customer], sites=[site], projects=[project], machines=[])
        self.app.refresh()
        self.wait_idle()
        for name in ('customer', 'site', 'project'):
            self.app.choices[name].setCurrentIndex(1)
            self.assertFalse(self.app.names[name].isEnabled())

    def test_registry_reuse_keeps_parent_ids_and_disables_new_name_fields(self):
        self.select_registered_hierarchy()
        self.app.names['source'].setText('Another fixture source')
        self.app.register_source()
        self.wait_idle()
        values = self.service.register.call_args.kwargs
        self.assertEqual(values['customer_id'], 'customer-id')
        self.assertEqual(values['site_id'], 'site-id')
        self.assertEqual(values['project_id'], 'project-id')
        self.assertNotIn('machine_id', values)
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

    def test_analysis_defers_ai_settings_and_report_reads_during_work_and_preserves_feedback(self):
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

    def test_equipment_editor_preserves_original_message_as_plain_text(self):
        from PySide6.QtWidgets import QTextEdit
        result=self.equipment_result()
        result['issues'][0]['message']='Conveyor VFD <Connect Error>'
        dialog=self.open_equipment_editor(result)
        evidence=dialog.findChildren(QTextEdit)[0]
        self.assertTrue(evidence.isReadOnly())
        self.assertEqual(evidence.toPlainText(),'Conveyor VFD <Connect Error>')
        self.service.enable_machine_ai.assert_not_called()
        dialog.reject()

    def test_identification_page_removed_and_ai_controls_live_in_analysis(self):
        from server.management.qt_docker_gui import PAGES
        self.assertEqual(self.app.pages.count(),5)
        self.assertEqual([page[0] for page in PAGES],['Overview','Register source','Sources & setup','Deployment','Analysis'])
        self.assertEqual(self.app.nav_buttons[4].text(),'Analysis')
        self.assertFalse(hasattr(self.app,'ai_table'))
        self.app.navigate(4);self.wait_idle()
        self.assertEqual(self.app.page_title.text(),'Analysis')
        self.assertFalse(self.app.ai_settings_panel.isVisible())
        self.app.ai_settings_panel.show()
        self.assertTrue(self.app.ai_model.isVisible())
        self.assertTrue(self.app.enable_ai_button.isVisible())
        self.assertTrue(self.app.disable_ai_button.isVisible())
        for call in self.service.machine_interpretations.call_args_list:
            self.assertEqual(call.kwargs,dict(include_records=False))
        self.service.enable_machine_ai.assert_not_called()

    def test_footer_and_navigation_remain_available_at_minimum_window_size(self):
        self.app.resize(1100, 740)
        for index in range(5):
            self.app.navigate(index)
            self.wait_idle()
            self.assertTrue(self.app.footer_frame.isVisible())
            self.assertLessEqual(self.app.footer_frame.geometry().bottom(), self.app.centralWidget().height())
            self.assertTrue(self.app.nav_buttons[index].isVisible())
