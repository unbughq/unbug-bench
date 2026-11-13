"""A money wait recorded by main's wait_for_bound (recv, recv, ...) recovers under the new engine.

Real DBOS 3.4.0 on SQLite: the first process runs main's loop body through several poll timeouts
and dies; the second recovers the same workflow with engine._Case.wait_for_bound, which must replay
the recorded operations in order and then finish on a wake. Before the fix every poll read the clock
(now_step) and recovery raised DBOSUnexpectedStepError.
Needs dbos (the suite runs with `--with dbos==3.4.0`, tests/README.md).
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[2]

PROGRAM = textwrap.dedent('''
    import json, os, pathlib, sys, threading, time, types
    sys.path.insert(0, sys.argv[1])
    work, mode = pathlib.Path(sys.argv[2]), sys.argv[3]
    from dbos import DBOS, SetWorkflowID
    import durable.engine as eng
    from durable.engine import _Case, _RT, WAKE, now_step
    DBOS(config={"name": "bound-wait-replay", "system_database_url": f"sqlite:///{work}/sys.sqlite",
                 "application_version": "factory-engine-1"})
    eng._RT.timing = eng.Timing(wake_poll_s=0.2)
    WID = "case-t-1/money-wait"
    eng._RT.executor = types.SimpleNamespace(release=lambda lease: None)

    def main_wait_for_bound(self, deadline=None):
        # origin/main factory/durable/engine.py, _Case.wait_for_bound, verbatim
        self.release_worker()
        self.status = "waiting_for_bound"
        self.card()
        self.tell("waiting")
        blocks = DBOS.patch("bound_wait_blocks")
        while DBOS.recv(WAKE, timeout_seconds=_RT.timing.wake_poll_s) is None and blocks:
            if deadline is not None and now_step() >= deadline:
                return False
        self.status = "running"
        return True

    def case_object():
        # The case tells its own workflow ("waiting" goes to the batch in the engine).
        me = types.SimpleNamespace(case_id="case-t-1", batch_id=WID, workflow_id=WID, worker_id="w-1",
                                   seq=3, resume_seq=0, status="running")
        for name in ("release_worker", "tell", "replaying"):
            attr = getattr(_Case, name)
            setattr(me, name, attr.fget(me) if isinstance(attr, property) else types.MethodType(attr, me))
        me.card = lambda: DBOS.set_event("card", me.status)
        return me

    @DBOS.workflow()
    def money_wait(deadline):
        me = case_object()
        wait = main_wait_for_bound if mode == "old" else _Case.wait_for_bound
        return {"woke": wait(me, deadline), "worker": me.worker_id}

    DBOS.launch()
    wid = WID
    if mode == "old":
        with SetWorkflowID(wid):
            DBOS.start_workflow(money_wait, None)
        time.sleep(1.5)   # several 0.2 s poll timeouts are recorded, then the process dies
        os._exit(0)
    time.sleep(1.0)       # recovery replays the recorded polls, then waits live
    DBOS.send(wid, "bound_raised", topic=WAKE)
    try:
        out = {"result": DBOS.retrieve_workflow(wid).get_result()}
    except Exception as error:
        out = {"error": f"{type(error).__name__}: {error}"}
    out["steps"] = [s["function_name"] for s in DBOS.list_workflow_steps(wid)]
    print(json.dumps(out), flush=True)
    os._exit(0)
''')


class MainMoneyWaitReplays(unittest.TestCase):
    def test_a_wait_recorded_on_main_recovers_and_finishes(self):
        with tempfile.TemporaryDirectory() as tmp:
            prog = Path(tmp) / "prog.py"
            prog.write_text(PROGRAM)
            def go(mode):
                p = subprocess.run([sys.executable, "-B", str(prog), str(ROOT / "factory"), tmp, mode],
                                   capture_output=True, text=True, timeout=120, env={**os.environ, "BENCH": str(ROOT)})
                self.assertEqual(p.returncode, 0, p.stderr[-3000:])
                return p
            go("old")
            out = json.loads(go("new").stdout.strip().splitlines()[-1])
        self.assertNotIn("error", out, out.get("error"))
        self.assertEqual(out["result"], {"woke": True, "worker": None})
        recorded = out["steps"]
        self.assertGreaterEqual(recorded.count("DBOS.recv"), 3, recorded)   # two or more timeouts, then the wake
        self.assertNotIn("now_step", recorded)


if __name__ == "__main__":
    unittest.main()
