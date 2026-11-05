"""Frozen contract shared by every durable-execution work package (version 5).

Only what crosses a package boundary lives here: the records the engine stores, the
worker wire protocol, key derivation, and the seams (protocols) between packages.
Engine policy (what to do after each outcome) is WP1's and lives in policy.py.

The workflow engine (DBOS) records every step argument, result and exception in its
database. Nothing here may carry case content: identifiers, keyed digests, reason
codes from a fixed grammar, and numbers only. Case content lives in encrypted
artifacts, referenced by `Ref`.

Design: docs/designs/durable-execution.md. Pure module: no I/O, no engine import.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from enum import Enum
import hashlib
import hmac
import math
import re
from typing import Any, Mapping, Optional, Protocol

CONTRACT_VERSION = 5

DIGEST = re.compile(r"[0-9a-f]{64}")
CASE_ID = re.compile(r"case-[A-Za-z0-9-]{1,80}")
BATCH_ID = re.compile(r"b-[a-z0-9-]{1,60}")
WORKER_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")
GATE = re.compile(r"G(?:[1-9]|1[0-7])")
# A reason is "<stage>:<code>". The code is lowercase letters and underscores only, so it
# cannot hold a path, a file name, an identifier with digits or dots, or a sentence.
REASON = re.compile(r"(admit|writer|stress|g(?:[1-9]|1[0-7])|seal|diagnosis|infra|router|engine|batch)"
                    r":[a-z][a-z_]{0,31}")


class ContractError(ValueError):
    pass


def _check(cond, message):
    if not cond:
        raise ContractError(message)


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


def _enum(cls, value, name):
    try:
        return cls(value)
    except ValueError:
        raise ContractError(f"unknown {name} {value!r}") from None


# ---- artifacts and keys --------------------------------------------------------------------

class ArtifactKind(str, Enum):
    """What an encrypted artifact holds. Content never leaves the artifact."""
    INPUTS = "inputs"                   # batch: app pin, promise text, rotation
    STATEMENT_REGISTRY = "registry"     # batch: statements already admitted or reserved
    CASE_SNAPSHOT = "case"              # c.case plus the retained c.work subset
    WRITER_FEEDBACK = "feedback"        # findings handed to the next writer round
    GATE_RECEIPT = "receipt"            # private evidence behind the gate verdicts
    FOUNDER_RULING = "ruling"           # the founder's answer to an escalation
    DIAGNOSIS_REPORT = "diagnosis"      # the diagnosis agent's private report
    DIAGNOSTIC = "diagnostic"           # logs and transcripts of one failed attempt
    SEALED_ARCHIVE = "sealed"           # the final G12 archive


BATCH_SCOPED = frozenset({ArtifactKind.INPUTS, ArtifactKind.STATEMENT_REGISTRY})


@dataclass(frozen=True)
class Ref:
    """Pointer to one encrypted artifact. digest = artifact_digest(scope hmac key, plaintext)."""
    digest: str
    kind: ArtifactKind

    def __post_init__(self):
        _id(self.digest, DIGEST, "Ref.digest")
        object.__setattr__(self, "kind", _enum(ArtifactKind, self.kind, "artifact kind"))


def _ref(value, kinds, name):
    if value is None:
        return None
    kinds = (kinds,) if isinstance(kinds, ArtifactKind) else tuple(kinds)
    _check(isinstance(value, Ref), f"{name} must be a Ref")
    _check(value.kind in kinds, f"{name} must be a {'/'.join(k.value for k in kinds)} Ref")
    return value


def hkdf_sha256(key: bytes, info: bytes, length: int = 32, salt: bytes = b"") -> bytes:
    """RFC 5869 HKDF with SHA-256 (stdlib only, so both ends derive identically)."""
    _check(type(key) is bytes and len(key) >= 16, "key must be at least 16 bytes")
    prk = hmac.new(salt or b"\x00" * 32, key, hashlib.sha256).digest()
    out, block, i = b"", b"", 1
    while len(out) < length:
        block = hmac.new(prk, block + info + bytes([i]), hashlib.sha256).digest()
        out += block; i += 1
    return out[:length]


AGE_INFO = b"unbug-durable/age-x25519/v1"
HMAC_INFO = b"unbug-durable/artifact-hmac/v1"


def derive_keys(scope_key: bytes) -> tuple[bytes, bytes]:
    """A scope key is 32 random bytes. Returns (age X25519 secret, artifact HMAC key).

    WP3 encodes the first as an age identity (Bech32 "AGE-SECRET-KEY-1...") and encrypts
    with the `age` CLI already used by the runner. Neither value is ever recorded."""
    _check(type(scope_key) is bytes and len(scope_key) == 32, "scope key must be 32 bytes")
    return hkdf_sha256(scope_key, AGE_INFO), hkdf_sha256(scope_key, HMAC_INFO)


def artifact_digest(hmac_key: bytes, plaintext: bytes) -> str:
    """Ref.digest: stable for identical bytes within one scope, and useless for confirming
    a guessed plaintext or comparing scopes without the key."""
    return hmac.new(hmac_key, plaintext, hashlib.sha256).hexdigest()


# ---- steps -----------------------------------------------------------------------------------

class StepKind(str, Enum):
    ADMIT = "admit"          # choose the bug and admit its statement (batch-serialized)
    WRITER = "writer"        # one writer round, with today's G1 and early checks inside it
    STRESS = "stress"        # one stress round, with today's early reviews inside it
    GATES = "gates"          # today's whole gate pipeline (run.run_gates) on one worker
    DIAGNOSIS = "diagnosis"  # the automatic diagnosis agent (ENGINEERING section 3)
    SEAL = "seal"            # G12: encrypt and retain the archive

    @property
    def numbered(self) -> bool:
        return self in (StepKind.WRITER, StepKind.STRESS, StepKind.GATES)


@dataclass(frozen=True)
class Step:
    kind: StepKind
    round: int = 0   # >= 1 exactly for WRITER, STRESS and GATES (the writer round validated)

    def __post_init__(self):
        object.__setattr__(self, "kind", _enum(StepKind, self.kind, "step kind"))
        _nonneg_int(self.round, "Step.round")
        _check(self.kind.numbered == (self.round >= 1), "round is >= 1 exactly for writer, stress and gates")

    @property
    def name(self) -> str:
        return f"{self.kind.value}:{self.round}" if self.round else self.kind.value


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


EVIDENCE_KINDS = (ArtifactKind.GATE_RECEIPT, ArtifactKind.DIAGNOSTIC, ArtifactKind.DIAGNOSIS_REPORT)


@dataclass(frozen=True)
class StepInput:
    batch_id: str
    case_id: str
    seq: int                     # 1-based, strictly increasing over the case's steps
    step: Step
    attempt: int                 # 1-based, attempts of this seq
    plumbing_version: str        # release current when the attempt starts
    bench_version: str           # bench release the case runs; changed only by a BenchRelease
    inputs: Ref                  # INPUTS: the promise, app pin and rotation
    snapshot: Optional[Ref]      # CASE_SNAPSHOT to restore; None exactly for ADMIT
    deadline_s: float            # wall-clock budget of this attempt on the worker
    money_ceiling_usd_micros: int  # the Grant for this attempt; the worker stops at it (EXHAUSTED)
    feedback: Optional[Ref] = None   # WRITER_FEEDBACK: WRITER steps only
    registry: Optional[Ref] = None   # STATEMENT_REGISTRY: exactly for ADMIT
    ruling: Optional[Ref] = None     # FOUNDER_RULING: STRESS or GATES after an escalation
    evidence: tuple = ()             # GATE_RECEIPT / DIAGNOSTIC / DIAGNOSIS_REPORT: DIAGNOSIS only

    def __post_init__(self):
        _id(self.batch_id, BATCH_ID, "batch_id")
        _id(self.case_id, CASE_ID, "case_id")
        _pos_int(self.seq, "seq")
        _check(isinstance(self.step, Step), "step must be a Step")
        _pos_int(self.attempt, "attempt")
        _id(self.plumbing_version, DIGEST, "plumbing_version")
        _id(self.bench_version, DIGEST, "bench_version")
        _check(self.inputs is not None, "inputs is required")
        _ref(self.inputs, ArtifactKind.INPUTS, "inputs")
        _finite(self.deadline_s, "deadline_s", positive=True)
        _nonneg_int(self.money_ceiling_usd_micros, "money_ceiling_usd_micros")
        k = self.step.kind
        _check((self.snapshot is None) == (k is StepKind.ADMIT), "snapshot is absent exactly for ADMIT")
        _ref(self.snapshot, ArtifactKind.CASE_SNAPSHOT, "snapshot")
        _check(self.feedback is None or k is StepKind.WRITER, "feedback goes only to writer steps")
        _ref(self.feedback, ArtifactKind.WRITER_FEEDBACK, "feedback")
        _check((self.registry is not None) == (k is StepKind.ADMIT), "registry is present exactly for ADMIT")
        _ref(self.registry, ArtifactKind.STATEMENT_REGISTRY, "registry")
        _check(self.ruling is None or k in (StepKind.STRESS, StepKind.GATES), "a ruling goes only to stress or gates")
        _ref(self.ruling, ArtifactKind.FOUNDER_RULING, "ruling")
        _check(type(self.evidence) is tuple, "evidence must be a tuple")
        _check(not self.evidence or k is StepKind.DIAGNOSIS, "evidence goes only to diagnosis")
        for i, r in enumerate(self.evidence):
            _ref(r, EVIDENCE_KINDS, f"evidence[{i}]")

    @property
    def idempotency_key(self) -> str:
        """Identical on a replayed attempt, distinct for every new step, repair or extension."""
        return f"{self.case_id}/{self.seq}/{self.step.name}/{self.attempt}"


@dataclass(frozen=True)
class StepResult:
    outcome: Outcome
    reason: str                        # "<stage>:<code>", e.g. "g5:reference_unsolved"
    usage: Usage = field(default_factory=Usage)
    snapshot: Optional[Ref] = None     # CASE_SNAPSHOT after the step; required for OK
    gate: Optional[str] = None         # GATES: the gate that failed or escalated
    receipt: Optional[Ref] = None      # GATE_RECEIPT: GATES evidence
    feedback: Optional[Ref] = None     # WRITER_FEEDBACK: stress findings, a repairable gate, or extension guidance
    repairable: bool = False           # GATE_FAILED only
    retry_at: Optional[float] = None   # PROVIDER_LIMIT only: epoch seconds of the reset
    verdict: Optional[Verdict] = None  # OK of DIAGNOSIS only
    report: Optional[Ref] = None       # DIAGNOSIS_REPORT
    registry: Optional[Ref] = None     # STATEMENT_REGISTRY: OK of ADMIT only
    archive: Optional[Ref] = None      # SEALED_ARCHIVE: OK of SEAL only
    hard: Optional[bool] = None        # OK of SEAL only: strong calibrators solved zero tries
    diagnostic: Optional[Ref] = None   # DIAGNOSTIC
    passed: tuple = ()                 # GATES only: every gate that passed or was reused in this step

    def __post_init__(self):
        object.__setattr__(self, "outcome", _enum(Outcome, self.outcome, "outcome"))
        _check(type(self.reason) is str and REASON.fullmatch(self.reason) is not None,
               "reason must be '<stage>:<code>' from the fixed grammar, not free text")
        _check(isinstance(self.usage, Usage), "usage must be a Usage")
        _check(type(self.repairable) is bool, "repairable must be a bool")
        _check(self.gate is None or (type(self.gate) is str and GATE.fullmatch(self.gate) is not None), "bad gate")
        _check(type(self.passed) is tuple and all(type(g) is str and GATE.fullmatch(g) for g in self.passed)
               and len(set(self.passed)) == len(self.passed), "passed is a tuple of distinct gate names")
        _check(self.gate is None or self.gate not in self.passed, "a failed or escalated gate did not pass")
        for name, kind in (("snapshot", ArtifactKind.CASE_SNAPSHOT), ("receipt", ArtifactKind.GATE_RECEIPT),
                           ("feedback", ArtifactKind.WRITER_FEEDBACK), ("report", ArtifactKind.DIAGNOSIS_REPORT),
                           ("registry", ArtifactKind.STATEMENT_REGISTRY), ("archive", ArtifactKind.SEALED_ARCHIVE),
                           ("diagnostic", ArtifactKind.DIAGNOSTIC)):
            _ref(getattr(self, name), kind, name)
        o = self.outcome
        _check(o is not Outcome.OK or self.snapshot is not None, "OK carries the snapshot after the step")
        if o is Outcome.PROVIDER_LIMIT:
            _finite(self.retry_at, "retry_at")
        else:
            _check(self.retry_at is None, "retry_at is only for PROVIDER_LIMIT")
        _check(o is Outcome.GATE_FAILED or not self.repairable, "repairable is only for GATE_FAILED")
        _check(not self.repairable or self.feedback is not None, "a repairable gate failure carries feedback")
        _check(o is not Outcome.GATE_FAILED or self.gate is not None, "a gate failure names its gate")
        _check(self.feedback is None or o in (Outcome.OK, Outcome.GATE_FAILED), "feedback only on OK or GATE_FAILED")
        if self.verdict is not None:
            _check(o is Outcome.OK, "verdict only on OK")
            object.__setattr__(self, "verdict", _enum(Verdict, self.verdict, "verdict"))
        _check(self.hard is None or type(self.hard) is bool, "hard must be a bool")
        _check((self.archive is None) == (self.hard is None), "archive and hard come together")
        _check(self.archive is None or o is Outcome.OK, "archive only on OK")


def check_result_for(step: Step, result: StepResult) -> None:
    """Rules that depend on which step produced the result. guarded_run applies them."""
    k, o = step.kind, result.outcome
    if result.feedback is not None:
        allowed = (k is StepKind.STRESS and o is Outcome.OK) or (k is StepKind.GATES and o is Outcome.GATE_FAILED) \
            or (k is StepKind.DIAGNOSIS and result.verdict is Verdict.CLOSE_TO_PASSING)
        _check(allowed, "feedback comes from stress findings, a gate failure, or a close-to-passing diagnosis")
    _check((result.verdict is not None) == (k is StepKind.DIAGNOSIS and o is Outcome.OK),
           "a verdict comes exactly from a successful DIAGNOSIS step")
    _check(o is not Outcome.GATE_FAILED or k is StepKind.GATES, "only the gates step fails as GATE_FAILED")
    _check(result.gate is None or k is StepKind.GATES, "only the gates step names a gate")
    _check(not result.passed or k is StepKind.GATES, "only the gates step reports passed gates")
    _check(result.verdict is not Verdict.CLOSE_TO_PASSING or result.feedback is not None,
           "a close-to-passing verdict carries the extension's writer feedback")
    _check(o is not Outcome.NEEDS_FOUNDER or k in (StepKind.STRESS, StepKind.GATES),
           "only stress review or a gate review escalates")
    _check(o is not Outcome.NEEDS_FOUNDER or k is not StepKind.GATES or result.gate in ("G8", "G9", "G16", "G17"),
           "only the review gates G8, G9, G16 and G17 escalate")
    _check((result.registry is not None) == (k is StepKind.ADMIT and o is Outcome.OK),
           "ADMIT returns the updated registry exactly when it succeeds")
    _check((result.archive is not None) == (k is StepKind.SEAL and o is Outcome.OK),
           "SEAL returns the archive exactly when it succeeds")


# ---- batch input and output ----------------------------------------------------------------

@dataclass(frozen=True)
class BatchSpec:
    """The factory's whole input: which app, which promise, how many cases, which bounds."""
    batch_id: str
    plumbing_version: str        # initial plumbing release; PlumbingRelease rolls it forward
    bench_version: str           # initial bench release; BenchRelease changes it
    app_repo: str                # "owner/name"
    app_commit: str              # exact pinned commit
    inputs: Ref                  # INPUTS
    target_sealed: int           # stop starting cases when this many have sealed
    money_bound_usd_micros: int  # cumulative paid spend across all cases, retries, extensions
    deadline_epoch: float        # no new case or extension starts after this
    max_concurrency: int = 1
    max_cases_started: int = 24  # originals plus replacements; bounds replacement chains
    case_money_usd_micros: int = 50_000_000   # one case's own paid money, extensions excluded (today's default)
    max_writer_rounds: int = 8          # the runner's --rounds is set from this
    max_infra_retries_per_step: int = 5
    max_spent_limits_per_step: int = 50  # limit attempts of one step that each spent money
    max_extensions: int = 5             # ENGINEERING section 3
    max_factory_bug_resumes: int = 3    # ENGINEERING section 3, counted across batches
    step_deadline_s: float = 14_400.0   # default StepInput.deadline_s (agent_timeout today)
    release_worker_after_sleep_s: float = 1_800.0

    def __post_init__(self):
        _id(self.batch_id, BATCH_ID, "batch_id")
        _id(self.plumbing_version, DIGEST, "plumbing_version")
        _id(self.bench_version, DIGEST, "bench_version")
        _check(type(self.app_repo) is str and re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", self.app_repo) is not None,
               "app_repo is owner/name")
        _check(type(self.app_commit) is str and re.fullmatch(r"[0-9a-f]{40}", self.app_commit) is not None,
               "app_commit is a full git sha")
        _check(self.inputs is not None, "inputs is required")
        _ref(self.inputs, ArtifactKind.INPUTS, "inputs")
        for name in ("target_sealed", "max_concurrency", "max_cases_started", "max_writer_rounds",
                     "max_spent_limits_per_step"):
            _pos_int(getattr(self, name), name)
        for name in ("money_bound_usd_micros", "case_money_usd_micros", "max_infra_retries_per_step",
                     "max_extensions", "max_factory_bug_resumes"):
            _nonneg_int(getattr(self, name), name)
        _finite(self.deadline_epoch, "deadline_epoch")
        _finite(self.step_deadline_s, "step_deadline_s", positive=True)
        _finite(self.release_worker_after_sleep_s, "release_worker_after_sleep_s", positive=True)


