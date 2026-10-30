# Cross-stream interfaces

This file is the contract between workstreams A–E. Each stream codes against
it. A change to it needs a goldfish review, like any other design. Reviews
are kept in `docs/reviews/interfaces-design-<n>.md`.

## 1. Ownership

Streams own **Murphy rows and contracts**, not whole files. A file like
`run.py` is touched by several streams, and that is allowed.

- **Rows.** Each stream closes the rows listed against it in
  `docs/murphy-register.md`.
- **Contracts.** The owner of a contract is the only stream that may change
  its shape:
  - **A** owns router admission and leases (section 2), and the
    provider-failure classifier in `budget.py`.
  - **A** writes the provider-wait record (section 3).
  - **B** owns relaunch, the journal, continuation, publication, the scoped
    VM restore key and Codex renewal (section 4).
  - **D** owns `settle()`, reservations and the limits in section 5.
  - **E** owns the `sh()` subprocess helper and per-case lifecycle in
    `launch.sh`.
- **Edits in another stream's area.** Keep them minimal, and name each one
  in your design. The goldfish diff review checks that it doesn't change a
  contract owned by another stream.
- **Conflicts.** The merge order in section 6 settles them. A later stream
  rebases onto `factory-simplify` before its diff review.

## 2. Router admission (A provides, D uses)

`model_router.admit(role, case, deadline)` returns either `Lease(lease_id,
route, account, expires_at)` or `Wait(reason, retry_after, evidence)`.

**Who calls it.** Nobody outside `model_router.py` calls the bare `admit()`.
Everyone calls `model_router.await_lease(role, case, deadline) -> Lease`.
It re-checks admission for up to 60 seconds. If the provider condition
persists, it writes the provider-wait record, takes the checkpoint and exits
with `provider_wait` (section 3). It only ever returns a `Lease`.

- **Calls that make a reservation** (writer, stress re-review): D's code
  calls `await_lease()` itself. It writes the reservation with the `lease_id`,
  then passes the Lease to the model-call wrapper, e.g. `opencode(...,
  lease=lease)`.
- **All other calls:** the wrapper calls `await_lease()` itself when no
  lease is passed.

**Leases expire.**
- While a call runs, the wrapper renews its lease every 60 seconds. A lease
  that isn't renewed for 180 seconds is reclaimed by the router, so a dead
  worker frees its capacity within 3 minutes.
- On every exit path, including a provider wait, the wrapper calls
  `finish(lease_id, outcome, receipt)`, where `outcome` is `done`,
  `interrupted` or `denied`, and `receipt` is the `call_id` path or null.
  `finish` releases capacity and books nothing.

**Checking capacity.** `model_router.capacity(route)` returns the number of
free slots without taking a lease. B uses it (section 4).

**Clearing a blocked pool.** `credit` and `credential_expiring` never clear
just because time passes. After B verifies a top-up or a Codex renewal, it
calls `model_router.observe(pool, healthy=True, observation_id=<receipt ID>)`.
This call:
- uses the batch-scoped router token;
- is idempotent on `observation_id`;
- frees the pool, after which `capacity(route)` shows free slots and
  `await_lease` admits again.

B delivers a renewed Codex login with an atomic write-and-replace to
`/dev/shm/secrets/codex-auth.json`. Workers read that file on every call and
keep no copy under `~/.codex`.

- `run.py` writes recovery reservations only after `await_lease` returns a
  `Lease`, and records `lease_id` in them. This covers writer
  `repair_pending` and the stress re-review counters.
- A `Wait` before admission therefore leaves no reservation behind.

## 3. The provider-wait record (A writes, B consumes, D settles)

### When it is written

A **provider condition** is a refusal, rate limit, quota limit, credit error,
outage, router unavailable, or credential expiring. Once such a condition
has lasted 60 seconds, the worker stops waiting. That 60 seconds measures
how long the condition has lasted, not how long the model call has run;
long calls are fine.

The worker then:

1. Writes `provider_wait.json` in the case work directory.
2. Takes a normal authenticated checkpoint, which includes the record.
3. Exits with stop reason `provider_wait`.

```json
{
  "wait_id": "<uuid4>",
  "case": "case-...", "job": "...", "batch": "...",
  "role": "...", "route": "...", "account": "<label or null>",
  "reason": "quota|rate|credit|outage|router_unavailable|credential_expiring",
  "retry_after": "<UTC ISO time>",
  "evidence": "denied_before_work|interrupted",
  "lease_id": "<lease of the interrupted call, or null if denied before admission>",
  "call_id": "<path of the per-lease usage receipt in the work dir, or null>",
  "settled": false,
  "batch_deadline": "<UTC ISO time>"
}
```

### Rules

- **No self-reference.** The record holds no checkpoint hash at all. B
  relaunches from the `sha256` of the **collected card**.
- **Default `retry_after`** when the provider gives none:
  - `rate` or `quota`: the provider's reset time, or 15 minutes;
  - `outage`: 15 minutes;
  - `router_unavailable`: 5 minutes;
  - after each repeat: 15, then 30, then 60 minutes.
