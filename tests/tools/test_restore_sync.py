"""Synthetic local publication: no keys, network, workers or real bundles."""
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


class SyncTests(unittest.TestCase):
    def test_successor_identity_and_generation_backups_retry_and_compare(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'bundle'; (root / 'sealed').mkdir(parents=True)
            remote = Path(tmp) / 'remote'; remote.mkdir()
            case = 'case-synthetic'
            sha = lambda data: hashlib.sha256(data).hexdigest()
            dump = lambda value: json.dumps(value).encode()
            original = dict(case=case, status='stopped', sha256=sha(b'old checkpoint'),
                statement_sha256='a'*64, continuation_budget=dict(calls=1, cost=1, events=[]))
            current = {**original, 'sha256':sha(b'new checkpoint'),
                       'continuation_budget':dict(calls=2, cost=2, events=[])}
            old = {case+'.'+suffix: b'old '+suffix.encode() for suffix in
                   ('casekey.age', 'statement.age', 'search.age', 'progress.json', 'scorecard.txt')}
            old.update({case+'.checkpoint.tar.gz.age':b'old checkpoint',
                        case+'.scorecard.json':dump(original)})
            incoming = {**old, case+'.checkpoint.tar.gz.age':b'new checkpoint',
                        case+'.scorecard.json':dump(current)}
            for name, data in old.items():
                (remote/name).write_bytes(data)
                (remote/(name+'.pre-restore')).write_bytes(b'even older generation')
            for name, data in incoming.items(): (root/'sealed'/name).write_bytes(data)
            baseline = {name:sha(data) for name,data in old.items()}
            for name, value in {'restore-config.json':{'case':case},
                    'input-sha256.json':baseline, 'vm-baseline-sha256.json':baseline,
                    'input-scorecard.json':original, 'expected-restored-scorecard.json':original}.items():
                (root/name).write_bytes(dump(value))
            with patch.dict(os.environ, UNBUG_RESTORE_ROOT=str(root)):
                api = runpy.run_path(str(ROOT/'factory/restore_sync.py'))
            request = api['prepare']()  # Original identity is direct; no obsolete ruling file.
            for attempt in range(2):
                stage = remote/('stage'+str(attempt)); stage.mkdir()
                for name in incoming: shutil.copy2(root/'sealed'/name, stage/name)
                result = subprocess.run([sys.executable, '-B', '-', json.dumps(request), str(stage)],
                    input=api['REMOTE'], text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                receipt = json.loads(result.stdout)
                self.assertEqual(receipt['verified_sha256'], request['incoming'])
                backup = Path(receipt['pre_restore_root'])
                self.assertEqual({n:sha((backup/n).read_bytes()) for n in old}, baseline)
                self.assertTrue(all((remote/(n+'.pre-restore')).read_bytes() ==
                                    b'even older generation' for n in old))
            # A prior published generation may already be canonical. Migrate an
            # exact legacy baseline backup without replacing that older backup.
            legacy_request = {**request, 'baseline':{n:sha(b'even older generation') for n in old},
                              'expected':request['incoming']}
            stage = remote/'legacy'; stage.mkdir()
            for name in incoming: shutil.copy2(root/'sealed'/name, stage/name)
            result = subprocess.run([sys.executable, '-B', '-', json.dumps(legacy_request), str(stage)],
                input=api['REMOTE'], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['pre_restore_sha256'], legacy_request['baseline'])
            # An independent edit is rejected before any canonical replacement.
            (remote/(case+'.statement.age')).write_bytes(b'independent edit')
            before = {n:sha((remote/n).read_bytes()) for n in incoming}
            stage = remote/'conflict'; stage.mkdir()
            for name in incoming: shutil.copy2(root/'sealed'/name, stage/name)
            result = subprocess.run([sys.executable, '-B', '-', json.dumps(request), str(stage)],
                input=api['REMOTE'], text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('VM changed independently', result.stderr)
            self.assertEqual({n:sha((remote/n).read_bytes()) for n in incoming}, before)


if __name__ == '__main__': unittest.main()
