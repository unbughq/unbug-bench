"""Offline qualified-path replays over saved practice bytes and the 5813be ledger.

Authority envelopes, model answers and gate failures are authored controls.
No live qualification or Murphy closure is claimed.
"""
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin'), str(ROOT / 'tests/factory')]
import budget
import founder_ruling
import founder_decisions
import free_models
import model_runtime
import registry
import run
import test_stream_d_runtime as runtime


class QualifiedAllowanceTests(unittest.TestCase):
    patch = runtime.RuntimeTests.patch
    setUp = runtime.RuntimeTests.setUp

    def test_batch_does_not_record_or_enforce_d1_call_cap(self):
        self.c.args.max_total_calls = 9001
        founder_decisions.record(self.c)
        self.assertNotIn('call_cap_ruling', self.c.card)
        self.assertIn('freshness_archive_ruling', self.c.card)

    def test_model_selection_never_consults_cohort_for_batch(self):
        with patch.object(free_models, 'apply', side_effect=AssertionError('legacy cohort')):
            selected = model_runtime.select_models(self.c, log=lambda *a: None)
        self.assertEqual(len(selected['builder']), 1)
        self.assertNotIn('model_transition', self.c.card)

    def test_final_repair_refuses_before_freshness_or_role_work(self):
        self.c.args.resume = self.c.case_id
        registry.atomic_json(self.work / 'attack-state.json', {'final_repair': True})
        with patch.object(founder_ruling, 'context', side_effect=AssertionError('legacy ruling')), \
             patch.object(run, 'freshness_lines', return_value=[{'hit': True}]), \
             patch.object(run, 'ensure_freshness', side_effect=AssertionError('freshness work')), \
             patch.object(run, 'resume_provider_wait', side_effect=AssertionError('provider work')), \
             patch.object(run, 'opencode', side_effect=AssertionError('model work')):
            for action in (lambda: run.build(self.c), lambda: run.write_and_attack(self.c, {})):
                with self.assertRaisesRegex(budget.BudgetError, 'invalid_recovery_receipt'): action()

    def test_modern_late_defect_stays_held_without_founder_context(self):
        self.c.args.resume = self.c.case_id
        label = 'late_defect_needs_ruling:G8'
        registry.atomic_json(self.work / 'scorecard.json', {'terminal_stop': label})
        registry.atomic_json(self.work / 'attack-state.json', {})
        with patch.object(founder_ruling, 'context', side_effect=AssertionError('legacy ruling')), \
             patch.object(run, 'freshness_lines', return_value=[{'hit': True}]), \
             patch.object(run, 'ensure_freshness', side_effect=AssertionError('freshness work')), \
             patch.object(run, 'write_and_attack', side_effect=AssertionError('writer work')):
            with self.assertRaisesRegex(budget.BudgetError, label): run.build(self.c)

    def test_modern_stress_replay_ignores_old_attempt_counts_and_completed_claim(self):
        original = registry.atomic_json
        def retained(path, value):
            if Path(path).name == 'attack-state.json' and value.get('actor') == 'stress_tester':
                value['rereviews'] = 7
                value['release_review_attempts'] = [dict(round=1, binding='a' * 64,
                    cause='infrastructure', actor='stress_tester', reason='authored retained retry') for _ in range(9)]
            return original(path, value)
        claim = self.work / 'diagnostic-budgets/attacker-1'
        (claim / 'claimed').mkdir(parents=True)
        (claim / 'status.json').write_text('{"status":"completed"}')
        with patch.object(registry, 'atomic_json', side_effect=retained), \
             patch.object(founder_ruling, 'feedback_allowed', side_effect=AssertionError('founder feedback')):
            runtime.RuntimeTests.stress_rebind(self, 'pending')
        self.assertEqual(self.c.card['stress_review']['status'], 'completed')

    def test_completed_stress_findings_never_consult_founder_feedback(self):
        with patch.object(founder_ruling, 'feedback_allowed', side_effect=AssertionError('founder feedback')):
            runtime.RuntimeTests.stress_rebind(self, 'finished')

    def main_replay(self, mode):
        home = self.work / ('main-' + mode)
        home.mkdir()
        control = {key: getattr(self.c, key) for key in ('job_money', 'authenticated_job_config',
            'batch_id', 'job_id', 'batch_deadline', 'source_generation')}
        (home / 'control.json').write_text(json.dumps(control))
        harness = r'''
import hashlib, json, pathlib, shutil, sys
from unittest.mock import patch
sys.path[:0] = [sys.argv[1], sys.argv[2]]
import run, job_config, founder_ruling, restart, free_models, worker_release, late_recovery
home, practice, ledger, case, mode = sys.argv[3:]
home = pathlib.Path(home); work = home/'work'/case
work.mkdir(parents=True); (work/'logs').mkdir(); shutil.copytree(practice, work/'case')
run.HOME=home; run.SEALED=home/'sealed'; run.SEALED.mkdir()
shutil.copyfile(ledger, run.SEALED/(case+'.continuation-budget.json'))
release=b'authored release'; (home/'batch-release.json').write_bytes(release)
release_hash=hashlib.sha256(release).hexdigest()
previous={'case':case,'batch_release_sha256':release_hash,'builder_rounds':1,
 'recovery_config':{'max_total_calls':9001,'rounds':4},'gates':{},
 'extension_history':[]}
if mode == 'crash':
 previous.update(failed_gate='G8',failed_detail={'error':'RuntimeError'},gates={'G8':'fail'})
(work/'scorecard.json').write_text(json.dumps(previous))
(work/'founder-ruling-applied.json').write_text('malformed historical ruling')
(work/'attack-state.json').write_text('{}')
def forbidden(*a,**kw): raise AssertionError('legacy rescue invoked')
founder_ruling.context=founder_ruling.feedback_allowed=restart.raised_limits=run.restore_gate_crash=free_models.apply=forbidden
run.bench_manifest=lambda:'saved-practice-bench'
run.sh=lambda *a,**kw:0  # Successful non-capture sh returns an exit status.
run.stop_pilot=lambda *a:False
run.pilot_homes=lambda:[]
run.seal=lambda *a,**kw:None
run.wipe=lambda *a:None
worker_release.verify_selected_drivers=lambda *a,**kw:{}
run.pick_models=lambda c:{}
real_install=job_config.install
def install(c,a):
 if mode == 'missing': return real_install(c,a)
 for k,v in json.loads((home/'control.json').read_text()).items(): setattr(c,k,v)
job_config.install=install
# OS, release delivery and judgments are controls; entry, repair loop,
# late-defect publication, accounting and exhaustion classification are real.
def build(c):
 assert not c.args.skip_build and 'salvaged_from' not in c.card
 assert c.args.max_total_calls == 5000
 assert 'call_cap_ruling' not in c.card
 c.card['ordinary_build_entered']=True
 if mode in ('ordinary','crash'): raise run.BudgetError('authored_entry_stop')
run.build=build
late_recovery.mark_gates=lambda c:None
def gates(c):
 c.card.update(failed_gate='G8',failed_detail={'authored':'scientific defect'})
 c.card['gates']['G8']='fail'
def writer(c,previous):
 if mode == 'unchanged': return
 c.card['builder_rounds']+=1
 (c.case/'draft.txt').write_text(str(c.card['builder_rounds']))
run.run_gates=gates; run.write_and_attack=writer
argv=['run.py','--source','hunt','--resume',case,'--resume-bench-sha','saved-practice-bench',
 '--batch-release-sha256',release_hash,'--rounds','4','--max-repairs','0']
with patch.object(sys,'argv',argv), patch.object(run.shutil,'which',return_value='offline'):
 run.main()
'''
        result = subprocess.run([sys.executable, '-B', '-c', harness, str(ROOT/'factory'), str(ROOT/'bin'),
            str(home), str(self.case), str(self.ledger), self.c.case_id, mode],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((home/'sealed/DONE').read_text().strip(), self.c.case_id)
        return json.loads((home/'sealed'/f'{self.c.case_id}.scorecard.json').read_text())

    def test_ordinary_and_crash_launch_ignore_exhausted_legacy_caps_and_bad_ruling(self):
        for mode in ('ordinary', 'crash'):
            with self.subTest(mode=mode):
                card = self.main_replay(mode)
                self.assertEqual(card['terminal_stop'], 'authored_entry_stop')
                self.assertTrue(card['ordinary_build_entered'])
                self.assertNotIn('salvaged_from', card)

    def test_missing_authority_stops_before_build(self):
        card = self.main_replay('missing')
        self.assertEqual(card['terminal_stop'], 'money_wait')
        self.assertNotIn('ordinary_build_entered', card)

    def test_late_repairs_ignore_zero_legacy_limit_until_writer_round_exhaustion(self):
        card = self.main_replay('repairs')
        self.assertEqual(card['builder_rounds'], 4)
        self.assertEqual(len(card['repairs']), 3)
        self.assertEqual(card['diagnosis_state']['stop'], 'late_defect_needs_ruling:G8')
        self.assertEqual(card['diagnosis_state']['status'], 'pending')
        self.assertNotEqual(card['gates'].get('G12'), 'pass')

    def test_unchanged_modern_repair_remains_scientific_failure(self):
        card = self.main_replay('unchanged')
        self.assertEqual(card['failed_gate'], 'G8')
        self.assertEqual(card['repair_blocked'], 'repair made no case changes')
        self.assertEqual(card['builder_rounds'], 1)
        self.assertFalse(card.get('repairs'))
        self.assertNotIn('diagnosis_state', card)
        self.assertEqual(card['gates']['G12'], 'pass')


if __name__ == '__main__': unittest.main()
