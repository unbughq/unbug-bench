#!/usr/bin/env python3
"""Offline check: interactive shell session chatter must not corrupt Boat output."""

import sys
from pathlib import Path as _Path

_BENCH_ROOT = _Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_BENCH_ROOT / "bin"))

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

CALL = (_BENCH_ROOT / "bin" / 'boat-call')


class BoatCallTests(unittest.TestCase):
    def test_shell_sessions_disabled_and_stdin_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / 'zsh'
            fake.write_text('''#!/usr/bin/env python3
import json,os,sys
if os.environ.get('SHELL_SESSIONS_DISABLE') != '1': print('Restored session: synthetic terminal')
print(json.dumps({'stdin':sys.stdin.read(),'args':sys.argv[1:]}))
''')
            fake.chmod(0o755)
            env = {**os.environ, 'PATH':tmp + os.pathsep + os.environ['PATH'],
                   'SHELL_SESSIONS_DISABLE':'0'}
            env.pop('BOAT_CMD', None)
            p = subprocess.run([str(CALL), '--stdin', 'ssh', 'fake', 'cat'],
                               env=env, input='synthetic input\n',capture_output=True,text=True,timeout=5)
            self.assertEqual(p.returncode, 0, p.stderr)
            data=json.loads(p.stdout)
            self.assertEqual(data['stdin'], 'synthetic input\n')
            self.assertEqual(data['args'][-3:], ['ssh','fake','cat'])


if __name__ == '__main__': unittest.main()
