"""Worker stress-review and writer handoff guards; synthetic files and model stubs."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "factory"), str(ROOT / "bin"), str(ROOT / "tests/bench")]
import json
import tempfile
import types
import unittest
from unittest.mock import patch
import run
from durable.contract import ArtifactKind, Outcome, Ref, Step, StepInput, StepKind


class AttackRecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        work = Path(temporary.name)
        case = work / "case"; case.mkdir()
        (case / "statement.md").write_text("synthetic selected case")
        ledger = work / "continuation-budget.json"
        ledger.write_text('{"events": [], "calls": 0, "cost": 0}')
        self.c = types.SimpleNamespace(work=work, case=case, case_id="case-synthetic", card={},
            ledger=ledger, manifest0="synthetic bench revision",
            models={"builder": ["writer"], "attacker": ["tester"]},
            args=types.SimpleNamespace(dry_run=False, source="hunt", rounds=2, case_budget=10))
        for target, value in (("g1", (True, {"problems": []})), ("early_checks", None),
                              ("early_review", None), ("ensure_freshness", (True, {})),
                              ("engine_prepare_bench", None)):
            mocked = patch.object(run, target, return_value=value)
            setattr(self, target, mocked.start()); self.addCleanup(mocked.stop)
        for target, value in (("prompt", lambda role, text: text),
                              ("run_context", lambda c, **kw: json.dumps(kw))):
            mocked = patch.object(run, target, value)
            mocked.start(); self.addCleanup(mocked.stop)

    def step(self, kind, n):
        si = StepInput('b-offline', self.c.case_id, n, Step(kind, n), 1,
            'a' * 64, 'b' * 64, Ref('a' * 64, ArtifactKind.INPUTS),
            Ref('b' * 64, ArtifactKind.CASE_SNAPSHOT), 300, 10_000_000)
        self.c.engine = run.EngineStep(si, 0)

    def stress(self, content, n=1):
        self.step(StepKind.STRESS, n)
        def categories(c, number, report, receipt, completed):
            # Category orchestration has its own durable progress/replay tests.
            if content is not None: report.write_text(content)
        with patch.object(run, "stress_categories", categories):
            return run.engine_stress_round(self.c, n)

    def test_partial_blocking_finding_reaches_writer_before_next_review(self):
        result = self.stress(json.dumps({"complete": False,
            "blocking": ["review incomplete", "reference misses second writer"]}))
        self.assertEqual((result['outcome'], result['reason']), (Outcome.OK, 'stress:findings'))
        self.assertEqual(json.loads(result['feedback'])['problems'], ['reference misses second writer'])
        def writer(c, models, text, cwd, name):
            self.assertEqual(name, 'builder-2')
            request = json.loads(text)
            self.assertEqual(request['precheck_problems'], ['reference misses second writer'])
            self.assertEqual(Path(request['attack_report']).name, 'round-1.json')
            (c.case / 'repair.txt').write_text('second writer fixed')
        self.step(StepKind.WRITER, 2)
        with patch.object(run, 'opencode', writer):
            repaired = run.engine_writer_round(self.c, 2, result['feedback'])
        self.assertEqual(repaired['outcome'], Outcome.OK)
        self.early_checks.assert_called_once_with(self.c)
        self.assertEqual(self.stress('{"complete": true, "blocking": []}', 2)['reason'], 'stress:clean')
        self.early_review.assert_called_once_with(self.c)

    def test_missing_malformed_and_incomplete_reports_never_pass(self):
        for content, reason in ((None, 'malformed_report'), ('not json', 'malformed_report'),
                ('[]', 'malformed_report'), ('{"blocking": []}', 'malformed_report'),
                ('{"complete": false, "blocking": []}', 'interrupted_review'),
                ('{"complete": true, "blocking": ["review incomplete"]}', 'interrupted_review')):
            with self.subTest(content=content):
                (self.c.work / 'attacks/round-1.json').unlink(missing_ok=True)
                self.assertEqual(self.stress(content),
                    {'outcome': Outcome.INFRA_ERROR, 'reason': 'stress:' + reason})
        self.early_review.assert_not_called()

    def test_unfinished_validation_cannot_be_reported_as_passed(self):
        result = self.stress('{"complete": true, "blocking": [], "unfinished_validation": ["stock check"]}')
        self.assertEqual(result, {'outcome': Outcome.INFRA_ERROR, 'reason': 'stress:unfinished_validation'})
        self.early_review.assert_not_called()

    def test_failed_diagnostic_cannot_be_reported_as_passed(self):
        diagnostic = self.c.work / 'diagnostic-budgets/attacker-1'
        diagnostic.mkdir(parents=True); (diagnostic / 'claimed').touch()
        for status in ('running', 'timeout'):
            with self.subTest(status=status):
                (diagnostic / 'status.json').write_text(json.dumps({'status': status}))
                self.assertEqual(self.stress('{"complete": true, "blocking": []}'),
                    {'outcome': Outcome.INFRA_ERROR, 'reason': 'stress:unfinished_diagnostic'})
        self.early_review.assert_not_called()
        (diagnostic / 'status.json').write_text('{"status": "completed"}')
        self.assertEqual(self.stress('{"complete": true, "blocking": []}')['reason'], 'stress:clean')
        self.early_review.assert_called_once_with(self.c)

    def test_unchanged_repair_cannot_restart_tester(self):
        feedback = self.stress('{"complete": false, "blocking": ["reference misses stock update"]}')['feedback']
        self.step(StepKind.WRITER, 2)
        with patch.object(run, 'opencode', return_value=0) as writer:
            result = run.engine_writer_round(self.c, 2, feedback)
        self.assertEqual(result, {'outcome': Outcome.EXHAUSTED, 'reason': 'writer:unchanged_repair'})
        self.assertEqual([call.args[4] for call in writer.call_args_list], ['builder-2'])
        self.early_review.assert_not_called()


if __name__ == "__main__":
    unittest.main()
