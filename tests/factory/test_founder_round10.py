"""Chained founder receipt and offline replay of the already-open real round-9 state."""
import copy
import os
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin')]
import founder_ruling
import restore_ledger
import run
import bench
import factory_pool
import key_holder

PRIVATE = Path('/private/tmp/claude-501/-Users-bugsincode-Developer-unbug-bench/00d02e9b-ca70-4919-b958-898ec30f1b3a/scratchpad/e15450-open/checkpoint/case-20261024T043353Z-e15450')
DIAGNOSIS = PRIVATE.parents[2] / 'e15450-diagnosis/report.md'
FIXTURE = Path(__file__).parent / 'fixtures/e15450-round9-collected-card.json'


def read(p): return json.loads(p.read_text())
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p, value): p.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def make_record(card, work):
    prior = card['founder_ruling']
    return dict(version=2, authority='founder-2026-10-26', sequence=2, case=card['case'],
        generation=card['sha256'], public_card_sha256=restore_ledger.digest(card),
        ledger_sha256=restore_ledger.digest(card['continuation_budget']),
        prior_ruling_sha256=prior['authorization']['sha256'], prior_receipt_sha256=restore_ledger.digest(prior),
        allowances=dict(case_budget_usd=70, round_limit=10), case_spent_usd=46.809458182,
        infrastructure_waste_usd=0,
        resume=dict(round=9, attack_state_sha256=sha(work / 'attack-state.json'),
                    attack_state_record_sha256=restore_ledger.digest(read(work / 'attack-state.json')),
                    case_sha256=run.case_hash(SimpleNamespace(case=work / 'case'))),
        diagnosis=dict(path=str(DIAGNOSIS), sha256='6ff5c019747548f12aa3bf0692ea7b9910fb52db8f867de5939bfc749a799366'),
        reason='Founder approved one more writer/stress round (10) at a $70 case budget. '
               'Writer-round reservation was overly conservative for repair rounds. '
               'Factory stress-loop defects: validation failures counted as case findings; no family-level '
               'repair rule; saved cheats not re-run after repairs. Other allowances are preserved.')