@dataclass(frozen=True)
class SealedCase:
    """The factory's output for one case. The public scorecard is a report the control VM
    generates from the engine tables (WP1); it is not a worker artifact."""
    case_id: str
    archive: Ref
    hard: bool

    def __post_init__(self):
        _id(self.case_id, CASE_ID, "case_id")
        _check(self.archive is not None, "archive is required")
        _ref(self.archive, ArtifactKind.SEALED_ARCHIVE, "archive")
        _check(type(self.hard) is bool, "hard must be a bool")


# ---- messages the engine waits for (DBOS.send / DBOS.recv) -----------------------------------

class Topic(str, Enum):
    BENCH_RELEASE = "bench_release"        # batch workflow: cases adopt it at their next GATES step
    PLUMBING_RELEASE = "plumbing_release"  # batch workflow: steps started after it use it
    BOUND_RAISED = "bound_raised"          # batch workflow: the founder raised the money bound
    FOUNDER_REPLY = "founder_reply"        # case workflow: the answer to an escalation


@dataclass(frozen=True)
class BenchRelease:
    bench_version: str
    def __post_init__(self): _id(self.bench_version, DIGEST, "bench_version")


@dataclass(frozen=True)
class PlumbingRelease:
    plumbing_version: str
    def __post_init__(self): _id(self.plumbing_version, DIGEST, "plumbing_version")


