"""Public synthetic TTL preparation; no launch, model, credential or case access."""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import copy
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import pathlib
import tempfile
import unittest
import os
import inspect
import shlex
import time
import subprocess
from types import SimpleNamespace
from unittest.mock import patch

import coordinator
import ttl_continuation as ttl
import key_holder
import run as runner


class TTLPreparationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name); (self.root / 'sealed').mkdir()
        self.request = dict(version=1, reason='ttl', case='case-synthetic', worker='worker-synthetic',
                            nonce='a' * 32, runner_pid=123, requested_at=2000)
        config = {field: 1 for field in coordinator.CONFIG_FIELDS}
        config.update(version=1, case_budget=50, max_total_calls=100, max_cost=5, max_repairs=0)
        self.card = dict(case='case-synthetic', source='port', rotation_slot=1, seed=42, status='stopped',
                         terminal_stop='ttl_retired', retirement=copy.deepcopy(self.request), recovery_config=config,
                         roles={'writer': {'model': 'codex/synthetic', 'effort': 'medium'}},
                         continuation_budget={'calls': 20, 'cost': 1, 'events': [], 'terminal_stop': 'PauseRequested'})
        self.archive = self.root / 'sealed/case-synthetic.checkpoint.tar.gz.age'
        self.card_path = self.root / 'sealed/case-synthetic.scorecard.json'
        self.options = dict(started_at=1000, deadline=10000, max_attempts=2, max_spend=3,
                            initial_spend=1, launch_spend=1, ttl_hours=1, now=3000)
        self.generation(1)

    def generation(self, number):
        self.archive.write_bytes(b'age-encryption.org/v1\nsynthetic ciphertext ' + str(number).encode())
        self.card['sha256'] = hashlib.sha256(self.archive.read_bytes()).hexdigest()
        self.write_card()

    def write_card(self):
        self.card_path.write_text(json.dumps(self.card))

    def prepare(self):
        return ttl.prepare(self.root, self.request, **self.options)

    def test_ttl_preparation_preserves_conditions_and_deduplicates_without_launching(self):
        with patch.object(coordinator.key_holder, 'request', side_effect=AssertionError('no holder launch')):
            row = self.prepare()
            self.assertEqual(self.prepare(), row)
        self.assertEqual(row['action'], 'queued_policy_required')
        self.assertEqual(row['launch_expectations']['expected_generation'], self.card['sha256'])
        argv = row['job_proposal']['args']
        for flag, expected in (('--seed', '42'), ('--max-total-calls', '100'), ('--max-cost', '5'),
                               ('--builder', 'codex/synthetic'), ('--builder-effort', 'medium')):
            self.assertEqual(argv[argv.index(flag) + 1], expected)
        self.assertEqual((row['budget_calls'], row['budget_cost']), (20, 1))
        self.assertEqual(len(json.loads((self.root / 'results/ttl-continuations/case-synthetic.json').read_text())['preparations']), 1)

    def test_manual_pause_missing_or_mismatched_request_never_queues(self):
        for change in ('manual', 'missing', 'mismatch', 'non-ttl'):
            original = copy.deepcopy(self.card)
            if change == 'manual': self.card['terminal_stop'] = 'paused'
            if change == 'missing': self.card.pop('retirement')
            if change == 'mismatch': self.card['retirement']['nonce'] = 'b' * 32
            if change == 'non-ttl': self.card['retirement']['reason'] = 'stalled'
            self.write_card()
            with self.subTest(change=change), self.assertRaises(ValueError): self.prepare()
            self.card = original
        self.assertFalse((self.root / 'results/ttl-continuations/case-synthetic.json').exists())

    def test_concurrent_preparations_share_one_durable_reservation(self):
        with ThreadPoolExecutor(max_workers=3) as pool:
            rows = list(pool.map(lambda _: self.prepare(), range(3)))
        self.assertTrue(all(row == rows[0] for row in rows))
        state = json.loads((self.root / 'results/ttl-continuations/case-synthetic.json').read_text())
        self.assertEqual(len(state['preparations']), 1)

    def test_verified_collection_and_original_budget_are_required(self):
        self.archive.unlink()
        with self.assertRaisesRegex(ValueError, 'collection required'): self.prepare()
        self.generation(1)
        self.archive.write_bytes(b'age-encryption.org/v1\ntampered ciphertext')
        with self.assertRaisesRegex(ValueError, 'collection required'): self.prepare()
        self.generation(1)
        for updates in ({'active': True}, {'calls': 100}, {'cost': 5}, {'terminal_stop': 'total_call_limit'}):
            original = copy.deepcopy(self.card['continuation_budget'])
            self.card['continuation_budget'].update(updates); self.write_card()
            with self.subTest(updates=updates), self.assertRaises(ValueError): self.prepare()
            self.card['continuation_budget'] = original

    def test_fixed_wall_spend_and_attempt_bounds_cannot_expand(self):
        self.prepare()
        self.options['deadline'] += 1
        with self.assertRaisesRegex(ValueError, 'bounds changed'): self.prepare()
        self.options['deadline'] -= 1
        self.request['nonce'] = 'b' * 32; self.card['retirement'] = copy.deepcopy(self.request)
        self.card['continuation_budget'].update(calls=25, cost=1.2); self.generation(2)
        self.prepare()
        self.request['nonce'] = 'c' * 32; self.card['retirement'] = copy.deepcopy(self.request)
        self.generation(3)
        with self.assertRaisesRegex(ValueError, 'allowance exhausted'): self.prepare()

    def test_reused_retirement_nonce_or_regressed_usage_is_rejected(self):
        self.prepare()
        self.generation(2)
        with self.assertRaisesRegex(ValueError, 'already consumed'): self.prepare()
        self.request['nonce'] = 'b' * 32; self.card['retirement'] = copy.deepcopy(self.request)
        self.card['continuation_budget']['calls'] = 19; self.write_card()
        with self.assertRaisesRegex(ValueError, 'usage regressed'): self.prepare()

    def test_insufficient_wall_or_infrastructure_allowance_never_queues(self):
        for update in ({'max_spend': 1}, {'deadline': 4000}, {'max_attempts': 4},
                       {'now': 10000}, {'deadline': 100000}):
            original = self.options.copy(); self.options.update(update)
            with self.subTest(update=update), self.assertRaises(ValueError): self.prepare()
            self.options = original


