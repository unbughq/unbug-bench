#!/usr/bin/env python3
"""Synthetic identity and fake launcher only; no cloud or real secrets."""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
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


def economic_recovery_checks():
    """No identity, holder daemon, cloud call or real ciphertext is needed."""
    from unittest import mock
    spec = importlib.util.spec_from_file_location('economic_holder', SOURCE)
    holder = importlib.util.module_from_spec(spec); spec.loader.exec_module(holder)
    with tempfile.TemporaryDirectory() as temp, mock.patch.object(holder, 'ROOT', pathlib.Path(temp)):
        sealed = pathlib.Path(temp) / 'sealed'; sealed.mkdir()
        case = 'case-economic-fixture'
        archive = sealed / (case + '.checkpoint.tar.gz.age'); archive.write_bytes(b'synthetic ciphertext')
        card = {'case': case, 'status': 'stopped', 'failed_gate': None, 'gates': {},
                'terminal_stop': 'stress_review_unresolved:rounds_exhausted', 'roles': {},
                'recovery_config': {'rounds': 3}, 'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
                'continuation_budget': {'calls': 2, 'cost': .1, 'list_cost_usd': 30,
                                        'events': [], 'terminal_stop': 'complete'}}
        path = sealed / (case + '.scorecard.json')
        job = {'case': case, 'mode': 'case', 'card': path.name, 'archive_prefix': case,
               'roles': {}, 'max_calls': 10, 'max_cost': 5,
               'args': ['1', '--restore', case, '--case-budget', '50', '--rounds', '8']}
        def check(value, policy, accepted):
            path.write_text(json.dumps(value))
            try: result = holder.current_generation(policy)
            except ValueError:
                assert not accepted, 'raised economic recovery refused'
            else:
                assert accepted and result == card['sha256'], 'unsafe recovery accepted'
        check(card, job, True)
        check(card, {**job, 'args': ['1', '--restore', case]}, False)
        check(card, {**job, 'args': ['1', '--restore', case, '--case-budget=50', '--rounds=8']}, True)
        for stop in ('budget_exhausted', card['terminal_stop']):
            economic = {**card, 'terminal_stop': stop, 'case_budget': {'limit_usd': 30.1}}
            check(economic, job, True)
            check(economic, {**job, 'args': ['1', '--restore', case, '--case-budget', '30.1', '--rounds', '3']}, False)
        check({**card, 'failed_gate': 'G8', 'gates': {'G8': 'fail'}, 'failed_detail': {'findings': ['real failure']}}, job, False)
        missing = {**card, 'terminal_stop': 'stress_review_unresolved:missing_or_malformed_report',
                   'case_budget': {'limit_usd': 50}, 'recovery_config': {'rounds': 8, 'case_budget': 50},
                   'budget_raised': {'from': None, 'to': 50, 'spent_at_raise': 30},
                   'rounds_raised': {'from': 3, 'to': 8}}
        check(missing, job, True)
        check(missing, {**job, 'args': ['1', '--restore', case]}, True)
        check(missing, {**job, 'args': ['1', '--restore', case, '--case-budget', '40', '--rounds', '3']}, True)
        check({**missing, 'budget_raised': None, 'rounds_raised': None}, job, True)
        check({**missing, 'gates': {'G15': 'fail'}}, job, False)
        check({**missing, 'failed_gate': 'G15', 'failed_detail': {'findings': ['real failure']}}, job, False)
        freshness = {**card, 'terminal_stop': 'freshness_unresolved',
                     'loop_freshness': {'rows': 0, 'verdict_path': None, 'outcome': 'unresolved'}}
        unraised = {**job, 'args': ['1', '--restore', case]}
        check(freshness, unraised, True)
        for changes in ({'failed_gate': 'G2'}, {'gates': {'G2': 'fail'}},
                        {'loop_freshness': None}, {'loop_freshness': {'outcome': 'unresolved'}},
                        {'loop_freshness': {'rows': 2, 'verdict_path': 'g2-confirm-1/verdict.json',
                                            'outcome': 'unresolved', 'reason': 'reviewer_unresolved'}},
                        {'continuation_budget': {**card['continuation_budget'], 'list_cost_usd': 50}},
                        {'continuation_budget': {**card['continuation_budget'], 'terminal_stop': 'budget_exhausted'}}):
            check({**freshness, **changes}, unraised, False)
        check(freshness, {**unraised, 'mode': 'review'}, False)
        # Public eligibility is provisional: the restored worker authenticates
        # the encrypted attack receipt's binding before any attacker call.
        for stop in ('stress_review_unresolved:interrupted_review',
                     'stress_review_unresolved:missing_or_malformed_report',
                     'stress_review_unresolved:case_changed_since_review'):
            interrupted = {**card, 'terminal_stop': stop, 'case_budget': {'limit_usd': 50}}
            unraised = {**job, 'args': ['1', '--restore', case]}
            check(interrupted, unraised, True)
            for ledger_stop in ('stalled', 'timeout', 'provider_limit:opencode/test', 'budget_exhausted'):
                check({**interrupted, 'continuation_budget': {**card['continuation_budget'],
                      'terminal_stop': ledger_stop}}, unraised, ledger_stop != 'budget_exhausted')
            check({**interrupted, 'gates': {'G15': 'fail'}}, unraised, False)
            check({**interrupted, 'failed_gate': 'G15'}, unraised, False)
            check(interrupted, {**unraised, 'mode': 'review'}, False)
        check(card, {**job, 'mode': 'review'}, False)
        check(card, {**job, 'case': 'case-other'}, False)
        crash = {**card, 'terminal_stop': 'runner_error:RuntimeError', 'failed_gate': 'G15',
                 'gates': {'G15': 'fail'}, 'failed_detail': {'error': 'RuntimeError'}}
        check(crash, job, True)
        check({**crash, 'terminal_stop': 'unrelated_stop'}, job, False)
    print('PASS raised economic stop, unraised refusal, genuine gate refusal, crash eligibility and mode/case mismatch; offline only')


