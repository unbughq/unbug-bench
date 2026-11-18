"""G11/G16/G17's independent reviewers are asked side by side (speed plan 2026-11-18); the first family still decides."""
from pathlib import Path
from types import SimpleNamespace
import json
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "factory"), str(ROOT / "bin"), str(Path(__file__).resolve().parent)]
import independent_review  # noqa: E402
from model_router import family  # noqa: E402
from test_preflight_role_pin import context  # noqa: E402


class SideBySide(unittest.TestCase):
    def review(self, answers):
        """answers: call name -> verdict the reviewer writes (None: no answer). Both calls must overlap."""
        met = threading.Barrier(2, timeout=5)   # one after the other, the first call would wait here alone
        def call(c, chain, text, cwd, name, **kw):
            met.wait()
            if answers[name] is not None:
                Path(text.rsplit('Write the JSON verdict to ', 1)[1][:-1]).write_text(json.dumps(answers[name]))
            return 0
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / 'evidence').mkdir(); (Path(t) / 'evidence/x').write_text('x'); (Path(t) / 'work').mkdir()
            r = SimpleNamespace(family=family, model_call=call)
            return independent_review.review(context(work=Path(t) / 'work'), r, 'G16', {'evidence': Path(t) / 'evidence'},
                                             'review', lambda v: v if v.get('ok') else None)

    def test_both_reviewers_run_together_and_the_first_family_still_decides(self):
        self.assertEqual(self.review({'reviewer-g16': {'ok': 1}, 'reviewer-2-g16': {'ok': 2}}), {'ok': 1})
        self.assertEqual(self.review({'reviewer-g16': None, 'reviewer-2-g16': {'ok': 2}}), {'ok': 2})


if __name__ == '__main__':
    unittest.main()
