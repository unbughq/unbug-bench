"""Frozen contract shared by every durable-execution work package.

The workflow engine (DBOS) records every step argument, every step result and every
step exception in its database. Nothing here may carry case content: identifiers,
keyed digests, reason codes from a fixed grammar, and numbers only. Case content lives
in encrypted artifacts, referenced by `Ref`.

Design: docs/designs/durable-execution.md. Pure module: no I/O, no engine import.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from enum import Enum
import math
import re
from typing import Any, Mapping, Optional, Protocol

CONTRACT_VERSION = 2

DIGEST = re.compile(r"[0-9a-f]{64}")
CASE_ID = re.compile(r"case-[A-Za-z0-9-]{1,80}")
BATCH_ID = re.compile(r"b-[a-z0-9-]{1,60}")
WORKER_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")
# A reason is "<stage>:<code>". The code is lowercase letters and underscores only, so it
# cannot hold a path, a file name, an identifier with digits or dots, or a sentence.
REASON = re.compile(r"(admit|writer|stress|g(?:[1-9]|1[0-7])|seal|diagnosis|infra|router|engine|batch)"
                    r":[a-z][a-z_]{0,31}")

# Copy of run.GATES (cheap rejectors first); tests/factory/test_durable_contract.py fails
# if they differ. G12 (seal) is the SEAL step, not a gate step.
GATES = ("G1", "G2", "G3", "G4", "G5", "G16", "G8", "G9", "G6",
         "G13", "G14", "G15", "G7", "G10", "G17", "G11")
# G10 starts as soon as G6 passes and runs beside G13-G15 and G7; it is joined before
# G17 (gate_pipeline.py). Every other gate runs in GATES order.
CONCURRENT_FROM = {"G10": "G6"}


class ContractError(ValueError):
    pass


def _check(cond, message):
    if not cond:
        raise ContractError(message)


def _reason(value, name="reason"):
    _check(type(value) is str and REASON.fullmatch(value) is not None,
           f"{name} must be '<stage>:<code>' from the fixed grammar, not free text")
    return value


def _nonneg_int(value, name):
    _check(type(value) is int and value >= 0, f"{name} must be a non-negative int")
    return value


def _pos_int(value, name):
    _check(type(value) is int and value >= 1, f"{name} must be a positive int")
    return value


def _finite(value, name, positive=False):
    _check(type(value) in (int, float) and math.isfinite(value) and (value > 0 or not positive),
           f"{name} must be a finite{' positive' if positive else ''} number")
    return value


def _id(value, pattern, name):
    _check(type(value) is str and pattern.fullmatch(value) is not None, f"bad {name}")
    return value


class ArtifactKind(str, Enum):
    """What an encrypted artifact holds. Content never leaves the artifact."""
    INPUTS = "inputs"                       # batch: app pin, promise text, rotation
    STATEMENT_REGISTRY = "registry"         # batch: statements already admitted or reserved
    CASE_SNAPSHOT = "case"                  # case tree plus the retained work-dir subset
    WRITER_FEEDBACK = "feedback"            # findings handed to the next writer round
    GATE_RECEIPT = "receipt"                # private evidence behind one gate verdict
    DIAGNOSIS_REPORT = "diagnosis"          # the diagnosis agent's private report
    DIAGNOSTIC = "diagnostic"               # logs and transcripts of one failed attempt
    SEALED_ARCHIVE = "sealed"               # the final G12 archive


BATCH_SCOPED = {ArtifactKind.INPUTS, ArtifactKind.STATEMENT_REGISTRY}


@dataclass(frozen=True)
class Ref:
    """Pointer to one encrypted artifact.

    digest = HMAC-SHA256(scope key, plaintext): stable for identical bytes within one
    scope (a case, or a batch for BATCH_SCOPED kinds), and useless for confirming a
    guessed plaintext or comparing across scopes without the key.
    """
    digest: str
    kind: ArtifactKind

    def __post_init__(self):
        _id(self.digest, DIGEST, "Ref.digest")
        try:
            object.__setattr__(self, "kind", ArtifactKind(self.kind))
        except ValueError:
            raise ContractError(f"unknown artifact kind {self.kind!r}") from None


def _ref(value, kind, name):
    if value is None:
        return None
    _check(isinstance(value, Ref), f"{name} must be a Ref")
    _check(value.kind is kind, f"{name} must be a {kind.value} Ref")
    return value


class StepKind(str, Enum):
    ADMIT = "admit"          # choose the bug and admit its statement (batch-serialized)
    WRITER = "writer"        # one writer round
    STRESS = "stress"        # one stress (attacker) round
    GATE = "gate"            # one gate in GATES
    DIAGNOSIS = "diagnosis"  # the automatic diagnosis agent (ENGINEERING section 3)
    SEAL = "seal"            # G12: encrypt, hash, retain the archive


@dataclass(frozen=True)
class Step:
    kind: StepKind
    gate: Optional[str] = None   # set exactly for GATE
    round: int = 0               # >= 1 exactly for WRITER and STRESS

    def __post_init__(self):
        try:
            object.__setattr__(self, "kind", StepKind(self.kind))
        except ValueError:
            raise ContractError(f"unknown step kind {self.kind!r}") from None
        _check((self.kind is StepKind.GATE) == (self.gate is not None), "gate is set exactly for GATE steps")
        _check(self.gate is None or self.gate in GATES, f"unknown gate {self.gate!r}")
        _nonneg_int(self.round, "Step.round")
        _check((self.kind in (StepKind.WRITER, StepKind.STRESS)) == (self.round >= 1),
               "round is >= 1 exactly for writer and stress steps")

    @property
    def name(self) -> str:
        if self.kind is StepKind.GATE:
            return f"gate:{self.gate}"
        if self.round:
            return f"{self.kind.value}:{self.round}"
        return self.kind.value


@dataclass(frozen=True)
class Usage:
    """Model usage of one attempt. Micro-dollars keep it exact and JSON-safe."""
    calls: int = 0
    paid_usd_micros: int = 0
    list_usd_micros: int = 0

    def __post_init__(self):
        for f in fields(self):
            _nonneg_int(getattr(self, f.name), f"Usage.{f.name}")

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(*(getattr(self, f.name) + getattr(other, f.name) for f in fields(self)))


class Outcome(str, Enum):
    """Every step attempt ends in exactly one of these. There is no seventh."""
    OK = "ok"                          # committed; next step (STRESS may carry findings)
    INFRA_ERROR = "infra_error"        # retry; never scored, never writer feedback
    PROVIDER_LIMIT = "provider_limit"  # durable sleep until retry_at
    GATE_FAILED = "gate_failed"        # a scored rejection by a gate
    EXHAUSTED = "exhausted"            # the case's own round or money limit ran out
    NEEDS_FOUNDER = "needs_founder"    # independent reviewers genuinely disagree


class Verdict(str, Enum):
    """The diagnosis agent's verdict (docs/designs/stream-d.md)."""
    FACTORY_BUG = "factory_bug"
    CLOSE_TO_PASSING = "close_to_passing"
    NOT_CONVERGING = "not_converging"


