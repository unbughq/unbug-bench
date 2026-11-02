"""Real D consumer integration. --consumer-root accepts its reviewed factory tree.

No stub reader. Until D merges, an ordinary suite reports the missing prerequisite;
the explicit cross-branch run is required and is repeated before enablement.
"""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
consumer = os.environ.get('UNBUG_TEST_D_CONSUMER_ROOT')
if '--consumer-root' in sys.argv:
    index = sys.argv.index('--consumer-root'); consumer = Path(sys.argv[index + 1])
    del sys.argv[index:index + 2]
if consumer:
    sys.path.insert(0, str(consumer))
    import job_authority  # Load the actual D reader and its real budget dependency first.
sys.path.insert(0, str(ROOT / 'factory'))
try:
    import job_authority
except ImportError:
    job_authority = None
import job_config as config
from budget import BudgetError


@unittest.skipIf(job_authority is None, 'D consumer not merged; explicit --consumer-root run required; enablement blocked')
class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name); self.factory = self.home / 'factory'
        (self.factory / 'batches').mkdir(parents=True)
        self.patch = patch.object(config, 'FACTORY', self.factory); self.patch.start(); self.addCleanup(self.patch.stop)
        self.case = 'case-practice-a'; self.work = self.home / 'work' / self.case; self.work.mkdir(parents=True)
        self.channel = dict(schema=1, batch='practice', job='a', case=self.case,
                            reservation_id=str(uuid.uuid4()), revision=1, source_generation=None,
                            committed_total_usd='50.000000000', batch_deadline='2099-01-01T00:00:00Z')
        recipient = (ROOT / 'factory/control-recipient.txt').read_text().strip()
        (self.factory / 'control-recipient.txt').write_text(recipient)
        record = dict(schema=1, id='practice', money_limit_usd='100.000000000',
                      batch_deadline=self.channel['batch_deadline'], max_concurrency=1, target_slots=1,
                      restore_recipient=recipient, jobs={'a': dict(mode='batch', case=self.case,
                          requested_total_usd='50.000000000', max_calls=100, args=['1'])})
        raw = json.dumps(record).encode(); (self.factory / 'batches/practice.json').write_bytes(raw)
        self.manifest_sha = hashlib.sha256(raw).hexdigest()
        worker = json.dumps({'files': {'factory/batches/practice.json': self.manifest_sha}}).encode()
        (self.home / 'worker-release-manifest.json').write_bytes(worker)
        release = json.dumps({'files': {'worker-release-manifest.json': hashlib.sha256(worker).hexdigest()}}).encode()
        (self.home / 'batch-release.json').write_bytes(release)
        self.release_sha = hashlib.sha256(release).hexdigest()
        self.path = self.home / 'ram/factory-job.json'
        self.args = SimpleNamespace(batch_release_sha256=self.release_sha,
                                    factory_job_config=str(self.path), factory_job_config_sha256=None, resume=None)
        self.c = SimpleNamespace(case_id=self.case, card={}, work=self.work)
        self.deliver()

    def deliver(self):
        value = dict(schema=1, batch_id='practice', job_id='a', case_id=self.case,
                     batch_deadline=self.channel['batch_deadline'], source_generation=self.channel['source_generation'],
                     batch_release_sha256=self.release_sha, manifest_sha256=self.manifest_sha,
                     job_money=dict(self.channel))
        raw = json.dumps(value).encode(); pin = hashlib.sha256(raw).hexdigest()
        config.deliver(raw, pin, self.path)
        self.args.factory_job_config_sha256 = pin

    def restored(self, total=1):
        # Authored transport receipt; genuine importer validation is tested separately.
        from carry_over import digest
        saved = json.loads((self.work / 'job-money.json').read_text())
        public = dict(case=self.case, sha256=self.channel['source_generation'], job_money=saved,
                      case_budget=dict(total_spent_usd=total))
        sealed = self.home / 'sealed'; sealed.mkdir(exist_ok=True)
        self.c.ledger = sealed / (self.case + '.continuation-budget.json')
        (sealed / (self.case + '.restore-scorecard.json')).write_text(json.dumps(public))
        (sealed / (self.case + '.restore-accounting.json')).write_text(json.dumps(dict(
            case=self.case, generation=self.channel['source_generation'], accounting_authenticated=True,
            public_card_sha256=digest(public))))

    def test_null_source_same_revision_and_old_source_refusal(self):
        config.install(self.c, self.args); self.args.resume = self.case
        self.channel['source_generation'] = 'a' * 64; self.deliver(); self.restored(None)
        config.install(self.c, self.args)
        self.assertEqual(self.c.job_money['revision'], 1)
        self.channel['source_generation'] = 'b' * 64; self.deliver(); self.restored(None)
        config.install(self.c, self.args)
        self.channel['source_generation'] = 'a' * 64; self.deliver(); self.restored(None)
        with self.assertRaises(BudgetError): config.install(self.c, self.args)

    def test_source_change_needs_matching_restored_receipt(self):
        config.install(self.c, self.args); self.args.resume = self.case
        self.channel.update(revision=2, source_generation='a' * 64); self.deliver()
        with self.assertRaises(BudgetError): config.install(self.c, self.args)
        self.restored()
        path = self.home / 'sealed' / (self.case + '.restore-accounting.json')
        receipt = json.loads(path.read_text()); receipt['generation'] = 'b' * 64
        path.write_text(json.dumps(receipt))
        with self.assertRaises(BudgetError): config.install(self.c, self.args)

    def test_fresh_is_separate_checkpoint_state_and_actual_d_admits(self):
        config.install(self.c, self.args)
        authority = job_authority.for_case(self.c)
        self.assertEqual(authority.revision, 1)
        self.assertEqual(self.c.job_money, self.c.authenticated_job_config['job_money'])
        self.assertIsNot(self.c.job_money, self.c.authenticated_job_config['job_money'])
        self.assertEqual(json.loads((self.work / 'job-money.json').read_text()), self.channel)
        self.assertEqual(self.c.batch_id, 'practice'); self.assertEqual(self.c.job_id, 'a')
        self.assertIsNone(self.c.source_generation)
        import model_router
        with patch.dict(os.environ, FACTORY_BATCH_ID='forged', FACTORY_JOB_ID='forged',
                        FACTORY_BATCH_DEADLINE='2000-01-01T00:00:00Z'):
            self.assertEqual(model_router.metadata(self.c), ('practice', 'a', 4070908800))
        self.c.job_money['committed_total_usd'] = '99.000000000'
        with self.assertRaises(BudgetError): job_authority.for_case(self.c)

    def test_revision_bump_history_repair_and_same_revision_replay(self):
        config.install(self.c, self.args)
        self.args.resume = self.case
        self.channel.update(revision=2, source_generation='a' * 64)
        self.deliver(); self.restored()
        real = config.atomic_json
        def interrupted(path, value):
            if path.name == 'job-money.json': raise OSError('authored interrupted local transition')
            return real(path, value)
        with patch.object(config, 'atomic_json', interrupted), self.assertRaises(BudgetError):
            config.install(self.c, self.args)
        self.assertEqual(json.loads((self.work / 'job-money.json').read_text())['revision'], 1)
        config.install(self.c, self.args)
        self.assertEqual(job_authority.for_case(self.c).revision, 2)
        config.install(self.c, self.args)
        self.assertEqual(len(json.loads((self.work / 'job-money-history.json').read_text())), 1)
        self.channel['committed_total_usd'] = '61.000000000'; self.deliver()
        with self.assertRaises(BudgetError): config.install(self.c, self.args)
        with self.assertRaises(BudgetError): job_authority.for_case(self.c)

    def test_stale_lowered_missing_and_retired_cannot_admit(self):
        config.install(self.c, self.args); self.args.resume = self.case
        self.channel.update(revision=2, source_generation='a' * 64); self.deliver(); self.restored()
        config.install(self.c, self.args)
        self.channel.update(revision=1, source_generation=None); self.deliver()
        with self.assertRaises(BudgetError): config.install(self.c, self.args)
        self.channel.update(revision=3, source_generation='b' * 64, committed_total_usd='49.000000000'); self.deliver()
        with self.assertRaises(BudgetError): config.install(self.c, self.args)
        (self.work / 'job-money.json').unlink()
        with self.assertRaises(BudgetError): config.install(self.c, self.args)
        self.c.checkpoint_card = {'terminal_stop': 'retired_batch_bound'}
        with self.assertRaises(BudgetError): config.install(self.c, self.args)

    def test_config_hash_case_mode_and_host_source_binding(self):
        config.host_check(self.path, self.args.factory_job_config_sha256, self.case, None, self.release_sha)
        with self.assertRaises(ValueError):
            config.host_check(self.path, self.args.factory_job_config_sha256, self.case, 'b' * 64, self.release_sha)
        self.path.write_bytes(self.path.read_bytes() + b' ')
        with self.assertRaises(BudgetError): config.install(self.c, self.args)
        self.deliver(); self.c.case_id += '-wrong'
        with self.assertRaises(BudgetError): config.install(self.c, self.args)
        self.c.case_id = self.case; self.path.chmod(0o644)
        with self.assertRaises(BudgetError): config.install(self.c, self.args)
        self.path.chmod(0o600); self.args.factory_job_config = None
        with self.assertRaises(BudgetError): config.install(self.c, self.args)


if __name__ == '__main__': unittest.main()
