import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'factory'))
from durable.diagnostics import inspect_snapshot


class Inspection(unittest.TestCase):
    def test_retained_answer_failures_export_shape_and_progress_without_answers(self):
        secret = 'PRIVATE RETAINED ANSWER SENTINEL'
        state = {'binding': {'kind': 'dedup', 'inputs': secret}, 'spent_routes': [secret],
                 'attempts': [{'kind': 'judgment', 'phase': 'invalid', 'output': secret,
                               'validation_error': 'schema validation failed'},
                              {'kind': 'repair', 'phase': 'invalid', 'validation_error': secret}]}
        stream = io.BytesIO(); raw = json.dumps(state).encode()
        with tarfile.open(fileobj=stream, mode='w:gz') as archive:
            member = tarfile.TarInfo('ordinary-retries/'+'a'*64+'/state.json')
            member.size = len(raw); archive.addfile(member, io.BytesIO(raw))
        report = inspect_snapshot(stream.getvalue())
        self.assertEqual(report['answer_retries'], [{'kind': 'dedup', 'spent_routes': 1, 'attempts': [
            {'kind': 'judgment', 'phase': 'invalid', 'validation': 'schema_invalid'},
            {'kind': 'repair', 'phase': 'invalid', 'validation': 'other'}]}])
        self.assertNotIn(secret, json.dumps(report))

    def test_corrupt_retained_answer_state_does_not_hide_other_evidence(self):
        stream = io.BytesIO()
        files = {'ordinary-retries/'+'a'*64+'/state.json': b'{broken',
                 'continuation-budget.json': b'{"calls":7}'}
        with tarfile.open(fileobj=stream, mode='w:gz') as archive:
            for name, raw in files.items():
                member = tarfile.TarInfo(name); member.size = len(raw)
                archive.addfile(member, io.BytesIO(raw))
        report = inspect_snapshot(stream.getvalue())
        self.assertEqual(report['model_calls'], 7)
        self.assertIs(report['answer_retry_state_invalid'], True)

    def test_valid_transport_retry_state_is_not_a_broken_answer(self):
        stream = io.BytesIO()
        raw = b'{"version":1,"transport_failures":2,"last_error":"PRIVATE TRANSPORT SENTINEL"}'
        with tarfile.open(fileobj=stream, mode='w:gz') as archive:
            member = tarfile.TarInfo('ordinary-retries/'+'a'*64+'/state.json')
            member.size = len(raw); archive.addfile(member, io.BytesIO(raw))
        report = inspect_snapshot(stream.getvalue())
        self.assertNotIn('answer_retry_state_invalid', report)
        self.assertNotIn('PRIVATE TRANSPORT SENTINEL', json.dumps(report))

    def test_worker_publishes_safe_error_summary_without_manual_inspection(self):
        from durable.worker_step import diagnostic
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            (work / 'transcripts').mkdir()
            (work / 'transcripts' / 'failed.jsonl').write_text(json.dumps({
                'type': 'assistant', 'error': 'unknown', 'message': {'content': [
                    {'type': 'text', 'text': 'API Error: 400 inference_geo is not supported for this organization type PRIVATE CASE SENTINEL'}]}}))
            result = json.loads(diagnostic(SimpleNamespace(work=work, card={}),
                                           {'reason': 'router:claude_error'}))
            self.assertEqual(result['operational']['http_statuses'], [400])
            self.assertEqual(result['operational']['typed_error_count'], 1)
            self.assertEqual(result['operational']['error_hints'], ['geo_unsupported'])
            self.assertNotIn('PRIVATE CASE SENTINEL', json.dumps(result))

    def test_cleanup_failures_are_visible_without_paths_or_exception_messages(self):
        from durable.worker_step import diagnostic
        from durable.diagnostics import cleanup_errors
        secret='PRIVATE PATH AND CASE SENTINEL'
        card={'cleanup_errors':[{'stage':'model_scratch','error':'TimeoutExpired','path':secret},
                                {'stage':'model_scratch','error':secret},{'stage':secret,'error':'OSError'}]}
        with tempfile.TemporaryDirectory() as temporary:
            work=Path(temporary)
            result=json.loads(diagnostic(SimpleNamespace(work=work,card=card),{'reason':'router:preflight_failed'}))
        self.assertEqual(result['operational']['cleanup_errors'],[{'stage':'model_scratch','error':'TimeoutExpired'}])
        self.assertNotIn(secret,json.dumps(result))
        for value in (None,secret,{}):self.assertEqual(cleanup_errors({'cleanup_errors':value}),[])
        encoded=json.dumps(card).encode();data=io.BytesIO()
        with tarfile.open(fileobj=data,mode='w:gz') as archive:
            member=tarfile.TarInfo('scorecard.json');member.size=len(encoded);archive.addfile(member,io.BytesIO(encoded))
        report=inspect_snapshot(data.getvalue())
        self.assertEqual(report['cleanup_errors'],result['operational']['cleanup_errors'])
        self.assertNotIn(secret,json.dumps(report))

    def test_json_diagnostic_inspection_exports_only_allowlisted_metadata(self):
        import base64
        from unittest.mock import patch
        from durable import diagnostics
        secret='PRIVATE CASE AND TRACEBACK SENTINEL'
        raw=json.dumps({'traceback':secret,'runner_log_tail':secret,'operational':{
            'typed_error_count':1,'http_statuses':[400,True,200,999],
            'error_hints':['request_invalid',secret],
            'cleanup_errors':[{'stage':'model_scratch','error':'TimeoutExpired','message':secret}]}}).encode()
        packet={'key':base64.b64encode(b'x'*32).decode(),'ref':{'digest':'a'*64,'kind':'diagnostic'},
                'ciphertext':base64.b64encode(b'synthetic').decode()}
        from durable.contract import ArtifactKind
        packet['ref']['kind']=ArtifactKind.DIAGNOSTIC.value
        output=io.StringIO()
        with patch.object(sys,'stdin',io.StringIO(json.dumps(packet))),patch.object(sys,'stdout',output),              patch.object(diagnostics.AgeSealer,'open',return_value=raw):
            self.assertEqual(diagnostics.main(),0)
        result=json.loads(output.getvalue())
        self.assertEqual(result['http_statuses'],[400])
        self.assertEqual(result['error_hints'],['request_invalid'])
        self.assertEqual(result['cleanup_errors'],[{'stage':'model_scratch','error':'TimeoutExpired'}])
        self.assertNotIn(secret,output.getvalue())

    def test_driver_error_envelopes_exclude_ordinary_model_prose(self):
        from durable.diagnostics import _error_fields
        for event in [{'type': 'turn.failed', 'error': {'message': 'invalid api key'}},
                      {'type': 'assistant', 'error': 'authentication_error'},
                      {'type': 'assistant', 'error': 'unknown', 'message': {'content': [
                          {'type': 'text', 'text': 'invalid api key'}]}},
                      {'type': 'system', 'subtype': 'api_retry', 'message': 'invalid api key'},
                      {'type': 'result', 'is_error': True, 'errors': ['invalid api key']}]:
            fields = _error_fields(event)
            self.assertIsNotNone(fields)
            self.assertTrue(fields[0])
        fields = _error_fields({'type': 'assistant', 'error': 'unknown', 'message': {
            'content': [{'type': 'text', 'text': 'invalid api key'}]}})
        self.assertIn('invalid api key', fields[0])
        fields = _error_fields({'type': 'assistant', 'error': 'unknown', 'message': {
            'content': [{'type': 'text', 'text': 'API Error: 403 Request not allowed'}]}})
        self.assertEqual(fields[1], [403])
        self.assertIsNone(_error_fields({'type': 'assistant', 'message': {'content': 'invalid api key'}}))
        self.assertIsNone(_error_fields({'type': 'item.completed', 'item': {'text': 'invalid api key'}}))

    def test_only_operational_codes_and_numbers_leave_archive(self):
        secret = 'PRIVATE CASE PROMPT AND API KEY SENTINEL'
        files = {'case/statement.md': secret,
                 'continuation-budget.json': json.dumps({'calls': 1, 'terminal_stop': 'provider_wait',
                    'provider_failure': {'reason': 'quota', 'message': secret}}),
                 'usage-receipts/' + 'a' * 32 + '.json': json.dumps({'outcome': 'interrupted',
                    'final_usage_known': True, 'invocation': secret,
                    'usage_delta': {'cost': 1.25, 'message': secret},
                    'cap_used': {'settled_usd': '1.25', 'exhausted': False, 'token': secret}}),
                 'transcripts/model.jsonl': '\n'.join([json.dumps({'type': 'assistant', 'text': secret + ' rate limit'}),
                    json.dumps({'type': 'error', 'error': {'message': secret + ' invalid api key'}})])}
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode='w:gz') as archive:
            for name, body in files.items():
                raw = body.encode(); member = tarfile.TarInfo(name); member.size = len(raw)
                archive.addfile(member, io.BytesIO(raw))
        result = inspect_snapshot(stream.getvalue())
        self.assertEqual(result['provider_reason'], 'quota')
        self.assertEqual(result['error_hints'], ['authentication'])
        self.assertNotIn(secret, json.dumps(result))
        self.assertNotIn('statement', json.dumps(result))
        self.assertEqual(result['receipts'][0]['cap_used']['settled_usd'], 1.25)


if __name__ == '__main__': unittest.main()
