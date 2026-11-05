"""Admission probes run on real DBOS with disposable SQLite and fake accounting."""
import os
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]


class AdmissionProbe(unittest.TestCase):
    def test_exhausted_bound_waits_until_raise_or_stop(self):
        program = textwrap.dedent('''
            import logging, os, sys, time
            from pathlib import Path
            logging.disable(logging.CRITICAL)
            for key in ("DBOS_CONDUCTOR_KEY", "DBOS_CONDUCTOR_URL"):
                os.environ.pop(key, None)
            root, work, mode = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
            sys.path[:0] = [str(root / "factory"), str(root / "tests/factory")]
            from dbos import DBOS, SetWorkflowID
            from durable.contract import ArtifactKind, BoundRaised, Ref, Topic, Usage, to_record
            from durable import engine
            from test_durable_engine_fakes import FakeLedger, make_spec

            if mode == "queued_stop":
                @DBOS.workflow()
                def block_decisions():
                    DBOS.set_event("ready", True)
                    DBOS.recv("release", timeout_seconds=15)
                original_handle = engine._BatchV2.handle
                def observed_handle(self, message):
                    original_handle(self, message)
                    if message.get("kind") == "stop_admission": DBOS.set_event("test_stopped", True)
                engine._BatchV2.handle = observed_handle

            class LedgerOnly:
                def __init__(self): self.ledger = FakeLedger(work / "ledger")
                def open_batch(self, batch_id, bound): self.ledger.open(batch_id, bound)
                def raise_bound(self, batch_id, bound): self.ledger.raise_bound(batch_id, bound)
                def reserve(self, si, *, request, case_limit, draws_case_money):
                    if mode == "expire": time.sleep(2.0)
                    return self.ledger.reserve(si.batch_id, si.case_id, si.idempotency_key, request,
                                               case_limit, draws_case_money=draws_case_money)
                def release_unstarted(self, si): self.ledger.settle(si.idempotency_key, Usage())
                def __getattr__(self, name): raise AssertionError("unexpected executor call: " + name)

            ex = LedgerOnly()
            engine._RT.executor = ex
            engine._RT.timing = engine.Timing(batch_poll_s=0.1, wake_poll_s=60,
                                              queue_poll_s=0.05, listener_poll_s=0.05)
            DBOS(config={"name": "unbug-factory-engine", "application_version": "factory-engine-2",
                         "system_database_url": f"sqlite:///{work}/sys.sqlite",
                         "notification_listener_polling_interval_sec": 0.05})
            DBOS.launch()
            opts = {"target_sealed": 1, "max_cases_started": 1,
                    "money_bound_usd_micros": 0 if mode in ("raise", "stop") else 100_000_000}
            if mode == "two":
                opts.update(target_sealed=2, max_cases_started=2, money_bound_usd_micros=50_000_000)
            if mode == "expire": opts["deadline_epoch"] = time.time() + 1.5
            if mode == "small": opts["case_money_usd_micros"] = 500_000
            if mode == "zero": opts["case_money_usd_micros"] = 0
            spec = make_spec(**opts)
            DBOS.register_queue(engine.decision_queue(spec.batch_id), global_concurrency=1,
                                polling_interval_sec=0.05, on_conflict="always_update")
            if mode == "queued_stop":
                with SetWorkflowID("decision-blocker"):
                    DBOS.retrieve_queue(engine.decision_queue(spec.batch_id)).enqueue(block_decisions)
                assert DBOS.get_event("decision-blocker", "ready", timeout_seconds=15) is True
            registry = Ref("a" * 64, ArtifactKind.STATEMENT_REGISTRY)
            with SetWorkflowID(spec.batch_id):
                DBOS.start_workflow(engine.batch_workflow, {"spec": to_record(spec),
                                    "initial_registry": to_record(registry), "queue_v2": True,
                                    "probe_enabled": True})

            def until(predicate):
                end = time.monotonic() + 15
                while time.monotonic() < end:
                    value = predicate()
                    if value: return value
                    time.sleep(0.03)
                raise AssertionError("timed out waiting for admission state")

            if mode == "queued_stop":
                until(lambda: DBOS.list_workflows(name=engine.admission_probe_workflow.__qualname__,
                                                  status="ENQUEUED"))
                DBOS.send(spec.batch_id, {"kind": "stop_admission"}, topic=engine.CASE_EVENT)
                assert DBOS.get_event(spec.batch_id, "test_stopped", timeout_seconds=15) is True
                DBOS.send("decision-blocker", {"kind": "release"}, topic="release")
                result = DBOS.retrieve_workflow(spec.batch_id).get_result()
                assert result["cases"] == {"case-t-1": "not_admitted"}, result
                assert not ex.ledger.snapshot()["res"]
                os._exit(0)
            if mode == "zero":
                result = DBOS.retrieve_workflow(spec.batch_id).get_result()
                assert result["cases"] == {"case-t-1": "not_admitted"}, result
                assert not ex.ledger.snapshot()["res"]
                os._exit(0)
            if mode == "small":
                grant = until(lambda: DBOS.get_event("case-t-1", "admission_grant", timeout_seconds=0.2))
                state = ex.ledger.snapshot()
                assert state["res"][grant["key"]]["amount"] == 500_000, state
                assert state["res"][grant["key"]]["settled"] is None
                assert not DBOS.list_workflows(name=engine.attempt_workflow.__qualname__)
                os._exit(0)
            if mode == "two":
                initial = until(lambda: (s if len((s := ex.ledger.snapshot())["res"]) == 2 and
                                         any(v["settled"] is not None for v in s["res"].values()) else None))
                assert initial["batches"][spec.batch_id]["held"] == 50_000_000, initial
                assert DBOS.get_event("case-t-1", "admission_grant", timeout_seconds=5)
                assert DBOS.get_event("case-t-2", "card", timeout_seconds=5)["status"] == "pending_admission"
                time.sleep(0.3)
                assert len(ex.ledger.snapshot()["res"]) == 2
                DBOS.send(spec.batch_id, to_record(BoundRaised(100_000_000)), topic=Topic.BOUND_RAISED.value)
                DBOS.send(spec.batch_id, {"kind": "nudge"}, topic=engine.CASE_EVENT)
                grant = until(lambda: DBOS.get_event("case-t-2", "admission_grant", timeout_seconds=0.2))
                state = ex.ledger.snapshot()
                assert len(state["res"]) == 3 and state["res"][grant["key"]]["settled"] is None, state
                assert state["batches"][spec.batch_id]["held"] == 100_000_000, state
                assert not DBOS.list_workflows(name=engine.attempt_workflow.__qualname__)
                os._exit(0)
            first = until(lambda: (s if (s := ex.ledger.snapshot())["res"] and
                                      all(v["settled"] is not None for v in s["res"].values()) else None))
            assert len(first["res"]) == 1, first
            if mode == "expire":
                result = DBOS.retrieve_workflow(spec.batch_id).get_result()
                assert result["cases"] == {"case-t-1": "not_admitted"}, result
                assert next(iter(first["res"].values()))["amount"] == spec.case_money_usd_micros
                assert first["batches"][spec.batch_id]["held"] == 0 and first["batches"][spec.batch_id]["spent"] == 0
                assert not DBOS.list_workflows(name=engine.attempt_workflow.__qualname__)
                os._exit(0)
            time.sleep(0.3)  # the probe's own zero settlement must not wake itself
            assert len(ex.ledger.snapshot()["res"]) == 1
            assert DBOS.get_event("case-t-1", "card", timeout_seconds=5)["status"] == "pending_admission"
            if mode == "stop":
                DBOS.send(spec.batch_id, {"kind": "stop_admission"}, topic=engine.CASE_EVENT)
                result = DBOS.retrieve_workflow(spec.batch_id).get_result()
                assert result["cases"] == {"case-t-1": "not_admitted"}, result
                assert len(ex.ledger.snapshot()["res"]) == 1
                os._exit(0)
            DBOS.send(spec.batch_id, to_record(BoundRaised(100_000_000)), topic=Topic.BOUND_RAISED.value)
            DBOS.send(spec.batch_id, {"kind": "nudge"}, topic=engine.CASE_EVENT)
            second = until(lambda: (s if len((s := ex.ledger.snapshot())["res"]) == 2 else None))
            grant = until(lambda: DBOS.get_event("case-t-1", "admission_grant", timeout_seconds=0.2))
            assert grant["key"] in second["res"] and second["res"][grant["key"]]["settled"] is None, second
            assert second["res"][grant["key"]]["amount"] == spec.case_money_usd_micros
            assert len(set(second["res"])) == 2
            assert DBOS.get_event("case-t-1", "card", timeout_seconds=5)["status"] == "waiting_for_worker"
            assert not DBOS.list_workflows(name=engine.attempt_workflow.__qualname__)
            os._exit(0)  # the disabled pending worker stage is intentionally not completed
        ''')
        for mode in ("raise", "stop", "small", "zero", "expire", "queued_stop", "two"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as work:
                completed = subprocess.run([sys.executable, "-B", "-c", program, str(ROOT), work, mode],
                                           capture_output=True, text=True, timeout=45)
                self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_reserve_committed_before_step_record_is_reused_on_restart(self):
        program = textwrap.dedent('''
            import logging, os, sys, time
            from pathlib import Path
            logging.disable(logging.CRITICAL)
            for key in ("DBOS_CONDUCTOR_KEY", "DBOS_CONDUCTOR_URL"):
                os.environ.pop(key, None)
            root, work, mode = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
            sys.path[:0] = [str(root / "factory"), str(root / "tests/factory")]
            from dbos import DBOS, SetWorkflowID
            from durable.contract import ArtifactKind, Ref, Usage, to_record
            from durable import engine
            from test_durable_engine_fakes import FakeLedger, make_spec

            if mode == "crash_grant":
                original_send = DBOS.send
                def crash_before_prepare(*args, **kwargs):
                    if len(args) >= 2 and isinstance(args[1], dict) and args[1].get("kind") == "prepare":
                        os._exit(9)
                    return original_send(*args, **kwargs)
                DBOS.send = staticmethod(crash_before_prepare)

            class LedgerOnly:
                def __init__(self): self.ledger = FakeLedger(work / "ledger")
                def open_batch(self, batch_id, bound): self.ledger.open(batch_id, bound)
                def reserve(self, si, *, request, case_limit, draws_case_money):
                    grant = self.ledger.reserve(si.batch_id, si.case_id, si.idempotency_key, request,
                                                case_limit, draws_case_money=draws_case_money)
                    if mode in ("crash", "crash_late"): os._exit(9)
                    return grant
                def release_unstarted(self, si): self.ledger.settle(si.idempotency_key, Usage())
                def __getattr__(self, name): raise AssertionError("unexpected executor call: " + name)

            ex = LedgerOnly()
            engine._RT.executor = ex
            engine._RT.timing = engine.Timing(batch_poll_s=0.1, wake_poll_s=60,
                                              queue_poll_s=0.05, listener_poll_s=0.05)
            DBOS(config={"name": "unbug-factory-engine", "application_version": "factory-engine-2",
                         "system_database_url": f"sqlite:///{work}/sys.sqlite",
                         "notification_listener_polling_interval_sec": 0.05})
            DBOS.launch()
            DBOS.register_queue(engine.decision_queue("b-t"), global_concurrency=1,
                                polling_interval_sec=0.05, on_conflict="always_update")
            if mode.startswith("crash"):
                options = {"target_sealed": 1, "max_cases_started": 1, "money_bound_usd_micros": 100_000_000}
                if mode in ("crash_late", "crash_grant"):
                    options["deadline_epoch"] = time.time() + 2.0
                    (work / "deadline.txt").write_text(str(options["deadline_epoch"]))
                spec = make_spec(**options)
                registry = Ref("a" * 64, ArtifactKind.STATEMENT_REGISTRY)
                with SetWorkflowID(spec.batch_id):
                    DBOS.start_workflow(engine.batch_workflow, {"spec": to_record(spec),
                                        "initial_registry": to_record(registry), "queue_v2": True,
                                        "probe_enabled": True})
                time.sleep(20)
                raise AssertionError("reserve did not reach its kill point")
            end = time.monotonic() + 15
            while time.monotonic() < end:
                if mode == "resume_late":
                    state = ex.ledger.snapshot()
                    card = DBOS.get_event("case-t-1", "card", timeout_seconds=0.2)
                    if card and card["status"] == "not_admitted":
                        assert len(state["res"]) == 1, state
                        row = next(iter(state["res"].values()))
                        assert row["settled"] is not None and row["settled"]["paid"] == 0, state
                        assert state["batches"]["b-t"]["held"] == 0, state
                        assert DBOS.get_event("case-t-1", "admission_grant", timeout_seconds=0.2) is None
                        os._exit(0)
                    time.sleep(0.03)
                    continue
                grant = DBOS.get_event("case-t-1", "admission_grant", timeout_seconds=0.2)
                if grant:
                    state = ex.ledger.snapshot()
                    assert list(state["res"]) == [grant["key"]], state
                    assert state["res"][grant["key"]]["amount"] == 50_000_000, state
                    assert state["res"][grant["key"]]["settled"] is None, state
                    assert len(DBOS.list_workflows(name=engine.admission_probe_workflow.__qualname__)) == 1
                    if mode == "resume_grant":
                        assert time.time() > float((work / "deadline.txt").read_text())
                    assert not DBOS.list_workflows(name=engine.attempt_workflow.__qualname__)
                    os._exit(0)
                time.sleep(0.03)
            raise AssertionError("recovered probe did not deliver its original grant")
        ''')
        for crash_mode, resume_mode in (("crash", "resume"), ("crash_late", "resume_late"),
                                        ("crash_grant", "resume_grant")):
            with self.subTest(crash_mode=crash_mode), tempfile.TemporaryDirectory() as work:
                killed = subprocess.run([sys.executable, "-B", "-c", program, str(ROOT), work, crash_mode],
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(killed.returncode, 9, killed.stdout + killed.stderr)
                state = json.loads((Path(work) / "ledger" / "ledger.json").read_text())
                self.assertEqual(len(state["res"]), 1)
                self.assertIsNone(next(iter(state["res"].values()))["settled"])
                if resume_mode in ("resume_late", "resume_grant"):
                    time.sleep(2.1)
                resumed = subprocess.run([sys.executable, "-B", "-c", program, str(ROOT), work, resume_mode],
                                         capture_output=True, text=True, timeout=30)
                self.assertEqual(resumed.returncode, 0, resumed.stdout + resumed.stderr)


if __name__ == "__main__":
    unittest.main()
