"""The engine properties the durable design rests on, proven against real DBOS on SQLite.

1. A process killed with os._exit in the middle of a step is restarted: completed steps
   return their recorded results without running again, and only the open step reruns.
   Attaching to the same case ID again runs nothing.
2. A crash during a provider-limit sleep keeps the original wake time.
3. A restart that reaches the sleep after its wake time has passed still replays. DBOS
   records nothing for sleep(<=0), so the wait must always be positive
   (contract.wait_seconds; design review 1, finding 1).
4. A restart under changed step code with the same pinned application_version resumes
   the case, and the open step runs the new code (design review 1, finding 2).

Needs dbos (the suite runs with `--with dbos==3.4.0`, docs/ENGINEERING.md).
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]

PROGRAM = textwrap.dedent('''
    import json, os, pathlib, sys, threading, time
    sys.path.insert(0, sys.argv[1])
    from dbos import DBOS, SetWorkflowID
    from durable.contract import (ArtifactKind, Outcome, Ref, Step, StepKind, StepResult, step_input_from_record,
                                  step_result_from_record, to_record, wait_seconds, StepInput)
    INPUTS = Ref("e" * 64, ArtifactKind.INPUTS)
    work = pathlib.Path(sys.argv[2]); mode = sys.argv[3]; code = os.environ.get("STEP_CODE", "old")
    DBOS(config={"name": "durable-replay", "system_database_url": f"sqlite:///{work}/sys.sqlite",
                 "application_version": "factory-engine-1"})   # pinned for the life of the database
    def log(event):
        with open(work / "events.log", "a") as f: f.write(event + "\\n")
    SNAP = Ref("a" * 64, ArtifactKind.CASE_SNAPSHOT)
    LIMIT_S = float(os.environ.get("LIMIT_S", "20"))
    @DBOS.step()
    def now():
        return time.time()
    @DBOS.step()
    def attempt(record):
        si = step_input_from_record(record)
        log(f"run {si.step.name} {code}")
        if si.step.name == "stress:1" and mode == "crash-in-step":
            log("crash"); os._exit(9)
        if si.step.name == "gates:1" and not (work / "limit-done").exists():
            (work / "limit-done").touch()
            return to_record(StepResult(Outcome.PROVIDER_LIMIT, "router:claude_limit", retry_at=time.time() + LIMIT_S))
        return to_record(StepResult(Outcome.OK, f"engine:pass_{code}", snapshot=SNAP))
    @DBOS.workflow()
    def case(case_id):
        steps = [Step(StepKind.WRITER, 1), Step(StepKind.WRITER, 2), Step(StepKind.STRESS, 1),
                 Step(StepKind.GATES, 1), Step(StepKind.SEAL)]
        done = []
        for seq, s in enumerate(steps, 1):
            n = 1
            while True:
                si = StepInput("b-test", case_id, seq, s, n, "c" * 64, "d" * 64, INPUTS, SNAP, 60.0, 0)
                r = step_result_from_record(attempt(to_record(si)))
                if r.outcome is Outcome.PROVIDER_LIMIT:
                    if mode == "crash-in-sleep":
                        log("sleeping")
                        threading.Timer(0.5, lambda: (log("crash"), os._exit(9))).start()
                    DBOS.sleep(wait_seconds(r.retry_at, now()))
                    n += 1; continue
                break
            done.append(f"{s.name}={r.reason}")
        return done
    DBOS.launch()  # recovers this executor's pending workflows in the background
    # Attach to a known case; start it only if it has never existed. Starting a pending ID
    # again races the recovery thread with a second local execution of the same case.
    if DBOS.get_workflow_status("case-replay1") is None:
        with SetWorkflowID("case-replay1"):
            handle = DBOS.start_workflow(case, "case-replay1")
    else:
        handle = DBOS.retrieve_workflow("case-replay1")
    print(json.dumps(handle.get_result()))
''')


class Replay(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.work = Path(self.tmp.name)
        self.prog = self.work / "prog.py"
        self.prog.write_text(PROGRAM)

    def tearDown(self):
        self.tmp.cleanup()

    def run_prog(self, mode, **env):
        return subprocess.run([sys.executable, "-B", str(self.prog), str(ROOT / "factory"), str(self.work), mode],
                              capture_output=True, text=True, timeout=180, env={**os.environ, **env})

    def ok(self, proc):
        self.assertEqual(proc.returncode, 0, proc.stderr[-3000:])
        return json.loads(proc.stdout.strip().splitlines()[-1])

    def events(self):
        return (self.work / "events.log").read_text().split("\n")[:-1]

    def after_crash(self):
        e = self.events()
        return e[e.index("crash") + 1:]

    def test_crash_mid_step_reruns_only_open_step(self):
        self.assertEqual(self.run_prog("crash-in-step", LIMIT_S="1").returncode, 9)
        self.assertEqual(self.ok(self.run_prog("normal", LIMIT_S="1")),
                         ["writer:1=engine:pass_old", "writer:2=engine:pass_old", "stress:1=engine:pass_old",
                          "gates:1=engine:pass_old", "seal=engine:pass_old"])
        self.assertEqual(self.events()[:5], ["run writer:1 old", "run writer:2 old", "run stress:1 old", "crash",
                                             "run stress:1 old"])   # only the open step reran
        before = len(self.events())
        self.ok(self.run_prog("normal"))                         # attach: nothing runs
        self.assertEqual(len(self.events()), before)

    def test_crash_during_provider_sleep_keeps_the_deadline(self):
        self.assertEqual(self.run_prog("crash-in-sleep").returncode, 9)
        self.assertEqual(self.events()[-2:], ["sleeping", "crash"])
        time.sleep(12)  # the 20 s limit keeps running while nothing is alive
        started = time.monotonic()
        self.ok(self.run_prog("normal"))
        elapsed = time.monotonic() - started
        self.assertEqual(self.after_crash(), ["run gates:1 old", "run seal old"])
        # About 7.5 s of the wait remained. Restarting the wait from zero would take at least 20 s,
        # so the margin covers interpreter and engine startup under suite load.
        self.assertLess(elapsed, 17)

    def test_restart_after_the_wake_time_has_passed(self):
        self.assertEqual(self.run_prog("crash-in-sleep", LIMIT_S="2").returncode, 9)
        time.sleep(4)  # the wake time is long gone when replay reaches the sleep
        self.ok(self.run_prog("normal"))
        self.assertEqual(self.after_crash(), ["run gates:1 old", "run seal old"])

    def test_changed_step_code_resumes_under_the_pinned_version(self):
        self.assertEqual(self.run_prog("crash-in-step", LIMIT_S="1").returncode, 9)
        result = self.ok(self.run_prog("normal", LIMIT_S="1", STEP_CODE="new"))
        # Recorded steps keep their old-code results; the open step and later ones run the new code.
        self.assertEqual(result, ["writer:1=engine:pass_old", "writer:2=engine:pass_old", "stress:1=engine:pass_new",
                                  "gates:1=engine:pass_new", "seal=engine:pass_new"])
        self.assertEqual(self.after_crash()[0], "run stress:1 new")


if __name__ == "__main__":
    unittest.main()