class TTLAdmissionTests(TTLPreparationTests):
    def setUp(self):
        super().setUp()
        self.now = time.time()
        self.options.update(started_at=self.now - 2000, deadline=self.now + 7000, now=self.now)
        # Full original args, fixed policy bounds, no credential/account material.
        self.request['requested_at'] = self.now
        self.card['retirement'] = copy.deepcopy(self.request)
        self.write_card()
        bounds = {k: v for k, v in self.options.items() if k != 'now'}
        job = self.prepare()['job_proposal']
        self.job = {**job, 'ttl_continuation': bounds}
        (self.root / 'results/ttl-continuations/case-synthetic.json').unlink()
        self.policy = {'jobs': {'synthetic': self.job}}
        self.snapshot = dict(version=1, observed_at=self.now, inventory_complete=True, workers=[], claude_accounts=[],
                             codex_accounts=[dict(id=1, capacity=1, used=0, available=True,
                                 models=[dict(model='codex/synthetic', effort='medium')],
                                 quota=dict(state='available', observed_at=self.now - 1, expires_at=self.now + 100,
                                            source='operator_observation'))])
        self.receipts, self.consumed, self.launches = [], set(), []

    def trigger(self):
        def remote(command):
            if command.startswith('pgrep'): return str(os.getpid())
            self.assertTrue((self.root / 'results/ttl-retirements/worker-synthetic.json').is_file())
            with patch.object(pathlib.Path, 'home', return_value=self.root):
                exec(shlex.split(command)[2], {})  # executes only the public marker installer locally
            return ''
        request = ttl.request_retirement(self.root, 'worker-synthetic', self.job, remote=remote, now=self.now)
        # Call the real SIGTERM handler with the same main-frame case binding as the runner.
        def main():
            c = SimpleNamespace(case_id=self.card['case'])
            runner.pause_on_term(None, inspect.currentframe())
        with patch.object(runner, 'SEALED', self.root / 'sealed'), patch.object(runner.signal, 'signal'):
            try: main()
            except runner.PauseRequested as error:
                self.card.update(runner.pause_terminal(error, self.card['case']))
        self.assertEqual(self.card['retirement'], request)
        self.assertEqual(self.card['terminal_stop'], 'ttl_retired')
        self.write_card()
        return request

    def holder(self, payload):
        if payload == {'op': 'status'}:
            return dict(unlocked=True, policy_sha256=key_holder.policy_digest(self.policy), seconds_remaining=7200, jobs={})
        generation = key_holder.current_generation(self.job)
        key_holder.attest_launch(self.job, generation, payload)
        ttl.admit(self.root, self.job, self.card, generation, payload, self.receipts, self.consumed)
        self.consumed.add((self.card['case'], generation))
        self.receipts.append(dict(case=self.card['case'], generation=generation, at=time.time(),
                                  budget_calls=self.card['continuation_budget']['calls'], budget_cost=self.card['continuation_budget']['cost']))
        self.launches.append(payload)
        return dict(started=True, job='synthetic', pid=123)

    def coordinate(self):
        with patch.object(key_holder, 'ROOT', self.root):
            return coordinator.coordinate(self.policy, self.snapshot, self.root / 'coordinator.json', 'synthetic',
                execute=True, now=time.time(), deadline=self.options['deadline'], request=self.holder)

    def test_trigger_collection_single_holder_admission(self):
        self.trigger()
        row = ttl.collect(self.root, 'worker-synthetic')
        self.assertEqual(ttl.collect(self.root, 'worker-synthetic'), row)
        self.assertEqual(self.coordinate()['action'], 'started')
        self.assertEqual(self.coordinate()['action'], 'reconcile')
        self.assertEqual(len(self.launches), 1)
        # Direct holder clients cannot replay even under retry_failed_launches policies.
        with self.assertRaisesRegex(ValueError, 'already admitted'):
            ttl.admit(self.root, self.job, self.card, self.card['sha256'], self.launches[0], self.receipts, set())
        argv = self.job['args']
        for flag, value in (('--seed', '42'), ('--max-cost', '5'), ('--max-total-calls', '100'),
                            ('--builder', 'codex/synthetic'), ('--builder-effort', 'medium')):
            self.assertEqual(argv[argv.index(flag) + 1], value)

    def test_unqueued_unverified_manual_and_expired_never_admitted(self):
        self.trigger()
        with self.assertRaises(OSError): ttl.ready(self.root, self.job, self.card)
        self.assertNotEqual(self.coordinate()['action'], 'started')
        ttl.collect(self.root, 'worker-synthetic')
        original = copy.deepcopy(self.card)
        for change in ('manual', 'hash', 'budget', 'host'):
            self.card = copy.deepcopy(original)
            if change == 'manual': self.card['terminal_stop'] = 'paused'
            if change == 'hash': self.card['sha256'] = '0' * 64
            if change == 'budget': self.card['continuation_budget']['calls'] = 100
            if change == 'host': self.card['retirement']['nonce'] = '0' * 32
            self.write_card()
            with self.subTest(change=change): self.assertNotEqual(self.coordinate()['action'], 'started')
        self.card = original; self.write_card()
        with self.assertRaises(ValueError): ttl.ready(self.root, self.job, self.card, now=self.options['deadline'])
        self.assertFalse(self.launches)

    def test_holder_rechecks_bounds_identity_and_infrastructure(self):
        self.trigger(); row = ttl.collect(self.root, 'worker-synthetic')
        payload = {'op': 'launch', 'job': 'synthetic', **row['launch_expectations']}
        for change in ('attempts', 'machine', 'expectations', 'conditions', 'deadline', 'spend'):
            job, card, req = copy.deepcopy(self.job), copy.deepcopy(self.card), payload.copy()
            receipts = []
            if change == 'attempts': receipts = [dict(case=card['case'], generation=str(i)) for i in range(2)]
            if change == 'machine': req['machine'] = 'large'
            if change == 'expectations': req.pop('expected_generation')
            if change == 'conditions': card['seed'] = 43
            if change == 'deadline': job['ttl_continuation']['deadline'] += 1
            if change == 'spend': job['ttl_continuation']['max_spend'] += 1
            # The holder reads the current card before admission.
            self.card_path.write_text(json.dumps(card))
            with self.subTest(change=change), self.assertRaises(ValueError):
                ttl.admit(self.root, job, card, card['sha256'], req, receipts, set())
        self.write_card()

    def test_manual_stale_wrong_pid_markers_remain_paused(self):
        self.trigger()
        marker = self.root / 'sealed/.ttl-retirement.json'
        request = json.loads(marker.read_text())
        for changes in ({'runner_pid': os.getpid() + 1}, {'requested_at': self.now - 121}, {'case': 'case-other'}):
            marker.write_text(json.dumps({**request, **changes}))
            self.assertIsNone(ttl.runner_request(marker, os.getpid(), self.card['case']))
        self.assertEqual(runner.pause_terminal(runner.PauseRequested(), self.card['case']), {'terminal_stop': 'paused'})

    def test_ttl_between_model_calls_preserves_completed_ledger(self):
        self.trigger()
        self.card['continuation_budget']['terminal_stop'] = 'complete'; self.write_card()
        ttl.collect(self.root, 'worker-synthetic')
        self.assertEqual(self.coordinate()['action'], 'started')
        self.assertEqual(self.card['continuation_budget']['terminal_stop'], 'complete')

    def test_second_generation_reconciles_only_after_confirmed_delete(self):
        self.trigger(); ttl.collect(self.root, 'worker-synthetic')
        self.assertEqual(self.coordinate()['action'], 'started')
        self.now = time.time()
        self.card['continuation_budget'].update(calls=25, cost=1.2)
        self.trigger(); self.generation(2)
        ttl.collect(self.root, 'worker-synthetic')
        self.assertEqual(self.coordinate()['action'], 'reconcile')
        ttl.retired(self.root, 'worker-synthetic')
        self.assertEqual(self.coordinate()['action'], 'started')
        self.assertEqual(len(self.launches), 2)
        self.assertEqual(self.coordinate()['action'], 'reconcile')
        self.now = time.time(); self.trigger(); self.generation(3)
        with self.assertRaisesRegex(ValueError, 'allowance exhausted'):
            ttl.collect(self.root, 'worker-synthetic')

    def test_ordinary_authorized_recovery_bootstraps_opt_in_within_same_caps(self):
        self.card.update(terminal_stop='stalled'); self.card.pop('retirement')
        self.card['continuation_budget']['terminal_stop'] = 'stalled'; self.write_card()
        # Keep the existing transient-stop backoff, then arm the opted-in launcher.
        os.utime(self.card_path, (self.now - 1000, self.now - 1000))
        self.assertEqual(self.coordinate()['action'], 'started')
        self.now = time.time(); self.trigger()
        self.card['continuation_budget'].update(terminal_stop='PauseRequested', calls=25, cost=1.2)
        self.generation(2); ttl.collect(self.root, 'worker-synthetic'); ttl.retired(self.root, 'worker-synthetic')
        self.assertEqual(self.coordinate()['action'], 'started')
        self.assertEqual(len(self.launches), 2)
        # Bootstrap and successor together consume both permitted launches.
        with self.assertRaisesRegex(ValueError, 'attempt allowance'):
            ttl.admit(self.root, self.job, self.card, 'new',
                      {'expected_generation': self.card['sha256'], 'expected_recovery_config_sha256': key_holder.recovery_conditions_digest(self.card)},
                      self.receipts, set())

    def test_bootstrap_rejects_noncanonical_policy_before_any_launch(self):
        self.card.update(terminal_stop='stalled'); self.card.pop('retirement')
        self.card['continuation_budget']['terminal_stop'] = 'stalled'; self.write_card()
        job = copy.deepcopy(self.job)
        job['args'] = [*job['args'][:3], *job['args'][5:], *job['args'][3:5]]  # seed moved to the end
        payload = dict(expected_generation=self.card['sha256'],
                       expected_recovery_config_sha256=key_holder.recovery_conditions_digest(self.card))
        with self.assertRaisesRegex(ValueError, 'bootstrap changes original conditions'):
            ttl.admit(self.root, job, self.card, self.card['sha256'], payload, [], set())
        self.assertFalse(self.launches)