- **Usage settlement.** `budget.py` already books usage events
  incrementally while a call runs. A keeps that unchanged, and never
  removes or re-books work that was already billed.
  - **The receipt.** For each lease, A writes a usage receipt at `call_id`. It
    lists the event IDs already booked, the usage delta, and whether the
    final usage is known. Writing the receipt books nothing.
  - **Settling.** D's `settle(record)` runs once, on resume, before any new
    model call. It is the only place that books anything for an interrupted
    call:
    - it books only usage missing from the event IDs already booked;
    - if final usage is unknown, it books a conservative reservation for
      the gap;
    - it then sets `settled: true`.
  - **Where it books.** `settle` books into the case's own budget ledger
    in the work directory, the same place `budget.py` books. The booking
    and the `settled` flag are therefore always in the same checkpoint. If
    the worker dies before checkpointing, both are lost together, and the
    next resume settles once, correctly.
  - **Repeated runs.** `settle` is keyed on event IDs and `wait_id`, so
    running it twice books nothing new.
  - **The batch money cap.** B computes it from the cumulative spend on
    collected cards. It never books separately, so the cap can't
    double-count.
- **Resume after a wait is not a crash.** On resume, a live
  `provider_wait.json` whose `lease_id` equals the `lease_id` in a pending
  receipt means a provider wait. A pending receipt is the writer's
  `repair_pending` or the stress review's `review_pending`. It never counts
  as `interrupted_review` and never uses up a re-review attempt. Resume continues from the receipt,
  and never stops as `interrupted_repair`. A `repair_pending` or `review_pending`
  with no matching record is a crash and follows D's ordinary crash rules.
- **Clean-up on resume.** Before its first model call, the resumed worker
  moves `provider_wait.json` to `provider_waits/<wait_id>.json`. Later
  checkpoints therefore never carry a live record.

## 4. Relaunch (B)

### What B reads

The collected **public card** carries:

- `terminal_stop: provider_wait`;
- a `provider_wait` object with `wait_id`, `reason`, `retry_after`, `role`,
  `route`, `account`, `evidence` and `batch_deadline`.

A writes this object onto the card in the same scorecard write that sets `terminal_stop`. These fields hold no case content. B does not need to decrypt anything to schedule a
relaunch.

### Steps

1. B keeps a journal on the control VM, keyed on `(case, collected
   generation)`, with state `pending`, `launched` or `failed`. Each key is
   successfully launched at most once. A `failed` launch, such as one where
   VM provisioning failed, is retried under E's infrastructure-retry rule (Murphy row 29). `failed`
   means the launch verifiably started no worker. An unknown outcome, such as
   a holder timeout, stays `pending` until reconciled, so one generation can
   never get two workers. Replaying the journal
   after a VM restart, or collecting the same card twice, cannot launch a
   case twice.
2. Before starting workers, B calls `capacity(route)` from the VM. It
   relaunches at most that many waiting cases per route per tick, oldest
   first, with 0–60 seconds of jitter. No worker starts while the route has
   no free slots, so a reset doesn't start a stampede.
3. At or after `retry_after`, and only before `batch_deadline`, B calls
   `launch(batch, job, collected_generation)` using the batch restore key.
   If the holder refuses because concurrency is full, B queues the launch;
   it is never dropped.
4. The VM time spent on relaunches goes on the infra-waste line.

### Caps per case

| Reason | Limit | When reached |
|---|---|---|
| `rate`, `quota`, `outage`, `router_unavailable`, `credential_expiring` | 10 relaunches per case per reason. B relaunches only into free capacity, so most relaunches succeed. `credential_expiring` clears once B renews Codex. | Stop `provider_wait_unrecoverable`. Unscored. Maintainer alert. The cap is a backstop for a broken router, not a capacity limit: hitting it means a bug. |
| `credit` | One relaunch after a top-up is detected. Credit never clears on its own. | Stop `provider_wait_unrecoverable`. Unscored. Maintainer alert to top up. |

At `batch_deadline`, the case stops as `provider_wait_deadline`. It is
unscored. Whether the next batch can import it is decided in B's design.
Today `bind()` rejects cards from another batch release.

## 5. What does not count against limits (D's rule; owners per section 1)

A `provider_wait` stop and its relaunch never consume any of these:

- writer rounds;
- extensions;
- restart counts (`restart.py`, A);
- holder recovery attempts (`key_holder.py`, B);
- coordinator launch actions (`coordinator.py`, B);
- stress re-review reservations (`run.py`, D).

## 6. Merge order

Each step merges only after its diff review passes.

1. Single launch path.
2. E: isolation and timeouts.
3. C: invalid runs.
4. A: router. The record writer ships behind `UNBUG_PROVIDER_WAIT=0`, which
   is off by default, and the old in-worker wait stays until B merges.
5. D: caps, resume and settlement.
6. B: batch service. B turns the record writer on.

No batch runs on `factory-simplify` between steps 4 and 6. While the flag is
off, `await_lease()` uses the old in-worker wait and never takes the 60-second
`provider_wait` exit. Explicit caller deadlines and batch deadlines still
apply: when one passes, the call raises a sanitized timeout or
`provider_wait_deadline`.

Rows 2, 4, 20, 47 and 48 close only when B's end-to-end test passes:

wait → checkpoint → retire → relaunch from the collected generation → settle
→ finish

That test runs on the practice case, with a real or recorded provider
denial.

## 7. Router API details (from stream A's implementation, ef01df3)

