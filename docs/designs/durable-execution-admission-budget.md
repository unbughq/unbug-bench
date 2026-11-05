# Budget-aware case admission, revision 3

Status: proposed for fresh independent review. Applies to WP1; the frozen v5
contract remains unchanged. Revision 1 failed review; revision 2's deadline
interpretation received a narrow independent review in
`docs/reviews/durable-execution-admission-budget-design-2.md`.

## Problem and boundary

The batch starts replacements without consulting the money bound. A balance read
alone races concurrent reservations. `Ledger.reserve` already serializes holds.
We define **case admission** as the recorded decision to allocate its first ADMIT
grant, not the later scheduling of its DBOS workflow or its first model call. The
deadline cutoff is the clock read belonging to the probe execution whose ADMITTED
decision is recorded. A crash before that read is recorded re-reads the clock; a
crash after the decision may create one admitted case after the deadline. The case
ID, first attempt number, and grant are part of that decision. This is a cost choice:
DBOS records time separately from starting a child, and an ordinary queued ADMIT can
already make its first paid call after the deadline. At most one admission is between
its decision and child creation per crash because probes are serialized. The hold
counts against the batch bound.

## The admission decision

The batch is the sole arbiter and handles one pending request at a time. Candidate
IDs use the next `case-<batch>-<n>`; the number advances only on successful
admission. Probe attempt numbers increase for that candidate after each failed
probe; a successful number becomes the case's first ADMIT attempt. Initial requests
and replacements are durable workflow-local state reconstructed by DBOS replay.
Replacements take priority over pending originals; the finite `max_cases_started`
limits the queue. A case may request only one replacement.

An admission probe calls the existing recorded `reserve_step` for the actual first
ADMIT key, then records a clock read with `now_step`. If the read is at/after the
deadline, it settles the unstarted key at zero and returns EXPIRED. If the reserve
completed but its result was not recorded before a crash, replay reserves the same
key; no child can yet exist. If the clock read was recorded, replay uses that same
decision before any zero settlement, even if the system clock moves backwards. A
BATCH grant below the existing minimum is settled at zero and returns WAIT. These
probe settlements generate no wake event. A positive ordinary grant, or an allowed
sub-minimum NOTHING grant, yields ADMITTED. For `case_money_usd_micros=0`, no ADMIT
can buy a model call: the batch stops admission without starting a worker,
independently of batch balance. The post-reserve clock read is the deadline
authority; any earlier `admission_open()` clock read is only a fast path.

Once the probe reaches ADMITTED, replay keeps that grant: the batch never settles
it at zero on a guess. The child may be created after a restart and deadline.

The next operation is `DBOS.start_workflow` with the deterministic case ID and
successful attempt number. DBOS 3.4 persists a child workflow and its parent's
operation in one transaction (`dbos._core._init_workflow`); on replay it attaches
to that child. The case's ADMIT uses the same key and calls `reserve` idempotently.
No separate release/re-reserve handoff occurs. The batch does not wrap or retry
`start_workflow`: DBOS retries connection failures and replay handles crashes. Any
other exception fails the batch with the hold intact; it is never settled on a
guess. A confirmed workflow failure must not cause an immediate zero settlement:
first reconcile its attempt workflow. If an attempt is still pending or running,
wait for it to settle. If it failed before dispatch with proof no attempt started,
settle zero; if dispatch or usage is uncertain, settle lost. The recovery path must
not allow a later execution to use a grant after either settlement. If that cannot
be established through DBOS records, keep the hold and report `engine_error` rather
than release it speculatively. This preserves the money bound at the cost of manual
investigation for an unexpected unrecoverable DBOS error.

## Ordering and wakeups

The batch serializes decisions. A decision linearizes at the successful recorded
probe; STOP_ADMISSION, target reached, deadline, or max cases already processed by
that point forbids it. Events that arrive later are ordered after it. To prevent an
attempt settlement from waking pending admissions before its terminal result is
processed, settlement events carry case and step. ADMIT and SEAL settlements raise
a per-case barrier; the batch clears it only after the case has either reported
STOP_ADMISSION / sealed `done`, or explicitly acknowledged that its attempt was
nonterminal. No pending admission is decided while such a barrier is outstanding.
A failed case clears its barrier only after failure reconciliation. The barrier is
tracked in batch workflow state and reconstructed by replay. Settlement from a probe
never wakes pending requests. Real settlements, bound raises and a bounded batch
poll can retry them, so no-money polling cannot trigger an immediate self-loop.

For a diagnosis-triggering stop, the case sends `line_stopped` and waits for the
batch's acknowledgement before enqueuing diagnosis. The batch acknowledges when
its one replacement is admitted, or when an already-effective stop, deadline,
target, or case limit rules it out. When money is unavailable, both the replacement
and the original wait for the bound, so diagnosis cannot reserve ahead of it. Other
already-running attempts retain their holds and can finish; pending replacements
are finite and take priority over pending originals. This is the budget-qualified
meaning of ENGINEERING's replacement-before-diagnosis rule. Escalation and retirement
use the same acknowledgement so a replacement cannot be duplicated on replay.

When no cases have yet been admitted, pending work keeps the batch workflow alive
until money arrives or the deadline/stop makes admission impossible. When all cases
finish, pending requests are retained only while they can still be admitted. A
bound raise wakes both pending admissions and existing bound waiters. If the target,
STOP_ADMISSION, deadline or maximum prevents a pending request, discard it and send
any required acknowledgement; no grant may remain held for a rejected request.

## Files and tests

- `factory/durable/engine.py`: admission probe using the existing reserve, clock and
  zero-settle steps; pending state; barrier/ack messages; start/replay reconciliation;
  and the case's first ADMIT number. No `contract.py` edit and no new balance API.
- `tests/factory/test_durable_engine.py`: exhausted bound with another case's hold;
  a bound raise; real-settle wake; no self-wake loop; target and STOP_ADMISSION
  interleavings; replacement vs diagnosis with only one grant; zero case money;
  and an existing case making progress under finite pending admissions.
- `tests/factory/test_durable_engine_exam.py` and
  `tests/factory/test_durable_admission_recovery.py`: kill before and after the
  reservation record, clock record and child start, including recovery past the
  deadline. After an ADMITTED decision, assert no second probe or reserve row,
  exactly one late-created case workflow, the same held key until ADMIT settles,
  no replacement or extension, and one child-start operation. Stall the step record
  until after the deadline to cover a pre-deadline clock read recorded later. Assert
  no released grant is reused and no duplicate worker execution or over-bound hold.
- Finish with the full suite required by ENGINEERING, followed by a fresh diff review.

## Cost, risks, and Murphy rows

This adds one ledger reservation before each admitted case and extra control-only
messages; it starts no paid calls by itself. Replacements may consume a reservation
before their worker is scheduled, delaying other cases, and a genuinely ambiguous
unrecoverable failure retains a hold until investigated. The strict deadline applies
to durable admission rather than physical worker scheduling, as described above.
Implementation and replay tests are not yet timed; the parent design's release and
final-exam estimates remain unchanged and these additional tests may extend them.
Targets Murphy rows 18 and 51; closes neither without the real final-exam artifacts.
