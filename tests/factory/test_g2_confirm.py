#!/usr/bin/env python3
"""G2 fails only on reviewer-confirmed hits; a missing or malformed verdict keeps every flagged hit (synthetic)."""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import json, os, pathlib, sys, tempfile, types
sys.path.insert(0, str((pathlib.Path(__file__).resolve().parents[2] / "factory")))
os.environ.setdefault("BENCH", str(pathlib.Path(__file__).resolve().parents[2]))
import run
from unittest.mock import patch

with tempfile.TemporaryDirectory() as t:
    t = pathlib.Path(t); (t / "case").mkdir(); (t / "work").mkdir()
    from test_admission import evidence
    lines = [evidence("builder", k, i, hit=i < 2) for i, k in enumerate(["web"] * 3 + ["github"] * 3)]
    lines += [evidence("attacker", "web", i) for i in range(2)]
    (t / "case/freshness.jsonl").write_text("\n".join(json.dumps(x) for x in lines))
    c = types.SimpleNamespace(case=t / "case", work=t / "work", card={}, args=types.SimpleNamespace(),
                              models={"reviewers": [["opencode-go/x"]]})
    cleared = lambda i: {"same_bug": False, "resolved": True, "url": lines[i]["url"], "why": "Other app/version", "retrieved": True, "app_version": "2.19.0", "version_scope": "Other app"}
    for verdict, ok, hits in (({"hits": [cleared(0), cleared(1)]}, True, 0),
                              ({"hits": [cleared(0), {"same_bug": True}]}, False, 1),
                              ({"hits": [cleared(0), {}]}, False, 1),          # not explicitly cleared
                              ({"hits": [cleared(0)]}, False, 2),              # wrong length: all stand
                              (None, False, 2)):                                        # no verdict: all stand
        def fake(c, m, text, cwd, name, v=verdict, **kwargs):
            if v: (pathlib.Path(cwd) / "verdict.json").write_text(json.dumps(v))
            return 0
        with patch.object(run, 'opencode', fake):
            (c.work / "public-search.json").unlink(missing_ok=True)
            (c.work / "freshness-verdict.json").unlink(missing_ok=True)
            got = run.g2(c)
        assert got[0] is ok and got[1]["hits"] == hits and got[1]["flagged_hits"] == 2, (verdict, got)
print("PASS G2 fails only on confirmed hits; missing, short or unclear verdicts fail closed")
