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

    def test_a_retry_from_a_receipt_without_a_round_start_is_not_called_unchanged(self):
        # f46dac-2's held snapshot: written before receipts carried the round start, after the
        # writer's interrupted edits. Its first retried call cannot be judged unchanged.
        feedback = self.stress('{"complete": false, "blocking": ["reference misses stock update"]}')['feedback']
        (self.c.case / 'repair.txt').write_text('edits of the interrupted call')
        (self.c.work / 'attack-state.json').write_text(json.dumps({"engine": True, "round": 2, "call": 1,
            "binding": {}, "report": "round-2.json", "repair_pending": True}))
        self.step(StepKind.WRITER, 2)
        with patch.object(run, 'opencode', return_value=0):
            self.assertEqual(run.engine_writer_round(self.c, 2, feedback)['outcome'], Outcome.OK)

    def test_a_round_start_from_other_feedback_is_not_reused(self):
        feedback = self.stress('{"complete": false, "blocking": ["reference misses stock update"]}')['feedback']
        (self.c.work / 'attack-state.json').write_text(json.dumps({"engine": True, "round": 2, "call": 1,
            "round_start": {"case": "0" * 64, "feedback": "f" * 64}, "repair_pending": True}))
        self.step(StepKind.WRITER, 2)
        with patch.object(run, 'opencode', return_value=0):
            result = run.engine_writer_round(self.c, 2, feedback)
        self.assertEqual(result, {'outcome': Outcome.EXHAUSTED, 'reason': 'writer:unchanged_repair'})

    def transcript(self, name, *reasons, stamp=1):
        folder = self.c.work / 'transcripts'; folder.mkdir(exist_ok=True)
        rows = [{'type': 'step_finish', 'part': {'messageID': 'm', 'id': str(i), 'reason': r}}
                for i, r in enumerate(reasons)]
        (folder / f'{name}.{stamp}.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))

    def test_a_reply_cut_at_the_output_cap_is_retried_with_smaller_edits(self):
        # 22e434-3 and f46dac-2r round 3: the writer's last request stopped at the 32k output cap,
        # none of its edits applied, and the round was called an unchanged repair.
        feedback = self.stress('{"complete": false, "blocking": ["reference misses stock update"]}')['feedback']
        self.step(StepKind.WRITER, 2)
        seen = []
        def writer(c, models, text, cwd, name):
            seen.append((name, json.loads(text)))
            if name == 'builder-2': self.transcript(name, 'tool-calls', 'length')
            else: (c.case / 'repair.txt').write_text('repaired in parts')
        with patch.object(run, 'opencode', writer):
            result = run.engine_writer_round(self.c, 2, feedback)
        self.assertEqual(result['outcome'], Outcome.OK)
        self.assertEqual([name for name, _ in seen], ['builder-2', 'builder-2-fix-1'])
        self.assertNotIn('output_capped', seen[0][1])
        self.assertIs(seen[1][1]['output_capped'], True)
        self.assertEqual(seen[1][1]['precheck_problems'], seen[0][1]['precheck_problems'])
        self.assertEqual(seen[1][1]['attack_report'], seen[0][1]['attack_report'])
        self.assertEqual(self.c.card['writer_output_capped'], ['builder-2'])

    def test_a_capped_reply_on_the_last_call_names_the_cap(self):
        feedback = self.stress('{"complete": false, "blocking": ["reference misses stock update"]}')['feedback']
        self.step(StepKind.WRITER, 2)
        def writer(c, models, text, cwd, name): self.transcript(name, 'length')
        with patch.object(run, 'opencode', writer):
            result = run.engine_writer_round(self.c, 2, feedback)
        self.assertEqual(result, {'outcome': Outcome.EXHAUSTED, 'reason': 'writer:output_capped'})
        self.assertIn('writer:output_capped', run_engine_resumable())

    def test_a_reply_that_finished_normally_is_still_an_unchanged_repair(self):
        feedback = self.stress('{"complete": false, "blocking": ["reference misses stock update"]}')['feedback']
        self.step(StepKind.WRITER, 2)
        def writer(c, models, text, cwd, name):
            self.transcript(name, 'length', stamp=1)       # an older call of the same name
            self.transcript(name, 'length', 'stop', stamp=2)
        with patch.object(run, 'opencode', writer):
            result = run.engine_writer_round(self.c, 2, feedback)
        self.assertEqual(result, {'outcome': Outcome.EXHAUSTED, 'reason': 'writer:unchanged_repair'})

    def test_output_cap_reading(self):
        self.assertFalse(run._output_capped(self.c, 'builder-1'))
        self.transcript('builder-1', 'stop', 'length')
        self.assertTrue(run._output_capped(self.c, 'builder-1'))
        self.transcript('builder-1', 'length', 'stop', stamp=10)
        self.assertFalse(run._output_capped(self.c, 'builder-1'))
        (self.c.work / 'transcripts/builder-1-fix-1.5.jsonl').write_text(
            'not json\n' + json.dumps({'type': 'assistant', 'message': {'stop_reason': 'max_tokens'}}) + '\n')
        self.assertTrue(run._output_capped(self.c, 'builder-1-fix-1'))
        self.assertFalse(run._output_capped(self.c, 'builder-1'), 'builder-1-fix-1 is another call')


def run_engine_resumable():
    from durable.engine import FACTORY_BUG_RESUMABLE
    return FACTORY_BUG_RESUMABLE["writer"]


if __name__ == "__main__":
    unittest.main()