def main():
    economic_recovery_checks()
    # Exercise the same offline policy/lock scenarios with a founder identity too.
    import unittest
    from test_control_key_holder import ControlKeyHolderTests
    class FounderResumeTests(ControlKeyHolderTests):
        def start(self, identity=None):
            return super().start(identity or self.keys[0])
    suite = unittest.TestSuite(FounderResumeTests(name) for name in (
        'test_resume_live_controller_under_old_policy_is_skipped',
        'test_resume_orphan_under_changed_policy_is_refused',
        'test_resume_orphan_under_same_policy_is_resumed',
        'test_resume_refused_orphan_does_not_block_eligible_orphan'))
    assert unittest.TextTestRunner().run(suite).wasSuccessful(), 'founder resume regression'
    with tempfile.TemporaryDirectory() as temp:
        root = pathlib.Path(temp).resolve(); (root/'factory').mkdir(); (root/'bin').mkdir(); (root/'sealed').mkdir()
        script = root/'factory/key_holder.py'; shutil.copyfile(SOURCE, script)
        shutil.copyfile(SOURCE.with_name('control_resume.py'), root/'factory/control_resume.py')
        shutil.copyfile(SOURCE.with_name('recovery.py'), root/'factory/recovery.py')
        shutil.copyfile(SOURCE.with_name('account_handoff.py'), root/'factory/account_handoff.py')
        shutil.copyfile(SOURCE.with_name('launch_manifest.py'), root/'factory/launch_manifest.py')
        launcher = root/'factory/launch.sh'
        launcher.write_text('#!/bin/sh\nset -eu\nidentity=$(cat)\nprintf "%s" "$identity" | wc -c > proof.txt\nprintf "private fixture output\\n"\n')
        boat = root/"bin/boat-call"; boat.write_text('#!/bin/sh\ncat '+str(root/'fleet.json')+'\n'); boat.chmod(0o755)
        fleet=root/'fleet.json'; fleet.write_text(json.dumps({'sandboxes':[],'pageInfo':{'hasMore':False}}))
        identity = root/'synthetic-identity'
        subprocess.run(['age-keygen', '-o', str(identity)], check=True, capture_output=True)
        key = next(x for x in identity.read_bytes().splitlines() if x.startswith(b'AGE-SECRET-KEY-')) + b'\n'
        recipient = subprocess.check_output(['age-keygen', '-y', str(identity)], text=True).strip()
        spec = importlib.util.spec_from_file_location('fixture_holder', script); module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        case = 'case-synthetic'; archive = root/'sealed'/f'{case}.checkpoint.tar.gz.age'; archive.write_bytes(b'synthetic ciphertext')
        card = {'case':case, 'seed':42, 'recovery_config':{'version':1,'pilot_tries':3},
                'status':'stopped', 'terminal_stop':'codex_cli_not_0.162.1',
                'roles':{'strong_calibrator':{'model':'claude/synthetic','effort':'high','family':'anthropic'}},
                'continuation_budget':{'calls':2,'cost':.1,'events':[]}, 'sha256':hashlib.sha256(archive.read_bytes()).hexdigest()}
        (root/'sealed'/f'{case}.scorecard.json').write_text(json.dumps(card))
        policy = {'root':str(root), 'code_sha256':module.fingerprint(root), 'recipient':recipient, 'path':os.environ['PATH'], 'jobs':{'fixture':{'case':case,'mode':'case','card':f'{case}.scorecard.json','archive_prefix':case,'roles':card['roles'],'max_calls':10,'max_cost':1,'known_worker_ids':['bx_fixture'],'args':['1','--restore',case]}}}
        # An any-case job: the case id comes with the request (2026-10-19).
        case2='case-synthetic2'; a2=root/'sealed'/f'{case2}.checkpoint.tar.gz.age'; a2.write_bytes(b'second ciphertext')
        (root/'sealed'/f'{case2}.scorecard.json').write_text(json.dumps({**card,'case':case2,'source':'port','rotation_slot':1,'sha256':hashlib.sha256(a2.read_bytes()).hexdigest()}))
        policy['jobs']['repair']={'case':'any','mode':'any','variant':'repair','max_calls':10,'max_cost':1,'args':['--max-cost','1']}
        policy_path=root/'policy.json'; policy_path.write_text(json.dumps(policy))
        job=policy['jobs']['fixture']
        # VM-side factory code may change without a new unlock; pinned host code may not (2026-10-19).
        before=module.fingerprint(root); (root/'factory/run.py').write_text('changed vm-side code')
        assert module.fingerprint(root)==before, 'vm-side change must not need a new unlock'
        for helper in ('control_resume.py', 'statement_round.py', 'admission.py', 'calibration.py', 'launcher-sha256.json'):
            path = root / 'factory' / helper
            original = path.read_bytes() if path.exists() else None
            path.write_text('changed host admission helper')
            assert module.fingerprint(root) != before, f'host helper is not pinned: {helper}'
            if original is None: path.unlink()
            else: path.write_bytes(original)
            assert module.fingerprint(root) == before
        assert module.current_generation(job)==card['sha256']
        selected_final=root/'sealed'/f'{case}.tar.gz.age'; selected_final.write_bytes(b'newer unverified ciphertext')
        try: module.current_generation(job); raise AssertionError('must authenticate the selected archive, not any older archive')
        except ValueError: pass
        selected_final.unlink()
        card_path=root/'sealed'/f'{case}.scorecard.json'
        for changes in ({'active':[{'pending':True}]},{'cost':float('nan')},{'calls':-1},{'terminal_stop':'cost_limit'}):
            bad={**card,'continuation_budget':{**card['continuation_budget'],**changes}};card_path.write_text(json.dumps(bad))
            try: module.current_generation(job); raise AssertionError('unsafe cumulative budget accepted')
            except ValueError: pass
        card_path.write_text(json.dumps(card))
        audit={**card,'kind':'g11-independent-review','inputs_unchanged':True,'terminal_stop':'time_limit','limits':{'max_role_calls':51},'calls_delta':30,'continuation_budget':{**card['continuation_budget'],'terminal_stop':'timeout'}}
        selected_final.write_bytes(archive.read_bytes());card_path.write_text(json.dumps(audit))
        assert module.current_generation({**job,'mode':'review'})==card['sha256']
        audit['continuation_budget']['terminal_stop']='cost_limit';card_path.write_text(json.dumps(audit))
        try:module.current_generation({**job,'mode':'review'});raise AssertionError('must not clear a conflicting audit budget stop')
        except ValueError:pass
        selected_final.unlink();card_path.write_text(json.dumps(card))
        # Repairs: a listed failed gate may resume; any other failed gate may not (2026-10-19).
        failed={**card,'status':None,'terminal_stop':None,'failed_gate':'G8','continuation_budget':{**card['continuation_budget'],'terminal_stop':'complete'}}
        card_path.write_text(json.dumps(failed))
        assert module.current_generation({**job,'allow_failed_gates':['G8']})==card['sha256']
        try: module.current_generation({**job,'allow_failed_gates':['G5']}); raise AssertionError('unlisted failed gate resumed')
        except ValueError: pass
        card_path.write_text(json.dumps(card))
        # New-case jobs: one case on one rotation slot; recovery flags are refused.
        new_policy={**policy,'jobs':{'new-a':{'case':'new-slot5-port','mode':'new','args':['1','--source','port','--rotation-slot','5']}}}
        bad_policy={**policy,'jobs':{'new-b':{'case':'new-x','mode':'new','args':['1','--restore',case,'--source','port','--rotation-slot','5']}}}
        for pol, ok in ((new_policy, True), (bad_policy, False)):
            (root/'p2.json').write_text(json.dumps(pol))
            try: module.policy_load(root/'p2.json'); assert ok, 'bad new-case job accepted'
            except ValueError: assert not ok
        def start():
            p=subprocess.Popen([sys.executable,'-c','import pathlib,runpy,sys; sys.path.insert(0, '+repr(str(script.parent))+'); runpy.run_path('+repr(str(script))+')["serve"](pathlib.Path('+repr(str(policy_path))+'), .02)'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            p.stdin.write(key);p.stdin.close()
            for _ in range(100):
                if p.poll() is not None: raise AssertionError('synthetic holder failed: '+p.stderr.read().decode())
                try:
                    if module.request({'op':'status'}).get('unlocked'):return p
                except (OSError,ValueError):pass
                time.sleep(.05)
            raise AssertionError('holder not ready')
        # Existing daemon discovery and launch timeouts must never ask for the key again.
        original_request, original_stdin, original_argv = module.request, sys.stdin, sys.argv
        original_getpass=module.getpass.getpass
        class TTY:
            def isatty(self): return True
        def uncertain(req):
            if req['op']=='status': return {'unlocked':True,'policy_sha256':module.policy_digest(policy)}
            raise TimeoutError('uncertain synthetic launch')
        module.request=uncertain; sys.stdin=TTY();sys.argv=['key_holder','unlock','--policy',str(policy_path),'--start','fixture']
        module.getpass.getpass=lambda *_: (_ for _ in ()).throw(AssertionError('must not reprompt'))
        try:
            try:module.main();raise AssertionError('must surface uncertain start')
            except TimeoutError:pass
        finally:
            module.request=original_request;sys.stdin=original_stdin;sys.argv=original_argv;module.getpass.getpass=original_getpass
        p=start()
        try:
            assert module.RUNTIME.stat().st_mode & 0o077 == 0
            assert module.SOCKET.stat().st_mode & 0o777 == 0o600
            assert 'error' in module.request({'op':'export'})
            assert 'error' in module.request({'op':'launch','job':'fixture','command':'cat'})
            fleet.write_text('{}')
            assert 'error' in module.request({'op':'launch','job':'fixture'}), 'malformed inventory must fail closed'
            fleet.write_text(json.dumps({'sandboxes':[{'id':'bx_fixture','name':'unnamed'}],'pageInfo':{'hasMore':False}}))
            assert 'error' in module.request({'op':'launch','job':'fixture'}), 'known live ID must block even without a case name'
            fleet.write_text(json.dumps({'sandboxes':[],'pageInfo':{'hasMore':False}}))
            expected = {'expected_generation':card['sha256'], 'expected_recovery_config_sha256':module.recovery_conditions_digest(card)}
            for changes in ({'expected_generation':'0'*64}, {'expected_recovery_config_sha256':'0'*64}):
                assert 'error' in module.request({'op':'launch','job':'fixture',**expected,**changes}), 'stale expectations consumed a launch'
            assert 'error' in module.request({'op':'launch','job':'fixture','expected_generation':card['sha256']}), 'partial attestation accepted'
            paused = {**card,'terminal_stop':'paused','continuation_budget':{**card['continuation_budget'],'terminal_stop':'PauseRequested'}}
            card_path.write_text(json.dumps(paused))
            assert 'error' in module.request({'op':'launch','job':'fixture',**expected}), 'a newly paused case was resumed by an older plan'
            changed = {**card,'roles':{'strong_calibrator':{**card['roles']['strong_calibrator'],'model':'anthropic/synthetic'}}}
            card_path.write_text(json.dumps(changed))
            assert 'error' in module.request({'op':'launch','job':'fixture',**expected}), 'an exact provider route changed under an older plan'
            changed = {**card,'continuation_budget':{**card['continuation_budget'],'calls':1}}
            card_path.write_text(json.dumps(changed))
            assert 'error' in module.request({'op':'launch','job':'fixture',**expected}), 'lower cumulative usage slipped through unchanged configuration'
            card_path.write_text(json.dumps(card))
            reply=module.request({'op':'launch','job':'fixture',**expected}); assert reply.get('started'),reply
            for _ in range(100):
                status=module.request({'op':'status'})
                if status['jobs']['fixture']['exit'] is not None:break
                time.sleep(.03)
            assert status['jobs']['fixture']['exit']==0
            assert int((root/'proof.txt').read_text())==len(key.rstrip(b'\n'))
            assert 'error' in module.request({'op':'launch','job':'fixture'}), 'must reject stale checkpoint replay'
            assert 'error' in module.request({'op':'launch','job':'repair'}), 'any-case job needs a case id'
            assert 'error' in module.request({'op':'launch','job':'fixture','case':case2}), 'only any-case jobs take a case id'
            reply=module.request({'op':'launch','job':'repair','case':case2}); assert reply.get('started'), reply
            for _ in range(100):
                status=module.request({'op':'status'})
                if status['jobs']['repair-hetic2']['exit'] is not None:break
                time.sleep(.03)
            assert status['jobs']['repair-hetic2']['exit']==0
            assert key.strip().decode() not in json.dumps(status)
            module.request({'op':'stop'});p.wait(timeout=5)
            assert not module.SOCKET.exists()
            assert key.strip() not in p.stdout.read()+p.stderr.read()
            p=start()
            assert 'error' in module.request({'op':'launch','job':'fixture'}), 'replay reservation must survive holder restart'
            launcher.write_text(launcher.read_text()+'# changed trusted code\n')
            assert 'error' in module.request({'op':'launch','job':'fixture'})
            module.request({'op':'stop'});p.wait(timeout=5)
            print('PASS hidden key API, owner-only socket, pinned commands, no arbitrary export, direct stdin delivery, durable replay refusal, code drift refusal and clean stop; synthetic only')
        finally:
            if p.poll() is None:p.terminate();p.wait(timeout=5)
            shutil.rmtree(module.RUNTIME,ignore_errors=True)


if __name__=='__main__':main()
