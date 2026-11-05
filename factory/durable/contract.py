"""Frozen contract shared by every durable-execution work package.

Everything here is recorded by the workflow engine (DBOS stores step arguments
and results in its database), so nothing here may carry case content. Case
content lives only in encrypted artifacts, referenced by sha256. The
constructors enforce that: identifiers, hashes and short reason codes only.

Design: docs/designs/durable-execution.md. Pure module: no I/O, no engine import.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from enum import Enum
import math
import re
from typing import Any, Optional, Protocol

CONTRACT_VERSION = 1

SHA = re.compile(r"[0-9a-f]{64}")
CODE = re.compile(r"[a-z0-9][a-z0-9_.:/-]{0,79}")
CASE_ID = re.compile(r"case-[A-Za-z0-9-]{1,80}")
BATCH_ID = re.compile(r"b-[a-z0-9-]{1,60}")

# Copy of run.GATES (cheap rejectors first); tests/factory/test_durable_contract.py
# fails if the two differ. G12 (seal) is the SEAL step, not a gate step.
GATES = ("G1", "G2", "G3", "G4", "G5", "G16", "G8", "G9", "G6",
         "G13", "G14", "G15", "G7", "G10", "G17", "G11")


def _code(value, name):
    if type(value) is not str or not CODE.fullmatch(value):
        raise ValueError(f"{name} must be a short reason code, not free text")
    return value


def _sha(value, name):
    if type(value) is not str or not SHA.fullmatch(value):
        raise ValueError(f"{name} must be a sha256 hex digest")
    return value


def _nonneg_int(value, name):
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a non-negative int")
    return value


class ArtifactKind(str, Enum):
    """What an encrypted artifact holds. Content never leaves the artifact."""
    INPUTS = "inputs"            # batch inputs: app pin, promise text, rotation
    CASE_SNAPSHOT = "case"       # the case tree after a step
    WRITER_FEEDBACK = "feedback"  # gate findings handed to the next writer round
    GATE_RECEIPT = "receipt"     # private evidence behind one gate verdict
    DIAGNOSTIC = "diagnostic"    # logs/transcripts for one failed attempt
    SEALED_ARCHIVE = "sealed"    # the final G12 archive
    SCORECARD = "scorecard"      # the founder-visible public card


@dataclass(frozen=True)
class Ref:
    """Pointer to one encrypted, content-addressed artifact in the object store."""
    sha256: str
    kind: ArtifactKind

    def __post_init__(self):
        _sha(self.sha256, "Ref.sha256")
        object.__setattr__(self, "kind", ArtifactKind(self.kind))


class StepKind(str, Enum):
    ADMIT = "admit"          # choose the bug and admit its statement
    WRITER = "writer"        # one writer round
    STRESS = "stress"        # one stress (attacker) round
    GATE = "gate"            # one gate in GATES
    SEAL = "seal"            # G12: encrypt, hash, publish scorecard


@dataclass(frozen=True)
class Step:
    kind: StepKind
    gate: Optional[str] = None   # set only for GATE
    round: int = 0               # writer/stress round number, else 0

    def __post_init__(self):
        object.__setattr__(self, "kind", StepKind(self.kind))
        if (self.kind is StepKind.GATE) != (self.gate is not None):
            raise ValueError("gate is set exactly for GATE steps")
        if self.gate is not None and self.gate not in GATES:
            raise ValueError(f"unknown gate {self.gate!r}")
        _nonneg_int(self.round, "Step.round")
        if (self.kind in (StepKind.WRITER, StepKind.STRESS)) != (self.round >= 1):
            raise ValueError("round is >= 1 exactly for writer and stress steps")

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
    OK = "ok"                          # result committed; run the next step
    INFRA_ERROR = "infra_error"        # retry; never scored, never writer feedback
    PROVIDER_LIMIT = "provider_limit"  # durable sleep until retry_at; no worker held
    GATE_FAILED = "gate_failed"        # a scored rejection by a gate
    EXHAUSTED = "exhausted"            # the case's own round or money bound ran out
    NEEDS_FOUNDER = "needs_founder"    # reviewers genuinely disagree about the case


@dataclass(frozen=True)
class StepInput:
    batch_id: str
    case_id: str
    step: Step
    attempt: int                 # 1-based, counts every attempt of this step
    code_version: str            # batch release digest the attempt runs under
    snapshot: Optional[Ref]      # case tree before the step; None only for ADMIT
    feedback: Optional[Ref] = None  # writer feedback, WRITER steps only

    def __post_init__(self):
        if type(self.batch_id) is not str or not BATCH_ID.fullmatch(self.batch_id):
            raise ValueError("bad batch_id")
        if type(self.case_id) is not str or not CASE_ID.fullmatch(self.case_id):
            raise ValueError("bad case_id")
        if type(self.attempt) is not int or self.attempt < 1:
            raise ValueError("attempt is 1-based")
        _sha(self.code_version, "code_version")
        if (self.snapshot is None) != (self.step.kind is StepKind.ADMIT):
            raise ValueError("snapshot is absent exactly for ADMIT")
        if self.feedback is not None and self.step.kind is not StepKind.WRITER:
            raise ValueError("feedback goes only to writer steps")

    @property
    def idempotency_key(self) -> str:
        """Same key on a replayed attempt, so a worker can return a finished result."""
        return f"{self.case_id}/{self.step.name}/{self.attempt}"


@dataclass(frozen=True)
class StepResult:
    outcome: Outcome
    reason: str                       # short code, e.g. "pass", "opencode_error", "rounds"
    usage: Usage = field(default_factory=Usage)
    snapshot: Optional[Ref] = None    # case tree after the step (OK, GATE_FAILED)
    receipt: Optional[Ref] = None     # gate evidence (GATE steps)
    feedback: Optional[Ref] = None    # writer feedback (GATE_FAILED when repairable)
    repairable: bool = False          # GATE_FAILED: may the writer repair it?
    retry_at: Optional[float] = None  # PROVIDER_LIMIT: epoch seconds of the reset
    diagnostic: Optional[Ref] = None  # private logs for a failed attempt

    def __post_init__(self):
        object.__setattr__(self, "outcome", Outcome(self.outcome))
        _code(self.reason, "reason")
        o = self.outcome
        if o is Outcome.OK and self.snapshot is None:
            raise ValueError("OK carries the snapshot after the step")
        if o is Outcome.PROVIDER_LIMIT:
            if type(self.retry_at) not in (int, float) or not math.isfinite(self.retry_at):
                raise ValueError("PROVIDER_LIMIT carries a finite retry_at")
        elif self.retry_at is not None:
            raise ValueError("retry_at is only for PROVIDER_LIMIT")
        if o is Outcome.GATE_FAILED:
            if self.repairable and self.feedback is None:
                raise ValueError("a repairable gate failure carries writer feedback")
        elif self.repairable or self.feedback is not None:
            raise ValueError("feedback and repairable are only for GATE_FAILED")
        for name in ("snapshot", "receipt", "feedback", "diagnostic"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, Ref):
                raise ValueError(f"{name} must be a Ref")


@dataclass(frozen=True)
class BatchSpec:
    """The factory's whole input: which app, which promise, how many cases, which bounds.

    The promise text and rotation sit in the INPUTS artifact; the spec holds its hash.
    """
    batch_id: str
    release_digest: str          # one immutable release for every case in the batch
    app_repo: str                # e.g. "medusajs/medusa"
    app_commit: str              # exact pinned commit
    inputs: Ref                  # INPUTS artifact: promise, rotation, case contract
    target_sealed: int           # stop when this many cases have sealed
    money_bound_usd_micros: int  # cumulative paid spend across all cases and retries
    deadline_epoch: float        # no new case starts after this
    max_concurrency: int = 1
    max_infra_retries_per_step: int = 5
    max_factory_bug_resumes: int = 3
    max_writer_rounds: int = 6

    def __post_init__(self):
        if type(self.batch_id) is not str or not BATCH_ID.fullmatch(self.batch_id):
            raise ValueError("bad batch_id")
        _sha(self.release_digest, "release_digest")
        if type(self.app_repo) is not str or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", self.app_repo):
            raise ValueError("app_repo is owner/name")
        if type(self.app_commit) is not str or not re.fullmatch(r"[0-9a-f]{40}", self.app_commit):
            raise ValueError("app_commit is a full git sha")
        if not isinstance(self.inputs, Ref) or self.inputs.kind is not ArtifactKind.INPUTS:
            raise ValueError("inputs is an INPUTS Ref")
        for name in ("target_sealed", "max_concurrency", "max_writer_rounds"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError(f"{name} must be a positive int")
        for name in ("money_bound_usd_micros", "max_infra_retries_per_step", "max_factory_bug_resumes"):
            _nonneg_int(getattr(self, name), name)
        if type(self.deadline_epoch) not in (int, float) or not math.isfinite(self.deadline_epoch):
            raise ValueError("deadline_epoch must be finite")


@dataclass(frozen=True)
class SealedCase:
    """The factory's output for one case."""
    case_id: str
    archive: Ref
    scorecard: Ref
    hard: bool                   # strong calibrators solved zero tries (G10/G17)

    def __post_init__(self):
        if type(self.case_id) is not str or not CASE_ID.fullmatch(self.case_id):
            raise ValueError("bad case_id")
        if self.archive.kind is not ArtifactKind.SEALED_ARCHIVE or self.scorecard.kind is not ArtifactKind.SCORECARD:
            raise ValueError("archive and scorecard Refs have the wrong kinds")


