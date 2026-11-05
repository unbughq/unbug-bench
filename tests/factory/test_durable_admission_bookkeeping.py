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


if __name__ == "__main__":
    unittest.main()