@dataclass(frozen=True)
class StepInput:
    batch_id: str
    case_id: str
    seq: int                     # 1-based, strictly increasing over the case's steps
    step: Step
    attempt: int                 # 1-based, attempts of this seq
    plumbing_version: str        # rolls forward at step boundaries
    bench_version: str           # pinned for the case; a gate change bumps it per gate
    snapshot: Optional[Ref]      # CASE_SNAPSHOT before the step; None exactly for ADMIT
    deadline_s: float            # wall-clock budget of this attempt on the worker
    money_ceiling_usd_micros: int  # paid spend this attempt may reserve; stop at it
    feedback: Optional[Ref] = None  # WRITER_FEEDBACK, WRITER steps only
    registry: Optional[Ref] = None  # STATEMENT_REGISTRY, ADMIT steps only

    def __post_init__(self):
        _id(self.batch_id, BATCH_ID, "batch_id")
        _id(self.case_id, CASE_ID, "case_id")
        _pos_int(self.seq, "seq")
        _check(isinstance(self.step, Step), "step must be a Step")
        _pos_int(self.attempt, "attempt")
        _id(self.plumbing_version, DIGEST, "plumbing_version")
        _id(self.bench_version, DIGEST, "bench_version")
        _finite(self.deadline_s, "deadline_s", positive=True)
        _nonneg_int(self.money_ceiling_usd_micros, "money_ceiling_usd_micros")
        admit = self.step.kind is StepKind.ADMIT
        _check((self.snapshot is None) == admit, "snapshot is absent exactly for ADMIT")
        _ref(self.snapshot, ArtifactKind.CASE_SNAPSHOT, "snapshot")
        _check(self.feedback is None or self.step.kind is StepKind.WRITER, "feedback goes only to writer steps")
        _ref(self.feedback, ArtifactKind.WRITER_FEEDBACK, "feedback")
        _check((self.registry is not None) == admit, "registry is present exactly for ADMIT")
        _ref(self.registry, ArtifactKind.STATEMENT_REGISTRY, "registry")

    @property
    def idempotency_key(self) -> str:
        """Identical on a replayed attempt, distinct for every new step, repair or resume."""
        return f"{self.case_id}/{self.seq}/{self.step.name}/{self.attempt}"


