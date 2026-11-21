"""G10 tries and G5 checkpoints as helper jobs: same committed results and verdict inputs as the serial
path, tries concurrent and independent, a dead helper requeues only its job, flag off changes nothing."""
import sys
from pathlib import Path as _P
_ROOT = _P(__file__).resolve().parents[2]
sys.path[:0] = [str(_ROOT / "factory"), str(_ROOT / "bin"), str(_ROOT / "tests/bench")]
from decimal import Decimal
import argparse, json, tempfile, threading, time, types, unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
import run
import calibration
from durable import helpers
sys.path.insert(0, str(_ROOT / "tests/factory"))
from test_helper_machines import write_checkpoint


REAL_AUTHORITY, REAL_AUTHOR = run.helper_try_authority, run._author_try


def solved_for(i): return i != 2          # try 2 of the fake model fails every run


def fake_execution(i, runs=2, solved=None):
    solved = solved_for(i) if solved is None else solved
    recs = [{"run": n, "errors": [], "checker": {"valid": True},
             "judge": {"pass": solved, "paths": {"p": False}, "checks": {"k": solved}, "legit": {"attempted": 1, "placed": 1}}}
            for n in range(1, runs + 1)]
    summary = {"runs": runs, "pass_runs": runs if solved else 0, "error_runs": 0, "invalid_runs": 0,
               "paths": {"p": {"violated_runs": 0, "runs": runs}},
               "checks": {"k": {"ok_runs": runs if solved else 0, "runs": runs}}}
    return {"summary": summary, "records": recs}


