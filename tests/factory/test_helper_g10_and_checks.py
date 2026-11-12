"""G10 tries and G5 checkpoints as helper jobs: same committed results and verdict inputs as the serial
path, tries concurrent and independent, a dead helper requeues only its job, flag off changes nothing."""
import sys
from pathlib import Path as _P
_ROOT = _P(__file__).resolve().parents[2]
sys.path[:0] = [str(_ROOT / "factory"), str(_ROOT / "bin"), str(_ROOT / "tests/bench")]
import argparse, json, tempfile, threading, time, types, unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
import run
import calibration
from durable import helpers
sys.path.insert(0, str(_ROOT / "tests/factory"))
from test_helper_machines import write_checkpoint


def solved_for(i): return i != 2          # try 2 of the fake model fails every run


def fake_files(i, *, submit=True, solved=None):
    solved = solved_for(i) if solved is None else solved
    execution = None
    if submit:
        rec = {"run": 1, "errors": [], "checker": {"valid": True},
               "judge": {"paths": {"p": False}, "checks": {"k": solved}}}
        execution = {"summary": {"runs": 1, "marker": i}, "records": [rec, rec]}
    files = {"result.json": json.dumps({"capped": None, "execution": execution})}
    if submit:
        import base64
        files["guard/db.sql"] = base64.b64encode(f"-- try {i}".encode()).decode()
    return files


class TryPool:
    def __init__(self, die_on=(), mutate=None):
        self.lock, self.die_on, self.mutate = threading.Lock(), set(die_on), mutate
        self.live = self.peak = self.leased = 0
        self.jobs, self.dead = [], []

    def lease(self):
        with self.lock:
            self.leased += 1
            return self.leased

    def run(self, handle, job, key):
        with self.lock:
            self.jobs.append(job)
            self.live += 1
            self.peak = max(self.peak, self.live)
            die = job["try"] in self.die_on
            self.die_on.discard(job["try"])
        try:
            time.sleep(0.05)   # let the other tries overlap
            if die: raise helpers.HelperDied()
            files = fake_files(job["try"]) if self.mutate is None else self.mutate(job["try"])
            return helpers.execute(job, key, check=lambda j: None, run=lambda j: files)
        finally:
            with self.lock: self.live -= 1

    def release(self, handle, dead):
        if dead: self.dead.append(handle)