@dataclass(frozen=True)
class BoundRaised:
    money_bound_usd_micros: int
    def __post_init__(self): _nonneg_int(self.money_bound_usd_micros, "money_bound_usd_micros")


class FounderAction(str, Enum):
    CONTINUE = "continue"   # rerun the escalated step with the ruling as input
    RETIRE = "retire"       # retire the case


@dataclass(frozen=True)
class FounderReply:
    action: FounderAction
    ruling: Optional[Ref] = None   # FOUNDER_RULING, required for CONTINUE

    def __post_init__(self):
        object.__setattr__(self, "action", _enum(FounderAction, self.action, "founder action"))
        _ref(self.ruling, ArtifactKind.FOUNDER_RULING, "ruling")
        _check((self.ruling is not None) == (self.action is FounderAction.CONTINUE), "CONTINUE carries a ruling")


# ---- the worker wire protocol (WP2 control side, WP5a worker side) ---------------------------

WORKER_COMMAND = ("python3", "-B", "factory/durable/worker_step.py")  # + start | poll | cancel; cwd RELEASE_ROOT
WORKER_ROOT = "durable"            # relative to the worker user's home
RELEASE_ROOT = "factory-release"   # relative to the worker user's home; WP2 installs here
RELEASE_MANIFEST = "factory-release/RELEASE.json"
"""RELEASE.json holds exactly {"plumbing_version": ..., "bench_version": ...}. WP2 writes it
at install; WP5a reads it and ends any attempt whose StepInput disagrees with
infra:version_mismatch.

plumbing_version is the sha256 of the uploaded factory bundle (launch.sh's bundle_sha
today). It covers factory/, including the gate code in factory/run.py, so a gate fix ships
as a PlumbingRelease. gate_state fingerprints hash their source inputs, so only the gates
whose code changed rerun.
bench_version is run.bench_manifest() of the clean installed bench (launch.sh's bench_sha
today): the bench tree outside factory/.

Commands, run over `boat ssh` with cwd RELEASE_ROOT:
  start   stdin: start_frame(...) as one JSON object. Prints nothing. Exit 0 once the
          attempt is detached, or its marker already exists (including a cancel
          tombstone). Under one per-case lock, it checks for a live attempt of the same
          case (a unit whose result does not exist yet); if there is one, it writes a
          result at once (INFRA_ERROR "infra:attempt_busy") and exits 0.
  poll    stdin: key_frame(key). Prints one line: json.dumps(to_record(Poll)). Exit 0.
  cancel  stdin: key_frame(key). Creates the attempt marker if missing (a tombstone, so a
          late start does nothing), stops the unit if live, and writes an INFRA_ERROR
          "infra:cancelled" result if none exists. Prints nothing. Exit 0.
Results are written first-wins (link() or O_EXCL, never a plain rename over an existing
file), so an attempt and a cancel can never replace each other's result.
Any other exit status, or unparsable output, is a transport failure (see WorkerChannel).
"""