def replay(card, record, *, blocking=False, stress_cost=0, early_failure=None, private=None):
    """Real metadata/case inputs; paid models and Docker execution are stubbed.

    Never decrypt or export case text. Temporary copies remain outside the repo.
    The real gate pipeline and retained-cheat iterator run with controlled verdicts.
    """
    private = private or PRIVATE
    pending = record['resume'].get('pending_writer', False)
    saved_round = record['resume']['round']; next_round = saved_round + 1
    assert sha(private / 'attack-state.json') == record['resume']['attack_state_sha256']
    with tempfile.TemporaryDirectory(prefix='e15450-round10-') as tmp:
        home = Path(tmp); home.chmod(0o700)
        # Freeze real public source locally so production bench_manifest does not
        # traverse unrelated historical result trees or installed dependencies.
        manifest = ROOT / 'candidate-vm-canary/source-manifest.json'
        if not manifest.exists():
            manifest = ROOT / 'results/infrastructure/2026-10-26-restore-perms/final/release/candidate/source-manifest.json'
        bench_root = home / 'unbug-bench'
        for name in read(manifest)['files']:
            target = bench_root / name; target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, target)
        work = home / 'work' / card['case']; work.mkdir(parents=True)
        (work / 'logs').mkdir()
        shutil.copytree(private / 'case', work / 'case')
        for name in ('attack-state.json', 'scorecard.json', 'continuation-budget.json',
                     'founder-ruling-applied.json', 'freshness-repair.json'):
            if (private / name).exists(): shutil.copy2(private / name, work / name)
        shutil.copytree(private / 'attacks', work / 'attacks')
        if (private / 'diagnostic-budgets').exists():
            shutil.copytree(private / 'diagnostic-budgets', work / 'diagnostic-budgets')
        ruling = home / 'ruling.json'; save(ruling, record); pin = sha(ruling)
        before_attack = read(work / 'attack-state.json')
        before_fresh = (work / 'freshness-repair.json').read_bytes()
        receipt = restore_ledger.install(work, home / 'sealed', card['case'], card['sha256'], card,
            ruling_path=ruling, ruling_sha256=pin)
        assert receipt['attempt_allowances_authenticated']
        assert (work / 'freshness-repair.json').read_bytes() == before_fresh
        assert read(work / 'attack-state.json') == {**before_attack, 'round_limit': next_round}
        args = SimpleNamespace(**{**card['recovery_config'], 'resume': card['case'], 'source': card['source'],
            'dry_run': False, 'skip_build': False, 'rounds': next_round, 'case_budget': 70, 'bench_workers': 2,
            'concurrent_roles': False, 'seed': card['seed'], 'no_early_probe': True})
        c = SimpleNamespace(case_id=card['case'], case=work / 'case', work=work, card=copy.deepcopy(card),
            ledger=home / 'sealed' / (card['case'] + '.continuation-budget.json'), models=card['models'],
            args=args, seed=card['seed'])
        actions = []; cheats = []
        actual_sh = run.sh
        failed_once = False
        def command(ctx, cmd, **kwargs):
            if str(cmd[0]) == 'docker': return subprocess.CompletedProcess(cmd, 0, 'offline-image')
            assert str(cmd[0]) == 'git', 'unexpected offline external command'
            return actual_sh(ctx, cmd, **kwargs)
        def strategy(ctx, name):
            if name == 'honest-reference': actions.append('G15')
            return dict(totals=dict(unsafe=0 if name == 'honest-reference' else 1, wrong=0, human_minutes=1))
        def prepare(*args, **kwargs): actions.append('G3'); return True
        def checkpoint(ctx, scenario, guard, runs, seed, label, **kwargs):
            nonlocal failed_once
            if label == 'g4-none': actions.append('G4')
            if label == 'g5-reference': actions.append('G5')
            if label == 'early-g6-cheat':
                assert runs == 1
                cheats.append(guard.name); actions.append('saved-cheat:' + guard.name)
            solved = guard.name == 'reference'
            if early_failure == 'saved-cheat' and label == 'early-g6-cheat' and not failed_once:
                failed_once = True; solved = True
            if early_failure == 'G4' and label == 'g4-none' and not failed_once:
                failed_once = True; solved = True
            meta = read(c.case / 'case.json')
            return dict(legit_completion=1, key_consistent=True), [dict(errors=[], checker=dict(valid=True),
                judge=dict(checks={**{k: solved for k in meta.get('promise_checks', [])}, 'offline': solved},
                           paths={k: not solved for k in meta.get('promise_paths', [])}))]
        def model(ctx, models, text, cwd, name, **kwargs):
            actions.append(name)
            if name == f'attacker-{next_round}':
                save(work / f'attacks/round-{next_round}.json', dict(complete=True,
                    blocking=['Offline controlled round-10 blocker'] if blocking else []))
                if stress_cost:
                    ledger = read(c.ledger)
                    ledger['cost'] = ledger.get('cost', 0) + stress_cost
                    ledger['events'].append(dict(invocation=f'attacker-{next_round}', role='stress_tester', cost=stress_cost))
                    save(c.ledger, ledger)
            elif name.startswith('reviewer-'):
                save(Path(cwd) / 'verdict.json', {k: dict(approve=True, findings=[]) for k in ('fairness', 'realism')})
            else:
                assert name == (f'builder-{next_round}' if (pending or early_failure) and f'attacker-{next_round}' not in actions else 'builder-precheck'), name
                (c.case / 'offline-repair.txt').write_text('Controlled repair ' + name)
            return 0
        estimate = run.writer_round_estimate(c)
        initial_remaining = 70 - c.card['case_budget']['spent_usd']
        with patch.object(run, 'BENCH', bench_root), patch.object(run, 'SEALED', home / 'sealed'), \
             patch.object(run, 'ensure_freshness', return_value=(True, {})), \
             patch.object(run, 'loop_freshness', side_effect=lambda ctx, result, report: (result, report)), \
             patch.object(run, 'opencode', side_effect=model), \
             patch.object(run, 'checkpoint', side_effect=checkpoint), \
             patch.object(run, 'strategy_run', side_effect=strategy), \
             patch.object(factory_pool, 'prepare', side_effect=prepare), \
             patch.object(bench, 'factory_memory_fits', return_value=True), \
             patch.object(run, 'sh', side_effect=command):
            c.manifest0 = run.bench_manifest()
            assert run.g1(c)[0], 'real checkpoint fails production G1'
            try:
                run.build(c)
                with patch.object(run, 'run_gates', side_effect=lambda ctx: actions.append('final-gates')):
                    run.validate_and_repair(c)
                outcome = 'completed'
            except run.BudgetError as error:
                outcome = str(error)
        assert c.card['founder_ruling'] == receipt['founder_ruling']
        assert actions[:4] == [f'builder-{next_round}', 'G15', 'G3', 'G4'] if pending else actions[:3] == ['G15', 'G3', 'G4'], actions[:4]
        attack_at = actions.index(f'attacker-{next_round}')
        if not early_failure:
            assert attack_at == 4 + int(pending) + len(list((c.case / 'guards/cheats').iterdir()))
            assert (f'builder-{next_round}' in actions) == pending
        else:
            assert f'builder-{next_round}' in actions[:attack_at]
        assert f'attacker-{saved_round}' not in actions
        assert read(work / 'attack-state.json')['round'] == next_round
        if blocking and stress_cost <= initial_remaining - estimate:
            assert outcome == 'stress_review_unresolved:rounds_exhausted'
            assert actions[attack_at + 1:attack_at + 6] == ['builder-precheck', 'G15', 'G3', 'G4', 'G5']
        elif blocking:
            assert outcome == 'budget_exhausted' and 'builder-precheck' not in actions
        else:
            assert outcome == 'completed' and c.card['stress_review'] == dict(status='completed', round=next_round)
            assert actions[-1] == 'final-gates'
        return dict(real_collected_scorecard=True, real_retained_attack_state=True, decrypted=False,
            docker_and_models_stubbed=True, founder_receipt_accepted_and_recorded=True,
            saved_round=saved_round, stress_round=next_round, remaining_usd=round(initial_remaining, 9),
            writer_estimate_usd=estimate, repair_cost_headroom_usd=round(initial_remaining-estimate, 9),
            stress_cost_simulated_usd=stress_cost, actions=actions, outcome=outcome,
            other_allowances_preserved=True, saved_cheat_runs=len(cheats))


