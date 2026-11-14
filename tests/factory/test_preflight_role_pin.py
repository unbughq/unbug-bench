"""Every provider preflight call is booked to the role it checks (13 Nov, case 1110a-2: the second
reviewer's check was named 'reviewer2-...', read as the first reviewer, and refused as 'role family
changed' on every ADMIT attempt)."""
from pathlib import Path
from types import SimpleNamespace
import os
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "factory")]
os.environ.setdefault("BENCH", str(ROOT))
import model_runtime  # noqa: E402
import run  # noqa: E402
from model_router import family  # noqa: E402

MODELS = {'writer': 'openrouter/deepseek/deepseek-v4.1-flash', 'stress_tester': 'codex/gpt-6.1-sol',
          'reviewer': 'openrouter/xiaomi/mimo-v2.6-pro', 'reviewer2': 'opencode-go/glm-5.3-flash',
          'strong_calibrator': 'claude/claude-opus-5-5', 'easy_calibrator': 'openrouter/z-ai/glm-5.3-flash'}


class PreflightRolePin(unittest.TestCase):
    def test_every_preflight_passes_the_real_role_pin_check(self):
        c = SimpleNamespace(case='/nonexistent', card={'roles': {r: {'model': m, 'family': family(m)} for r, m in MODELS.items()}},
                            models={'builder': [MODELS['writer']], 'attacker': [MODELS['stress_tester']],
                                    'reviewers': [[MODELS['reviewer']], [MODELS['reviewer2']]],
                                    'strong_calibrator': [MODELS['strong_calibrator']],
                                    'easy_calibrator': [MODELS['easy_calibrator']]})
        runtime, refused = model_runtime.ModelRuntime.__new__(model_runtime.ModelRuntime), []

        class Past(Exception): pass

        def through_pin(c, chain, text, cwd, name, **kw):
            # The real ModelRuntime._call: the pin check runs first; stop the call once it is past.
            saved = model_runtime.copy.copy
            model_runtime.copy.copy = lambda _: (_ for _ in ()).throw(Past())
            try: runtime._call(c, chain, text, cwd, name)
            except Past: return 0
            except ValueError as error: refused.append((name, str(error))); return 0
            finally: model_runtime.copy.copy = saved
        saved = run.opencode
        run.opencode = through_pin
        try: run.provider_preflight(c)
        finally: run.opencode = saved
        self.assertEqual(refused, [])
        self.assertEqual([r['role'] for r in c.card['provider_preflight']],
                         ['writer', 'stress_tester', 'reviewer', 'reviewer2', 'strong_tester', 'easy_tester'])


if __name__ == "__main__":
    unittest.main()
