
# Keep direct execution independent of the working directory.
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))

import io
import json
import unittest
import tempfile
import tarfile
from pathlib import Path
from audit_saved_stress import analyze, retain_member, CASE


class AuditTest(unittest.TestCase):
    def test_private_evidence_filters_links_paths_keys_and_reasoning(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            entries = [{'part':{'type':'reasoning','text':'PRIVATE_REASONING_SENTINEL'}},
                       {'part':{'type':'tool','tool':'bash','state':{'status':'completed'}}}]
            data = '\n'.join(json.dumps(x) for x in entries).encode()
            member = tarfile.TarInfo(CASE+'/transcripts/test.jsonl'); member.size = len(data)
            retain_member(member, io.BytesIO(data), destination)
            text = (destination/'transcripts/test.jsonl').read_text()
            self.assertNotIn('PRIVATE_REASONING_SENTINEL', text)
            self.assertIn('bash', text)
            for name in [CASE+'/case/../escape',CASE+'/case/.env',CASE+'/case/auth.json']:
                member = tarfile.TarInfo(name); member.size = 4
                retain_member(member, io.BytesIO(b'key!'), destination)
            link = tarfile.TarInfo(CASE+'/case/link'); link.type = tarfile.SYMTYPE; link.linkname = '/tmp'
            retain_member(link, io.BytesIO(), destination)
            self.assertEqual([p.name for p in destination.rglob('*') if p.is_file()], ['test.jsonl'])

    def test_only_metadata_and_repeat_links_leave_reader(self):
        secret = 'PRIVATE_CASE_SENTINEL'
        def event(identifier):
            return {'type':'tool_use','part':{'type':'tool','id':identifier,'tool':'bash',
                'state':{'status':'completed','input':{'command':'bin/checkpoint --guard '+secret},
                         'output':secret+' diagnostic allowance exhausted',
                         'metadata':{'exit':1},'time':{'start':1000,'end':1100}}}}
        entries = [event('a'), event('a'), event('b'),
                   {'part':{'type':'reasoning','text':secret}},
                   {'part':{'type':'text','text':secret}}]
        out = analyze(io.BytesIO(('\n'.join(json.dumps(e) for e in entries)+'\nnot-json').encode()))
        self.assertNotIn(secret, json.dumps(out))
        self.assertEqual(out['completed_tool_actions'], 2)
        self.assertEqual(out['exact_repeated_inputs'], 1)
        self.assertEqual(out['category_counts'], {'checkpoint':2})
        self.assertEqual(out['result_error_marker_counts'], {'diagnostic_exhausted':2})
        self.assertEqual(out['actions'][1]['same_input_as_action'], 1)
        self.assertEqual(out['actions'][0]['exit_code'], 1)
        self.assertEqual(out['malformed_lines'], 1)


if __name__ == '__main__': unittest.main()