# ---- seams the work packages implement -------------------------------------------------

class ArtifactStore(Protocol):
    """WP3. Encrypted, content-addressed. put() of identical bytes returns the same Ref."""
    def put(self, data: bytes, kind: ArtifactKind) -> Ref: ...
    def get(self, ref: Ref) -> bytes: ...
    def exists(self, ref: Ref) -> bool: ...


class StepExecutor(Protocol):
    """WP2 (where) + WP5 (what). Runs one attempt and classifies it into one Outcome.

    Must be idempotent on StepInput.idempotency_key: called again for the same key
    (the control VM crashed mid-step), it returns the finished result or reattaches
    to the running attempt instead of starting a second one.
    """
    def run(self, step_input: StepInput) -> StepResult: ...


# ---- the case state machine --------------------------------------------------------------

class Action(str, Enum):
    ADVANCE = "advance"      # move to the next step with result.snapshot
    RETRY = "retry"          # same step, attempt + 1, same input snapshot
    SLEEP = "sleep"          # durable sleep until result.retry_at, then RETRY
    REPAIR = "repair"        # next writer round with result.feedback
    RETIRE = "retire"        # stop this case; the batch starts a replacement now
    DIAGNOSE = "diagnose"    # infra retries exhausted: factory-bug hold + replacement
    ESCALATE = "escalate"    # park the case for the founder; the batch continues


