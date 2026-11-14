"""Every model call is booked to the role whose model it uses (13 Nov, case 1110a-2: the second
reviewer's preflight was named 'reviewer2-...', read as the first reviewer, and refused as 'role family
changed' on every ADMIT attempt; independent_review named the second reviewer's G11/G16/G17 call the same way)."""
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
import tempfile  # noqa: E402
import budget  # noqa: E402
import independent_review  # noqa: E402
from model_router import family  # noqa: E402

MODELS = {'writer': 'openrouter/deepseek/deepseek-v4.1-flash', 'stress_tester': 'codex/gpt-6.1-sol',
          'reviewer': 'openrouter/xiaomi/mimo-v2.6-pro', 'reviewer2': 'opencode-go/glm-5.3-flash',
          'strong_calibrator': 'claude/claude-opus-5-5', 'easy_calibrator': 'openrouter/z-ai/glm-5.3-flash'}


def context(**more):
    return SimpleNamespace(case='/nonexistent', card={'roles': {r: {'model': m, 'family': family(m)} for r, m in MODELS.items()}},
                           models={'builder': [MODELS['writer']], 'attacker': [MODELS['stress_tester']],
                                   'reviewers': [[MODELS['reviewer']], [MODELS['reviewer2']]],
                                   'strong_calibrator': [MODELS['strong_calibrator']],
                                   'easy_calibrator': [MODELS['easy_calibrator']]}, **more)


class Past(Exception): pass


def pin_checker(refused, code=0):
    """A model call that runs the real ModelRuntime._call up to and through its role pin check."""
    runtime = model_runtime.ModelRuntime.__new__(model_runtime.ModelRuntime)
    def call(c, chain, text, cwd, name, **kw):
        saved = model_runtime.copy.copy
        model_runtime.copy.copy = lambda _: (_ for _ in ()).throw(Past())   # the first step after the check
        try: runtime._call(c, chain, text, cwd, name)
        except Past: return code
        except ValueError as error: refused.append((name, str(error))); return code
        finally: model_runtime.copy.copy = saved
    return call


class PreflightRolePin(unittest.TestCase):
    def test_every_preflight_passes_the_real_role_pin_check(self):
        c, refused = context(), []
        through_pin = pin_checker(refused)
        saved = run.opencode
        run.opencode = through_pin
        try: run.provider_preflight(c)
        finally: run.opencode = saved
        self.assertEqual(refused, [])
        self.assertEqual([r['role'] for r in c.card['provider_preflight']],
                         ['writer', 'stress_tester', 'reviewer', 'reviewer2', 'strong_tester', 'easy_tester'])

    def test_the_second_independent_reviewer_passes_the_real_role_pin_check(self):
        # G11/G16/G17: an inconclusive first reviewer hands the gate to the second (gate_state.SECOND_REVIEWER_GATES).
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / 'evidence').mkdir(); (Path(t) / 'evidence/x').write_text('x')
            (Path(t) / 'work').mkdir()
            refused, names = [], []
            checker = pin_checker(refused, code=1)   # every reviewer inconclusive
            r = SimpleNamespace(family=family, model_call=lambda c, chain, text, cwd, name, **kw:
                                names.append(name) or checker(c, chain, text, cwd, name))
            with self.assertRaises(Exception):   # both inconclusive: the gate's normal fallback stop
                independent_review.review(context(work=Path(t) / 'work'), r, 'G11', {'evidence': Path(t) / 'evidence'},
                                          'review', lambda v: v)
        self.assertEqual(names, ['reviewer-g11', 'reviewer-2-g11'])
        self.assertEqual(refused, [])

    def test_every_call_name_maps_to_the_role_whose_model_it_uses(self):
        # (name the factory builds, role whose chain it is given) for every model call site.
        sites = [('builder-provider-preflight', 'writer'), ('attacker-provider-preflight', 'stress_tester'),   # run.provider_preflight
                 ('reviewer-provider-preflight', 'reviewer'), ('reviewer-2-provider-preflight', 'reviewer2'),
                 ('strong-calibrator-provider-preflight', 'strong_calibrator'),
                 ('easy-calibrator-provider-preflight', 'easy_calibrator'),
                 ('builder-freshness', 'writer'), ('attacker-freshness', 'stress_tester'),                        # run.py freshness repair
                 ('builder-freshness-web', 'writer'), ('attacker-freshness-web', 'stress_tester'),                # freshness_fanout._ask
                 ('builder-selection', 'writer'), ('builder-selection-2', 'writer'),                              # statement_precheck, admit._screen
                 ('easy-calibrator-dedup', 'easy_calibrator'), ('reviewer-idea-realism', 'reviewer'),
                 ('reviewer-g2-confirm', 'reviewer'), ('builder-3', 'writer'), ('builder-3-fix-1', 'writer'),
                 ('reviewer-1', 'reviewer'), ('reviewer-2', 'reviewer2'),                                         # run.review panel
                 ('attacker-4', 'stress_tester'),                                                                 # stress_progress
                 ('strong-calibrator-early_probe-1', 'strong_calibrator'), ('easy-calibrator-calibration-2', 'easy_calibrator'),
                 ('reviewer-g11-audit', 'reviewer'), ('reviewer-owner-ws-try-1-3', 'reviewer'),                   # g11_review, exam_responder
                 ('reviewer-g16', 'reviewer'), ('reviewer-2-g16', 'reviewer2'),                                   # independent_review
                 ('diagnosis-0123abcd', 'reviewer')]                                                              # diagnosis_dispatch.reviewer
        sites += [(prefix + '-second-opinion-dedup', {'reviewer': 'reviewer', 'reviewer-2': 'reviewer2', 'attacker': 'stress_tester',
                   'easy-calibrator': 'easy_calibrator'}[prefix]) for prefix in run._SECOND_PREFIX.values()]
        self.assertEqual([(n, budget.invocation_role(n)) for n, _ in sites], sites)

    def test_an_unknown_call_name_is_refused_not_booked_to_the_first_reviewer(self):
        for name in ('reviewer2-provider-preflight', 'reviewers-x', 'pilot-1', 'x'):
            with self.assertRaises(ValueError): budget.invocation_role(name)


if __name__ == "__main__":
    unittest.main()