@dataclass(frozen=True)
class StepResult:
    outcome: Outcome
    reason: str                       # "<stage>:<code>", e.g. "g5:reference_unsolved"
    usage: Usage = field(default_factory=Usage)
    snapshot: Optional[Ref] = None    # CASE_SNAPSHOT after the step; required for OK
    receipt: Optional[Ref] = None     # GATE_RECEIPT
    feedback: Optional[Ref] = None    # WRITER_FEEDBACK: STRESS findings, or a repairable gate failure
    repairable: bool = False          # GATE_FAILED only
    retry_at: Optional[float] = None  # PROVIDER_LIMIT only: epoch seconds of the reset
    verdict: Optional[Verdict] = None  # OK of a DIAGNOSIS step only
    report: Optional[Ref] = None      # DIAGNOSIS_REPORT
    diagnostic: Optional[Ref] = None  # DIAGNOSTIC

    def __post_init__(self):
        try:
            object.__setattr__(self, "outcome", Outcome(self.outcome))
        except ValueError:
            raise ContractError(f"unknown outcome {self.outcome!r}") from None
        _reason(self.reason)
        _check(isinstance(self.usage, Usage), "usage must be a Usage")
        _check(type(self.repairable) is bool, "repairable must be a bool")
        o = self.outcome
        _ref(self.snapshot, ArtifactKind.CASE_SNAPSHOT, "snapshot")
        _ref(self.receipt, ArtifactKind.GATE_RECEIPT, "receipt")
        _ref(self.feedback, ArtifactKind.WRITER_FEEDBACK, "feedback")
        _ref(self.report, ArtifactKind.DIAGNOSIS_REPORT, "report")
        _ref(self.diagnostic, ArtifactKind.DIAGNOSTIC, "diagnostic")
        _check(o is not Outcome.OK or self.snapshot is not None, "OK carries the snapshot after the step")
        if o is Outcome.PROVIDER_LIMIT:
            _finite(self.retry_at, "retry_at")
        else:
            _check(self.retry_at is None, "retry_at is only for PROVIDER_LIMIT")
        _check(o is Outcome.GATE_FAILED or not self.repairable, "repairable is only for GATE_FAILED")
        _check(not self.repairable or self.feedback is not None, "a repairable gate failure carries feedback")
        _check(self.feedback is None or o in (Outcome.OK, Outcome.GATE_FAILED), "feedback only on OK or GATE_FAILED")
        if self.verdict is not None:
            _check(o is Outcome.OK, "verdict only on OK")
            try:
                object.__setattr__(self, "verdict", Verdict(self.verdict))
            except ValueError:
                raise ContractError(f"unknown verdict {self.verdict!r}") from None


def check_result_for(step: Step, result: StepResult) -> None:
    """Rules that depend on which step produced the result. The engine calls this."""
    k = step.kind
    _check(result.feedback is None or k in (StepKind.STRESS, StepKind.GATE),
           "only stress findings or gate failures carry feedback")
    _check(not (result.outcome is Outcome.OK and k is StepKind.GATE and result.feedback is not None),
           "a passing gate carries no feedback")
    _check((result.verdict is not None) == (k is StepKind.DIAGNOSIS and result.outcome is Outcome.OK),
           "a verdict comes exactly from a successful DIAGNOSIS step")
    _check(result.outcome is not Outcome.GATE_FAILED or k is StepKind.GATE, "only gates fail as GATE_FAILED")


