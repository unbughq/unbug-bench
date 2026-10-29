#!/usr/bin/env python3
"""Offline round check: python3 tests/bench/test-exam-round.py. Fakes only; no cloud or models."""

import sys
from pathlib import Path as _Path

_BENCH_ROOT = _Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_BENCH_ROOT / "bin"))

import hashlib
import contextlib
import sys
import importlib.util
import importlib.machinery
from unittest.mock import patch
from types import SimpleNamespace
import threading
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import time

ROOT = _BENCH_ROOT
FAKE = r'''#!/usr/bin/env python3
import datetime, hashlib, json, os, pathlib, sys, time
assert sys.stdin.buffer.read() == b'FAKE AGE IDENTITY\n'
args = sys.argv[1:]
account = os.environ['EXAM_CLAUDE_SECRET']
assert os.environ['EXAM_SECRETS'].split()[0] == account
assert os.environ['HCLOUD_PLACES'] == 'cx33@nbg1 cx33@fsn1 cx33@hel1'
assert os.environ['UNBUG_CLOUD'] == 'hetzner'
assert not any('FAKE AGE IDENTITY' in v for v in args + list(os.environ.values()))
case = pathlib.Path(args[0]).name.removesuffix('.tar.gz.age')
dest = pathlib.Path(os.environ['EXAM_RESULTS_DIR'])
pathlib.Path(os.environ['EXAM_STATUS_FILE']).write_text(case)
now = time.time()
with open(os.environ['CALLS'], 'a') as f:
    f.write(json.dumps({'case':case, 'account':account, 'at':now,
                       'trials':[args[i+1] for i,v in enumerate(args) if v == '--trial']})+'\n')
# Force a live-meter poll while the fake VM is running.
time.sleep(.18)
trials = []
for i,v in enumerate(args):
    if v != '--trial': continue
    arm, number = args[i+1].split(':')
    failed = os.environ.get('MODE') == 'limits'
    meter = {'timestamp':datetime.datetime.now(datetime.timezone.utc).isoformat(),
             'http_status':429 if failed else 200, 'status':'rejected' if failed else 'allowed',
             '5h-utilization':'.99' if failed else '.1', '5h-reset': time.time()+.25}
    trials.append({'arm':arm, 'try':int(number), 'meter':meter,
                   'infrastructure_failure':'claude_usage_limit' if failed else None})
    if failed: break
raw = dest / 'fake.jobs.tar.gz.age'; raw.write_bytes(b'FAKE SEALED JOBS')
card = {'case':case, 'case_sha256_matches':True, 'trials':trials,
        'raw_archive':raw.name, 'raw_archive_sha256':hashlib.sha256(raw.read_bytes()).hexdigest()}
(dest / 'fake.scorecard.json').write_text(json.dumps(card))
'''
BOAT = r'''#!/usr/bin/env python3
import datetime, json, os, pathlib, sys, time
if sys.argv[1] == 'list':
    print(json.dumps({'sandboxes': [{'id':'c1'}] if os.environ.get('ORPHAN') else []}))
    sys.exit(0)
assert sys.argv[1] == 'ssh'
with open(os.environ['BOAT_CALLS'], 'a') as f: f.write(json.dumps(sys.argv[1:])+'\n')
# Case 1 reports its meter while live. Other account remains available.
if os.environ.get('MODE') == 'pacing' and sys.argv[2] == 'c1':
    until = float(os.environ['RESET'])
    print(json.dumps({'timestamp':datetime.datetime.now(datetime.timezone.utc).isoformat(),
                     'status':'allowed', 'http_status':200, '5h-utilization':'.85',
                     '5h-reset':until}))
else: print('{}')
'''


