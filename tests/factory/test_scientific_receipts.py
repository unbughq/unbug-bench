"""Saved public case/execution replays; cap metadata perturbations are authored.

The public card proves historical no-submission caps, not a retained per-attempt
capped submission. This test does not claim complete Murphy 39 closure.
"""
import copy
import gzip
import json
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin')]
import calibration
import fairness
import gate_state
import run
from run_validity import InvalidInfra

FIXTURES = ROOT / 'tests/factory/fixtures'
def fixture(name):
    return json.loads(gzip.decompress((FIXTURES / name).read_bytes()))
REAL = fixture('invalid-runs-real.json.gz')
PRACTICE = fixture('invalid-runs-practice.json.gz')


def execution(label):
    files = REAL[label]['files']
    return {'summary': files['checkpoint.json'],
            'records': [files[n] for n in sorted(files) if Path(n).stem.isdigit()],
            'seed': 43, 'runs': 1}


class ScientificReceiptsTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        factory = self.root / 'factory'; factory.mkdir()
        for path in (ROOT / 'factory').glob('*.py'):
            shutil.copy2(path, factory / path.name)
        self.runner = factory / 'run.py'
        self.work = self.root / 'work'; self.case = self.work / 'case'; self.case.mkdir(parents=True)
        for name, content in PRACTICE['files'].items():
            path = self.case / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(content)
        (self.case / 'case.json').write_text(json.dumps(REAL['suffix-case']['files']['case.json']))
        card = json.loads((FIXTURES / 'e15450-collected-card.json').read_text())
        self.c = SimpleNamespace(work=self.work, case=self.case, case_id='public-practice', seed=42,
            manifest0='saved-public-practice', card={'roles': card['roles'], 'gates': {}},
            models=card['models'], args=run.argument_parser().parse_args([]))
        self.c.args.runs = self.c.args.pilot_runs = self.c.args.pilot_tries = 1
        details = self.work / 'gate-details'; details.mkdir()
        self.evidence = details / 'saved-execution.json'
        self.evidence.write_text(json.dumps(execution('plain')))
        for replacement in (patch.object(gate_state, 'RUNNER', self.runner), patch.object(run, 'BENCH', ROOT)):
            replacement.start(); self.addCleanup(replacement.stop)

    def versions(self):
        return {gate: gate_state.scientific_version(self.c, gate, ROOT) for gate in [*run.GATES, 'stress']}

    def test_nine_retained_receipts_and_calibration_survive_boundary_plumbing(self):
        # Receipt envelopes for other gates are authored. The retained support is
        # real saved execution; this tests binding/reuse, not their gate verdicts.
        for gate in gate_state.REUSABLE:
            gate_state.save(self.c, gate, {'retained': gate}, gate_state.fingerprint(self.c, gate, ROOT), {}, ROOT)
        calibration_before = run.calibration_identity(self.c, 'strong_calibrator', 'statement')
        versions = self.versions()
        for name in ('worker_secrets.py', 'model_runtime.py', 'model_router.py', 'budget.py', 'registry.py', 'run_artifacts.py'):
            path = self.runner.with_name(name)
            path.write_text(path.read_text() + '\n# Authored plumbing-only revision.\n')
        original = self.runner.read_text()
        text = original.replace('    install_publication_barrier(c)\n', '    install_publication_barrier(c)  # Authored plumbing edit.\n')
        self.assertNotEqual(text, original)
        self.runner.write_text(text + '\ndef unrelated_publication_revision():\n    return 2\n')
        self.assertEqual(self.versions(), versions)
        self.assertEqual(run.calibration_identity(self.c, 'strong_calibrator', 'statement'), calibration_before)
        for gate in gate_state.REUSABLE:
            self.assertEqual(gate_state.load(self.c, gate, ROOT), {'retained': gate}, gate)
        self.evidence.write_text(self.evidence.read_text() + ' ')
        for gate in gate_state.REUSABLE:
            self.assertIsNone(gate_state.load(self.c, gate, ROOT), gate)

    def test_own_gate_edit_changes_only_its_version_and_preserves_other_pass(self):
        before = self.versions()
        for gate in ('G4', 'G5'):
            saved = execution('plain' if gate == 'G4' else 'reference')
            with patch.object(run, 'checkpoint', return_value=(saved['summary'], saved['records'])):
                if gate == 'G5':
                    self.c.args.rehearse_only = True
                ok, info = getattr(run, gate.lower())(self.c)
            self.assertTrue(ok)
            gate_state.save(self.c, gate, info, gate_state.fingerprint(self.c, gate, ROOT), {}, ROOT)
        # Rehearsal setting is now common to both comparison vectors.
        before = self.versions()
        source = self.runner.read_text()
        self.runner.write_text(source.replace('broke >= 1, {"broke"', 'broke >= 2, {"broke"'))
        after = self.versions()
        self.assertEqual([gate for gate in before if before[gate] != after[gate]], ['G4'])
        self.assertIsNone(gate_state.load(self.c, 'G4', ROOT))
        self.assertIsNotNone(gate_state.load(self.c, 'G5', ROOT))

    def test_models_prompts_family_logic_and_evidence_remain_scientific(self):
        before = self.versions()
        with patch.object(run, 'prompt', side_effect=lambda role, extra: 'changed ' + role + extra):
            after = self.versions()
        self.assertEqual(before['G4'], after['G4'])
        self.assertNotEqual(before['G10'], after['G10'])
        self.c.models = copy.deepcopy(self.c.models)
        self.c.models['strong_calibrator'] = ['codex/changed']
        self.assertNotEqual(before['G16'], self.versions()['G16'])
        router = self.runner.with_name('model_router.py')
        router.write_text(router.read_text().replace("return 'anthropic'", "return 'changed-family'", 1))
        self.assertNotEqual(before['G17'], self.versions()['G17'])

    def test_source_mode_and_stress_judge_environment_are_versioned(self):
        before = self.versions()
        self.c.args.source = 'hunt' if self.c.args.source != 'hunt' else 'port'
        after = self.versions()
        self.assertNotEqual(before['G1'], after['G1'])
        with patch.dict(run.os.environ, {'UNBUG_JUDGE': 'authored-change'}):
            self.assertNotEqual(after['stress'], self.versions()['stress'])

    def attempt(self, *, stop='completed', label='cheat', submitted=True):
        path = self.work / 'strong_calibrator/results.json'
        identity = run.calibration_identity(self.c, 'strong_calibrator', 'exam')
        series = calibration.AttemptSeries(path, identity, self.work, 1, 'public-practice')
        ws = series.workspace(1); ws.mkdir(parents=True)
        row = {'try': 1, 'solved': False, 'guard_submitted': submitted, 'stop_reason': stop}
        if submitted:
            shutil.copytree(ROOT / 'guards/refuse-all', ws / 'guard')
            saved = execution(label)
            (ws / 'execution.json').write_text(json.dumps(saved))
            values = run.verdicts(self.c, saved['records'])
            row.update(guard=str(ws / 'guard'), errors=0, checked_runs=len(values),
                       solved_runs=sum(v['solved'] for v in values), solved=all(v['solved'] for v in values))
        summary = series.commit(row, ws)
        self.c.card['calibrators'] = {'strong': summary}
        return path, summary

    def test_saved_execution_receipt_distinguishes_authored_caps_and_wrong_fix(self):
        # A call-capped try stays inconclusive. A time-limited try that handed in a checked fix is
        # graded since the founder's 14 November decision (tests/factory/test_fairness.py).
        path, summary = self.attempt(stop='call_limit')
        self.assertEqual(summary['scientific']['outcomes']['capped'], 1)
        row = json.loads(path.read_text())[0]
        self.assertEqual(row['scientific_outcome'], 'capped')
        reply = {'tries': [{'try': 1, 'label': 'wrong_fix', 'finding': 'authored reviewer label', 'evidence': 'execution.json'}]}
        self.assertIsNone(fairness.verdict(reply, [row]))
        with patch.object(run, 'model_call') as paid:
            ok, info = fairness.diagnose(self.c, run)
            self.assertFalse(ok); self.assertTrue(info['review_inconclusive'])
        paid.assert_not_called()
        self.assertNotIn('difficulty', self.c.card)
        identity = row['identity']
        replay = calibration.AttemptSeries(path, identity, self.work, 1, 'public-practice')
        self.assertTrue(replay.finish()[0]['kept'])
        # Tampering with the scientific label cannot upgrade a capped receipt.
        row['scientific_outcome'] = 'demonstrated_failure'
        calibration.atomic_results(path, [row])
        self.assertEqual(calibration.completed_attempts(path, identity, self.work), [])

    def test_saved_valid_failure_unknown_and_invalid_execution(self):
        path, summary = self.attempt()
        self.assertEqual(summary['scientific']['outcomes']['demonstrated_failure'], 1)
        row = json.loads(path.read_text())[0]
        row.pop('scientific_outcome'); row.pop('stop_reason')
        self.assertEqual(calibration.scientific_outcome(row), 'unknown')
        with self.assertRaises(InvalidInfra):
            run.verdicts(self.c, execution('reset-invalid')['records'])

    def test_saved_public_no_submission_cap_is_not_a_wrong_fix(self):
        cards = fixture('invalid-runs-public-cards.json.gz')
        card = next(entry['card'] for entry in cards if entry['card'].get('case') == 'case-20261017T125556Z-18681d')
        easy = card['calibrators']['easy']
        self.assertEqual(easy['diagnostics']['stop_reasons']['time_limit'], 3)
        self.assertEqual(easy['diagnostics']['outcomes']['no_fix_submitted'], 3)
        # Aggregate saved counts cannot invent a per-attempt join. Replayed author
        # metadata below explicitly models that observed no-submission condition.
        _, summary = self.attempt(stop='time_limit', submitted=False)
        self.assertEqual(summary['scientific']['outcomes']['no_submission'], 1)
        self.assertEqual(summary['scientific']['outcomes']['demonstrated_failure'], 0)
        self.assertEqual(summary['diagnostics']['stop_reasons']['time_limit'], 1)


if __name__ == '__main__': unittest.main()
