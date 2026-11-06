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
            import logging, os, sys, threading, time
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

            gate = threading.Event()
            bound_gate, bound_started = threading.Event(), threading.Event()
            received_events = []
            if mode == "event_storm":
                original_recv = DBOS.recv
                def observed_recv(topic, *args, **kwargs):
                    result = original_recv(topic, *args, **kwargs)
                    if topic == engine.CASE_EVENT:
                        received_events.append(result)
                    return result
                DBOS.recv = staticmethod(observed_recv)
            if mode == "queued_stop":
                @DBOS.workflow()
                def block_decisions():
                    DBOS.set_event("ready", True)
                    DBOS.recv("release", timeout_seconds=15)
            if mode in ("queued_stop", "stop_inflight", "wake_bound_inflight", "wake_release_inflight", "release_waiting",
                        "bound_stall", "bound_stall_probe", "event_storm"):
                original_handle = engine._BatchV2.handle
                def observed_handle(self, message):
                    original_handle(self, message)
                    if message.get("kind") == "stop_admission": DBOS.set_event("test_stopped", True)
                    if message.get("kind") == "nudge": DBOS.set_event("test_nudged", True)
                    if message.get("kind") == "bound_raised": DBOS.set_event("test_bound_applied", True)
                    if message.get("kind") == "worker_released": DBOS.set_event("test_released", True)
                    if message.get("kind") == "probe_result" and message.get("status") == "waiting":
                        DBOS.set_event("test_waited", True)
                engine._BatchV2.handle = observed_handle

            class LedgerOnly:
                def __init__(self): self.ledger = FakeLedger(work / "ledger")
                def open_batch(self, batch_id, bound): self.ledger.open(batch_id, bound)
                def raise_bound(self, batch_id, bound):
                    if mode in ("bound_stall", "bound_stall_probe"):
                        bound_started.set()
                        if not bound_gate.wait(10): raise AssertionError("bound gate timed out")
                    self.ledger.raise_bound(batch_id, bound)
                def reserve(self, si, *, request, case_limit, draws_case_money):
                    if mode == "expire": time.sleep(2.0)
                    if mode == "event_storm" and si.attempt == 2:
                        received_events.append("next_reserve")
                    grant = self.ledger.reserve(si.batch_id, si.case_id, si.idempotency_key, request,
                                                case_limit, draws_case_money=draws_case_money)
                    block = ((mode in ("stop_inflight", "wake_bound_inflight", "bound_stall_probe") and si.attempt == 1)
                             or (mode == "wake_release_inflight" and si.case_id == "case-t-2" and si.attempt == 1))
                    if block and not gate.wait(10): raise AssertionError("reserve gate timed out")
                    return grant
                def release_unstarted(self, si): self.ledger.settle(si.idempotency_key, Usage())
                def __getattr__(self, name): raise AssertionError("unexpected executor call: " + name)

            ex = LedgerOnly()
            engine._RT.executor = ex
            engine._RT.timing = engine.Timing(batch_poll_s=0.5 if mode == "event_storm" else 0.1,
                                              wake_poll_s=1 if mode == "event_storm" else 60,
                                              queue_poll_s=0.05, listener_poll_s=0.05)
            DBOS(config={"name": "unbug-factory-engine", "application_version": "factory-engine-2",
                         "system_database_url": f"sqlite:///{work}/sys.sqlite",
                         "notification_listener_polling_interval_sec": 0.05})
            DBOS.launch()
            opts = {"target_sealed": 1, "max_cases_started": 1,
                    "money_bound_usd_micros": 0 if mode in ("raise", "stop", "wake_bound_inflight", "bound_stall", "event_storm") else 100_000_000}
            if mode in ("two", "wake_release_inflight", "release_waiting"):
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
            if mode == "stop_inflight":
                until(lambda: ex.ledger.snapshot()["res"])
                DBOS.send(spec.batch_id, {"kind": "stop_admission"}, topic=engine.CASE_EVENT)
                assert DBOS.get_event(spec.batch_id, "test_stopped", timeout_seconds=15) is True
                gate.set()
                result = DBOS.retrieve_workflow(spec.batch_id).get_result()
                assert result["cases"] == {"case-t-1": "not_admitted"}, result
                state = ex.ledger.snapshot()
                row = next(iter(state["res"].values()))
                assert row["settled"] is not None and row["settled"]["paid"] == 0, state
                assert state["batches"][spec.batch_id]["held"] == 0, state
                assert DBOS.get_event("case-t-1", "admission_grant", timeout_seconds=0.2) is None
                os._exit(0)
            if mode == "bound_stall":
                assert DBOS.get_event(spec.batch_id, "test_waited", timeout_seconds=15) is True
                DBOS.send(spec.batch_id, to_record(BoundRaised(100_000_000)), topic=Topic.BOUND_RAISED.value)
                DBOS.send(spec.batch_id, {"kind": "nudge"}, topic=engine.CASE_EVENT)
                assert bound_started.wait(10)
                DBOS.send(spec.batch_id, {"kind": "stop_admission"}, topic=engine.CASE_EVENT)
                assert DBOS.get_event(spec.batch_id, "test_stopped", timeout_seconds=5) is True
                card = until(lambda: (c if (c := DBOS.get_event("case-t-1", "card", timeout_seconds=0.2))
                                      and c["status"] == "not_admitted" else None))
                assert not bound_gate.is_set(), card
                bound_gate.set()
                result = DBOS.retrieve_workflow(spec.batch_id).get_result()
                assert result["cases"] == {"case-t-1": "not_admitted"}, result
                os._exit(0)
            if mode == "bound_stall_probe":
                until(lambda: ex.ledger.snapshot()["res"])
                DBOS.send(spec.batch_id, to_record(BoundRaised(200_000_000)), topic=Topic.BOUND_RAISED.value)
                DBOS.send(spec.batch_id, {"kind": "nudge"}, topic=engine.CASE_EVENT)
                assert bound_started.wait(10)
                gate.set()
                grant = until(lambda: DBOS.get_event("case-t-1", "admission_grant", timeout_seconds=0.2))
                assert grant and not bound_gate.is_set(), grant
                bound_gate.set()
                os._exit(0)
            if mode == "wake_bound_inflight":
                until(lambda: ex.ledger.snapshot()["res"])
                DBOS.send(spec.batch_id, to_record(BoundRaised(100_000_000)), topic=Topic.BOUND_RAISED.value)
                DBOS.send(spec.batch_id, {"kind": "nudge"}, topic=engine.CASE_EVENT)
                assert DBOS.get_event(spec.batch_id, "test_bound_applied", timeout_seconds=15) is True
                gate.set()
                grant = until(lambda: DBOS.get_event("case-t-1", "admission_grant", timeout_seconds=0.2))
                state = ex.ledger.snapshot()
                assert len(state["res"]) == 2 and state["res"][grant["key"]]["settled"] is None, state
                assert any(v["amount"] == 0 and v["settled"] is not None for v in state["res"].values()), state
                os._exit(0)
            if mode in ("wake_release_inflight", "release_waiting"):
                first = until(lambda: DBOS.get_event("case-t-1", "admission_grant", timeout_seconds=0.2))
                until(lambda: len(ex.ledger.snapshot()["res"]) == 2)
                if mode == "release_waiting":
                    assert DBOS.get_event(spec.batch_id, "test_waited", timeout_seconds=15) is True
                ex.ledger.settle(first["key"], Usage())
                DBOS.send(spec.batch_id, {"kind": "worker_released", "case": "case-t-1"}, topic=engine.CASE_EVENT)
                assert DBOS.get_event(spec.batch_id, "test_released", timeout_seconds=15) is True
                gate.set()
                grant = until(lambda: DBOS.get_event("case-t-2", "admission_grant", timeout_seconds=0.2))
                state = ex.ledger.snapshot()
                assert len(state["res"]) == 3 and state["res"][grant["key"]]["settled"] is None, state
                assert any(v["case"] == "case-t-2" and v["amount"] == 0 and v["settled"] is not None
                           for v in state["res"].values()), state
                os._exit(0)
            if mode == "event_storm":
                assert DBOS.get_event(spec.batch_id, "test_waited", timeout_seconds=15) is True
                first_wait = next(i for i, msg in enumerate(received_events)
                                  if isinstance(msg, dict) and msg.get("kind") == "probe_result"
                                  and msg.get("status") == "waiting")
                assert len(ex.ledger.snapshot()["res"]) == 1
                stop = threading.Event()
                def traffic():
                    while not stop.is_set():
                        DBOS.send(spec.batch_id, {"kind": "unrelated"}, topic=engine.CASE_EVENT)
                        time.sleep(0.02)
                thread = threading.Thread(target=traffic, daemon=True)
                thread.start()
                try:
                    state = until(lambda: (s if len((s := ex.ledger.snapshot())["res"]) >= 2 else None))
                    end = received_events.index("next_reserve", first_wait)
                    observed = received_events[first_wait:end]
                    unrelated = sum(isinstance(msg, dict) and msg.get("kind") == "unrelated"
                                    for msg in observed)
                    assert unrelated >= 2 and None not in observed, observed
                    assert thread.is_alive() and len(state["res"]) >= 2, state
                finally:
                    stop.set(); thread.join(timeout=3)
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
        for mode in ("raise", "stop", "small", "zero", "expire", "queued_stop", "two", "stop_inflight",
                     "wake_bound_inflight", "wake_release_inflight", "release_waiting", "bound_stall",
                     "bound_stall_probe", "event_storm"):
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

    def test_settled_wait_and_expiry_survive_restart_with_clock_reversed(self):
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

            @DBOS.step()
            def fake_now(): return float((work / "clock.txt").read_text())
            engine.now_step = fake_now
            original_handle = engine._BatchV2.handle
            def watched_handle(self, message):
                original_handle(self, message)
                if message.get("kind") == "probe_result" and message.get("status") == "waiting":
                    DBOS.set_event("test_waited", True)
            engine._BatchV2.handle = watched_handle

            class LedgerOnly:
                def __init__(self): self.ledger = FakeLedger(work / "ledger")
                def open_batch(self, batch_id, bound): self.ledger.open(batch_id, bound)
                def raise_bound(self, batch_id, bound): self.ledger.raise_bound(batch_id, bound)
                def reserve(self, si, *, request, case_limit, draws_case_money):
                    grant = self.ledger.reserve(si.batch_id, si.case_id, si.idempotency_key, request,
                                                case_limit, draws_case_money=draws_case_money)
                    if mode == "crash_expired": (work / "clock.txt").write_text("300")
                    return grant
                def release_unstarted(self, si):
                    self.ledger.settle(si.idempotency_key, Usage())
                    if mode.startswith("crash"):
                        (work / "clock.txt").write_text("50")
                        os._exit(9)
                def __getattr__(self, name): raise AssertionError("unexpected executor call: " + name)

            ex = LedgerOnly()
            if mode == "raise_offline":
                ex.ledger.raise_bound("b-t", 200_000_000)
                os._exit(0)
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
                spec = make_spec(target_sealed=1, max_cases_started=1, deadline_epoch=200,
                                 money_bound_usd_micros=0 if mode == "crash_wait" else 100_000_000)
                registry = Ref("a" * 64, ArtifactKind.STATEMENT_REGISTRY)
                with SetWorkflowID(spec.batch_id):
                    DBOS.start_workflow(engine.batch_workflow, {"spec": to_record(spec),
                                        "initial_registry": to_record(registry), "queue_v2": True,
                                        "probe_enabled": True})
                time.sleep(20)
                raise AssertionError("zero-settlement kill point not reached")

            if mode == "resume_wait":
                assert DBOS.get_event("b-t", "test_waited", timeout_seconds=15) is True
                DBOS.send("b-t", to_record(BoundRaised(200_000_000)), topic=Topic.BOUND_RAISED.value)
                DBOS.send("b-t", {"kind": "nudge"}, topic=engine.CASE_EVENT)
                end = time.monotonic() + 15
                while time.monotonic() < end:
                    grant = DBOS.get_event("case-t-1", "admission_grant", timeout_seconds=0.2)
                    if grant:
                        state = ex.ledger.snapshot()
                        assert grant["key"].endswith("/2"), grant
                        assert len(state["res"]) == 2, state
                        assert state["res"]["case-t-1/1/admit/1"]["settled"] is not None, state
                        assert state["res"][grant["key"]]["settled"] is None, state
                        os._exit(0)
                    time.sleep(0.03)
                raise AssertionError("raised bound did not admit a fresh key")

            result = DBOS.retrieve_workflow("b-t").get_result()
            assert result["cases"] == {"case-t-1": "not_admitted"}, result
            state = ex.ledger.snapshot()
            assert len(state["res"]) == 1 and next(iter(state["res"].values()))["settled"] is not None, state
            assert DBOS.get_event("case-t-1", "admission_grant", timeout_seconds=0.2) is None
            os._exit(0)
        ''')
        for state in ("wait", "expired"):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as work:
                (Path(work) / "clock.txt").write_text("100")
                crashed = subprocess.run([sys.executable, "-B", "-c", program, str(ROOT), work, f"crash_{state}"],
                                         capture_output=True, text=True, timeout=30)
                self.assertEqual(crashed.returncode, 9, crashed.stdout + crashed.stderr)
                self.assertEqual((Path(work) / "clock.txt").read_text(), "50")
                ledger = json.loads((Path(work) / "ledger" / "ledger.json").read_text())
                self.assertIsNotNone(next(iter(ledger["res"].values()))["settled"])
                raised = subprocess.run([sys.executable, "-B", "-c", program, str(ROOT), work, "raise_offline"],
                                        capture_output=True, text=True, timeout=15)
                self.assertEqual(raised.returncode, 0, raised.stdout + raised.stderr)
                resumed = subprocess.run([sys.executable, "-B", "-c", program, str(ROOT), work, f"resume_{state}"],
                                         capture_output=True, text=True, timeout=30)
                self.assertEqual(resumed.returncode, 0, resumed.stdout + resumed.stderr)


if __name__ == "__main__":
    unittest.main()
