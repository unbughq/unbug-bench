"""WP5a: the worker side of the durable wire protocol and the run.py engine hooks.

Real artifacts: the public practice case (run.build_fixture), real bin/ tooling for G1,
the real `age` CLI, the real e15450 ledger (spent $52.79) from
fixtures/router-paid-deepseek.json.gz, and the real budget.run_budgeted. The model CLI is
a local process that prints one priced step_finish event (no provider is called), and
the bench preparation (Docker) is replaced only where a test says so.

Stand-ins written here from the contract protocols: AgeCliSealer (contract.Sealer, the
real age CLI; WP3's AgeSealer replaces it) and classify (contract.Classifier; WP4's
classify replaces it). Design: docs/designs/durable-execution-wp5a.md.
"""
import sys
from pathlib import Path as _TestPath
_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_ROOT / "factory"), str(_ROOT / "bin"), str(_TestPath(__file__).resolve().parent)]

import base64
import gzip
import hashlib
import io
import json
import os
import pathlib
import shutil
import signal
import subprocess
import tarfile
import tempfile
import threading
import time
import types
import unittest
import uuid
from unittest.mock import patch

import budget
import model_runtime
import model_router
import run
from durable import worker_step
from durable import contract as k
from durable.contract import (ArtifactKind, Outcome, PollState, Ref, Step, StepInput, StepKind, attempt_id,
                              attempt_paths, derive_keys, artifact_digest, key_frame, poll_from_record, start_frame)

REPO = _ROOT
FIXTURES = _TestPath(__file__).resolve().parent / "fixtures"
PLUMBING = hashlib.sha256(b"wp5a plumbing release").hexdigest()
BENCH_V = hashlib.sha256(b"wp5a bench release").hexdigest()
CASE = "case-wp5a-practice"
BATCH = "b-wp5a"
E15450 = next(card for card in json.loads(gzip.decompress((FIXTURES / "router-paid-deepseek.json.gz").read_bytes()))
              if card["case"].endswith("e15450"))


def docker_available():
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


DOCKER = docker_available()
NO_DOCKER = "needs a Docker host: the step builds the Medusa shop (G3 / bench preparation)"


# ---- stand-ins from the contract protocols ---------------------------------------------------

_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def _bech32(hrp, data):
    acc = bits = 0
    five = []
    for value in data:
        acc, bits = (acc << 8) | value, bits + 8
        while bits >= 5:
            bits -= 5
            five.append((acc >> bits) & 31)
    if bits: five.append((acc << (5 - bits)) & 31)
    def polymod(values):
        gen, chk = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3), 1
        for v in values:
            top, chk = chk >> 25, (chk & 0x1FFFFFF) << 5 ^ v
            for i in range(5):
                if (top >> i) & 1: chk ^= gen[i]
        return chk
    expanded = [ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp]
    pm = polymod(expanded + five + [0] * 6) ^ 1
    return hrp + "1" + "".join(_CHARSET[d] for d in five + [(pm >> 5 * (5 - i)) & 31 for i in range(6)])


class AgeCliSealer:
    """contract.Sealer with the real age CLI and derive_keys."""
    def _age(self, args, secret, data):
        with tempfile.TemporaryDirectory() as tmp:
            identity = pathlib.Path(tmp) / "identity"
            identity.write_text(_bech32("age-secret-key-", secret).upper() + "\n")
            done = subprocess.run(["age", *args, "-i", str(identity)], input=data, capture_output=True)
        if done.returncode: raise ValueError("age failed")
        return done.stdout

    def seal(self, scope_key, kind, plaintext):
        secret, mac = derive_keys(scope_key)
        return Ref(artifact_digest(mac, plaintext), ArtifactKind(kind)), self._age(["-e"], secret, plaintext)

    def open(self, scope_key, ref, ciphertext):
        secret, mac = derive_keys(scope_key)
        plaintext = self._age(["-d"], secret, ciphertext)
        if artifact_digest(mac, plaintext) != ref.digest: raise ValueError("digest mismatch")
        return plaintext


def classify(stop, *, step, now):
    """contract.Classifier stand-in: the stops these tests produce."""
    stage = {StepKind.GATES: "engine"}.get(StepKind(step), StepKind(step).value)
    head = stop.replace("Budget stopped: ", "").split(":", 1)[0]
    if head in ("budget_exhausted", "cost_limit"):
        return k.Classified(Outcome.EXHAUSTED, stage + ":money")
    if head in ("provider_limit", "provider_wait"):
        return k.Classified(Outcome.PROVIDER_LIMIT, "router:provider_limit", retry_at=now + 900)
    if head == "timeout":
        return k.Classified(Outcome.INFRA_ERROR, "infra:timeout")
    return k.Classified(Outcome.INFRA_ERROR, "infra:unclassified_stop")


# ---- the model and Docker boundaries -----------------------------------------------------------

