"""Pending replacement facts do not depend on message order or duplicate delivery."""
import itertools
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "factory"), str(Path(__file__).resolve().parent)]
os.environ.setdefault("BENCH", str(ROOT))

from durable.engine import _BatchV2, _message_key
from test_durable_engine_fakes import make_spec


class ReplacementFacts(unittest.TestCase):
    def test_message_identity_separates_each_phase_and_destination(self):
        parts = ("b-t", "case-t-1/1/admit/1", "case", "prepare", "request", "case-t-1")
        original = _message_key(*parts)
        self.assertEqual(original, _message_key(*parts))
        for index in range(len(parts)):
            changed = list(parts)
            changed[index] += "-other"
            self.assertNotEqual(original, _message_key(*changed))

    def batch(self):
        batch = _BatchV2(make_spec(target_sealed=2), {"digest": "a" * 64, "kind": "registry"})
        batch.cases = ["case-t-1"]
        batch.admitted.add("case-t-1")
        batch.admission_open = lambda: True
        started = []

        def start(replacement_of):
            started.append(replacement_of)
            batch.cases.append(f"case-t-{len(batch.cases) + 1}")

        batch.start_case = start
        return batch, started

    def test_request_release_and_done_join_in_every_order_and_ignore_duplicates(self):
        request = {"kind": "line_stopped", "case": "case-t-1", "action": "diagnose"}
        release = {"kind": "worker_released", "case": "case-t-1"}
        done = {"kind": "done", "case": "case-t-1", "status": "retired",
                "replacement_action": "diagnose", "worker_released": True}
        for order in itertools.permutations((request, release, done)):
            with self.subTest(order=[event["kind"] for event in order]):
                batch, started = self.batch()
                for event in (*order, *order):
                    batch.handle(event)
                self.assertEqual(started, ["case-t-1"])
                self.assertEqual(batch.done, {"case-t-1": "retired"})
                self.assertIn("case-t-1", batch.released)

    def test_unknown_or_unadmitted_cases_cannot_request_replacements(self):
        batch, started = self.batch()
        batch.cases.append("case-t-2")
        for case in ("case-t-2", "case-t-99"):
            batch.handle({"kind": "line_stopped", "case": case, "action": "diagnose"})
        self.assertEqual(started, [])

    def test_done_does_not_finish_the_batch_until_the_admitted_worker_is_released(self):
        batch, _ = self.batch()
        batch.handle({"kind": "done", "case": "case-t-1", "status": "retired"})
        self.assertTrue(batch.has_pending_work())
        batch.handle({"kind": "worker_released", "case": "case-t-1"})
        self.assertFalse(batch.has_pending_work())


