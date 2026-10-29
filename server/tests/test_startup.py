from contextlib import ExitStack
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch

from collector.errors import CollectorError


@unittest.skipUnless(os.name=='nt','Windows process startup')
class StartupFailureTests(unittest.TestCase):
    def setUp(self):
        from deploy import local_server
        self.server=local_server
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.root=Path(folder.name)
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(local_server,'LOCAL',self.root))
        self.stack.enter_context(patch.object(local_server,'WORKING_DIR',self.root))
        self.stack.enter_context(patch.object(local_server,'setup_database',return_value={'api':'test-only-api-password','worker':'test-only-worker-password'}))
        self.stack.enter_context(patch.object(local_server,'process_identity',side_effect=['owned-api','owned-worker']))
        self.stop=self.stack.enter_context(patch.object(local_server,'stop_process'))
        self.sleep=self.stack.enter_context(patch.object(local_server.time,'sleep'))
        self.stack.enter_context(patch('ssl.create_default_context'))
        self.client=self.stack.enter_context(patch.object(local_server.httpx,'Client')).return_value.__enter__.return_value
        self.client.get.return_value.status_code=200
        self.client.get.return_value.json.return_value={'status':'ready'}
        self.api=Mock(pid=101);self.api.poll.return_value=None
        self.worker=Mock(pid=102);self.worker.poll.return_value=None
        self.popen=self.stack.enter_context(patch.object(local_server.subprocess,'Popen',side_effect=[self.api,self.worker]))

    def test_api_or_worker_exit_fails_without_waiting_and_cleans_owned_components(self):
        for component,label in ((self.api,'HTTPS API'),(self.worker,'worker')):
            with self.subTest(component=label):
                component.poll.return_value=1
                with self.assertRaisesRegex(CollectorError,label):self.server.start()
                self.client.get.assert_not_called();self.sleep.assert_not_called()
                self.assertEqual(self.stop.call_count,2)
                component.poll.return_value=None
                self.stop.reset_mock();self.popen.side_effect=[self.api,self.worker]
                self.stack.enter_context(patch.object(self.server,'process_identity',side_effect=['owned-api','owned-worker']))
                (self.root/'processes.json').unlink()

    def test_wrong_health_response_does_not_report_success_and_cleans_components(self):
        self.client.get.return_value.json.return_value={'status':'some other service'}
        with self.assertRaisesRegex(CollectorError,'did not become ready'):self.server.start()
        self.assertEqual(self.stop.call_count,2)

    def test_partial_launch_failure_cleans_the_component_already_started(self):
        self.popen.side_effect=[self.api,OSError('could not launch worker')]
        with self.assertRaises(OSError):self.server.start()
        self.stop.assert_called_once_with({'pid':101,'created':'owned-api'})


class StartupMessageTests(unittest.TestCase):
    def test_safe_startup_error_is_actionable_but_unexpected_errors_remain_redacted(self):
        from server.management.entry import main
        for error,expected,excluded in ((CollectorError('HTTPS listen address is not available on this server PC.'),'not available on this server PC',None),
                                        (ValueError('password=private'),'Error type: ValueError','password=private')):
            with self.subTest(error=type(error).__name__):
                output=io.StringIO()
                with patch('server.management.entry._main',side_effect=error),patch('sys.stderr',output):
                    self.assertEqual(main(['--component','start']),1)
                self.assertIn(expected,output.getvalue())
                if excluded:self.assertNotIn(excluded,output.getvalue())
