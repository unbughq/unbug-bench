# Stream B blocker resolution

## Problem and authority

Objective: stop recycling unknown cloud costs and stop trying to revive old
cases. Batch operators get a durable terminal legacy disposition file and honest admission
refusals instead of an apparent spending guarantee. Timeline: this offline
implementation, full suite and reviews in this task; live evidence has no promised
date and is owned by the later practice run.

The preceding cleanup qualification collected evidence but left unsafe behavior:
boat-spend excludes finished reservations from the next admission, compares only
the next estimate with max-spend, and calls a TTL estimate a cap. Legacy case
provenance is treated as an indefinitely repairable admission prerequisite.
The founder approved retirement of pre-new-schema cases on 2026-10-30 and now
explicitly requires retire rather than hold when provenance cannot be proved.
This design supersedes the legacy hold/reconciliation prerequisite in
stream-b-practice-blockers.md and cleanup-qualification report for CASE eligibility.
It does not assert that retirement of a case proves deletion of its worker.

Read docs/ENGINEERING.md. This branch merged factory-simplify at 9b9e5e0.
No worker, provider mutation, paid call, deployment, push or activation is allowed.
HOLDER_ENABLED and DIAGNOSIS_ENABLED stay false. Existing evidence is in
 docs/reports/stream-b-cleanup-qualification-20261031/{report.md,observations.json,provenance.json}
and docs/reports/batch-service-inventory-20261030.json.

## Change and deletions

1. Delete release of infrastructure liability on controller finish. In
bin/boat-spend retain finished records and mark their charge unknown (null),
including the idempotent finish-recovery branch. Never convert account balance
change into attributable spend. On --check validate every ledger reservation:
finite nonnegative usd, recognized status reserved/finished/reconciled_expired.
Finished and historical reconciled_expired records are unknown liability and refuse new admission, before querying balance
or writing a new reservation. Existing v1 historical records are not silently
zeroed. Reserved TTL estimates remain reserved even after expiry. Refuse any other reservation, including reserved, finished or reconciled_expired:
its actual liability is unknown regardless of TTL expiry. This intentionally
serializes Boat admission across the whole control home. Also compare the next
estimate with max-spend and balance; these remain estimates, not a hard ceiling. Count a same-key reservation exactly once; reuse with a
changed amount or completed state refuses. This is single-admission within
the existing control-home ledger, deliberately conservative across batches; no
new per-batch ledger or reset path. --finish never releases liability. No actual
receipt import is invented; known final charge attribution must be qualified in
the live practice run before any later implementation releases these holds.
The command/report wording must call TTL amounts estimates, not hard bounds.

2. Retire legacy case generations at the B planning boundary. Once an immutable
snapshot is verified, absence/non-dict diagnosis_state yields status retired,
reason legacy_retire, facts null, queue empty. Persist an idempotent public
retirement record under the batch_money.locked(home, id) state directory's retirements/<case>/<generation>.json
binding case/generation/manifest digest and founder decision date. Do this even
when diagnosis is disabled, before invoking D or reading stored projection facts.
Do not change original cards/ciphertext or release model/cloud money. At holder
_source (common to reserve and dispatch source verification), reject the same
legacy condition as legacy_retire; no source mutation, account selection, router
or provider call is reachable. Retirement is terminal for this case generation,
not a successful case result. This deletes the legacy_projection_unbound hold
outcome in planning; it does not enable a legacy import path.

Produce a frozen public retirement disposition for every case in the saved
2026-10-30 Mac/VM inventory, with inventory digest, case names and all retained
card/archive digests, reason pre-new-schema, decision date 2026-10-30. These
historical cases are not eligible practice inputs, including conflicting and
missing-bound archives. Preserve historical evidence; no migration or source
provenance reconstruction is needed to decide retirement. The legacy b275
launch is retire-only as case work, but unknown provider debt stays unknown;
do not fabricate complete/deleted/spend-finished markers or delete its directory.

3. Explicitly separate deployment and cost qualification from offline safety.
Write a handoff report with the four blocker dispositions and exact practice
exams. Cleanup cost guarantees are DEFERRED: current official provider contracts
have no universal exceptional billing ceiling, and installed opaque CLI creation
multiplicity is unproved. A live worker is needed for actual request/deletion/
charge evidence, but one successful practice cannot prove a universal bound.
Before that run, its owner must obtain the missing provider ceiling/single-request
contract or explicitly re-approve a different financial risk policy; this branch
does not silently relax USD 5. The accounting change prevents re-spending unknown liability; it does not prove
a cumulative monetary bound. After first finish, ALL Boat admission on the same
control home (including non-batch callers) refuses until the later reviewed
**Boat attributed settlement** increment exists. There is no reset/bypass here.
Relaunch, settlement and multi-worker exams cannot run on this increment alone:
that settlement increment is an explicit prerequisite. First-worker evidence may
inform it only after cleanup cost and b275 debt entry conditions are satisfied.
Deployment qualification is DEFERRED to live practice: frozen current release,
B2 authenticated input/store and B3 policy/manifest pins, router/account identity,
Mac-off holder restart, delayed creation reconciliation and deletion evidence.
Old staged practice-6ac450e is not qualified. No claim that an empty fleet or
retired legacy CASE proves safe provider cleanup. No new deployment validator,
supervisor or guessed provider adapter is added without a qualified contract.

