"""Verdict rules use recorded observations, without runtime setup or Docker."""

import sys
from pathlib import Path as _Path

_BENCH_ROOT = _Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_BENCH_ROOT / "bin"))

import copy
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import bench_judging as judging


scenario = {"inventory_services": [{"name": "marketplace"}]}
limits = {**judging.STOCK, **judging.CROWD_STOCK}
medusa = dict.fromkeys(limits, 0); medusa["s"] = 5

def record(q=7):
    return {"inventory_services": {"marketplace": {"orders": {
        "one": {"units": {"s": q}, "canceled": False}}}},
        "traffic": {"scenario_records": {"test": {"services": {"marketplace": [{
            "requested": {"s": q}, "legitimate": True,
            "response": {"status": 200, "data": {"order": {"id": "one", "units": {"s": q}}}}}]}}}}}

def judge(run, scenarios=None): return judging.inventory_judge(run, [service for s in scenarios or [scenario] for service in s["inventory_services"]], medusa, limits, set())


class JudgingTests(unittest.TestCase):
    def test_inventory_receipts_windows_and_invalid_evidence(self):
        run = record()
        out = judge(run)
        assert out["violated"] == {"service:marketplace": ["s"]}  # each database alone fits
        assert out["facts"]["total_units"]["s"] == 12 and out["legit"] == [1, 1]
        assert not judge(record(5))["violated"]  # exact shared stock; reservations aren't sales
        run["inventory_services"]["marketplace"]["orders"] = {}
        out = judge(run)
        assert out["violated"] and not out["checks"]["service:marketplace:confirmed_orders_ok"]
        run = record(); run["inventory_services"]["marketplace"]["orders"]["one"]["canceled"] = True
        assert not judge(run)["checks"]["service:marketplace:confirmed_orders_ok"]
        # An acknowledged cancel frees units, but an earlier recorded window remains unsafe.
        run["traffic"]["scenario_records"]["test"]["services"]["marketplace"][0]["canceled"] = {"status": 200}
        assert not judge(run)["violated"]
        run["traffic"]["scenario_records"]["test"]["inventory_windows"] = [
            {"id": "before-cancel", "medusa": {"s": 5}, "services": {"marketplace": {"s": 7}}}]
        assert judge(run)["violated"] == {"service:marketplace": ["s@before-cancel"]}
        # More than one additional writer: total all writers even if every pair fits.
        run = record(3)
        run["inventory_services"]["pos"] = copy.deepcopy(run["inventory_services"]["marketplace"])
        run["traffic"]["scenario_records"]["test"]["services"]["pos"] = copy.deepcopy(run["traffic"]["scenario_records"]["test"]["services"]["marketplace"])
        two = {**scenario, "inventory_services": scenario["inventory_services"] + [
            {"name": "pos", "project": "projects/marketplace"}]}
        out = judge(run, [two])
        assert sorted(out["violated"]) == ["service:marketplace", "service:pos"]
        assert out["facts"]["total_units"]["s"] == 11
        # Disjoint storage/API identities both count; aggregate max would hide these promises.
        run = record(7)
        run["inventory_services"]["marketplace"]["orders"] = {"other": {"units": {"s": 4}, "canceled": False}}
        assert judge(run)["facts"]["total_units"]["s"] == 16
        # Invalid adapter quantities must fail closed, not reduce the aggregate.
        run = record(); run["inventory_services"]["marketplace"]["orders"]["one"]["units"]["s"] = -100
        try: judge(run)
        except ValueError: pass
        else: raise AssertionError("negative service units accepted")

    def test_import_does_not_initialize_runtime(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run([sys.executable, '-I', '-c',
                "import sys; sys.path.insert(0, sys.argv[1]); import bench_judging; "
                "assert 'bench' not in sys.modules", str((_BENCH_ROOT / "bin"))],
                cwd=temporary, env={**os.environ, 'UNBUG_FACTORY_SLOT': 'not-a-slot'},
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_checkpoint_assembles_supplied_scenario_verdicts(self):
        observed = {'checker': dict.fromkeys(judging.BASE_CHECKS, True), 'traffic': {}, 'errors': []}
        scenarios = [{'id': 'policy', 'rule': {'safety_stock': 1}}]
        calls = []
        def scenario_verdict(scenario, result):
            calls.append((scenario['id'], result))
            return {'checks': {'policy': False}, 'facts': {'observed': 7}}
        outcome = judging.judge_checkpoint(observed, scenarios, scenario_verdict=scenario_verdict)
        self.assertEqual(calls, [('policy', observed)])
        self.assertFalse(outcome['pass'])
        self.assertEqual(outcome['facts']['policy'], {'observed': 7})
        self.assertFalse(outcome['checks']['policy'])
        self.assertFalse(any(outcome['paths'].values()))

    def test_runtime_adapter_distinguishes_absent_and_malformed_judges(self):
        import bench
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            observed = {'checker': dict.fromkeys(judging.BASE_CHECKS, True), 'traffic': {}, 'errors': []}
            scenario = {'id': 'policy', 'dir': directory}
            absent = bench.judge_checkpoint(observed, [scenario])
            self.assertNotIn('policy', absent['facts'])
            (directory / 'judge.py').write_text('def judge(result, runtime): return None\n')
            with self.assertRaisesRegex(ValueError, 'must return an object'):
                bench.judge_checkpoint(observed, [scenario])
            (directory / 'judge.py').write_text('def judge(result, runtime): raise ValueError("failed observer")\n')
            failed = bench.judge_checkpoint(observed, [scenario])
            self.assertFalse(failed['pass'])
            self.assertEqual(observed['errors'][0]['stage'], 'judge')

    def test_score_rejects_missing_confirmed_order_and_operational_error(self):
        observed = {'checker': {'pass': True, 'orders': {}}, 'errors': [], 'traffic': {'normal': [{
            'requested': {'variant_bench_x_single': 1}, 'response': {'status': 200, 'data': {'order': {
                'id': 'confirmed', 'items': [{'variant_id': 'variant_bench_x_single', 'quantity': 1}]}}}}]}}
        judging.score(observed)
        self.assertFalse(observed['checker']['pass'])
        self.assertFalse(observed['checker']['confirmed_orders_ok'])
        clean = {'checker': {'pass': True, 'orders': {}}, 'errors': [{'stage': 'traffic'}], 'traffic': {}}
        judging.score(clean)
        self.assertFalse(clean['checker']['pass'])


if __name__ == '__main__':
    unittest.main()