def decide(result: StepResult, *, step_infra_errors: int, writer_rounds_used: int,
           spec: BatchSpec) -> Action:
    """Pure policy for one finished attempt. Counts come from the journal, never a worker.

    step_infra_errors counts INFRA_ERROR attempts of this step, this one included.
    """
    o = result.outcome
    if o is Outcome.OK:
        return Action.ADVANCE
    if o is Outcome.PROVIDER_LIMIT:
        return Action.SLEEP                      # waiting costs no allowance
    if o is Outcome.INFRA_ERROR:
        return Action.RETRY if step_infra_errors <= spec.max_infra_retries_per_step else Action.DIAGNOSE
    if o is Outcome.GATE_FAILED:
        if result.repairable and writer_rounds_used < spec.max_writer_rounds:
            return Action.REPAIR
        return Action.RETIRE
    if o is Outcome.EXHAUSTED:
        return Action.RETIRE
    if o is Outcome.NEEDS_FOUNDER:
        return Action.ESCALATE
    raise AssertionError(o)


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


def _ref(d):
    return None if d is None else Ref(**d)


def step_result_from_record(d: dict) -> StepResult:
    if set(d) != {f.name for f in fields(StepResult)}:
        raise ValueError("unexpected StepResult fields")
    return StepResult(
        outcome=d["outcome"], reason=d["reason"], usage=Usage(**d["usage"]),
        snapshot=_ref(d["snapshot"]), receipt=_ref(d["receipt"]), feedback=_ref(d["feedback"]),
        repairable=d["repairable"], retry_at=d["retry_at"], diagnostic=_ref(d["diagnostic"]))


def step_input_from_record(d: dict) -> StepInput:
    if set(d) != {f.name for f in fields(StepInput)}:
        raise ValueError("unexpected StepInput fields")
    return StepInput(batch_id=d["batch_id"], case_id=d["case_id"], step=Step(**d["step"]),
                     attempt=d["attempt"], code_version=d["code_version"],
                     snapshot=_ref(d["snapshot"]), feedback=_ref(d["feedback"]))