def check_vm_trial(root):
    """Exercise the real run-exam control flow with fake Harbor/build/age operations."""
    exam = importlib.machinery.SourceFileLoader('round_run_exam', str(ROOT / 'bin/run-exam')).load_module()
    archive = root / 'vm.tar.gz.age'; archive.write_bytes(b'FAKE ENCRYPTED CASE')
    sys.path.insert(0, str(ROOT / 'factory'))
    import sealed_audit, exam_responder
    reviewer = {'model': 'synthetic/reviewer', 'effort': 'default'}
    source_card = {'case': 'vm', 'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
                   'gates': {f'G{i}': 'pass' for i in range(1, 18)},
                   'roles': {'reviewer': reviewer},
                   'owner_contract': exam_responder.contract(ROOT, reviewer),
                   'delivery_provenance': {'contract': sealed_audit.delivery_contract(), 'sha256': '0' * 64}}
    archive.with_name('vm.scorecard.json').write_text(json.dumps(source_card))
    private, out = root / 'private', root / 'out'
    calls = []

    def fake_run(cmd, **kwargs):
        if isinstance(cmd, str) and 'age -d' in cmd:
            task = next(private.glob('*')) / 'vm/case/harbor/task'
            task.mkdir(parents=True)
            (task / 'task.toml').write_text('')
        elif isinstance(cmd, str) and ' | age ' in cmd:
            (out / (next(private.iterdir()).name + '.jobs.tar.gz.age')).write_bytes(b'FAKE SEALED JOBS')
        else:
            raise AssertionError(cmd)
        return SimpleNamespace(returncode=0)

    def fake_sh(cmd, log, **kwargs):
        if 'run-audited.py' in ' '.join(cmd):
            calls.append(cmd)
            name = cmd[cmd.index('--job-name')+1]
            trial = pathlib.Path(cmd[cmd.index('--jobs-dir')+1]) / name / 'trial'
            trial.mkdir(parents=True)
            (trial / 'result.json').write_text('{}')
            (trial / 'claude-meter.jsonl').write_text(json.dumps({'timestamp':'2026-01-01T00:00:00Z',
                'http_status':429, 'status':'allowed', 'retry-after':'10'})+'\n')
        return 0

    # This test covers trial selection and metering. Receipt authentication and real
    # owner setup have dedicated tests; stand in for their successful boundaries.
    admitted = []
    def verify(card, case_id, *, restored_work, archive):
        sealed_audit.verify_exam_metadata(card, case_id)
        assert hashlib.sha256(archive.read_bytes()).hexdigest() == card['sha256']
        assert (restored_work / 'case/harbor/task/task.toml').is_file()
        admitted.append(restored_work)
        return card

    def owner_context(case, card, logs, args):
        assert admitted == [case.parent]
        work = logs / 'owner'; work.mkdir()
        return SimpleNamespace(), SimpleNamespace(work=work, ledger=work / 'budget.json')

    argv = ['run-exam', str(archive), '--identity', str(root/'fake-key'), '--arm','A','--arm','B',
            '--tries','2','--trial','A:2','--trial','B:1','--private',str(private),'--out',str(out)]
    with patch.object(exam.sys, 'argv', argv), patch.object(exam.sys, 'platform', 'linux'), \
         patch.object(exam, 'sh', fake_sh), patch.object(exam, 'prepare', return_value={'cpus':None}), \
         patch.object(sealed_audit, 'verify_exam', verify), \
         patch.object(exam, 'owner_context', owner_context), \
         patch.object(exam_responder, 'docker_owner_server', side_effect=lambda *args: contextlib.nullcontext({})), \
         patch.object(exam, 'shred'), patch.object(exam.subprocess, 'run', fake_run), \
         patch.object(exam.shutil, 'which', return_value='/fake/harbor'):
        exam.main()
    assert len(calls) == 1 and calls[0][calls[0].index('-k')+1] == '1'
    card = json.loads(next(out.glob('*.scorecard.json')).read_text())
    assert not card.get('error'), card
    trial = card['trials'][0]
    assert trial['arm'] == 'A' and trial['try'] == 2
    assert trial['infrastructure_failure'] == 'claude_usage_limit' and trial['steps'] == []
    assert trial['human_minutes'] is None and not trial['meter'].get('_unknown_reset')
    # Real relay metering preserves both HTTP 429 and unified status, plus Retry-After.
    relay_spec = importlib.util.spec_from_file_location('round_keyswap', ROOT/'harbor/keyswap/keyswap.py')
    relay = importlib.util.module_from_spec(relay_spec); relay_spec.loader.exec_module(relay)
    fake = SimpleNamespace(log_file=str(root/'web.jsonl'), log_lock=threading.Lock())
    response = SimpleNamespace(status=429, getheader=lambda k:'10' if k == 'retry-after' else None,
        getheaders=lambda:[('anthropic-ratelimit-unified-status','allowed')])
    relay.Relay.meter(fake, response)
    row = json.loads((root/'claude-meter.jsonl').read_text())
    assert row['http_status'] == 429 and row['status'] == 'allowed' and row['retry-after'] == '10'