## Tests and Murphy rows

Add offline subprocess tests of the real boat-spend with a local billing double:
sequential/restarted --check/--finish must not recycle unknown cost; a historical
finished or reconciled_expired row blocks; another reservation refuses even when both estimates fit cap/balance;
expiry never releases; same-key replay counts once; malformed/negative/nonfinite
ledger values refuse without mutation; finish replay retains liability. Check
account balance observations remain unattributed. No fixture produced by the
code under test is called real cloud proof.
Use retained real legacy cards in test_batch_service_d.py to verify durable
retirement for known and unknown totals, before disabled adapter and before stored
facts, unchanged inputs and replay. Holder tests reject legacy source before money
advance/dispatch. Verify retirement disposition exactly covers the saved real
inventory and preserves all digests. These tests prove exclusion and bookkeeping,
not a real worker lifecycle. Close no existing Murphy row: 6,17,27,28,29,35,49,51 and
open batch-service/single-path rows require wider real artifact lifecycle proof.

Run full uv run --with numpy --with scipy python -B tests/run.py, with unique
committed log/result (source commit/tree, timestamps, exit/count/log hash). Fresh
goldfish design review uses zoom_out, design_critic, implementation_readiness and
heilmeier/implementation-readiness standards; fresh diff review uses zoom_out and
implementation_readiness. Save reviews verbatim and dispositions. No self-rejection
of blockers. Cost: one offline implementation/review/suite cycle, no live work.

## Revision 2: exact dispositions and implementation contract

The four blockers below are the USER's four named blockers, not the scanner's
four outstanding-proof labels. A deferred item is not completed or launch-ready.

| Blocker | Disposition after this increment | Reason and exact remaining exam |
|---|---|---|
| Cleanup cost guarantees | Deferred to live practice, with provider-contract prerequisite | Actual create request identity, delayed result, deletion operation completedAt and full charges require a worker. A run alone cannot prove a universal bound; obtain the exceptional billing ceiling and bounded creation contract first, or obtain explicit founder approval of a different risk policy. No such approval is inferred. b275 unledgered debt must be reconciled BEFORE first new admission: provider-bound non-creation evidence, or positively linked worker plus deletion completion and charges. Empty inventory is insufficient. This is an operator entry condition: the disabled holder gate prevents holder admission, but non-batch Boat launch paths on a missing ledger are not fenced by this patch. |
| Cumulative infrastructure accounting | Deferred to live practice AFTER Boat attributed settlement increment | This increment deletes unsafe reuse of unknown money, but supplies neither missing historical charges nor a provider-certified ceiling. Practice must price every start/lifetime/storage/proxy/egress charge and replay across restart/relaunch without resetting total. The first finish blocks all further Boat launches on this home until the named reviewed settlement increment; relaunch/settlement/multi-worker practice is blocked on that code, not promised by this patch. |
| Legacy provenance | Resolved for case eligibility by retirement | All saved pre-new-schema cases retire; provenance cannot revive them. Frozen inventory disposition excludes the saved cases (which have no journal/ACK); runtime source refusal catches later collected sources carrying job_money without diagnosis_state. Unknown b275 cloud debt is a cleanup/accounting prerequisite above, not a held case. |
| Deployment qualification | Deferred to live practice after preceding prerequisites and B2/B3 | Exact current release/input/policy hashes, real VM and R2 bindings, router/account identity, Mac-off holder restart, cleanup/deletion and terminal finish must be recorded. Old staged release is obsolete. Offline success cannot qualify deployed state. |

This explicitly supersedes the finish-release and historical reconciled_expired
exclusion clauses of stream-b-delayed-creation.md and isolation-timeouts.md.
Hetzner (ledger_path None) is outside these Boat ledger changes. No policy expands.
The first request in a genuinely empty Boat ledger remains estimate-based; this
patch is not an activation authority and cannot detect unledgered historic debt.
The b275 debt entry condition therefore remains mandatory for deployment.

Ledger validation applies before BOTH --check and --finish. Require exact integer
version 1 and a dict of string-keyed object rows; usd is a decimal-compatible
string/number (not bool), finite and nonnegative; status is one of reserved,
finished,reconciled_expired. Invalid JSON/shape yields fixed `invalid reservation
ledger`, unchanged ledger and spend record. Do not echo bad values. No receipt
or numeric field injected into a row constitutes settlement authority.
For valid-ledger admission refusal, do not write the ledger. A new target spend
record is still written with allowed=false, refusal=<fixed label>, estimate data,
null balances if no query occurred, and actual_spend_usd=null. Existing target
spend records are preserved byte-for-byte on refusal (do not erase lifecycle
evidence). Refusal priority: completed reservation cannot be reused; reservation
envelope changed; infrastructure liability unsettled (any other row); estimated
batch cost exceeds balance or --max-spend. Do not query balance for the first
three. Ordinary argument/ledger validation failure does not write a spend record.
Accepted same-key replay never overwrites an existing spend record; a crash after
ledger-save before record-save may rebuild a missing record. Finish updates status
finished and actual_spend_usd=null; replays do likewise, never releasing liability.
Use the existing atomic writer but fsync file and containing directory for spend
and ledger commits. Finish validation precedes all mutation; error messages never
include exception/provider output. Existing finish processing preserves deletion
and account-observation evidence.

