"""Hetzner-only final practice run; no model calls. Launch detached.

python3 harbor/probes/run-phase2-practice.py [--native-only|--oracle-only]
Results and logs stay in /tmp/phase2-final-r2 for hcloud-dev pull.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
OUT = Path('/tmp/phase2-final-r2')
assert sys.platform == 'linux', 'Run through HCLOUD_DEV=phase2 bin/hcloud-dev'
OUT.mkdir(exist_ok=True)
os.chdir(ROOT)
os.environ['UNBUG_JUDGE'] = '1'
os.environ['BENCH'] = str(ROOT)
os.environ['MEDUSA_DEPS_IMAGE'] = 'unbug-bench-medusa-deps:' + hashlib.sha256(
    (ROOT / 'projects/medusa/package-lock.json').read_bytes()).hexdigest()
status = {}


def run(name, arguments):
    start = time.monotonic()
    with (OUT / (name + '.log')).open('w') as log:
        code = subprocess.call(arguments, stdout=log, stderr=subprocess.STDOUT)
    status[name] = {'exit_code': code, 'seconds': round(time.monotonic() - start, 3)}
    (OUT / 'status.json').write_text(json.dumps(status, indent=2) + '\n')
    print(name, status[name], flush=True)
    if code:
        raise SystemExit(code)


if '--native-only' not in sys.argv:
    run('build', ['bash', 'harbor/medusa-oversell-v2/build.sh'])
    test_dirs = ('tests/harbor/medusa-oversell-v2', 'tests/live/harbor/medusa-oversell-v2')
    for test in sorted(p for directory in test_dirs for p in (ROOT / directory).glob('test-*.py')):
        run(test.stem, [sys.executable, str(test)])
    run('oracle', [sys.executable, 'harbor/run-audited.py', '--agent', 'oracle',
        '--job-name', 'phase2-final-oracle-r2', '--task', 'harbor/medusa-oversell-v2',
        '--jobs-dir', str(OUT / 'jobs'), '--', '--ve', 'UNBUG_RUNS=1', '-n', '1'])
    trials = list((OUT / 'jobs/phase2-final-oracle-r2').glob('*/result.json'))
    assert len(trials) == 1, trials
    trial = json.loads(trials[0].read_text())
    assert not trial['exception_info'], trial['exception_info']
    assert len(trial['step_results']) == 7
    for step in trial['step_results']:
        assert not step['exception_info'], step
        assert step['verifier_result']['rewards']['reward'] == 1, step
    quiet = trial['step_results'][-1]
    assert quiet['agent_result'] is None and quiet['agent_execution'] is None
    checkpoint = json.loads((trials[0].parent / 'steps/quiet/verifier/checkpoint.json').read_text())
    assert checkpoint['exposure']['valid'] and not checkpoint['error_runs']
if '--oracle-only' in sys.argv:
    raise SystemExit(0)
run('native-clean', ['docker', 'compose', '-f', 'projects/medusa/compose.yaml', 'down', '-v', '--remove-orphans'])
run('native-setup', ['bin/setup', '--scenario', str(ROOT / 'cases/medusa-oversell-v2/base')])
names = ['honest-reference', 'frozen-first-fix', 'claim-without-evidence', 'ask-everything', 'block-all-pending']
for name in names:
    run(name, [sys.executable, 'bin/strategy', '--case', str(ROOT / 'cases/medusa-oversell-v2'),
               '--strategy', name, '--runs', '1', '--seed', '1'])
run('read-only-probes', [sys.executable, 'tests/live/harbor/probes/test_live_reads.py'])
run('G14', [sys.executable, 'harbor/medusa-oversell-v2/verify.py', '--gates', 'G14',
            '--runs', '1', '--out', str(OUT / 'gates')])

# Reuse the five actual runs above, rather than replaying them for G13/G15.
sys.path.insert(0, str(ROOT / 'factory'))
spec = importlib.util.spec_from_file_location('phase2_factory', ROOT / 'factory/run.py')
factory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(factory)
context = SimpleNamespace(case=ROOT / 'cases/medusa-oversell-v2', work=OUT / 'gates',
    args=SimpleNamespace(dry_run=False, source='fixture', scenario_runs=1), seed=1, card={},
    strategies={name: json.loads((OUT / (name + '.log')).read_text()) for name in names})
context.manifest0 = factory.bench_manifest()
gates = json.loads((OUT / 'gates/gates.json').read_text())
for name in ['G1', 'G13', 'G15']:
    ok, detail = getattr(factory, name.lower())(context)
    gates[name] = {'passed': bool(ok), **detail}
    print(name, gates[name], flush=True)
(OUT / 'gates/gates.json').write_text(json.dumps(gates, indent=2) + '\n')
if not all(value['passed'] for value in gates.values()):
    raise SystemExit('Factory gate failed')
(OUT / 'DONE').write_text(json.dumps(status, indent=2) + '\n')
