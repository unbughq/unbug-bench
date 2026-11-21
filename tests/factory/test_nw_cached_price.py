"""new-nw-cached-price-1 (hotfix port): the gate counts Neuralwatt's cached prompt tokens at its list cache
rate. cae763-h6's G10 easy calibrator (2026-11-21) stopped model_call_cap at ~$0.25 of list spend."""
import sys, unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin')]
import model_call_gate as gate
from token_prices import _gate_maximum, gate_profile, openrouter_gate_cost

GLM = 'neuralwatt/glm-5.3-flash'
USAGE = {'prompt_tokens': 65000, 'completion_tokens': 400, 'total_tokens': 65400,
         'prompt_tokens_details': {'cached_tokens': 63700, 'created_cache_tokens': 0},
         'completion_tokens_details': {'reasoning_tokens': 40}}


class NeuralwattCachedPrice(unittest.TestCase):
    def test_cost_at_list_cache_rate(self):
        want = (Decimal(1300) * Decimal('0.15') + Decimal(63700) * Decimal('0.03') + Decimal(400) * Decimal('0.5')) / 1_000_000
        self.assertEqual(openrouter_gate_cost(GLM, USAGE), want)

    def test_openrouter_without_cost_unchanged(self):
        twin = 'openrouter/z-ai/glm-5.3-flash'
        self.assertEqual(openrouter_gate_cost(twin, USAGE), (Decimal(65000) * Decimal('0.15') + Decimal(400) * Decimal('0.5')) / 1_000_000)

    def test_malformed_cached_is_refused(self):
        self.assertIsNone(openrouter_gate_cost(GLM, dict(USAGE, prompt_tokens_details={'cached_tokens': 70000})))

    def test_easy_calibrator_try_fits_its_window(self):
        lease = SimpleNamespace(route=GLM, **{k: v for k, v in _gate_maximum(GLM, gate_profile(GLM)).items() if k.startswith('max_')})
        lease.max_usd = 1.2582918
        state = gate.Allowance(lease)
        for _ in range(130):   # the old full-rate count cuts at ~110, a gate-only revert at ~113
            identity = state.reserve(gate.OPENROUTER_OUTPUT)
            self.assertIsNotNone(identity, 'a list-priced try must fit its window')
            state.finish(identity, USAGE)


if __name__ == '__main__':
    unittest.main()
