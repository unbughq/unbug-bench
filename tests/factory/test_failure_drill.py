"""Failure drill: a throwaway batch must finish through every failure of 6 November with zero
human actions. Real DBOS, the real guard and fake Boat, router and workers; no money.

Set DRILL_REQUIRE_POSTGRES=1 to fail, not skip, without a local PostgreSQL (bin/failure-drill does).
"""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "factory"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from durable.guard import Guard
from test_durable_engine_fakes import EngineRun, _Files
from test_durable_guard import REQUEST, USAGE, inventory

C1 = "case-t-1"  # the fakes' case id
ADMIT = C1 + "/1/admit/1"
WRITER = C1 + "/2/writer:1/1"
DUR = 3.0


def scenario(**kw):
    return {"spec": {"max_cases_started": 1}, "drain_s": 5, "default_dur": 0.05, "poll_s": 0.05,
            "script": {"1/writer:1/1": {"dur": DUR}},
            "timing": {"degraded_poll_s": 0.1}, **kw}


class Drill(unittest.TestCase):
    def start(self, config):
        run = EngineRun(config)
        self.addCleanup(run.close)
        process = run.spawn()
        self.addCleanup(lambda: process.poll() is None and process.kill())
        return run, process

    def wait_for(self, run, key, process):
        until = time.monotonic() + 60
        while not [s for s in run.starts() if s["key"] == key]:
            self.assertIsNone(process.poll(), run.tail())
            self.assertLess(time.monotonic(), until, "attempt never started:\n" + run.tail())
            time.sleep(0.02)

    def finish(self, run, process=None, timeout=120):
        """To the end with no human action. A running process finishes by itself; otherwise
        restart it, as systemd would."""
        if process is None:
            out = run.run(timeout=timeout)
        else:
            process.wait(timeout=timeout)
            self.assertEqual(process.returncode, 0, run.tail())
            out = run.result()
        self.assertEqual(out["result"]["cases"], {C1: "sealed"}, run.tail())
        self.assertEqual([c["status"] for c in out["scorecard"]["cases"]], ["sealed"])
        settled = [x for x in run.ledger_log() if x["op"] in ("settle", "settle_lost")]
        keys = [x["key"] for x in settled]
        self.assertEqual(len(keys), len(set(keys)), "an attempt settled twice")
        reserved = {x["key"] for x in run.ledger_log() if x["op"] == "reserve"}
        self.assertEqual(reserved, set(keys), "an attempt kept its hold")
        self.assertEqual(out["ledger"]["batches"]["b-t"]["held"], 0)
        return out

    def guard(self, run, boat, *, calls):
        service = type("Service", (), {"state": lambda s: ("active", time.time() - 3600, time.time() - 3600),
                                       "stop": lambda s: calls.append("stop")})()
        rpc = lambda op: {"status": {"cases": [{"case": C1, "status": "running"}]},
                          "budget": {"spent": 0, "bound": 1}}[op]
        return Guard({**REQUEST, "deadline_epoch": time.time() + 3600}, run.work / "state/guard", boat=boat, rpc=rpc,
                     service=service, ours=lambda row: True, count=lambda: 1, delete=lambda worker: None,
                     sleep=lambda s: None)

    def test_a_hanging_usage_call_pauses_only_new_attempts(self):
        run, process = self.start(scenario())
        self.wait_for(run, WRITER, process)
        calls = []
        def boat(args, timeout):
            calls.append(args[0])
            if args[0] == "usage":
                return {"code": 124, "out": b"", "stderr": b"boat-call: command timed out", "seconds": timeout}
            return {"code": 0, "out": inventory("bx_aaaaaaaa") if args[0] == "list" else b"{}", "stderr": b"", "seconds": 0}
        out = self.guard(run, boat, calls=calls).run()
        self.assertEqual((out["phase"], out["failed_checks"]), ("degraded", ["boat_usage"]))
        self.assertNotIn("stop", calls)
        self.assertIn("extend", calls)
        # The running attempt finishes; the next one waits for a clean pass.
        until = time.monotonic() + 30
        while not [x for x in run.worker_log() if x["op"] == "ran" and x["key"] == WRITER]:
            self.assertLess(time.monotonic(), until, run.tail())
            time.sleep(0.05)
        time.sleep(1)
        self.assertFalse([s for s in run.starts() if "/stress:" in s["key"]], "a new attempt ran while degraded")
        self.assertIsNone(process.poll())
        def healthy(args, timeout):
            return {"code": 0, "out": {"list": inventory("bx_aaaaaaaa"), "usage": USAGE}.get(args[0], b"{}"),
                    "stderr": b"", "seconds": 0}
        self.assertEqual(self.guard(run, healthy, calls=calls).run()["phase"], "healthy")
        self.finish(run, process)
        self.assertNotIn("stop", calls)

    def test_a_check_that_fails_briefly_changes_nothing(self):
        run, process = self.start(scenario())
        self.wait_for(run, WRITER, process)
        calls, left = [], [2]
        def boat(args, timeout):
            if args[0] == "list" and left[0]:
                left[0] -= 1
                return {"code": 1, "out": b"", "stderr": b"temporary", "seconds": 0.1}
            return {"code": 0, "out": {"list": inventory("bx_aaaaaaaa"), "usage": USAGE}.get(args[0], b"{}"),
                    "stderr": b"", "seconds": 0}
        self.assertEqual(self.guard(run, boat, calls=calls).run()["phase"], "healthy")
        self.assertFalse((run.work / "state/guard/degraded.json").exists())
        self.finish(run, process)
        self.assertEqual(calls, [])

    def test_sigterm_mid_attempt_exits_cleanly_and_reattaches(self):
        run, process = self.start(scenario())
        self.wait_for(run, WRITER, process)
        started = time.monotonic()
        process.send_signal(signal.SIGTERM)
        self.assertEqual(process.wait(timeout=30), 0, run.tail())
        self.assertLess(time.monotonic() - started, 2.5)   # parked at once, not waiting for the 3s attempt
        for text in ("Traceback", "No DBOS was created", "System database accessed"):
            self.assertNotIn(text, run.tail(100000))
        self.finish(run)
        self.assertEqual(len([s for s in run.starts() if s["key"] == WRITER]), 1, "the attempt ran twice")
        settle = [x for x in run.ledger_log() if x.get("key") == WRITER]
        self.assertEqual([x["op"] for x in settle], ["reserve", "settle"])   # its usage survives

    def test_sigterm_waits_for_a_step_that_is_recording(self):
        """The drain counts attempts for real: a step past its last park must finish recording."""
        run, process = self.start(scenario(script={"1/writer:1/1": {"dur": 0.6}}, poll_s=0.5))
        self.wait_for(run, WRITER, process)
        time.sleep(0.3)
        self.assertEqual(_Files(run.work / "state/worker").read("in-flight.json", 0), 1)
        process.send_signal(signal.SIGTERM)
        self.assertEqual(process.wait(timeout=30), 0, run.tail())
        self.finish(run)

    def test_sigkill_mid_attempt_reattaches(self):
        run, process = self.start(scenario())
        self.wait_for(run, WRITER, process)
        process.kill()
        process.wait()
        self.finish(run)
        self.assertEqual(len([s for s in run.starts() if s["key"] == WRITER]), 1)
        self.assertEqual([x["op"] for x in run.ledger_log() if x.get("key") == WRITER], ["reserve", "settle"])

    def test_a_worker_deleted_while_the_controller_is_down_is_an_ordinary_retry(self):
        """The 6 November state: attempt pending, controller gone, worker deleted."""
        run, process = self.start(scenario())
        self.wait_for(run, WRITER, process)
        process.kill()
        process.wait()
        pool = _Files(run.work / "state/pool")
        workers = pool.read("pool.json", {})
        workers[C1]["dead"] = True
        pool.write("pool.json", workers)
        self.finish(run)
        self.assertEqual([x["op"] for x in run.ledger_log() if x.get("key") == WRITER], ["reserve", "settle_lost"])
        retry = [s for s in run.starts() if s["key"] == C1 + "/2/writer:1/2"]
        self.assertEqual(retry[0]["worker"], "w-1-2")

    def test_a_worker_deleted_mid_attempt_is_an_ordinary_retry(self):
        run, process = self.start(scenario())
        self.wait_for(run, WRITER, process)
        pool = _Files(run.work / "state/pool")
        with pool.locked():
            workers = pool.read("pool.json", {})
            workers[C1]["dead"] = True
            pool.write("pool.json", workers)
        self.finish(run, process)
        self.assertEqual([x["op"] for x in run.ledger_log() if x.get("key") == WRITER], ["reserve", "settle_lost"])

    def hard_stop(self, run, process, *, grace_s):
        """A money breach against the running controller, with Boat faked over the worker pool."""
        time.sleep(0.3)   # the fake reports its in-flight count every 50ms
        pool, stopped = _Files(run.work / "state/pool"), []
        def live():
            workers = pool.read("pool.json", {})
            return [] if workers[C1]["dead"] else ["bx_aaaaaaaa"]
        def delete(worker):
            with pool.locked():
                workers = pool.read("pool.json", {})
                workers[C1]["dead"] = True
                pool.write("pool.json", workers)
            _Files(run.work / "state/worker").write(f"attempts-{C1}.json", {})   # its work dies with it
        def boat(args, timeout):
            return {"code": 0, "out": {"list": inventory(*live()), "usage": USAGE}.get(args[0], b"{}"),
                    "stderr": b"", "seconds": 0}
        def rpc(op):
            if op == "in_flight":
                return _Files(run.work / "state/worker").read("in-flight.json", 0)
            return {"status": {"cases": [{"case": C1, "status": "running"}]}, "budget": {"spent": 2, "bound": 1}}[op]
        def stop():
            process.send_signal(signal.SIGTERM)
            self.assertEqual(process.wait(timeout=30), 0, run.tail())
            stopped.append(1)
        service = type("Service", (), {"state": lambda s: ("inactive" if stopped else "active", time.time() - 3600, None),
                                       "stop": lambda s: stop()})()
        return Guard({**REQUEST, "deadline_epoch": time.time() + 3600}, run.work / "state/guard", boat=boat, rpc=rpc,
                     service=service, ours=lambda row: True, count=lambda: 1, delete=delete,
                     checkpoint_grace_s=grace_s, sleep=lambda s: None), stopped, live

    def resume(self, run):
        """What an operator does after fixing the cause. Then the batch must run by itself."""
        (run.work / "state/guard/status.json").unlink()
        (run.work / "state/guard/degraded.json").unlink(missing_ok=True)
        return self.finish(run)

    def test_hard_stop_past_the_grace_deletes_the_worker_and_retries_cleanly(self):
        run, process = self.start(scenario(script={"1/writer:1/1": {"dur": 30.0}}))
        self.wait_for(run, WRITER, process)
        guard, stopped, live = self.hard_stop(run, process, grace_s=1.0)
        begun = time.monotonic()
        self.assertEqual(guard.run()["phase"], "stopping")
        self.assertEqual((stopped, live()), ([], ["bx_aaaaaaaa"]))
        time.sleep(1.1)
        self.assertEqual(guard.run()["phase"], "stopped")
        self.assertEqual(live(), [])
        self.assertLess(time.monotonic() - begun, 8)
        self.assertFalse([x for x in run.ledger_log() if x["op"].startswith("settle") and x.get("key") == WRITER])
        self.resume(run)
        self.assertEqual([x["op"] for x in run.ledger_log() if x.get("key") == WRITER], ["reserve", "settle_lost"])
        self.assertEqual([s["worker"] for s in run.starts() if s["key"] == C1 + "/2/writer:1/2"], ["w-1-2"])

    def test_hard_stop_deletes_at_once_when_the_step_records_inside_the_grace(self):
        run, process = self.start(scenario(script={"1/writer:1/1": {"dur": 2.0}}))
        self.wait_for(run, WRITER, process)
        guard, stopped, live = self.hard_stop(run, process, grace_s=600.0)
        begun = time.monotonic()
        self.assertEqual(guard.run()["phase"], "stopping")
        until = time.monotonic() + 30
        while guard.run()["phase"] == "stopping":
            self.assertLess(time.monotonic(), until, run.tail())
            time.sleep(0.2)
        self.assertLess(time.monotonic() - begun, 30)   # far inside the 10 minutes
        self.assertEqual(live(), [])
        self.assertEqual([x["op"] for x in run.ledger_log() if x.get("key") == WRITER], ["reserve", "settle"])
        self.assertFalse([s for s in run.starts() if "/stress:" in s["key"]], "a new attempt ran during the stop")
        self.resume(run)
        self.assertEqual(len([s for s in run.starts() if s["key"] == WRITER]), 1)

    def test_admission_timeouts_recover_alone(self):
        """The 7 November park: infra retries used up, and no release should be needed."""
        run, process = self.start(scenario(
            spec={"max_cases_started": 1, "max_infra_retries_per_step": 0}, timing={"admission_backoff_s": 0.1},
            script={f"1/admit/{n}": {"outcome": "infra_error", "reason": "infra:timeout", "checkpoint": True}
                    for n in (1, 2, 3)}))
        self.finish(run, process)
        self.assertEqual(len([s for s in run.starts() if "/admit/" in s["key"]]), 4)

    def test_postgres_restart_mid_attempt(self):
        binaries = [shutil.which(n) for n in ("initdb", "pg_ctl")]
        if not all(binaries):
            if os.environ.get("DRILL_REQUIRE_POSTGRES"):
                self.fail("PostgreSQL not installed")
            self.skipTest("PostgreSQL not installed")
        initdb, pg_ctl = binaries
        with tempfile.TemporaryDirectory(dir="/tmp", prefix="drill-pg-") as directory:
            data, port = Path(directory) / "data", 54000 + os.getpid() % 1000
            subprocess.run([initdb, "-D", str(data), "-U", "drill", "--auth=trust"], check=True, capture_output=True)
            options = f"-p {port} -k {directory} -c listen_addresses=127.0.0.1"
            def pg(*args):
                subprocess.run([pg_ctl, "-D", str(data), "-o", options, "-l", str(data / "log"), "-w", *args],
                               check=True, capture_output=True, timeout=60)
            pg("start")
            self.addCleanup(lambda: subprocess.run([pg_ctl, "-D", str(data), "-m", "immediate", "stop"],
                                                   capture_output=True))
            run, process = self.start(scenario(database_url=f"postgresql://drill@127.0.0.1:{port}/postgres",
                                               script={"1/writer:1/1": {"dur": 8.0}}))
            self.wait_for(run, WRITER, process)
            pg("-m", "immediate", "restart")
            self.finish(run, process, timeout=180)
            self.assertEqual(len([s for s in run.starts() if s["key"] == WRITER]), 1)


if __name__ == "__main__":
    unittest.main()