@dataclass(frozen=True)
class BatchSpec:
    """The factory's whole input: which app, which promise, how many cases, which bounds.

    The promise text and rotation sit in the INPUTS artifact; the spec holds its Ref.
    """
    batch_id: str
    plumbing_version: str        # initial plumbing release; later releases roll forward
    bench_version: str           # bench logic every case of the batch pins
    app_repo: str                # "owner/name"
    app_commit: str              # exact pinned commit
    inputs: Ref                  # INPUTS
    target_sealed: int           # stop when this many cases have sealed
    money_bound_usd_micros: int  # cumulative paid spend across all cases, retries, extensions
    deadline_epoch: float        # no new case or extension starts after this
    max_concurrency: int = 1
    max_writer_rounds: int = 8          # the runner's --rounds is set from this
    max_infra_retries_per_step: int = 5
    max_consecutive_limits: int = 50    # limit attempts of one step that each spent money
    max_extensions: int = 5             # ENGINEERING section 3
    max_factory_bug_resumes: int = 3    # ENGINEERING section 3
    step_deadline_s: float = 14_400.0   # default StepInput.deadline_s (agent_timeout today)
    release_worker_after_sleep_s: float = 1_800.0  # longer sleeps give the worker back

    def __post_init__(self):
        _id(self.batch_id, BATCH_ID, "batch_id")
        _id(self.plumbing_version, DIGEST, "plumbing_version")
        _id(self.bench_version, DIGEST, "bench_version")
        _check(type(self.app_repo) is str and re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", self.app_repo) is not None,
               "app_repo is owner/name")
        _check(type(self.app_commit) is str and re.fullmatch(r"[0-9a-f]{40}", self.app_commit) is not None,
               "app_commit is a full git sha")
        _ref(self.inputs, ArtifactKind.INPUTS, "inputs")
        _check(self.inputs is not None, "inputs is required")
        for name in ("target_sealed", "max_concurrency", "max_writer_rounds", "max_consecutive_limits"):
            _pos_int(getattr(self, name), name)
        for name in ("money_bound_usd_micros", "max_infra_retries_per_step", "max_extensions", "max_factory_bug_resumes"):
            _nonneg_int(getattr(self, name), name)
        _finite(self.deadline_epoch, "deadline_epoch")
        _finite(self.step_deadline_s, "step_deadline_s", positive=True)
        _finite(self.release_worker_after_sleep_s, "release_worker_after_sleep_s", positive=True)


@dataclass(frozen=True)
class SealedCase:
    """The factory's output for one case. The public scorecard is a report the control
    VM generates from the engine tables; it is not a worker artifact."""
    case_id: str
    archive: Ref
    hard: bool                   # strong calibrators solved zero tries (G10/G17)

    def __post_init__(self):
        _id(self.case_id, CASE_ID, "case_id")
        _ref(self.archive, ArtifactKind.SEALED_ARCHIVE, "archive")
        _check(self.archive is not None, "archive is required")
        _check(type(self.hard) is bool, "hard must be a bool")


# ---- the case state machine --------------------------------------------------------------

class Action(str, Enum):
    ADVANCE = "advance"                    # next step, with result.snapshot
    RETRY = "retry"                        # same seq, attempt + 1, same input
    SLEEP = "sleep"                        # durable_wait(result.retry_at), then RETRY
    REPAIR = "repair"                      # next writer round with result.feedback
    DIAGNOSE = "diagnose"                  # run a DIAGNOSIS step; the batch starts a replacement now
    EXTEND = "extend"                      # one writer round + stress round + gate rerun
    RESUME_AFTER_FIX = "resume_after_fix"  # wait for a new plumbing release, then resume
    RETIRE = "retire"                      # stop this case; the batch starts a replacement now
    ESCALATE = "escalate"                  # park for the founder; slot freed, replacement now


STARTS_REPLACEMENT = {Action.DIAGNOSE, Action.RETIRE, Action.ESCALATE}


@dataclass(frozen=True)
class Counters:
    """Per-case counts the engine derives from the journal, never from a worker."""
    step_infra_errors: int = 0      # INFRA_ERROR attempts of this seq, this one included
    step_spent_limits: int = 0      # PROVIDER_LIMIT attempts of this seq that spent money, this one included
    writer_rounds_used: int = 0
    extensions_used: int = 0
    factory_bug_resumes: int = 0

    def __post_init__(self):
        for f in fields(self):
            _nonneg_int(getattr(self, f.name), f"Counters.{f.name}")