- **`await_lease(role, case, deadline=None)`.** `deadline` is the caller's
  existing monotonic deadline, the same as `opencode`.
  - The batch deadline comes from `case.batch_deadline` (UTC epoch or ISO),
    or else from `FACTORY_BATCH_DEADLINE`.
  - With the flag on, `case.batch_id` and `case.job_id` (or
    `FACTORY_BATCH_ID` and `FACTORY_JOB_ID`) are required.
- **Requested route.** It is `case.card['roles'][role]['model']`. The wrapper
  applies any fallback override internally.
- **Passing a lease (D).** D passes `lease=Lease` to `opencode` and
  `model_call`. `case.model_lease` exposes the current lease to callbacks.
- **Starting the router (B).** B sets `FACTORY_ROUTER_URL` and
  `FACTORY_ROUTER_TOKEN`, plus a per-batch JSON config with the database
  path, capacities and accounts.
- **`capacity(route)`.** It returns free slots for that exact effective
  route only. Fallback routes are not added in. B asks per route.
- **`finish` and the receipt.** `finish` releases capacity. The per-lease
  receipt books nothing. Usage of an interrupted call stays conservative
  until D's `settle()`.
- **Codex login.** The Codex login is read from
  `/dev/shm/secrets/codex-auth.json` on every call. `launch.sh` no longer
  copies it to `~/.codex`.
- **Credentials are checked before a Lease is returned.** `await_lease`
  checks that the account's credential is installed and that the Codex
  login has not expired. A missing token returns a wait, so D never writes
  a reservation for it.
- **Which account.** `await_lease` prefers the worker's current authorized
  account. It may name another authorized account whose credential the
  worker lacks, so that B can deliver it.
- **Two kinds of field in a provider-wait record.**
  - `lease_id` and `call_id` describe the interrupted attempt. D uses
    them.
  - `route` and `account` describe the candidate that is waiting to be
    admitted or delivered. B uses them. The account can differ from the
    interrupted attempt's.
- **Cooldowns.** When fallbacks are tried one after another, the receipts
  do not extend the cooldown of routes that are no longer being considered.
  Concurrent waits use the latest `retry_after`.
- **Where the route came from.** Each lease's effective route is kept in
  the card's `route_receipts`.

## 8. Batch money authority (B provides, D enforces)

B serializes money admission under `~/.unbug-control/batches/<batch>/lock`.
The authorized manifest has `money_limit_usd` (decimal string, nine places),
`batch_deadline` (absolute UTC), `target_slots`, and root jobs with fixed case IDs
and `requested_total_usd`. A pinned `replacement_policy:{schema:1,enabled:true}`
authorizes replacement-derived jobs as described below; absent/disabled refuses
them. Scheduling priority belongs to an admission/revision request, not another
money owner for the same case. Covered settlement resumes run first; then
replacement, same-owner exhaustion/diagnosis resume, extension, ordinary work,
FIFO within each class. Blocked requests never block later eligible work.

The durable authority is `~/.unbug-control/batch-money/<batch>/jobs/<job>.json`, copied unchanged
into authenticated worker configuration and checkpointed:

```json
{"schema":1,"batch":"...","job":"...","case":"case-...",
 "reservation_id":"<uuid4>","revision":1,"source_generation":null,
 "committed_total_usd":"50.000000000","batch_deadline":"...Z"}
```

`source_generation` is null for fresh work; otherwise the exact acknowledged
collected ciphertext sha256. The commitment is cumulative authority including
already-spent money and infrastructure waste, never a fresh allowance. A case
has one job money owner; changing stage/worker does not change that owner.
Replacement cases have distinct jobs and reservations. A diagnosis of the same
case uses its existing money owner and an ordinary same-owner relaunch; there
is no separate diagnosis launch mode or configuration shape. A manifest amendment cannot lower a limit
below spend or outstanding commitments; it cannot revive terminal batch-bound
work. D requests revisions by collecting `terminal_stop: money_wait` with
`money_wait: {requested_total_usd, reservation_id, revision, priority}`; it makes no further
model call. B queues it until authority exists or emits `retired_batch_bound`
at exhaustion/deadline. `money_wait` is separate from A's provider-wait reasons.

B uses Decimal USD to nine places, rejects negative/nonfinite values, and sums
one latest verified cumulative `case_budget.total_spent_usd` per money owner.
Older cards may use `spent_usd + infrastructure_waste_usd` only when both are
known and validated; missing/unknown totals block that owner's new admission,
subject only to the conservative same-owner resume below.
For each job, outstanding = max(0, commitment - latest collected total).
Admission requires sum(collected totals) + sum(outstanding commitments) <=
manifest money_limit_usd. Collection replaces the previous total and consumes
outstanding authority; it never adds the cumulative total again. A decreasing
cumulative total refuses acknowledgment unless receipt-backed reconciliation
below verifies it. Reclassification
of waste does not release money. A completed job releases unused authority only
after verified terminal collection and worker retirement; loss/unreachability
alone releases nothing. Boat infrastructure cash remains in E's existing shared
reservation and is also shown separately; the model bound includes D's model
infrastructure-waste charges, not a second charge for Boat cash.

