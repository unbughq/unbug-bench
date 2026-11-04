# Completion pilot: decision and implementation brief

Status: **inactive proposal / preparation only**, 2026-11-04. No production
manifest, pin, unlock, worker or spend authority is created by this document.
This replaces the *purpose* of the old [diagnosis experiment](pilot-run.md) for
24-case delivery. It does not reinterpret that experiment's approved bounds.
[Current inventory and queue](../reports/24-case-delivery-status.md).

## Problem and smallest change

We need accepted exam cases and a measured completion rate. The existing
`pilot.py` accepts three serial jobs but fixes TTL to one hour and the batch to
six hours. Shared cleanup uses practice's 30-minute work / 45-minute deletion /
60-minute TTL. Increasing only `--ttl-hours` cannot work: validation and cleanup
would reject it. The launcher's ordinary default is eight hours, but its comment
about historical 5–6 hour runs is not a current ETA.

Keep the existing key-holder, batch manifest/release, dispatcher, router,
controller, checkpoint, cleanup, publication and settlement path. Add one pinned
completion profile to that path. Do not create a new launcher, dashboard, retry
service or case-specific rescue bundle. Keep all case gates, calibrator counts,
seeds, scoring and family-preserving routes unchanged. Deterministic exam scoring
remains the founder's choice; no per-submission model judge.

## Concrete candidate bounds — require approval before activation

| Bound | Proposed value |
|---|---|
| New cases / concurrency | Three fresh distinct cases / one active worker |
| Worker lifecycles | Six total, at most two per case, all retries/resumes included; no replacement cases |
| Per-worker timing, from durable creation start | Work/collection cutoff +6h; deletion due +7h; provider TTL +8h. Startup consumes this same window. Early completion collects/retires immediately. |
| Absolute batch window | 72h from the pinned UTC start; admit only if a full 8h TTL fits before the absolute end |
| Priced-inference authority | $70 cumulative per case, $210 batch, including diagnosis/extensions/retries and priced subscription equivalents; exact CLI round/budget and diagnosis headroom must fit this allocation |
| Infrastructure cash | Original $5 global cap less all actual debits, unresolved holds and other liabilities; no new payment or reset |
| OpenRouter cash | Existing min($11.63, observed available credit) ceiling less charges/holds and overlap reservations; no automatic refill |
| Quality | Full configured current pipeline and independently bound acceptance evidence; no waiver for reaching budget/deadline |

The $70 proposal reuses a historical limit, **not a measured cost to finish**.
Retained public receipts in `stream-d-cost-evidence.json` show two incomplete
cases costing roughly $51–54, and a writer receipt costing $15.05. They do not
prove this allocation sufficient. The $210 includes list-equivalent subscription
work; it is not a $210 cash purchase. Current cash/credit must be checked at launch;
if headroom cannot fund the proposed profile, report that incompatibility and
request a concrete revised decision. Never silently shrink quality or add money.
Six eight-hour lifecycles permit up to 48 worker-hours; the 72h window is a bound
with admission/setup margin, not a completion forecast. The holder itself still
accepts at most 24 hours per invocation: use its existing control-VM
`holder-command.sh serve` / `Restart=on-failure` renewal and holder-bound resume
mechanism, not `--hours 72` or a Mac session. Qualify that restart path before launch. The second lifecycle is
available only through an already-authorized checkpoint/diagnosis transition;
budget or elapsed-time expiry alone does not authorize another worker.

## Implementation package — required before an executable manifest

Use a distinct `b-completion-pilot-1` batch and a new strict pilot profile, leaving
old `b-real-pilot` and practice manifests/journals/cleanup timings unchanged.
The new profile has `pilot_admission.schema=2` and an exact timing tuple
`{run_seconds:21600, grace_seconds:3600, ttl_seconds:28800}`; schema 1 retains its
existing contract. Other lifecycle/count bounds stay as proposed above. Unknown
schemas, extra timing keys, malformed/non-integer timings and mismatched launch
state refuse admission. This brief is not a claim that schema 2 exists today.

The small implementation must cover all these shared seams, with a fresh design
review of its final interface before code:

1. `pilot.py`, `batch_money.py`, `batch_holder.py`: select the exact new managed
   batch, enforce profile/count/window rules and the same pinned five-role checks;
   retain cumulative money handling, round maxima and reserved diagnosis headroom.
   Audit every `PILOT_BATCH`/`b-real-pilot` equality so the new ID cannot bypass a
   role restriction or the ordinary money gate. Keep activation exact-pin only.