def decide(step: Step, result: StepResult, counters: Counters, spec: BatchSpec) -> Action:
    """Pure policy for one finished attempt (ENGINEERING section 3)."""
    check_result_for(step, result)
    o = result.outcome
    rounds_left = counters.writer_rounds_used < spec.max_writer_rounds
    if o is Outcome.OK:
        if step.kind is StepKind.STRESS and result.feedback is not None:
            return Action.REPAIR if rounds_left else Action.DIAGNOSE
        if step.kind is StepKind.DIAGNOSIS:
            raise ContractError("route a diagnosis verdict through decide_diagnosis")
        return Action.ADVANCE
    if o is Outcome.PROVIDER_LIMIT:
        # Waiting spends no allowance. Only a run of limits that each spent money (a
        # likely misclassification) goes to diagnosis.
        return Action.SLEEP if counters.step_spent_limits <= spec.max_consecutive_limits else Action.DIAGNOSE
    if o is Outcome.INFRA_ERROR:
        return Action.RETRY if counters.step_infra_errors <= spec.max_infra_retries_per_step else Action.DIAGNOSE
    if o is Outcome.GATE_FAILED:
        if not result.repairable:
            return Action.RETIRE                 # a scored rejection, e.g. the bug is not fresh
        return Action.REPAIR if rounds_left else Action.DIAGNOSE
    if o is Outcome.EXHAUSTED:
        return Action.DIAGNOSE
    if o is Outcome.NEEDS_FOUNDER:
        return Action.ESCALATE
    raise AssertionError(o)


def decide_diagnosis(verdict: Verdict, *, progressed: bool, counters: Counters, spec: BatchSpec) -> Action:
    """What a diagnosis verdict allows. Code enforces the limits; the agent only proposes."""
    verdict = Verdict(verdict)
    if verdict is Verdict.FACTORY_BUG:
        return Action.RESUME_AFTER_FIX if counters.factory_bug_resumes < spec.max_factory_bug_resumes else Action.RETIRE
    if verdict is Verdict.CLOSE_TO_PASSING:
        allowed = counters.extensions_used < spec.max_extensions
        needs_progress = counters.extensions_used >= 1   # a further extension needs progress
        return Action.EXTEND if allowed and (progressed or not needs_progress) else Action.RETIRE
    return Action.RETIRE


def progressed(before: tuple, after: tuple) -> bool:
    """Gates passed before and after an extension. Progress means the case got further
    (it passes at least one more gate) and nothing it had already passed broke. Gates are
    counted as a set because G10 runs beside other gates, so "further" is not one index."""
    _check(all(g in GATES for g in (*before, *after)), "unknown gate in progress check")
    return set(before) < set(after)


# ---- seams the work packages implement -------------------------------------------------

@dataclass(frozen=True)
class WorkerLease:
    worker_id: str
    case_id: str

    def __post_init__(self):
        _id(self.worker_id, WORKER_ID, "worker_id")
        _id(self.case_id, CASE_ID, "case_id")


class ArtifactStore(Protocol):
    """WP3. scope is the case_id, or the batch_id for BATCH_SCOPED kinds. The store
    encrypts to the scope key and computes Ref.digest with it."""
    def put(self, scope: str, data: bytes, kind: ArtifactKind) -> Ref: ...
    def get(self, scope: str, ref: Ref) -> bytes: ...
    def exists(self, scope: str, ref: Ref) -> bool: ...


class KeyService(Protocol):
    """WP7. Returns the scope key in control-VM memory. Never recorded, never logged."""
    def scope_key(self, scope: str) -> bytes: ...


class WorkerPool(Protocol):
    """WP2. acquire() is idempotent per case: it returns the case's live worker or
    creates one under an idempotency label. Workers are a cache, never state."""
    def acquire(self, case_id: str) -> WorkerLease: ...
    def release(self, lease: WorkerLease) -> None: ...
    def alive(self, lease: WorkerLease) -> bool: ...


class WorkerChannel(Protocol):
    """WP2 (control side) + WP5a (worker side).

    start() delivers the StepInput record and the scope key over the ssh channel's
    stdin. The worker detaches the attempt (systemd-run or setsid) before start()
    returns, so a dropped ssh session or a control-VM restart never stops it. The
    worker writes the finished StepResult record under the idempotency key, and only
    there. start() for a key that already exists does nothing. poll() returns the
    finished result or None while running. Neither method raises on worker errors."""
    def start(self, lease: WorkerLease, step_input: StepInput, scope_key: bytes) -> None: ...
    def poll(self, lease: WorkerLease, idempotency_key: str) -> Optional[StepResult]: ...
    def cancel(self, lease: WorkerLease, idempotency_key: str) -> None: ...