class TTLGuardTests(unittest.TestCase):
    def test_only_reachable_ttl_arms_and_delete_precedes_retirement_proof(self):
        guard = pathlib.Path(__file__).resolve().parents[2] / 'bin/boat-launch-guards.sh'
        for reply, expected in (('0', ['marker', 'collect', 'delete', 'proof']),
                                ('100', ['collect', 'delete', 'proof']),
                                ('DONE', ['collect', 'delete', 'proof'])):
            with self.subTest(reply=reply), tempfile.TemporaryDirectory() as temp:
                root = pathlib.Path(temp); (root / 'bin').mkdir(); (root / 'state').mkdir()
                (root / 'factory').mkdir()
                (root / 'factory/boat_lifecycle.py').write_bytes((guard.parent.parent / 'factory/boat_lifecycle.py').read_bytes())
                (root / 'state/ids').write_text('worker-synthetic\n')
                (root / 'state/worker-synthetic.started').write_text('1\n')
                fake = root / 'bin/boat-call'
                operation = json.dumps({'operation': {'id': 'delete-synthetic',
                    'targetId': 'worker-synthetic', 'kind': 'sandbox', 'status': 'completed',
                    'stage': 'completed', 'completedAt': '2026-10-24T00:00:00Z'}})
                fake.write_text('#!/bin/sh\ncase "$1" in\n'
                    'delete) echo delete >> "$EVENTS"; printf \'%s\\n\' ' + shlex.quote(operation) + ';;\n'
                    'deletion) printf \'%s\\n\' ' + shlex.quote(operation) + ';;\n'
                    '*) echo "$REPLY";;\nesac\n')
                fake.chmod(0o755)
                script = '\n'.join([
                    'set -eu', 'root=' + shlex.quote(str(root)), 'label=factory',
                    '. ' + shlex.quote(str(guard)), 'state="$root/state"; spend_file="$root/spend.json"',
                    'retire_at=1; stall_seconds=10; stall_minutes=1; unreachable=1; poll=1; probe_python="print(0)"',
                    'factory_ttl_retire() { echo marker >> "$EVENTS"; }',
                    'factory_ttl_retired() { echo proof >> "$EVENTS"; }',
                    'collect_vm() { echo collect >> "$EVENTS"; }', 'guard_wait once || true'])
                env = {**os.environ, 'UNBUG_CLOUD': 'boat', 'BOAT_CMD': str(fake),
                       'EVENTS': str(root / 'events'), 'REPLY': reply}
                result = subprocess.run(['sh', '-c', script], env=env, capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual((root / 'events').read_text().splitlines(), expected)


if __name__ == '__main__': unittest.main()