def stub_model(behaviour, record=None):
    """Replace run.opencode at the model boundary. Each call passes the runtime's first check
    (case_budget_boundary) and books one priced event through the real run_budgeted."""
    def call(c, models, text, cwd, name, user=None, timeout=None, deadline=None, **kw):
        if run.under_engine(c): timeout, deadline = run.engine_call_window(c, timeout, deadline)
        role = "builder" if name.startswith("builder") else "attacker" if name.startswith("attacker") else "other"
        cfg = behaviour.get(role, {})
        if record is not None:
            with open(record, "a") as f: f.write(json.dumps({"name": name, "timeout": timeout, "text": text}) + "\n")
        model = models[0]
        model_runtime.case_budget_boundary(c, model)
        if role == "builder":
            aside = c.work / "stub-case.json"
            if cfg.get("break_first") and not aside.exists():
                shutil.move(c.case / "case.json", aside)
            elif aside.exists():
                shutil.move(aside, c.case / "case.json")
            if cfg.get("edit", True):
                with open(c.case / "BUILD-NOTES.md", "a") as f: f.write(f"{name}\n")
        if role == "attacker":
            category = json.loads(text.split('CATEGORY MODE (overrides whole-review completion instructions):\n')[1].split('\n')[0])
            pathlib.Path(category['category_output']).write_text(json.dumps({
                "category": category['category'], "category_complete": True,
                "completed_subchecks": category['required_subchecks'], "blocking": cfg.get("blocking", []),
                "unfinished_validation": [], "non_blocking": [], "freshness_review": [], "cheats_tried": []}))
        event = {"type": "step_finish", "sessionID": "s", "part": {
            "id": uuid.uuid4().hex, "messageID": uuid.uuid4().hex, "cost": cfg.get("cost", 0.25), "reason": "stop",
            "tokens": {"input": 10, "output": 20, "reasoning": 0, "cache": {"read": 0, "write": 0}}}}
        sleep = cfg.get("sleep_second", 0) if "-fix-" in name else cfg.get("sleep", 0)
        code = f"import time\ntime.sleep({sleep})\nprint({json.dumps(json.dumps(event))}, flush=True)\n"
        result = budget.run_budgeted([sys.executable, "-c", code], cwd, os.environ.copy(),
            c.work / "transcripts" / f"{name}.jsonl", c.ledger, timeout or c.args.agent_timeout,
            max_cost=c.args.max_cost, max_calls=c.args.max_role_calls, max_total_calls=c.args.max_total_calls,
            driver="opencode", progress_timeout=c.args.no_progress_minutes * 60,
            max_zero_tokens=c.args.max_zero_tokens, configured_model=model,
            concurrent=c.args.concurrent_roles, case_budget=c.args.case_budget,
            role=budget.invocation_role(name), invocation_name=name, containment=False)
        if kw.get("on_complete"):
            c.model_lease = types.SimpleNamespace(route=model)
            kw["on_complete"]()
        return result
    return call


def cli(argv):
    """The worker command with this file's stand-in seams; WP5A_STUB sets the boundaries."""
    stub = json.loads(os.environ.get("WP5A_STUB", "{}"))
    home = pathlib.Path.home()
    if stub.get("bench") == "skip":
        def prepare(c):
            with open(home / "prepare-bench.log", "a") as f: f.write(c.engine.key + "\n")
        run.engine_prepare_bench = prepare
    if "model" in stub:
        run.opencode = stub_model(stub["model"], home / "model-calls.jsonl")
    worker = worker_step.Worker(sealer=AgeCliSealer(), classifier=classify)
    return worker_step.main(argv, worker=worker)


WRAPPER = ("import sys; sys.path[:0] = [%r]; import test_durable_worker_step as t; sys.exit(t.cli(sys.argv[1:]))"
           % str(_TestPath(__file__).resolve().parent))


# ---- a worker home with the practice case ------------------------------------------------------

def practice_card(case_id, **more):
    card = {"case": case_id, "dry_run": True, "source": "fixture (dry-run)", "seed": 7, "gates": {},
            "failed_gate": None, "models": E15450["models"], "roles": E15450["roles"], "factory_slots_prepared": 1,
            "recovery_config": {**{key: E15450["recovery_config"][key] for key in (
                "agent_timeout", "calibrator_minutes", "max_role_calls", "max_total_calls", "max_zero_tokens",
                "no_progress_minutes", "pilot_runs", "pilot_tries")}, "rounds": 3, "runs": 1, "scenario_runs": 1}}
    card.update(more)
    return card


def practice_tree(root, case_id, *, ledger=None, extra=(), card=None):
    """The work tree ADMIT would hand over: the practice case laid out by run.build_fixture."""
    work = pathlib.Path(root) / case_id
    run.build_fixture(types.SimpleNamespace(case=work / "case"))
    (work / "logs").mkdir()
    (work / "scorecard.json").write_text(json.dumps(card or practice_card(case_id)))
    (work / "continuation-budget.json").write_text(json.dumps(ledger if ledger is not None else {"calls": 0, "events": [], "cost": 0}))
    for name in extra:
        path = work / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("legacy lifecycle file")
    return work


def tar_tree(work):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for path in sorted(work.iterdir()): tar.add(path, arcname=path.name)
    return buffer.getvalue()


def members(snapshot):
    with tarfile.open(fileobj=io.BytesIO(snapshot), mode="r:*") as tar:
        return {m.name.split("/", 1)[0] for m in tar.getmembers()}, tar