class Ledger(Protocol):
    """WP6. reserve() before a paid attempt holds its ceiling against the batch bound, so
    concurrent cases can never overshoot it together. settle() books actual usage and
    frees the rest. Rebuilt identically on replay (keys are idempotency keys)."""
    def reserve(self, batch_id: str, idempotency_key: str, ceiling_usd_micros: int) -> bool: ...
    def settle(self, idempotency_key: str, usage: Usage) -> None: ...


class StepExecutor(Protocol):
    """Runs one attempt end to end and classifies it into one Outcome. Never raises."""
    def run(self, step_input: StepInput) -> StepResult: ...


def guarded_run(executor: StepExecutor, step_input: StepInput) -> StepResult:
    """The only way the engine calls an executor. An exception would be pickled into the
    engine database and logs with its message, which may hold case content; this keeps
    only a fixed reason code."""
    try:
        result = executor.run(step_input)
    except Exception:
        return StepResult(Outcome.INFRA_ERROR, "engine:executor_raised")
    if not isinstance(result, StepResult):
        return StepResult(Outcome.INFRA_ERROR, "engine:executor_bad_result")
    try:
        check_result_for(step_input.step, result)
    except ContractError:
        return StepResult(Outcome.INFRA_ERROR, "engine:executor_bad_result")
    return result


def wait_seconds(retry_at: float, now: float) -> float:
    """Duration for DBOS.sleep. Always positive: DBOS records nothing for a sleep of zero
    or less, so a replay that reaches the sleep after its wake time would otherwise
    desynchronize the journal (design review 1, finding 1). `now` must come from a step."""
    _finite(retry_at, "retry_at"); _finite(now, "now")
    return max(0.001, retry_at - now)


CONDUCTOR_ENV = ("DBOS__CONDUCTOR_KEY", "DBOS__CONDUCTOR_URL", "DBOS_CONDUCTOR_KEY", "DBOS_CONDUCTOR_URL")


def assert_no_conductor(environ: Mapping[str, str], config: Mapping[str, Any]) -> None:
    """The engine must never connect to DBOS Conductor (hosted console)."""
    present = [k for k in environ if k.upper() in CONDUCTOR_ENV or k.upper().startswith("DBOS__CONDUCTOR")]
    _check(not present, f"conductor environment must be unset: {sorted(present)}")
    _check(not config.get("conductor_key") and not config.get("conductor_url"), "conductor must not be configured")


# ---- strict serialization (what the engine records) ---------------------------------------

def to_record(value: Any) -> Any:
    """Plain JSON-safe form of a contract value, for engine arguments and results."""
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return {k: to_record(v) for k, v in asdict(value).items()}
    if isinstance(value, dict):
        return {k: to_record(v) for k, v in value.items()}
    return value


def _exact(d, cls, name):
    _check(isinstance(d, dict), f"{name} record must be an object")
    _check(set(d) == {f.name for f in fields(cls)}, f"unexpected {name} fields")
    return d


def _ref_from(d):
    return None if d is None else Ref(**_exact(d, Ref, "Ref"))


def step_result_from_record(d: dict) -> StepResult:
    _exact(d, StepResult, "StepResult")
    return StepResult(
        outcome=d["outcome"], reason=d["reason"], usage=Usage(**_exact(d["usage"], Usage, "Usage")),
        snapshot=_ref_from(d["snapshot"]), receipt=_ref_from(d["receipt"]), feedback=_ref_from(d["feedback"]),
        repairable=d["repairable"], retry_at=d["retry_at"], verdict=d["verdict"],
        report=_ref_from(d["report"]), diagnostic=_ref_from(d["diagnostic"]))


def step_input_from_record(d: dict) -> StepInput:
    _exact(d, StepInput, "StepInput")
    return StepInput(**{**d, "step": Step(**_exact(d["step"], Step, "Step")),
                        "snapshot": _ref_from(d["snapshot"]), "feedback": _ref_from(d["feedback"]),
                        "registry": _ref_from(d["registry"])})


def batch_spec_from_record(d: dict) -> BatchSpec:
    _exact(d, BatchSpec, "BatchSpec")
    return BatchSpec(**{**d, "inputs": _ref_from(d["inputs"])})
