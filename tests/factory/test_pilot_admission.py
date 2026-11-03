"""Offline contracts using retained card/ciphertext/creation evidence via holder fixtures.
Policy, clocks, extra identities, service and provider edges are authored controls.
No live acceptance evidence; no Murphy closure.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin')]
import batch
import batch_holder as holder
import batch_money as money
import batch_service as service
import key_holder
import pilot
import practice_cleanup as cleanup
import test_batch_holder as retained
import test_batch_service as fixtures


class PilotTests(unittest.TestCase):
    setUpBase = fixtures.ServiceTests.setUp
    started = retained.HolderTests.started
    reserve = retained.HolderTests.reserve
    reconcile = retained.HolderTests.reconcile
    ops = retained.HolderTests.ops
    money = retained.HolderTests.money
    publish = retained.HolderTests.publish
    output = retained.HolderTests.output
    retirement = retained.HolderTests.retirement
    write_card = fixtures.ServiceTests.write_card
    answers = fixtures.ServiceTests.answers

    @property
    def directory(self): return self.home / 'batches' / self.record['id']

    def freeze(self):
        path = self.root / ('factory/batches/' + self.record['id'] + '.json')
        path.write_text(json.dumps(self.record))
        pin = hashlib.sha256(path.read_bytes()).hexdigest()
        self.policy['batch']['manifest_sha256'] = pin
        self.policy['batch']['manifest_path'] = str(path.relative_to(self.root))
        (self.release / 'source-manifest.json').write_text(json.dumps({'files': {str(path.relative_to(self.root)): pin}}))

    def input(self, job='j', **kwargs):
        card = fixtures.ServiceTests.input(self, job, **kwargs)
        old = card['case']; case = self.record['jobs'][job]['case']
        card.update(case=case, archive=case + '.checkpoint.tar.gz.age')
        for file in list(self.source.iterdir()):
            if file.name.startswith(old + '.'): file.rename(file.with_name(case + file.name[len(old):]))
        self.write_card(card)
        return card

    def setUp(self):
        self.setUpBase()
        now = datetime.now(timezone.utc)
        self.record.update(id='b-pilot-offline', target_slots=3, money_limit_usd='3000.000000000',
            replacement_policy=dict(schema=1, enabled=False),
            batch_deadline=(now + timedelta(hours=5)).isoformat(),
            pilot_admission=dict(schema=1, starts_at=(now - timedelta(minutes=30)).isoformat(),
                max_lifecycles=6, max_lifecycles_per_case=2, infrastructure_limit_usd='4.000000000'))
        self.record['jobs']['l'] = deepcopy(self.record['jobs']['k'])
        for name, job in self.record['jobs'].items():
            job.update(case='case-' + self.record['id'] + '-' + name, requested_total_usd='1000.000000000',
                       args=['1', '--source', 'port', '--rotation-slot', '0', '--ttl-hours', '1', '--max-spend', '4'])
        self.policy['batch']['id'] = self.record['id']
        self.freeze()
        self.objects = {}
        pin = patch.dict(os.environ, UNBUG_PILOT_PIN=pilot.pin(self.policy), UNBUG_CLOUD='boat')
        pin.start(); self.addCleanup(pin.stop)

    def ledger(self, rows=None):
        self.home.mkdir(exist_ok=True)
        (self.home / 'boat-reservations.lock').touch()
        service.atomic_json(self.home / 'boat-reservations.json', dict(version=1, reservations=rows or {}))

    def armed(self, op):
        target = cleanup.location(self.home, op).with_suffix('.ready.json')
        target.parent.mkdir(parents=True, exist_ok=True)
        service.atomic_json(target, cleanup.ready(self.policy, op, 42))
        response = subprocess.CompletedProcess([], 0, 'ActiveState=active\nSubState=running\nExecMainPID=42\n')
        with patch.object(cleanup, 'digest', return_value='a' * 64), patch.object(cleanup.subprocess, 'run', return_value=response):
            cleanup.armed(self.policy, self.root, self.home, op, self.ops())

    def failed(self, missing_ids=False):
        op = self.started(self.reserve(), created=False)
        path = self.home / 'launches' / op['launch_id']
        if missing_ids: (path / 'ids').unlink()
        self.reconcile()
        op = self.ops()[op['operation_id']]
        self.assertEqual((op['state'], op['incident'], op['worker_id']), ('failed', 'preflight_refused', None))
        return op, path

    def test_default_off_pin_authentication_and_no_legacy_bypass(self):
        self.assertFalse(holder.HOLDER_ENABLED)
        self.assertTrue(holder.active(self.policy, self.root))
        for pin in ('', 'wrong'):
            with patch.dict(os.environ, UNBUG_PILOT_PIN=pin), patch.object(holder, 'HOLDER_ENABLED', True):
                self.assertFalse(holder.active(self.policy, self.root))
                with self.assertRaises(ValueError): self.reserve()
                with self.assertRaises(ValueError): batch.bind(self.policy, 'j', None, self.root)
                with self.assertRaises(ValueError): key_holder.batch_request(self.policy, dict(op='launch', batch=self.record['id']))
        path = self.root / self.policy['batch']['manifest_path']
        path.write_text('{}')
        with self.assertRaises(ValueError): holder.active(self.policy, self.root)

    def test_shape_and_caps_are_parameterized(self):
        pilot.validate(self.record)
        bad = []
        for key, value in [('max_concurrency', 2), ('target_slots', 4), ('carry_from', {}),
                           ('practice_admission', {}), ('replacement_policy', dict(schema=1, enabled=True)),
                           ('money_limit_usd', '1.000000000')]:
            record = deepcopy(self.record); record[key] = value; bad.append(record)
        for key, value in [('max_lifecycles', 9), ('max_lifecycles_per_case', True),
                           ('infrastructure_limit_usd', '0.000000000'), ('infrastructure_limit_usd', 'NaN')]:
            record = deepcopy(self.record); record['pilot_admission'][key] = value; bad.append(record)
        for args in (['--ttl-hours', '2'], ['--ttl-hours=1'], ['--max-spend', '5'],
                     ['--dry-run'], ['--restore', 'case-old'], ['--reuse-review-worker', 'bx_old']):
            record = deepcopy(self.record); record['jobs']['j']['args'] += args; bad.append(record)
        for record in bad:
            with self.subTest(record=record), self.assertRaises(ValueError): pilot.validate(record)
        other = deepcopy(self.record); other['pilot_admission']['infrastructure_limit_usd'] = '2.500000000'
        for job in other['jobs'].values(): job['args'][-1] = '2.50'
        pilot.validate(other)

    def test_window_boundaries_and_cleanup_pin_does_not_expire(self):
        starts = datetime.fromisoformat(self.record['pilot_admission']['starts_at'])
        end = datetime.fromisoformat(self.record['batch_deadline'])
        for now in (starts - timedelta(seconds=1), end - timedelta(hours=1), end):
            with self.assertRaisesRegex(money.MoneyWait, 'pilot_window_closed'): pilot.admission(self.record, now)
        pilot.admission(self.record, starts)
        pilot.admission(self.record, end - timedelta(hours=1, seconds=1))
        record = deepcopy(self.record); record['pilot_admission']['starts_at'] = (end - timedelta(hours=7)).isoformat()
        with self.assertRaises(ValueError): pilot.validate(record)
        self.assertTrue(pilot.active(self.policy, self.root))

    def test_three_serial_initials_and_one_successor_each_caps_and_replay(self):
        for job in ('j', 'k', 'l'):
            op = self.started(self.reserve(job))
            card = self.output(op); self.publish(op); self.retirement(op); self.reconcile()
            successor = self.reserve(job, card['sha256'])
            self.assertEqual(self.reserve(job, card['sha256']), successor)
            successor = self.started(successor)
            next_card = self.output(successor, payload=fixtures.KEY)
            self.publish(successor); self.retirement(successor); self.reconcile()
            with self.assertRaisesRegex(money.MoneyWait, 'pilot_lifecycle_limit'):
                self.reserve(job, next_card['sha256'])
        self.assertEqual(len(self.ops()), 6)
        self.assertEqual(len(holder._operations(self.directory, self.record, self.policy)), 6)
        with self.assertRaisesRegex(money.MoneyWait, 'pilot_lifecycle_limit'): self.reserve('j', 'b' * 64)

    def test_round2_preflight_no_row_missing_and_empty_ids_clear_successor(self):
        for missing in (False, True):
            with self.subTest(missing=missing):
                if missing: self.setUp()
                old, path = self.failed(missing)
                self.ledger()
                self.assertTrue(cleanup.preflight_clear(self.home, old))
                new = self.reserve('k')
                self.armed(new)
                cleanup.observe_batch(self.policy, self.root, self.home, self.ops(), set())
                status = service._json(cleanup.location(self.home, old).with_suffix('.status.json'))
                self.assertEqual((status['state'], status['basis']), ('not_dispatched', 'preflight_no_reservation'))
                self.assertFalse((path / 'spend-finished').exists())

    def test_missing_invalid_ledger_bound_liability_and_uncertainty_stay_blocked(self):
        old, path = self.failed(); new = self.reserve('k')
        for raw in (None, '{}', '{"version":1,"reservations":{"bad":{}}}',
                    '{"version":1,"version":1,"reservations":{}}'):
            ledger = self.home / 'boat-reservations.json'
            if raw is None: ledger.unlink(missing_ok=True)
            else: ledger.write_text(raw)
            self.assertFalse(cleanup.preflight_clear(self.home, old))
            with self.assertRaisesRegex(money.MoneyWait, 'cleanup not settled'): self.armed(new)
        row = dict(status='finished', usd='0.036', expires_at=9999999999,
                   state_path=str(path.resolve()), vms=1, ttl_seconds=3600, max_spend_usd='4')
        self.ledger({'/retained-spend.json': row})
        self.assertFalse(cleanup.preflight_clear(self.home, old))
        with self.assertRaises(money.MoneyWait): self.armed(new)
        self.ledger()
        for name in ('new.1.pending', 'new.bad'):
            intent = path / name; intent.symlink_to(path / 'missing')
            self.assertFalse(cleanup.preflight_clear(self.home, old)); intent.unlink()
        for name in ('ids', 'launch.json'):
            file = path / name; saved = file.read_bytes(); file.write_text('wrong')
            self.assertFalse(cleanup.preflight_clear(self.home, old)); file.write_bytes(saved)
        with (path / 'controller.lock').open('rb') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertFalse(cleanup.preflight_clear(self.home, old))
        with holder.operation_lock(self.directory, old['operation_id']):
            self.assertFalse(cleanup.preflight_clear(self.home, old))
        self.assertTrue(cleanup.preflight_clear(self.home, old))

    def test_fenced_before_controller_and_no_missing_directory_proof(self):
        op = self.reserve()
        with money.locked(self.home, self.record['id']):
            ops = self.ops(); ops[op['operation_id']].update(dispatch_started=True,
                launch=dict(argv=['1'], environment={'UNBUG_BATCH_OPERATION': op['operation_id']}))
            holder._save(self.directory, self.record, self.policy, ops)
        self.reconcile(); op = self.ops()[op['operation_id']]; self.ledger()
        self.assertTrue(cleanup.preflight_clear(self.home, op))
        path = self.home / 'launches' / op['launch_id']; path.rmdir()
        self.assertFalse(cleanup.preflight_clear(self.home, op))

    def test_pending_settlement_status_gate_and_ready_binding(self):
        old = self.started(self.reserve()); self.output(old); self.publish(old); self.retirement(old); self.reconcile()
        new = self.reserve('k')
        target = cleanup.location(self.home, old).with_suffix('.status.json'); target.parent.mkdir(parents=True)
        for state in ('settlement_pending', 'uncertain', 'waiting', 'deleting'):
            service.atomic_json(target, dict(schema=1, operation_id=old['operation_id'], state=state))
            with self.assertRaisesRegex(money.MoneyWait, 'cleanup not settled'): self.armed(new)
            self.assertFalse(self.ops()[new['operation_id']]['dispatch_started'])
        service.atomic_json(target, dict(schema=1, operation_id='wrong', state='complete'))
        with self.assertRaises(money.MoneyWait): self.armed(new)
        service.atomic_json(target, dict(schema=1, operation_id=old['operation_id'], state='complete'))
        self.armed(new)
        marker = cleanup.location(self.home, new).with_suffix('.ready.json')
        saved = service._json(marker); saved['pid'] = 43; service.atomic_json(marker, saved)
        response = subprocess.CompletedProcess([], 0, 'ActiveState=active\nSubState=running\nExecMainPID=42\n')
        with patch.object(cleanup, 'digest', return_value='a'), patch.object(cleanup.subprocess, 'run', return_value=response):
            with self.assertRaisesRegex(money.MoneyWait, 'cleanup not armed'):
                cleanup.armed(self.policy, self.root, self.home, new, self.ops())

    def test_batch_arms_all_before_observation_and_restart_revalidates(self):
        old, _ = self.failed(); self.ledger(); new = self.reserve('k')
        terminal = set(); observed = []
        def step(policy, root, home, op):
            for other in self.ops().values():
                self.assertEqual(service._json(cleanup.location(home, other).with_suffix('.ready.json')),
                                 cleanup.ready(policy, other, os.getpid()))
            observed.append(op['operation_id'])
            return dict(schema=1, operation_id=op['operation_id'], state='waiting')
        with patch.object(cleanup, 'step', side_effect=step):
            cleanup.observe_batch(self.policy, self.root, self.home, self.ops(), terminal)
            self.assertIn(old['operation_id'], terminal)
            cleanup.observe_batch(self.policy, self.root, self.home, self.ops(), terminal)
            cleanup.observe_batch(self.policy, self.root, self.home, self.ops(), set())
        self.assertEqual(observed, [new['operation_id']] * 3)
        self.assertNotEqual(cleanup.location(self.home, old), cleanup.location(self.home, new))

    def test_dispatch_waits_before_durable_start_then_proceeds_same_operation(self):
        import account_handoff
        old, _ = self.failed(); new = self.reserve('k')
        self.policy.update(code_sha256='fingerprint', path='/usr/bin:/bin', recipient='founder-public')
        target = cleanup.location(self.home, new).with_suffix('.ready.json'); target.parent.mkdir(parents=True)
        service.atomic_json(target, cleanup.ready(self.policy, new, 42))
        def run(argv, **kwargs):
            if argv[0] == 'age-keygen': return SimpleNamespace(stdout=self.record['restore_recipient'].encode())
            if argv[0] == 'systemctl': return SimpleNamespace(stdout='ActiveState=active\nSubState=running\nExecMainPID=42\n')
            return SimpleNamespace(stdout=b'{"sandboxes":[],"pageInfo":{"hasMore":false}}')
        with patch.object(key_holder, 'fingerprint', return_value='fingerprint'), patch.object(key_holder, 'secret_labels', return_value={'claude-token'}), patch.object(account_handoff, 'launch_accounts', return_value=(None, 1, {})), patch.object(cleanup, 'digest', return_value='a'), patch.object(holder.subprocess, 'run', side_effect=run), patch.object(holder.subprocess, 'Popen') as launch:
            self.assertEqual(holder.dispatch(self.policy, self.root, self.home, new['operation_id'], b'authored identity'), holder.TEMPFAIL)
            launch.assert_not_called()
            self.assertFalse(self.ops()[new['operation_id']]['dispatch_started'])
            self.ledger()
            launch.return_value = SimpleNamespace(stdin=io.BytesIO(), wait=lambda: 0)
            self.assertEqual(holder.dispatch(self.policy, self.root, self.home, new['operation_id'], b'authored identity'), 0)
            self.assertEqual(launch.call_count, 1)
            env = launch.call_args.kwargs['env']
            self.assertEqual(env['UNBUG_PILOT_PIN'], pilot.pin(self.policy))
            self.assertTrue(self.ops()[new['operation_id']]['dispatch_started'])

    def test_real_guard_preflight_refusal_has_no_row_and_does_not_deadlock(self):
        import test_boat_settlement as settlement
        edge = settlement.SettlementTests(); edge.setUp(); self.addCleanup(edge.doCleanups)
        old, path = self.failed()
        # A retained historical hold forces the real --check refusal before new.
        self.ledger({'/historical.json': dict(status='finished', usd='0.036', expires_at=9999999999)})
        before = (self.home / 'boat-reservations.json').read_bytes()
        script = '''set -eu
root=$1; n=1; ttl_hours=1; max_spend=4; label=pilot-refusal; purpose=case
. "$root/bin/boat-launch-guards.sh"
guard_init
'''
        result = subprocess.run(['sh', '-c', script, 'sh', str(ROOT)],
            env={**edge.env, 'UNBUG_CONTROL_HOME': str(self.home), 'UNBUG_LAUNCH_STATE': str(path)},
            capture_output=True, text=True, timeout=120)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('infrastructure liability unsettled', result.stderr)
        self.assertEqual((self.home / 'boat-reservations.json').read_bytes(), before)
        self.addCleanup(lambda: [p.unlink() for p in (ROOT / 'results/spend').glob('*-pilot-refusal.json')])
        self.assertTrue((path / 'spend-finished').exists())
        self.assertFalse(list(path.glob('new.*')))
        self.assertTrue(cleanup.preflight_clear(self.home, old))
        self.armed(self.reserve('k'))  # Real shell guard still independently retains historical hold.

    def test_window_closed_reservation_cleanup_survives_without_mutating_journal(self):
        op = self.reserve(); before = (self.directory / 'reservations.json').read_bytes()
        with patch.object(pilot, 'admission', side_effect=money.MoneyWait('pilot_window_closed')):
            with self.assertRaisesRegex(money.MoneyWait, 'pilot_window_closed'): self.armed(op)
            cleanup.observe_batch(self.policy, self.root, self.home, self.ops(), set())
        status = service._json(cleanup.location(self.home, op).with_suffix('.status.json'))
        self.assertEqual(status['state'], 'window_closed')
        self.assertEqual((self.directory / 'reservations.json').read_bytes(), before)

    def test_concurrent_reservations_cannot_create_two_live_operations(self):
        from concurrent.futures import ThreadPoolExecutor
        def attempt(job):
            try: return self.reserve(job)
            except money.MoneyWait: return None
        with ThreadPoolExecutor(2) as pool: outcomes = list(pool.map(attempt, ('j', 'k')))
        self.assertEqual(sum(o is not None for o in outcomes), 1)
        self.assertEqual(len(self.ops()), 1)

    def test_cap_and_ready_marker_mutations_are_detected(self):
        import tempfile
        mutations = (
            ('pilot', "counts[name] >= bounds['max_lifecycles_per_case']", "counts[name] > bounds['max_lifecycles_per_case']",
             'test_three_serial_initials_and_one_successor_each_caps_and_replay'),
            ('practice_cleanup', 'or marker != ready(policy, op, pid)', 'or False',
             'test_pending_settlement_status_gate_and_ready_binding'))
        for module, original, replacement, check in mutations:
            with self.subTest(module=module), tempfile.TemporaryDirectory() as temporary:
                source = (ROOT / 'factory' / (module + '.py')).read_text()
                self.assertIn(original, source)
                mutant = Path(temporary) / (module + '.py')
                mutant.write_text(source.replace(original, replacement))
                script = "import sys, unittest; sys.path[:0]=sys.argv[1:3]; import test_pilot_admission; import " + module + "; exec(compile(open(sys.argv[3]).read(), sys.argv[3], 'exec'), " + module + ".__dict__); unittest.main(module='test_pilot_admission', argv=['mutant', 'PilotTests.'+sys.argv[4]])"
                result = subprocess.run([sys.executable, '-B', '-c', script, str(ROOT / 'tests/factory'),
                    str(ROOT / 'factory'), str(mutant), check], capture_output=True, text=True, timeout=60)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('FAIL:', result.stderr)

    def test_unit_uses_same_cleanup_and_preserves_practice_service_fields(self):
        old = (ROOT / 'control' / cleanup.UNIT).read_text()
        new = (ROOT / 'control' / cleanup.PILOT_UNIT).read_text()
        for line in old.splitlines():
            if line.startswith(('Description=', 'ExecStart=', 'Environment=HOME=')): continue
            self.assertIn(line, new)
        self.assertIn('practice_cleanup.py --batch', new)
        self.assertIn('EnvironmentFile=/home/user/.unbug-control/pilot.env', new)
        self.assertIn('WantedBy=multi-user.target', new)
        self.assertNotIn('UNBUG_PILOT_PIN=', new)


if __name__ == '__main__': unittest.main()