def key_frame(idempotency_key: str) -> dict:
    """The JSON object `poll` and `cancel` read on stdin."""
    _check(type(idempotency_key) is str and idempotency_key.count("/") == 3, "bad idempotency key")
    return {"key": idempotency_key}


def attempt_id(idempotency_key: str) -> str:
    """Filesystem- and unit-safe name of one attempt on a worker."""
    _check(type(idempotency_key) is str and idempotency_key, "idempotency key required")
    return hashlib.sha256(idempotency_key.encode()).hexdigest()


def attempt_paths(idempotency_key: str) -> dict:
    """Worker-side layout of one attempt, relative to the worker user's home.

    attempt: created with O_EXCL by `start`; its existence is the "already started" marker.
    blobs:   input ciphertexts the control side pushed before `start`, named <digest>.<kind>.age.
    out:     output ciphertexts the worker wrote, named the same way; fetched after DONE.
    result:  the StepResult record, written once and first-wins (see RELEASE_MANIFEST notes).
    unit:    the systemd unit (or setsid process-group name) of the detached attempt."""
    a = attempt_id(idempotency_key)
    return {"attempt": f"{WORKER_ROOT}/attempts/{a}", "blobs": f"{WORKER_ROOT}/blobs",
            "out": f"{WORKER_ROOT}/attempts/{a}/out", "result": f"{WORKER_ROOT}/results/{a}.json",
            "unit": f"durable-{a[:16]}"}