class G10Tests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.tmp = Path(tempfile.mkdtemp())

    def context(self, name):
        root = self.tmp / name
        c = run.Ctx(); c.work = root / "work"; c.work.mkdir(parents=True)
        c.case = c.work / "case"; (c.case / "base").mkdir(parents=True)
        for n in ("promise.md", "contestant.md"): (c.case / n).write_text("synthetic contract")
        c.args = argparse.Namespace(pilot_tries=3, pilot_runs=2, calibrator_minutes=30, resume=None, helper_workers=0, bench_workers=1)
        c.models = {"easy_calibrator": ["synthetic/easy"], "reviewers": [["synthetic/reviewer"]]}
        c.seed, c.card, c.pilot_passes, c.manifest0 = 7, {}, [], "m"
        app = root / "bench/projects/medusa"; app.mkdir(parents=True); (app / "f.js").write_text("app")
        (root / "bench/harbor/responder").mkdir(parents=True)
        self.local, self.checkpoints = [], []
        def author(c_, role, name, exposure, i, make_ws):
            ws = make_ws(); (ws / "guard").mkdir(parents=True)
            (ws / "guard/db.sql").write_text(f"-- try {i}")
            self.local.append(i)
            return ws, None
        def checkpoint(c_, scenarios, guard, runs, seed, label):
            self.checkpoints.append((seed, label))
            i = seed - c_.seed
            return fake_files_exec(i)
        def delivery(case, bench, ws, **kw): ws.mkdir(parents=True); (ws / "DELIVERY.md").write_text("d")
        for owner, n, v in [(run, "BENCH", root / "bench"), (run, "_author_try", author), (run, "checkpoint", checkpoint),
                            (run, "prompt", lambda *a: "p"), (run, "prepare_delivery", delivery),
                            (run, "case_budget_boundary", lambda c_: None),
                            (run, "verdicts", lambda c_, recs: [{"clean": True, "solved": all(
                                ((r.get("judge") or {}).get("checks") or {}).get("k") for r in recs)}] * len(recs))]:
            self.stack.enter_context(patch.object(owner, n, v))
        return c

    def rows(self, c):
        out = []
        for r in json.loads((c.work / "easy_calibrator/results.json").read_text()):
            out.append({k: r.get(k) for k in ("try", "solved", "guard_submitted", "checked_runs", "solved_runs",
                                               "stop_reason", "scientific_outcome", "errors")} |
                       {"guard": (Path(r["guard"]) / "db.sql").read_text() if r.get("guard") else None})
        return out

    def test_flag_off_is_serial_and_never_touches_pool(self):
        c = self.context("off")
        c.helper_pool = types.SimpleNamespace(lease=lambda: 1 / 0)
        run.calibrate(c, "easy_calibrator")
        self.assertEqual(self.local, [1, 2, 3])
        self.assertEqual(len(self.checkpoints), 3)

    def test_hosted_tries_commit_the_same_results_concurrently(self):
        serial = self.context("serial")
        summary_serial = run.calibrate(serial, "easy_calibrator")
        rows_serial, local_serial = self.rows(serial), list(self.local)
        self.local.clear(); self.checkpoints.clear()
        c = self.context("hosted")
        pool = TryPool()
        c.args.helper_workers, c.helper_pool = 3, pool
        summary = run.calibrate(c, "easy_calibrator")
        self.assertEqual(summary, summary_serial)
        self.assertEqual(self.rows(c), rows_serial)
        self.assertEqual((self.local, self.checkpoints), ([], []))   # nothing authored or scored here
        self.assertEqual(pool.peak, 3)                                # all tries at once
        self.assertEqual(sorted(j["try"] for j in pool.jobs), [1, 2, 3])
        for job in pool.jobs:
            self.assertEqual((job["seed"], job["runs"], job["minutes"], job["role"], job["name"], job["workers"]),
                             (7 + job["try"], 2, 30, "easy_calibrator", "easy_calibrator", 1))
            self.assertEqual(job["case"], run.case_hash(c))
        self.assertEqual(len({j["identity"] for j in pool.jobs}), 1)
        self.assertEqual(local_serial, [1, 2, 3])

    def test_dead_helper_requeues_only_its_try(self):
        c = self.context("dead")
        pool = TryPool(die_on=[2])
        c.args.helper_workers, c.helper_pool = 3, pool
        run.calibrate(c, "easy_calibrator")
        self.assertEqual(sorted(j["try"] for j in pool.jobs), [1, 2, 2, 3])
        self.assertEqual(len(pool.dead), 1)
        self.assertEqual((self.local, self.checkpoints), ([], []))

    def test_try_a_helper_cannot_complete_is_authored_here(self):
        c = self.context("broken")
        pool = TryPool(mutate=lambda i: fake_files(i, submit=False) if i == 3 else fake_files(i))
        # try 3 returns no guard and no execution: a valid "no guard written" result, committed as such
        c.args.helper_workers, c.helper_pool = 3, pool
        run.calibrate(c, "easy_calibrator")
        self.assertEqual(self.rows(c)[2]["guard_submitted"], False)
        self.local.clear()
        bad = self.context("bad")
        bad.args.helper_workers = 3
        bad.helper_pool = TryPool(mutate=lambda i: {**fake_files(i), "guard/../evil": "AA=="} if i == 1 else fake_files(i))
        run.calibrate(bad, "easy_calibrator")
        self.assertEqual(self.local, [1])   # the malformed result is dropped; try 1 runs here, the others stay hosted

    def test_unpack_rejects_inconsistent_results(self):
        good = fake_files(1)
        helpers.unpack_try(good)
        for bad in ({"result.json": good["result.json"]},                           # execution without a guard
                    {**fake_files(1, submit=False), "guard/db.sql": good["guard/db.sql"]},  # guard without execution
                    {**good, "guard/../x": "AA=="}, {**good, "other": "AA=="},
                    {"result.json": json.dumps({"capped": "weird", "execution": None})}):
            with self.assertRaises(ValueError): helpers.unpack_try(bad)

    def test_job_and_pack_round_trip(self):
        guard = self.tmp / "guard"; (guard / "sub").mkdir(parents=True)
        (guard / "db.sql").write_bytes(b"\x00\xffbin"); (guard / "sub/x.patch").write_text("p")
        files = helpers.pack_try(guard, "timeout", {"summary": {}, "records": []})
        out = helpers.unpack_try(files)
        self.assertEqual(out["guard"], {"db.sql": b"\x00\xffbin", "sub/x.patch": b"p"})
        job = helpers.make_try_job(case="c", role="r", name="n", exposure="blind", number=1, seed=1, runs=1, minutes=1,
                                   model=["m"], identity="i", bench="b", release="r")
        sealed = helpers.execute(job, b"k" * 32, check=lambda j: None, run=lambda j: files)
        self.assertEqual(helpers.open_sealed(b"k" * 32, job, sealed), files)

    def test_g10_and_g5_bind_helper_code(self):
        import gate_state
        self.assertIn("factory/durable/helpers.py", gate_state.DEPENDENCIES["G5"])
        self.assertIn("factory/durable/helpers.py", gate_state.STAGE_DEPENDENCIES["G10"])


