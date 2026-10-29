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

- `run.py` writes recovery reservations only after `admit` returns a
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
  and never stops as `interrupted_repair`. A `repair_pending` with no
  matching record is a crash and follows D's ordinary crash rules.
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
   VM provisioning failed, is retried under E's infrastructure-retry rule. Replaying the journal
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

No batch runs on `factory-simplify` between steps 4 and 6.

Rows 2, 4, 20, 47 and 48 close only when B's end-to-end test passes:

wait → checkpoint → retire → relaunch from the collected generation → settle
→ finish

That test runs on the practice case, with a real or recorded provider
denial.