def fake_files(i, *, submit=True, solved=None, runs=2):
    execution = fake_execution(i, runs, solved) if submit else None
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
        for owner, n, v in [(run, "BENCH", root / "bench"), (run, "_author_try", author), (run, "try_checkpoint", checkpoint),
                            (run, "prompt", lambda *a: "p"), (run, "prepare_delivery", delivery),
                            (run, "case_budget_boundary", lambda c_: None),
                            (run, "helper_try_authority", lambda c_, role, exposure, n: (Decimal("1"), n)),
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

    # --- review fixes -------------------------------------------------------------------------------

    def hosted(self, name, pool, workers=3, tries=3):
        c = self.context(name)
        c.args.helper_workers, c.args.pilot_tries, c.helper_pool = workers, tries, pool
        return c

    def test_truncated_or_invalid_try_execution_is_not_committed(self):
        short = lambda i: fake_files(i, runs=1) if i == 1 else fake_files(i)      # 1 record for pilot_runs=2
        invalid = lambda i: (fake_files(i) if i != 1 else {
            **fake_files(i), "result.json": json.dumps({"capped": None, "execution": {
                **fake_execution(1), "records": [{**r, "checker": {"valid": False}} for r in fake_execution(1)["records"]]}})})
        for n, mutate in enumerate((short, invalid)):
            pool = TryPool(mutate=mutate)
            c = self.hosted(f"trunc{n}", pool)
            run.calibrate(c, "easy_calibrator")
            self.assertEqual(self.local, [1])                                      # dropped, authored here
            self.assertEqual(self.rows(c)[0]["checked_runs"], 2)
            self.assertEqual(sorted(j["try"] for j in pool.jobs).count(1), helpers.MAX_ATTEMPTS)

    def test_a_seed_tamper_try_scored_on_a_helper_is_accepted_as_a_failed_try(self):
        """2a7b2a-h4 shape on a helper (founder 2026-11-21): the try counts as failed; it is not re-dispatched or re-authored."""
        def tamper(i):
            if i != 1: return fake_files(i)
            errors = [{"stage": "reset", "message": "Baseline changed during application startup"},
                      {"stage": "installation", "message": "Frozen installation identity changed"}]
            recs = [{"run": n, "errors": errors, "checker": {"valid": False},
                     "judge": {"pass": False, "paths": {}, "checks": {}, "invalid": "reset failed"}} for n in (1, 2)]
            summary = {"runs": 2, "pass_runs": 0, "error_runs": 2, "invalid_runs": 2, "paths": {}, "checks": {}}
            return {**fake_files(i), "result.json": json.dumps({"capped": None, "execution": {"summary": summary, "records": recs}})}
        pool = TryPool(mutate=tamper)
        c = self.hosted("tamper", pool)
        run.calibrate(c, "easy_calibrator")
        self.assertEqual((self.local, self.checkpoints), ([], []))
        self.assertEqual(sorted(j["try"] for j in pool.jobs), [1, 2, 3])
        first = self.rows(c)[0]
        self.assertEqual((first["solved"], first["errors"], first["checked_runs"], first["solved_runs"], first["scientific_outcome"]),
                         (False, 0, 2, 0, "demonstrated_failure"))

    def test_money_authority_sized_up_front_for_all_tries(self):
        c = self.context("money")
        c.models = {"easy_calibrator": ["synthetic/easy"], "reviewers": [["synthetic/reviewer"]]}
        spend = {"limit_usd": 50.0, "total_spent_usd": 0.0}
        with patch.object(run.model_router, "_bounded_routes", lambda model, accounts: [{"max_usd": 20}]), \
             patch.object(run, "update_case_budget", lambda c_: ({}, spend)):
            self.assertEqual(REAL_AUTHORITY(c, "easy_calibrator", "blind", 3), (Decimal("12.5"), 3))   # one call window each
            self.assertEqual(REAL_AUTHORITY(c, "easy_calibrator", "exam", 3), (Decimal("32.5"), 1))    # plus the owner window
            spend["total_spent_usd"] = 30.0
            self.assertEqual(REAL_AUTHORITY(c, "easy_calibrator", "blind", 3), (Decimal("12.5"), 1))
            spend["total_spent_usd"] = 49.0
            self.assertEqual(REAL_AUTHORITY(c, "easy_calibrator", "blind", 3)[1], 0)
        with patch.object(run.model_router, "_bounded_routes", lambda model, accounts: []):
            self.assertEqual(REAL_AUTHORITY(c, "easy_calibrator", "blind", 3)[1], 0)

    def test_tries_beyond_the_authority_run_here_and_the_hold_is_recorded(self):
        pool = TryPool()
        c = self.hosted("cap", pool)
        with patch.object(run, "helper_try_authority", lambda c_, role, exposure, n: (Decimal("12.5"), 1)):
            run.calibrate(c, "easy_calibrator")
        self.assertEqual([j["try"] for j in pool.jobs], [1])
        self.assertEqual(pool.jobs[0]["authority_usd"], "12.5")
        self.assertEqual(self.local, [2, 3])
        self.assertEqual(c.card["helper_try_authority"]["easy_calibrator"],
                         {"per_try_usd": 12.5, "hosted_tries": [1], "reserved_usd": 12.5})

    def job_and_context(self, name="refuse"):
        c = self.context(name)
        identity = {"x": 1}
        self.stack.enter_context(patch.object(run, "calibration_identity", lambda *a, **k: dict(identity, slot=0)))
        job = helpers.make_try_job(case=run.case_hash(c), role="easy_calibrator", name="easy_calibrator", exposure="blind",
                                   number=1, seed=c.seed + 1, runs=2, minutes=30, model=["synthetic/easy"],
                                   identity=helpers.digest_of(identity), bench="m",
                                   release=__import__("durable.checkpoints", fromlist=["x"]).verdict_code(), workers=1)
        return c, job

    def test_helper_refuses_a_job_whose_conditions_differ_from_its_own(self):
        c, job = self.job_and_context()
        files = run.hosted_try(c, job)                    # matching conditions run
        self.assertEqual(helpers.unpack_try(files)["execution"]["summary"]["runs"], 2)
        for key, value in (("minutes", 5), ("model", ["other/model"]), ("bench", "stale"), ("release", "old"),
                           ("identity", "0" * 64), ("workers", 8), ("case", "x"), ("seed", 99)):
            self.local.clear()
            with self.assertRaises(helpers.HelperRefused, msg=key): run.hosted_try(c, {**job, key: value})
            self.assertEqual(self.local, [], key)         # refused before any model call

    def test_model_stop_on_a_helper_is_a_result_not_a_fault(self):
        c, job = self.job_and_context("stop")
        def stop(c_, role, name, exposure, i, make_ws): raise run.BudgetError("budget_exhausted:grant_insufficient")
        with patch.object(run, "_author_try", stop):
            out = helpers.unpack_try(run.hosted_try(c, job))
        self.assertEqual((out["stopped"], out["label"]), ("budget_exhausted:grant_insufficient",
                         calibration.interruption_label(run.BudgetError("budget_exhausted:grant_insufficient"))))
        pool = TryPool(mutate=lambda i: helpers.pack_stop("quota:x", "provider_quota") if i == 2 else fake_files(i))
        c = self.hosted("stopping", pool)
        with self.assertRaises(run.BudgetError) as raised: run.calibrate(c, "easy_calibrator")
        self.assertEqual(str(raised.exception), "quota:x")
        self.assertEqual(sorted(j["try"] for j in pool.jobs), [1, 2, 3])             # never requeued and paid again
        self.assertEqual(c.card["calibration_interruptions"], {"easy_calibrator": {"provider_quota": 1}})
        self.assertEqual(self.local, [])

    def test_capped_hosted_try_allows_continuation_like_the_serial_cap_handler(self):
        pool = TryPool(mutate=lambda i: {**fake_files(i), "result.json": json.dumps(
            {"capped": "timeout", "execution": fake_execution(i)})})
        c = self.hosted("capped", pool)
        run.calibrate(c, "easy_calibrator")
        self.assertTrue(c.force_budget_resume)

    def test_finished_tries_survive_a_stop_and_are_not_run_again(self):
        stops = []
        def boundary(c_):
            if stops: raise run.BudgetError("budget_exhausted:grant_insufficient")
        pool = TryPool()
        c = self.hosted("salvage", pool, workers=1)
        with patch.object(run, "case_budget_boundary", boundary):
            def after(*a):
                stops.append(1)
            orig = pool.run
            pool.run = lambda h, j, k: (lambda r: (after(), r)[1])(orig(h, j, k))
            with self.assertRaises(run.BudgetError): run.calibrate(c, "easy_calibrator")
        self.assertEqual([j["try"] for j in pool.jobs], [1])                          # try 1 finished, then the stop
        self.assertEqual(len(list((c.work / "helper-tries").glob("*.json"))), 1)
        pool2 = TryPool()
        c.helper_pool = pool2
        run.calibrate(c, "easy_calibrator")
        self.assertEqual(sorted(j["try"] for j in pool2.jobs), [2, 3])               # try 1 comes from the saved result
        self.assertEqual([r["try"] for r in self.rows(c)], [1, 2, 3])

    def test_pack_try_tolerates_symlinks_the_serial_path_ignores(self):
        outside = self.tmp / "outside"; outside.mkdir(); (outside / "secret.sql").write_text("s")
        guard = self.tmp / "g2"; guard.mkdir()
        (guard / "db.sql").write_text("real")
        (guard / "link.sql").symlink_to(outside / "secret.sql")
        (guard / "dirlink").symlink_to(outside, target_is_directory=True)
        out = helpers.unpack_try(helpers.pack_try(guard, None, fake_execution(1)))
        self.assertEqual(out["guard"], {"db.sql": b"real"})

    def test_author_try_serial_unit(self):
        c = self.context("author")
        import bench
        user_home = self.tmp / "home"; user_home.mkdir()
        calls = []
        def model(ctx, models, text, dest, call_name, **kw):
            calls.append(call_name)
            (dest / "guard").mkdir(parents=True, exist_ok=True); (dest / "guard/db.sql").write_text("g")
            if kw.get("timeout") != 30 * 60: raise AssertionError("time limit")
            raise c.error
        for owner, n, v in [(run, "sh", lambda *a, **k: None), (run, "pilot_home", lambda u: user_home),
                            (run, "shred_tree", lambda *a, **k: None), (run, "model_call", model),
                            (bench, "reset", lambda *a, **k: None), (bench, "load_scenario", lambda x: x)]:
            self.stack.enter_context(patch.object(owner, n, v))
        ws = self.tmp / "authored-ws"
        c.error = run.BudgetError("timeout")
        out_ws, capped = REAL_AUTHOR(c, "easy_calibrator", "easy_calibrator", "blind", 1, lambda: ws)
        self.assertEqual((out_ws, capped, calls, c.force_budget_resume), (ws, "timeout", ["easy-calibrator-easy_calibrator-1"], True))
        c.error = run.BudgetError("quota:x")
        with self.assertRaises(run.BudgetError): REAL_AUTHOR(c, "easy_calibrator", "easy_calibrator", "blind", 1, lambda: self.tmp / "ws2")
        label = calibration.interruption_label(c.error)
        self.assertEqual(c.card["calibration_interruptions"], {"easy_calibrator": {label: 1}})

    def test_g10_and_g5_bind_helper_code(self):
        import gate_state
        self.assertIn("factory/durable/helpers.py", gate_state.DEPENDENCIES["G5"])
        self.assertIn("factory/durable/helpers.py", gate_state.STAGE_DEPENDENCIES["G10"])


def fake_files_exec(i):
    ex = fake_execution(i)
    return ex["summary"], ex["records"]


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