Runtime retirement record exact fields: schema=1, status=retired,
reason=legacy_retire, decision_date=2026-10-30, case, generation, manifest_sha256.
Use validated entry case/generation, not raw inputs. Reuse atomic_json under the
existing batch_money.locked lock; fsync newly created retirement directories.
If a record already differs or is linked/nonregular, refuse `retirement conflict`
without changing it. Same record replays idempotently. Return exactly
{status:retired,reason:legacy_retire,facts:null,queue:[]} even with diagnosis off.
The planning function currently has no production caller; _source is the real
holder enforcement. Persist the same retirement record in _source before its
legacy_retire refusal, so production rejection is a durable terminal disposition.
Do not mutate original journal or money or cloud ownership records.

Static disposition path: docs/reports/stream-b-legacy-retirements-20261031.json.
Exact fields schema=1, decision_date=2026-10-30, disposition=retired,
reason=pre-new-schema, inventory_path, inventory_sha256, inventories.
inventories has mac/vm keys whose value is a list (original inventory order) of
{case,card_sha256,card_archive_sha256,casekey,casekey_metadata,files}; files is the retained list of
{name,sha256,size}. Include casekey_metadata only when present in the original record, copied verbatim. Cover all original checkpoint records, preserve nulls and
both stores' different variants. All identifiers/digests are already public in
the committed source inventory; add no case content or credential material.
Handoff path: docs/reports/stream-b-blocker-resolution.md, containing the four-row
disposition table, exact prerequisites, tests/reviews and remaining practice exams.
This is a disposition record, not a live catalog rewrite or cleanup receipt.

Modify tests/factory/test_isolation_timeouts.py, specifically reverse the final
admission expectation in test_concurrent_admission_reserves_whole_envelope_and_finish_observes_account
and test_historical_expired_release_remains_compatible. Add same-key, low-estimate
concurrency, malformed-ledger and finish replay tests in that file, using retained
billing/created artifacts and only a local subprocess transport double. Add the
retirement-inventory test to tests/factory/test_batch_service_d.py; also check
conflicting persisted retirement refuses. Holder tests go in test_batch_holder.py.

## Review-2 precision touch-up (before implementation)

Runtime case retirement is a durable file and a plan return, not a new status UI;
batch_status remains unchanged. _source authenticates through _entry and checks
ACK/card bindings before recording legacy retirement; its docstring must no
longer say read-only. Comment that this is case disposition, distinct from worker
deletion proof (op.retirement). No record is written for an unverified request.

boat-spend --finish replaces balance_after_error exception text with the fixed
label balance_unavailable, prints only WARNING: account balance unavailable, and
catches provider/parse failures without emitting raw output. Top-level handled
errors use fixed validation labels; external/subprocess/OS errors map to
boat-spend: accounting unavailable. balance() captures stderr too; it never
streams provider diagnostics. These changes apply only to boat-spend, not other
scripts. Invalid ledger JSON/shape maps to invalid reservation ledger. The
Hetzner pricing query also captures stderr. No dynamic value is in a refusal
message. This does not purport to redact arbitrary secrets throughout the repo.

Tests additionally cover unchanged existing target spend bytes on refusal;
new allowed=false refusal record with null balances; no billing calls for the
first three refusals; accepted same-key replay preserves record bytes; conflicting,
linked and nonregular retirement paths refuse unchanged with retirement conflict.
Rename/reverse test_unbound_legacy_known_precollected_refuses_without_changes and
test_unbound_legacy_null_precollected_refuses_without_changes. Row 17 stays at its
current status: this offline billing double is not new real-run closure evidence.
Add supersession notices to stream-b-delayed-creation.md and isolation-timeouts.md;
do not rewrite their historical test results. Runtime retirement helper accepts
only the already-validated entry after snapshot verification.

The independent scenarios in tests/bench/test-launch-guards.py each use a distinct
synthetic control home; otherwise unknown liability from the first scenario would
prevent all later scenarios from exercising their intended paths. This is test
isolation, not a production reset mechanism. Cross-launch refusal stays tested
in test_isolation_timeouts.py.


Full-suite compatibility: test_gate_smoke.py now asserts same-home second-launch
refusal, then uses an independent synthetic home for its remote-failure scenario.
The public batch integration test now proves first-worker interruption/collection/
deletion, retained model ledger, duplicate/restart replay and refusal of subsequent
job and restore creation. Successful multi-worker relaunch cannot be asserted
under this increment; it remains deferred to attributed settlement and practice.