def start_frame(step_input: StepInput, keys: Mapping[str, bytes]) -> dict:
    """The one JSON object `start` reads on stdin. keys: scope -> 32-byte scope key, holding
    the case scope and, for ADMIT, the batch scope. Keys travel only in this frame."""
    import base64
    _check(step_input.case_id in keys, "the case scope key is required")
    _check(step_input.step.kind is not StepKind.ADMIT or step_input.batch_id in keys, "ADMIT needs the batch key")
    _check(set(keys) <= {step_input.case_id, step_input.batch_id}, "only the case and batch keys may travel")
    for k in keys.values():
        _check(type(k) is bytes and len(k) == 32, "scope keys are 32 bytes")
    return {"input": to_record(step_input), "keys": {s: base64.b64encode(k).decode() for s, k in keys.items()}}


class PollState(str, Enum):
    RUNNING = "running"   # the attempt is live, or the worker could not be reached (bounded by the deadline)
    DONE = "done"         # the result record exists
    ABSENT = "absent"     # the worker answered: no result and no live unit (never started, or lost)


@dataclass(frozen=True)
class Poll:
    state: PollState
    result: Optional[StepResult] = None
    checkpoint: Optional[Ref] = None   # latest in-step CASE_SNAPSHOT (WP5f); a retry may restore it

    def __post_init__(self):
        object.__setattr__(self, "state", _enum(PollState, self.state, "poll state"))
        _check((self.result is not None) == (self.state is PollState.DONE), "a result exactly when DONE")
        _ref(self.checkpoint, ArtifactKind.CASE_SNAPSHOT, "checkpoint")


