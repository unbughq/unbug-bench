"""Checkpoint transport tests use real local files and synthetic process results."""

import sys
from pathlib import Path as _Path

_BENCH_ROOT = _Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_BENCH_ROOT / "bin"))

import json
import copy
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest

from checkpoint_evidence import publish, read_completed, record_paths, RECEIPT_PREFIX


class CheckpointEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.record = {'run': 1, 'errors': [], 'checker': {'valid': True},
                       'judge': {'pass': False, 'paths': {'shop': True}, 'checks': {'legit': True}}}
        self.summary = {'runs': 1, 'pass_runs': 0, 'error_runs': 0, 'invalid_runs': 0,
                        'paths': {'shop': {'runs': 1, 'violated_runs': 1}},
                        'checks': {'legit': {'runs': 1, 'ok_runs': 1}}}

    def process(self):
        (self.root / '01.json').write_text(json.dumps(self.record))
        receipt = publish(self.root, self.summary, 1)
        return subprocess.CompletedProcess([], 0, 'presentation can change\n' + receipt + '\n', '')

    def test_valid_scored_failure_is_evidence_not_operational_failure(self):
        process = self.process()
        summary, records, path = read_completed(process, 1, 'test', require_valid=True)
        self.assertEqual(summary['pass_runs'], 0)
        self.assertTrue(records[0]['judge']['paths']['shop'])
        self.assertEqual(path, self.root / 'checkpoint.json')
        self.assertFalse(path.with_suffix('.json.tmp').exists())

    def test_legacy_presentation_is_supported_in_one_place(self):
        self.process()
        process = subprocess.CompletedProcess([], 0, f'Checkpoint: {self.root / "checkpoint.json"}\n', '')
        self.assertEqual(read_completed(process, 1, 'legacy')[0], self.summary)

    def test_invalid_runs_remain_inspectable_but_are_not_strategy_verdicts(self):
        self.record['checker']['valid'] = False
        self.record['errors'] = [{'stage': 'reset', 'message': 'synthetic'}]
        self.summary.update(error_runs=1, invalid_runs=1)
        process = self.process()
        self.assertEqual(read_completed(process, 1, 'diagnostic', require_valid=False)[1], [self.record])
        with self.assertRaisesRegex(RuntimeError, 'no valid verdict'):
            read_completed(process, 1, 'strategy', require_valid=True)

    def test_nonzero_exit_never_authorizes_receipt(self):
        process = self.process(); process.returncode = 7; process.stderr = 'specific failure'
        with self.assertRaisesRegex(RuntimeError, 'returncode=7; stderr=specific failure'):
            read_completed(process, 1, 'test')

    def test_missing_or_partial_evidence_is_rejected(self):
        for target, contents in (('checkpoint.json', None), ('checkpoint.json', '{'), ('01.json', None)):
            with self.subTest(target=target, contents=contents):
                process = self.process()
                path = self.root / target
                if contents is None: path.unlink()
                else: path.write_text(contents)
                with self.assertRaises(RuntimeError): read_completed(process, 1, 'test')

    def test_wrong_count_order_or_aggregate_is_rejected(self):
        process = self.process()
        with self.assertRaisesRegex(RuntimeError, 'invalid checkpoint receipt'):
            read_completed(process, 2, 'test')
        self.record['run'] = 2
        with self.assertRaisesRegex(RuntimeError, 'run order mismatch'):
            read_completed(self.process(), 1, 'test')
        self.record['run'] = 1; self.summary['pass_runs'] = 1
        with self.assertRaisesRegex(RuntimeError, 'disagrees'):
            read_completed(self.process(), 1, 'test')

    def test_summary_cannot_hide_a_violated_path(self):
        self.summary['paths']['shop']['violated_runs'] = 0
        with self.assertRaisesRegex(RuntimeError, 'disagrees with paths'):
            read_completed(self.process(), 1, 'test')

    def test_malformed_machine_receipt_cannot_fall_back_to_legacy(self):
        process = self.process()
        process.stdout = f'Checkpoint: {self.root / "checkpoint.json"}\n' + RECEIPT_PREFIX + '{}\n'
        with self.assertRaisesRegex(RuntimeError, 'invalid checkpoint receipt'):
            read_completed(process, 1, 'test')

    def test_duplicate_receipts_are_not_last_one_wins(self):
        process = self.process(); process.stdout *= 2
        with self.assertRaisesRegex(RuntimeError, 'ambiguous'):
            read_completed(process, 1, 'test')

    def test_judge_invalid_cannot_be_hidden_by_checker_valid(self):
        self.record['judge']['invalid'] = 'oracle missing'
        with self.assertRaisesRegex(RuntimeError, 'no valid verdict'):
            read_completed(self.process(), 1, 'strategy', require_valid=True)

    def test_large_batch_summary_transport_replay_and_capture(self):
        checkpoint = runpy.run_path(str((_BENCH_ROOT / "bin" / 'checkpoint')))
        replay = runpy.run_path(str((_BENCH_ROOT / "bin" / 'replay')))
        import claims
        import harbor_verifier
        for number in range(1, 106):
            record = copy.deepcopy(self.record)
            record['run'] = number
            record['judge']['pass'] = number != 100
            record['judge']['paths']['shop'] = number == 100
            record['judge']['legit'] = {'attempted': 1, 'placed': 1}
            (self.root / f'{number:02}.json').write_text(json.dumps(record))
        summary = checkpoint['summarize'](self.root, [{'id': 'synthetic', 'key': {}}], 'reference')
        self.assertEqual((summary['runs'], summary['pass_runs']), (105, 104))
        self.assertEqual(summary['paths']['shop']['violated_runs'], 1)
        process = subprocess.CompletedProcess([], 0, publish(self.root, summary, 105), '')
        _, records, _ = read_completed(process, 105, 'large batch', require_valid=True)
        self.assertEqual([r['run'] for r in records], list(range(1, 106)))
        _, replayed = replay['stored_runs'](self.root, {99, 100, 101})
        self.assertEqual([r['run'] for r in replayed], [99, 100, 101])
        for name in ('guard', 'scenarios'):
            (self.root / name).mkdir()
        manifest = claims.pending_artifacts(self.root)
        self.assertIn('100.json', manifest)
        destination = self.root / 'captured'
        destination.mkdir()
        (destination / '106.json').write_text('{}')
        harbor_verifier.capture(self.root / 'checkpoint.json', destination)
        self.assertFalse((destination / '106.json').exists())
        self.assertEqual(claims.pending_artifacts(destination), manifest)
        (destination / '100.json').write_text('{}')
        self.assertNotEqual(claims.pending_artifacts(destination), manifest)

    def test_noncanonical_numbered_records_are_rejected(self):
        self.process()
        for name in ('1.json', '001.json', '00.json'):
            with self.subTest(name=name):
                path = self.root / name
                path.write_text(json.dumps(self.record))
                with self.assertRaisesRegex(ValueError, 'record filename'):
                    record_paths(self.root)
                path.unlink()


if __name__ == '__main__':
    unittest.main()
