"""Offline accounting exams. Saved deletion receipts are real; usage/list replies,
creation events and guard-produced state/ledger layouts are authored edge doubles.
No test qualifies the deleted-ID usage API or cash billing on live Boat.
"""
import copy
from decimal import Decimal
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'factory'))
import boat_lifecycle as life
import deployment_inventory as inventory

FIXTURE = ROOT / 'tests/factory/fixtures/isolation-settlement-cloud'
WORKER = 'bx_d6dzvjbc'


class SettlementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.home = self.base / 'control'; self.home.mkdir()
        self.state = self.home / 'launches/test'; self.state.mkdir(parents=True)
        self.record = self.base / 'spend.json'
        self.edge = self.base / 'provider-edge'
        self.edge.write_text('''#!/usr/bin/env python3
import json, os, pathlib, sys
base=pathlib.Path(os.environ['SETTLEMENT_BASE']); args=sys.argv[1:]
with (base/'calls').open('a') as out: out.write(json.dumps(args)+'\\n')
if args[0]=='billing': print('{"limits":{"creditBalanceSeconds":1000000}}')
elif args[0]=='new': print('{"event":"created","id":"bx_d6dzvjbc"}')
elif args[0]=='list':
    if (base/'fail-list').exists(): sys.exit(1)
    print((base/'inventory').read_text())
elif args[0]=='usage':
    if (base/'fail-usage').exists(): sys.exit(1)
    print((base/'usage').read_text())
elif args[0] in ('delete','deletion'):
    name='deletion-request.json' if args[0]=='delete' else 'deletion-completion.json'
    print(json.dumps({'operation':json.loads((pathlib.Path(os.environ['SETTLEMENT_FIXTURE'])/name).read_text())}))
else: sys.exit(99)
'''); self.edge.chmod(0o755)
        self.env = {**os.environ, 'UNBUG_CLOUD':'boat', 'UNBUG_CONTROL_HOME':str(self.home),
                    'UNBUG_LAUNCH_STATE':str(self.state), 'BOAT_CMD':str(self.edge),
                    'SETTLEMENT_BASE':str(self.base), 'SETTLEMENT_FIXTURE':str(FIXTURE)}
        (self.base / 'inventory').write_text('{"sandboxes":[],"pageInfo":{"hasMore":false}}')
        (self.base / 'usage').write_text('{"seconds":9361,"dollars":0.09361,"running":false}')

    def command(self, *args):
        return subprocess.run([str(ROOT / 'bin/boat-spend'), *map(str, args)], env=self.env,
                              capture_output=True, text=True, timeout=120)

    def check(self, record=None, cap='5', count='1'):
        state = self.state if record is None else self.state.parent / Path(record).stem
        state.mkdir(parents=True, exist_ok=True)
        return self.command('--check', count, '1', cap, record or self.record, state)

    def ledger(self):
        return json.loads((self.home / 'boat-reservations.json').read_text())

    def row(self):
        return self.ledger()['reservations'][str(self.record)]

    def admit(self, cap='5', count='1'):
        (self.state / 'ids').write_text('')
        result = self.check(cap=cap, count=count)
        self.assertEqual(result.returncode, 0, result.stderr)

    def proof(self, count=1):
        names = [WORKER] + (['worker-authored-2'] if count == 2 else [])
        (self.state / 'ids').write_text('\n'.join(names)+'\n')
        for serial, worker in enumerate(names, 1):
            (self.state / f'new.{serial}').write_text(json.dumps(dict(event='created', id=worker)))
            directory = self.record.with_suffix('.deletions') / worker; directory.mkdir(parents=True)
            for name in ('deletion-request.json', 'deletion-completion.json'):
                data = json.loads((FIXTURE / name).read_text())
                if worker != WORKER: data.update(targetId=worker, id='authored-op-2')
                (directory / name).write_text(json.dumps(data))

    def settle(self):
        return self.command('--settle', self.record, self.state)

    def finish(self):
        return self.command('--finish', self.record, '1', self.state / 'ids')

    def assertHeld(self):
        before = (self.home / 'boat-reservations.json').read_bytes()
        result = self.settle()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('infrastructure settlement unavailable', result.stderr)
        self.assertEqual(before, (self.home / 'boat-reservations.json').read_bytes())
        self.assertNotEqual(self.check(self.base / 'next.json').returncode, 0)

    def test_saved_receipts_settle_once_and_ledger_first_replay_repairs_mirror(self):
        self.admit(); self.proof()
        self.assertEqual(self.settle().returncode, 0)
        self.assertEqual(self.row()['actual_spend_usd'], '0.09361')
        self.assertEqual(self.row()['settlement']['workers'][0]['deletion_operation_id'],
                         json.loads((FIXTURE/'deletion-request.json').read_text())['id'])
        data = json.loads(self.record.read_text()); data.pop('settlement'); data['actual_spend_usd']=None
        self.record.write_text(json.dumps(data))  # ledger-first crash before mirror
        before = (self.base/'calls').read_bytes()
        self.assertEqual(self.settle().returncode, 0)
        self.assertEqual((self.base/'calls').read_bytes(), before)
        self.assertEqual(self.finish().returncode, 0)
        self.assertEqual(self.row()['status'], 'settled')
        self.assertEqual(json.loads(self.record.read_text())['actual_spend_usd'], .09361)
        report = inventory.scan_ledger(self.home/'boat-reservations.json', time.time())
        self.assertEqual(report['state'], 'ok'); self.assertEqual(report['settled_usd'], '0.09361')
        self.assertEqual(self.check(self.base/'second-batch.json').returncode, 0)

    def test_cumulative_exact_boundary_and_larger_new_cap_cannot_reset(self):
        self.admit(cap='.12961'); self.proof(); self.assertEqual(self.settle().returncode, 0)
        self.assertEqual(self.check(self.base/'new-batch.json', cap='100').returncode, 0)
        self.assertEqual(self.row()['actual_spend_usd'], '0.09361')

    def test_one_cent_over_and_actual_overcap_stay_recorded(self):
        for cost in ('.10361', '6'):
            with self.subTest(cost=cost):
                # Independent home per arithmetic exam, never a recovery path.
                other = SettlementTests(); other.setUp()
                try:
                    other.admit(cap='.12961'); other.proof()
                    (other.base/'usage').write_text(json.dumps(dict(seconds=1,dollars=float(cost),running=False)))
                    self.assertEqual(other.settle().returncode, 0)
                    self.assertEqual(Decimal(other.row()['actual_spend_usd']), Decimal(cost))
                    self.assertNotEqual(other.check(other.base/'other-batch.json', cap='100').returncode, 0)
                finally: other.doCleanups()

    def test_bad_usage_and_identity_keep_hold(self):
        self.admit(); self.proof()
        for raw in ('{"running":false,"seconds":1,"dollars":true}',
                    '{"running":false,"seconds":1,"dollars":"0.1"}',
                    '{"running":false,"seconds":1,"dollars":NaN}',
                    '{"running":false,"seconds":1,"dollars":-1}',
                    '{"running":true,"seconds":1,"dollars":0.1}',
                    '{"running":false,"seconds":true,"dollars":0.1}',
                    '{"running":false,"seconds":1,"dollars":0.1,"sandboxId":"wrong"}',
                    '{"running":false,"seconds":1,"dollars":1,"dollars":0}'):
            with self.subTest(raw=raw):
                (self.base/'usage').write_text(raw); self.assertHeld()
        (self.base/'fail-usage').touch(); self.assertHeld()

    def test_creation_deletion_inventory_and_binding_negative_controls(self):
        self.admit(); self.proof()
        for name in ('new.2.pending', 'new.bad'):
            path=self.state/name; path.symlink_to(self.base/'absent')
            self.assertHeld(); path.unlink()
        path=self.state/'new.1'; original=path.read_bytes()
        path.write_text('not json'); self.assertHeld(); path.write_bytes(original)
        done=self.record.with_suffix('.deletions')/WORKER/'deletion-completion.json'
        original=done.read_bytes(); data=json.loads(original); data['targetId']='wrong'
        done.write_text(json.dumps(data)); self.assertHeld(); done.write_bytes(original)
        (self.base/'inventory').write_text('{"sandboxes":[],"pageInfo":{"hasMore":true}}'); self.assertHeld()
        result=self.command('--settle', self.record, self.base)
        self.assertNotEqual(result.returncode, 0)

    def test_reserved_empty_and_partial_slots_refuse(self):
        self.admit(count='2'); self.assertHeld()
        self.proof(); self.assertHeld()

    def test_no_creation_finish_without_monitor_and_symlink_refusal(self):
        self.admit(); self.assertFalse((self.state/'monitor.sh').exists())
        (self.state/'new.1.pending').symlink_to(self.base/'absent')
        self.assertEqual(self.finish().returncode, 0)
        self.assertEqual(self.row()['status'], 'finished')
        self.assertHeld(); (self.state/'new.1.pending').unlink()
        self.assertEqual(self.settle().returncode, 0)
        self.assertEqual(self.row()['settlement']['basis'], 'no_creation')
        self.assertEqual(self.row()['actual_spend_usd'], '0')

    def test_real_guard_created_lifecycle_finishes_and_publishes_when_usage_unknown(self):
        script = '''set -eu
root=$1; n=1; ttl_hours=1; max_spend=5; label=test; purpose=case
. "$root/bin/exam-launch-guards.sh"
collect_vm() { touch "$state/collected-by-test-edge"; }
guard_init
guard_new
guard_exit 0
'''
        (self.base/'fail-usage').touch()
        result=subprocess.run(['sh','-c',script,'sh',str(ROOT)], env=self.env,
                              capture_output=True,text=True,timeout=120)
        ledger=self.ledger()
        self.addCleanup(lambda: [Path(k).unlink(missing_ok=True) for k in ledger['reservations']])
        self.assertEqual(result.returncode,0,result.stderr)
        self.record=Path(next(iter(ledger['reservations'])))
        self.assertEqual(self.row()['status'],'finished')
        self.assertTrue((self.state/'complete').exists())
        self.assertTrue((self.state/'collected-by-test-edge').exists())
        (self.base/'fail-usage').unlink()
        self.assertEqual(self.settle().returncode,0)
        self.assertEqual(self.row()['actual_spend_usd'],'0.09361')

    def test_malformed_settlement_never_becomes_admission_authority(self):
        self.admit(); self.proof(); self.assertEqual(self.settle().returncode,0)
        original=self.ledger()
        changes=[lambda r: r.update(actual_spend_usd='0'),
                 lambda r: r['settlement'].update(extra=True),
                 lambda r: r['settlement']['workers'][0].update(seconds=True),
                 lambda r: r['settlement']['workers'].append(r['settlement']['workers'][0].copy())]
        ledger_path=self.home/'boat-reservations.json'
        for change in changes:
            bad=copy.deepcopy(original); change(bad['reservations'][str(self.record)])
            ledger_path.write_text(json.dumps(bad))
            report=inventory.scan_ledger(ledger_path,time.time())
            self.assertEqual(report['state'],'invalid')
            result=self.check(self.base/'next.json')
            self.assertNotEqual(result.returncode,0)
            self.assertIn('invalid reservation ledger',result.stderr)
        ledger_path.write_text(json.dumps(original))

    def test_real_guard_exit_between_check_and_monitor_write(self):
        script='''set -eu
root=$1; n=1; ttl_hours=1; max_spend=5; label=test; purpose=case
. "$root/bin/exam-launch-guards.sh"
guard_init
'''
        # Margin validation is the real exit after admission and before monitor.
        result=subprocess.run(['sh','-c',script,'sh',str(ROOT)],
            env={**self.env,'BOAT_TTL_MARGIN_SECONDS':'invalid'}, capture_output=True,text=True,timeout=120)
        self.assertNotEqual(result.returncode,0)
        self.assertFalse((self.state/'monitor.sh').exists())
        row=next(iter(self.ledger()['reservations'].values()))
        self.assertEqual(row['status'],'settled'); self.assertEqual(row['actual_spend_usd'],'0')
        self.addCleanup(lambda: [Path(k).unlink(missing_ok=True) for k in self.ledger()['reservations']])


    def test_two_workers_partial_usage_never_commits(self):
        self.admit(count='2'); self.proof(count=2)
        (self.base/'usage').write_text(json.dumps(dict(id=WORKER,seconds=1,dollars=.1,running=False)))
        self.assertHeld()

    def test_hetzner_existing_record_behavior_unchanged(self):
        hcloud=self.base/'hcloud'
        price=json.dumps(dict(prices=[dict(location='fsn1',price_hourly=dict(gross='0.01'))]))
        hcloud.write_text('#!/usr/bin/env python3\nprint('+repr(price)+')\n')
        hcloud.chmod(0o755)
        env={**self.env,'BOAT_CMD':'hcloud-boat','HCLOUD_PLACES':'cx33@fsn1',
             'PATH':str(self.base)+os.pathsep+self.env['PATH']}
        for _ in range(2):
            result=subprocess.run([str(ROOT/'bin/boat-spend'),'--check','1','1','5',str(self.record)],
                                  env=env,capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stderr)
        self.assertFalse((self.home/'boat-reservations.json').exists())

    def test_concurrent_successors_only_one_admits(self):
        self.admit(); self.assertEqual(self.finish().returncode,0)
        ps=[subprocess.Popen([str(ROOT/'bin/boat-spend'),'--check','1','1','5',str(self.base/f'new-{i}.json'),str(self.state.parent/f'new-{i}')],
            env=self.env,stdout=subprocess.PIPE,stderr=subprocess.PIPE) for i in range(2)]
        for p in ps: p.communicate(timeout=120)
        self.assertEqual(sorted(p.returncode for p in ps),[0,1])


if __name__ == '__main__': unittest.main()