B issues initial authority/revisions and collection acknowledgment under the
same lock. Relaunch binds source_generation to the newly acknowledged generation
and increments revision (same reservation_id, unchanged cumulative amount unless
explicitly re-admitted), except for the conservative same-revision source rebind
below. D checks batch/job/case/deadline, exact source_generation,
and revision against the authenticated launch configuration before any call.
A stale copy cannot admit work: only the holder's current frozen job configuration
is deliverable; old workers must be proved retired before revision/relaunch.
The VM never raises live-worker authority in place. Money is reserved before
holder submission; an uncertain submission retains its entire commitment.
A publication failure never releases it.

### Conservative resume and receipt reconciliation

A provider-wait or crash checkpoint with `case_budget.total_spent_usd: null`
may resume under the same batch/job/case/reservation owner and the same revision,
with the same or a lower operating commitment. No money increase or new revision
is permitted. The old full commitment remains held in B's durable money state,
even if the operating commitment is lower. Count this owner once at that full
held commitment for the batch bound; it is covered worst-case authority, not an
unbounded unknown. Every unknown part must be mapped to an `unpriced_invocations`
invocation ID or wait ID with its admitted per-invocation maximum. D's verified
ledger coverage must show that known usage plus the outstanding admitted maxima,
without double counting already-booked events, fits the held commitment. Missing
mapping, missing maximum or unknown legacy usage refuses this exception.

The predecessor must be proved retired and the collected input acknowledged as
usual. The holder may then rebind `source_generation` to that collected SHA at
the **same** monetary revision. This is an authenticated source transition, not
a grant: batch/job/case/reservation/deadline stay fixed and commitment cannot
increase. Both the RAM channel and the checkpointed copy advance to the new
source before D's exact-equality check. Rebind starts from the current persisted
source and advances along acknowledged collection lineage; replay of an older
source (including A→B→A) refuses. D runs `settle()` first on that resume,
before another model invocation. Covered same-owner/same-revision settlement
resumes have priority ahead of replacement, diagnosis and extension. The worker
reads its authenticated restored exhaustion state, settles and checks that the
total is known before D runs its read-only diagnosis under the existing owner
and authority. B supplies no settlement-only or diagnosis mode. A known settled
checkpoint must be durably collected/acknowledged before dependent replacement
admission; it does not wait for the diagnosis result. If an exhausted owner's
total was unknown at launch, D checkpoints and exits after settlement without a
model call; after collection/ACK its next ordinary same-owner resume diagnoses.
This decision comes from authenticated restored state and D's projection, not a
B launch mode. Unknown-total exhausted resumes belong to the first (settlement)
priority class; known-total ones to the exhaustion/diagnosis resume class.
A request blocked on money or
an unknown total retains its FIFO position but never blocks later eligible
requests, including the settlement that can unblock it. Until settlement produces a known total, new
admission, increased commitment, revision old+1, replacement, diagnosis and
extension all remain blocked. Other owners may use only their already-available
batch headroom; this owner's full held commitment is never transferred.

A late actual receipt may lower a previously conservative collected total,
for example $10 to $8. B acknowledges the lower total only under the increment-3
reconciled_decrease qualification below: an invocation estimated in the
immediately previous acknowledged ledger and settled now. Persist a
`reconciled_decrease` acknowledgment with that invocation ID, old/new totals,
collected generation and receipt digest; replay is
idempotent and replaces the latest cumulative total, never adds a refund event.
An unsupported decrease still refuses acknowledgment. A verified decrease does
not poison later revisions or release held authority. Unused authority is still
released only after verified terminal collection and worker retirement.

Increment2b supplies these collection proofs and transitions before resume is
enabled; increment2's fresh-only authorizer/installer continues to refuse them.
The real practice qualification must collect a null-total provider wait, retire,
resume at the same revision, settle and finish; it must also demonstrate a
receipt-backed decrease and refusal of the same decrease without that receipt.

### Replacement derivation and D's exhaustion projection

B consumes D's pure exhaustion/actual-model-work eligibility function and its
content-free pending-diagnosis projection. B does not reproduce their predicates
from stop labels, dollar spend or reservation counts. A denied reservation is
zero work and does not qualify; a real zero-cash subscription invocation can.
Enqueue one replacement immediately when D's pending_projection(card) returns a
PRESENT record whose replacement_eligible is exactly true, before diagnosis runs.
A None projection NEVER permits first derivation, even when exhaustion(card)
and actual_model_work(card) both return true. B never re-derives eligibility from
those predicates or stop labels. This is the parent ruling of 2026-10-30.
D checkpoints the pending state on first exhaustion, before any diagnosis call,
so the first collected exhausted card with actual work exposes an eligible
projection (except infrastructure exhaustion). Completed diagnosis clears it.
B's one-child-per-parent journal is the durable latch: later exhaustions may
request diagnosis again, but never make that parent eligible to derive another
child. Replay returns the existing derivation without new admission.
Do not wait for diagnosis. Unknown totals still block its admission until
settlement under the rules above. Diagnosis runs inside the original's ordinary
same-owner resume, after settlement and known-total checks; B schedules that
resume from D's projection and never creates another diagnosis money owner.

The finite manifest jobs map names roots, not a cap on derived work. For an
enabled replacement policy, root job J derives J-r1, then J-r2 from J-r1, and so
on; cases are case-<batch>-<derived-job>. Derived ordinals are canonical positive
decimal without leading zeros. Root names may not end in -r<digits>, including
-r01, so derivations cannot collide with root names. Increment2b's check_manifest
enforces that reserved suffix and exact replacement_policy keys/types
`{schema:1, enabled:bool}`. Each immediate original
case gets at most one child across all generations/extensions/replays. Under the
batch lock record parent case/job, root job, ordinal, child case/job and the
eligible collected generation in the journal before admission. Replaying that
derivation returns the same child. A derived child can itself qualify for its
one replacement. It gets a distinct job/reservation and inherits the root's
approved source/roles/non-money arguments and initial requested authority.