class WorkerHome:
    def __init__(self, test, case_id=CASE):
        self.tmp = tempfile.TemporaryDirectory(); test.addCleanup(self.tmp.cleanup)
        self.home = pathlib.Path(self.tmp.name)
        self.case_id = case_id
        self.sealer = AgeCliSealer()
        self.case_key, self.batch_key = os.urandom(32), os.urandom(32)
        self.release = self.home / k.RELEASE_ROOT
        self.release.mkdir()
        self.write_release(PLUMBING, BENCH_V)
        (self.home / k.WORKER_ROOT / "blobs").mkdir(parents=True)
        test.addCleanup(self.kill_all)

    def write_release(self, plumbing, bench):
        (self.home / k.RELEASE_MANIFEST).write_text(json.dumps({"plumbing_version": plumbing, "bench_version": bench}))

    def env(self, stub=None):
        return {**os.environ, "HOME": str(self.home), "BENCH": str(REPO), "WP5A_STUB": json.dumps(stub or {})}

    def push(self, kind, plaintext, key=None):
        ref, ciphertext = self.sealer.seal(key or self.case_key, kind, plaintext)
        (self.home / k.WORKER_ROOT / "blobs" / worker_step.blob_name(ref)).write_bytes(ciphertext)
        return ref

    def push_practice(self, **kw):
        with tempfile.TemporaryDirectory() as tmp:
            return self.push(ArtifactKind.CASE_SNAPSHOT, tar_tree(practice_tree(tmp, self.case_id, **kw)))

    def step(self, kind, round=0, *, seq=1, attempt=1, snapshot=None, ceiling=20_000_000, deadline=600.0,
             feedback=None, registry=None):
        return StepInput(BATCH, self.case_id, seq, Step(kind, round), attempt, PLUMBING, BENCH_V,
                         Ref("1" * 64, ArtifactKind.INPUTS), snapshot, deadline, ceiling, feedback=feedback,
                         registry=registry)

    def keys(self, step_input):
        keys = {self.case_id: self.case_key}
        if step_input.step.kind is StepKind.ADMIT: keys[BATCH] = self.batch_key
        return keys

    def start(self, step_input, stub=None, *, real=False, frame=None):
        frame = frame if frame is not None else start_frame(step_input, self.keys(step_input))
        command = ([sys.executable, "-B", str(REPO / "factory/durable/worker_step.py")] if real
                   else [sys.executable, "-B", "-c", WRAPPER])
        return subprocess.run(command + ["start"], input=json.dumps(frame).encode(), env=self.env(stub),
                              cwd=self.release, capture_output=True, timeout=120)

    def command(self, verb, key, frame=None):
        frame = key_frame(key) if frame is None else frame
        return subprocess.run([sys.executable, "-B", str(REPO / "factory/durable/worker_step.py"), verb],
                              input=json.dumps(frame).encode(), env=self.env(), cwd=self.release,
                              capture_output=True, timeout=120)

    def poll(self, step_input):
        done = self.command("poll", step_input.idempotency_key)
        assert done.returncode == 0, done.stderr.decode()
        return poll_from_record(json.loads(done.stdout))

    def wait(self, step_input, timeout=240):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            polled = self.poll(step_input)
            if polled.state is PollState.DONE: return polled.result
            time.sleep(0.3)
        raise AssertionError("attempt did not finish: " + self.log(step_input))

    def log(self, step_input):
        path = self.home / attempt_paths(step_input.idempotency_key)["attempt"] / "supervisor.log"
        return path.read_text() if path.exists() else "(no supervisor log)"

    def output(self, step_input, ref):
        path = self.home / attempt_paths(step_input.idempotency_key)["out"] / worker_step.blob_name(ref)
        return self.sealer.open(self.case_key, ref, path.read_bytes())

    def processes(self, step_input):
        return worker_step.Worker(self.home).processes(step_input.idempotency_key)

    def kill_all(self):
        worker = worker_step.Worker(self.home)
        attempts = self.home / k.WORKER_ROOT / "cases"
        for entry in attempts.rglob("*") if attempts.exists() else ():
            if entry.is_file(): worker.stop(entry.read_text())


# ---- the wire protocol -------------------------------------------------------------------------