def main():
    with tempfile.TemporaryDirectory(prefix='exam-round-test-') as temporary:
        root = pathlib.Path(temporary)
        check_vm_trial(root)
        bench = root / 'bench'
        (bench / 'bin').mkdir(parents=True)
        for name in ('exam-round', 'exam_meter.py', 'boat-call', 'processes.py'):
            shutil.copy2(ROOT / 'bin' / name, bench / 'bin' / name)
        fake, boat = root / 'fake-exam', root / 'fake-boat'
        for path, content in ((fake, FAKE), (boat, BOAT)):
            path.write_text(content); path.chmod(0o755)
        cases = []
        for n in range(1, 5):
            archive = root / f'c{n}.tar.gz.age'; archive.write_bytes(b'FAKE SEALED CASE')
            archive.with_name(f'c{n}.scorecard.json').write_text('{}')
            cases.append({'archive': archive.name})
        spec = {'accounts':['claude-token', 'claude-token-2'], 'arms':['A', 'B'], 'tries':2, 'cases':cases}
        round_file = root / 'round.json'; round_file.write_text(json.dumps(spec))
        calls, boat_calls = root / 'calls', root / 'boat-calls'
        env = dict(os.environ, EXAM_LAUNCH_CMD=str(fake), BOAT_CMD=str(boat), CALLS=str(calls),
                   BOAT_CALLS=str(boat_calls), MODE='pacing', RESET=str(time.time()+.9))
        command = [str(bench / 'bin/exam-round'), str(round_file), '--parallel','2', '--poll-seconds','.03']
        def run(expected=0):
            result = subprocess.run(command, input=b'FAKE AGE IDENTITY\n', capture_output=True, env=env, timeout=10)
            assert result.returncode == expected, (result.stdout, result.stderr)
            assert b'FAKE AGE IDENTITY' not in result.stdout + result.stderr
            return result
        run()
        manifest_path = bench / 'results/exam-round/round/manifest.json'
        state = json.loads(manifest_path.read_text())
        assert [c['account'] for c in state['cases']] == ['claude-token','claude-token-2'] * 2
        assert all(r['status'] == 'collected' for c in state['cases'] for r in c['trials'].values())
        started = [json.loads(line) for line in calls.read_text().splitlines()]
        assert len(started) == 4
        c3 = next(c for c in started if c['case'] == 'c3')
        assert c3['at'] >= float(env['RESET']), (started, env['RESET'])
        assert boat_calls.read_text(), 'live meter not polled'
        original = calls.read_text()
        run()
        assert calls.read_text() == original, 'resume repeated finished work'
        assert [c['account'] for c in json.loads(manifest_path.read_text())['cases']] == [c['account'] for c in state['cases']]
        # The full assignment exists before the very first launcher is started.
        fake.write_text(FAKE.replace("assert sys.stdin.buffer.read()", "assert json.loads(pathlib.Path(os.environ['MANIFEST']).read_text())['cases'][0]['account'] == 'claude-token'\nassert sys.stdin.buffer.read()"))
        one = root / 'limits.json'
        one.write_text(json.dumps({'arms':['A'], 'tries':1, 'cases':cases[:1]}))
        command[1] = str(one)
        limit_manifest = bench / 'results/exam-round/limits/manifest.json'
        env.update(MODE='limits', MANIFEST=str(limit_manifest))
        before = len(started)
        run(1)
        state = json.loads(limit_manifest.read_text())
        trial = state['cases'][0]['trials']['A:1']
        assert trial['status'] == 'missing' and trial['limit_failures'] == 3
        assert len(trial['attempts']) == 3 and all(a['outcome'] == 'claude_usage_limit' for a in trial['attempts'])
        starts = [json.loads(line) for line in calls.read_text().splitlines()][before:]
        assert len(starts) == 3 and all(c['account'] == 'claude-token' and c['trials'] == ['A:1'] for c in starts)
        assert all(b['at'] - a['at'] >= .4 for a,b in zip(starts, starts[1:])), starts
        run(1)
        assert len(calls.read_text().splitlines()) == before + 3, 'missing trial restarted'
        env['ORPHAN'] = '1'
        result = subprocess.run(command, input=b'FAKE AGE IDENTITY\n', capture_output=True, env=env, timeout=5)
        assert result.returncode != 0 and b'still exists' in result.stderr
        env.pop('ORPHAN')
        # Reject a changed frozen round rather than repinning accounts.
        spec['accounts'] = ['claude-token']; round_file.write_text(json.dumps(spec)); command[1] = str(round_file)
        run(2)
        # Pure meter checks exercise weekly cutoff, missing resets, header status collision and stale rows.
        mod_spec = importlib.util.spec_from_file_location('meter', ROOT / 'bin/exam_meter.py')
        meter = importlib.util.module_from_spec(mod_spec); mod_spec.loader.exec_module(meter)
        assert meter.limited({'http_status':429, 'status':'allowed'})
        assert meter.limited({'http_status':200, 'status':'rejected'})
        m = meter.merge({}, [{'timestamp':'2026-01-02', '7d-utilization':'.95', '7d-reset':100}])
        assert not meter.ready(m, 99) and meter.ready(m, 101)
        meter.merge(m, [{'timestamp':'2026-01-01', '7d-utilization':'0'}])
        assert m['7d-utilization'] == '.95'
        assert not meter.ready(meter.merge({}, [{'status':429}]))
        m = meter.merge({}, [{'timestamp':'2026-01-01', 'status':429}])
        meter.merge(m, [{'timestamp':'2026-01-02', 'status':'allowed', '5h-utilization':'.9', '5h-reset':100}])
        assert meter.ready(m, 101), m
        m = meter.merge({}, [{'5h-utilization':'.9', '7d-utilization':'.99', '7d-reset':100}])
        assert not meter.ready(m, 101), m
        m = meter.merge({}, [{'timestamp':'1970-01-01T00:00:00+00:00', 'http_status':429, 'retry-after':'100'}])
        assert not meter.ready(m, 99) and meter.ready(m, 101), m
        m = meter.merge({}, [{'timestamp':'1970-01-01T00:01:40+00:00', 'http_status':429,
                              '5h-utilization':'.9', '5h-reset':110, 'retry-after':'60'}])
        assert not meter.ready(m, 120) and meter.ready(m, 161), m
        # Meter rows contain only the explicit metadata allowlist.
        logs = root / 'logs'; logs.mkdir()
        (logs / 'claude-meter.jsonl').write_text('{"status":429,"body":"SEALED"}\npartial')
        assert meter.rows_under(logs) == [{'status':429}]
        assert all(b'FAKE AGE IDENTITY' not in p.read_bytes() for p in (bench / 'results').rglob('*') if p.is_file())
    print('PASS stable prelaunch pinning, resume, live-meter pacing, weekly/missing resets, 429 + two reruns -> missing; fakes only')


if __name__ == '__main__':
    main()