# ---- seams the work packages implement -------------------------------------------------------

@dataclass(frozen=True)
class WorkerLease:
    worker_id: str
    case_id: str

    def __post_init__(self):
        _id(self.worker_id, WORKER_ID, "worker_id")
        _id(self.case_id, CASE_ID, "case_id")


@dataclass(frozen=True)
class Classified:
    outcome: Outcome
    reason: str
    retry_at: Optional[float] = None

    def __post_init__(self):
        StepResult(self.outcome, self.reason, retry_at=self.retry_at,
                   snapshot=Ref("0" * 64, ArtifactKind.CASE_SNAPSHOT) if self.outcome is Outcome.OK else None,
                   gate="G1" if self.outcome is Outcome.GATE_FAILED else None)   # same shape rules


class Classifier(Protocol):
    """WP4. stop is the runner's BudgetError text or card terminal_stop, e.g.
    "provider_limit:opencode-go/mimo-v2.6-pro". The result never echoes stop text."""
    def __call__(self, stop: str, *, step: StepKind, now: float) -> Classified: ...


class ArtifactStore(Protocol):
    """WP3, control VM only. Holds ciphertext, never sees keys or plaintext. Workers never
    reach it: the channel moves blobs over ssh (workers hold no R2 credentials)."""
    def put_sealed(self, scope: str, ref: Ref, ciphertext: bytes) -> None: ...
    def get_sealed(self, scope: str, ref: Ref) -> bytes: ...
    def exists(self, scope: str, ref: Ref) -> bool: ...


