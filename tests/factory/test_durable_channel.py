"""WP2 channel, control side of the wire protocol (docs/designs/durable-execution-wp2.md).

Runs against a worker the real pool provisioned through the stand-in Boat of
test_durable_workers.py (real saved Boat CLI outputs; `boat ssh` runs locally per worker
home), with the stand-in worker command written there from the contract docstring. The
ArtifactStore is a fake written from the contract protocol. Ciphertexts are opaque random
bytes: the channel never opens them.
"""
import base64
import json
import os
from pathlib import Path
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "tests/factory"), str(ROOT / "factory"), str(ROOT / "bin")]
os.environ.setdefault("BENCH", str(ROOT))

import test_durable_workers as support   # noqa: E402
from durable.contract import (ArtifactKind as K, ContractError, Outcome, PollState, Ref, Step, StepInput,  # noqa: E402
                              StepKind, StepResult, WorkerLease, attempt_paths, to_record)
from durable import workers as W   # noqa: E402
from durable.channel import BoatChannel, blob_name   # noqa: E402

CASE = support.CASE
BATCH = "b-wp2-test"


class FakeStore:
    """ArtifactStore from the protocol: ciphertext by (scope, Ref)."""

    def __init__(self):
        self.blobs = {}

    def put_sealed(self, scope, ref, ciphertext):
        self.blobs[(scope, ref)] = ciphertext

    def get_sealed(self, scope, ref):
        return self.blobs[(scope, ref)]

    def exists(self, scope, ref):
        return (scope, ref) in self.blobs


def digest(n):
    return format(n, "064x")


