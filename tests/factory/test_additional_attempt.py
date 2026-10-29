#!/usr/bin/env python3
"""Offline synthetic fixtures only; never connects to the real holder/cloud."""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import concurrent.futures
import copy
import hashlib
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time

SOURCE = (pathlib.Path(__file__).resolve().parents[2] / "factory" / 'key_holder.py')


def refused(call):
    try:
        call()
    except ValueError:
        return
    raise AssertionError('unsafe additional attempt accepted')


def main():
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp).resolve()
        for name in ('factory', 'bin', 'sealed'):
            (root/name).mkdir()
        script = root/'factory/key_holder.py'
        shutil.copyfile(SOURCE, script)
        for name in ('recovery.py', 'control_resume.py', 'account_handoff.py', 'launch_manifest.py'):
            shutil.copyfile(SOURCE.with_name(name), root/'factory'/name)
        spec = importlib.util.spec_from_file_location('synthetic_holder', script)
        holder = importlib.util.module_from_spec(spec); spec.loader.exec_module(holder)
        holder.RUNTIME = root/'runtime'; holder.SOCKET = holder.RUNTIME/'control.sock'
        case = 'case-synthetic'
        archive = root/'sealed'/f'{case}.checkpoint.tar.gz.age'
        archive.write_bytes(b'synthetic ciphertext only')
        generation = hashlib.sha256(archive.read_bytes()).hexdigest()
        card = {'case': case, 'sha256': generation, 'seed': 42,
                'recovery_config': {'version': 1}, 'status': 'stopped', 'terminal_stop': 'process_error',
                'roles': {'writer': {'family': 'synthetic', 'model': 'synthetic/test', 'effort': 'high'}},
                'continuation_budget': {'calls': 432, 'cost': .787819661, 'events': [{'synthetic': True}]}}
        card_path = root/'sealed'/f'{case}.scorecard.json'
        card_path.write_text(json.dumps(card))
        base = {'case': case, 'mode': 'case', 'card': card_path.name, 'archive_prefix': case,
                'roles': card['roles'], 'max_calls': 2000, 'max_cost': 5,
                'args': ['1', '--restore', case, '--max-cost', '5', '--max-total-calls', '2000']}
        auth = {'case': case, 'generation': generation,
                'recovery_conditions_sha256': holder.recovery_conditions_digest(card),
                'reason': 'Synthetic explicit approval for one infrastructure retry'}
        job = {**base, 'additional_attempt': auth}
        rows = [{'case': case, 'job': 'fixture', 'generation': generation, 'at': n,
                 'completed_ok': False, 'budget_calls': 432, 'budget_cost': .787819661,
                 'infrastructure_spend': .0015} for n in range(3)]
        original_rows = copy.deepcopy(rows); original_card = card_path.read_bytes()
        req = {'additional_attempt_generation': generation}
        for n in range(3):
            assert holder.admit_attempt(base, generation, {}, rows[:n], n) is None
        for n in (3, 4):
            refused(lambda: holder.admit_attempt(base, generation, {}, rows, n))
        refused(lambda: holder.admit_attempt(base, generation, req, rows, 2))
        refused(lambda: holder.admit_attempt({**base, 'max_attempts': 4}, generation, {}, rows, 3))
        used = rows + [{**rows[0], 'job': 'renamed', 'additional_attempt': auth}]
        refused(lambda: holder.admit_attempt(job, generation, req, used, 3))
        refused(lambda: holder.admit_attempt(job, generation, req, used, 4))
        fifth_auth = {**auth, 'prior_attempts_sha256': hashlib.sha256(json.dumps(used, sort_keys=True).encode()).hexdigest()}
        fifth_job = {**base, 'additional_attempt': fifth_auth}
        assert holder.admit_attempt(fifth_job, generation, req, used, 4) == fifth_auth
        refused(lambda: holder.admit_attempt(fifth_job, generation, req, used, 3))
        refused(lambda: holder.admit_attempt(fifth_job, generation, req, used + [used[-1]], 5))
        altered = copy.deepcopy(used); altered[0]['budget_calls'] = 0
        refused(lambda: holder.admit_attempt(fifth_job, generation, req, altered, 4))
        for bad in (None, {}, {**auth, 'case': 'case-other'}, {**auth, 'generation': 'bad'},
                    {**auth, 'reason': ''}, {**auth, 'max_attempts': 5}):
            refused(lambda: holder.additional_attempt_policy_check({**base, 'additional_attempt': bad}))
        refused(lambda: holder.additional_attempt_policy_check({**job, 'mode': 'any'}))
        for change in ({}, {'additional_attempt_generation': '0'*64}):
            refused(lambda: holder.admit_attempt(job, generation, change, rows, 3))
        refused(lambda: holder.admit_attempt(job, '0'*64, req, rows, 3))
        refused(lambda: holder.admit_attempt({**job, 'case': 'case-other'}, generation, req, rows, 3))
        refused(lambda: holder.admit_attempt(job, generation, req, rows[:2], 3))
        refused(lambda: holder.admit_attempt(job, generation, req, rows, 0))  # cutoff cannot hide history
        assert holder.admit_attempt(job, generation, req, rows, 3) == auth
        for changed in ({**card, 'sha256': '0'*64},
                        {**card, 'continuation_budget': {**card['continuation_budget'], 'calls': 0}},
                        {**card, 'continuation_budget': {**card['continuation_budget'], 'cost': 0}}):
            card_path.write_text(json.dumps(changed))
            refused(lambda: holder.admit_attempt(job, generation, req, rows, 3))
        card_path.write_bytes(original_card)
        assert rows == original_rows
        assert holder.current_generation(job) == generation
        # Exercise the actual single-owner, serialized request loop with three retained rows.
        launcher = root/'factory/launch.sh'
        launcher.write_text('#!/bin/sh\ncat >/dev/null\nprintf started >> starts.txt\n')
        boat = root/'bin/boat-call'
        boat.write_text("#!/bin/sh\nprintf '%s\\n' '{\"sandboxes\":[],\"pageInfo\":{\"hasMore\":false}}'\n")
        boat.chmod(0o755)
        identity = root/'identity'
        subprocess.run(['age-keygen', '-o', str(identity)], check=True, capture_output=True)
        key = next(s for s in identity.read_bytes().splitlines() if s.startswith(b'AGE-SECRET-KEY-')) + b'\n'
        recipient = subprocess.check_output(['age-keygen', '-y', str(identity)], text=True).strip()
        policy = {'root': str(root), 'code_sha256': holder.fingerprint(root), 'recipient': recipient,
                  'path': os.environ['PATH'], 'retry_failed_launches': True, 'jobs': {'fixture': job}}
        policy_path = root/'policy.json'; policy_path.write_text(json.dumps(policy))
        assert holder.policy_load(policy_path) == policy
        holder.RUNTIME.mkdir(mode=0o700)
        journal = holder.RUNTIME/'reservations.json'; journal.write_text(json.dumps(rows))
        code = ('import pathlib,runpy,sys; sys.path.insert(0,'+repr(str(script.parent))+'); m=runpy.run_path('+repr(str(script))+'); '
                'g=m["serve"].__globals__; g["RUNTIME"]=pathlib.Path('+repr(str(holder.RUNTIME))+'); '
                'g["SOCKET"]=g["RUNTIME"] / "control.sock"; m["serve"](pathlib.Path('+repr(str(policy_path))+'), .02)')
        def start():
            p = subprocess.Popen([sys.executable, '-c', code], stdin=subprocess.PIPE, stderr=subprocess.PIPE)
            p.stdin.write(key); p.stdin.close()
            for _ in range(100):
                if p.poll() is not None: raise AssertionError(p.stderr.read().decode())
                try:
                    if holder.request({'op': 'status'}).get('unlocked'): return p
                except (OSError, ValueError): pass
                time.sleep(.03)
            p.terminate(); p.wait(timeout=5)
            raise AssertionError('synthetic holder not ready')
        p = start()
        try:
            assert 'error' in holder.request({'op': 'launch', 'job': 'fixture'})
            assert json.loads(journal.read_text()) == rows
            launch = {'op': 'launch', 'job': 'fixture', **req}
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                replies = list(pool.map(lambda _: holder.request(launch), range(2)))
            assert sum(r.get('started', False) for r in replies) == 1, replies
            recorded = json.loads(journal.read_text())
            assert len(recorded) == 4 and recorded[:3] == original_rows
            assert recorded[3]['additional_attempt'] == auth
            assert recorded[3]['budget_calls'] == 432 and recorded[3]['budget_cost'] == .787819661
            assert card_path.read_bytes() == original_card and job['max_calls'] == 2000 and job['max_cost'] == 5
            assert 'error' in holder.request(launch)
            holder.request({'op': 'stop'}); p.wait(timeout=5)
            p = start()  # no fifth, even after process/holder restart
            assert 'error' in holder.request(launch)
            assert len(json.loads(journal.read_text())) == 4
            assert (root/'starts.txt').read_text() == 'started'
            # A separately reviewed policy may authorize exactly one fifth start.
            holder.request({'op': 'stop'}); p.wait(timeout=5)
            four = json.loads(journal.read_text())
            fifth_auth = {**auth, 'prior_attempts_sha256': hashlib.sha256(json.dumps(four, sort_keys=True).encode()).hexdigest()}
            policy['jobs']['fixture']['additional_attempt'] = fifth_auth
            policy_path.write_text(json.dumps(policy))
            p = start()
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                replies = list(pool.map(lambda _: holder.request(launch), range(2)))
            assert sum(r.get('started', False) for r in replies) == 1, replies
            five = json.loads(journal.read_text())
            assert len(five) == 5 and five[:4] == four
            assert five[4]['additional_attempt'] == fifth_auth
            assert five[4]['budget_calls'] == 432 and five[4]['budget_cost'] == .787819661
            holder.request({'op': 'stop'}); p.wait(timeout=5)
            p = start()
            assert 'error' in holder.request(launch)  # no sixth, even after restart
            assert len(json.loads(journal.read_text())) == 5
            assert card_path.read_bytes() == original_card
        finally:
            if p.poll() is None: p.terminate(); p.wait(timeout=5)
        print('PASS default cap3, strict scoped authorization, exact generation/conditions, retained history/budgets, concurrent fourth and durable fifth refusal without new approval, explicitly approved fifth and durable sixth refusal; synthetic only')


if __name__ == '__main__': main()