class Sealer(Protocol):
    """WP3, used on both sides. Encrypts with the age identity from derive_keys(scope_key)
    and names the result with artifact_digest."""
    def seal(self, scope_key: bytes, kind: ArtifactKind, plaintext: bytes) -> tuple[Ref, bytes]: ...
    def open(self, scope_key: bytes, ref: Ref, ciphertext: bytes) -> bytes: ...


class KeyService(Protocol):
    """WP7. Returns a 32-byte scope key in control-VM memory. Never recorded or logged."""
    def scope_key(self, scope: str) -> bytes: ...


class WorkerPool(Protocol):
    """WP2. acquire() is idempotent per case. It returns the case's live worker with the
    requested release installed and verified, or provisions one under an idempotency label.
    Workers are a cache, never state."""
    def acquire(self, case_id: str, plumbing_version: str, bench_version: str) -> WorkerLease: ...
    def release(self, lease: WorkerLease) -> None: ...
    def alive(self, lease: WorkerLease) -> bool: ...


class WorkerChannel(Protocol):
    """WP2. Runs WORKER_COMMAND over `boat ssh` with the attempt_paths layout.

    start(): pushes the input blobs, then sends start_frame on stdin. The worker detaches
    the attempt before replying. A start for an existing attempt does nothing.
    poll(): returns RUNNING, DONE with the result, or ABSENT. It fetches DONE output blobs
    into the ArtifactStore before returning.
    A transport failure (ssh error, bad exit status, unparsable output) is RUNNING, never
    ABSENT, so a network flake can never start a second attempt beside a live one. The
    engine bounds RUNNING by deadline_s plus a grace period, then calls cancel().
    ABSENT is returned only when the worker answered and has neither a result nor a live
    unit. Before starting attempt n+1 of a seq, the engine cancels attempt n.
    No method raises on worker errors."""
    def start(self, lease: WorkerLease, step_input: StepInput, keys: Mapping[str, bytes],
              blobs: Mapping[str, bytes]) -> None: ...
    def poll(self, lease: WorkerLease, step_input: StepInput) -> Poll: ...
    def cancel(self, lease: WorkerLease, step_input: StepInput) -> None: ...


class LimitedBy(str, Enum):
    NOTHING = "nothing"   # the whole request was granted
    CASE = "case"         # the case's own money ran short: exhausting it is a case outcome
    BATCH = "batch"       # the batch bound ran short: using it all waits for any settle or BOUND_RAISED


@dataclass(frozen=True)
class Grant:
    amount_usd_micros: int
    limited_by: LimitedBy

    def __post_init__(self):
        _nonneg_int(self.amount_usd_micros, "Grant.amount_usd_micros")
        object.__setattr__(self, "limited_by", _enum(LimitedBy, self.limited_by, "limit"))


