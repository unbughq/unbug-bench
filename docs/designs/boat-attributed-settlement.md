# Boat attributed settlement — offline increment

## Problem, impact and boundaries
`boat-spend` admits at most one lifecycle per control home: every historical row
blocks another. This blocks the first pilot worker after practice as well as later
workers. Balance deltas cannot attribute concurrent charges. Reuse that ledger and
lock; let completed, attributable machine usage become a permanent cumulative debit.
B owns this L increment before pilot admission/cleanup/config. One offline build,
locked full suite and fresh reviews; live qualification remains a practice exam.
No worker, provider request, paid call, pin, practice-state edit or activation here.

Retained contract: `docs/reports/stream-b-provider-contract-20261031/billing.md`
§Per-sandbox usage documents `boat usage ID --json`, lifetime when no dates are
supplied, `seconds`, `dollars` at list price, and `running=false` after stop.
It does NOT promise querying a deleted ID or establish a final cash invoice.
Settlement here means attributable VM machine-time debit, never account cash,
snapshot charges or proxy charges. Pilot uses no snapshots and no AI proxy;
those exclusions and remaining wallet credit must be verified before live admission.
The existing prepaid/TTL acceptance is not strengthened into a hard provider cap.

## Delete before adding
Replace the refuse-any-other-row rule with refuse-any-UNSETTLED-row plus permanent
settled debits. Delete no history. No reset, receipt-import override, separate ledger,
new launcher, or charge derived from account balance. Hetzner stays unchanged.
Keep the existing single outstanding lifecycle policy. No parallel admission here.

## Exact interfaces and authority
Extend Boat `--check VMS TTL MAX RECORD [STATE]`; guards supply their existing state
path as the final argument. Old callers without STATE keep working but cannot
settle automatically. Bind canonical STATE into the reservation at admission;
refuse a changed binding on replay. Pass STATE also for non-batch launch guards.
Persist vms, ttl_seconds and max_spend_usd in each new reservation. Existing rows
remain unknown unless the original spend record supplies those fields and an
already-recorded state binding; do not infer ownership from a caller-provided path.
Do not permit a fresh admission to overwrite an existing unledgered spend record.

Add `--settle RECORD STATE` to boat-spend, under boat-reservations.lock, using
existing processes/boat-call and atomic fsync writes. A small helper in the existing
`factory/boat_lifecycle.py` validates ownership/evidence; host trusted inventory
includes any newly imported dependencies. No worker release change is needed.
No manual dollar input. Refusals print only `infrastructure settlement unavailable`.

Validation before querying usage:
- Reservation exists, STATE equals its bound canonical path, spend record is allowed
  Boat with matching count/TTL/cap, and the row is finished (settled replay is below).
- Read regular files without following symlinks, including monitor and evidence;
  parse duplicate-free JSON. Parse monitor via shlex, never source shell. Its
  spend_file resolves to RECORD. ids must be unique validated Boat IDs.
- Reconcile IDs read-only with boat_lifecycle.ids; reject any pending creation,
  malformed creation record, unmatched creation ID, or empty ID set. A no-worker
  reservation is not discharged by this increment; no zero-cost inference.
- For every ID verify deletion request/completion identity (same operation ID,
  targetId, kind=sandbox, status/stage completed, timezone-bearing completedAt),
  reusing the deletion validator extracted from _delete without issuing delete.
- Query `boat-call list --json`: pageInfo.hasMore exactly false, unique IDs and
  no owned IDs present. Absence alone never substitutes for deletion receipts.
- Then query `boat-call usage ID --json` once per owned ID, without date filters.
  Require a JSON object with running exactly false, seconds a non-bool nonnegative
  integer and dollars a non-bool finite nonnegative decimal. Unknown fields are
  discarded; the command's exact ID binds this response, not a guessed response ID.
  No response text or provider stderr is printed or stored. A 404, unavailable CLI
  verb, partial response or unknown final usage preserves the entire hold.

## Persistence, replay and cumulative cap
Keep version 1 and add status `settled`; validate its settlement object strictly.
The row retains original usd estimate and gets settlement schema=1, state path,
settled_at UTC, and workers sorted by ID: id, deletion_operation_id, completed_at,
seconds and dollars (decimal string). `actual_spend_usd` is the decimal sum.
No partial settlement: all workers must qualify. Atomic ledger write is authority;
then mirror the canonical settlement into the spend record. Crash between writes
replays the ledger into the record, without another provider query or added debit.
`--finish` must never downgrade a settled row or erase actual_spend_usd on replay.
`--settle` on settled rows checks unchanged binding and repairs only that mirror.

Admission sums all settled actual_spend_usd across this control home, including
prior batches, plus the requested TTL estimate. It refuses above the minimum of
current max-spend and every recorded reservation cap; historical rows without cap
remain unsettled and block. A smaller later cap can restrict but never replenish
headroom. Fresh wallet credit must independently cover the requested estimate.
An existing reserved replay checks the cumulative cap and immutable envelope too.
This intentionally conservative home-wide cumulative bound has no new-batch reset.
An actual debit above cap remains recorded, stops all future admission and is an
incident; settlement never clamps real usage down to an estimate.

`--finish` keeps its account observation separate, writes finished first, then tries
settlement for a bound row. Unavailable settlement leaves finished/unknown and
returns existing finish success with a fixed warning so publication is not lost.
The independent cleanup owner, after verified deletion/full absence, calls the same
--settle command (and --finish first if controller died before it). It records
settlement_pending versus settled separately from verified deletion; it never
creates/relaunches. Retry can run from its existing loop, bounded per call.
A standalone --settle supports restart recovery without altering journals/ledgers.

## Exams and honest limits
Add `tests/factory/test_boat_settlement.py` using saved real deletion receipts and
creation/spend layouts in isolation-settlement-cloud; identity/binding metadata and
usage/list transport replies are authored doubles, explicitly labelled. No real
per-worker usage response is retained, so these prove validation/arithmetic only.
Midterms: wrong ownership, pending creation, malformed/duplicate JSON, bool/negative/
NaN amounts, running usage, wrong deletion, incomplete inventory and 404 all retain
unknown liability and forbid second admission. Exact-boundary admission succeeds;
one cent above fails; cross-batch charges and a larger requested cap never reset it.
Two-ID partial success never settles. Concurrency under the real ledger lock admits
at most one successor. Finish/replay and ledger-first crash never double-charge or
release a hold. Over-cap actual cost is retained. Failed settlement still publishes.
Exercise real guard exit and cleanup replay with provider edge doubles; no new
fixture generator is cited as cloud evidence. Existing single-admission tests keep
unknown-liability expectations; add positive second-lifecycle tests only with proof.
Run touched scripts, then the full locked suite to unique logs and commit provenance.
Fresh diff review must challenge the negative controls for attribution and cap checks.

Live practice exam before claiming multiple-lifecycle readiness: capture sanitized
per-ID lifetime usage AFTER verified deletion using the pinned CLI; establish that
the API still serves it with running=false. If unavailable, retain hold and STOP:
this design cannot deliver automatic reuse on that provider contract. Return that
specific gap to the parent; no balance-delta workaround or speculative stop path.
Record machine debit separately from actual wallet delta and all non-machine costs.
Murphy 17 (wallet admission race), 49/51 (lifecycle cost/qualification) remain open
until real evidence; this offline increment closes no rows.
