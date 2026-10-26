"""Finalize a synthetic collected successor; never read a live bundle or a key."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
EVIDENCE = REPO / 'results/infrastructure/2026-10-26-opencode-failover'
sys.path.insert(0, str(REPO / 'factory'))
import key_holder


class FinalizeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name); self.root = self.base / 'new'; self.old = self.base / 'collected'
        self.root.mkdir(); self.old.mkdir()
        spec = importlib.util.spec_from_file_location('finalize_failover_fixture', EVIDENCE / 'finalize-restore.py')
        self.module = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.module)
        self.module.ROOT = self.root
        self.case = self.module.CASE; self.worker = self.module.WORKER
        self.fixture = REPO / 'tests/factory/fixtures/opencode-failover'
        policy = json.loads((self.fixture / 'policy.restore.json').read_text())
        self.job = copy.deepcopy(next(iter(policy['jobs'].values())))
        args = self.job['args']; index = args.index('--founder-ruling-sha256'); del args[index:index + 2]
        args[args.index('--qualified-release') + 1] = str(self.root / 'candidate')
        self.job.update(opencode_account=2, opencode_limited_accounts=[1])
        policy.update(root=str(self.root), jobs={self.module.JOB: self.job})
        self.save(self.root / 'policy.restore.pending.json', policy)
        for name in key_holder.PINNED:
            source = REPO / name; destination = self.root / name
            if source.exists(): destination.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(source, destination)
        self.save(self.root / 'build.json', {'launch_ready': False})
        self.save(self.root / 'PREPARATION-BLOCKED.json', {'reason': 'not collected'})
        self.state = self.old / 'control-home/launches/source'
        self.state.mkdir(parents=True)
        self.save(self.state / 'launch.json', {'argv': self.job['args']})
        (self.state / 'ids').write_text(self.worker + '\n')
        self.card = json.loads((self.fixture / 'input-scorecard.json').read_text())
        self.save(self.old / 'input-scorecard.json', self.card)
        self.card['terminal_stop'] = self.card['continuation_budget']['terminal_stop'] = 'provider_limit:opencode/deepseek-v4.1-flash-free'
        self.card['status'] = 'stopped'; self.card['continuation_budget']['active'] = None
        self.card['recovery_config'].update(rounds=9, case_budget=70)
        self.card['case_budget']['limit_usd'] = 70
        (self.old / 'sealed').mkdir()
        archive = self.old / 'sealed' / (self.case + '.checkpoint.tar.gz.age')
        archive.write_bytes(b'synthetic collected successor ciphertext')
        self.card['sha256'] = hashlib.sha256(archive.read_bytes()).hexdigest()
        self.save(self.old / 'sealed' / (self.case + '.scorecard.json'), self.card)
        self.save(self.old / 'vm-current-sha256.json', {archive.name: 'a' * 64})
        self.holder = patch.object(key_holder, 'ROOT', self.root); self.holder.start(); self.addCleanup(self.holder.stop)

    @staticmethod
    def save(path, value):
        path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(value))

    def collected(self):
        for name in ('complete', self.worker + '.collected', self.worker + '.deleted'): (self.state / name).touch()
        self.save(self.old / 'results/spend/synthetic.deletions' / self.worker / 'deletion-completion.json',
                  {'targetId': self.worker, 'status': 'completed', 'completedAt': '2026-10-26T12:00:00Z'})

    def test_live_source_is_refused_before_sealed_copy(self):
        with self.assertRaisesRegex(ValueError, 'not complete'): self.module.finalize(self.old)
        self.assertFalse((self.root / 'sealed').exists())
        self.assertTrue((self.root / 'PREPARATION-BLOCKED.json').exists())

    def test_collected_exact_ledger_limits_and_account2(self):
        self.collected()
        with patch('builtins.print'): self.module.finalize(self.old)
        result = json.loads((self.root / 'FINALIZED.json').read_text())
        self.assertEqual(result['spent_usd'], self.card['case_budget']['spent_usd'])
        self.assertEqual(result['round_limit'], 9)
        self.assertEqual(result['case_budget_usd'], 70)
        self.assertEqual(result['opencode_account'], 2)
        self.assertFalse(result['launched'])
        self.assertEqual(json.loads((self.root / 'corrected-continuation-budget.json').read_text()), self.card['continuation_budget'])
        self.assertEqual(json.loads((self.root / 'sealed' / (self.case + '.scorecard.json')).read_text()), self.card)
        self.assertFalse((self.root / 'PREPARATION-BLOCKED.json').exists())
        with self.assertRaisesRegex(ValueError, 'already finalized'): self.module.finalize(self.old)

    def test_missing_deletion_and_stale_generation_refused(self):
        self.collected()
        archive = self.old / 'sealed' / (self.case + '.checkpoint.tar.gz.age')
        archive.write_bytes(b'changed after collection')
        with self.assertRaisesRegex(ValueError, 'generation mismatch'): self.module.finalize(self.old)
        self.assertFalse((self.root / 'FINALIZED.json').exists())


if __name__ == '__main__': unittest.main()
