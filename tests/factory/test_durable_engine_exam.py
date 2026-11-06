"""The durable-execution mid-term exam (WP1 "Done when", docs/designs/durable-execution.md).

A batch of three cases on fake workers runs to the end while the engine process is killed
with SIGKILL at 20 random points. One case repairs after stress findings; one has an infra
retry and a provider sleep; one is retired by a gate, which starts a replacement. The run
must match an unkilled reference run, and no finished step may run twice:

- the worker ran each attempt key at most once, and never refused one as busy;
- no attempt step was entered again after its settle was booked (only the open step reruns);
- every case started the same attempts, in the same order, as in the reference run;
- ADMITs never overlapped;
- the final ledger equals the reference ledger.

Real DBOS 3.4.0 on SQLite. Set EXAM_SEED to replay one set of kill points.
"""
import os
from pathlib import Path
import random
import signal
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "factory"), str(Path(__file__).resolve().parent)]
os.environ.setdefault("BENCH", str(ROOT))

from test_durable_engine_fakes import EngineRun  # noqa: E402

KILLS = 20
SCENARIO = {
    "spec": {"target_sealed": 3, "max_cases_started": 4, "max_concurrency": 2},
    "default_dur": 0.2,
    "script": {
        "1/stress:1/1": {"feedback": True},
        "2/writer:1/1": {"outcome": "infra_error", "reason": "infra:stalled", "paid": 3000},
        "2/gates:1/1": {"outcome": "provider_limit", "reason": "router:claude_limit", "retry_in": 0.8, "paid": 0},
        "3/gates:1/1": {"outcome": "gate_failed", "gate": "G2", "reason": "g2:public_fix", "passed": ["G1"]},
    },
}
EXPECTED = {"case-t-1": "sealed", "case-t-2": "sealed", "case-t-3": "retired", "case-t-4": "sealed"}


def ledger_view(ledger):
    return {"batches": ledger["batches"], "cases": ledger["cases"],
            "res": {k: (v["amount"], v["label"], v["draws"], v["settled"]) for k, v in ledger["res"].items()}}


class MidTermExam(unittest.TestCase):
    def check_run(self, r, out):
        self.assertEqual(out["result"]["cases"], EXPECTED)
        log = r.worker_log()
        ran = [x["key"] for x in log if x["op"] == "ran"]
        self.assertEqual(len(ran), len(set(ran)), "an attempt ran twice on the worker")
        self.assertFalse([x for x in log if x["op"] == "start" and x["mode"] != "run"], "busy or bad input")
        spans = sorted((x["t"], next(y["done_at"] for y in log if y["op"] == "ran" and y["key"] == x["key"]))
                       for x in log if x["op"] == "start" and "/admit/" in x["key"])
        for (_, e1), (s2, _) in zip(spans, spans[1:]):
            self.assertGreaterEqual(s2, e1, "two ADMITs overlapped")

    def test_three_cases_survive_twenty_kills(self):
        ref = EngineRun(SCENARIO)
        self.addCleanup(ref.close)
        ref_out = ref.run(timeout=180)
        self.check_run(ref, ref_out)
        self.assertFalse([x for x in ref.worker_log() if x["op"] == "start_again"])

        seed = int(os.environ.get("EXAM_SEED", time.time_ns() % 1_000_000))
        rng = random.Random(seed)
        r = EngineRun(SCENARIO)
        self.addCleanup(r.close)
        kills, deadline = 0, time.time() + 600
        while kills < KILLS and time.time() < deadline:
            p = r.spawn()
            seen = len(r.worker_log())
            want = rng.randint(0, 2)   # 0: a kill point during startup or recovery
            while p.poll() is None and len(r.worker_log()) < seen + want and time.time() < deadline:
                time.sleep(0.01)
            time.sleep(rng.uniform(0.0, 0.3))
            if p.poll() is not None:
                break   # finished before this kill point
            p.send_signal(signal.SIGKILL)
            p.wait()
            kills += 1
        self.assertEqual(kills, KILLS, f"seed {seed}: the batch finished after {kills} kills; raise the durations")
        out = r.run(timeout=300)
        msg = f"seed {seed}"
        self.check_run(r, out)
        # Only the open step reruns: no attempt step was entered again after its settle.
        settled = {}
        for x in r.ledger_log():
            if x["op"] in ("settle", "settle_lost"):
                settled.setdefault(x["key"], x["t"])
        for x in r.worker_log():
            if x["op"] == "start_again" and x["key"] in settled:
                self.assertLess(x["t"], settled[x["key"]], f"{msg}: {x['key']} reran after it finished")
        for n in range(1, 5):
            self.assertEqual(r.keys(n), ref.keys(n), f"{msg}: case {n} diverged from the reference")
        self.assertEqual(ledger_view(out["ledger"]), ledger_view(ref_out["ledger"]), msg)
        self.assertEqual([c["status"] for c in out["scorecard"]["cases"]],
                         [c["status"] for c in ref_out["scorecard"]["cases"]])
        print(f"exam: seed {seed}, {kills} kills, "
              f"{len([x for x in r.worker_log() if x['op'] == 'start_again'])} open steps reattached", flush=True)


if __name__ == "__main__":
    unittest.main()
