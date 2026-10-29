"""G11 after a kept G10 (resume after a G11 failure): the saved solved tries are checked, not none (2026-10-19)."""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import json, pathlib, sys, tempfile, types
from unittest import mock
sys.path.insert(0, str((pathlib.Path(__file__).resolve().parents[2] / "factory"))); import run
w = pathlib.Path(tempfile.mkdtemp()); (w / 'strong_calibrator').mkdir(); (w / 'easy_calibrator').mkdir()
(w / 'strong_calibrator/results.json').write_text(json.dumps([{'try': 1, 'solved': True, 'guard': '/g/s1'}, {'try': 2, 'solved': False}]))
(w / 'easy_calibrator/results.json').write_text(json.dumps([{'try': 1, 'solved': True, 'guard': '/g/e1'}]))
c = types.SimpleNamespace(work=w, case=w/'case', card={}, seed=1, pilot_passes=[], args=types.SimpleNamespace(dry_run=False, bench_workers=1))  # [] as left by the early probe
seen = {}
def stop(c, cmd, **k): seen['guards'] = [str(g) for g in cmd[1:3]]; raise SystemExit
with mock.patch.object(run, 'sh', stop):
    try: run.g11(c)
    except SystemExit: pass
assert seen['guards'] == ['/g/s1', '/g/e1'], seen
print('PASS G11 checks the solved tries of a kept G10')
