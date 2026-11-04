#!/usr/bin/env python3
"""Offline check: interactive shell session chatter must not corrupt Boat output."""

import sys
from pathlib import Path as _Path

_BENCH_ROOT = _Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_BENCH_ROOT / "bin"))

import json
import shutil
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

CALL = (_BENCH_ROOT / "bin" / 'boat-call')


class BoatCallTests(unittest.TestCase):
    def test_standalone_copy_works_but_managed_missing_helper_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp); tools=base/'bin'; tools.mkdir()
            for name in ('boat-call','processes.py'): shutil.copy2(_BENCH_ROOT/'bin'/name,tools/name)
            provider=base/'provider'; called=base/'called'
            provider.write_text('#!/bin/sh\ntouch "'+str(called)+'"\necho \'{"ok":true}\'\n'); provider.chmod(0o755)
            env={**os.environ,'BOAT_CMD':str(provider)}
            env.pop('UNBUG_LAUNCH_STATE',None); env.pop('PYTHONPATH',None)
            good=subprocess.run([str(tools/'boat-call'),'usage','owned','--json'],env=env,capture_output=True,timeout=8)
            self.assertEqual(good.returncode,0,good.stderr); self.assertTrue(called.exists())
            called.unlink(); state=base/'managed'; state.mkdir(); (state/'ids').write_text('owned')
            bad=subprocess.run([str(tools/'boat-call'),'resume','owned'],env={**env,'UNBUG_LAUNCH_STATE':str(state)},capture_output=True,timeout=8)
            self.assertNotEqual(bad.returncode,0); self.assertFalse(called.exists())

    def test_updates_disabled_and_stdin_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / 'fake-transport'
            fake.write_text('''#!/usr/bin/env python3
import json,os,sys
if os.environ.get('SHELL_SESSIONS_DISABLE') != '1': print('Restored session: synthetic terminal')
print(json.dumps({'stdin':sys.stdin.read(),'args':sys.argv[1:]}))
''')
            fake.chmod(0o755)
            env = {**os.environ, 'PATH':tmp + os.pathsep + os.environ['PATH'],
                   'SHELL_SESSIONS_DISABLE':'0', 'BOAT_CMD':str(fake)}
            p = subprocess.run([str(CALL), '--stdin', 'ssh', 'fake', 'cat'],
                               env=env, input='synthetic input\n',capture_output=True,text=True,timeout=5)
            self.assertEqual(p.returncode, 0, p.stderr)
            data=json.loads(p.stdout)
            self.assertEqual(data['stdin'], 'synthetic input\n')
            self.assertEqual(data['args'][-3:], ['ssh','fake','cat'])


if __name__ == '__main__': unittest.main()
