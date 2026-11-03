"""Startup smoke (docs/designs/startup-smoke.md): the -3 batch, its money, accounting and sealing.

Real artifacts: the retained -2 manifest upgraded to -3, the tracked -3 manifest,
the real control recipient, the canary6 collected card and real age. Release
verification, systemd, Boat and the launcher child are the HolderTests doubles.
"""
from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin')]
import batch
import batch_holder as holder
import batch_money as money
import batch_service as service
import budget
import job_authority
import model_runtime
import practice
import practice_cleanup as cleanup
import practice_preflight as preflight
import run
from batch_accounting import collection_facts
from launch_manifest import collection_files
from run_artifacts import RunArtifacts
import test_practice_readiness as readiness
from test_batch_holder import HolderTests

PREVIOUS = ROOT / 'factory/batches/b-plumbing-practice-2.json'
CANARY = ROOT / 'tests/factory/fixtures/canary6-collected-card.json'


class Clock(datetime):
    """Before the -3 deadline, so the real manifest stays admissible after 2026-11-07."""
    @classmethod
    def now(cls, tz=None): return datetime(2026, 11, 3, 12, tzinfo=timezone.utc)


def upgrade(previous):
    """The design's -2 to -3 change, applied to the retained -2 manifest."""
    record = deepcopy(previous)
    record['id'] = 'b-plumbing-practice-3'
    job = record['jobs']['practice']
    job.update(case='case-b-plumbing-practice-3-practice', requested_total_usd='19.980000000')
    smoke = dict(deepcopy(job), case='case-b-plumbing-practice-3-smoke', requested_total_usd='0.010000000',
                 args=job['args'] + ['--dry-run'])
    record['jobs'] = dict(smoke=smoke, practice=job)
    record['practice_admission']['jobs'] = dict(
        smoke=dict(baseline_usd='0.000000000', incremental_usd='0.010000000'),
        practice=dict(baseline_usd='0.000000000', incremental_usd='19.980000000'))
    return record