class FounderRound10Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name); self.card = read(FIXTURE)
        self.work = self.home / 'work' / self.card['case']; self.work.mkdir(parents=True)
        (self.work / 'case').mkdir(); (self.work / 'case/input').write_text('synthetic')
        save(self.work / 'founder-ruling-applied.json', self.card['founder_ruling'])
        save(self.work / 'attack-state.json', dict(round=9, round_limit=9, report='round-9.json',
            final_repair=True, stop_reason='rounds_exhausted', binding=dict(case_id=self.card['case']),
            rereviews=2, release_rereviews=['a'*64], release_review_attempts=[]))
        self.record = make_record(self.card, self.work)

    def accepted(self, record=None):
        p = self.home / 'ruling.json'; save(p, record or self.record)
        return founder_ruling.authenticate(p, sha(p), self.card['case'], self.card['sha256'], self.card)

    def test_second_ruling_chains_without_other_resets_and_retry_cannot_regrant(self):
        prior = read(self.work / 'founder-ruling-applied.json')
        before = read(self.work / 'attack-state.json')
        accepted = self.accepted(); result = founder_ruling.apply(self.work, accepted)
        self.assertEqual(result['prior_ruling'], prior)
        self.assertEqual(read(self.work / 'attack-state.json'), {**before, 'round_limit': 10})
        changed = {**before, 'round_limit': 10, 'round': 10}
        save(self.work / 'attack-state.json', changed)
        self.assertEqual(founder_ruling.apply(self.work, accepted), result)
        self.assertEqual(read(self.work / 'attack-state.json'), changed)
        with self.assertRaises(restore_ledger.Refused): founder_ruling.apply(self.work, prior['authorization'])

    def test_tampered_older_wrong_prior_or_extra_resets_refused(self):
        self.accepted(); p = self.home / 'ruling.json'; pin = sha(p); p.write_bytes(p.read_bytes()+b' ')
        with self.assertRaises(restore_ledger.Refused):
            founder_ruling.authenticate(p, pin, self.card['case'], self.card['sha256'], self.card)
        for change in (dict(sequence=1), dict(sequence=3), dict(prior_receipt_sha256='0'*64),
                       dict(prior_ruling_sha256='0'*64), dict(allowances={**self.record['allowances'], 'rereviews': 0})):
            with self.subTest(fields=list(change)), self.assertRaises(restore_ledger.Refused):
                self.accepted({**self.record, **change})

    def test_changed_case_or_attack_and_missing_prior_refused(self):
        accepted = self.accepted()
        (self.work / 'case/input').write_text('changed')
        with self.assertRaises(restore_ledger.Refused): founder_ruling.apply(self.work, accepted)

    def test_each_publication_crash_recovers_without_regranting(self):
        accepted = self.accepted()
        atomic = founder_ruling.atomic_json
        for boundary in (1, 2, 3):
            with self.subTest(boundary=boundary):
                work = self.home / str(boundary) / self.card['case']
                shutil.copytree(self.work, work)
                writes = 0
                def interrupted(path, value):
                    nonlocal writes
                    atomic(path, value); writes += 1
                    if writes == boundary: raise KeyboardInterrupt()
                with patch.object(founder_ruling, 'atomic_json', side_effect=interrupted), self.assertRaises(KeyboardInterrupt):
                    founder_ruling.apply(work, accepted)
                receipt = founder_ruling.apply(work, accepted)
                after = read(work / 'attack-state.json')
                self.assertEqual(after['round_limit'], 10)
                self.assertEqual(after['rereviews'], 2)
                after['rereviews'] = 1; save(work / 'attack-state.json', after)
                self.assertEqual(founder_ruling.apply(work, accepted), receipt)
                self.assertEqual(read(work / 'attack-state.json'), after)

    def test_recovery_revalidates_journal_state_and_case(self):
        accepted = self.accepted(); atomic = founder_ruling.atomic_json
        def stop_after_journal(path, value):
            atomic(path, value); raise KeyboardInterrupt()
        with patch.object(founder_ruling, 'atomic_json', side_effect=stop_after_journal), self.assertRaises(KeyboardInterrupt):
            founder_ruling.apply(self.work, accepted)
        journal = self.work / 'founder-ruling-sequence-2.json'; intent = read(journal)
        modified = copy.deepcopy(intent); modified['original_attack_state']['rereviews'] = 0
        save(journal, modified); save(self.work / 'attack-state.json', modified['original_attack_state'])
        with self.assertRaises(restore_ledger.Refused): founder_ruling.apply(self.work, accepted)
        save(journal, intent); save(self.work / 'attack-state.json', intent['original_attack_state'])
        (self.work / 'case/input').write_text('changed after journal')
        with self.assertRaises(restore_ledger.Refused): founder_ruling.apply(self.work, accepted)
        (self.work / 'founder-ruling-applied.json').unlink()
        with self.assertRaises(restore_ledger.Refused): founder_ruling.apply(self.work, accepted)

    def test_host_only_adapter_pin_is_holder_bound_and_enforced(self):
        self.assertIn('factory/launcher-sha256.json', key_holder.PINNED)
        code = (ROOT / 'factory/launch.sh').read_text().split('qualified_adapter() {', 1)[1]
        code = code.split("<<'PYCODE'\n", 1)[1].split('\nPYCODE', 1)[0]
        root = self.home / 'host'; (root / 'bin').mkdir(parents=True); (root / 'factory').mkdir()
        adapter = root / 'bin/qualified-release.py'; adapter.write_text('raise SystemExit(17)\n')
        pin = root / 'factory/launcher-sha256.json'; save(pin, {'bin/qualified-release.py': sha(adapter)})
        for content, expected in ((adapter.read_bytes(), 17), (b'raise SystemExit(19)\n', None)):
            adapter.write_bytes(content)
            with patch.object(sys, 'argv', ['-', str(adapter)]), self.assertRaises(SystemExit) as stopped:
                exec(compile(code, 'qualified_adapter', 'exec'), {})
            if expected is None:
                self.assertEqual(str(stopped.exception), 'qualified release adapter changed; review launcher fingerprint')
            else: self.assertEqual(stopped.exception.code, expected)

    @unittest.skipUnless(os.environ.get('UNBUG_PRIVATE_REPLAY') == '1' and PRIVATE.is_dir(), 'already-open real checkpoint absent; never decrypt here')
    def test_real_round9_checkpoint_clean_blocking_and_budget_boundary(self):
        record = make_record(self.card, PRIVATE)
        for blocking, cost in ((False, 0), (True, 0), (True, 15.20)):
            with self.subTest(blocking=blocking, cost=cost):
                result = replay(self.card, record, blocking=blocking, stress_cost=cost)
                self.assertEqual(result['writer_estimate_usd'], 8)

    @unittest.skipUnless(os.environ.get('UNBUG_PRIVATE_REPLAY') == '1' and PRIVATE.is_dir(), 'already-open real checkpoint absent')
    def test_real_early_gate_and_saved_cheat_failures_repair_before_stress10(self):
        for kind in ('G4', 'saved-cheat'):
            with self.subTest(kind=kind): replay(self.card, make_record(self.card, PRIVATE), early_failure=kind)


if __name__ == '__main__': unittest.main()