2. `practice_cleanup.py`, `boat_lifecycle.py`: select timing from the operation's
   authenticated policy/manifest, not a changed global `practice.TIMING`. Bind it
   to cleanup readiness, stored monitor TTL/cutoff, durable worker start, retirement
   intent and replay. Refuse mismatches before dispatch; retain original timings
   on restart. Do not change either approved historical $0.036 debit scope.
3. `batch_holder.py`, `control_resume.py`, `bin/boat-launch-guards.sh`: make the
   existing launcher derive the same cutoff from the bound job/profile. Its
   default 1800s TTL margin currently gives 7.5h work for an 8h TTL, which disagrees
   with this proposal. Persist/replay the selected 7200s margin with the launch;
   an unbound environment override must not select a new cleanup deadline.
4. Use the existing cleanup unit and retirement fence, bounded stop/usage capture,
   deletion reserve and exact operation receipts. Clock/deadline expiry cannot
   convert unknown charge to zero, permit duplicate deletion, or score a case.
   No new mutation or emergency-delete bypass is introduced.
5. After review/tests, build an inactive exact manifest/release using the already
   enforced `PILOT_ROLES` values and all ordinary roles/quality settings. Include
   exact budgets, UTC start/end, account labels and enforceable diagnosis headroom.
   Fresh IDs and a fresh release/policy bind it; do not repin old started journals.

Missing final interface/manifest details remain implementation work. Do not paste
these proposal values into the current launcher or call this deploy-ready.

## Tests and live evidence

The implementation must pass focused tests and one exact-head full suite under
ENGINEERING. Reuse retained public release/collection artifacts; newly authored
clock/provider responses are tests of mechanics, not live provider qualification.
Required assertions: legacy practice/diagnosis profile unchanged; new profile
admission/refusal; all managed-role and money restrictions on the new ID; all
three cutoff consumers agree before and after restart; full-TTL admission horizon;
6/2 lifecycle limits; insufficient cumulative credit/headroom stays pending/refuses
without spawn; no case pass on timeout; collection before retirement; unknown
usage/failed stop preserves liability; emergency deletion still reaches the same
wrapper and retained exact-worker operation. Do not close Murphy rows from
synthetic timing/provider doubles.

Before real production: accept the saved-smoke carry's reviews/integration, obtain
scoped deployment/unlock/worker authority, and prove live collection + publication
ACK + same-stop final usage/recheck + completed deletion + settlement. Retain
selected-route cancellation/isolated-UID evidence and restart/disconnect and
publication-fault replay required by the launch path. Root must identify their
exact passed receipts or mark them unresolved; the earlier smoke did not prove
all of them. Read-only metadata preflight cannot substitute for these results.

Pilot acceptance is **three qualified, distinct, encrypted cases**, with local
card/archive hashes, off-worker publication ACKs, deterministic scoring evidence,
usage and settlement, and completed deletion operations for every owned worker.
Completed CLI steps, diagnosis/retirement, an agent's success label and an empty
provider inventory do not satisfy it. Cases already accepted retain credit if a
later case fails; report partial yield instead of declaring the whole pilot passed.

Stop new admissions on unknown ownership/creation, failed publication, missing
settlement, exhausted bounds or failed gates needing an unreviewed correction.
The existing controller/cleanup still owns finalization. No automatic seventh
worker, replacement case, budget reset or concurrency increase is authorized.

## What this deletes; Murphy impact

Delete the assumption that the 30-minute diagnosis experiment measures completion.
Do not delete original evidence or acceptance gates. This preparation closes no
Murphy row. Timing work addresses rows 5/9/30/42 and interacts with cleanup,
recovery, accounting and `new-boat-stop-capture-1`; each retains its existing
status until its own real-artifact evidence and independent review permit closure.
The other open rows remain visible but do not all belong on the serial critical path.

## Go/no-go record

Before launch, retain: reviewed/tested source and fixture hashes; exact deployment
and lifecycle evidence; exact manifest/release/policy pins; founder's accepted
bounds and no-replacement decision; observed remaining credit/holds; cleanup owner
and UTC deadlines. After the pilot, record qualified yield, case durations, priced
inference vs actual cash, compute, waste and specific failure causes. Use that
measured result to decide whether to scale toward 24. No ETA or new fleet authority
is implied by this preparation.