Holder, bind, money validation and worker installation resolve derived jobs via
the same pure manifest-template resolver; only the holder's verified journal
derivation plus D eligibility permits admission. Do not insert mutable derived
jobs into the frozen manifest/policy or change the nine-field RAM config shape.
`target_slots` is the reporting goal and `max_concurrency` limits simultaneous
workers, not lineage length; neither is capped by len(manifest.jobs). Increment2b
removes both check_manifest's and key_holder.policy_load's root-count caps and
replaces direct root-job lookups in batch.bind, all policy['jobs'] lookups in
key_holder.serve (including orphan-resume policy_job membership),
batch_money.channel/authorize and job_config.install with the shared resolver.
The exact manifest.jobs==policy.jobs root-map check stays. There is
no replacement-count, manifest-job-count or successful-candidate cap. Cumulative
money and the absolute deadline bound the chain; normal capacity/retirement
checks continue to apply. Test J→J-r1→J-r2 with replay of every derivation,
distinct owners, one child per parent, root-only manifest, concurrency above the
root count, and refusal at the money bound/deadline. Concrete D projection API
names/fields are supplied by D and reviewed before this adapter is enabled.

D's draft API, relayed by the parent (not activation authority):
`diagnosis.exhaustion(card) -> bool`, `diagnosis.actual_model_work(card) -> bool`,
and `diagnosis.pending_projection(card) -> None | {schema_version:1,
status:'pending', replacement_eligible:bool}`. All are pure and contain no
generation reference. B calls them on an independently loaded, verified
collected card and stores the result under its existing (case, generation)
journal key. Function failures, non-boolean predicates, malformed/extra projection
fields or mutation of input refuse scheduling for that entry. B never adds a
generation to D's card or projection. Eligibility belongs to D, including typed
usage with a configured model/tokens, recorded unknown invocation/model/role,
invoked route receipt or completed CLI call; a denied reservation alone is false.
D persists invoked/cumulative route history across resumes. B consumes these
functions and never implements that list as a parallel predicate.

The adapter is disabled in tracked code until D's carrying increment passes
review and B's integration review checks the exact installed API/source and
collection/holder prerequisites. No environment toggle or public card enables it.
Contract-only authored API tests do not count as D eligibility qualification.

D's per-invocation reservation/settlement remains in the case ledger. B never
books usage. Provider wait/relaunch consumes no D case counters or holder legacy
attempt allowances. D remains disabled until this channel is implemented and
its practice lifecycle qualification passes. Owner: B; review with batch-service.

The ordinary case diagnosis threshold is distinct from this cumulative job share
of batch authority. Show ordinary `spent_usd` and `infrastructure_waste_usd` on
separate report lines. Waste never consumes ordinary case progress/diagnosis
allowance, and reclassification never creates batch headroom. With commitment
$13 and total $12 = case $8 + waste $4, $1 remains authorized. Batch money
exhaustion is operational and unscored. There is no separate waste allowance.
B grants no extension eligibility. ENGINEERING §3 now draws extensions from
the founder-set cumulative batch bound through this channel, with no fixed
per-extension dollar allowance. D enforces extension count/package/progress
rules; a money commitment alone grants no extension eligibility.

### D coverage, reconciliation, and diagnosis APIs (increment 3)

This additive producer contract enables no runtime work by itself. D implements
and reviews these APIs before B enables its increment2b adapter. B calls them
on the ledger/card from its verified collected generation, after authenticating
owner and collection lineage. Requester-supplied JSON alone grants no authority.
No API reads files, time, environment, credentials or mutable global state, or
mutates its input. Identical JSON inputs give identical outputs. Private provider
receipts and diagnosis findings stay inside the encrypted checkpoint; no record
names the output checkpoint containing itself. B records that output generation
in its ACK. The source_generation binding always names the acknowledged input.

Money strings below are nonnegative Decimal USD with exactly nine places;
invocation, wait and reservation IDs are canonical UUID4; lease_id is A's opaque
nonempty string, unchanged (currently undashed UUID hex). SHA-256 values are
64 lowercase hex digits. Canonical hashes use sorted-key UTF-8 JSON, separators
`(',', ':')`, and nonfinite values refused. Unknown fields or malformed records
fail closed. These records are evidence, never a second spend ledger.

**Pure coverage API:** `budget.usage_coverage(continuation_budget) -> dict | None`.
There is no stored `usage_coverage` card field or duplicate hash/binding record.
The exact result shape is:

```json
{"schema_version":1,"booked_total_usd":"3.000000000",
 "covered_total_usd":"10.000000000",
 "invocations":[{"invocation_id":"<uuid4>","lease_id":"<A lease string>",
   "wait_ids":["<uuid4>"],"maximum_usd":"10.000000000",
   "booked_usd":"3.000000000","remaining_usd":"7.000000000"}]}
```