class PendingWorkflow(unittest.TestCase):
    def test_disabled_v2_waits_without_reserving_or_starting_a_worker(self):
        program = textwrap.dedent('''
            import logging, os, sys
            from pathlib import Path
            logging.disable(logging.CRITICAL)
            for key in ("DBOS_CONDUCTOR_KEY", "DBOS_CONDUCTOR_URL"):
                os.environ.pop(key, None)
            root, work = Path(sys.argv[1]), Path(sys.argv[2])
            sys.path[:0] = [str(root / "factory"), str(root / "tests/factory")]
            from dbos import DBOS, SetWorkflowID
            from durable.contract import ArtifactKind, Ref, to_record
            from durable.engine import (_RT, PENDING_ADMISSION, Timing, _message_key, attempt_workflow, batch_workflow)
            from test_durable_engine_fakes import make_spec

            @DBOS.workflow()
            def read_phases():
                return [DBOS.recv("phase", timeout_seconds=10), DBOS.recv("phase", timeout_seconds=10),
                        DBOS.recv("phase", timeout_seconds=0.2)]

            class LedgerOnly:
                def __init__(self): self.opened = []
                def open_batch(self, batch_id, bound): self.opened.append((batch_id, bound))
                def __getattr__(self, name): raise AssertionError("unexpected executor call: " + name)

            ex = LedgerOnly()
            _RT.executor = ex
            _RT.timing = Timing(batch_poll_s=0.1, queue_poll_s=0.05, listener_poll_s=0.05)
            DBOS(config={"name": "unbug-factory-engine", "application_version": "factory-engine-2",
                         "system_database_url": f"sqlite:///{work}/sys.sqlite",
                         "notification_listener_polling_interval_sec": 0.05})
            DBOS.launch()
            try:
                spec = make_spec()
                registry = Ref("a" * 64, ArtifactKind.STATEMENT_REGISTRY)
                with SetWorkflowID(spec.batch_id):
                    batch = DBOS.start_workflow(batch_workflow, {"spec": to_record(spec),
                                              "initial_registry": to_record(registry), "queue_v2": True})
                card = DBOS.get_event("case-t-1", "card", timeout_seconds=15)
                assert card["status"] == "pending_admission", card
                assert not DBOS.list_workflows(name=attempt_workflow.__qualname__)
                DBOS.send("case-t-1", {"kind": "not_admitted"}, topic=PENDING_ADMISSION)
                result = batch.get_result()
                assert result["cases"] == {"case-t-1": "not_admitted"}, result
                assert len(ex.opened) == 1
                assert not DBOS.list_workflows(name=attempt_workflow.__qualname__)
                with SetWorkflowID("message-target"):
                    receiver = DBOS.start_workflow(read_phases)
                request = _message_key("b-t", "op", "case", "probe", "request", "message-target")
                ack = _message_key("b-t", "op", "case", "probe", "ack", "message-target")
                DBOS.send("message-target", "request", topic="phase", idempotency_key=request)
                DBOS.send("message-target", "duplicate", topic="phase", idempotency_key=request)
                DBOS.send("message-target", "ack", topic="phase", idempotency_key=ack)
                assert receiver.get_result() == ["request", "ack", None]
            finally:
                DBOS.destroy()
        ''')
        with tempfile.TemporaryDirectory() as work:
            completed = subprocess.run([sys.executable, "-B", "-c", program, str(ROOT), work],
                                       capture_output=True, text=True, timeout=45)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_switched_batch_replays_out_of_order_predecessor_facts_after_kill(self):
        program = textwrap.dedent('''
            import logging, os, sqlite3, sys, time
            from pathlib import Path
            logging.disable(logging.CRITICAL)
            for key in ("DBOS_CONDUCTOR_KEY", "DBOS_CONDUCTOR_URL"):
                os.environ.pop(key, None)
            root, work, mode = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
            sys.path[:0] = [str(root / "factory"), str(root / "tests/factory")]
            from dbos import DBOS, SendMessage, SetWorkflowID
            from durable.contract import ArtifactKind, Ref, to_record
            from durable import engine
            from test_durable_engine_fakes import make_spec

            class LedgerOnly:
                def open_batch(self, _batch_id, _bound): pass
                def __getattr__(self, name): raise AssertionError("unexpected executor call: " + name)

            # Controlled stand-in for the admission probe in this disabled increment.
            original_init, original_handle = engine._BatchV2.__init__, engine._BatchV2.handle
            def init(self, spec, registry):
                original_init(self, spec, registry)
                self.admitted.add("case-t-1")
                self.test_seen = []
            def handle(self, message):
                original_handle(self, message)
                self.test_seen.append(message.get("kind"))
                DBOS.set_event("test_facts", {"cases": list(self.cases), "done": dict(self.done),
                                               "released": sorted(self.released), "seen": list(self.test_seen)})
            engine._BatchV2.__init__, engine._BatchV2.handle = init, handle
            engine._RT.executor = LedgerOnly()
            engine._RT.timing = engine.Timing(batch_poll_s=0.1, listener_poll_s=0.05)
            DBOS(config={"name": "unbug-factory-engine", "application_version": "factory-engine-2",
                         "system_database_url": f"sqlite:///{work}/sys.sqlite",
                         "notification_listener_polling_interval_sec": 0.05})
            DBOS.launch()
            spec = make_spec(target_sealed=1, max_cases_started=2)
            registry = Ref("a" * 64, ArtifactKind.STATEMENT_REGISTRY)

            def await_facts(predicate):
                until = time.monotonic() + 15
                while time.monotonic() < until:
                    facts = DBOS.get_event(spec.batch_id, "test_facts", timeout_seconds=0.2)
                    if facts and predicate(facts): return facts
                    time.sleep(0.02)
                raise AssertionError("timed out waiting for recorded facts")

            if mode == "start":
                with SetWorkflowID(spec.batch_id):
                    DBOS.start_workflow(engine.batch_workflow, {"spec": to_record(spec),
                                        "initial_registry": to_record(registry), "queue_v2": True})
                assert DBOS.get_event("case-t-1", "card", timeout_seconds=15)["status"] == "pending_admission"
                DBOS.send(spec.batch_id, {"kind": "worker_released", "case": "case-t-1"},
                          topic=engine.CASE_EVENT, idempotency_key="release")
                facts = await_facts(lambda f: f["released"] == ["case-t-1"])
                assert facts["seen"] == ["worker_released"], facts
                os._exit(9)

            try:
                done = {"kind": "done", "case": "case-t-1", "status": "retired",
                        "replacement_action": "diagnose", "worker_released": True}
                request = {"kind": "line_stopped", "case": "case-t-1", "action": "diagnose"}
                if mode == "resume_equal":
                    # One DBOS transaction gives both facts the same timestamp.
                    DBOS.send_bulk([SendMessage(spec.batch_id, done, engine.CASE_EVENT, "done"),
                                    SendMessage(spec.batch_id, request, engine.CASE_EVENT, "request")])
                    with sqlite3.connect(work / "sys.sqlite") as conn:
                        timestamps = conn.execute("SELECT created_at_epoch_ms FROM notifications "
                                                  "WHERE message_uuid IN (?, ?)",
                                                  ("done::b-t", "request::b-t")).fetchall()
                    assert len(timestamps) == 2 and timestamps[0] == timestamps[1], timestamps
                else:
                    DBOS.send(spec.batch_id, done, topic=engine.CASE_EVENT, idempotency_key="done")
                    first = await_facts(lambda f: "done" in f["seen"])
                    assert "line_stopped" not in first["seen"], first
                    DBOS.send(spec.batch_id, request, topic=engine.CASE_EVENT, idempotency_key="request")
                # Distinct IDs force duplicate facts through the actor. Reusing each
                # original ID separately checks DBOS's same-key suppression.
                DBOS.send(spec.batch_id, done, topic=engine.CASE_EVENT, idempotency_key="done-again")
                DBOS.send(spec.batch_id, request, topic=engine.CASE_EVENT, idempotency_key="request-again")
                DBOS.send(spec.batch_id, done, topic=engine.CASE_EVENT, idempotency_key="done")
                DBOS.send(spec.batch_id, request, topic=engine.CASE_EVENT, idempotency_key="request")
                facts = await_facts(lambda f: len(f["cases"]) == 2 and f["done"].get("case-t-1") == "retired"
                                    and f["seen"].count("done") == 2 and f["seen"].count("line_stopped") == 2)
                assert facts["released"] == ["case-t-1"], facts
                assert facts["seen"].index("worker_released") < facts["seen"].index("line_stopped"), facts
                if mode == "resume_ordered":
                    assert facts["seen"].index("done") < facts["seen"].index("line_stopped"), facts
                with sqlite3.connect(work / "sys.sqlite") as conn:
                    rows = conn.execute("SELECT message_uuid FROM notifications WHERE message_uuid IN (?, ?, ?, ?)",
                                        ("done::b-t", "request::b-t", "done-again::b-t", "request-again::b-t")).fetchall()
                assert len(rows) == 4, rows
                assert DBOS.get_event("case-t-2", "card", timeout_seconds=15)["status"] == "pending_admission"
                DBOS.send("case-t-1", {"kind": "not_admitted"}, topic=engine.PENDING_ADMISSION)
                DBOS.send("case-t-2", {"kind": "not_admitted"}, topic=engine.PENDING_ADMISSION)
                result = DBOS.retrieve_workflow(spec.batch_id).get_result()
                assert result["cases"] == {"case-t-1": "retired", "case-t-2": "not_admitted"}, result
                assert not DBOS.list_workflows(name=engine.attempt_workflow.__qualname__)
            finally:
                DBOS.destroy()
        ''')
        for mode in ("resume_ordered", "resume_equal"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as work:
                start = subprocess.run([sys.executable, "-B", "-c", program, str(ROOT), work, "start"],
                                       capture_output=True, text=True, timeout=45)
                self.assertEqual(start.returncode, 9, start.stdout + start.stderr)
                resume = subprocess.run([sys.executable, "-B", "-c", program, str(ROOT), work, mode],
                                        capture_output=True, text=True, timeout=45)
                self.assertEqual(resume.returncode, 0, resume.stdout + resume.stderr)


if __name__ == "__main__":
    unittest.main()
