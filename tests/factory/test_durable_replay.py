"""The property the durable design rests on, proven against the real engine (DBOS on SQLite).

A process killed with os._exit in the middle of a step is restarted. Completed steps must
return their recorded results without running again; only the open step reruns. Starting
the same case workflow ID twice must attach, not duplicate. A provider-limit sleep must
survive a crash and not restart its wait from zero.

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
    import json, os, pathlib, sys, time
    sys.path.insert(0, sys.argv[1])
    from dbos import DBOS, SetWorkflowID
    from durable.contract import (ArtifactKind, Outcome, Ref, Step, StepInput, StepKind, StepResult,
                                  step_result_from_record, to_record)
    work = pathlib.Path(sys.argv[2]); mode = sys.argv[3]
    DBOS(config={"name": "durable-replay", "system_database_url": f"sqlite:///{work}/sys.sqlite",
                 "application_version": "test-v1"})
    def log(event):
        with open(work / "events.log", "a") as f: f.write(event + "\\n")
    SNAP = "a" * 64
    @DBOS.step()
    def attempt(record):
        si = StepInput(**{**record, "step": Step(**record["step"]),
                          "snapshot": Ref(**record["snapshot"]) if record["snapshot"] else None})
        log("run " + si.step.name)
        if si.step.name == "gate:G2" and mode == "crash-in-step":
            log("crash"); os._exit(9)
        if si.step.name == "gate:G3" and not (work / "limit-done").exists():
            (work / "limit-done").touch()
            return to_record(StepResult(Outcome.PROVIDER_LIMIT, "claude:limit", retry_at=time.time() + 6))
        return to_record(StepResult(Outcome.OK, "pass", snapshot=Ref(SNAP, ArtifactKind.CASE_SNAPSHOT)))
    @DBOS.workflow()
    def case(case_id):
        steps = [Step(StepKind.ADMIT), Step(StepKind.WRITER, round=1),
                 Step(StepKind.GATE, "G1"), Step(StepKind.GATE, "G2"), Step(StepKind.GATE, "G3")]
        snap, done = None, []
        for s in steps:
            n = 1
            while True:
                si = StepInput("b-test", case_id, s, n, "c" * 64, snap)
                r = step_result_from_record(attempt(to_record(si)))
                if r.outcome is Outcome.PROVIDER_LIMIT:
                    if mode == "crash-in-sleep":
                        import threading
                        log("sleeping")
                        threading.Timer(0.5, lambda: (log("crash"), os._exit(9))).start()
                    DBOS.sleep(max(0.0, r.retry_at - time.time()))
                    n += 1; continue
                break
            snap = r.snapshot; done.append(s.name)
        return done
    DBOS.launch()  # recovers this executor's pending workflows in the background
    # Attach to a known case; start it only if it has never existed. Starting a pending ID
    # again would race the recovery thread with a second local execution of the same case.
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

    def run_prog(self, mode):
        return subprocess.run([sys.executable, "-B", str(self.prog), str(ROOT / "factory"), str(self.work), mode],
                              capture_output=True, text=True, timeout=120)

    def events(self):
        return (self.work / "events.log").read_text().split("\n")[:-1]

    def test_crash_mid_step_reruns_only_open_step(self):
        first = self.run_prog("crash-in-step")
        self.assertEqual(first.returncode, 9, first.stderr[-2000:])
        second = self.run_prog("normal")
        self.assertEqual(second.returncode, 0, second.stderr[-2000:])
        self.assertEqual(json.loads(second.stdout.strip().splitlines()[-1]),
                         ["admit", "writer:1", "gate:G1", "gate:G2", "gate:G3"])
        self.assertEqual(self.events(), [
            "run admit", "run writer:1", "run gate:G1", "run gate:G2", "crash",   # first process
            "run gate:G2", "run gate:G3", "run gate:G3"])                         # only the open step reran
        # Same workflow ID again attaches to the finished case; nothing runs.
        third = self.run_prog("normal")
        self.assertEqual(third.returncode, 0, third.stderr[-2000:])
        self.assertEqual(len(self.events()), 8)

    def test_crash_during_provider_sleep_keeps_the_deadline(self):
        first = self.run_prog("crash-in-sleep")
        self.assertEqual(first.returncode, 9, first.stderr[-2000:])
        self.assertEqual(self.events()[-2:], ["sleeping", "crash"])
        time.sleep(4)  # the 6 s limit wait keeps running while nothing is alive
        started = time.monotonic()
        second = self.run_prog("normal")
        elapsed = time.monotonic() - started
        self.assertEqual(second.returncode, 0, second.stderr[-2000:])
        # Only gate:G3 runs again after the wake-up; earlier steps replay from the journal.
        after_crash = self.events()[self.events().index("crash") + 1:]
        self.assertEqual(after_crash, ["run gate:G3"])
        # About 1.5 s of the wait remained. Restarting the wait from zero would take at least 6 s.
        self.assertLess(elapsed, 5.5)


if __name__ == "__main__":
    unittest.main()