`invocations` sorts by invocation_id and contains every pending or estimated
reservation once, including estimates already counted in a numeric total.
Every unknown marker must name an admitted reservation through matching
invocation_id and lease_id. Repeated markers for the same invocation fold into
one row and one maximum. Missing/mismatched IDs, an absent/unknown maximum,
unpriced legacy usage or invalid `_event_components` returns None. Return None
unless case_spending(ledger).get('unpriced_events', 0) equals the raw length of
ledger.get('unpriced_invocations', []) BEFORE folding duplicates; this refuses
unknown gap/waste/aggregate amounts that have no admitted maximum. A marker
naming an already-settled row also returns None.
`wait_ids` is the sorted unique set of wait_settlements IDs naming that lease,
possibly empty. A multi-lease wait never repeats a maximum.

Every unique event counts once in booked_total_usd. An event reduces one row's
remaining maximum only if its ID is in that row's event_ids, or BOTH its
invocation_id and lease_id match that row. A historical event with no binding
reduces no row and still counts fully. Metadata naming a missing reservation,
conflicting IDs, duplicate event IDs or an event attributed to two rows refuses coverage.
`booked_usd` is that row's actual event charge, excluding its estimated gap;
`remaining_usd = max(0, maximum_usd - booked_usd)`. Actual charges exceeding a
maximum count in full; no spend is truncated. `booked_total_usd` is
the shared raw Decimal total underlying case_spending(ledger), minus ALL
once-counted estimated_gap_usd, rounded normally once for this display. The
implementation exposes a shared raw valuation helper rather than reparsing
case_spending's rounded floats. It includes
known legacy remainders and additive infrastructure waste. For the covered total, sum raw Decimal actual charges and raw per-row remaining
gaps first, then round UP once to the nine-place unit. Row booked_usd rounds
normally and remaining_usd rounds UP for reporting; their separately rounded
sum is not reused as admission money. A booked $3 under a $10 maximum covers
$10, never $13. Reuse case_spending's raw Decimal valuation, legacy-remainder
and waste rules; no independent tariff or float sum is introduced.

