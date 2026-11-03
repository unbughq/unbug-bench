# Boat attributed settlement — offline increment

## Problem, impact and boundaries
`boat-spend` admits at most one lifecycle per control home: every historical row
blocks another. This blocks the first pilot worker after practice as well as later
workers. Balance deltas cannot attribute concurrent charges. Reuse that ledger and
lock; count each deleted worker's lifetime machine cost once, and keep counting it
when deciding whether another worker fits the infrastructure budget.
B owns this L increment before pilot admission/cleanup/config. One offline build,
locked full suite and fresh reviews; live qualification remains a practice exam.
No worker, provider request, paid call, pin, practice-state edit or activation here.
Cost: $0 provider/model spend; local CPU plus subscription review only. Timeline:
one implementation/review cycle (estimate 1–2 working days), then a live gate.
Dependency: after merge, parent must re-cut practice release AND policy pins before
any practice admission. The current b75c9b4 offline pin lacks this binding too
(the older 3a50896 report is historical). An old-pin reservation without binding
remains unsettleable: STOP to parent, no reset or inferred migration. Do not
resume practice on existing pins; this document does not change its paused state.

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
path as the final argument ONLY when UNBUG_LAUNCH_STATE is nonempty.
Old callers without STATE keep working but cannot
settle automatically. Bind canonical STATE into the reservation at admission;
refuse a changed binding on replay. Non-batch exam-launch/run-gate-smoke keep
today's unsettleable/blocking behavior: their temporary state has no monitor and
may be deleted. They do not receive STATE and are outside automatic reuse.
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
  Boat with matching count/TTL/cap; row is reserved or finished (settled replay below).
- Read regular files without following symlinks, including monitor and evidence;
  parse duplicate-free JSON. Parse monitor via shlex, never source shell. Its
  spend_file resolves to RECORD. ids must be unique validated Boat IDs.
- Validate creation evidence read-only in the new helper, not ids()'s tolerant
  parser: lstat every directory entry named new.* (including dangling symlinks).
  Reject pending/unknown names or nonregular files. Each new.N must be UTF-8 JSONL
  with object events and exactly one created event with a valid unique ID; allow
  other valid object progress events. Created IDs must equal the unique ids set.
  For reserved rows require contiguous serials 1..vms and exactly vms created IDs,
  so no remaining slot can create after settlement. Finished rows may have fewer.
- Zero creation is provable ONLY for a finished bound row with a regular empty ids
  file and NO entry matching new.* (lexists, including symlinks). Keep the full
  inventory check below; settle workers=[] and actual_spend_usd="0". Every other
  empty/unknown case holds. No failed/pending provider request counts as no creation.
- For every ID verify deletion request/completion identity (same operation ID,
  targetId, kind=sandbox, status/stage completed, timezone-bearing completedAt),
  reusing the deletion validator extracted from _delete without issuing delete.
- Query `boat-call list --json`: pageInfo.hasMore exactly false, unique IDs and
  no owned IDs present. Absence alone never substitutes for deletion receipts.
- Then query `boat-call usage ID --json` once per owned ID, without date filters.
  Require a JSON object with running exactly false, seconds a non-bool nonnegative
  integer and dollars a non-bool finite nonnegative decimal. Unknown fields are
  discarded except id/sandboxId: when present, each must equal the queried ID.
  The command's exact ID binds the response when neither identity field is present.
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
incident; settlement never clamps real usage down to an estimate. This permanently
blocks this home under the no-reset policy; founder decides what happens next.

`--finish` keeps its account observation separate, writes finished first, then tries
settlement for a bound row. Unavailable settlement leaves finished/unknown and
returns existing finish success with a fixed warning so publication is not lost.
The independent cleanup owner calls --settle directly; it never fabricates an exit
code or calls --finish. Reserved rows can settle only with the complete creation
and deletion proof above; no-creation requires finished. --finish later adds actual
exit metadata without downgrading settled authority or rewriting its debit.
Explicitly edit practice_cleanup.py here for settlement only, not pilot generalization.
Its status gains settlement ("not_attempted"|"pending"|"settled") and
settlement_attempted_at (UTC epoch seconds or null). After verified absence it uses
state="settlement_pending" until --settle exits 0; only then state="complete".
Persist the attempt timestamp atomically in the existing status path BEFORE the
subprocess; pass UNBUG_CONTROL_HOME=home explicitly. Read it on restart to enforce
at least 60 seconds between attempts; a future timestamp refuses another attempt.
The existing five-second loop continues while pending; deletion checks continue,
but no settlement provider calls occur inside the 60-second interval. main() exits
only on complete/not_dispatched as today. Guard finish replay preserves settled
rows; guard markers remain guard-owned. No new cleanup service or scheduler.
Standalone --settle supports restart recovery with the same checks and lock.

## Files, shapes and deadlines
Runtime: bin/boat-spend, bin/boat-launch-guards.sh, factory/boat_lifecycle.py,
factory/practice_cleanup.py and factory/deployment_inventory.py. Host inventory:
factory/launch_manifest.py TRUSTED_FILES (boat_lifecycle is already included).
Tests: new tests/factory/test_boat_settlement.py; existing test_isolation_timeouts.py,
test_control_resume.py, test_deployment_inventory.py, test_practice_readiness.py,
tests/bench/test-launch-guards.py and integration/test_batch_launch.py as needed.
Factor monitor's spend-file parser into boat_lifecycle; practice retains timing
validation. Extract deletion completion validation there too, reuse in _delete.

