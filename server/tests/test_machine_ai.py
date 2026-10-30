import json
import unittest
from unittest.mock import Mock,patch

import httpx

from collector.errors import CollectorError
from server.machine_ai import LocalModel, model_name


class LocalMachineAITests(unittest.TestCase):
    def test_saved_configuration_is_readable_without_database_or_model_calls(self):
        from pathlib import Path
        from server.management.service import ManagerService
        from server.management.settings import ServerSettings
        factory=Mock(side_effect=AssertionError('Database access is not needed'))
        service=ManagerService(ServerSettings(Path('unused-local-settings')),factory)
        with patch('server.machine_ai.configuration',return_value=dict(enabled=False,model='saved-model')):
            result=service.machine_interpretations(include_records=False)
        self.assertEqual(result,dict(configuration=dict(enabled=False,model='saved-model'),rows=[],records_available=False))
        factory.assert_not_called()

    def interpret(self, text, machines, **extra):
        requests = []
        def response(request):
            requests.append(json.loads(request.content))
            self.assertEqual(str(request.url), 'http://127.0.0.1:11434/api/generate')
            return httpx.Response(200, json=dict(done=True, response=json.dumps(dict(machines=machines)), **extra))
        with httpx.Client(transport=httpx.MockTransport(response)) as client:
            result = LocalModel('qwen3:4b', client).interpret(dict(al_message=text, al_user='PRIVATE_OPERATOR', al_user_comment='PRIVATE_COMMENT'))
        encoded = json.dumps(requests)
        self.assertNotIn('PRIVATE_OPERATOR', encoded)
        self.assertNotIn('PRIVATE_COMMENT', encoded)
        return result

    def test_native_oven_and_mua_labels_are_preserved(self):
        for label in ('Oven 1','MUA 1'):
            candidates, status = self.interpret(label+' temperature high', [label])
            self.assertEqual(status, 'suggested')
            self.assertEqual(candidates[0]['label'], label)

    def test_conveyor_vfd_is_equipment_and_connect_error_is_the_condition(self):
        self.assertEqual(self.interpret('Conveyor VFD Connect Error',['Conveyor VFD']),
                         ([dict(label='Conveyor VFD',field='al_message')],'suggested'))
        for label in ('Conveyor VFD Connect Error','Connect Error'):
            self.assertEqual(self.interpret('Conveyor VFD Connect Error',[label]),([], 'uncertain'))

    def test_alarm_conditions_cannot_be_accepted_as_equipment_even_when_present(self):
        for message in ('Communication Error','General alarm','High temperature','Fan not running'):
            with self.subTest(message=message):
                self.assertEqual(self.interpret(message,[message]),([], 'uncertain'))

    def test_multiple_or_absent_equipment_remains_uncertain(self):
        self.assertEqual(self.interpret('General alarm', [])[1], 'uncertain')
        machines = ['Oven 1','MUA 1']
        self.assertEqual(self.interpret('Oven 1 interlock with MUA 1', machines)[1], 'uncertain')

    def test_hallucinated_partial_and_wrong_field_evidence_is_rejected(self):
        for item in ('Oven 2','Oven 1',
                     dict(label='Oven 10',field='ev_source')):
            with self.subTest(item=item):
                self.assertEqual(self.interpret('Oven 10 high temperature', [item]),([], 'uncertain'))

    def test_truncated_response_and_cloud_model_are_rejected(self):
        self.assertEqual(self.interpret('Oven 1', ['Oven 1'], done_reason='length'),([], 'uncertain'))
        for model in ('model:cloud','https://external.example/model','invalid model'):
            with self.subTest(model=model),self.assertRaises(CollectorError): model_name(model)

    def test_empty_native_text_does_not_call_model(self):
        client = Mock()
        self.assertEqual(LocalModel('qwen3:4b',client).interpret({}), ([], 'uncertain'))
        client.stream.assert_not_called()

    def test_event_messages_and_sources_never_enter_ai(self):
        client=Mock()
        result=LocalModel('qwen3:4b',client).interpret({'ev_message':'Oven 9 alarm','ev_source':'MUA 9'})
        self.assertEqual(result,([], 'uncertain'))
        client.stream.assert_not_called()

    def test_invalid_json_oversize_and_transport_errors_are_redacted(self):
        for body in (b'not json', b' '*32769, b'{"done":true,"done":false}'):
            with self.subTest(size=len(body)):
                with httpx.Client(transport=httpx.MockTransport(lambda _:httpx.Response(200,content=body))) as client:
                    with self.assertRaises(CollectorError):LocalModel('qwen3:4b',client).interpret({'al_message':'Oven 1'})
