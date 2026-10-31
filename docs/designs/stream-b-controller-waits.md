# Stream B: schedule retired provider waits

## Problem and scope

When a case pauses for a provider limit, an operator must currently restart it.
This change schedules that restart after the provider retry time passes.

The holder reconciles, resumes orphan controllers and replays publication, but
nobody reserves the next worker after a provider-wait checkpoint is published
and retired. This increment completes that controller scheduling path using
existing reservation authority. It follows stream-b-practice-blockers.md; the
founder now approves $25 all-in for a later practice, not launches in this task.
Controller work goes first as requested. No VM mutation, paid calls, activation,
legacy ownership resolution, cleanup supervisor or router provisioning here.
HOLDER_ENABLED and DIAGNOSIS_ENABLED remain false.

## Change

Add batch_holder.schedule_waits, called by key_holder.batch_tick after reconcile
and before orphan/publication scans. It examines durable operations, selecting
only launched, incident-free, retired operations with an output generation and
no existing successor operation for that job/source/release. It calls the ordinary
reserve path as reserve(..., provider_wait=True), a new keyword defaulting to
False. Before calling reserve, read only the frozen scorecard and apply the same
wait predicate as a cheap skip-only filter; a future wait never hashes archives. The next tick's
ordinary reconcile discovers and dispatches the new pending operation. No spawn,
network call, new journal schema, queue, timer or money owner is introduced.
The scan returns an empty list and is inserted in the scan loop with no child
action. A scan-level failure uses the existing batch scan refused label; an individual refusal is skipped
so other candidates can proceed. Existing status reports remain authoritative.

Inside reserve's batch lock, before advancing money, re-read _source: the matching
ACK, authority, retirement, current pointer, acknowledged outbox and verified
immutable collection must all agree. For the scheduler, additionally require
terminal_stop == provider_wait and a dict provider_wait projection. Require a
canonical version-4 UUID wait_id, reason in model_router.REASONS minus unbounded_route, evidence denied_before_work
or interrupted, and UTC retry_after and batch_deadline parsed with money.deadline. The projected
batch deadline must equal the frozen manifest deadline. Retry time must be due
and strictly before the batch deadline. Invalid/missing projections refuse, never
infer a retry time. Role/route/account remain transport hints, never admission.
With provider_wait=True, reject a null source and an already existing operation
before reserve's idempotent return. Check the verified card returned by _source
before advance_locked; recheck the predecessor is incident-free in this lock.
Catch (OSError, ValueError, KeyError, TypeError, AttributeError) per candidate
(MoneyWait inherits ValueError); let whole-scan read failures propagate.
credential_expiring remains retryable: A uses it for a router-selected credential
absent from the worker bundle, and fresh dispatch reloads held credentials and
account selection. It does not authorize an expired credential or account 1;
the router checks eligibility again. Unbounded routes require policy repair.
The manual reserve path remains available for other checkpoint stop classes.

Reuse operation_id(policy, job, source), which includes the policy release as the durable predecessor-successor
link. A saved successor, even failed or retired, consumes this source forever;
do not retry it under a new ID. Reuse reserve's crash repair: money may advance
before config/reservation writes; replay from the predecessor recreates that same
successor and authority without another money advance. Lost reservation replies
are harmless. Reservations written before journal repair are authoritative.
No process-local wait or children map is needed to remember retry_after across
holder restarts. Existing operation locks and dispatch_started handle transport
uncertainty; never reset them. Existing concurrency, batch deadline, aggregate
money freeze and owner hold remain enforced by reserve and _post. Router admission
and interrupted usage settlement remain worker responsibilities before invocation.
The legacy same-worker batch guard remains unchanged.

This removes the need for an operator to submit each eligible provider-wait
successor. It deletes no legacy launcher yet. Infrastructure lifetime and charges
across successors are deliberately NOT claimed bounded by this scheduler: delayed
creation cleanup and the cumulative $5 infrastructure bound still block activation.
No new live failure has been observed; no Murphy rows close from offline tests.

## Files and verification

Change factory/batch_holder.py and factory/key_holder.py; extend
 tests/factory/test_batch_holder.py (existing retained ciphertext/card and created
event, authored authority/wait/deletion envelopes). These prove composition, not
live authentication or deletion. Cover future retry and restart, due boundary,
invalid projection/deadline, non-wait stop, missing ACK/pointer/outbox/retirement,
stale sources, existing failed successor, money freeze, deadline and concurrency,
per-candidate refusal isolation, lost reply, money advance before reservation
write, reservation before journal write, and dispatch uncertainty. Prove a
successor retains reservation ID/hold and advances source exactly once. Exercise
real batch_tick with empty child/wait maps to prove scheduling is wired and
restart-independent; fake only process spawning. No workers or model calls.
Run the full suite `uv run --with numpy --with scipy python -B tests/run.py`, retain
a unique log and result record, then obtain fresh goldfish diff review.

## Cost, acceptance and remaining work

One offline implementation/review cycle; no infrastructure or model-probe cost.
Pass requires design/diff review without open blockers and the full suite passing.
Rows 2, 11 and 47 advance but do not close. Rows 6, 27, 28, 35, 51 and open batch-service rows keep their statuses. Remaining
launch blockers: delayed-creation ownership/cleanup with provider cost-bound
proof; legacy unresolved launch; router provisioning; cheap plumbing profile
compatible with production role restrictions; fresh reviewed policy/release pins
and account-2 attribution qualification. Expect about three further increments:
cleanup/legacy ownership, router/profile integration, final policy/release review
and deployment qualification. Provider semantics may require an additional one.
