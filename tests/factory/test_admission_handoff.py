"""Actual collector/planner/Registry/launcher, synthetic ciphertext and local Boat only."""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import copy
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import time
import unittest
import tarfile
import io
import types
from unittest import mock

import registry
import restart
import statement_round

HERE = (Path(__file__).resolve().parents[2] / "factory")


class AdmissionHandoffTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.root = self.base / 'host'; self.remote = self.base / 'worker'
        self.history = self.base / 'authority'; self.state = self.base / 'state'
        for path in (self.root / 'factory', self.root / 'bin', self.root / 'sealed',
                     self.remote / 'sealed', self.remote / 'statements', self.remote / 'factory',
                     self.history / 'sealed', self.state, self.base / 'tools'):
            path.mkdir(parents=True)
        for name in ('statement_round.py', 'restart.py', 'recovery.py', 'budget.py', 'token_prices.py', 'registry.py', 'admission.py',
                     'calibration.py', 'free_models.py', 'collect.sh', 'transfer.py'):
            shutil.copyfile(HERE / name, self.root / 'factory' / name)
        self.worker = 'worker-owned'; self.case = 'case-selected'
        case_dir = self.remote / 'work' / self.case / 'case'; case_dir.mkdir(parents=True)
        statement = 'synthetic freshly selected candidate'
        (case_dir / 'statement.md').write_text(statement)
        self.archive = self.case + '.checkpoint.tar.gz.age'
        (self.remote / 'sealed' / self.archive).write_bytes(b'age-encryption.org/v1\nsynthetic checkpoint')
        cipher = self.remote / 'sealed' / (self.case + '.statement.age')
        cipher.write_bytes(b'age-encryption.org/v1\nsynthetic selected statement')
        self.config = dict(version=1, rounds=3, runs=10, scenario_runs=3, pilot_tries=3,
            pilot_runs=5, calibrator_minutes=30, max_role_calls=400, max_total_calls=2000,
            max_cost=5, no_progress_minutes=45, max_zero_tokens=3, agent_timeout=14400, max_repairs=2)
        roles = dict(writer=dict(model='codex/gpt-6.1-sol', effort='high'),
            stress_tester=dict(model='opencode/deepseek-v4.1-flash-free', effort='default'),
            strong_calibrator=dict(model='claude/claude-opus-5-5', effort='high'),
            reviewer=dict(model='openrouter/xiaomi/mimo-v2.6-pro', effort='default'),
            easy_calibrator=dict(model='openrouter/minimax/minimax-m3.1-flash:free', effort='default'))
        self.budget = dict(calls=23, cost=.012, active=None, events=[], terminal_stop='complete')
        self.card = dict(case=self.case, status='stopped', terminal_stop='admission_registry_unavailable',
            seed=12345, source='hunt', rotation_slot=1, roles=roles, recovery_config=self.config,
            candidate_attempts=1, rejected_candidates=[], continuation_budget=self.budget,
            sha256=self.sha(self.remote / 'sealed' / self.archive),
            statement_sha256=hashlib.sha256(statement.encode()).hexdigest(),
            statement_cipher_sha256=self.sha(cipher))
        self.save_card()
        (self.remote / 'sealed' / 'DONE').write_text(self.case + '\n')
        (self.remote / 'sealed' / (self.case + '.continuation-budget.json')).write_text(json.dumps(self.budget))
        old = self.history / 'sealed/case-history.statement.age'
        old.write_bytes(b'age-encryption.org/v1\nsynthetic global history')
        (old.parent / 'case-history.scorecard.json').write_text('{}')
        registry.Registry(old.parent / 'statement-registry').import_historical('case-history', old)
        self.argv = ['--source', 'hunt', '--rotation-slot', '1']
        for key, value in self.config.items():
            if key != 'version': self.argv += ['--' + key.replace('_', '-'), str(value)]
        for role, flag in (('writer', 'builder'), ('stress_tester', 'attacker'),
                           ('strong_calibrator', 'strong-calibrator'), ('reviewer', 'reviewer1'),
                           ('easy_calibrator', 'easy-calibrator')):
            self.argv += ['--' + flag, roles[role]['model'], '--' + flag + '-effort', roles[role]['effort']]
        self.argv += ['--bench-workers', '2', '--concurrent-roles']
        self.args = shlex.join(self.argv)
        (self.base / 'tools/pgrep').write_text('#!/bin/sh\ntest -f "$HOME/live-runner"\n')
        (self.base / 'tools/pgrep').chmod(0o755)
        cli = self.base / 'tools/opencode'; cli.write_text('#!/bin/sh\necho 1.19.0\n'); cli.chmod(0o755)
        backend = self.root / 'bin/boat-call'
        backend.write_text('#!/usr/bin/env python3\n' +
            'import json,os,pathlib,shutil,subprocess,sys\n' +
            'base=pathlib.Path(' + repr(str(self.base)) + '); remote=base/"worker"\n' +
            'a=sys.argv[1:]; a=a[1:] if a[:1]==["--stdin"] else a; assert a[0] in ("ssh","scp","exec"), a\n' +
            'with (base/"calls").open("a") as f: f.write(json.dumps(a)+"\\n")\n' +
            'if a[0]=="scp":\n' +
            ' assert a[2].split(":")[0]=="worker-owned"\n' +
            ' shutil.copyfile(a[1], str(remote)+a[2].split(":",1)[1].removeprefix("/home/user")); sys.exit()\n' +
            'assert a[1]=="worker-owned"\n' +
            'cmd=a[2] if a[0]=="ssh" else a[-1]\n' +
            'cmd=cmd.replace("/home/user",str(remote)).replace("/usr/local/bin/opencode",str(base/"tools/opencode"))\n' +
            'env={**os.environ,"HOME":str(remote),"PATH":str(base/"tools")+os.pathsep+os.environ["PATH"]}\n' +
            'if a[0]=="exec" and (base/"async-detach").exists():\n' +
            ' (base/"pending-detached.sh").write_text(cmd); sys.exit()\n' +
            'sys.exit(subprocess.run(["/bin/sh","-c",cmd],env=env,stderr=subprocess.DEVNULL).returncode)\n')
        backend.chmod(0o755)
        (self.remote / 'factory/run.py').write_text('import json,pathlib,sys\nh=pathlib.Path.home()\n'
            'case=sys.argv[sys.argv.index("--resume")+1]\n'
            'result={"args":sys.argv[1:],"budget":json.loads((h/"sealed"/(case+".continuation-budget.json")).read_text()),"lock_owner":(h/"sealed/.factory-restart.lock/owner").read_text()}\n'
            '(h/"resumed.json").write_text(json.dumps(result))\n')

    @staticmethod
    def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()

    def save_card(self):
        (self.remote / 'sealed' / (self.case + '.scorecard.json')).write_text(json.dumps(self.card))

    def collect(self):
        result = subprocess.run(['/bin/sh', str(self.root / 'factory/collect.sh'), self.worker],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def handoff(self, remaining=3600, args=None, handoffs=0):
        return statement_round.same_worker_handoff(self.root, self.history, self.worker, self.case,
                                                   remaining, self.args if args is None else args, handoffs)

    def launch_resume(self):
        source = (HERE / 'launch.sh').read_text()
        function = source[source.index('factory_auto_resume() {'):source.index('\nbatch_status=0')]
        started = self.state / (self.worker + '.started')
        if not started.exists(): started.write_text(str(int(time.time())))
        (self.state / (self.worker + '.bench-sha')).write_text('a' * 64)
        script = 'set -eu\n' + function + '\n' + '\n'.join([
            'root=' + shlex.quote(str(self.root)), 'here=$root/factory',
            'state=' + shlex.quote(str(self.state)), 'admission_root=' + shlex.quote(str(self.history)),
            'sealed_audit=""; UNBUG_CLOUD=boat; retire_at=3600; workers_arg=""; vm_creds=:',
            'args=' + shlex.quote(self.args),
            'boat() { "$root/bin/boat-call" "$@"; }',
            'collect_vm() { /bin/sh "$here/collect.sh" "$1"; }',
            # This extracts only admission restart logic; real bundle gating is
            # exercised through the full launcher in test_codex_login_rotation.
            'codex_login_gate() { :; }',
            'factory_auto_resume ' + self.worker])
        return subprocess.run(['/bin/sh', '-c', script], capture_output=True, text=True)

    def test_collector_registry_planner_and_launcher_resume_same_worker(self):
        result = self.launch_resume()
        self.assertEqual(result.returncode, 0, result.stderr)
        resumed = json.loads((self.remote / 'resumed.json').read_text())
        self.assertEqual(resumed['budget'], self.budget)
        self.assertEqual(resumed['args'][:len(self.argv)], self.argv)
        self.assertEqual(resumed['args'][-6:], ['--resume', self.case, '--resume-bench-sha', 'a' * 64, '--seed', '12345'])
        self.assertEqual(self.sha(self.root / 'sealed' / self.archive), self.card['sha256'])
        self.assertFalse((self.state / (self.worker + '.autoresumes')).exists())
        self.assertEqual((self.state / (self.worker + '.admission-handoffs')).read_text().strip(), '1')
        snapshot = json.loads((self.remote / 'statements/admission.json').read_text())
        self.assertEqual(set(snapshot['statements']), {'case-history'})
        calls = [json.loads(line) for line in (self.base / 'calls').read_text().splitlines()]
        self.assertEqual(sum(row[0]=='exec' for row in calls), 1)
        self.assertTrue(all(row[1]==self.worker for row in calls if row[0] in ('exec', 'ssh')))
        self.assertFalse(any(row[0] in ('create', 'extend', 'delete') for row in calls))

    def test_registry_only_reservation_needs_no_loose_copy(self):
        # Live 862371: the board exported a screening reservation whose ciphertext
        # exists only in the registry object store, not as a loose history file.
        other = self.base / 'elsewhere.statement.age'
        other.write_bytes(b'age-encryption.org/v1\nsynthetic other worker reservation')
        registry.Registry(self.history / 'sealed/statement-registry').reserve(
            'case-reserved', 'b' * 64, other)
        result = self.launch_resume()
        self.assertEqual(result.returncode, 0, result.stderr)
        snapshot = json.loads((self.remote / 'statements/admission.json').read_text())
        self.assertEqual(set(snapshot['statements']), {'case-history', 'case-reserved'})
        self.assertEqual((self.remote / 'statements/case-reserved.statement.age').read_bytes(),
                         other.read_bytes())

    def test_registry_only_reservation_with_missing_object_fails_closed(self):
        other = self.base / 'elsewhere.statement.age'
        other.write_bytes(b'age-encryption.org/v1\nsynthetic other worker reservation')
        entry = registry.Registry(self.history / 'sealed/statement-registry').reserve(
            'case-reserved', 'b' * 64, other)
        (self.history / 'sealed/statement-registry/objects' / (entry['cipher_sha256'] + '.age')).unlink()
        self.collect()
        with self.assertRaisesRegex(ValueError, 'incomplete global statement history'): self.handoff()
        self.assertFalse((self.remote / 'resumed.json').exists())
        self.assertFalse((self.remote / 'sealed/.factory-restart.lock').exists())

    def test_advisory_board_batched_delivery_cannot_grant_admission(self):
        import admission
        board = self.base / 'selection-board'
        registry.Registry(self.history / 'sealed/statement-registry').export_board(board)
        statement_round.install(str(self.root/'bin/boat-call'), self.worker, board, provider='boat')
        delivered = self.remote / 'statements'
        self.assertEqual(set(admission.selection_snapshot(delivered, self.case)), {'case-history'})
        with self.assertRaises((OSError, ValueError)):
            admission.registry_snapshot(delivered, self.case, 'synthetic freshly selected candidate')
        calls = [json.loads(line) for line in (self.base/'calls').read_text().splitlines()]
        self.assertEqual([row[0] for row in calls], ['ssh', 'ssh'])
        self.assertFalse((self.remote/'resumed.json').exists())

    def test_actual_seal_binds_statement_ciphertext_before_handoff(self):
        import run
        import r2_upload
        key = self.base / 'throwaway-key'
        subprocess.run(['age-keygen', '-o', str(key)], check=True, capture_output=True)
        recipient = subprocess.check_output(['age-keygen', '-y', str(key)], text=True).strip()
        recipient_file = self.base / 'statements-recipient.txt'
        recipient_file.write_text(recipient)
        work = self.remote / 'work' / self.case
        card = copy.deepcopy(self.card)
        card.pop('statement_cipher_sha256')  # The real producer must supply this.
        card.pop('statement_sha256')  # Completed resumes initialize a fresh card.
        c = types.SimpleNamespace(work=work, case_id=self.case, card=card,
            args=types.SimpleNamespace(dry_run=False), recipient=recipient,
            statement=(work / 'case/statement.md').read_text())
        previous = None
        for _ in range(2):
            with mock.patch.multiple(run, HOME=self.remote, SEALED=self.remote/'sealed',
                    STATEMENTS_RECIPIENT=recipient_file, AGENT_STATE=()), \
                 mock.patch.object(run.RunArtifacts, 'results_since', return_value=[]), \
                 mock.patch.object(run, 'pilot_homes', return_value=[]), \
                 mock.patch.object(r2_upload, 'case_recipient', return_value=None):
                run.seal(c, checkpoint=True)
            cipher = self.remote / 'sealed' / (self.case + '.statement.age')
            self.assertEqual(c.card.get('statement_cipher_sha256'), self.sha(cipher))
            self.assertEqual(c.card.get('statement_sha256'), hashlib.sha256(c.statement.encode()).hexdigest())
            self.assertNotEqual(c.card['statement_cipher_sha256'], previous)
            previous = c.card['statement_cipher_sha256']
            opened = subprocess.run(['age', '-d', '-i', str(key), c.card['archive']],
                                    check=True, capture_output=True).stdout
            with tarfile.open(fileobj=io.BytesIO(opened), mode='r:gz') as archive:
                embedded = json.load(archive.extractfile(self.case + '/scorecard.json'))
            self.assertEqual(embedded['statement_cipher_sha256'], self.sha(cipher))
        self.card = c.card
        self.save_card()
        self.collect()
        proof = self.handoff()
        self.assertEqual(proof['statement_cipher_sha256'], previous)
        self.assertEqual(proof['budget'], self.budget)

    def test_reselection_uses_same_worker_deadline_and_separate_bound(self):
        self.assertEqual(self.launch_resume().returncode, 0)
        started = (self.state / (self.worker + '.started')).read_text()
        old_digest = self.card['statement_sha256']
        selected = self.remote / 'work' / self.case / 'case/statement.md'
        selected.write_text('synthetic second candidate')
        self.card['statement_sha256'] = self.sha(selected)
        self.card['candidate_attempts'] = 2
        self.card['rejected_candidates'] = [{'statement_sha256':old_digest}]
        cipher = self.remote / 'sealed' / (self.case + '.statement.age')
        cipher.write_bytes(b'age-encryption.org/v1\nsynthetic second statement')
        self.card['statement_cipher_sha256'] = self.sha(cipher)
        archive = self.remote / 'sealed' / self.archive
        archive.write_bytes(b'age-encryption.org/v1\nsynthetic second checkpoint')
        self.card['sha256'] = self.sha(archive)
        self.save_card()
        (self.remote / 'sealed/DONE').write_text(self.case)
        result = self.launch_resume()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.state / (self.worker + '.started')).read_text(), started)
        self.assertEqual((self.state / (self.worker + '.admission-handoffs')).read_text().strip(), '2')
        self.assertEqual(json.loads((self.remote / 'resumed.json').read_text())['budget'], self.budget)
        self.assertEqual(json.loads((self.remote / 'statements/admission.json').read_text())['statement_sha256'], self.card['statement_sha256'])

    def test_restart_lock_prevents_duplicate_handoff_during_detach(self):
        (self.remote / 'sealed/.factory-restart.lock').mkdir()
        self.assertEqual(self.launch_resume().returncode, 0)
        self.assertFalse((self.remote / 'resumed.json').exists())
        self.assertFalse((self.state / (self.worker + '.admission-handoffs')).exists())

    def test_refuses_unproven_stop_and_expired_or_exhausted_handoffs(self):
        self.collect()
        card_path = self.root / 'sealed' / (self.case + '.scorecard.json')
        with self.assertRaises(ValueError): restart.plan(card_path, 0, 3600, self.args)
        for kwargs in ({'remaining':60}, {'remaining':float('nan')}, {'handoffs':3},
                       {'args':self.args.replace('--runs 10', '--runs 1')}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError): self.handoff(**kwargs)
        for field, value in (('calls',2000), ('cost',5), ('active',{'synthetic':True})):
            card = copy.deepcopy(self.card); card['continuation_budget'][field]=value
            card_path.write_text(json.dumps(card))
            with self.subTest(field=field), self.assertRaises(ValueError): self.handoff()
        for count in (0,4):
            card = copy.deepcopy(self.card); card['candidate_attempts']=count
            card_path.write_text(json.dumps(card))
            with self.assertRaises(ValueError): self.handoff()
        self.assertNotIn('exec', (self.base / 'calls').read_text())

    def test_wrong_done_live_runner_stale_cipher_and_missing_history_fail_closed(self):
        self.collect()
        for mutation in ('done','live','cipher','ledger','history'):
            with self.subTest(mutation=mutation):
                target = {'done':self.remote/'sealed/DONE', 'live':self.remote/'live-runner',
                    'cipher':self.remote/'sealed'/(self.case+'.statement.age'),
                    'ledger':self.remote/'sealed'/(self.case+'.continuation-budget.json'),
                    'history':self.history/'sealed/case-history.statement.age'}[mutation]
                before = target.read_bytes() if target.exists() else None
                if mutation=='history': target.unlink()
                else: target.write_text('case-wrong' if mutation=='done' else 'changed')
                with self.assertRaises((ValueError, subprocess.CalledProcessError)): self.handoff()
                if before is None: target.unlink()
                else: target.write_bytes(before)
                shutil.rmtree(self.remote / 'sealed/.factory-restart.lock', ignore_errors=True)
        self.assertFalse((self.remote / 'resumed.json').exists())

    def test_fences_detect_mutation_during_transfer_and_before_detach(self):
        for boundary in ('swap', 'resume'):
            with self.subTest(boundary=boundary):
                original = statement_round.command
                def mutate(args, capture=False, **kwargs):
                    if args[1] == '--stdin':
                        (self.remote / 'work' / self.case / 'case/statement.md').write_text('changed')
                    return original(args, capture, **kwargs)
                if boundary == 'swap':
                    self.collect()
                    with mock.patch.object(statement_round, 'command', mutate):
                        with self.assertRaises(subprocess.CalledProcessError): self.handoff()
                    self.assertFalse((self.remote / 'statements/admission.json').exists())
                    (self.remote / 'work' / self.case / 'case/statement.md').write_text('synthetic freshly selected candidate')
                    shutil.rmtree(self.remote / 'sealed/.factory-restart.lock')
                else:
                    self.collect()
                    proof = self.handoff()
                    (self.remote / 'sealed' / (self.case + '.scorecard.json')).write_text('{}')
                    with self.assertRaises(subprocess.CalledProcessError):
                        original([str(self.root / 'bin/boat-call'), 'ssh', self.worker, proof['resume_guard']])
                    self.assertFalse((self.remote / 'resumed.json').exists())

    def test_async_detach_retains_owner_across_swap_to_actual_start(self):
        (self.base / 'async-detach').touch()
        accepted = self.launch_resume()
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertFalse((self.remote / 'resumed.json').exists())
        lock = self.remote / 'sealed/.factory-restart.lock'
        owner = (lock / 'owner').read_text()
        proof_path = next(self.state.glob('*.admission-*.json'))
        proof = json.loads(proof_path.read_text())
        self.assertEqual(owner, proof['lock_owner'])
        self.assertTrue((self.remote / 'statements/admission.json').is_file())
        # Exact reviewed interval: the swap returned and detach was accepted, but
        # the remote startup command has not run. A competing owner cannot enter.
        with self.assertRaises(FileExistsError): lock.mkdir()
        self.assertEqual(self.launch_resume().returncode, 0)
        calls = [json.loads(line) for line in (self.base / 'calls').read_text().splitlines()]
        self.assertEqual(sum(row[0]=='exec' for row in calls), 1)
        env = {**os.environ, 'HOME':str(self.remote),
               'PATH':str(self.base / 'tools') + os.pathsep + os.environ['PATH']}
        started = subprocess.run(['/bin/sh', str(self.base / 'pending-detached.sh')],
                                 env=env,capture_output=True,text=True)
        self.assertEqual(started.returncode, 0, started.stderr)
        self.assertEqual(json.loads((self.remote / 'resumed.json').read_text())['lock_owner'], owner)
        self.assertFalse(lock.exists())

    def test_async_startup_refusal_retains_owned_lock_and_checkpoint(self):
        (self.base / 'async-detach').touch()
        self.assertEqual(self.launch_resume().returncode, 0)
        lock = self.remote / 'sealed/.factory-restart.lock'
        owner = (lock / 'owner').read_text()
        (self.remote / 'work' / self.case / 'case/statement.md').write_text('stale after detach')
        env = {**os.environ, 'HOME':str(self.remote),
               'PATH':str(self.base / 'tools') + os.pathsep + os.environ['PATH']}
        refused = subprocess.run(['/bin/sh', str(self.base / 'pending-detached.sh')],
                                 env=env,capture_output=True,text=True)
        self.assertNotEqual(refused.returncode, 0)
        self.assertEqual((lock / 'owner').read_text(), owner)
        self.assertEqual(self.sha(self.root / 'sealed' / self.archive), self.card['sha256'])
        self.assertFalse((self.remote / 'resumed.json').exists())

    def test_uncertain_transfer_keeps_checkpoint_and_never_retries(self):
        backend = self.root / 'bin/boat-call'
        backend.write_text(backend.read_text().replace('if a[0]=="scp":',
                           'if a[0]=="ssh" and "tar -xzf" in a[-1]: sys.exit(1)\nif a[0]=="scp":'))
        result = self.launch_resume()
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue((self.state / (self.worker + '.keep')).exists())
        self.assertEqual(self.sha(self.root / 'sealed' / self.archive), self.card['sha256'])
        self.assertFalse((self.remote / 'resumed.json').exists())
        calls = (self.base / 'calls').read_bytes()
        self.assertNotEqual(self.launch_resume().returncode, 0)
        self.assertEqual((self.base / 'calls').read_bytes(), calls)


if __name__ == '__main__': unittest.main()