B does not reimplement these joins. It calls this API on the verified collected
ledger (and the immediately previous ACK's estimated map described below). For a
conservative resume, B additionally checks case, reservation_id and revision
against its held job_money owner, source_generation against the journal's input
generation for that worker, and covered_total_usd <= held committed_total_usd.
A lower operating commitment never releases the old full held commitment.
Coverage grants no increase, new revision, replacement, diagnosis or extension
while the collected total is unknown. Missing coverage refuses this exception.

**One decrease receipt per invocation.** D appends to
`continuation_budget.reconciled_decreases` atomically with settlement:

```json
{"schema_version":1,"kind":"reconciled_decrease","invocation_id":"<uuid4>",
 "wait_id":null,"receipt_sha256":"<canonical final per-lease receipt sha256>",
 "booked_before_usd":"3.000000000","previous_estimate_usd":"7.000000000",
 "actual_charge_usd":"8.000000000","released_usd":"2.000000000"}
```

Identity is invocation_id ALONE. D emits at most one such record per invocation,
only when the individual row immediately before _settle_leaf has state=estimated
and usd(estimated_gap_usd) > 0, and that call makes it settled using a final-known
receipt for the same lease. Unrelated unknown totals and leaf order cannot
suppress that row's record. The receipt hash is evidence,
not identity. `actual_charge_usd` is the settled row's once-counted event charge;
Compute all three money fields as nine-place strings using D's shared Decimal
valuation, then compute released_usd from EXACTLY those strings:
`released_usd = booked_before_usd + previous_estimate_usd - actual_charge_usd`.
Emit nothing if released_usd <= 0. Shared event attribution refuses settlement.
`wait_id` is null for crash/late-receipt reconciliation, otherwise a retained
wait_settlements ID naming the same lease. A pending row with an unknown/null
prior total settles without a decrease record, because that row was not estimated.
release_uninvoked refuses every non-pending reservation, including an estimated
row with no events; only settlement can release that row's gap with evidence.
Further growing final receipts add actual usage and cannot release another gap.
Replay adds no record and changes no total. B acknowledges each invocation once.

D retains the final private receipt and its events in the encrypted generation.
B does not decrypt it: receipt_sha256 is audit evidence, and correct retention
and hash/lease validation are D producer invariants proved by D tests. B checks
the public record's exact shape, arithmetic and owner/lineage. Let P be this
owner's immediately previous acknowledged total and T the collected total.
A record qualifies iff its invocation_id was estimated in that immediately
previous ACK, the same row is settled in the collected ledger, and
0 < released_usd <= that previous row's estimated_gap_usd. Per ACK B persists
only the estimated rows as `{invocation_id: estimated_gap_usd}`, including on
ACKs with a null total; it replaces this map on EVERY ACK. Settled rows cannot
become estimated again, so a record qualifies once and no consumed-ID set or
older-ledger search is needed. Duplicate receipt IDs never multiply R; conflicting
duplicate records fail shape validation. Evaluate qualification on every ACK,
including null P or T. An in-run estimate absent from the immediately previous
map contributes zero and is not grounds for refusal by itself.
Let R be the sum of qualifying released_usd and M the immediately previous
ACK's estimated invocation map. Let epsilon = (2*len(M)+1)*0.000000001. When P and T are known accept iff
T >= P - R - epsilon; this bounds re-estimation, releases that round to zero, and per-record versus
cumulative rounding at the nine-place boundary. An unsupported decrease larger
than that bounded rounding allowance still refuses, even without qualifying
records. Each previously estimated row can lose less than two nanodollars to
rounding, and the total roundings add less than one. A null T must pass the conservative coverage/held-authority checks.
A null P permits any known T <= held commitment after normal owner/collection
checks. These checks do not release held authority; even the rounding margin
cannot create new commitment or transfer headroom to another owner.
B's existing reconciled_decrease ACK records old/new collected totals, matching
IDs, receipt digest and collected generation; no refund/negative spend event is
added. Held authority remains held until terminal collection and retirement.
`case_spending` ignores reconciled_decreases; tests assert adding/replaying these
records never changes totals. It also ignores any historical usage_coverage field.

**Public extension history.** The top-level card field extension_history is a
list of exactly `{schema_version:1, extension_id:<integer 1..5>,
writer_operation_id:<uuid4>, entry_sha256:<sha256>, outcome_sha256:null|<sha256>}`.
IDs are consecutive lifetime ordinals starting at 1, per stream-d's passed design.
The last entry is active iff its outcome_sha256 is null; no earlier entry may be
active. It changes once from null to the hash of the completed private outcome.
There is no public state field. The private entry snapshot and its case bytes
are immutable; a private outcome is appended once (private state is derived
active/complete). Repair invalidation preserves the history and snapshots.
Any substantive failure during the extension, including a late defect, completes
its outcome and emits extension_incomplete, never late_defect_needs_ruling.
Infrastructure interruption preserves the active entry for continuation.

**Final diagnosis projection APIs** in `factory/diagnosis.py`:
Read card['terminal_stop'] only, never continuation_budget.terminal_stop.
diagnosis_state and extension_history are top-level card fields. The exception
is recovery.infrastructure_exhausted(card), which also recognizes the existing
infrastructure_gate.exhausted marker. When that helper triggers despite another
terminal_stop, diagnosis_state.stop is the literal infrastructure_exhausted.

- `exhaustion(card) -> bool`: true for budget_exhausted,
  stress_review_unresolved:rounds_exhausted, infrastructure_exhausted (reuse
  `recovery.infrastructure_exhausted`), or the defined extension_incomplete stop.
  A late_defect_needs_ruling:<gate> qualifies only with integer builder_rounds >=
  integer recovery_config.rounds > 0 and no active extension_history entry.
  Sealed cases, provider wait, explicit pause, malformed evidence and terminal
  retirement do not qualify merely because counters are high.
- `actual_model_work(card) -> bool`: true iff continuation_budget has a retained
  events entry, whatever its pricing kind or price validity (including historical,
  opencode cost events, subscription usage and cost-0 free routes), or an
  accountant-produced unpriced_invocations entry. Both are emitted
  after process start. A bare reservation or its conservative crash gap with no
  usage event/unknown marker is false. No private file or route-receipt invoked
  flag is consulted; no such flag is required from A.
- `pending_projection(card) -> dict | None`: None unless exhaustion is true and
  diagnosis for that exhaustion is still pending. Otherwise exactly
  `{"schema_version":1,"status":"pending","replacement_eligible":<bool>}`.
  replacement_eligible = actual_model_work(card) AND the current exhaustion is
  not infrastructure_exhausted. A valid diagnosis_state.stop identifies the
  current exhaustion; legacy cards without it use recovery.infrastructure_exhausted(card). Infrastructure exhaustion requests
  read-only diagnosis only; it does not spawn replacement chains. B derives a child only from a PRESENT pending_projection with
  replacement_eligible exactly true; None always forbids first derivation.
  exhaustion and actual_model_work are diagnostic helpers, never a fallback
  authorization when the projection is absent. B applies its one-child journal
  before derivation, so later pending states cannot admit a second child.
  B calls these functions rather than copying the predicates, and binds output to its
  verified collected case/generation externally.

D's runner records the content-free field `diagnosis_state` with exactly
`{schema_version:1, exhaustion_id:<uuid4>, stop:<original exhaustion stop>,
status:"pending"|"completed", outcome:null|"factory_bug"|"close_to_passing"|
"not_converging"}`. On first exhaustion it creates the ID once, before the
checkpoint. Provider waits/retries of that diagnosis keep it. A validated result
sets completed/outcome before checkpointing; pending_projection then returns
None even if the original terminal_stop remains. An active extension,
factory-bug maintainer queue or retired case cannot schedule another diagnosis
for that same ID. Only a later, distinct code-recorded exhaustion (for example
a completed extension still failing) creates a fresh ID; no counter is reset.
Legacy exhausted cards without diagnosis_state project pending until the runner
records their first ID; B still requires an authenticated explicit import/migration
record before acting on any legacy projection. Malformed diagnosis_state fails
closed to no projection. A validated close_to_passing continues in the same worker
run into code-enforced extension admission; an interrupted extension resumes as
ordinary same-owner work, so B needs no extra projection. factory_bug enters the
existing coordinator maintainer queue; not_converging retires. Only a reviewed
qualified fix and authenticated operation attribution admit a factory-bug resume
(up to three lifetime resumes). That resume archives and clears the old
infrastructure_gate marker before work; a later budget/round exhaustion creates
a fresh diagnosis_state.stop and can qualify for replacement under the one-child
journal rule. It does not reuse legacy restart's blanket infrastructure refusal.

`terminal_stop: diagnosis_pending` is produced by D's same-owner runner when an
exhausted unknown-at-launch owner has settled and must exit without a model
call for B collection/ACK; its diagnosis_state.stop retains the original valid
exhaustion trigger. exhaustion() unwraps only that valid pending state, never an
arbitrary diagnosis_pending label. `terminal_stop: extension_incomplete` is
produced after the active extension's single gate traversal fails substantively
and D completes its history outcome; the final public extension_history entry
must have nonnull outcome_sha256 (the completed public state). Incomplete/invalid
execution remains pending infrastructure, never an extension outcome/regression.
These producers and lifetime-state rules also apply in stream-d.md. Private
findings are never projected. No Murphy row closes until the required real
artifact and lifecycle exams pass.

**Required implementation replays (no row closure claimed).** Use the saved
5813be/e15450 ledgers for legacy unbound-event coverage; estimated-to-settled
release once followed by a growing final receipt; an estimate created and released
within one run; the T >= P-R-epsilon boundary; completed diagnosis clearing the
projection; denied-only reservation versus free/subscription work; mixed leaf
orders with another unpriced marker; null-P/null-T ACK chains with no second
release; sub-nanodollar charges; pending-marker settlement with no decrease
receipt; late extension defects and active-history detection; nonnumeric
infrastructure_kill refusing coverage; and metadata addition/replay leaving
case_spending totals unchanged. B proves its ACK inequalities/map updates; D
proves the producer transitions, receipt retention and pure projections.

### Existing money-path and installation constraints

The money projection path is kept as `batch-money/<batch>/jobs/` for D's already
reviewed consumer. It shares the journal's `batches/<batch>/lock`; it is no
second service, spend ledger or independent lock. Manifest jobs omit max_cost.
B removes batch.bind's max_cost/--max-cost emission for authenticated batch jobs
in increment2; D's job_authority enforces committed_total_usd exclusively.

### Worker installation and D's context (B installs, D reads)

Delivery is an owner-only, atomic file `/dev/shm/secrets/factory-job.json`,
installed by the verified host launcher over existing Boat stdin SSH. The
holder freezes its bytes and SHA in launch state before provisioning. Launcher
passes `--factory-job-config /dev/shm/secrets/factory-job.json` and
`--factory-job-config-sha256 <sha256>` to run.py; batch job args cannot override
either flag. The expected digest comes from holder-authenticated launch state,
never from a restored file or card. No delivery filename/env convention is
required from D. B's installer is `factory/job_config.py:install(c, args)`, called
at context construction before D's `job_authority.for_case` or any model call.
This module/CLI wiring ships in B increment2; until installed D stays fail-closed.

The verified JSON has schema1 and exactly these root fields:
`schema, batch_id, job_id, case_id, batch_deadline, source_generation,
batch_release_sha256, manifest_sha256, job_money`. `job_money` is the exact
nine-field money-channel dictionary above. All repeated batch/job/case/deadline/
source fields must match it, and release/manifest digests must match the verified
installed release. Filename ownership/mode, no-follow read, bytes digest and
case identity are checked before trusting it. Host owner and runner are trusted;
contestant/role UIDs cannot write this RAM directory or runner argv.

B installs separate objects (no aliased mutable dictionaries):
- `c.authenticated_job_config`: current verified RAM launch configuration; never
  loaded from a checkpoint. D reads its `['job_money']` as current authority.
- `c.batch_id`, `c.job_id`, `c.batch_deadline`, `c.source_generation`: from that
  same independently verified current launch binding, not restored files.
- `c.job_money`: case state persisted at `c.work / 'job-money.json'`, included
  in checkpoints. On a fresh job, install an independent copy of current
  authenticated `job_money` and persist before any model call.

On resume first authenticate the encrypted checkpoint/accounting via the normal
restore path, then load its persisted job-money copy separately. B validates
same batch/job/case/reservation owner, preserves cumulative spend, and checks
the holder's explicit transition: new revision, exact collected input generation
and current authorized amount/deadline. If revision/source changes, B records
old/new authority in checkpoint `job-money-history.json` and atomically advances
the case's copy to the verified current holder revision before D admission.
This is an authenticated transition, never a budget reset or a copy of restored
config into both attributes. A commitment increase requires B's serialized
admission; a stale revision/generation refuses. A same-revision replay at the
same source must be byte-equivalent. Increment2b adds only the conservative
source-rebind exception above; history is keyed by reservation/revision/source
so repeated covered waits do not collide. The four binding attributes continue
to use the RAM config. Increment2 refuses source changes until that proof and
installer transition are implemented and reviewed.

A legacy checkpoint lacking job-money needs an explicit manifest import record
and authenticated cumulative-ledger migration before initial assignment; absence
alone grants no authority. No case content/public-card limit substitutes for
the holder binding. D's `for_case` then compares its persisted current case copy
to `c.authenticated_job_config['job_money']` and the four context fields, using
its documented API names unchanged.

Review-17 implementation replays add a release rounded to zero, a re-estimation
at the sub-nanodollar boundary, an infrastructure factory-bug resume followed by
replacement-eligible budget exhaustion, and refusal to release an estimated
reservation as uninvoked. B owns the ACK bound/map tests; D owns the producers.
