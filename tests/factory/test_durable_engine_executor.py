"""WP1 executor (factory/durable/executor.py) against in-memory fakes of its seams.

docs/designs/durable-execution-wp1.md: the executor composes pool, channel, ledger, store,
sealer and keys; a transport failure is RUNNING; cancellation is reconciled until the worker
answers or is proven dead; unknown usage settles as lost; seam errors carry only a fixed code.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import ModuleType
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "factory"), str(Path(__file__).resolve().parent)]
os.environ.setdefault("BENCH", str(ROOT))

from durable.contract import (ArtifactKind as K, Grant, LimitedBy, Outcome, Poll, PollState, Step, StepInput,
                              StepKind, StepResult, Usage, WorkerLease, guarded_run, step_result_from_record, to_record)
from durable.executor import Executor, SeamError, blob_name
from test_durable_engine_fakes import FakeKeys, FakeLedger, FakeSealer, FakeStore  # noqa: E402

P, B = "1" * 64, "2" * 64


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


class Pool:
    def __init__(self):
        self.dead, self.acquired, self.released = False, [], []

    def acquire(self, case_id, pv, bv):
        self.acquired.append((case_id, pv, bv))
        return WorkerLease("w-1", case_id)

    def release(self, lease):
        self.released.append(lease)

    def alive(self, lease):
        return not self.dead


class Channel:
    """polls: a list of Poll objects (or None for a transport failure), consumed in order;
    the last one repeats. cancel_drops: cancels that do nothing before one lands."""

    def __init__(self, polls, cancel_drops=0, on_cancel=None):
        self.polls, self.cancel_drops, self.on_cancel = list(polls), cancel_drops, on_cancel
        self.started, self.cancels = [], 0

    def start(self, lease, si, keys, blobs):
        self.started.append((si.idempotency_key, sorted(keys), sorted(blobs)))

    def poll(self, lease, si):
        p = self.polls.pop(0) if len(self.polls) > 1 else self.polls[0]
        if p is None:
            raise OSError("ssh: connection reset")   # a transport failure
        return p

    def cancel(self, lease, si):
        self.cancels += 1
        if self.cancels > self.cancel_drops and self.on_cancel:
            self.polls = [self.on_cancel]


class Setup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.keys, self.sealer, self.store = FakeKeys(), FakeSealer(), FakeStore(root / "store")
        self.ledger = FakeLedger(root / "ledger")
        self.ledger.open("b-t", 100_000_000)
        self.clock, self.pool = Clock(), Pool()
        bk = self.keys.scope_key("b-t")
        self.inputs, ct = self.sealer.seal(bk, K.INPUTS, b"inputs")
        self.store.put_sealed("b-t", self.inputs, ct)
        self.registry, ct = self.sealer.seal(bk, K.STATEMENT_REGISTRY, b"registry")
        self.store.put_sealed("b-t", self.registry, ct)
        self.snap = self.put("case-t-1", K.CASE_SNAPSHOT, b"snapshot")

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, scope, kind, text):
        ref, ct = self.sealer.seal(self.keys.scope_key(scope), kind, text)
        self.store.put_sealed(scope, ref, ct)
        return ref

    def ex(self, channel):
        return Executor(self.pool, channel, self.ledger, self.store, self.sealer, self.keys, poll_interval_s=10.0,
                        grace_s=100.0, clock=self.clock, sleep=self.clock.sleep)

    def si(self, step=None, attempt=1, deadline=600.0, **kw):
        step = step or Step(StepKind.WRITER, 1)
        admit = step.kind is StepKind.ADMIT
        return StepInput("b-t", "case-t-1", 2, step, attempt, P, B, self.inputs,
                         None if admit else self.snap, deadline, 5_000_000,
                         registry=self.registry if admit else None, **kw)

    def ok(self, **kw):
        return StepResult(Outcome.OK, "writer:pass", Usage(1, 300, 300), snapshot=self.snap, **kw)


class Run(Setup):
    def test_crashed_done_keeps_checkpoint_even_without_an_earlier_poll(self):
        checkpoint = self.put("case-t-1", K.CASE_SNAPSHOT, b"latest completed work")
        failed = StepResult(Outcome.INFRA_ERROR, "infra:step_crashed", Usage(1, 300, 300))
        for polls in ([Poll(PollState.DONE, failed, checkpoint=checkpoint)],
                      [Poll(PollState.RUNNING, checkpoint=checkpoint), Poll(PollState.DONE, failed)]):
            result = guarded_run(self.ex(Channel(polls)), self.si())
            self.assertEqual(result.snapshot, checkpoint)
            self.assertEqual(result.usage, failed.usage)

    def test_done_sends_the_right_keys_and_blobs(self):
        ch = Channel([Poll(PollState.RUNNING), None, Poll(PollState.DONE, self.ok())])
        r = guarded_run(self.ex(ch), self.si())
        self.assertIs(r.outcome, Outcome.OK)
        key, keys, blobs = ch.started[0]
        self.assertEqual(keys, ["case-t-1"])                          # only the case key
        self.assertEqual(blobs, sorted([blob_name(self.inputs), blob_name(self.snap)]))
        self.assertEqual(self.pool.acquired, [("case-t-1", P, B)])
        ch = Channel([Poll(PollState.DONE, StepResult(Outcome.OK, "admit:pass", snapshot=self.snap,
                                                       registry=self.registry))])
        guarded_run(self.ex(ch), self.si(Step(StepKind.ADMIT)))
        self.assertEqual(ch.started[0][1], ["b-t", "case-t-1"])        # ADMIT also gets the batch key
        self.assertEqual(ch.started[0][2], sorted([blob_name(self.inputs), blob_name(self.registry)]))

    def test_absent_and_lost_workers(self):
        cancelled = Poll(PollState.DONE, StepResult(Outcome.INFRA_ERROR, "infra:cancelled"))
        r = self.ex(Channel([Poll(PollState.ABSENT)], on_cancel=cancelled)).run(self.si())
        self.assertEqual(r.reason, "infra:attempt_absent")
        self.pool.dead = True
        ckpt = self.put("case-t-1", K.CASE_SNAPSHOT, b"checkpoint")
        r = self.ex(Channel([Poll(PollState.RUNNING, checkpoint=ckpt), None])).run(self.si())
        self.assertEqual((r.reason, r.snapshot), ("infra:worker_lost", ckpt))   # a retry may restore it

    def test_late_done_survives_a_prolonged_unconfirmed_cancel(self):
        late = self.ok()
        ch = Channel([None] * 30 + [Poll(PollState.DONE, late)])
        r = self.ex(ch).run(self.si(deadline=1.0), started_at=self.clock())
        self.assertEqual(r, late)
        self.assertGreater(ch.cancels, 10)

    def test_long_transfer_does_not_cancel_a_newly_started_worker(self):
        clock = self.clock
        class SlowStart(Channel):
            def start(self, lease, si, keys, blobs):
                clock.sleep(700.0)  # transfer lasted beyond the control-side deadline
                super().start(lease, si, keys, blobs)
        late = self.ok()
        ch = SlowStart([Poll(PollState.RUNNING)] * 15 + [Poll(PollState.DONE, late)])
        result = self.ex(ch).run(self.si(deadline=600.0), started_at=clock())
        self.assertEqual(result, late)
        self.assertEqual(ch.cancels, 0)

    def test_replay_with_unavailable_inputs_recovers_the_worker_result(self):
        late = self.ok()
        ch = Channel([Poll(PollState.RUNNING), Poll(PollState.DONE, late)])
        class FlakyStore:
            def __init__(self, store):
                self.store = store
            def get_sealed(self, scope, ref):
                if ref.kind is K.INPUTS:
                    raise OSError("temporary read failure")
                return self.store.get_sealed(scope, ref)
            def exists(self, scope, ref):
                return self.store.exists(scope, ref)
        ex = self.ex(ch)
        ex.store = FlakyStore(self.store)
        result = ex.run(self.si(), lease=WorkerLease("w-1", "case-t-1"))
        self.assertEqual(result, late)
        self.assertFalse(ch.started)

    def test_an_unexpected_executor_exception_reconciles_before_settlement(self):
        from durable.engine import _RT, attempt_step
        late = self.ok()
        channel = Channel([None] * 15 + [Poll(PollState.DONE, late)])
        class BrokenExecutor(Executor):
            def run(self, *args, **kwargs):
                raise RuntimeError("after dispatch")
        ex = BrokenExecutor(self.pool, channel, self.ledger, self.store, self.sealer, self.keys,
                            poll_interval_s=10, grace_s=100, clock=self.clock, sleep=self.clock.sleep)
        old = _RT.executor
        _RT.executor = ex
        try:
            result = step_result_from_record(attempt_step(to_record(self.si()), self.clock(), "w-1"))
        finally:
            _RT.executor = old
        self.assertEqual(result, late)
        self.assertGreater(channel.cancels, 1)

    def test_reconcile_goes_through_guarded_run(self):
        import durable.engine as engine
        late = self.ok()
        channel = Channel([None] * 15 + [Poll(PollState.DONE, late)])
        class BrokenExecutor(Executor):
            def run(self, *args, **kwargs):
                raise RuntimeError("after dispatch")
        ex = BrokenExecutor(self.pool, channel, self.ledger, self.store, self.sealer, self.keys,
                            poll_interval_s=10, grace_s=100, clock=self.clock, sleep=self.clock.sleep)
        guarded, original, old = [], engine.guarded_run, engine._RT.executor
        engine.guarded_run = lambda executor, si: guarded.append(executor) or original(executor, si)
        engine._RT.executor = ex
        try:
            result = step_result_from_record(engine.attempt_step(to_record(self.si()), self.clock(), "w-1"))
        finally:
            engine.guarded_run, engine._RT.executor = original, old
        self.assertEqual(result, late)
        self.assertEqual(len(guarded), 2)   # the attempt, then its reconcile

    def test_an_unreachable_worker_is_not_declared_lost_until_death_is_proven(self):
        from durable.engine import _RT, attempt_step
        clock = self.clock
        class EventuallyDead(Pool):
            def alive(self, lease):
                return clock.t < 1300
        class BrokenExecutor(Executor):
            def run(self, *args, **kwargs):
                raise RuntimeError("after dispatch")
        channel = Channel([None])
        ex = BrokenExecutor(EventuallyDead(), channel, self.ledger, self.store, self.sealer, self.keys,
                            poll_interval_s=10, grace_s=100, clock=clock, sleep=clock.sleep)
        old = _RT.executor
        _RT.executor = ex
        try:
            result = step_result_from_record(attempt_step(to_record(self.si()), clock(), "w-1"))
        finally:
            _RT.executor = old
        self.assertEqual(result.reason, "infra:worker_lost")
        self.assertGreaterEqual(clock.t, 1300)
        self.assertGreater(channel.cancels, 10)

    def test_a_parked_thread_outside_an_attempt_does_not_end_the_drain_early(self):
        from durable import engine
        engine._RT.draining.set()
        self.addCleanup(engine._RT.draining.clear)
        threading.Thread(target=engine.hold_if_draining, daemon=True).start()
        time.sleep(0.05)
        self.assertEqual(engine._RT.parked, 0)

    def test_a_worker_that_can_never_be_confirmed_stops_blocking_the_case(self):
        """Boat stays unreadable: `alive` stays unknown, so nothing proves the worker gone. The
        run ends once any TTL has run out, instead of spinning for the life of the batch."""
        channel = Channel([None])
        ex = self.ex(channel)
        ex.unconfirmed_limit_s = 3600.0
        si = self.si(deadline=600.0)
        lease = WorkerLease("w-1", si.case_id)
        result = ex.run(si, started_at=self.clock(), lease=lease)
        self.assertEqual(result.reason, "infra:worker_lost")
        self.assertGreaterEqual(self.clock.t, 1000 + 600 + 3600)
        self.assertEqual(ex.pool.released, [lease])   # it cannot run beside the next attempt

    def silent_ex(self, channel, renewing, silent=1800.0):
        return Executor(self.pool, channel, self.ledger, self.store, self.sealer, self.keys, poll_interval_s=10.0,
                        grace_s=100.0, clock=self.clock, sleep=self.clock.sleep, unconfirmed_limit_s=3600.0,
                        renewing=renewing, silent_limit_s=silent)

    def test_a_silent_worker_with_stopped_renewal_is_retired_after_30_minutes(self):
        ex = self.silent_ex(Channel([None]), lambda lease: False)
        si = self.si(deadline=6 * 3600.0)
        lease = WorkerLease("w-1", si.case_id)
        result = ex.run(si, started_at=self.clock(), lease=lease)
        self.assertEqual(result.reason, "infra:worker_lost")
        self.assertGreaterEqual(self.clock.t, 1000 + 1800)
        self.assertLess(self.clock.t, 1000 + 1800 + 60)   # not the deadline plus the unconfirmed limit
        self.assertEqual(ex.pool.released, [lease])

    def test_a_silent_worker_whose_lease_is_still_renewed_is_not_retired_early(self):
        for renewing in (lambda lease: True, lambda lease: None, None):
            with self.subTest(renewing=renewing):
                self.clock.t, self.pool.released = 1000.0, []
                ex = self.silent_ex(Channel([None]), renewing)
                si = self.si(deadline=600.0)
                result = ex.run(si, started_at=self.clock(), lease=WorkerLease("w-1", si.case_id))
                self.assertEqual(result.reason, "infra:worker_lost")
                self.assertGreaterEqual(self.clock.t, 1000 + 600 + 3600)   # only the old limit ends it

    def test_a_worker_that_answers_polls_is_never_called_silent(self):
        # Answers every 10 s with RUNNING, then goes quiet: the 30 minutes count from the last answer.
        class Talks(Channel):
            def poll(inner, lease, si):
                if self.clock.t < 1000 + 3000:
                    return Poll(PollState.RUNNING)
                raise OSError("ssh: connection reset")
        ex = self.silent_ex(Talks([None]), lambda lease: False)
        si = self.si(deadline=6 * 3600.0)
        result = ex.run(si, started_at=self.clock(), lease=WorkerLease("w-1", si.case_id))
        self.assertEqual(result.reason, "infra:worker_lost")
        self.assertGreaterEqual(self.clock.t, 1000 + 3000 + 1800 - 20)   # from the last answer, within one poll

    def test_guard_renewing_is_false_only_once_a_known_renewal_goes_stale(self):
        from durable.guard import renewing
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(renewing(tmp, "bx_aaaaaaaa"))   # no record: unknown
            (Path(tmp) / "guard").mkdir()
            now = time.time()
            (Path(tmp) / "guard" / "renewed.json").write_text(json.dumps({
                "bx_aaaaaaaa": {"ok": now - 60},                                  # renewed, no refusal
                "bx_bbbbbbbb": {"ok": now - 5000, "refused": now - 30},           # refused, last ok long ago
                "bx_cccccccc": {"ok": now - 5000},                                # no pass since: unknown
                "bx_dddddddd": {"ok": now - 60, "refused": now - 30}}))           # recent ok: still renewed
            self.assertTrue(renewing(tmp, "bx_aaaaaaaa") is None)
            self.assertFalse(renewing(tmp, "bx_bbbbbbbb"))
            self.assertIsNone(renewing(tmp, "bx_cccccccc"))
            self.assertTrue(renewing(tmp, "bx_dddddddd"))
            self.assertIsNone(renewing(tmp, "bx_eeeeeeee"))

    def test_a_result_landing_at_the_limit_beats_deleting_the_worker(self):
        si = self.si(deadline=600.0)
        ex = self.ex(Channel([Poll(PollState.DONE, self.ok())]))
        ex.unconfirmed_limit_s = 0.0
        self.clock.t += 10000
        result = ex.run(si, started_at=1000.0, lease=WorkerLease("w-1", si.case_id))
        self.assertIs(result.outcome, Outcome.OK)
        self.assertEqual(ex.pool.released, [])

    def test_an_undeletable_worker_is_not_called_lost(self):
        clock = self.clock
        class Refusing(Pool):
            def release(self, lease):
                if clock.t < 6000:
                    raise OSError("boat down")
                super().release(lease)
        ex = Executor(Refusing(), Channel([None]), self.ledger, self.store, self.sealer, self.keys,
                      poll_interval_s=10, grace_s=100, clock=clock, sleep=clock.sleep, unconfirmed_limit_s=3600.0)
        si = self.si(deadline=600.0)
        result = ex.run(si, started_at=clock(), lease=WorkerLease("w-1", si.case_id))
        self.assertEqual(result.reason, "infra:worker_lost")
        self.assertGreaterEqual(clock.t, 6000)

    def test_reconcile_of_an_unconfirmed_worker_is_bounded_too(self):
        ex = self.ex(Channel([None]))
        ex.unconfirmed_limit_s = 3600.0
        si = self.si()
        lease = WorkerLease("w-1", si.case_id)
        result = ex.reconcile(si, lease)
        self.assertEqual(result.reason, "infra:worker_lost")
        self.assertGreaterEqual(self.clock.t, 1000 + 3600)
        self.assertEqual(ex.pool.released, [lease])

    def test_a_reconcile_that_keeps_raising_cannot_spin_forever(self):
        from dataclasses import replace
        from durable import engine
        class Broken(Executor):
            def run(self, *args, **kwargs):
                raise RuntimeError("after dispatch")
            def reconcile(self, si, lease):
                raise RuntimeError("deleted worker")
        ex = Broken(Pool(), Channel([None]), self.ledger, self.store, self.sealer, self.keys)
        old = engine._RT.executor, engine._RT.timing
        engine._RT.executor = ex
        engine._RT.timing = replace(engine.Timing(), reconcile_retry_s=0.01, unconfirmed_limit_s=0.05)
        try:
            result = step_result_from_record(engine.attempt_step(to_record(self.si()), self.clock(), "w-1"))
        finally:
            engine._RT.executor, engine._RT.timing = old
        self.assertEqual(result.reason, "infra:worker_lost")
        self.assertEqual(ex.pool.released, [WorkerLease("w-1", self.si().case_id)])

    def test_binding_failure_also_reconciles_the_recorded_worker(self):
        from durable.engine import _RT, attempt_step
        late = self.ok()
        channel = Channel([Poll(PollState.DONE, late)])
        class BrokenBinding(Executor):
            def bound(self, *args):
                raise RuntimeError("binding failed after a restart")
        ex = BrokenBinding(self.pool, channel, self.ledger, self.store, self.sealer, self.keys,
                           poll_interval_s=10, grace_s=100, clock=self.clock, sleep=self.clock.sleep)
        old = _RT.executor
        _RT.executor = ex
        try:
            result = step_result_from_record(attempt_step(to_record(self.si()), self.clock(), "w-1"))
        finally:
            _RT.executor = old
        self.assertEqual(result, late)
        self.assertEqual(channel.cancels, 1)

    def test_cancel_after_the_deadline_takes_a_confirmed_result(self):
        late = StepResult(Outcome.INFRA_ERROR, "infra:deadline", Usage(1, 900, 900))
        ch = Channel([Poll(PollState.RUNNING)], cancel_drops=2, on_cancel=Poll(PollState.DONE, late))
        r = self.ex(ch).run(self.si(), started_at=self.clock())
        self.assertEqual((r.reason, r.usage.paid_usd_micros), ("infra:deadline", 900))
        self.assertEqual(ch.cancels, 3)

    def test_transient_output_verification_keeps_the_completed_attempt(self):
        from durable.artifacts import ArtifactError
        completed = self.ok()
        ch = Channel([Poll(PollState.DONE, completed)])
        original_poll = ch.poll
        armed = False

        def fail_once(target, name, error):
            original = getattr(target, name)
            failed = False
            def call(*args, **kwargs):
                nonlocal failed
                if not failed:
                    failed = True
                    raise error
                return original(*args, **kwargs)
            setattr(target, name, call)

        def poll(lease, si):
            nonlocal armed
            if not armed:
                armed = True
                fail_once(self.store, "exists", OSError("temporary store failure"))
                fail_once(self.keys, "scope_key", OSError("temporary key failure"))
                fail_once(self.sealer, "open", ArtifactError("age_timeout"))
            return original_poll(lease, si)

        ch.poll = poll
        result = self.ex(ch).run(self.si())
        self.assertEqual(result, completed)
        self.assertEqual(len(ch.started), 1)
        self.assertGreaterEqual(self.clock(), 30.0)

    def test_missing_outputs_are_infra(self):
        missing = self.sealer.seal(self.keys.scope_key("case-t-1"), K.GATE_RECEIPT, b"never stored")[0]
        r = self.ex(Channel([Poll(PollState.DONE, self.ok(receipt=missing))])).run(self.si())
        self.assertEqual((r.reason, r.usage.paid_usd_micros), ("infra:output_missing", 300))

    def test_corrupt_output_or_checkpoint_is_never_recorded(self):
        si = self.si()
        self.store._path(si.case_id, self.snap).write_bytes(b"corrupt ciphertext")
        r = self.ex(Channel([Poll(PollState.DONE, self.ok())])).run(si)
        self.assertEqual((r.outcome, r.reason, r.usage.paid_usd_micros),
                         (Outcome.INFRA_ERROR, "infra:output_invalid", 300))
        self.pool.dead = True
        r = self.ex(Channel([Poll(PollState.RUNNING, checkpoint=self.snap)])).run(si)
        self.assertIsNone(r.snapshot)

    def test_ciphertext_encrypted_for_another_case_is_not_valid_output(self):
        si = self.si()
        wrong = self.sealer.seal(self.keys.scope_key("case-t-2"), K.CASE_SNAPSHOT, b"other")[1]
        self.store._path(si.case_id, self.snap).write_bytes(wrong)
        r = self.ex(Channel([Poll(PollState.DONE, self.ok())])).run(si)
        self.assertEqual(r.reason, "infra:output_invalid")

    def test_dispatch_failure_never_raises(self):
        class Broken(Pool):
            def acquire(self, *a):
                raise RuntimeError("boat: /home/user/case-secret not found")
        ex = Executor(Broken(), Channel([Poll(PollState.ABSENT)]), self.ledger, self.store, self.sealer, self.keys)
        self.assertEqual(guarded_run(ex, self.si()).reason, "infra:dispatch_failed")


class CancelBeforeRetry(Setup):
    def test_cancel_is_retried_through_transport_failures(self):
        cancelled = StepResult(Outcome.INFRA_ERROR, "infra:cancelled")
        ch = Channel([None], cancel_drops=3, on_cancel=Poll(PollState.DONE, cancelled))
        self.assertTrue(self.ex(ch).cancel(self.si(), started_at=self.clock()))
        self.assertEqual(ch.cancels, 4)

    def test_cancel_gives_up_at_deadline_plus_grace(self):
        ch = Channel([None])
        self.assertFalse(self.ex(ch).cancel(self.si(deadline=600.0), started_at=self.clock()))
        self.assertGreaterEqual(self.clock.t, 1700.0)
        self.assertLess(self.clock.t, 1720.0)

    def test_a_dead_worker_needs_no_cancel(self):
        self.pool.dead = True
        ch = Channel([None])
        self.assertFalse(self.ex(ch).cancel(self.si(), started_at=self.clock()))
        self.assertEqual(ch.cancels, 1)


class Settle(Setup):
    def test_only_the_pool_error_type_can_supply_a_reason(self):
        workers = ModuleType("durable.workers")
        class PoolError(Exception):
            def __init__(self, reason):
                self.reason = reason
        workers.PoolError = PoolError
        class Broken(Pool):
            def __init__(self, error):
                super().__init__()
                self.error = error
            def acquire(self, *args):
                raise self.error
        for error, expected in ((PoolError("infra:release_missing"), "infra:release_missing"),
                                (RuntimeError("private/path"), "infra:pool_failed")):
            ex = Executor(Broken(error), None, self.ledger, self.store, self.sealer, self.keys)
            with patch.dict(sys.modules, {"durable.workers": workers}):
                with self.assertRaises(SeamError) as caught:
                    ex.lease_for("case-t-1", P, B)
            self.assertEqual(caught.exception.code, expected)
            self.assertIsNone(caught.exception.__context__)

    def reserve(self, si):
        return self.ex(None).reserve(si, request=5_000_000, case_limit=50_000_000, draws_case_money=True)

    def test_routing(self):
        ex = self.ex(None)
        cases = [(self.ok(), "case"),
                 (StepResult(Outcome.INFRA_ERROR, "infra:stalled", Usage(1, 7, 7)), "waste"),
                 (StepResult(Outcome.PROVIDER_LIMIT, "router:claude_limit", Usage(1, 7, 7), retry_at=1.0), "waste"),
                 (StepResult(Outcome.PROVIDER_LIMIT, "router:claude_limit", retry_at=1.0), "case"),
                 (StepResult(Outcome.INFRA_ERROR, "infra:cancelled"), "lost"),
                 (StepResult(Outcome.INFRA_ERROR, "infra:worker_lost"), "lost"),
                 (StepResult(Outcome.INFRA_ERROR, "engine:executor_raised"), "lost")]
        for attempt, (result, how) in enumerate(cases, 1):
            si = self.si(attempt=attempt)
            self.assertEqual(self.reserve(si), Grant(5_000_000, LimitedBy.NOTHING))
            self.assertEqual(ex.settle(si, result), how)
        s = self.ledger.snapshot()
        self.assertEqual(s["cases"]["case-t-1"]["spent"], 300)                # only the OK attempt
        self.assertEqual(s["batches"]["b-t"]["waste"], 7 + 7 + 3 * 5_000_000)   # lost books the whole grant

    def test_a_cancelled_attempt_that_reports_usage_books_that_usage_as_waste(self):
        # case-import-2abb0a-2-1: a GATES attempt with a $61.76 grant was cancelled after 148 calls
        # and $5.54 of real spend. Booking its whole grant stranded the batch at waiting_for_bound.
        ex = self.ex(None)
        si = self.si(attempt=1)
        ex.reserve(si, request=61_760_000, case_limit=225_000_000, draws_case_money=True)
        reported = StepResult(Outcome.INFRA_ERROR, "infra:cancelled", Usage(148, 5_539_236, 5_539_236))
        self.assertEqual(ex.settle(si, reported), "waste")
        # A cancel with no usage (a tombstone, or a worker that never saw the attempt) stays lost.
        si2 = self.si(attempt=2)
        ex.reserve(si2, request=5_000_000, case_limit=225_000_000, draws_case_money=True)
        self.assertEqual(ex.settle(si2, StepResult(Outcome.INFRA_ERROR, "infra:cancelled")), "lost")
        s = self.ledger.snapshot()
        self.assertEqual(s["batches"]["b-t"]["waste"], 5_539_236 + 5_000_000)
        self.assertEqual(s["cases"]["case-t-1"]["spent"], 0)              # waste never touches the case

    def test_seam_errors_carry_no_content(self):
        class Leaky(FakeLedger):
            def reserve(self, *a, **k):
                raise RuntimeError("g5 failed on src/modules/inventory/reserve.ts")
        ex = Executor(self.pool, None, Leaky(Path(self.tmp.name) / "l2"), self.store, self.sealer, self.keys)
        with self.assertRaises(SeamError) as caught:
            ex.reserve(self.si(), request=1, case_limit=1, draws_case_money=True)
        self.assertEqual(str(caught.exception), "engine:ledger_failed")
        self.assertIsNone(caught.exception.__context__)
        self.assertIsNone(caught.exception.__cause__)


class Sealing(Setup):
    def test_real_store_rejects_output_with_the_wrong_digest(self):
        from durable.artifacts import AgeSealer, local_store
        sealer, store = AgeSealer(), local_store(Path(self.tmp.name) / "real-output-store")
        batch_key, case_key = self.keys.scope_key("b-t"), self.keys.scope_key("case-t-1")
        inputs, ct = sealer.seal(batch_key, K.INPUTS, b"public practice input")
        store.put_sealed("b-t", inputs, ct)
        snapshot, _ = sealer.seal(case_key, K.CASE_SNAPSHOT, b"expected")
        _, wrong_ct = sealer.seal(case_key, K.CASE_SNAPSHOT, b"different bytes")
        store.put_sealed("case-t-1", snapshot, wrong_ct)
        si = StepInput("b-t", "case-t-1", 2, Step(StepKind.WRITER, 1), 1, P, B,
                       inputs, snapshot, 600, 5_000_000)
        done = StepResult(Outcome.OK, "writer:pass", Usage(1, 300, 300), snapshot=snapshot)
        ex = Executor(self.pool, Channel([Poll(PollState.DONE, done)]), self.ledger, store, sealer, self.keys,
                      poll_interval_s=10, grace_s=100, clock=self.clock, sleep=self.clock.sleep)
        result = ex.run(si)
        self.assertEqual((result.reason, result.usage.paid_usd_micros), ("infra:output_invalid", 300))

    def test_killed_age_decrypt_retries_the_same_completed_result(self):
        import subprocess
        from durable.artifacts import AgeSealer, local_store
        sealer, store = AgeSealer(), local_store(Path(self.tmp.name) / "interrupted-age")
        batch_key, case_key = self.keys.scope_key("b-t"), self.keys.scope_key("case-t-1")
        inputs, ciphertext = sealer.seal(batch_key, K.INPUTS, b"inputs")
        store.put_sealed("b-t", inputs, ciphertext)
        snapshot, ciphertext = sealer.seal(case_key, K.CASE_SNAPSHOT, b"snapshot")
        store.put_sealed("case-t-1", snapshot, ciphertext)
        si = StepInput("b-t", "case-t-1", 2, Step(StepKind.WRITER, 1), 1, P, B, inputs, snapshot, 600, 5_000_000)
        done = StepResult(Outcome.OK, "writer:pass", Usage(1, 300, 300), snapshot=snapshot)
        channel = Channel([Poll(PollState.DONE, done)])
        ex = Executor(self.pool, channel, self.ledger, store, sealer, self.keys,
                      poll_interval_s=10, grace_s=100, clock=self.clock, sleep=self.clock.sleep)
        original = subprocess.run
        killed = []
        def run(*args, **kwargs):
            if not killed and "--decrypt" in args[0]:
                killed.append(True)
                return subprocess.CompletedProcess(args[0], -9, b"", b"")
            return original(*args, **kwargs)
        with patch("durable.artifacts.subprocess.run", side_effect=run):
            result = ex.run(si)
        self.assertEqual(result, done)
        self.assertTrue(killed)
        self.assertEqual(len(channel.started), 1)

    def test_local_stat_io_error_does_not_discard_completed_result(self):
        import errno
        from durable.artifacts import AgeSealer, local_store
        sealer, store = AgeSealer(), local_store(Path(self.tmp.name) / "flaky-stat")
        batch_key, case_key = self.keys.scope_key("b-t"), self.keys.scope_key("case-t-1")
        inputs, ciphertext = sealer.seal(batch_key, K.INPUTS, b"inputs")
        store.put_sealed("b-t", inputs, ciphertext)
        snapshot, ciphertext = sealer.seal(case_key, K.CASE_SNAPSHOT, b"snapshot")
        store.put_sealed("case-t-1", snapshot, ciphertext)
        si = StepInput("b-t", "case-t-1", 2, Step(StepKind.WRITER, 1), 1, P, B, inputs, snapshot, 600, 5_000_000)
        done = StepResult(Outcome.OK, "writer:pass", Usage(1, 300, 300), snapshot=snapshot)
        channel = Channel([Poll(PollState.DONE, done)])
        ex = Executor(self.pool, channel, self.ledger, store, sealer, self.keys,
                      poll_interval_s=10, grace_s=100, clock=self.clock, sleep=self.clock.sleep)
        target = store.objects._path(store.key("case-t-1", snapshot))
        original = Path.stat
        failed = []
        def stat(path, *args, **kwargs):
            if path == target and not failed:
                failed.append(True)
                raise OSError(errno.EIO, "simulated I/O failure")
            return original(path, *args, **kwargs)
        with patch.object(Path, "stat", stat):
            result = ex.run(si)
        self.assertEqual(result, done)
        self.assertTrue(failed)
        self.assertEqual(len(channel.started), 1)

    def test_history_is_a_case_scoped_diagnostic(self):
        history = [{"seq": 1, "step": "admit", "attempt": 1, "outcome": "ok", "reason": "admit:pass"}]
        ref = self.ex(None).seal_history("case-t-1", history)
        self.assertIs(ref.kind, K.DIAGNOSTIC)
        ct = self.store.get_sealed("case-t-1", ref)
        self.assertEqual(json.loads(self.sealer.open(self.keys.scope_key("case-t-1"), ref, ct)), history)
        with self.assertRaises(ValueError):
            self.sealer.open(self.keys.scope_key("b-t"), ref, ct)

    def test_inputs_keep_the_batch_scope_with_the_real_store(self):
        from durable.artifacts import AgeSealer, ArtifactError, local_store
        sealer, store = AgeSealer(), local_store(Path(self.tmp.name) / "real-store")
        inputs, ciphertext = sealer.seal(self.keys.scope_key("b-t"), K.INPUTS, b"public practice input")
        store.put_sealed("b-t", inputs, ciphertext)
        snapshot, ciphertext = sealer.seal(self.keys.scope_key("case-t-1"), K.CASE_SNAPSHOT, b"snapshot")
        store.put_sealed("case-t-1", snapshot, ciphertext)
        si = StepInput("b-t", "case-t-1", 2, Step(StepKind.WRITER, 1), 1, P, B,
                       inputs, snapshot, 600, 5_000_000)
        class Capture(Channel):
            def start(self, lease, step_input, keys, blobs):
                self.keys, self.blobs = keys, blobs
        cancelled = Poll(PollState.DONE, StepResult(Outcome.INFRA_ERROR, "infra:cancelled"))
        channel = Capture([Poll(PollState.ABSENT)], on_cancel=cancelled)
        ex = Executor(self.pool, channel, self.ledger, store, sealer, self.keys,
                      poll_interval_s=10, grace_s=100, clock=self.clock, sleep=self.clock.sleep)
        self.assertEqual(ex.run(si).reason, "infra:attempt_absent")
        self.assertEqual(set(channel.keys), {"case-t-1"})
        self.assertEqual(channel.blobs[blob_name(inputs)], store.get_sealed("b-t", inputs))
        with self.assertRaises(ArtifactError):
            sealer.open(channel.keys["case-t-1"], inputs, channel.blobs[blob_name(inputs)])
        with self.assertRaises(ArtifactError):
            store.get_sealed("case-t-1", inputs)


class Bucket:
    """The R2 bucket over HTTP, for the real R2Objects. `expired` keys answer 404, as objects the
    lifecycle rule expire-7d deleted do; `down` keys fail in transport."""

    def __init__(self):
        self.objects, self.expired, self.down = {}, set(), set()

    def __call__(self, method, url, headers, body):
        key = url.split("/bucket/", 1)[1]
        if key in self.down:
            raise OSError("connection reset by peer")
        if method == "PUT":
            self.objects[key] = body
            return 200, {}, b""
        if key in self.expired or key not in self.objects:
            return 404, {}, b""
        return 200, {"content-length": str(len(self.objects[key]))}, self.objects[key] if method == "GET" else b""


class ExpiredEvidence(Setup):
    """case-import-1bb2ad-2-1, b-import-1bb2ad-2r4, 16 November: the DIAGNOSIS step carried 18 evidence
    refs (17 from its 8 November attempts plus the engine's stop history), 12 of them expired from R2.
    The executor fetched no blobs, never started the worker, and the attempt ended infra:attempt_absent
    three times with 0 calls; the case was held for good."""

    def setUp(self):
        super().setUp()
        from durable.artifacts import AgeSealer, R2Objects, SealedStore
        self.bucket = Bucket()
        self.store = SealedStore(R2Objects("acct", "AKID", "secret", "bucket", transport=self.bucket))
        self.sealer = AgeSealer()
        self.inputs = self.put("b-t", K.INPUTS, b"inputs")
        self.snap = self.put("case-t-1", K.CASE_SNAPSHOT, b"snapshot")
        kinds = [K.GATE_RECEIPT, K.DIAGNOSTIC, K.DIAGNOSTIC] * 5 + [K.DIAGNOSIS_REPORT, K.DIAGNOSTIC]
        earlier = [self.put("case-t-1", kind, f"8 November attempt {i}".encode()) for i, kind in enumerate(kinds)]
        self.stops = [{"seq": 9, "step": "WRITER", "attempt": 1, "outcome": "infra_error", "reason": "infra:deadline"}]
        self.history = self.put("case-t-1", K.DIAGNOSTIC, json.dumps(self.stops).encode())
        self.evidence = (*earlier, self.history)
        self.gone = earlier[:12]
        for ref in self.gone:
            self.bucket.expired.add(self.store.key("case-t-1", ref))
        self.channel = self.Worker(self)

    class Worker(Channel):
        """A worker that answers ABSENT until started; a cancel of an attempt that never started
        answers infra:cancelled, as the production worker did."""

        def __init__(self, test):
            super().__init__([Poll(PollState.ABSENT)])
            self.test, self.frames = test, []

        def start(self, lease, si, keys, blobs):
            self.frames.append((si, keys, dict(blobs)))
            self.polls = [Poll(PollState.DONE, self.test.diagnosed())]

        def cancel(self, lease, si):
            if not self.frames:
                self.polls = [Poll(PollState.DONE, StepResult(Outcome.INFRA_ERROR, "infra:cancelled"))]

    def diagnosed(self):
        from durable.contract import Verdict
        report = self.put("case-t-1", K.DIAGNOSIS_REPORT, b'{"outcome":"factory_bug"}')
        return StepResult(Outcome.OK, "diagnosis:completed", Usage(1, 300, 300), snapshot=self.snap,
                          verdict=Verdict.FACTORY_BUG, report=report)

    def diagnosis(self):
        return StepInput("b-t", "case-t-1", 12, Step(StepKind.DIAGNOSIS), 1, P, B, self.inputs, self.snap,
                         600.0, 5_000_000, evidence=self.evidence)

    def run_it(self, si):
        return guarded_run(self.ex(self.channel), si)

    def test_expired_evidence_still_starts_the_diagnosis(self):
        si = self.diagnosis()
        result = self.run_it(si)
        self.assertEqual((result.outcome, result.reason), (Outcome.OK, "diagnosis:completed"))
        self.assertEqual(len(self.channel.frames), 1)
        sent, keys, blobs = self.channel.frames[0]
        self.assertEqual(sent.idempotency_key, si.idempotency_key)   # the same attempt: poll and replay match it
        self.assertEqual(sent.evidence[:-1], tuple(r for r in self.evidence if r not in self.gone))
        note = sent.evidence[-1]
        self.assertEqual(set(blobs), {blob_name(r) for r in (self.inputs, self.snap, *sent.evidence)})
        opened = [(r, self.sealer.open(keys["case-t-1"], r, blobs[blob_name(r)])) for r in sent.evidence]
        self.assertEqual(json.loads(opened[-1][1]), {"lost_evidence": {
            "reason": "artifact_missing", "count": 12, "kinds": {"diagnostic": 8, "receipt": 4}}})
        self.assertIs(note.kind, K.DIAGNOSTIC)
        from durable.steps.diagnosis import _history
        self.assertEqual(_history(opened), self.stops)   # the worker still finds the engine's stop history

    def test_a_missing_input_or_snapshot_still_fails(self):
        for ref, scope in ((self.inputs, "b-t"), (self.snap, "case-t-1")):
            with self.subTest(kind=ref.kind):
                self.bucket.expired = {self.store.key(scope, ref)}
                self.channel = self.Worker(self)
                self.assertEqual(self.run_it(self.diagnosis()).reason, "infra:attempt_absent")
                self.assertEqual(self.channel.frames, [])

    def test_an_expired_stop_history_still_fails(self):
        # The history is the last ref; without it diagnosis cannot reach its code-decided verdict.
        self.bucket.expired = {self.store.key("case-t-1", self.history)}
        self.assertEqual(self.run_it(self.diagnosis()).reason, "infra:attempt_absent")
        self.assertEqual(self.channel.frames, [])

    def test_a_store_outage_never_drops_evidence(self):
        self.bucket.expired = set()
        self.bucket.down = {self.store.key("case-t-1", self.evidence[3])}
        self.assertEqual(self.run_it(self.diagnosis()).reason, "infra:attempt_absent")
        self.assertEqual(self.channel.frames, [])
        self.bucket.down = set()
        self.channel = self.Worker(self)
        self.assertIs(self.run_it(self.diagnosis()).outcome, Outcome.OK)
        self.assertEqual(self.channel.frames[0][0].evidence, self.evidence)   # nothing lost, nothing noted


if __name__ == "__main__":
    unittest.main()