@unittest.skipUnless(sys.platform == "linux", "worker process tracking requires Linux /proc")
class WireProtocolTests(unittest.TestCase):
    def test_practice_admit_through_the_real_worker_command(self):
        from dataclasses import replace
        h = WorkerHome(self)
        inputs = h.push(ArtifactKind.INPUTS, json.dumps({"version": 1, "dry_run": True, "seed": 7}).encode(), h.batch_key)
        registry = h.push(ArtifactKind.STATEMENT_REGISTRY, b"", h.batch_key)
        si = replace(h.step(StepKind.ADMIT, registry=registry), inputs=inputs)
        done = h.start(si, real=True)
        self.assertEqual((done.returncode, done.stdout), (0, b""), done.stderr)
        result = h.wait(si)
        self.assertEqual((result.outcome, result.reason), (Outcome.OK, "admit:practice"))
        self.assertIsNotNone(result.snapshot)
        self.assertIsNotNone(result.registry)
        self.assertEqual(result.usage.calls, 0)
        self.assertTrue(k.REASON.fullmatch(result.reason))

    def test_release_check(self):
        h = WorkerHome(self)
        snapshot = h.push_practice()
        h.write_release(PLUMBING, hashlib.sha256(b"another bench").hexdigest())
        si = h.step(StepKind.WRITER, 1, snapshot=snapshot)
        h.start(si, {"bench": "skip", "model": {}})
        self.assertEqual(h.wait(si).reason, "infra:version_mismatch")
        (h.home / k.RELEASE_MANIFEST).write_text(json.dumps({"plumbing_version": PLUMBING}))
        si = h.step(StepKind.WRITER, 1, snapshot=snapshot, attempt=2)
        h.start(si, {"bench": "skip", "model": {}})
        self.assertEqual(h.wait(si).reason, "infra:release_unreadable")
        self.assertFalse((h.home / "model-calls.jsonl").exists())

    def test_bad_frames(self):
        h = WorkerHome(self)
        si = h.step(StepKind.WRITER, 1, snapshot=h.push_practice())
        self.assertNotEqual(h.start(si, frame={"input": {"case_id": CASE}, "keys": {}}).returncode, 0)
        frame = start_frame(si, h.keys(si)); frame["keys"][CASE] = base64.b64encode(b"short").decode()
        self.assertEqual(h.start(si, frame=frame).returncode, 0)
        self.assertEqual(h.wait(si).reason, "infra:bad_frame")
        self.assertNotEqual(h.command("poll", None, {"key": "../x/y/z"}).returncode, 0)
        self.assertNotEqual(h.command("cancel", None, {"key": "case-a/1", "extra": 1}).returncode, 0)

    def test_absent_unknown_and_lost_attempts(self):
        h = WorkerHome(self)
        si = h.step(StepKind.WRITER, 1, snapshot=h.push_practice())
        self.assertIs(h.poll(si).state, PollState.ABSENT)
        (h.home / attempt_paths(si.idempotency_key)["attempt"]).mkdir(parents=True)  # marker, no unit, no result
        self.assertIs(h.poll(si).state, PollState.ABSENT)

    def test_detach_busy_repeat_and_first_wins(self):
        h = WorkerHome(self)
        snapshot = h.push_practice()
        stub = {"bench": "skip", "model": {"builder": {"sleep": 6}}}
        first = h.step(StepKind.WRITER, 1, snapshot=snapshot)
        began = time.monotonic()
        self.assertEqual(h.start(first, stub).returncode, 0)
        self.assertLess(time.monotonic() - began, 5, "start must return once the attempt is detached")
        self.assertIs(h.poll(first).state, PollState.RUNNING)
        self.assertTrue(h.processes(first))
        second = h.step(StepKind.WRITER, 1, snapshot=snapshot, attempt=2)
        self.assertEqual(h.start(second, stub).returncode, 0)
        self.assertEqual(h.wait(second, 30).reason, "infra:attempt_busy")
        self.assertEqual(h.start(first, stub).returncode, 0)      # repeated start: nothing happens
        result = h.wait(first)
        self.assertEqual((result.outcome, result.reason), (Outcome.OK, "writer:validated"), h.log(first))
        self.assertEqual(len((h.home / "model-calls.jsonl").read_text().splitlines()), 1)
        h.command("cancel", first.idempotency_key)                 # a cancel after DONE keeps the result
        self.assertIs(h.wait(first).outcome, Outcome.OK)
        third = h.step(StepKind.WRITER, 1, snapshot=snapshot, attempt=3)
        h.start(third, {"bench": "skip", "model": {}})
        self.assertIs(h.wait(third).outcome, Outcome.OK)          # a finished unit is not live

    def test_concurrent_starts_of_one_case_admit_one(self):
        h = WorkerHome(self)
        snapshot = h.push_practice()
        stub = {"bench": "skip", "model": {"builder": {"sleep": 8}}}
        steps = [h.step(StepKind.WRITER, 1, snapshot=snapshot, attempt=n) for n in (1, 2, 3)]
        threads = [threading.Thread(target=h.start, args=(si, stub)) for si in steps]
        for t in threads: t.start()
        for t in threads: t.join()
        reasons = sorted(h.wait(si).reason for si in steps)
        self.assertEqual(reasons, ["infra:attempt_busy", "infra:attempt_busy", "writer:validated"])

    def test_cancel_kills_and_tombstones(self):
        h = WorkerHome(self)
        snapshot = h.push_practice()
        live = h.step(StepKind.WRITER, 1, snapshot=snapshot)
        h.start(live, {"bench": "skip", "model": {"builder": {"sleep": 60}}})
        end = time.monotonic() + 30
        while not (h.home / "model-calls.jsonl").exists() and time.monotonic() < end: time.sleep(0.2)
        self.assertEqual(h.command("cancel", live.idempotency_key).returncode, 0)
        self.assertEqual(h.poll(live).result.reason, "infra:cancelled")
        self.assertFalse(h.processes(live), "cancel left processes of the attempt")
        time.sleep(1)
        self.assertEqual(h.poll(live).result.reason, "infra:cancelled")
        late = h.step(StepKind.WRITER, 1, snapshot=snapshot, attempt=2)
        h.command("cancel", late.idempotency_key)                  # never started: a tombstone
        h.start(late, {"bench": "skip", "model": {}})
        self.assertEqual(h.poll(late).result.reason, "infra:cancelled")
        self.assertEqual(len((h.home / "model-calls.jsonl").read_text().splitlines()), 1)
        after = h.step(StepKind.WRITER, 1, snapshot=snapshot, attempt=3)
        h.start(after, {"bench": "skip", "model": {}})
        self.assertIs(h.wait(after).outcome, Outcome.OK)

    def test_deadline_kills_the_attempt(self):
        h = WorkerHome(self)
        si = h.step(StepKind.WRITER, 1, snapshot=h.push_practice(), deadline=6.0)
        h.start(si, {"bench": "skip", "model": {"builder": {"sleep": 60}}})
        result = h.wait(si, 60)
        self.assertIn(result.reason, ("infra:deadline", "infra:timeout"))
        self.assertFalse(h.processes(si))

    def test_killed_attempt_reports_its_usage_so_far(self):
        h = WorkerHome(self)
        si = h.step(StepKind.WRITER, 1, snapshot=h.push_practice(), deadline=600.0)
        # The first call books $1 and breaks G1; the repair call hangs until the cancel.
        h.start(si, {"bench": "skip", "model": {"builder": {"cost": 1.0, "break_first": True, "sleep_second": 60}}})
        end = time.monotonic() + 60
        while time.monotonic() < end and len((h.home / "model-calls.jsonl").read_text().splitlines()
                                             if (h.home / "model-calls.jsonl").exists() else []) < 2:
            time.sleep(0.2)
        h.command("cancel", si.idempotency_key)
        result = h.poll(si).result
        self.assertEqual(result.reason, "infra:cancelled")
        self.assertEqual((result.usage.calls, result.usage.paid_usd_micros), (1, 1_000_000))

    def test_first_wins_result_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            worker = worker_step.Worker(tmp)
            key = f"{CASE}/1/writer:1/1"
            self.assertTrue(worker.write_result(key, k.StepResult(Outcome.INFRA_ERROR, "infra:cancelled")))
            self.assertFalse(worker.write_result(key, k.StepResult(Outcome.INFRA_ERROR, "infra:deadline")))
            self.assertEqual(worker.read_result(key).reason, "infra:cancelled")
            self.assertEqual(sorted(p.name for p in (pathlib.Path(tmp) / "durable/results").iterdir()),
                             [attempt_id(key) + ".json"])


# ---- the steps on the practice case --------------------------------------------------------------