def fake_files_exec(i):
    rec = {"run": 1, "errors": [], "checker": {"valid": True},
           "judge": {"paths": {"p": False}, "checks": {"k": solved_for(i)}}}
    return {"runs": 1, "marker": i}, [rec, rec]


class G5Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        case = self.tmp / "case"
        (case / "base").mkdir(parents=True); (case / "base/x").write_text("x")
        (case / "guards/reference").mkdir(parents=True); (case / "guards/reference/g").write_text("ref")
        for s in ("s1", "s2"):
            (case / "scenarios" / s / "examples/fix").mkdir(parents=True)
            (case / "scenarios" / s / "examples/fix/g").write_text(s)
            (case / "scenarios" / s / "key.json").write_text(json.dumps({"expected_judge": {"fix": {}}}))
        (case / "case.json").write_text("{}")
        work = self.tmp / "work"; work.mkdir()
        self.c = types.SimpleNamespace(case=case, work=work, seed=5, card={}, manifest0="m",
                                       args=types.SimpleNamespace(runs=3, scenario_runs=2, helper_workers=0, bench_workers=1))

    def pool(self, tmp):
        class P:
            lock = threading.Lock(); ran = []; n = 0
            def lease(s):
                with s.lock: s.n += 1; return s.n
            def run(s, handle, job, key):
                with s.lock: s.ran.append(job)
                return helpers.execute(job, key, check=lambda j: None,
                                       run=lambda j: write_checkpoint(tmp / f"h{handle}-{len(s.ran)}", j["runs"], True))
            def release(s, handle, dead): pass
        return P()

    def test_g5_checkpoints_run_as_jobs_and_flag_off_is_untouched(self):
        self.c.helper_pool = types.SimpleNamespace(lease=lambda: 1 / 0)
        self.assertEqual(run.g5_shards(self.c), {})
        pool = self.pool(self.tmp)
        self.c.args.helper_workers, self.c.helper_pool = 3, pool
        with patch.object(run, "case_budget_boundary"):
            shards = run.g5_shards(self.c)
        self.assertEqual(sorted(shards), ["reference", "s1/fix", "s2/fix"])
        base = helpers.digest_of(run.tree_digest(self.c.case / "base"))
        self.assertEqual({(j["label"], j["runs"], len(j["scenarios"]), j["seed"]) for j in pool.ran},
                         {("g5-reference", 3, 1, 5), ("g5-key", 2, 2, 5)})
        for j in pool.ran: self.assertEqual(j["scenarios"][0], base)
        summary, records = shards["reference"]
        self.assertEqual(len(records), 3)
        self.assertIn("legit", records[0]["judge"])


if __name__ == "__main__":
    unittest.main()
