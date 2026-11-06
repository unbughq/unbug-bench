#!/usr/bin/env python3
"""Offline: creation timeout is local; short TTL reserves time without instant retirement."""

import sys
from pathlib import Path as _Path

_BENCH_ROOT = _Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_BENCH_ROOT / "bin"))

import os
from pathlib import Path
import shutil
import subprocess
import tempfile

with tempfile.TemporaryDirectory() as temp:
    root = Path(temp)
    (root / 'bin').mkdir()
    (root / 'factory').mkdir()
    shutil.copy(_BENCH_ROOT / 'factory/boat_lifecycle.py', root / 'factory/boat_lifecycle.py')
    (root / 'results/spend').mkdir(parents=True)
    shutil.copy((_BENCH_ROOT / "bin" / 'exam-launch-guards.sh'), root / 'bin/exam-launch-guards.sh')
    for name, code in {
        'boat-spend': '#!/bin/sh\necho 30\n',
        'boat-call': '#!/bin/sh\necho "$BOAT_COMMAND_TIMEOUT_SECONDS" > "$TEST_ROOT/timeout"\necho \'{"event":"created","id":"vm-synthetic"}\'\n',
    }.items():
        path = root / 'bin' / name
        path.write_text(code)
        path.chmod(0o755)
    script = '''set -eu
root=$TEST_ROOT; n=1; label=factory; ttl_hours=0.01; max_spend=1
. "$root/bin/exam-launch-guards.sh"
guard_init
trap - 0 INT TERM
[ "$margin" -gt 0 ] && [ "$margin" -lt "$ttl_seconds" ] && [ "$retire_at" -gt 0 ]
guard_new
[ "$BOAT_COMMAND_TIMEOUT_SECONDS" = 7 ]
rm -rf "$state"
'''
    env = {**os.environ, 'TEST_ROOT': str(root), 'BOAT_CMD': str(root / 'bin/boat-call'),
           'BOAT_COMMAND_TIMEOUT_SECONDS': '7', 'BOAT_NEW_TIMEOUT_SECONDS': '300'}
    for margin in ('1800', '1', '29'):
        result = subprocess.run(['/bin/sh', '-c', script], env={**env, 'BOAT_TTL_MARGIN_SECONDS': margin},
                                capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, result.stderr
        assert (root / 'timeout').read_text().strip() == '300'
    for margin in ('0', '-1', 'NaN', '1.5'):
        result = subprocess.run(['/bin/sh', '-c', script], env={**env, 'BOAT_TTL_MARGIN_SECONDS': margin},
                                capture_output=True, text=True, timeout=10)
        assert result.returncode != 0, margin
print('PASS short TTL margin, invalid margin rejection, isolated creation timeout')