@unittest.skipUnless(sys.platform == "linux", "worker process tracking requires Linux /proc")
class StepTests(unittest.TestCase):
    def test_writer_round_runs_on_a_case_past_its_own_money(self):
        """Done when: a snapshot with spent >= $50 and a $20 ceiling still runs a writer round."""
        ledger = E15450["continuation_budget"]
        spent = budget.case_spending(ledger)["spent_usd"]
        self.assertGreaterEqual(spent, 50)
        with self.assertRaises(budget.BudgetError):   # today's in-process $50 case budget would refuse it
            budget.require_case_budget(ledger, 50.0)
        h = WorkerHome(self)
        si = h.step(StepKind.WRITER, 1, snapshot=h.push_practice(ledger=ledger), ceiling=20_000_000)
        h.start(si, {"bench": "skip", "model": {"builder": {"cost": 3.0}}})
        result = h.wait(si)
        self.assertEqual((result.outcome, result.reason), (Outcome.OK, "writer:validated"), h.log(si))
        self.assertEqual((result.usage.calls, result.usage.paid_usd_micros), (1, 3_000_000))
        self.assertTrue((h.home / "prepare-bench.log").read_text().strip())
        with tempfile.TemporaryDirectory() as tmp:
            worker_step.restore(h.output(si, result.snapshot), tmp)
            after = json.loads((pathlib.Path(tmp) / "continuation-budget.json").read_text())
            self.assertAlmostEqual(budget.case_spending(after)["spent_usd"], spent + 3.0, places=6)
            card = json.loads((pathlib.Path(tmp) / "scorecard.json").read_text())
            self.assertEqual(card["builder_rounds"], 1)
            self.assertEqual(card["case_budget"]["limit_usd"], round(spent + 20.0, 9))
            self.assertIn("builder-1", (pathlib.Path(tmp) / "case/BUILD-NOTES.md").read_text())

    def test_ceiling_refuses_the_next_call(self):
        h = WorkerHome(self)
        snapshot = h.push_practice(ledger=E15450["continuation_budget"])
        si = h.step(StepKind.WRITER, 1, snapshot=snapshot, ceiling=2_000_000)
        h.start(si, {"bench": "skip", "model": {"builder": {"cost": 3.0, "break_first": True}}})
        result = h.wait(si)
        self.assertEqual((result.outcome, result.reason), (Outcome.EXHAUSTED, "writer:money"), h.log(si))
        self.assertEqual((result.usage.calls, result.usage.paid_usd_micros), (1, 3_000_000))
        self.assertIsNotNone(result.snapshot)
        self.assertIn("budget_exhausted", json.loads(h.output(si, result.diagnostic))["stop"])

    def test_g1_failure_goes_back_to_the_writer_within_the_round(self):
        h = WorkerHome(self)
        si = h.step(StepKind.WRITER, 1, snapshot=h.push_practice())
        h.start(si, {"bench": "skip", "model": {"builder": {"break_first": True}}})
        self.assertEqual(h.wait(si).reason, "writer:validated", h.log(si))
        calls = [json.loads(l) for l in (h.home / "model-calls.jsonl").read_text().splitlines()]
        self.assertEqual([c["name"] for c in calls], ["builder-1", "builder-1-fix-1"])
        self.assertIn("case.json", calls[1]["text"])     # the G1 problems reach the writer

    def test_stress_findings_feed_the_next_writer_round(self):
        h = WorkerHome(self)
        stress = h.step(StepKind.STRESS, 1, snapshot=h.push_practice())
        h.start(stress, {"bench": "skip", "model": {"attacker": {"blocking": ["the key misses scenario S10"]}}})
        result = h.wait(stress)
        self.assertEqual((result.outcome, result.reason), (Outcome.OK, "stress:findings"), h.log(stress))
        feedback = json.loads(h.output(stress, result.feedback))
        self.assertEqual(feedback, {"version": 1, "source": "stress", "problems": ["the key misses scenario S10"],
                                    "attack_report": "round-1.json"})
        h.push(ArtifactKind.CASE_SNAPSHOT, h.output(stress, result.snapshot))
        h.push(ArtifactKind.WRITER_FEEDBACK, h.output(stress, result.feedback))
        writer = h.step(StepKind.WRITER, 2, seq=2, snapshot=result.snapshot, feedback=result.feedback)
        h.start(writer, {"bench": "skip", "model": {}})
        self.assertEqual(h.wait(writer).reason, "writer:validated", h.log(writer))
        call = json.loads((h.home / "model-calls.jsonl").read_text().splitlines()[-1])
        self.assertIn("the key misses scenario S10", call["text"])
        self.assertIn("round-1.json", call["text"])

    def test_clean_stress_round(self):
        h = WorkerHome(self)
        si = h.step(StepKind.STRESS, 1, snapshot=h.push_practice())
        h.start(si, {"bench": "skip", "model": {"attacker": {}}})
        result = h.wait(si)
        self.assertEqual((result.outcome, result.reason, result.feedback), (Outcome.OK, "stress:clean", None))

    def test_writer_dispatch_reaches_the_docker_boundary(self):
        if DOCKER: self.skipTest("Docker is available: the boundary is not reached")
        h = WorkerHome(self)
        si = h.step(StepKind.WRITER, 1, snapshot=h.push_practice())
        h.start(si, {"model": {}})
        result = h.wait(si)
        self.assertIs(result.outcome, Outcome.INFRA_ERROR)
        self.assertFalse((h.home / "model-calls.jsonl").exists())
        self.assertIn("factory_pool", json.loads(h.output(si, result.diagnostic))["traceback"])

    def test_gates_dispatch_runs_until_the_docker_boundary(self):
        if DOCKER: self.skipTest("Docker is available: test_gates_snapshot_reuse covers GATES")
        h = WorkerHome(self)
        si = h.step(StepKind.GATES, 1, snapshot=h.push_practice())
        h.start(si)
        result = h.wait(si)
        self.assertIsNot(result.outcome, Outcome.OK)
        self.assertEqual(result.passed, ("G1",), h.log(si))
        receipt = json.loads(h.output(si, result.receipt))
        self.assertEqual(receipt["gates"]["G1"], "pass")
        self.assertTrue(receipt["gates"]["G2"].startswith("skipped"))
        self.assertIsNotNone(result.snapshot)

    @unittest.skipUnless(DOCKER, NO_DOCKER)
    def test_gates_snapshot_reuse(self):
        """Done when: a fresh worker restoring a GATES snapshot reuses that snapshot's passed gates."""
        first = WorkerHome(self)
        si = first.step(StepKind.GATES, 1, snapshot=first.push_practice())
        first.start(si)
        result = first.wait(si, 4 * 3600)
        self.assertEqual(result.outcome, Outcome.OK, first.log(si))
        reusable = sorted(set(result.passed) & __import__("gate_state").REUSABLE)
        self.assertTrue(reusable, result.passed)
        fresh = WorkerHome(self)
        fresh.case_key = first.case_key
        snapshot = fresh.push(ArtifactKind.CASE_SNAPSHOT, first.output(si, result.snapshot))
        again = fresh.step(StepKind.GATES, 1, seq=2, snapshot=snapshot)
        fresh.start(again)
        second = fresh.wait(again, 4 * 3600)
        self.assertEqual(second.outcome, Outcome.OK, fresh.log(again))
        receipt = json.loads(fresh.output(again, second.receipt))
        for gate in reusable:
            self.assertTrue(receipt["gate_results"][gate].get("reused_verified_evidence"), gate)
        self.assertEqual(set(second.passed), set(result.passed))

    @unittest.skipUnless(DOCKER, NO_DOCKER)
    def test_writer_round_past_case_money_with_the_real_shop(self):
        h = WorkerHome(self)
        si = h.step(StepKind.WRITER, 1, snapshot=h.push_practice(ledger=E15450["continuation_budget"]))
        h.start(si, {"model": {"builder": {"cost": 3.0}}})
        self.assertEqual(h.wait(si, 3600).reason, "writer:validated", h.log(si))


