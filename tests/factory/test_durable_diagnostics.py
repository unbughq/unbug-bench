import io
import json
from pathlib import Path
import sys
import tarfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'factory'))
from durable.diagnostics import inspect_snapshot


class Inspection(unittest.TestCase):
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