class ChannelTests(unittest.TestCase):
    def setUp(self):
        self.h = support.Harness(self)
        self.bench = self.h.benches["bench-env"]
        self.pool = self.h.pool()
        self.lease = self.pool.acquire(CASE, self.h.plumbing, self.bench)
        self.home = self.h.home(W.boat_id(self.lease.worker_id))
        self.store = FakeStore()
        self.channel = BoatChannel(self.store, boat=self.h.boat, command_timeout=20, blob_timeout=20)
        self.inputs = Ref(digest(1), K.INPUTS)
        self.snapshot = Ref(digest(2), K.CASE_SNAPSHOT)
        self.blobs = {blob_name(self.inputs): os.urandom(4096), blob_name(self.snapshot): os.urandom(70_000)}
        self.case_key, self.batch_key = os.urandom(32), os.urandom(32)

    def step(self, kind=StepKind.WRITER, seq=1, attempt=1, **kw):
        base = dict(batch_id=BATCH, case_id=CASE, seq=seq, step=Step(kind, 1 if kind.numbered else 0),
                    attempt=attempt, plumbing_version=self.h.plumbing, bench_version=self.bench, inputs=self.inputs,
                    snapshot=None if kind is StepKind.ADMIT else self.snapshot, deadline_s=60.0,
                    money_ceiling_usd_micros=1_000_000)
        if kind is StepKind.ADMIT:
            base["registry"] = Ref(digest(3), K.STATEMENT_REGISTRY)
        return StepInput(**{**base, **kw})

    def plan(self, step_input, result, outputs=None, sleep=0.0):
        path = self.home / "standin-plan.json"
        plans = json.loads(path.read_text()) if path.exists() else {}
        plans[step_input.idempotency_key] = {"sleep": sleep, "result": to_record(result),
                                             "outputs": {blob_name(r): base64.b64encode(b).decode()
                                                         for r, b in (outputs or {}).items()}}
        path.write_text(json.dumps(plans))

    def start(self, step_input, blobs=None, keys=None):
        self.channel.start(self.lease, step_input, keys or {CASE: self.case_key}, self.blobs if blobs is None else blobs)

    def until(self, step_input, state, timeout=30.0):
        end = time.monotonic() + timeout
        while True:
            poll = self.channel.poll(self.lease, step_input)
            if poll.state is state or time.monotonic() > end:
                return poll
            time.sleep(0.2)

    def test_start_then_running_then_done_with_outputs_in_the_store(self):
        si = self.step()
        after = Ref(digest(10), K.CASE_SNAPSHOT)
        after_bytes = os.urandom(200_000)
        self.plan(si, StepResult(Outcome.OK, "writer:done", snapshot=after), {after: after_bytes}, sleep=2)
        self.start(si)
        for name, data in self.blobs.items():
            self.assertEqual((self.home / "durable/blobs" / name).read_bytes(), data)
        self.assertEqual(self.channel.poll(self.lease, si).state, PollState.RUNNING)
        self.assertFalse(self.store.blobs)
        poll = self.until(si, PollState.DONE)
        self.assertEqual(poll.state, PollState.DONE)
        self.assertEqual(poll.result, StepResult(Outcome.OK, "writer:done", snapshot=after))
        self.assertEqual(self.store.get_sealed(CASE, after), after_bytes)
        attempt = self.home / attempt_paths(si.idempotency_key)["attempt"]
        self.assertEqual(json.loads((attempt / "keys-seen.json").read_text()), [CASE])
        before = len(self.h.calls())
        self.assertEqual(self.channel.poll(self.lease, si), poll)
        self.assertEqual(len(self.h.calls()), before + 1)   # stored outputs are not fetched again

    def test_admit_registry_goes_to_the_batch_scope(self):
        si = self.step(StepKind.ADMIT)
        registry, snap = Ref(digest(20), K.STATEMENT_REGISTRY), Ref(digest(21), K.CASE_SNAPSHOT)
        self.plan(si, StepResult(Outcome.OK, "admit:done", snapshot=snap, registry=registry),
                  {registry: b"registry-ciphertext", snap: b"snapshot-ciphertext"})
        blobs = {blob_name(self.inputs): b"inputs", blob_name(si.registry): b"old-registry"}
        self.start(si, blobs, {CASE: self.case_key, BATCH: self.batch_key})
        poll = self.until(si, PollState.DONE)
        self.assertEqual(poll.result.registry, registry)
        self.assertEqual(self.store.get_sealed(BATCH, registry), b"registry-ciphertext")
        self.assertEqual(self.store.get_sealed(CASE, snap), b"snapshot-ciphertext")
        self.assertFalse(self.store.exists(CASE, registry))

    def test_keys_travel_only_in_the_start_frame(self):
        si = self.step(StepKind.ADMIT)
        self.plan(si, StepResult(Outcome.INFRA_ERROR, "infra:test_stop"))
        self.start(si, {blob_name(self.inputs): b"x", blob_name(si.registry): b"y"},
                   {CASE: self.case_key, BATCH: self.batch_key})
        self.until(si, PollState.DONE)
        argv = json.dumps(self.h.calls())
        for key in (self.case_key, self.batch_key):
            self.assertNotIn(base64.b64encode(key).decode(), argv)
            self.assertNotIn(key.hex(), argv)
        frames = [c for c in self.h.calls() if c[0] == "ssh" and c[2].endswith("worker_step.py start")]
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0][2], "cd ~/factory-release && exec python3 -B factory/durable/worker_step.py start")

    def test_a_second_start_does_nothing(self):
        si = self.step()
        snap = Ref(digest(30), K.CASE_SNAPSHOT)
        self.plan(si, StepResult(Outcome.OK, "writer:done", snapshot=snap), {snap: b"s"})
        self.start(si)
        first = self.until(si, PollState.DONE)
        self.plan(si, StepResult(Outcome.INFRA_ERROR, "infra:second_run"))
        self.start(si)
        time.sleep(0.5)
        self.assertEqual(self.channel.poll(self.lease, si), first)

    def test_transport_failures_are_running_never_absent(self):
        si = self.step()
        snap = Ref(digest(40), K.CASE_SNAPSHOT)
        self.plan(si, StepResult(Outcome.OK, "writer:done", snapshot=snap), {snap: b"s"})
        self.start(si)
        self.assertEqual(self.until(si, PollState.DONE).state, PollState.DONE)
        self.store.blobs.clear()
        for flag in ("ssh-fail", "ssh-exit", "ssh-garbage", "ssh-extra"):
            self.h.flag(flag, "worker_step.py poll")
            self.assertEqual(self.channel.poll(self.lease, si).state, PollState.RUNNING, flag)
            self.h.flag(flag, None)
        self.h.flag("ssh-hang", "worker_step.py poll")
        slow = BoatChannel(self.store, boat=self.h.boat, command_timeout=2)
        self.assertEqual(slow.poll(self.lease, si).state, PollState.RUNNING)
        self.h.flag("ssh-hang", None)
        gone = WorkerLease("bx-z4wktrbn", CASE)   # a worker the provider does not know
        self.assertEqual(self.channel.poll(gone, si).state, PollState.RUNNING)
        self.assertFalse(self.store.blobs)
        self.assertEqual(self.channel.poll(self.lease, si).state, PollState.DONE)

    def test_absent_only_from_an_answering_worker(self):
        self.assertEqual(self.channel.poll(self.lease, self.step(seq=9)).state, PollState.ABSENT)

    def test_done_is_held_back_until_every_output_is_stored(self):
        si = self.step()
        snap, receipt = Ref(digest(50), K.CASE_SNAPSHOT), Ref(digest(51), K.GATE_RECEIPT)
        result = StepResult(Outcome.OK, "writer:done", snapshot=snap, receipt=receipt)
        self.plan(si, result, {snap: b"snapshot bytes"})   # the receipt blob is missing
        self.start(si)
        time.sleep(1)
        self.assertEqual(self.channel.poll(self.lease, si).state, PollState.RUNNING)
        out = self.home / attempt_paths(si.idempotency_key)["out"]
        (out / blob_name(receipt)).write_bytes(b"receipt bytes")
        self.h.flag("ssh-truncate", "sha256sum <")
        self.assertEqual(self.channel.poll(self.lease, si).state, PollState.RUNNING)
        self.assertFalse(self.store.exists(CASE, receipt))
        self.h.flag("ssh-truncate", None)
        poll = self.channel.poll(self.lease, si)
        self.assertEqual(poll.result, result)
        self.assertEqual(self.store.get_sealed(CASE, receipt), b"receipt bytes")
        self.assertEqual(self.store.get_sealed(CASE, snap), b"snapshot bytes")

    def test_cancel_stops_a_live_attempt_and_tombstones_an_unstarted_one(self):
        si = self.step()
        self.plan(si, StepResult(Outcome.OK, "writer:done", snapshot=self.snapshot), sleep=60)
        self.start(si)
        self.assertEqual(self.channel.poll(self.lease, si).state, PollState.RUNNING)
        pid = int((self.home / attempt_paths(si.idempotency_key)["attempt"] / "pid").read_text())
        self.channel.cancel(self.lease, si)
        poll = self.channel.poll(self.lease, si)
        self.assertEqual(poll.result, StepResult(Outcome.INFRA_ERROR, "infra:cancelled"))
        time.sleep(0.3)
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] if Path(f"/proc/{pid}").exists() else "gone"
        self.assertIn(state, ("Z", "gone"))
        late = self.step(attempt=2)
        self.channel.cancel(self.lease, late)
        self.plan(late, StepResult(Outcome.OK, "writer:done", snapshot=self.snapshot))
        self.start(late)
        self.assertEqual(self.channel.poll(self.lease, late).result, StepResult(Outcome.INFRA_ERROR, "infra:cancelled"))

    def test_a_second_live_attempt_of_the_case_is_busy(self):
        first, second = self.step(), self.step(seq=2)
        self.plan(first, StepResult(Outcome.OK, "writer:done", snapshot=self.snapshot), sleep=60)
        self.plan(second, StepResult(Outcome.OK, "writer:done", snapshot=self.snapshot))
        self.start(first)
        self.start(second)
        self.assertEqual(self.channel.poll(self.lease, second).result,
                         StepResult(Outcome.INFRA_ERROR, "infra:attempt_busy"))
        self.assertEqual(self.channel.poll(self.lease, first).state, PollState.RUNNING)
        self.channel.cancel(self.lease, first)

    def test_a_failed_blob_push_sends_no_frame(self):
        si = self.step()
        self.h.flag("ssh-fail", "durable/blobs")
        self.start(si)
        self.assertFalse([c for c in self.h.calls() if c[0] == "ssh" and "worker_step.py start" in c[2]])
        self.h.flag("ssh-fail", None)
        self.assertEqual(self.channel.poll(self.lease, si).state, PollState.ABSENT)
        self.h.flag("ssh-corrupt", "durable/blobs")
        self.start(si)
        self.assertFalse(list((self.home / "durable/blobs").glob("*")))
        self.assertEqual(self.channel.poll(self.lease, si).state, PollState.ABSENT)

    def test_nothing_raises_when_boat_itself_is_broken(self):
        env = {**self.h.env, "BOAT_CMD": str(self.h.tmp / "no-such-boat")}
        broken = BoatChannel(self.store, boat=W.BoatCli(env=env), command_timeout=5)
        si = self.step()
        broken.start(self.lease, si, {CASE: self.case_key}, self.blobs)
        self.assertEqual(broken.poll(self.lease, si).state, PollState.RUNNING)
        broken.cancel(self.lease, si)

    def test_bad_caller_input_is_refused_before_any_transport(self):
        si = self.step()
        before = len(self.h.calls())
        with self.assertRaises(ContractError):
            self.channel.start(self.lease, si, {CASE: self.case_key}, {"../../etc/passwd": b"x"})
        with self.assertRaises(ContractError):
            self.channel.start(self.lease, si, {CASE: self.case_key, "case-other": os.urandom(32)}, {})
        with self.assertRaises(ContractError):
            self.channel.poll(WorkerLease(self.lease.worker_id, "case-other"), si)
        self.assertEqual(len(self.h.calls()), before)


if __name__ == "__main__":
    unittest.main()