# ---- the run.py hooks in process ---------------------------------------------------------------

class HookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)

    def context(self, kind=StepKind.WRITER, round=1, *, ceiling=5_000_000, deadline=600.0, **tree):
        work = practice_tree(self.root, CASE, **tree)
        si = StepInput(BATCH, CASE, 1, Step(kind, round), 1, PLUMBING, BENCH_V, Ref("1" * 64, ArtifactKind.INPUTS),
                       Ref("2" * 64, ArtifactKind.CASE_SNAPSHOT), deadline, ceiling)
        return run.context_for_step(si, work), si

    def test_start_dies_before_unit_publication_without_running_child(self):
        c, si = self.context()
        worker = worker_step.Worker(self.root)
        marker = self.root / "child-ran"
        children = []
        def fail_publication(step, pid):
            children.append(pid)
            raise RuntimeError("injected start failure")
        with patch.object(worker, "_publish_unit", side_effect=fail_publication), \
                patch.object(worker, "supervise", side_effect=lambda *args: marker.write_text("ran")):
            with self.assertRaisesRegex(RuntimeError, "injected start failure"):
                worker.start(start_frame(si, {CASE: b"k" * 32}))
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if os.waitpid(children[0], os.WNOHANG)[0]: break
            time.sleep(0.01)
        else:
            os.kill(children[0], signal.SIGKILL); os.waitpid(children[0], 0)
            self.fail("child remained live after the start command failed")
        self.assertFalse(marker.exists())

    def test_card_write_failure_cannot_publish_ok(self):
        c, si = self.context()
        with patch.object(run, "engine_writer_round", return_value={"outcome": Outcome.OK, "reason": "writer:done"}), \
                patch("registry.atomic_json", side_effect=OSError("injected card failure")):
            result = run.run_step(c, si)
        self.assertEqual(result["outcome"], Outcome.INFRA_ERROR)
        self.assertEqual(result["reason"], "infra:card_write_failed")

    def test_post_execution_error_keeps_booked_usage_and_syncs_outputs_before_result(self):
        c, si = self.context()
        worker = worker_step.Worker(self.root)
        worker.paths(si.idempotency_key)["attempt"].mkdir(parents=True)
        worker.paths(si.idempotency_key)["out"].mkdir()
        worker._save_baseline(si, c.ledger, worker_step.ledger_totals(c.ledger))
        def priced_then_fail(*args):
            with budget.ledger_transaction(c.ledger) as ledger:
                ledger["calls"] = ledger.get("calls", 0) + 1
                ledger["events"].append({"id": "priced-failure", "cost": 0.75,
                                          "configured_model": "x/y", "role": "writer"})
            raise RuntimeError("injected output failure")
        order = []
        with patch.object(worker, "execute", side_effect=priced_then_fail), \
                patch.object(worker, "_sync_directory", side_effect=lambda path: order.append("outputs")), \
                patch.object(worker, "write_result", side_effect=lambda key, result: order.append(result)):
            worker.run_attempt(si, {CASE: b"k" * 32})
        self.assertEqual(order[0], "outputs")
        self.assertEqual(order[1].outcome, Outcome.INFRA_ERROR)
        self.assertEqual(order[1].usage.calls, 1)
        self.assertEqual(order[1].usage.paid_usd_micros, 750000)

    def test_context_keeps_supervisor_deadline_and_discards_legacy_timeout(self):
        with patch.dict(os.environ, {"UNBUG_DURABLE_DEADLINE_EPOCH": str(time.time() + 30)}):
            c, _ = self.context(deadline=600)
        self.assertAlmostEqual(c.engine.deadline_monotonic - time.monotonic(), 30, delta=5)
        self.assertAlmostEqual(c.args.agent_timeout, 30, delta=5)
        self.assertEqual(c.job_id, CASE)
        self.assertTrue(model_router._deadlines(c, None)[0])

    def test_durable_context_inherits_the_administrator_judge_without_main(self):
        import factory_pool
        probe = ('import sys; sys.path.insert(0, ' + repr(str(REPO / 'bin')) +
                 '); import bench; print(bench.CHECKER_ROLE)')
        with patch.dict(os.environ), patch.object(run, 'main', side_effect=AssertionError('standalone entry')):
            os.environ.pop('UNBUG_JUDGE', None)
            c, _ = self.context(StepKind.GATES)
            for env in (None, factory_pool.worker_env(0)):
                result = run.sh(c, [sys.executable, '-B', '-c', probe], capture=True, check=True, env=env)
                self.assertEqual(result.stdout.strip(), 'medusa')

    def test_provider_limit_reset_and_credential_fault_are_distinct(self):
        c, si = self.context()
        for reason, expected in (("quota", "router:quota"), ("credential_expiring", "router:credential_expiring")):
            reset = time.time() + 1234
            wait = model_router.ProviderWait("writer", model_router.Wait(reason, reset))
            with patch.object(run, "engine_writer_round", side_effect=wait):
                result = run.run_step(c, si)
            self.assertEqual(result["reason"], expected)
            self.assertEqual(result["retry_at"], reset if reason == 'quota' else None)
            self.assertEqual(c.card['engine_provider_wait']['waits'][-1]['retry_after'], reset)
            worker = worker_step.Worker(self.root, sealer=AgeCliSealer())
            wire, _ = worker.result(si, c, result, k.Usage(), worker.sealer(), b'k' * 32, classify, run)
            self.assertEqual(wire.reason, expected)
            self.assertEqual(wire.retry_at, result['retry_at'])
            k.check_result_for(si.step, wire)

    def test_dry_run_writer_and_stress_never_invoke_models(self):
        c, si = self.context()
        c.card["admission"] = {"status": "practice_dry_run"}
        with patch.object(run, "opencode", side_effect=AssertionError("dry run model call")), \
                patch.object(run, "engine_prepare_bench", side_effect=AssertionError("unneeded bench")):
            self.assertEqual(run.engine_writer_round(c, 1, None)["outcome"], Outcome.OK)
            self.assertEqual(run.engine_stress_round(c, 1)["outcome"], Outcome.OK)

    def test_confirmed_public_match_routes_to_scientific_gate_without_stress_spend(self):
        c, _ = self.context(StepKind.STRESS)
        c.args.dry_run = False
        c.card["admission_freshness"] = {"outcome": "public_match"}
        with patch.object(run, "opencode", side_effect=AssertionError("public match stress call")):
            self.assertEqual(run.engine_stress_round(c, 1)["reason"], "stress:public_match")

    def test_founder_ruling_reaches_new_reviewer_call(self):
        c, si = self.context(StepKind.GATES)
        c.card["failed_gate"] = "G8"
        c.votes, c.votes_hash = [], run.case_hash(c)
        seen = []
        def model(c, models, text, cwd, name, **kwargs):
            seen.append(text)
            target = pathlib.Path(text.split('verdict_path": "')[1].split('"')[0])
            target.write_text(json.dumps({"fairness": {"approve": True}, "realism": {"approve": True}}))
            c.model_lease = types.SimpleNamespace(route=models[0])
            kwargs["on_complete"]()
            return 0
        def gates(c):
            run.review(c)
            return {"outcome": Outcome.OK, "reason": "engine:gates_passed"}
        with patch.object(run, "engine_gates", side_effect=gates), patch.object(run, "opencode", side_effect=model):
            out = run.run_step(c, si, ruling=b"The disputed owner fact is available in the statement.")
        self.assertEqual(out["outcome"], Outcome.OK)
        self.assertTrue(seen)
        self.assertTrue(all("disputed owner fact" in text for text in seen))
        self.assertEqual(run.engine_review_ruling(c, "G16"), "")

    def test_corrupt_usage_never_reports_zero_cost(self):
        c, si = self.context()
        worker = worker_step.Worker(self.root)
        worker.paths(si.idempotency_key)["attempt"].mkdir(parents=True)
        worker._save_baseline(si, c.ledger, worker_step.ledger_totals(c.ledger))
        c.ledger.write_text("{invalid")
        out = worker._failure_result(si.idempotency_key, "infra:worker_error")
        self.assertEqual(out.reason, "infra:usage_unknown")
        from durable.policy import settles_lost
        self.assertTrue(settles_lost(out))

    def test_missing_usage_ledger_is_unknown_before_paid_execution(self):
        c, _ = self.context()
        c.ledger.unlink()
        self.assertIsNone(worker_step.ledger_totals(c.ledger)["total"])

    def test_context_is_never_a_legacy_job_and_only_the_attempt_deadline_bounds_calls(self):
        with patch.dict(os.environ, {"FACTORY_BATCH_DEADLINE": "2020-01-01T00:00:00Z"}):
            c, _ = self.context(deadline=120.0)
            self.assertIsNotNone(c.engine)
            self.assertFalse(hasattr(c, "authenticated_job_config"))
            self.assertEqual(c.args.max_cost, run.ENGINE_COST_CAP)
            _, batch_end, stop_at = run.model_router._deadlines(c, None)
            self.assertAlmostEqual(batch_end, time.time() + 120, delta=5)
        seen = []
        with patch.object(run, "_opencode", lambda c, *a, **kw: seen.append(kw)):
            run.opencode(c, ["x/y"], "text", c.case, "builder-1")
            run.opencode(c, ["x/y"], "text", c.case, "strong-calibrator-1", timeout=30)
        self.assertAlmostEqual(seen[0]["timeout"], 120, delta=5)
        self.assertAlmostEqual(seen[0]["deadline"], c.engine.deadline_monotonic)
        self.assertEqual(seen[1]["timeout"], 30)
        c.engine.deadline_monotonic = time.monotonic() - 1
        with self.assertRaisesRegex(budget.BudgetError, "timeout"):
            run.opencode(c, ["x/y"], "text", c.case, "builder-1")

    def test_a_model_call_times_out_at_the_attempt_deadline_not_a_batch_bound(self):
        c, _ = self.context(deadline=2.0)
        call = stub_model({"builder": {"sleep": 30}})
        began = time.monotonic()
        with self.assertRaises(budget.BudgetError) as stop:
            call(c, c.models["builder"], "text", c.case, "builder-1")
        self.assertEqual(str(stop.exception).replace("Budget stopped: ", ""), "timeout")
        self.assertLess(time.monotonic() - began, 15)

    def test_plumbing_stops_are_infrastructure(self):
        c, si = self.context()
        for stop, expected in (("router_batch_unconfigured", "infra:router_unconfigured"),
                               ("Budget stopped: router_batch_unconfigured", "infra:router_unconfigured"),
                               ("provider_wait_deadline", "infra:deadline")):
            with patch.object(run, "engine_writer_round", side_effect=budget.BudgetError(stop)):
                result = run.run_step(c, si)
            self.assertEqual((result["outcome"], result["reason"], result["stop"]),
                             (Outcome.INFRA_ERROR, expected, None), stop)

    def test_validate_and_repair_runs_one_gate_pass(self):
        c, _ = self.context(StepKind.GATES)
        def gates(c): c.card.update(failed_gate="G5", failed_detail={"problems": ["x"]})
        with patch.object(run, "run_gates", side_effect=gates) as runner:
            c.args.dry_run = False
            run.validate_and_repair(c)
        runner.assert_called_once()
        self.assertFalse(hasattr(run, "write_and_attack"))

    def test_engine_gates_failure_shapes(self):
        c, _ = self.context(StepKind.GATES)
        def failing(gate, detail, **card):
            def gates(c):
                c.card["gates"][gate] = "fail"; c.card["gates"]["G1"] = "pass"
                c.card.update(failed_gate=gate, failed_detail=detail, **card)
            return gates
        cases = [
            (failing("G5", {"problems": ["reference unsolved"]}), Outcome.GATE_FAILED, "g5:failed", True),
            (failing("G3", {"problems": ["build"]}), Outcome.GATE_FAILED, "g3:failed", False),
            (failing("G8", {"approve": "1/2"}, reviewers_fairness="1/2"), Outcome.NEEDS_FOUNDER, "g8:reviewers_disagree", False),
            (failing("G8", {"approve": "0/2"}, reviewers_fairness="0/2"), Outcome.GATE_FAILED, "g8:failed", True),
            (failing("G17", {"review_inconclusive": True}), Outcome.NEEDS_FOUNDER, "g17:review_inconclusive", False),
            (failing("G6", {"error": "RuntimeError"}), Outcome.INFRA_ERROR, "infra:gate_error", False)]
        for gates, outcome, reason, repairable in cases:
            with patch.object(run, "run_gates", side_effect=gates):
                out = run.engine_gates(c)
            self.assertEqual((out["outcome"], out["reason"], bool(out.get("repairable"))), (outcome, reason, repairable))
            self.assertEqual(out["passed"], ("G1",))
            self.assertEqual(out.get("feedback") is not None, repairable)

    def test_engine_gate_checkpoint_uses_explicit_hook_and_no_legacy_upload(self):
        c, _ = self.context(StepKind.GATES)
        c.recipient = run.FOUNDER_RECIPIENT; c.args.dry_run = False; c.args.no_early_probe = True
        completed = []
        c.engine_checkpoint = lambda: completed.append(True)
        run._gate_completed(c, "G4", True, True)
        self.assertEqual(completed, [True])
        self.assertFalse(run.parallel_calibrators(c))
        with patch.object(run.model_runtime.ModelRuntime, "call", return_value=0):
            run._opencode(c, ["x/y"], "text", c.case, "reviewer-1")
        self.assertFalse(hasattr(run, "reselect_candidate"))

    def test_engine_writer_has_no_case_round_reservation_or_final_repair(self):
        c, _ = self.context(ledger=E15450["continuation_budget"],
                            card=practice_card(CASE, recovery_config={"rounds": 1}))
        c.args.dry_run = False
        self.assertGreater(model_runtime.writer_round_estimate(c), c.engine.ceiling_usd)
        names = []
        def model(c, models, text, cwd, name, **kwargs):
            model_runtime.case_budget_boundary(c, models[0])
            names.append(name)
            if name.startswith("attacker"):
                cfg = json.loads(text.split('CATEGORY MODE (overrides whole-review completion instructions):\n')[1].split('\n')[0])
                pathlib.Path(cfg['category_output']).write_text(json.dumps({
                    "category": cfg['category'], "category_complete": True, "completed_subchecks": cfg['required_subchecks'],
                    "blocking": ["still broken"], "unfinished_validation": [], "non_blocking": [], "freshness_review": [], "cheats_tried": []}))
                c.model_lease = types.SimpleNamespace(route=models[0])
                kwargs["on_complete"]()
            return 0
        with patch.object(run, "opencode", model), patch.object(run, "engine_prepare_bench"), \
                patch.object(run, "g1", return_value=(True, {"problems": []})), \
                patch.object(run, "early_checks", return_value=None), patch.object(run, "ensure_freshness"), \
                patch.object(run, "loop_freshness", side_effect=lambda c, result, report: (result, report)):
            self.assertEqual(run.engine_writer_round(c, 1, None)["outcome"], Outcome.OK)
            result = run.engine_stress_round(c, 1)
        self.assertEqual(names, ["builder-1", "attacker-1"])
        self.assertEqual(result["reason"], "stress:findings")
        self.assertIn("still broken", json.loads(result["feedback"])["problems"])
        self.assertFalse(hasattr(run, "write_and_attack"))

    def test_retained_subset(self):
        legacy = ("agent-state/x", "durable-checkpoint.json", "job-money.json",
                  "rejected-candidate-1-5/statement.md", "extension-history.json")
        evidence = ("gate-cache/G4.json", "gate-details/G4.json", "review-1/verdict.json", "strong_calibrator/results.json",
                    "attacks/round-1.json", "infra-attempts.json", "prototype.json", "stress-publication.json", "ordinary-retries/state.json")
        c, _ = self.context(extra=legacy + evidence)
        bench = self.root / "bench"; (bench / "results/run-a").mkdir(parents=True)
        (bench / "results/run-a/trial.json").write_text("{}")
        (bench / "results/.bench.lock").write_text("")
        with patch.object(run, "BENCH", bench):
            names = {p.as_posix() for p in run.retained_paths(c)}
        self.assertTrue({"case", "scorecard.json", "logs", "bench-results", "gate-cache", "gate-details", "review-1",
                         "strong_calibrator", "attacks", "infra-attempts.json", "prototype.json", "ordinary-retries", "stress-publication.json"} <= names, names)
        self.assertFalse({p.split("/")[0] for p in legacy} & names)
        self.assertTrue((c.work / "bench-results/run-a/trial.json").is_file())
        snapshot = worker_step.snapshot_bytes(c, run)
        restored = self.root / "restored"
        worker_step.restore(snapshot, restored)
        self.assertEqual({p.name for p in restored.iterdir()}, names)
        self.assertEqual(run.case_hash(types.SimpleNamespace(case=restored / "case")), run.case_hash(c))

    def test_restore_refuses_paths_outside_the_work_tree(self):
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
            info = tarfile.TarInfo("../escape"); data = b"x"; info.size = 1
            tar.addfile(info, io.BytesIO(data))
        with self.assertRaises(Exception):
            worker_step.restore(buffer.getvalue(), self.root / "work")
        self.assertFalse((self.root / "escape").exists())


if __name__ == "__main__":
    unittest.main()