New reservation fields (in addition to today's usd/expires_at/status): state_path
(canonical absolute string or null), vms (positive int), ttl_seconds (positive int),
max_spend_usd (finite nonnegative decimal string). All replay values must match.
Settled row adds actual_spend_usd (decimal string) and settlement object with EXACT
keys schema (integer 1), state_path (same string), settled_at (UTC ISO timestamp),
basis ("no_creation" or "deleted_lifetime_usage"), workers (list). Each worker has
EXACT keys id, deletion_operation_id, completed_at (strings), seconds (non-bool int),
dollars (decimal string). Reject unknown settlement/worker keys, duplicate IDs,
wrong sorting, nonfinite/negative numbers, sums unequal to actual_spend_usd, and
empty workers except basis=no_creation. Old record actual_spend_usd, including
historical account deltas, is never settlement authority. Only this ledger mirror
replaces it: spend record settlement is an exact copy, actual_spend_usd is numeric
float for compatibility with tools/public-qualification/finish.py; that float is
NEVER read back as accounting authority. Its existing rejection of unknown None
is a pre-existing qualification limitation, not permission to fake actual usage.

Use duplicate-free json.loads(parse_float=Decimal, parse_constant=reject), validate
numbers with deployment_inventory.number's existing bounds; sum under precision 80
with Inexact trapped (no rounding). Decimal monetary strings use format(value,'f').
Scan inventory accepts settled and validates settlement via the same helper; add
settled_usd decimal string (null on invalid/missing), keep reserved_usd unchanged.
Tests must update the scanner's exact schemas. No scanner output grants admission.

--settle exits 0 for committed or repaired replay, 1 with the fixed refusal label
for unavailable evidence. No stdout. --finish warns with that label but succeeds
on unavailable settlement; it still records the exit. --check waits for the ledger
lock without a timeout. After lock acquisition, share a 40-second monotonic RPC
budget across balance/list/usage; each boat-call gets BOAT_COMMAND_TIMEOUT_SECONDS
=min(10, remaining). Its outer subprocess timeout is remaining+70 seconds for
existing process-group cleanup. Stop after budget expiry; at most 110 seconds of
RPC/cleanup work after acquiring the lock, including --finish's balance query.
No second query can start after expiry. Timeout leaves liability held. No sleep
inside settlement. Local lock wait is outside that bound; caller termination at
130 seconds is recoverable by ledger-first replay, never a release of authority.

## Exams and honest limits
Add `tests/factory/test_boat_settlement.py` using saved real deletion receipts and
spend record in isolation-settlement-cloud. STATE/creation/ledger layouts come
from real guard_init/guard_new/guard_exit with authored BOAT_CMD edge doubles,
following test_control_resume.py; these layouts are authored, not retained cloud
artifacts. Two-ID receipts and usage/list replies are authored too. No real
per-worker usage response is retained, so these prove validation/arithmetic only.
Midterms: wrong ownership, pending creation, malformed/duplicate JSON, bool/negative/
NaN amounts, running usage, wrong deletion, incomplete inventory and 404 all retain
unknown liability and forbid second admission. Finished no-create admits a second
lifecycle; even a dangling new.* symlink blocks that proof. Reserved partial slots
refuse. Practice cleanup retries survive restart and never invent an exit code.
Exact-boundary admission succeeds;
one cent above fails; cross-batch charges and a larger requested cap never reset it.
Two-ID partial success never settles. Concurrency under the real ledger lock admits
at most one successor. Finish/replay and ledger-first crash never double-charge or
release a hold. Over-cap actual cost is retained. Failed settlement still publishes.
Exercise real guard exit and cleanup replay with provider edge doubles; no new
fixture generator is cited as cloud evidence. Existing single-admission tests keep
unknown-liability expectations; add positive second-lifecycle tests only with proof.
Run touched scripts, then the full locked suite to unique logs and commit provenance.
Fresh diff review must challenge the negative controls for attribution and cap checks.

G1 decision: remain offline as instructed; do NOT run the suggested old-ID usage
probe now. This risks spending build time on an unavailable endpoint. The first
authorized live qualification should query retained deleted bx_d6dzvjbc with the
pinned CLI, before creation; verify verb/schema/lifetime across the month boundary.
A failed probe is a STOP, not grounds for an alternative launch or ledger reset.
Live practice exam before claiming multiple-lifecycle readiness: capture sanitized
per-ID lifetime usage AFTER verified deletion using the pinned CLI; establish that
the API still serves it with running=false. If unavailable, retain hold and STOP:
this design cannot deliver automatic reuse on that provider contract. Return that
specific gap to the parent; no balance-delta workaround or speculative stop path.
Record machine debit separately from actual wallet delta and all non-machine costs.
Also verify no snapshot/proxy charges, top-up OFF and credit covering the estimate.
Murphy 17 (wallet admission race), 49 (lifecycle cost), 51 (control-VM restart recovery) remain open
until real evidence; this offline increment closes no rows.