class Ledger(Protocol):
    """WP6. Lives in the engine database. There are no per-step price caps: no evidence
    prices a step, and a cap would turn plumbing into a case result.

    Which money an attempt draws on:
      - Ordinary steps (ADMIT, WRITER, STRESS, GATES and SEAL outside an extension) draw
        on the case's own money AND the batch bound: draws_case_money=True. The engine
        requests case_money_usd_micros; the ledger caps it.
      - DIAGNOSIS and every step of an extension draw on the batch bound only:
        draws_case_money=False (ENGINEERING section 3; Stream D). The engine requests the
        batch's remaining bound, or a smaller figure WP1 sets in its note.
    reserve() grants min(requested, the case's remaining money if drawn, the batch's
    remaining bound) and holds it before the attempt starts, so concurrent cases can never
    overshoot. Labels: BATCH whenever the batch's remaining bound is at or below the
    granted amount; otherwise CASE whenever the case's remaining money capped the grant;
    otherwise NOTHING. A repeated reserve() on the same key returns the original Grant,
    unchanged even after raise_bound().
    settle() books the real usage and frees the rest of the grant. With waste=True the
    usage is booked to the batch only, never against the case's own money: the engine
    passes it for INFRA_ERROR results, for PROVIDER_LIMIT results that spent money, and
    for cancelled or busy attempts (broken runs are never scored, ENGINEERING section 3).
    settle_lost() books the whole grant as waste for an attempt that produced no usage.
    Every call is idempotent on the idempotency key, so replay rebuilds the same ledger."""
    def open(self, batch_id: str, bound_usd_micros: int) -> None: ...
    def raise_bound(self, batch_id: str, bound_usd_micros: int) -> None: ...
    def reserve(self, batch_id: str, case_id: str, idempotency_key: str, requested_usd_micros: int,
                case_limit_usd_micros: int, *, draws_case_money: bool = True) -> Grant: ...
    def settle(self, idempotency_key: str, usage: Usage, *, waste: bool = False) -> None: ...
    def settle_lost(self, idempotency_key: str) -> None: ...


class StepExecutor(Protocol):
    """WP1 composes pool, channel, ledger, store and keys into one. Runs one attempt end to
    end and classifies it into one Outcome. Never raises."""
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
    """Duration for DBOS.sleep. Always positive: DBOS records nothing for sleep(<=0), so a
    replay that reaches the sleep after its wake time would otherwise lose its place
    (design review 1, finding 1). `now` must come from a step."""
    _finite(retry_at, "retry_at"); _finite(now, "now")
    return max(0.001, retry_at - now)


CONDUCTOR_ENV = ("DBOS__CONDUCTOR_KEY", "DBOS__CONDUCTOR_URL", "DBOS_CONDUCTOR_KEY", "DBOS_CONDUCTOR_URL",
                 "DBOS__CLOUD")


def assert_no_conductor(environ: Mapping[str, str], config: Mapping[str, Any]) -> None:
    """Before construction: the engine must never connect to DBOS Conductor or run in
    DBOS Cloud mode. WP1 also checks the constructed instance (conductor_key is None)."""
    present = [k for k in environ if k.upper() in CONDUCTOR_ENV or k.upper().startswith("DBOS__CONDUCTOR")]
    _check(not present, f"conductor environment must be unset: {sorted(present)}")
    _check(not config.get("conductor_key") and not config.get("conductor_url"), "conductor must not be configured")


# ---- strict serialization (what the engine records) ------------------------------------------

def to_record(value: Any) -> Any:
    """Plain JSON-safe form of a contract value, for engine arguments and results."""
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return {f.name: to_record(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, dict):
        return {k: to_record(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [to_record(v) for v in value]
    return value


def _exact(d, cls, name):
    _check(isinstance(d, dict), f"{name} record must be an object")
    _check(set(d) == {f.name for f in fields(cls)}, f"unexpected {name} fields")
    return d


def _ref_from(d):
    return None if d is None else Ref(**_exact(d, Ref, "Ref"))


def step_result_from_record(d: dict) -> StepResult:
    _exact(d, StepResult, "StepResult")
    refs = ("snapshot", "receipt", "feedback", "report", "registry", "archive", "diagnostic")
    _check(isinstance(d["passed"], list), "passed record must be a list")
    return StepResult(**{**d, "usage": Usage(**_exact(d["usage"], Usage, "Usage")),
                         **{k: _ref_from(d[k]) for k in refs}, "passed": tuple(d["passed"])})


def step_input_from_record(d: dict) -> StepInput:
    _exact(d, StepInput, "StepInput")
    _check(isinstance(d["evidence"], list), "evidence record must be a list")
    return StepInput(**{**d, "step": Step(**_exact(d["step"], Step, "Step")),
                        **{k: _ref_from(d[k]) for k in ("inputs", "snapshot", "feedback", "registry", "ruling")},
                        "evidence": tuple(_ref_from(r) for r in d["evidence"])})


def batch_spec_from_record(d: dict) -> BatchSpec:
    _exact(d, BatchSpec, "BatchSpec")
    return BatchSpec(**{**d, "inputs": _ref_from(d["inputs"])})


def poll_from_record(d: dict) -> Poll:
    _exact(d, Poll, "Poll")
    return Poll(state=d["state"], result=None if d["result"] is None else step_result_from_record(d["result"]),
                checkpoint=_ref_from(d["checkpoint"]))