class SmokeTests(unittest.TestCase):
    setUpBase = HolderTests.setUpBase
    freeze = HolderTests.freeze
    answers = HolderTests.answers
    holder_setUp = HolderTests.setUp
    practice_policy = readiness.PracticeTests.practice_policy

    def setUp(self):
        self.holder_setUp()
        for module in (holder, practice, job_authority):
            clock = patch.object(module, 'datetime', Clock); clock.start(); self.addCleanup(clock.stop)
        self.record = json.loads((ROOT / preflight.MANIFEST).read_text())
        self.policy = self.practice_policy(self.record)

    def reserve(self, name):
        return holder.reserve(self.policy, self.root, self.home, name, None)

    def context(self, op, *, dry_run=True):
        """Runner context as job_config installs it for a batch job (authority from the real reservation)."""
        return SimpleNamespace(
            args=SimpleNamespace(batch_release_sha256=self.policy['batch']['sha256'], dry_run=dry_run),
            job_money=op['authority'], authenticated_job_config=dict(job_money=op['authority']),
            batch_deadline=self.record['batch_deadline'], batch_id=self.record['id'], job_id=op['job'],
            case_id=op['case'], source_generation=None, card={}, work=self.root / 'work',
            ledger=self.root / 'work/absent-ledger.json')

    def test_previous_manifest_upgrades_to_tracked_minus_3(self):
        record = upgrade(json.loads(PREVIOUS.read_text()))
        self.assertEqual(record, self.record)
        self.assertTrue(practice.matches(record))
        self.assertEqual(money.manifest(self.policy, self.root), record)

    def test_both_jobs_admit_and_smoke_dispatch_adds_only_dry_run(self):
        smoke = self.reserve('smoke')
        self.assertEqual(smoke['authority']['committed_total_usd'], '0.010000000')
        calls = []
        def run_(argv, **kwargs):
            data = (self.record['restore_recipient'].encode() if argv[0] == 'age-keygen' else
                    json.dumps(dict(sandboxes=[], pageInfo=dict(hasMore=False))).encode())
            return SimpleNamespace(stdout=data)
        def popen(argv, **kwargs):
            calls.append(argv)
            return SimpleNamespace(stdin=io.BytesIO(), wait=lambda: 0)
        import account_handoff
        import key_holder
        self.policy.update(code_sha256='fingerprint', path='/usr/bin:/bin', recipient='founder-public')
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, {}, clear=True))
            stack.enter_context(patch.object(key_holder, 'fingerprint', return_value='fingerprint'))
            stack.enter_context(patch.object(key_holder, 'secret_labels', return_value={'claude-token'}))
            stack.enter_context(patch.object(account_handoff, 'launch_accounts', return_value=(None, 1, {})))
            stack.enter_context(patch.object(holder.subprocess, 'run', side_effect=run_))
            stack.enter_context(patch.object(holder.subprocess, 'Popen', side_effect=popen))
            self.assertEqual(holder.dispatch(self.policy, self.root, self.home, smoke['operation_id'], b'test identity'), 0)
        [argv] = calls
        self.assertEqual(argv[:2], ['/bin/sh', str(self.root / 'factory/launch.sh')])
        smoke_args = argv[2:argv.index('--factory-job-config')]
        practice_args = batch.bind(self.policy, 'practice', None, self.root)['args']
        expected = [a.replace('-practice-3-smoke', '-practice-3-practice') for a in smoke_args if a != '--dry-run']
        self.assertEqual(smoke_args.count('--dry-run'), 1)
        self.assertEqual(expected, practice_args)
        # Practice admits next, inside the same $19.99 with the smoke's 0.01 still held.
        holder.record_exit(self.policy, self.root, self.home, smoke['operation_id'], 0)
        with money.locked(self.home, self.record['id']) as directory:
            ops = holder._operations(directory, self.record, self.policy)
            ops[smoke['operation_id']].update(state='failed')  # Authored end of the smoke; holder retirement is tested elsewhere.
            holder._save(directory, self.record, self.policy, ops)
        second = self.reserve('practice')
        self.assertEqual(second['authority']['committed_total_usd'], '19.980000000')
        with money.locked(self.home, self.record['id']) as directory:
            state = money.load_locked(directory, self.record, self.policy['batch']['manifest_sha256'])
        self.assertEqual(money.aggregate(state), money.amount('19.990000000'))

    def test_smoke_budget_passes_the_boundary_before_g1(self):
        c = self.context(self.reserve('smoke'))
        model_runtime.case_budget_boundary(c)  # What gate_pipeline runs before G1; spend is zero.
        free = dict(c.job_money, committed_total_usd='0.000000000')
        c.job_money, c.authenticated_job_config = free, dict(job_money=free)
        with self.assertRaisesRegex(budget.BudgetError, '^money_wait$'):
            model_runtime.case_budget_boundary(c)  # Why the smoke is not a $0 job.

    def test_dry_run_accounting_collects_at_zero_and_missing_ledger_still_refused(self):
        op = self.reserve('smoke')
        card = json.loads(CANARY.read_text())
        del card['continuation_budget']
        for dry_run in (True, False):
            with self.subTest(dry_run=dry_run):
                c = self.context(op, dry_run=dry_run)
                c.card = deepcopy(card); c.work.mkdir(exist_ok=True)
                run.finalize_accounting(c)
                self.assertNotIn('cleanup_errors', c.card)
                self.assertEqual(c.card['terminal_stop'], card['terminal_stop'])  # Canary's own stop is kept.
                previous = dict(total_usd='0.000000000', estimated={})  # authorize_locked's first previous.
                if dry_run:
                    self.assertEqual(c.card['continuation_budget'], {'cost': 0, 'calls': 0, 'events': []})
                    facts = collection_facts(c.card, previous, op['authority']['committed_total_usd'], budget)
                    self.assertEqual(facts['total_usd'], '0.000000000')
                else:
                    self.assertIsNone(c.card['continuation_budget'])
                    with self.assertRaisesRegex(ValueError, '^invalid_accounting_input$'):
                        collection_facts(c.card, previous, op['authority']['committed_total_usd'], budget)

    def test_batch_dry_run_seal_wraps_case_key_and_collection_accepts_card(self):
        if not shutil.which('age'): self.skipTest('real age absent')
        op = self.reserve('smoke')
        c = self.context(op)
        c.work = self.root / 'home/work' / op['case']; (c.work / 'logs').mkdir(parents=True)
        (c.work / 'logs/runner.log').write_text('dry run\n')
        sealed = self.root / 'home/sealed'; sealed.mkdir()
        c.keyfile = sealed / (op['case'] + '.throwaway-key.txt')
        subprocess.run(['age-keygen', '-o', str(c.keyfile)], capture_output=True, check=True)
        c.recipient = subprocess.check_output(['age-keygen', '-y', str(c.keyfile)], text=True).strip()
        c.card = dict(case=op['case'], batch_release_sha256=c.args.batch_release_sha256)
        c.t0 = 0
        artifacts = RunArtifacts(home=self.root / 'home', bench=self.root / 'bench', sealed=sealed,
                                 statements_recipient=self.root / 'absent', agent_state=(), pilot_homes=lambda: [],
                                 pilot_wall=None, factory_slots=lambda c: 1, retain_delivery=None,
                                 cleanup=lambda path, sudo=False: shutil.rmtree(path, ignore_errors=True))
        with patch('r2_upload.upload', return_value=None) as upload:  # Offline: no R2.
            artifacts.seal(c)
        upload.assert_called_once()
        self.assertEqual(c.card['dry_run_roundtrip']['identical'], True)
        # The case key is wrapped to the throwaway key, and it opens the archive.
        identity = subprocess.check_output(['age', '-d', '-i', str(c.keyfile), str(sealed / (op['case'] + '.casekey.age'))])
        key = self.root / 'case.identity'; key.write_bytes(identity)
        subprocess.run(['age', '-d', '-i', str(key), c.card['archive']], capture_output=True, check=True)
        service.atomic_json(sealed / (op['case'] + '.scorecard.json'), c.card)
        names = {p.name for p in sealed.iterdir()} & collection_files(op['case'])
        self.assertNotIn(c.keyfile.name, names)
        card, archive = service._card(sealed, names, op['case'], c.args.batch_release_sha256)
        self.assertEqual(archive, op['case'] + '.tar.gz.age')

    def test_no_previous_batch_id_at_hard_coded_sites(self):
        for text in ((ROOT / 'control' / cleanup.UNIT).read_text(), preflight.DROPIN,
                     (ROOT / 'factory/practice.py').read_text()):
            self.assertNotIn('b-plumbing-practice-2', text)
            self.assertIn('b-plumbing-practice-3', text)

    @unittest.skipUnless(os.environ.get('UNBUG_LOCAL_DOCKER_SMOKE') == '1',
                         'explicit local qualification: UNBUG_LOCAL_DOCKER_SMOKE=1; shared Docker project')
    def test_local_real_dry_run_startup_reaches_g1(self):
        """Real run.py --dry-run against local Docker, stopped just after a real G1.

        Run explicitly on a quiet daemon, outside concurrent offline suites.
        Uses the real unbug-bench Compose project and ports on the local daemon,
        as a worker does, and removes it afterwards. The Medusa build uses the
        local deps image for this lock, so it needs no network.
        """
        lock = hashlib.sha256((ROOT / 'projects/medusa/package-lock.json').read_bytes()).hexdigest()
        bootstrap = r'''
import json, pathlib, sys
import run
from budget import BudgetError
root = pathlib.Path(sys.argv[1]); run.HOME = root; run.SEALED = root / 'sealed'
real = run.g1
def g1(c):
    result = real(c)
    (root / 'g1.json').write_text(json.dumps(result[0]))
    raise BudgetError('stopped_after_g1')
run.g1 = g1
run.wipe = lambda c: None
sys.argv = ['run.py', '--source', 'port', '--dry-run']
run.main()
'''
        compose = ['docker', 'compose', '-f', str(ROOT / 'projects/medusa/compose.yaml')]
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            try:
                result = subprocess.run([sys.executable, '-c', bootstrap, str(root)], cwd=ROOT / 'factory',
                                        env={**os.environ, 'BENCH': str(ROOT), 'HOME': str(root),
                                             'DOCKER_CONFIG': os.environ.get('DOCKER_CONFIG', str(Path.home() / '.docker')),
                                             'MEDUSA_DEPS_IMAGE': 'unbug-bench-medusa-deps:' + lock,
                                             'PYTHONPATH': str(ROOT / 'factory') + os.pathsep + str(ROOT / 'bin')},
                                        capture_output=True, text=True, timeout=1800)
                card = json.loads(next((root / 'sealed').glob('*.scorecard.json')).read_text())
                self.assertEqual(card['terminal_stop'], 'stopped_after_g1',
                                 (result.stderr[-2000:], (next((root / 'work').iterdir()) / 'logs/runner.log').read_text()[-4000:]))
                self.assertEqual(result.returncode, 0, result.stderr[-4000:])
                self.assertTrue(json.loads((root / 'g1.json').read_text()))
                self.assertTrue(card['dry_run_roundtrip']['identical'])
            finally:
                subprocess.run([*compose, 'down', '-v', '--remove-orphans'], capture_output=True, timeout=300,
                               env={**os.environ, 'DOCKER_CONFIG': os.environ.get('DOCKER_CONFIG', str(Path.home() / '.docker'))})


del HolderTests
if __name__ == '__main__': unittest.main()
