# Stream D: caps, resume and diagnosis

Design only, 2026-10-29. Help a batch finish without a person rescuing stopped
cases. Keep paid work and lost progress bounded while preserving gate standards.
The founder avoids rescue work and more candidate cases reach review without
weakening the bench. The risk is spending too much on a weak case.

Implement after E, C and A, against the reviewed interface contract
`docs/designs/interfaces.md` at **9699e5d + c49c754 + 4a10966**, including §7’s implemented API from
stream A commits **ef01df3 + 447795b** and interface update **ff5ed1a**, read from
`/Users/bugsincode/Developer/unbug-bench` (not yet on this worktree).
Replaces the seed in `extensions.md`. Targets Murphy **8, 9, 10, 11, 12, 13,
15, 21, 35, 39**; none closes before real-artifact implementation tests.

## Change and deletions

Today a $5 paid cap defeats a $50 case budget; separate recovery allowances
punish waiting and interrupted work. Use the ordinary checkpoint launcher,
cumulative accounting and one absolute batch deadline. Eight writer rounds/$50
remain the ordinary diagnosis trigger. Exhaustion queues one replacement per
original immediately, without waiting for diagnosis, **if it made at least one
model invocation** (including a zero-cash subscription invocation). A zero-work
case retires its replacement chain: a misconfigured bound cannot spawn endless
empty replacements. Both sealing keeps both
candidates. Delete replacement count limits: chains share only the cumulative
batch money/deadline bound. Replacements get
first admission, then diagnosis, then extensions, FIFO within each class.
Unavailable capacity means queued, never a founder pit stop.

Delete the $5 paid cap, $8 writer reservation floor, final-fix loopholes and
separate restart/stress-rereview/holder-recovery/diagnostic allowances. Keep
section 3’s five extensions and three factory-bug resumes. Waiting, malformed
answers and infrastructure continuations spend actual money/time, never an
extra author round or extension.

**Proposed section 3 amendment:** delete its fixed $15 per-extension allowance.
Use the authorized cumulative batch money bound for extensions, diagnosis,
normal work, replacements and infrastructure waste together. No new dollar
allowance, no automatic increase. Paid receipts and subscription list equivalents
are charged once each; infrastructure cash stays in the existing infrastructure
reservation. The user explicitly prefers deleting caps/allowances. The evidence
below does not support $15 and cannot establish another package price. ENGINEERING remains active until implementation adopts this
explicit amendment; this design changes no running policy or section 4 rule.

## Batch bound and reviewed interfaces

B owns money admission and the absolute UTC `batch_deadline` in the authorized
manifest: it is the batch end, not a worker TTL, holder lifetime or collection
margin. Missing/expired authority refuses dispatch. Reuse the control VM's
shared admission lock for job money commitments; B serializes admission there.
`admission.py`/`awaiting_shared_reservation` currently cover statement admission,
not money: extending that seam needs the proposed B-owned contract below. D books **only the case
ledger**. B computes spend from collected cumulative cards, plus outstanding job
commitments when admitting work, never a second spend ledger. A commitment is
converted into that case's spend, not added to it. Missing/stale shared reservation
refuses extension, diagnosis and replacement dispatch. Do not enable D until B
provides this enforcement; no new cross-worker money service in D.

B assigns each job an unspent portion of the remaining batch bound. D enforces
that commitment locally with atomic invocation reservations in `budget.py`.
After diagnosis `case_budget.limit_usd` is the job’s `committed_total_usd`
(including waste). `require_case_budget` compares `total_spent_usd` plus
outstanding reservations to that value; reclassifying waste never opens batch
headroom. The ordinary $50 threshold no longer stops that job.
Store `ordinary_limit_usd` (manifest default $50) in `case_budget`, preserved by
`model_runtime.update_case_budget`, separately as the trigger. Ordinary writer
admission stops for diagnosis if `builder_rounds >= rounds` OR
`spent_usd + next_writer_invocation_max > ordinary_limit_usd`. This bounds the
writer call, not the whole round; stress/gates use remaining job authority. At
spent $44 and next maximum $12, diagnose without calling (not $56 after return).
Inside an active extension, bypass that ordinary threshold; `require_case_budget`
still checks settled **total including waste** + outstanding reservations against
the job commitment.
Delete `writer_round_estimate` and its $8 floor instead of maintaining two tests.
Historical $70 limits remain import evidence, never new authority. No overspend
is erased. If the next invocation maximum exceeds the commitment, return to B
without calling; queue behind other work, and retire if no authority remains.
At the batch bound, mark `retired_batch_bound` with settled spend. It is terminal
in this batch, never revived just by increasing a limit.

### Proposed addition for B to adopt, not an existing interface

B must adopt and goldfish-review this money channel in `interfaces.md` before
D implementation relies on it. This design does not edit B’s contract. Minimum:
`batch-money/<batch>/jobs/<job>.json` on the control VM, included unchanged in
the authenticated worker job configuration, with schema-v1 fields
`{batch, job, case, reservation_id, revision, source_generation,
committed_total_usd, batch_deadline}`. Money = cumulative total authority for
that case/job, including already-spent money; use decimal USD to 9 places.
Stale means batch/job/case/deadline mismatch, an older revision than the shared
reservation, or source_generation not the acknowledged restore generation.
B issues/revises it under the shared admission lock. `money_wait` and its queue/
public-card handling are explicitly part of B’s proposed contract, not an
already-supported provider-wait reason. Outstanding commitment =
max(0, committed_total_usd − latest collected total for that job). On collection,
replace the old card in B’s aggregate; reduce outstanding commitment by the new
spend, never book a second cost. Relaunch preserves reservation/revision unless
B explicitly replaces it; worker requests more by returning `money_wait` with
its final collected card (no model call). B’s sizing choice is external: one
case can consume its whole commitment. No amount/channel is guessed in D.
This proposed addition is an **external prerequisite requiring B’s adoption**;
the current goldfish reviews its sufficiency for D, not authority to edit B.

D follows interfaces §§2–5 exactly:

- For writer `repair_pending` and **every** stress `review_pending` (initial
  review as well as re-review), D calls
  `model_router.await_lease(role, c, deadline=None)` itself, passing the existing
  **monotonic** operation deadline when present. Batch UTC authority comes from
  c.batch_deadline/FACTORY_BATCH_DEADLINE; never pass a UTC epoch as deadline.
  With the flag on, c.batch_id/c.job_id (or FACTORY_BATCH_ID/FACTORY_JOB_ID)
  are mandatory. Requested model is c.card["roles"][role]["model"]. Only after it returns
  a Lease, write the reservation with `lease_id`, then pass `lease=lease` to the
  wrapper (opencode or model_call). The existing before_attempt callback reads
  **c.model_lease** and reserves/maps each newly returned internal fallback lease
  before its CLI starts, updating the pending receipt without a new logical round.
  If an interrupted lease has unknown final usage, D’s accounting integration in
  ModelRuntime.call defers further internal attempts (existing router_deferred
  path) **only with UNBUG_PROVIDER_WAIT=1**, preserving its Wait/receipt until
  the ordinary checkpoint/resume. With the flag off, retain A’s behavior and
  the conservative reservation for ordinary crash settlement; never force
  router_deferred in a loop that cannot exit as provider_wait;
  do not start another CLI or replace the unknown by zero before settle().
  A checks installed credentials/Codex expiry **before returning a Lease**.
  Missing credentials wait without a D reservation, charge or counter change.
  D never treats an undelivered candidate credential as admitted capacity.
  No bare `admit()` or reservation/counter change while awaiting it.
  Other calls leave admission to the wrapper. Immediately after wrapper
  admission, the wrapper invokes D’s case-ledger reservation helper with the
  returned Lease and its existing call name, before dispatch. No money is
  reserved before admission for these calls either. D adds this minimal wrapper
  integration without changing A’s lease/record shape. A owns lease renewal and
  `finish(lease_id, outcome, receipt)` on every exit; finish books nothing.
- On resume, before **any** model call, D calls `settle(record)` for a live
  `provider_wait.json`. Preserve `budget.py`'s incremental booking. Read A's
  `call_id` receipt; union its already-booked IDs with IDs in the case ledger;
  add only missing events/delta, or reserve the unknown gap conservatively.
  In provider_wait, **lease_id/call_id are the interrupted attempt**. D never
  uses record.route/account to identify or price past usage: those are B’s next
  candidate and may name another account. Resolve interrupted effective route
  from D’s reservation, keyed by lease_id; store the returned Lease’s route,
  account, billing, pool and family there at creation. card.route_receipts
  corroborates that binding; A’s usage receipt need not contain route metadata.
  Sequential fallbacks as well as concurrent owner calls can produce a merged
  call_id with booked_event_ids spanning several leases. Expand its receipts
  recursively, validate every per-lease path, and union all event IDs across
  leaves and the case ledger. Never add aggregate usage_delta to the same leaf
  events. Settle each unknown per-lease reservation gap separately, even if the
  record names only one interrupted lease; no gap is priced from the next route.
  Unknown-gap estimate = max(0, reserved invocation maximum − already-booked
  charge). Example: $3 and $2 already booked under a $10 reservation adds $5,
  total $10; replay adds $0; a final $8 receipt releases $2, not another $8.
  A receipt is evidence, never another booking. `wait_id` and event IDs make
  replay a no-op. Store the booking and settlement entry in the case ledger;
  write `settled:true` in the record and checkpoint both together. If killed
  before checkpoint, restore loses both together and settles correctly again.
  If killed between local writes, ledger settlement keyed by `wait_id` repairs
  the flag without rebooking. B aggregates collected cards only.
- A live wait whose `lease_id` matches writer `repair_pending` or stress
  `review_pending` resumes as provider wait, never `interrupted_repair` or
  `interrupted_review`, and uses no re-review attempt. Unmatched pending work
  follows ordinary crash reconciliation. For a continuation, after settlement
  reset the pending receipt to `lease_id:null, resumed_from_wait:wait_id`;
  preserve operation/round/extension IDs and counters. This is continuation
  state, not a new reservation. Archive the settled wait before re-admission.
  A denied-before-admission wait with null lease/call IDs matches this unique
  pending role and books $0. After Lease L2 returns, atomically replace null
  with L2 and reserve its invocation; a new interrupted wait now matches L2.
  If killed while awaiting L2 with no live wait, the validated settled archive
  named by resumed_from_wait proves provider continuation, not interrupted repair.
  No matching live wait or verified archive means ordinary crash reconciliation.
  Before the first new model call,
  move the settled record to `provider_waits/<wait_id>.json`; later checkpoints
  have no live record. No checkpoint hash is added to A's wait-record schema.
- Provider waits/relaunches consume **no writer rounds, extensions, restarts,
  holder recovery attempts, coordinator launch actions or stress re-review
  reservations**. An already-started operation retains its ID and counter value.
  Keep B's separately reviewed section 4 provider-wait backstops (10 per reason,
  credit once after observed top-up) and unscored terminal labels; D deletes no
  part of that contract. Those counters detect router bugs, not case progress.

Merge: **single path → E → C → A → D → B**; rebase before implementation diff
review. A ships `UNBUG_PROVIDER_WAIT=0`; no batches between A and B. B enables it
and proves wait → checkpoint → retire → relaunch collected generation → settle
→ finish on a practice case with real/recorded denial. D does not take ownership
of A's record/classifier or B's journal/key/relaunch/publication.

All D reservations are keyed by a fresh UUID4 `invocation_id` per admitted
process attempt, mapped to `lease_id`; the logical UUID4 `operation_id` survives
waits/crashes in the same writer/stress unit. The wrapper reuses a caller-written
reservation for that lease instead of reserving twice. `settle` joins A’s receipt
to the reservation by lease_id, then deduplicates event IDs/wait_id. A lease that finishes denied before any CLI
started releases its reservation at $0 immediately; an interrupted lease does
not. before_attempt reuses the existing per-lease reservation idempotently.
Denied before
work with null lease_id/call_id creates no reservation or charge. Unmatched
admitted reservations follow conservative crash settlement; this may overcharge
an unrecorded wait until receipts arrive, but does not create a writer defect.

Serialize **model dispatch per case** with a case-local lock acquired **before
await_lease** and held through wrapper finish. Mechanical gates may overlap the
single model call, but strong/easy calibrators never make model calls together.
Use the lock, not a change to the concurrent_roles flag/fingerprinted setting.
Use one case-context threading.RLock: D’s caller and wrapper nest it in the
same thread, so passing a Lease does not deadlock/re-admit. All new-schema
factory jobs use this scheduling policy. G10 wall-time can approach
the sum of the two calibrators instead of their maximum; the measured impact is
unknown and must be included in the ordinary batch deadline qualification. Thus
ordinary calls have one admitted invocation **live at a time**; the nested-owner exception below
uses A’s existing multiple-receipt aggregation, without changing its record
shape. Across cases A still owns account concurrency.

**G10 nested owner exception (reviewer option b).** `calibrate` passes its
existing deterministic `call_name` (`role.replace("_","-") + name + try index`,
using the existing formatting) to `owner_channel` before starting the tester.
`owner_server` sets `_owner_lock_bypass=True` and `parent_call_name=call_name`
on its copied context. The wrapper bypasses the tester’s RLock only for that
program-created marker and a matching active tester reservation; a name prefix
alone cannot bypass it. Owner calls acquire their own reviewer-family Lease and
reserve independently after admission, storing parent_call_name in the case
ledger. They do not borrow the tester’s route/account or lease. Root contexts
pre-create and share router_waits, route_receipts and cleanup_errors lists before
copying; c.model_lease remains local. Owner ProviderWait uses existing failure/
role_cancel to cancel and join the tester, then root handles provider_wait;
never checkpoint/exit from the HTTP thread. A writes one record after joining:
call_id may be null, one leaf or an aggregate with receipts:[per-lease paths].
D settle expands it and joins the cancelled tester through parent_call_name,
plus all unsettled interrupted lease receipts in that unit; the link narrows the
search, never excludes an otherwise authenticated unsettled receipt. Book each
missing event/gap once by lease/event/wait ID. Null owner denial adds $0 while
tester spend remains conservative until settle. The interrupted G10 unit is
unscored and never writer feedback. Keep owner.calibrator_slot_offset=0 so the
HTTP thread cannot publish. Its ThreadingHTTPServer uses a non-blocking owner_lock
to serialize questions, so only one owner is live beside the tester. These are minimal exam_responder.py
and wrapper edits, with no A record/API change.

Holding a tester lease while its reviewer pool is busy can waste its reservation
and reach B’s reviewed backstop. Accept this scheduling risk visibly: batch
qualification reports owner-admission waits and their charges. B should check
both tester and reviewer capacity (combined slots if they share a pool) before
relaunching exam exposure; that scheduling decision belongs to B, not a changed
A wait threshold. No claimed package-price saving relies on those waits being free.

## Extension eligibility and progress

Stages are stress, then `run.py:GATES` in actual order (G16 before G8, G17 after
G10), excluding sealing G12. Frontier = first stage lacking a complete, valid,
hash-bound pass, never the highest gate number. Early passes count only at their
normal position.

First extension requires: exhaustion; diagnosis `close_to_passing`; remaining
batch money/deadline; fewer than five extensions; **complete stress coverage
with no open blocker**, bound to current case/stress version. Cases still stuck
in stress do not qualify; clearing stress without reaching a gate can qualify.
Infrastructure and incomplete reports retry before entry; incomplete evidence cannot authorize it.

After `await_lease()` returns and before dispatch, append an immutable entry to
checkpoint `extension_history`: extension ID, source/parent generation and case
digests (never a hash of the checkpoint containing the entry), ordered stage/version vector,
stress receipt, frontier, and each stage’s status/evidence/dependency digests.
Reserve the ID and writer receipt with that Lease’s `lease_id` only now. A
pre-admission wait writes no reservation. A mid-call wait retains the active ID.
Append the outcome after evaluation. History lives outside `gates`, `gate_results` and `failed_gate` in `work/extension-history.json`,
included in the encrypted checkpoint. The public card projects operational
IDs/counts/status and hashes only; no receipt text, findings or case files.
Each schema-v1 entry has
`extension_id`, `writer_operation_id`,
`entry`, `outcome` (null until complete), each snapshot with the fields above. Private state is derived from null/non-null
outcome, never another mutable field.
`late_recovery.invalidate/stop_defect` must preserve this file and field.

One extension = one logical writer round, its stress review, one gate traversal.
Set `validate_and_repair`’s repair limit to zero inside extensions. In
`write_and_attack`, use a one-round range for that extension and bypass ordinary
round exhaustion for its active ID; `builder_rounds` remains cumulative (9 after
the first extension following eight rounds). In `validate_and_repair`, bypass
the ordinary `builder_rounds >= args.rounds` stop only for that active ID so the
gates execute. Delete only the post-loop `builder-precheck` call and its G1/early
prechecks (~1180–1186), not the exhaustion receipt/stop emission (~1155–1179
and attack_unresolved(rounds_exhausted)). Every author edit belongs to an admitted round. No final fix,
freshness author edit or early failure may invoke a second writer. Genuine defect
ends this extension with findings retained. Infrastructure continuation of its
unfinished operation keeps the same round/extension IDs and cumulative spend.

Seal if all stages pass. A further extension needs diagnosis plus a strictly
later frontier and every entry-snapshot pass still passing with valid current
dependencies. No progress/regression retires. Invalid execution/provider wait
is pending, never scored regression. Reaching the batch bound retires for that
bound; running out before gates is no progress. Five is a lifetime count.

Compare **identical ordered stage/version vectors only**. On a gate update,
retain both snapshots and evaluate the changed gates and dependency-invalidated
successors on the saved **entry case revision** under the new versions; compare
outcome under those same versions. Keep unaffected evidence. Missing baseline
evidence means reconstruct it normally and leave comparison pending; inability
to finish by the batch bound retires for the bound, not regression. Version
changes never grant another extension/reset counts. Rebase lazily, only when
another extension is considered. Regression means an entry pass fails with
complete valid evidence under the same version; substantive reviewer disagreement
uses the independent review rule before retirement. Stress uses the same rule.

Version inventories are computed lazily when comparing an extension, not eagerly.
Version and case binding are separate. For reusable gates derive the version
from `gate_state.inputs` excluding `case`, `seed`, `slot` and the whole-cache-file
hash. Exclude router/accounting/publication byte hashes from scientific versions;
retain evaluator/calibration code, prompts, model identities and scientific settings.
Keep their full input digest as evidence binding. Extend its dependency inventory for G1
(case_contract + g1 transitive source), G2 (admission + trusted retrieval adapter
+ review/freshness prompts), G3 (build source + project image digests), G7/G11
(MEASURE + their transitive source), G10 (MEASURE + MODEL + calibration prompts),
G17 (G16 inventory + fairness review prompt + calibration settings). Stress uses
`judge_dependencies` plus its prompt/role settings. All include scientific args,
role model/family/prompt hashes and judge environment where used. Pure router/
publication changes do not change scientific versions. A global fingerprint
VERSION bump means every stage changed; never rename an old result to new.

## Diagnosis and factory-bug routing

The existing coordinator schedules a read-only diagnosis role through the same
launcher, isolated from other cases. It reads the authenticated restored case,
writer handoff, incremental stress findings/coverage, gate/calibration receipts,
retained transcripts, stop history, ledger/reservations, extension snapshots and
matching factory source. No credentials or exam secrets. Private findings stay
encrypted; public cards expose operational status/IDs only.

Use the configured **reviewer family**, distinct from writer and strong
calibrator: the case slot’s reviewer family at the checkpoint, from its resolved
rotation/role record. Enforce family identity; A supplies same-family fallback/waiting. Diagnosis cannot edit, certify a gate,
grant money or override code eligibility. Strict schema v1, unknown fields
rejected, nonempty reason/evidence, verified relative paths and SHA-256 digests:

```json
{"schema_version":1,"case_id":"...","checkpoint_sha256":"...",
 "outcome":"factory_bug|close_to_passing|not_converging",
 "reason":"...","evidence":[{"path":"...","sha256":"...","finding":"..."}],
 "factory_bug":null}
```

For `factory_bug`, replace null with `{component, reproducer,
affected_operations:[operation_id], fix_required}` (nonempty strings; the operation list may be empty when code proves no eligible charged operation).
Bind results to the queued checkpoint; stale output cannot authorize newer work.
Malformed/interrupted diagnosis is infrastructure, not a fourth case outcome;
retain and repair/retry under the batch bounds. `not_converging` retires.

**Parent ruling, 2026-10-30: factory bugs do not wait for an in-batch fix.**
Code is frozen per batch; ordinary plumbing releases roll forward at checkpoints.
Fixes follow ENGINEERING §1 on a branch, with design, goldfish review and merge.
There is no maintainer service, authenticated-fix delivery contract, mid-batch
fix dependency, or automatic production edit.

For a validated `factory_bug` outcome, persist the private finding and completed
`diagnosis_state`, then stop unscored as `factory_bug_held`. No more model work is
admitted for that held case in the current batch. The public card contains only
`factory_bug: {finding_id, gate_or_stage, summary_class}`: `finding_id` is the
existing exhaustion UUID4, `gate_or_stage` is the code-recorded gate/stage (or
`unknown`), and `summary_class` is the fixed value `factory_bug`. No model prose,
reproducer or case evidence is public. Retain the private finding at
`diagnosis/<finding_id>/finding.json` in the encrypted checkpoint. `unbug status`
shows a needs-attention item with action `factory bug: see finding <id>`; that
ordinary attention list is the human handoff. B owns the single status rule.

After a fix merges, an ordinary same-owner relaunch in a later batch release
containing it goes through the normal `bind()`/import path. D reads the normal
verified release/source binding, not a separate fix credential or message. Keep
at most three lifetime factory-bug resumes: record admission before work, retain
it across waits/crashes and do not count retries of that admitted resume again.
A fourth retires. Clear the old `infrastructure_gate` before admitted work; the
completed private finding remains evidence. A new exhaustion gets a fresh ID.
The current retirement-only legacy-import proposal does not authorize this
resume; B's normal bind/resumable-import path must supply ordinary authority.

Affected failed operations and their replay go to `infrastructure_waste` by
unique operation/event IDs and settled receipt sums. This is reclassification:
$12 booked with $4 classified becomes case $8 + waste $4 = batch $12. It creates
no headroom and adds no charge twice. Keep later receipt growth on the same
attribution. Historical schema-v1 `fix_commit`/`fix_attribution_sha256` records
remain readable, but are not a fix-delivery prerequisite for the new lifecycle.
The retained validated finding and ordinary release/restore binding establish
the source; attribution still requires actual operational receipts, never a
model's asserted dollar amount. Preserve additive legacy `infrastructure_kill`
records, whose charges have no already-booked event IDs.

Parent clarification, 2026-10-30: infrastructure exhaustion keeps a PRESENT
pending projection with `replacement_eligible:false` before diagnosis completes.
B therefore queues its same-owner diagnosis and derives no child. Completed
factory_bug diagnosis returns None under the existing completed-state rule and
sets `terminal_stop: factory_bug_held`. No new B fact or component is needed. The batch fills available slots with ordinary
new cases. Other exhausted cases already covered by the one-child journal do
not gain another child when a factory bug is diagnosed. At batch bounds,
unfinished work retires without blocking other cases. Tests cover held-state
purity/no work, content-free status, same-batch refusal, normal later-release
resume, three lifetime admissions with replay, no infrastructure replacement,
and unchanged cumulative spend under waste reclassification. No row closes
without the required real-artifact qualification.

Implementation decisions for the held lifecycle:

This increment implements the hold and refusal, not later-batch resume or waste
attribution. The present `infra-attempts.json` has no per-attempt operation links.
Therefore `eligible_operation_ids` and `failure_receipts` are always `[]` here,
code intersects the schema-valid `affected_operations` with that empty eligible
set (rather than rejecting a nonempty list), and no schema-v2 waste record is
emitted. Retain the raw model output privately; the normalized accepted finding
has `affected_operations: []`. Historical charges remain on the case
line. The causal-receipt producer, replay mapping and v2 attribution activation
below are requirements for a later reviewed addendum, not existing evidence or
an enabled path. This closes ordinary-budget headroom until those proofs exist.
The case can still be diagnosed and held; no in-batch work waits for the addendum.

- `factory_bug_held` is exactly the `terminal_stop` literal, with `status: stopped`
  and no scored case failure. Public `gate_or_stage` is one of the valid
  `run.GATES` names (that list excludes G12), `stress`, or `unknown`. It comes only
  from code-recorded stage/stop metadata, never the model's `component`.
- `diagnosis/<finding_id>/finding.json` has exactly `{schema_version:1,
  finding_id, held_batch_id, held_release_sha256, diagnosis,
  eligible_operation_ids, failure_receipts}`. `diagnosis` is the validated result
  schema above. The code supplies the UUID, authenticated current batch/release,
  sorted operation IDs, and `{path, sha256}` failure-receipt references. It never
  copies model-supplied authority into these fields. The private finding's
  canonical digest is `diagnosis_sha256` in waste records.
  The producer retains each accepted raw judgment privately as
  `diagnosis/<finding_id>/raw-result-<canonical-json-sha256>.json`; normalization
  never overwrites model evidence. A replay uses the immutable finding without
  inventing a new raw model result. Malformed raw outputs remain the diagnosis
  dispatcher's responsibility to retain before schema repair.
- Eligible failed operations are only those linked by code to an execution
  attempt classified `invalid-infra` at the recorded stage. The code's attempt
  receipt must list the operation IDs admitted in that attempt and bind their
  ledger reservations/usage receipts. A model may narrow this set through
  `affected_operations`, never enlarge it. Mere expenditure, a budget/round
  stop, provider waiting, cancellation or a substantive gate failure does not
  establish factory-bug causation. Without that code evidence the eligible set
  is empty; the diagnosis can still hold a bug, but no historical charge is
  reclassified. `affected_operations` may therefore be empty. Retry operation
  IDs qualify only through a code-written link to that eligible failed unit
  during its admitted resume; they are not free-form model output.
- A new waste record has exactly `{schema_version:2, kind:"factory_bug", id,
  finding_id, diagnosis_sha256, resume_id, resume_binding_sha256, operation_ids,
  event_ids, infrastructure_waste_usd}`. `id` is `factory-bug:<finding_id>`.
  IDs are sorted unique sets; event IDs are exactly the settled reservation
  events for the eligible failed/replay operations; the amount is their sum as
  a nine-place USD string. No record is emitted for an empty set. Extend that
  same record on later settlement, never append another charge. `resume_id`
  refers to the durable history below, and `resume_binding_sha256` hashes that
  exact history entry using UTF-8 JSON with sorted keys, compact comma/colon
  separators and allow_nan=False (the existing carry_over.digest convention).
  Future settlement growth must preserve the nine-place string amount, not
  rewrite it to a float. V1 records remain decode-only historical evidence;
  new producers do not fill dummy fix commits or ask for fix credentials.
- Hold records retain `held_batch_id`. A later resume requires a different
  authenticated `batch_id` and `batch_release_sha256`, the same case lineage,
  and a normal verified bind/import that preserves cumulative usage and history.
  "Same-owner" across batches means the same continuing case, not reuse of the
  previous batch/job/reservation money owner. B issues the new owner normally.
  Inclusion in that later batch's approved manifest is the operator's decision
  that the fix is present. D does not independently attest a code fix. Resuming
  without the fix still consumes one of the three lifetime admissions.
- The encrypted `factory-bug-resumes.json` will store an append-only list of exactly
  `{schema_version:1, resume_id:<uuid4>, finding_id:<uuid4>, case, held_batch_id,
  batch_id, job_id, reservation_id, source_generation, batch_release_sha256}`.
  The current binding fields come from B's verified context; source_generation
  is the input checkpoint, never its containing output checkpoint. Each finding
  and resume ID occurs once, with at most three entries. On the first held
  finding, create missing empty history only when there is no prior factory_bug
  card field, factory_bug_resume_count, retained finding, or factory_bug waste
  record of any schema. This includes pre-rollout running cases without inventing
  prior resumes. Atomic durable write order is history first, finding second,
  public marker, completed diagnosis_state and terminal_stop together last;
  a crash before the finding can replay the empty history,
  but a retained finding/hold with missing history refuses. Malformed history
  never resets. Public `factory_bug_resume_count` is a top-level integer equal
  to its length, present only once a valid history exists; a first hold shows 0.
  Unreadable history or missing history that cannot safely initialize removes
  the count and stops as factory_bug_history_invalid
  (check case), never as a zero count. Append before any resumed model work. A replay of the same admitted finding
  retains its entry/ID, including wait/crash continuation, and does not debit
  another slot. This replay rule applies to the same admitted binding; movement
  of an already-admitted resume into another batch belongs to B's reviewed
  cross-batch addendum. A subsequent held finding has a new exhaustion/finding ID.
  An unresumed hold stays charged to the case line. Future successful replay of
  eligible failed units is waste only through the code-proven links, bounded by
  the three admissions and those eligible units; arbitrary later work is excluded.
- A crash after the finding but before the completed public state reuses the
  immutable finding for that exhaustion ID before any further model invocation.
  A differing replay refuses instead of overwriting it. A non-factory_bug result
  cannot delete retained evidence. Completing the public state still requires
  a valid history and verified finding binding.
- B currently refuses cross-batch resumable imports. That reviewed B addendum is
  an explicit prerequisite for the later-batch resume and its integration test.
  D can ship holding, state validation, attribution restrictions and refusal now;
  no D flag, public card or retired legacy-import record bypasses B's refusal.
  The current batch proceeds with ordinary other cases and has no fix dependency.

The public stage mapping uses the original code-recorded stop and only valid
`run.GATES` labels (that list itself excludes G12):

| Original stop | gate_or_stage |
| --- | --- |
| infrastructure_exhausted | infrastructure_gate.gate if in run.GATES, else unknown |
| late_defect_needs_ruling:<gate> | the validated gate suffix |
| stress_review_unresolved:* | stress |
| budget_exhausted | unknown (the literal does not identify a role) |
| extension_incomplete | failed_gate if in run.GATES, else unknown |
| anything else | unknown |

Required parent-ruling replays: pending known-total infrastructure has a present
ineligible projection, queues one same-owner diagnosis and derives no child;
a completed factory_bug diagnosis has `terminal_stop: factory_bug_held`, projects
None and derives no child. D tests its states/API with the B core where possible;
B owns the adapter end-to-end test. Resume-count/binding tests remain offline
until B adopts the cross-batch path. Use saved 5813be for pending/completed
infrastructure and the missing-history first-hold replay; use its retained ledger
for input/charge preservation. The pre-rollout card acquires history on first
hold; its later-resume test is an offline binding/history test until B adopts the
path. Public-stage/count refusal tests use authored mutations of those real
bytes. These do not claim rollout qualification.

## Resume, accounting and checkpoints

Extend existing receipts: operation ID, input/version binding, phase
`pending|completed|validated`, output digest, reservation/settlement and next
phase. Commit writer completion **before G1**. Resume completed calls at
validation; continue unfinished authoring from saved draft/findings under its
existing round. **V2 = every V1 receipt field plus the fields shown below**, not
a replacement schema. Keep round_limit, binding (per-key dict), report,
release_rereviews, release_review_attempts and existing pending/review_attempt
keys. binding_sha256 supplements binding (hash of its canonical JSON).
Schema-v2 writer/stress examples (full SHA-256 values in storage):

```json
{"schema_version":2,"round":9,"operation_id":"<uuid4>","phase":"pending",
 "repair_pending":true,"lease_id":"L2","resumed_from_wait":"<uuid4-or-null>",
 "invocation_id":"<uuid4>","binding_sha256":"...","output_sha256":null,
 "next_phase":"G1","extension_id":1}
```

```json
{"schema_version":2,"round":9,"operation_id":"<uuid4>","phase":"pending",
 "review_pending":true,"review_attempt":"<stable-uuid4>","lease_id":"L2",
 "resumed_from_wait":"<uuid4-or-null>","invocation_id":"<uuid4>",
 "binding_sha256":"...","output_sha256":null,"next_phase":"gates",
 "report":"round-9.json","extension_id":1}
```

The writer output digest is the sorted case-file digest used by case_hash;
stress output digest hashes the completed JSON report. On call completion set
phase=completed, clear the corresponding pending boolean and save output digest;
after validation set phase=validated. A crash after completion resumes validation,
not authoring. During re-admission lease/invocation may be null only with the
verified resumed_from_wait marker. Legacy receipt migration preserves every
old field/count: infer completed only from authenticated output/usage completion
receipts; otherwise pending, reconcile or continue from saved draft. Missing
lease ID without an authenticated archived wait is a real crash. Never fabricate
an old lease or infer completion from file existence alone. For a verified active
extension, saved round_limit is the one authorized extension round number;
validate n against it and the immutable extension entry, and bypass the ordinary
min(args.rounds,saved_limit) clamp. Without an active entry, keep the ordinary
clamp. Example: active extension 1 at n=9/saved_limit=9 resumes; n=10 or an
unbound n=9 is rejected. Do not reuse limits_raised/ruling.allowances: those are
human, fungible round grants and do not prove a specific one-round extension.

Reconcile uncertain live operations first through the exclusive
case lease; never blindly duplicate them.

Reserve money atomically in the case ledger before every call, including G10.
Maximum = enforced request count × (maximum input/cache tokens × highest
applicable input/cache rate + maximum output/reasoning tokens × output rate),
plus bounded provider tool fees, using the pinned effective route price table
(`token_prices.py` and A’s paid route receipt rates). Use context-window maxima
where the CLI cannot predict input length. E/A enforce those request/token
bounds; missing bound/price makes the maximum unknown. Unbounded routes cannot
dispatch: A selects an
approved bounded same-family route or waits. Settle receipts by invocation/event
ID. Missing final usage: recover saved CLI/provider events, otherwise charge the
reserved maximum explicitly as estimated. A later receipt replaces the estimate
once. Imported unknown usage without a reservation must be reconciled from saved
events; otherwise charge an explicit conservative import estimate and retire only that
case: known booked total plus **$33 per unknown invocation** (ceil of the largest
authenticated CLI result aggregate observed in this corpus, $32.6137984).
This is empirical and aggregate-derived, not an invocation maximum (the source
may aggregate logical rounds). Import dry-run emits the known spend, unknown
count, estimated added charge and final total for each case and the whole batch.
The founder authorizes those **numbers**, not only a policy; $33×10 = $330 is
visible before import. The estimate counts against the cumulative batch bound. Missing invocation count refuses that case’s
import, without entering the new batch ledger. No other case is frozen pending
reconciliation. Late receipts replace estimates by stable import/wait/event IDs.
Never zero it or make every case’s ledger nonnumeric. G10 capped/
no-submission outcomes stay distinct from demonstrated wrong fixes; C supplies
scoring eligibility. Missing G16/G17 evidence uses the same execution path.

Malformed JSON retains raw output/errors; request schema-only repair from the
same family with that answer/schema, then use A’s fallback if still invalid.
For deterministic malformed output, try each approved same-family route once
per identical input/schema digest; exhausting that set retires this case. Provider
conditions remain A/B waits, not deterministic failures. Changed evidence/schema
permits a new digest. Backoff under batch time/money; no extra retry allowance
or malformed writer feedback. The same deterministic-failure rule covers diagnosis.
Refresh G2 trusted retrieval evidence at its 24-hour boundary before reuse.
Retrieval outage retries as infrastructure; confirmed match retires; substantive
conflicting reviews follow the independent-family/founder rule. No uncertainty
becomes PASS. Retain old evidence and current dependency bindings.

Stress commits findings and coverage categories incrementally; continue only
unfinished coverage after timeout. Each writer completion, stress category,
calibration attempt and mechanical checkpoint unit publishes an encrypted
immutable generation through B’s checkpoint/publication path before further
expensive work. Missing remote acknowledgement blocks new paid dispatch.
D checkpoints completed calls only. Mid-call writer snapshots/yield are explicitly
deferred to E: do not assert CLI suspension/resumption is available. During
G10’s overlap with **mechanical** work persist isolated committed attempts and
settled usage (model calls remain serialized), never copy
mutating shared directories; B composes those immutable units. E owns bounded
cancellation/join. Restore only acknowledged units; retain reservations for
unacknowledged calls. Snapshots and case revisions are part of every generation.

## Cost evidence: $15 is unsupported

`stream-d-cost-evidence.json` freezes public excerpts, source hashes and the
54-card VM inventory read on 2026-10-29. Sources: `input-scorecard.json` and
`sealed/*.scorecard.json` in both specified `*-restore-14-20261029` bundles;
VM `/home/user/unbug-bench/sealed/case-*.scorecard.json`. No archive/secret opened.
Sum `cost + list_cost_usd + estimated_subscription_cost_usd` once per event ID;
never add ledger totals to their constituent events. Historical receipts only.

- 873d7f `builder-1`, `b741739e-bdec-4272-8b41-4a7703b02d52:result`:
  **$15.0531879 writer alone**. Later `builder-8` is $0.744762; e15450
  `builder-10` is $4.3304802. Cheap late rounds cannot prove a safe package cap.
- 873d7f `attacker-8`: 41 events, recorded $0 on the then-free route;
  e15450 `attacker-9`: 26 events, recorded $0. Paid freshness stress totals
  $0.032489508/$0.041890088 are not whole stress rounds or current price quotes.
- VM 195b92 writer-family event `ca2f9bdf-be15-4883-941e-5935607fbea9:result`
  cost **$32.6137984**, but lacks an invocation label; do not call it an
  identified writer round; it may aggregate multiple logical rounds.
- Identified numbered writer rounds in the two recent cards range **$0.4463424–
  $15.0531879**; that is planning history, not an extension maximum. e15450
  has $30.09905083 across 124 unattributed events (about 57% of its $52.7866
  case spend), so even its latest card cannot attribute a complete round package.
  The range excludes selection/prototype/freshness author calls; those are still
  writer work and never permit a second author edit inside an extension.
- Both recent cases have empty final gates. Three VM cards record G10 passes;
  their old ledgers do not attribute a complete gate rerun. No card records a
  G16/G17 pass or labeled G16/G17 review receipt. The $0.0042488 calibrator
  preflight is not G10. **The authorized evidence cannot price a complete writer,
  stress and G10/G16/G17 package.** Delete $15 rather than invent a higher figure.
  The batch manifest supplies the sole authorized cumulative model dollar bound.
  A case may consume its full job commitment across up to five extensions; no
  package expectation is known. Cost of version migration below may likewise
  consume the full commitment; do not promise a cheaper expected rerun.

## Exhaustion routing and effective money source

These stops enter diagnosis and the replacement rule: `budget_exhausted`,
`stress_review_unresolved:rounds_exhausted`, `late_defect_needs_ruling:<gate>`
at the ordinary round limit, and an active extension’s completed gate-still-
failing outcome. Preserve their stop emission while deleting the final writer.
`late_recovery.stop_defect` records evidence but no longer requests founder
ruling for these states. `recovery.py:95–164` and `run.py:921–929/2532` stop
requiring founder_ruling/raised_limits; map the authenticated diagnosis plus
code eligibility instead. Retain founder_ruling.py only for historical evidence
and substantive reviewer disputes, never as exhaustion authority.

Single source for effective money = validated job committed_total_usd (total
including waste), not argv. At startup, set c.args.case_budget, the card’s
case_budget.limit_usd and recovery_config.case_budget from that source;
model_runtime.py:351 passes that same value to run_budgeted, whose budget.py:255
check uses it. update_case_budget preserves ordinary_limit_usd separately.
coordinator.py validates the effective value against the current job revision,
not the original ordinary argv; restart.py does likewise. CLI --case-budget is
only an ordinary-limit input before manifest authorization; imported argv cannot
replace job authority. An active reservation authorizes its own current call;
require_case_budget subtracts that reservation when checking that call to avoid
reserving it twice, while counting every other outstanding reservation.
These authority/total checks apply to authenticated factory jobs; non-factory
exam-owner callers keep their existing budget/cap semantics.

For factory_bug waste, accumulate observed cost/list/estimated totals across
**all** events first, including reclassified IDs. Compute legacy remainder from
those full observed sums; only then subtract classified IDs from the ordinary
role breakdown and add them once to waste. Otherwise they reappear as
legacy_unattributed. The $12→$8+$4=$12 test covers both ledger totals and events.

Before enabling D, E/A must supply a route-maximum report for every role beside
the real receipt planning range. An approved writer route maximum exceeding the
ordinary limit (default $50), or missing enforceable bounds, fails qualification:
no case/replacement launches. E must provide a tighter bound or an authorized
ordinary-limit change. Fresh jobs lacking enough commitment return money_wait
without starting a replacement chain. This is an external rollout prerequisite,
not a guessed multiplier in D.

B’s provider_wait_deadline applies when its provider-wait queue reaches the
deadline; D’s retired_batch_bound applies to non-provider extension/diagnosis/
money work. Both are unscored and terminal in that batch. D’s pre-B tests use
an authored job configuration at tests/fixtures/factory/stream-d/job-money.json
(schema v1 above), paired with the saved real practice bundle; it is contract
configuration, not a case generated by the code under test. B’s real published
job receipt replaces it in end-to-end qualification.

## Remove the paid cap everywhere; migrate its bindings once

`max_cost` is a cumulative paid-route accounting policy, not a per-contestant
scientific exposure limit. Remove its enforcement, not G10’s time/call limits.
That removal can change which runs complete, so it is **an intentional binding
migration**: stress, G8, G9, G16, G10 and dependent G17 evidence must use the
new accounting-policy version. Retain the original fingerprints/results as
historical; never relabel them. Other gate evidence is kept if dependencies
match. When the next extension comparison needs it, rebase the entry revision
and outcome under that same new version. One-time cost = two evaluations of
each affected, unreusable stage needed for the comparison, within the assigned
commitment. Receipts cannot give an expected price for these G10/G16/G17 reruns;
worst allowed cost is the remaining commitment. Do not run without that authority.
Pass criteria and time/call exposure limits remain unchanged.

Paid-cap/allowance inventory (line numbers refer to the design baseline):

- `budget.py` ~190/204/217/263/307: retain optional max_cost for non-factory
  callers. New authenticated factory jobs pass max_cost=None plus validated job
  authority via new run_budgeted(job_authority=validated_job) keyword; disable
  both priced-cost checks only in that branch and enforce
  commitment/reservations. None without valid factory authority is rejected.
  Legacy/default non-factory callers keep their numeric cap and validation.
  Incremental receipt booking stays.
- `model_runtime.py` ~180/198/345: update_case_budget preserves ordinary_limit
  and takes effective limit from the job authority; remove writer_round_estimate
  and send max_cost=None with validated factory authority (non-factory calls
  still forward their numeric value). `budget.require_case_budget` checks effective money
  including pending reservations; it does not recreate the ordinary trigger.
- `run.py` ~1949/2400/2499: remove calibration identity’s max_cost input, CLI
  enforcement default and recovery_config field; accept --max-cost only as
  deprecated historical input for old argv imports. Imports retain old values only
  in historical metadata. Unknown legacy max_cost never becomes zero authority.
- `gate_state.py` ~124/141: remove max_cost from stress/reviewer/G16 scientific
  settings and record the intentional migration above. All other scientific
  settings remain. The migration exam checks exact changed-stage membership.
- `coordinator.py` ~28/162: remove max_cost recovery equality/type checks for
  new-schema jobs; preserve ordinary/commitment/deadline bindings instead.
- `ttl_continuation.py` ~34/155/175/243–244: remove max_cost job propagation,
  equality/type validation and priced-cost stop. Use cumulative job authority.
- `key_holder.py` ~311: remove cost>=job[max_cost] recovery refusal. Keep job
  authority, ownership and the reviewed provider-wait backstops.
- `g11_review.py` ~100–119/169: remove legacy max_cost import/clamp/refusal and
  the hidden +$0.50 audit allowance; use normal invocation reservation and job
  authority, reporting that authority instead of residual paid wallet spend.
- Legacy import/export wrappers may decode max_cost for old receipt validation,
  but no launch, resume, gate, audit or continuation may enforce it on new-schema
  work. The search exam classifies remaining matches as historical decode,
  exam-owner protection or fixture data, never new-schema factory admission.
- `restart.py` ~57/72/76 (A-owned area, minimal D edit): remove retries<3 and
  paid cost>=--max-cost; the retry count stays telemetry only. Read effective
  money from validated job authority, not ordinary --case-budget. A’s provider
  classification remains; cap retry backoff at 60 minutes (15/30/60 thereafter),
  bounded by remaining deadline. Section 5 waits change no counters.
- `run.py` ~916/936/1027/1110 (D): remove the two stress re-review and eight
  infrastructure-attempt terminal bounds and diagnostic_allowance_exhausted
  branch for new-schema work. Retain history/IDs as evidence, not allowances.
- `key_holder.py` ~185–196 (B-owned, minimal D edit): remove counted>=3 cohort
  recovery refusal for new-schema jobs; delete additional_attempt authorization
  in new jobs/callers, decode it only as historical evidence. Keep concurrency/authority validation.
  B’s reviewed section 4 wait backstops remain; §5 holder counters are exempt.
- `carry_over.py` ~37–39/242/330–340 (D import): retain legacy operation counts
  as historical facts, remove OPERATIONS/INFRASTRUCTURE_LIMIT as new-schema
  admission caps. Its legacy projection cannot refuse import for an exhausted
  case allowance/budget; hand exhaustion to diagnosis after usage settlement.
  Keep schema/artifact/usage validation; estimates require the dry-run numbers.
- `ttl_continuation.py` ~192/194/281 (B-owned): old TTL/preparation action counts
  are historical; B’s single launcher replaces their enforcement. Wait/relaunch
  is exempt immediately under §5; D does not invent a new TTL path or counter.
- `bin/run-exam` ~250/270/279: **retain** owner-max-cost default $5, its numeric
  forwarding and tests/bench/test_run_exam.py expectations. It has no factory
  job authority, so the shared runner’s non-factory branch above applies. Its
  scientific owner behavior is unchanged; G16 does not lose this protection.
- `factory/README.md` ~404–423: document factory’s cumulative authority and
  legacy CLI import separately from the unchanged exam-owner cap.

## Implementation and exams

Estimate: one engineer, five to eight working days after A, excluding waiting
for B/E interfaces or missing public artifacts. First additive receipts and
accounting; then diagnosis/extensions; then fault replay and full-suite/diff
review. Reuse `budget.py`, `restore_ledger.py`, `run.py`, `recovery.py`, `restart.py`,
`gate_state.py`, `calibration.py`, `durable_checkpoint.py`, `coordinator.py` and
`key_holder.py` admission. Add diagnosis prompt/schema and extension eligibility/
history logic only. A owns routing, B verified generations/queue/launcher, C
invalid classification, E route bounds/isolation; do not create competing paths.

Import preserves spent/waste/rounds. Missing extension history means zero only
with receipts proving none; otherwise reconcile/retire. Over-threshold imports
enter diagnosis. Pin minimum checkpoint reader version; old readers cannot launch
new generations. Rollback must retain all later spend/count reservations. Enable
policy and remove old branches together; amend ENGINEERING section 3’s allowance
bullet in that implementation commit.

Per-file work and phase exams (all changes are future implementation):

1. **Receipts/accounting:** `budget.py` adds case-local operation reservations,
   `settle(record)`, event/wait dedup and factory_bug validation; keep streaming
   event booking. `restore_ledger.py` imports history, estimates and settlements
   without dropping later records. `token_prices.py` supplies maximum pricing
   with A’s effective paid-route prices. Exam: the $10/$8 example above, two
   resumes, $12→$8 case/$4 waste/$12 total reclassification, and the real 873d7f
   $16 legacy waste receipt stay single-counted. With commitment $13 and total
   $12=$8 case+$4 waste, only $1 remains available, never $5. Imported unknown estimates
   replace once and the dry-run $330 charge is visible before authorization.
2. **Control logic:** `run.py` calls await_lease before writer/re-review receipt
   writes, passes Lease, settles/archives waits before any call, persists writer
   completion before G1 via on_complete callback inside opencode after runtime.call returns
   and before its automatic checkpoint (~199–208), adds
   extension state and one-round range, disables
   extension gate repairs and removes final-fix calls and `--max-cost=5` checks
   (including calibration child limits near old line 1949). `gate_state.py`
   supplies all stage scientific version inventories. `late_recovery.py`
   preserves snapshots; `recovery.py` dispatches diagnosis vs provider wait vs
   real crash; `restart.py` preserves A’s wait exemptions. Add
   `factory/diagnosis.py` (new case-level schema validation; reuse the isolated
   read-only dispatch pattern from `sealed_audit.py`/`g11_review.py`) and
   `factory/prompts/diagnosis.md`; use `work/diagnosis.json` inside the checkpoint.
   Exam: builder_rounds 8→9 once, zero repairs, zero counters changed by a wait,
   same-version regression retires, changed-version comparison remains pending.
3. **Integration:** `coordinator.py`/`admission.py` expose D’s eligibility and
   money commitment checks to B’s existing queue/lock; `key_holder.py` removes
   ordinary recovery attempt caps but preserves B’s wait exemptions. These are
   minimal edits in B/A-owned areas, no contract-shape changes.
   `durable_checkpoint.py`, `run_artifacts.py` and `calibration.py` persist the
   new receipt/history files and completed isolated units via B; no new uploader.
   Add replay tests in `tests/factory/test_stream_d.py`, with named artifacts
   and source hashes. Amend ENGINEERING §3 allowance/pointer and the single-path
   rules. Exam: spent $44/max $12 invokes diagnosis without a call;
   missing/stale commitment refuses dispatch, two parallel jobs
   cannot reserve beyond one batch bound, and B’s practice wait→settle loop passes.

Tests use the saved cards above and retained **public-practice** receipts/bundles;
capture missing public units later, never decrypt sealed cases or generate cases
with the code under test. Rows 10/35/39 remain open until the missing real public
crash/capped-call bundles exist. Required assertions:

- 8/9: $5+ paid spend below batch bound continues; exhaustion queues one replacement
  and diagnosis; both sealing keeps both; sixth extension/fourth bug resume and
  duplicate/concurrent over-reservation are refused.
- 10/11: kill before/after writer completion, G1 and extension reservation; restore
  exact phase/IDs/spend. Missing credentials before first admission yield zero
  reservations/usage/counters. For sequential fallback, merge L1 (max $6, booked
  $3) and L2 (max $4, booked $2), both unknown, while next candidate is account3.
  settle adds only $3+$2 gaps: total $10; replay adds $0; candidate fields have no
  effect. Duplicate aggregate/leaf event IDs never double-count.
  For writer and stress, chain three waits: L1 interruption,
  null-lease denial after settled resume, L2 interruption. Kill after settlement,
  pending reset, archive, new Lease and reservation. All continue the same unit;
  no round/extension/restart/holder/coordinator/re-review counter increments.
  On a saved exam-exposure G10 attempt, answer an actual pilot owner question
  while the tester holds its lock: two distinct family-correct leases, independently
  bounded reservations, no deadlock. Repeat with owner denial and interrupted
  owner usage; cancel/join the tester, expect terminal_stop=provider_wait and
  one A record (leaf or aggregate), settle the linked tester and owner leases
  twice and assert the second adds $0. Neither attempt is scored or writer feedback.
  With UNBUG_PROVIDER_WAIT=0, an interrupted unknown receipt does not enter
  router_deferred; A’s existing exit/cancellation and crash reconciliation work.
  A denied-before-work null record books $0; mismatched real crash books the
  conservative gap once. Four reset/outage waits resume within batch bounds.
- 12/13/15: expire G2; fail retrieval; interrupt stress coverage; replay malformed
  model answers. No stale/incomplete evidence passes or becomes writer feedback.
- 21/39: replay missing-final-usage/capped G10; reconcile or reserve conservatively;
  late receipt settles once; no submission never proves wrong_fix.
- 35: worker loss after each committed unit restores the
  acknowledged generation. Mid-writer crash closes only when E supplies safe
  units; row 35 remains open for that part. Upload/ack failure stops paid dispatch. Repair clears
  current gates but preserves snapshots. Gate-version migration keeps unrelated
  passes and compares entry/outcome at one version; true regression retires.
  Saved-card fingerprint exam lists the intentional stress/G8/G9/G16/G10/G17
  migration and proves unrelated gate digests unchanged; no old receipt is renamed.

Update existing expectations, retaining scientific/receipt assertions:
`tests/factory/test_budget.py` (factory-vs-exam cap branch, totals and settlement),
`test_carry_over_fingerprints.py` (intentional changed bindings, not old max_cost
mutation), `test_carry_over.py` (historical counters vs new admission),
`test_ttl_continuation.py`, `test_g11_review.py`, `test_restart.py`,
`test_key_holder.py` and `test_coordinator.py` (effective authority, removed
factory allowance refusal and §5 exemptions). Preserve
`tests/bench/test_run_exam.py`’s owner cap expectations. Also migrate unlisted
max_cost fixtures/tests found by the search (including test_case_budget.py,
test_model_runtime.py, test_resume.py, test_recovery_routes.py and
test_paused_recovery.py). Update saved fixture
settings only with explicit schema/version migration records; do not regenerate
evidence with the implementation. No whole test file is deleted by D.

Run `uv run --with numpy --with scipy python -B tests/run.py`, then a fresh diff
review. Only real-artifact tests close Murphy rows. Main risks: unbounded routes,
false diagnosis/refunds, costly version rebasing and B/E dependency; the rules
above fail closed at the cumulative batch bound. Success: these rows cause no
human pit stop, accounting survives, and gate standards stay unchanged. No paid
run belongs to this design. A later public-practice qualification must capture
G10/G16/G17 package receipts before claiming a package price or throughput.
Founder still authorizes batch money/deadline and conservative-import policy
at launch. No founder action is needed for this documentation; a fixed extension
price would need new package receipts. B/E dependencies are rollout blockers,
not implementation choices to guess around.

## Incremental implementation obligations (diff review 1)

Increment 1 adds accounting primitives only; it enables no dispatch and closes
no Murphy row. The initial diff review is recorded verbatim in
`docs/reviews/stream-d-diff-1.md`. Before enabling the runtime, increment 2 must:

- Pass each reservation's invocation_id through run_budgeted/_run_budgeted to
  incremental events and unpriced_invocations, so settle removes only the
  matching unknown invocation. Cover the real streaming-accountant path.
- Release an admitted but never-invoked lease at known $0, and conservatively
  settle a crashed admitted reservation with no receipt. A provider denial
  before any lease still creates nothing. Preserve operation IDs across waits.
- Use the concurrent streaming accountant (short ledger transactions) for
  new-schema jobs while the case RLock serializes actual model dispatch. Never
  hold the ledger's serial session lock while an independently reserved G10
  owner call can be nested. Root concurrent_roles/scientific settings stay pinned.
- Obtain the cumulative limit only from JobAuthority, never card/argv. The
  reserve_invocation API now requires that object. The raw numeric limit is no
  longer an accepted argument.
- B must install job_money from the checkpointed channel, and install
  authenticated_job_config['job_money'] from its current holder-delivered frozen
  launch configuration. It must independently install batch_id, job_id,
  batch_deadline and source_generation from the verified launch/restore binding.
  Do not populate both copies from restored files. Until B supplies this installer,
  for_case fails closed. No delivery filename/environment convention is invented
  by D. Deadlines compare UTC instants, as A's metadata API permits.
- Authenticate the retained diagnosis and ordinary release/restore binding before
  reclassify_factory_bug. This accounting helper validates shape, settled sums
  and idempotence; no separate fix-delivery contract is required (parent ruling
  2026-10-30). Historical fix-attribution fields remain decode-only evidence.
  Initial attribution waits until all named operation reservations settle. A
  later final receipt extends the same waste record by its unique event IDs;
  it never creates a second record or changes cumulative batch spend.

The parent adopted the no-fixed-amount amendment in ENGINEERING §3 at a3bb9dc.
Dispatch still requires both B's qualified channel and E/A's enforced route maxima.

Money precision for the additive accounting helpers: a single Decimal valuation
preserves provider precision through summation, including derived legacy Codex
prices. Ledger settlement adds raw event amounts as the streaming accountant
does. Role rounding never feeds the cumulative total. Initial factory-bug
attribution and late receipt extension use that same valuation; public total
and waste round once to nine places and ordinary spend is their difference.
Stored event_ids/amount are derived; id, diagnosis/fix attribution and
operation_ids are immutable and define replay identity. Existing settled waste
stays classified while a replay lease is pending. Maxima and unknown gaps round
up to the nine-place unit. Public card totals remain JSON numbers for compatibility;
the B channel and reservation money strings use nine fixed decimal places.
reserve_invocation rechecks the absolute authority deadline. Increment 2 must
still call for_case immediately before every reservation, binding the current
revision/source generation; never cache an authority across separate calls.

Saved-card compatibility exam for Decimal valuation: the 20261029 recovery
snapshot has exactly three projection differences, each removal of a zero-valued
legacy_unattributed role label, for cases 6a8a7d, cae763 and 055481. The regression
pins each original canonical card hash before applying that exact expected-field
migration in memory. All saved totals, source cards and recovery/scientific
decisions remain identical. Neither the captured cards nor the frozen before
snapshot is regenerated or rewritten.
The coordinator supplies factory-bug amounts as usd(sum(event_charge(event)))
over the attributed event IDs, preserving the same valuation through admission.
Settled rows alone determine derived late-attribution event IDs, even while a
new replay lease is pending. The input event_ids/amount fields remain part of
the reviewed schema; they are checked, never taken as a second spend booking.

## Increment 2: runtime and pending-unit integration

This increment wires the accounting foundation into authenticated factory jobs
(batch-release binding or installed job_money). Legacy non-factory execution
keeps its numeric cap until the separate cap-migration increment. Every new job
needs B's independently installed current binding and E/A's qualified effective
route bounds. The enforcement inventory is intentionally empty: tests inject
authored bounds, but no production route is qualified by prices or receipts.
Missing/stale authority or unknown bounds refuses model work. Reporting still
projects settled spend after authority expires; it never grants admission.

Dispatch shares one case RLock through automatic checkpointing; G10's owner
alone may bypass it when a matching tester reservation is active. The merged E
owner server is ThreadingHTTPServer with an owner_lock, so that bypass uses the
existing single active owner request rather than changing the HTTP contract.
Both tester and owner reserve independently. The factory streaming accountant
uses short ledger transactions even when scientific concurrent_roles is false.
Events and unknown invocations carry the admitted invocation/lease IDs. A known
completion or never-started denial releases its reservation; an exclusive crash
reconciliation conservatively charges a missing receipt and late receipts replace
the estimate. Live parent calls are excluded from child reconciliation.

Writer/stress receipts retain V1 fields and add V2 operation/phase/binding/output
fields. Admission precedes receipt/counter mutation. Writer completion is saved
inside opencode before its automatic checkpoint and before G1; restored completed
work resumes validation. Provider settlement precedes pending reset and archival;
the archive plus ledger wait marker proves continuation while awaiting a new
lease. L1 interruption, null denial and L2 interruption keep one operation and
round. UNBUG_PROVIDER_WAIT=0 never forces deferred admission. The absolute money
deadline bounds the accountant; its expiry is retired_batch_bound, never a
contestant timeout. Final accounting reconciles only after calls join, leaving
provider-wait settlement for resume as specified.

tests/factory/test_stream_d_runtime.py replays the captured paid ledger 5813be
(already above $5) and hash-verified captured public-practice files, with authored
CLI envelopes, model outputs, provider conditions and job configuration. It
executes the real streaming accountant, local router and owner HTTP protocol.
It makes no real-crash, B/E qualification or Murphy-row closure claim.

Still pending in subsequent increments: diagnosis/extensions and immutable stage
snapshots; legacy receipt/import migration; complete removal of new-schema stale
allowances/caps across launch/resume/audit; scientific binding migration; B's
acknowledged checkpoint integration and lifecycle qualification; real crash/capped
artifact closure exams. No row closes with this incremental runtime wiring.

### B collection/settlement integration obligations

The contract is now landed in [interfaces §8](interfaces.md#8-batch-money-authority-b-provides-d-enforces),
merged with B increments 1–2 at 6abe169. Keep on-resume-only settlement and
fail-closed dispatch. B's fresh-only installer is present; its increment2b must
implement the acknowledged source transitions and collection proofs before
resume is enabled. The lifecycle qualification must cover these §8 cases:

- An unknown total permits only a same-owner conservative resume with no
  commitment increase and no new revision (the operating commitment may be lower),
  the old full commitment still held,
  and every unknown part mapped in unpriced_invocations to an admitted maximum.
  B counts the owner at its full commitment. New admission, increase, revision+1,
  replacement, diagnosis and extension remain blocked until settle yields a known
  total. Missing or unbounded attribution cannot use this exception.
  For an exhausted owner whose total was unknown at launch, D must checkpoint
  and exit after settlement without a model call. B must collect/ACK that known
  checkpoint before a dependent replacement or the next same-owner diagnosis
  resume; there is no settlement-only or diagnosis launch mode.
- A late receipt may replace a conservative gap with a lower actual charge.
  B acknowledges reconciled_decrease only under interfaces §8: an invocation
  estimated in the immediately previous ACK and settled now, with the bounded
  rounding allowance specified there. An unsupported decrease remains refused.
  D retains the invocation/wait settlement evidence in the checkpoint; neither
  side resets cumulative usage or silently releases the old commitment.
- Diagnosis uses the original's ordinary same-owner resume and a content-free
  D eligibility/projection API. B's enabled replacement policy derives J-r1,
  J-r2 and later children under the same root template, one child per immediate
  original across generations/extensions. The finite root manifest, target_slots
  and max_concurrency cannot become replacement-count caps. Adapter enablement
  waits for the concrete D API review and B's increment2b implementation.

Diff-6 runtime decisions: wrapper-only calls reserve immediately after admission,
before initial renewal or credential re-read. A lease that fails before its CLI
starts emits a known-zero denied receipt and releases its reservation. A missing
reservation may settle at zero only for an explicitly denied, final-known receipt
with no events or booked IDs; interrupted/unknown usage still refuses. The actual
Popen success callback distinguishes CLI setup failure from an interrupted process.
Every unknown process receipt has an invocation/lease attribution in
unpriced_invocations even if no streaming envelope arrived. A validated writer
awaiting stress keeps round n across a changed binding and re-reviews stress at
n; it never runs writer n+1 for a plumbing migration. Its output digest must
still match. The ordinary threshold follows await_lease because it prices the
chosen effective route; a provider wait may precede diagnosis without consuming
the unit. Rate maxima use the same existing long-context/fast/US-only tariffs as
receipt valuation, not historical-spend multipliers, with one paid-price table.

Diff-7 runtime decisions: a pending, completed or validated stress unit whose
binding changed re-reviews at its existing round n, retaining operation_id and
review_attempt. A completed report under an older binding remains historical;
only the current re-review can supply writer feedback. An unchanged pending
unit keeps its partial report and counters. The ordinary threshold is preserved
from the restored case_budget.ordinary_limit_usd/recovery_config value and never
replaced by cumulative job commitment. recovery_config.case_budget and the
coordinator's --case-budget binding describe that ordinary threshold; effective
case_budget.limit_usd comes only from JobAuthority. A legacy max_cost argument
is ignored for this new profile. A writer continuation still checks the ordinary
threshold at its next effective lease; it may exhaust mid-unit without adding a
second round. These changes grant no new money or extension eligibility.

Increment-2 source-test maintenance: C's exact invalid-runs migration test now
constructs its pinned target inventory explicitly and separately asserts that
the live D calibration source cannot inherit that grant. The production
invalid-runs-compat.json pins and captured artifacts remain unchanged. D's
intentional scientific migration is still pending; no historical result is
relabelled. The smoke preallocation test mutates the current boundary-call text
and retains its exact-source mismatch refusal assertions.

## Increment 3: diagnosis, extensions, and policy migration

**Founder decisions, 2026-10-30:** the cumulative `max_total_calls` limit is
removed for new-schema cases and their extensions; call counts remain telemetry.
Dollar ceilings apply to paid routes only. The 47 old cases are retired; cb5e2
and 14d35 are set aside. These decisions supersede the earlier provisional
parent ruling. Preserve historical D1 metadata. The scorecard
shows `model calls: N (telemetry)`. Keep per-invocation `max_role_calls`, time
limits, qualified enforced-route maxima, and the numeric protections of
`bin/run-exam`. Dollar ceilings bound paid routes; the absolute batch deadline
bounds every call.
Replay the real 5813be (2496), e15450 (1627), and 873d7f (1040) ledgers beyond
the former 1000-call threshold with authored money/deadline headroom; retain
their original events and totals and prove a further invocation progresses.

D's public API is `diagnosis.exhaustion(card) -> bool`,
`actual_model_work(card) -> bool`, and `pending_projection(card) -> dict | None`.
All three are pure, contain no reference to their own output generation, and
grant no authority. The pending projection has schema_version=1,
status="pending", and replacement_eligible=actual_model_work(card) except
that current infrastructure exhaustion is diagnosis-only and has replacement_eligible false (parent clarification 2026-10-30). B binds
it to its collected generation. A denied reservation alone is zero work;
an actually invoked zero-cash subscription process is work. Private diagnosis
results, findings, paths, and snapshots never enter that projection.

Use the existing same-owner ordinary restore after settlement for diagnosis.
Bind a diagnosis request to the acknowledged input generation and immutable
input digests, never the checkpoint being written. A resume launched with an
unknown exhausted total exits after settlement with no model invocation; B
must collect and acknowledge that known total before the next diagnosis resume.
An existing active extension retains its one authorized round and operation ID;
new writer admission creates its immutable history entry only after a lease and
money reservation exist. Five is a lifetime maximum. Progress is the furthest
contiguous pipeline point with complete valid evidence, compared at identical
ordered stage/version vectors, with every earlier pass retained. Missing or
changed-version evidence is pending reconstruction, never regression or a new
extension grant. Repairs preserve entry/outcome snapshots and their case bytes.

Migrate cumulative paid-cost and call-limit bindings once for stress, G8, G9,
G16, G10 and dependent G17; retain original scientific receipts as history.
Legacy cap/allowance fields remain decode-only evidence and cannot authorize
new-schema work. Legacy imports require explicit authenticated cumulative-usage
and lifetime-history migration; unknown invocation counts refuse import. A dry
run must show the known total and $33 per unresolved invocation before the
parent/founder authorizes the exact amounts. No automatic import grants money.

Production dispatch remains fail-closed. This increment does not populate
ENFORCED_ROUTE_BOUNDS, enable B's resume/replacement adapter, or claim B/E
checkpoint qualification. Real crash/capped-call closure exams remain required;
authored control-flow inputs on saved public bytes do not close those rows.


Increment-3 interface clarification (interfaces design review 15): use the exact
pure budget.usage_coverage API and per-invocation reconciled_decreases shapes in
interfaces §8. No duplicate coverage field is persisted. The runner owns the
schema-v1 diagnosis_state/exhaustion_id lifecycle specified there; completed
results clear pending_projection, and provider waits retain the same ID.
diagnosis_pending is the settlement-before-diagnosis checkpoint stop, authenticated
by that pending state. extension_incomplete requires a completed extension outcome,
not an infrastructure interruption. infrastructure_exhausted goes to diagnosis
without authorizing a replacement. These clarify the exhaustion-routing list
above; no model result grants a resume, extension or money. No code is enabled by
this documentation change.


Interface review 16 clarifications: B qualifies decreases only against the
immediately previous ACK's estimated invocation map, including null-total ACKs.
D emits the single row-transition receipt regardless of unrelated unknown totals;
released amounts and B's bounded nanodollar comparison follow interfaces §8.
The public extension history uses lifetime ordinal IDs 1..5 and hashes; null
outcome_sha256 means active. Entry case/evidence is immutable; outcome appends
once and a substantive late defect completes the extension as extension_incomplete.
A close_to_passing diagnosis continues in the same worker into extension admission;
factory_bug stops unscored as factory_bug_held; not_converging retires. The required real-ledger
replays are listed in interfaces §8; no code is enabled by these clarifications.

Parent ruling, 2026-10-30 (replacement derivation): B requires a present D
pending_projection with replacement_eligible exactly true. None forbids first
derivation even when exhaustion and actual_model_work remain true (including a
completed infrastructure diagnosis). D records pending state and checkpoints the
first exhaustion before diagnosis; B derives immediately from that collected
projection. Completed diagnosis clears it. Subsequent distinct exhaustion may
request diagnosis, but B's durable one-child-per-parent journal never admits a
second child. D's pure card-only API does not pretend to read that external latch.

Interface review 17: accept R1 and J1/J2. B uses epsilon=(2*len(previous
estimated map)+1) nanodollars, including zero-release settlements and
re-estimates. This grants no money or released commitment. Factory-bug resume
clears the old infrastructure_gate before work; current diagnosis_state
identifies a subsequent exhaustion. release_uninvoked refuses non-pending rows.

### Increment 3a review boundary

The first increment-3 implementation slice supplies the pure §8 diagnosis and
coverage APIs, one retained final receipt/decrease per estimated invocation, and
the parent-ruled cumulative-call telemetry branch. It changes no B enable flag,
route maxima, extension admission or legacy import authority. The full extension
runner/snapshots and stale-cap/import/scientific migration remain increment 3b;
this boundary is not a claim that increment 3 or any Murphy row is complete.

The coverage helper and public case_spending share one raw valuation. Retained
final receipts are atomically written beneath usage-receipts/final by canonical
hash before the ledger transaction records that hash, so later growing receipts
cannot erase the evidence. Unknown unrelated invocations do not suppress a row's
decrease record. The diagnosis APIs read only their input JSON; the pending
projection is the sole source of first replacement eligibility for B.

### Unwired legacy import implementation boundary

The additive §8 legacy-import proposal passed `legacy-import-design-2.md`.
Its first implementation supplies only pure dry-run/migration in `carry_over.py`
and a read-only validator sharing `restore_ledger` authentication. These imports
are accounting plus retirement, with unknown lifetime history; no resumable
legacy history is invented. B has not adopted storage/delivery/holder routing,
and `job_config.install` continues refusing legacy checkpoints. Exact numeric
founder authorization is an input that B must authenticate, never authority
created by D. Anonymous late-receipt attribution, resumable imports, extension/
diagnosis runner integration and remaining stale-cap migration are outstanding.
No Murphy row closes. Real canary6/c7d405 and resolved-waste cards prove the
accounting transformations; authored restore layouts exercise boundary refusals.

### Held-outcome producer review boundary

The next state slice adds the strict result validator, durable factory-bug finding
producer and immutable finding replay in `diagnosis.py`. Valid model operation
lists are narrowed to the empty code-eligible set; no waste is reclassified.
History initializes only at the first safe hold, including pre-rollout saved
cards; completion and the public stage/count follow durable private evidence.
The shared factory model-dispatch boundary refuses held cases before a lease.
Recovery carries the content-free marker/count as well as the completed state.

This slice does not yet invoke a diagnosis model or grant a later-batch resume.
The dispatcher will call replay before any model and the producer after a valid
result. Ordinary `bind()` still refuses cross-batch resumable import until B's
addendum. Extension execution and scientific/stale-cap migration remain separate.
Tests in `tests/factory/test_stream_d_held.py` use saved 5813be usage and verified
public practice bytes, with authored judgment, binding and interruption controls.
They prove write ordering, immutable replay, no model lease after a hold, and
unchanged spend; they do not close a Murphy row or qualify a live rollout.

### Extension state implementation boundary

`factory/extensions.py` implements the passed extension eligibility/progress
rules as worker-owned state helpers. It consumes code-produced snapshots and
an already admitted writer lease/reservation; it does not create a lease, grant
money or invoke a writer. The runner, snapshot producer, changed-gate baseline
evaluation and scientific-version migration remain unwired in this slice.

The private history stores schema_version, ordinal extension_id, immutable
writer_operation_id, authorizing exhaustion_id, cumulative round, entry, outcome (initially null) and
append-only comparisons. Each comparison retains the original entry/outcome
case digests with evidence at a common current version. Snapshot fields are
source_generation, case_sha256 (canonical digest of relative file digests),
ordered stages, frontier and evidence (relative work path to byte digest).
Stage rows contain stage, version, status, binding_sha256 and evidence_sha256;
pass/fail require bound retained evidence, while pending/unreached carry null
evidence and binding. The public projection is exactly the §8 history shape.

Entry/outcome case bytes and evidence are copied to
`work/extension-snapshots/<ordinal>/<entry|outcome>/{case,evidence}` before the
private history append; comparison evidence is retained under
`comparison-<canonical-pair-digest>/<entry|outcome>/`. Files and parent
directories are fsynced before publishing history. Repairs do not touch these
paths. Admission replays retain the same ordinal and writer operation; an
outcome is appended once. A pending execution cannot complete an extension.
No pending stage can authorize entry either. Each completed close_to_passing
diagnosis authorizes one extension only; its exhaustion_id is unique in private
history. Replaying that active extension retains its ID and binding. A further
extension requires a newly completed diagnosis. Its proposed snapshot must
match the selected compared outcome in case digest, ordered stage bindings,
frontier and evidence; source generation may advance through an ordinary
checkpoint. Earlier progress cannot authorize a newly regressed current case.

Retained rounds are consecutive and each is bound to its writer operation's
ledger reservation `call_name: builder-<round>`. A completed history's last
round must equal the restored builder_rounds counter. An active entry permits
that round or exactly one less, because admission precedes invocation; replay
does not increment the counter. Other counters refuse instead of resetting.

The private write commits before the in-memory public projection. On replay,
verify all retained snapshots and operation/round reservations first. Accept
either the exact public projection or its immediately preceding view: the
last active admission omitted, or the last completed outcome still null with
all other fields identical. Reconstruct only that projection. A comparison
append changes no public field. Unrelated mismatches still refuse; this is
recovery of a committed transition, not authority from public card fields.

`test_stream_d_extensions.py` uses the verified saved practice case and 5813be
ledger, with explicitly authored stage receipts and lease controls. It checks
the five-extension lifetime bound, cumulative writer rounds, no ID before an
actual reservation, repair survival, immutable snapshot bytes, exact-version
progress, regression/pending distinctions and retained baseline comparisons.
It does not qualify live gate receipts or a live extension run, and closes no
Murphy row. Money admission stays under the existing B runtime prerequisite.

### Queued diagnosis inputs (review-17 follow-up)

The dispatcher must never pass live `work` as the result validator's evidence
root. Before its first model call, retain immutable input bytes at
`work/diagnosis/<exhaustion_id>/inputs/` and a private `input.json` alongside it:
`{schema_version:1, case_id, exhaustion_id, generation, files}`. `files` is the
exact sorted map of input-relative POSIX file names to SHA-256 digests. The case
and exhaustion ID come from the current authenticated context/pending state;
on initial creation, generation comes from the existing worker restore-accounting
receipt's `generation` field and must equal B's verified non-null input
`source_generation`. It never names the generation containing this new snapshot.
No new field is added to the public state or nine-field RAM configuration.

Input selection belongs to code, not to model output. The input tree contains:

- `case/`: the current case tree, with symlinks refused;
- `ledger.json`: the bytes at `c.ledger` (the live cumulative ledger, normally
  `SEALED/<case>.continuation-budget.json`), after reconciliation and before
  reserving a diagnosis invocation. Do not use a stale work ledger copy.
- `card.json`: a canonical JSON copy of `c.checkpoint_card`, the authenticated
  archived card, whose case and pending exhaustion ID equal the current ones.
  It is not the newly built card. Its `sha256` may be absent or name an older
  generation: `RunArtifacts.seal` writes this card before creating the archive,
  so it cannot name its containing ciphertext. Never derive or validate the
  input generation from that field;
- `restore-accounting.json`: the unchanged receipt bytes from
  `c.ledger.parent / (c.case_id + '.restore-accounting.json')`, outside `work`.
  Require `type(version) is int` and `version == 1`, the matching `case`,
  `accounting_authenticated is True`, and a non-null SHA-256 `generation` matching
  the authenticated current job authority's `source_generation` on creation.
  Validate its `ledger_sha256` and `public_card_sha256` as SHA-256 values. Bind
  the archived card's `continuation_budget` using the existing canonical
  `carry_over.digest`: it must equal `retained_ledger_sha256` when that existing
  correction field is present, otherwise `ledger_sha256`. The live reconciled
  ledger may have grown after restore; it is separately frozen as `ledger.json`
  and is not required to hash to the pre-settlement receipt's ledger digest.
  Missing or null archived `continuation_budget` refuses input-invalid; no
  fallback to a mutable work ledger is inferred;
- `work/`: reuse the work-root evidence selected by `gate_state.inventory`
  (gate-details, judge_breadth, review-*), plus `bench-results` for restored
  bench-kind evidence. Current inventory bench-kind files go under that same
  `work/bench-results/` prefix. At creation, a current `bench/results/<rel>`
  file takes precedence over a restored `work/bench-results/<rel>` file with
  the same relative name. Here current means the live inventory copy, without
  an mtime filter; this agrees with the current gates' lookup order. The seal
  also overwrites restored copies, but only for files written since `c.t0`.
  Read selected paths safely on both sides; do not mutate either live copy.
  Restored-only paths remain available. Replay never reselects a current copy:
  the published manifest's bytes are immutable. Retain the
  remaining writer/stress and lifecycle inputs by name: attack-state.json,
  attacks, gate-continuation.json, late-defect.json,
  extension-history.json, extension-snapshots, transcripts, usage-receipts,
  infra-attempts.json, strong_calibrator, easy_calibrator, early_probe,
  independent-* directories, fixes, evidence, history, verdict.json,
  prototype.json, public-search.json, idea-realism.json, audit-baseline.json
  and delivery-provenance.json. These named roots are optional unless required
  below; they are not replaced by a recursive copy of work;
- `source/`: exactly the verified worker release manifest's `files` entries
  matching `factory/*.py`, `factory/prompts/*.md`, and the bin entries in
  `launch_manifest.WORKER_BENCH`. These are a subset of `worker_files`, stamped
  with the `worker_release.source_files` digest convention. Read the existing
  `batch-release.json` by the authenticated `batch_release_sha256`, then read
  `worker-release-manifest.json` by that release's recorded digest, using
  `job_config.read_file` as install already does. Each selected source file is
  required and its copied bytes must equal its manifest digest. Use the existing
  worker mapping: factory paths under the installed factory root, bin paths
  under BENCH. No independent source list and no unshipped run-exam,
  score-claims or land file is added. Do not run tool qualification again.

The minimum is a nonempty case tree, the valid pending authenticated card,
the restore-accounting receipt, the reconciled JSON ledger, and all selected
release source.

The receipt is code-owned provenance, not requester-supplied authority. It
proves this exact archive generation was extracted and its accounting
authenticated on this worker; unlike mutable current `source_generation`, its
bytes can be frozen with the original input for later replay.
`launch.sh` freezes the selected public card/archive, verifies the restored
ciphertext digest, extracts through the existing restore path, then passes the
public card and that digest as `--generation` to `restore_ledger.py` before
starting the runner. `restore_ledger.install` calls `authenticate` and
`_authenticated_source`, which check case identity, public-card generation and
public/archived/retained accounting equality (or the existing authenticated
founder correction), then atomically writes the ledger and
`sealed/<case>.restore-accounting.json`. B's independently verified RAM job
configuration supplies the matching current source binding; a restored card or
receipt cannot replace that configuration. D reads the existing receipt without
adding a field, altering its producer, re-running restore, or inventing a new
launch mode. Selected-file no-symlink/regular-file checks apply to this receipt.
Missing, malformed, wrong-case, unauthenticated, wrong-generation or
ledger-mismatched receipts stop `diagnosis_input_invalid` before publication.

On replay, validate the frozen receipt and card together against the original
manifest generation, including their case and ledger bindings. Never compare
that original generation to a later live restore receipt or current source
binding: a later ordinary restore legitimately replaces the live receipt while
carrying the immutable input snapshot. Existing authenticated job checks still
apply to the current owner. Missing or altered frozen receipt bytes refuse like
any other missing or changed input. No card SHA is synthesized or overwritten.

Gate-cache records are optional reuse hints, not diagnosis authority. At
creation, copy all selected current work/bench evidence first, then consider
`work/gate-cache/*.json`. Copy a cache record only when it has a nonempty valid
`evidence` list and every reference has a safe canonical relative path, kind
`work` or `bench`, a SHA-256 digest, and resolves with that digest in the already
copied evidence (bench-kind uses `work/bench-results`). Omit stale, missing-
evidence or malformed cache records without changing or deleting their live
bytes. This follows `gate_state.load`'s treatment of unusable cache hints; no
cached verdict is promoted or re-certified. Retained cache records are
historical pass receipts; a current gate outcome comes from the authenticated
card and current gate details, never from a retained cache's `info` alone.
A passing gate followed by a failed
rerun may leave a stale cache while overwriting its evidence, and must remain
diagnosable. Current failed gate details and other selected receipts are kept.
Unsafe selected paths, symlinks and nonregular files still refuse before reading;
only semantic cache invalidity is omitted. No record can resolve through another
cache file. Only files selected by this rule enter the manifest. On replay,
never omit or reselect anything: exact frozen inventory/digests and all retained
cache references remain mandatory. Damage after publication is input-invalid.
Required stop evidence follows its existing producer, not a universal
gate-detail filename:

- `late_defect_needs_ruling:<gate>` requires copied `work/late-defect.json`:
  its gate and the authenticated card's `late_defect.gate` equal the stop's
  gate, and `late_recovery.digest(record)` equals `late_defect.record_sha256`.
  G4/G6 need no gate-detail file; `stop_defect` already retains their detail
  in this bound receipt.
- `extension_incomplete` requires the completed last outcome in copied
  `work/extension-history.json` and its immutable snapshots. Verify with the
  extension history reader against the authenticated card's §8 projection;
  the last outcome must be non-null and its canonical digest must equal that
  projection's `outcome_sha256`. This reuses the snapshot validation instead of
  fabricating a gate-detail receipt.
- `infrastructure_exhausted` requires the authenticated input card's
  `infrastructure_gate.exhausted: true` marker with its code-recorded gate.
  A crash may have produced no detail file, which does not prevent diagnosis.
- Budget/stress-round exhaustion requires its valid pending state and retained
  ledger; no universal gate-detail file is required.

Any existing gate-detail files remain additional evidence. Missing or mismatched
required stop receipts are invalid inputs, not evidence of a writer failure.
Missing required inputs use `diagnosis_input_invalid`, defined below.

Statements are excluded: they belong to the separately encrypted statement
channel, not this diagnosis of factory execution. The selected calibration and
gate receipts describe the relevant execution without importing that channel.
Unlisted work artifacts are excluded because no diagnosis input contract needs
them; the explicit list above includes writer handoff, G11 audit and delivery
provenance. This is evidence selection, not a new gate pass or permission grant.

Never copy the whole worker home, logs/stdio, other case roots, credential
stores, environment files, restore keys or job configuration into these inputs.
Reject symlinks and non-regular selected files. Snapshot creation uses the same
joined-worker condition as `durable_checkpoint.checkpoint_progress(...,
quiescent=True)`, after reconciliation and with no active model calls. It does
not add a new checkpoint state or require an extra upload. Stage into
`work/diagnosis/<exhaustion_id>/.inputs-staging/`, hash the copies, fsync
files/directories, atomically publish inputs on that same filesystem, then
durably write input.json. No model call can precede that manifest. If input.json
is absent, first inspect this exhaustion's retained state, before cleanup or
finding validation. Any `finding.json`, `raw-result-*.json`, completed
diagnosis_state or retained diagnosis invocation reservation makes this
`diagnosis_input_invalid`; preserve all remaining inputs and findings. The
dispatcher uses `diagnosis-<exhaustion_id>` as the initial reservation call_name
and `diagnosis-<exhaustion_id>-repair-<ordinal>` for schema repair, so this check
uses those exact names in the ledger rather than model text. These names are
an obligation on future dispatcher wiring, which is not enabled here.
The proposed worker-dispatch addendum also binds `attempts.json`, `decision.json`,
`raw-bytes-*`, `audit-bytes-*` and `audit-*.json` to the input manifest. Before those producers are wired, extend
this orphan check to those paths as well. The repair suffix is a global logical
call ordinal; its attempt journal distinguishes schema repair from a judgment on
the next approved route. Exact raw bytes have a separate byte-hash filename so
the existing canonical-JSON factory-bug producer cannot overwrite them.
Only an unbound pending attempt with none of that evidence may remove orphan
inputs and staging directories and re-stage current bytes. Refuse symlink parents
rather than following them during cleanup. Once input.json exists, never rewrite the snapshot from
new work. Replays verify its exact file inventory and digests, case and
exhaustion ID. A later same-owner wait/checkpoint generation does not rebind the
original generation: the authenticated archive carries that immutable input.

The model's checkpoint_sha256 equals the original manifest generation and its
evidence paths are relative to inputs. That generation identifies the restored
ancestor; it is not a claim that post-settlement ledger bytes were in that
ancestor. The manifest, snapshot and finding are retained together under the
same exhaustion ID inside subsequent authenticated encrypted archives. The
manifest hashes establish the exact evidence bytes. Both result validation and finding replay use
that root. Live ledger growth after diagnosis, or a crash after finding.json
but before public completion, therefore cannot invalidate the retained finding.
Changed immutable evidence still refuses. Dispatcher wiring must load and
verify this input manifest before reusing a finding or starting a model. The
diagnosis role's only readable case/evidence root is this inputs directory,
under the existing launcher isolation and `case_permissions`; a copy allowlist
alone is not isolation. This amendment enables no dispatcher.

Every input-protocol refusal sets `status: stopped` and
`terminal_stop: diagnosis_input_invalid`, preserving the existing
`diagnosis_state` as evidence rather than completing or replacing it. This
includes missing/null/mismatched initial source generation, mismatched case or
exhaustion ID, unsafe paths, missing required inputs, release mismatches and any
missing/changed/extra frozen file or invalid manifest. `exhaustion` returns false
and `pending_projection` returns None for this stop even with an infrastructure
marker; `record_exhaustion` cannot mint a new ID. The ordinary final checkpoint
persists the stopped card. It is intentionally not a known status stop, so
status shows `check case`; B queues no automatic diagnosis retry. Existing held
model guards remain in force. Recovery is a separately reviewed operator
correction through the ordinary bind/import path, never an automatic reset.

`factory_bug_history_invalid` is a terminal attention stop: exhaustion returns
false and pending_projection returns None, including when an infrastructure
marker remains or a previously completed hold's history is damaged. It cannot
create a new diagnosis ID. A damaged completed hold does replace its stop with
`factory_bug_history_invalid`, removes the derived count and preserves its
finding and public factory_bug marker; `check case` takes priority over the
ordinary held action. No code clears this stop automatically; repair needs the
same reviewed operator correction as invalid inputs. The shared held-dispatch guard remains in force;
B's later cross-batch resume addendum must explicitly update that guard with
its authenticated admission path, not bypass it through another model caller.

Targets are `factory/diagnosis.py` and the held/input tests. The follow-up tests
use the saved 5813be ledger and verified practice bytes:
freeze input, write a finding, interrupt public completion, append to the live
ledger, then replay the same finding without a model. Corrupting frozen input
must stop as diagnosis_input_invalid with exhaustion false and a None projection,
including with an infrastructure marker. Remove the manifest after a finding
but before public completion, append live usage and attempt replay: preserve
input bytes, finding and exhaustion ID, do no model work and stop input-invalid.
Repeat after completed hold, and cover raw-result/reservation-only evidence.
Separately test genuine pre-manifest orphan re-staging after live settlement,
initial generation mismatch, archived cards with absent or older sha256 accepted
through a real `restore_ledger.install` receipt, missing/false/mismatched receipt
refusals, a changed live receipt after later restore leaving replay unchanged,
frozen receipt corruption refusal, and these real `restore_ledger.install`
receipt branches: (1) an authenticated founder correction with public ledger
unequal to archived ledger succeeds through `retained_ledger_sha256`; deleting
that correction field or altering its digest refuses, and (2) a carried-forward
ruling with `ruling_carried_forward: true` and no `retained_ledger_sha256` succeeds
through `ledger_sha256`. Authored ruling/control envelopes are explicitly marked
and use the saved real ledger and public-practice bytes. Cover missing embedded
accounting and strict boolean/version types too. G4/G6 late-defect receipts without gate details,
their missing/wrong-gate/wrong-digest refusals, completed extension outcome
bindings, the infrastructure crash marker, gate-cache reference resolution, release digest mismatch,
and unchanged replay across a later authenticated source generation. Add a
pass-then-fail-then-exhaust replay: save a genuine gate-cache record over retained
practice evidence, overwrite its detail as a failed rerun does, freeze successfully
with the stale cache omitted, and retain the failed detail and unchanged live
cache. Also cover missing and malformed cache references, absolute/`..` references,
and references through another cache file (all omitted, never followed), plus a
symlinked cache file (refused before semantic filtering). Keep valid records and
refuse changed retained cache bytes on replay. Replay differing restored/current
fixed-name bench files using the `plain` and `reference` `checkpoint.json`
receipts in `tests/factory/fixtures/invalid-runs-real.json.gz`: freeze the current bytes,
retain restored-only files, omit caches naming superseded bytes, preserve both
live copies, and keep replay unchanged after the live current bytes change again.
The fixture proves precedence with saved artifacts and authored layout; it does
not claim two live bench preparations were run. The overwrite need is established
by `RunArtifacts.seal` and the fixed-name writes in `bin/bench.py`. Assert
None projections for invalid history both before and after a completed hold.
These are offline control tests and close no Murphy row.

Storage cost is one immutable input copy per exhausted diagnosis, retained in
later encrypted archives. In the offline 5813be harness, the verified practice
tree is 94,188 bytes, the saved ledger serialized with json.dumps is 781,508
bytes, and the saved card is 784,266 bytes: 1,659,962 bytes before release source
and retained work evidence. This is a measured fixture subtotal, not a claim
about the full private 5813be archive (which was not decrypted). Input files'
actual sizes can be summed at implementation verification. There is no new
quota or garbage collection policy in this amendment.

### Queued input implementation boundary

The original `ebf3b1a` slice predates the generation/cache/bench amendments above
and is unqualified until their implementation passes a new diff review.

`diagnosis.queued_inputs(c, bench, quiescent=True)` creates or verifies the
private input manifest described above and returns it. The consumer uses that
manifest's original generation and the fixed inputs directory for held-result
validation and replay. `diagnosis_input_invalid` is excluded by the pure
exhaustion projection and cannot mint a new ID. This slice implements input
selection, source/evidence checks, durable publication, orphan recovery and
terminal refusals. It does not call the helper from the runner, start a model,
implement the diagnosis role's process isolation, or enable money admission.
Dispatcher wiring must enforce the passed read-only isolation and call this
helper before any finding replay, reservation or model invocation.

`tests/factory/test_stream_d_inputs.py` uses the verified practice case and
saved 5813be ledger. It authors release and lifecycle envelopes, copies actual
shipped source bytes, and explicitly distinguishes those controls from live
qualification. Together with the held/projection/extension tests it covers
frozen evidence, missing manifests after binding, pre-manifest interruptions,
required receipt paths, digest failures, terminal projections and unchanged
replay across later generations. No Murphy row closes.

The subsequent diagnosis-only worker increment is specified in
`stream-d-worker-dispatch.md` (design review 5). It adds the runner consumer,
retained-answer replay and disposable role helper. Its code is subject to a
separate diff review and full suite. The shared B activation constant remains
false; extension comparison/execution and live qualification remain outstanding.


## Remaining increments after 4f291fb (2026-10-30)

**Can a batch launch with diagnosis off?** Yes, as far as D is concerned. A/B/E
launch, money, isolation and collection checks must still pass. This section
does not claim they have. `DIAGNOSIS_ENABLED` is false, so at exhaustion B
returns `diagnosis_unavailable` with an empty queue. Stream C already keeps
broken runs unscored, so a held case is not a wrong result. That batch loses:

- automatic diagnosis of exhausted cases;
- the replacement launch on that path;
- near-pass extensions;
- factory-bug resumes.

An exhausted case stops as `diagnosis_pending`. That is a hold on one case,
not a halt of the batch, and it needs the founder. Until items 2–5 land,
ordinary cases can also stop on the open D rows 8, 10, 11, 12, 13, 15, 21 and
39. So the batch is safe, but it is not hands-free. Do not turn diagnosis on just to
avoid these holds.

**Order.** Items that help an ordinary diagnosis-off batch come first.
Extension-only work comes after them. Item 2 goes before item 3 because new
factory jobs already skip the $5 cap on the main call path
(`model_runtime.py:639`, `budget.py:736`). Item 3 removes what is left. An item
closes a row only when its test
on real saved artifacts proves the whole row. Otherwise the row waits for
item 8.

1. **Completed-writer validation parity** (small; implemented in c62f5f2;
   full suite and diff review 1 passed, not yet merged; the diff reviewer was
   Claude because the DeepSeek reviewer returned no output). A writer
   killed at its completion checkpoint gets the same `unchanged_repair`
   decision as an uninterrupted one. Part of row 10. Closes no row.
2. **Writer continuation and durable intent** (medium; implemented in
   4f9f931; design review 1 and diff review 1 passed (DeepSeek); full suite
   passed; not yet merged). An interrupted writer
   resumes in the same round and operation, keeps its findings, and makes no
   second author call after a completed one. Pending receipts use strict
   intent, like completed ones. Closes row 10. Persisting intent across
   extension admission and attack-receipt publication supports row 9.
3. **Money cleanup and settlement** (medium to large; implemented in
   477d84a; design reviews 1–8 (review 8's blockers rejected, upheld by a
   second goldfish); full suite passed at 477d84a, 155 scripts, 0 failed;
   diff review 1 passed (Codex); not yet merged). Remove the leftover
   paid-cap checks for new factory jobs. That means every remaining entry in
   the paid-cap inventory above: `g11_review.py`, `ttl_continuation.py`,
   `key_holder.py` and `gate_state.py`, plus the `coordinator.py`,
   `restart.py` and `carry_over.py` entries and the `--max-cost` default in
   `run.py`. Settle
   missing usage from retained receipts, or charge a bounded reservation,
   instead of marking the whole case budget unknown. Closes rows 8 and 21.
4. **Ordinary retry bounds** (large). Count failed work separately from
   waiting and transport retries. Refresh G2 evidence before it expires, and
   retry retrieval failures. Save stress findings as they come, and continue
   only the unfinished categories. Repair malformed output from the retained
   answer before trying an approved equivalent model. Closes rows 11, 12, 13
   and 15.
5. **Scientific receipts and per-gate versions** (large). A plumbing change
   keeps passes. A bench-logic change invalidates only its own gate. G10
   records capped or no-submission outcomes apart from demonstrated wrong
   fixes. Closes row 39. Extensions need this item.
6. **Comparison isolation** (medium). Compare an extension's before and after
   at one common gate version on immutable copies, without touching the live
   candidate. An invalid execution stays pending. Supports row 9 and closes
   none alone.
7. **Continuation routing** (large). Join one writer round, its stress round
   and its gate re-run into one unit. Route the diagnosis outcomes (factory
   bug, extension, retire) through B's checkpoint and money adapters.
   A case refused as `unchanged_repair` keeps a completed writer receipt and
   refuses again on every re-entry; an extension must replace or advance that
   receipt through B's checkpoint adapter, not re-enter at receipt load.
   Supports row 9.
8. **Live qualification, then diagnosis on** (large, cross-stream). Run the
   integrated path on retained real run artifacts and authorized live A/B/E
   runs, covering crash points, provider waits, limits, collection, and every
   diagnosis outcome. Closes row 9, plus any row that items 2–5 could not
   prove on saved artifacts. Set `DIAGNOSIS_ENABLED` only after this item
   passes review.

### First increment: completed writer validation parity

Problem: the ordinary writer path checks `repair_requested` and
`before_repair_sha256` after completion and refuses `unchanged_repair`. The
restored `phase: completed` path skips that check and runs G1/early checks.
A kill in the automatic completion checkpoint therefore changes the decision
for exactly the same completed bytes. A completed repair that changed nothing
can proceed to stress only because it was interrupted.

Change: in `factory/run.py`, apply the same unchanged-repair check to a completed
writer receipt before resumed G1/early validation. Reuse the saved intent and
before hash; do not invoke a writer, renumber the round, create a reservation or
reinterpret a provider wait. The existing output-hash verification still runs
first. Refuse a completed writer receipt with a missing/non-boolean repair intent
or missing/non-SHA256 before hash as `invalid_recovery_receipt`; those fields are
already written by the V2 completion producer. The strict check runs only
under `modern_writer_unit` (schema version 2), so legacy V1 behavior stays intact.
No new schema, launcher, toggle or authorization is needed. Delete the semantic
difference between uninterrupted and restored completion; add no subsystem.

Tests: extend `tests/factory/test_stream_d_runtime.py` using its hash-verified
saved practice case and captured 5813be ledger. Author only lifecycle/model
controls. Run an unchanged requested repair both uninterrupted and killed at
its completion checkpoint: both must stop `unchanged_repair`, retain round 1,
and call the writer exactly once with no stress call. Resume a changed repair
and confirm stress proceeds without another writer. Resume a no-repair first
writer whose bytes are unchanged and confirm it can validate. Missing/malformed
intent fields must refuse before any model or resumed validation call. Existing
changed-output checks remain. These controls prove crash parity, not a live
interrupted writer exam, so row 10 remains open. Run the full required suite and
a fresh diff review from another model family. There is no new storage or model cost; the restored
no-op repair now avoids a stress invocation. The risk is rejecting old malformed
V2 receipts; fail closed instead of guessing whether repair was required.


First-increment design review corrections (B1, M1, N1, N2): put both the
completed-intent validation and unchanged-repair check inside
`if modern_writer_unit and not awaiting_stress`, immediately after its existing
completed output-hash check, guarded by `resume_writer_validation`. This is
before loading receipt findings and before the shared `if report and problems`
freshness/early-review path, which can itself call models or return a pass.
Do not put the check in the later resumed-G1 branch. Strict intent validation
applies only to completed writer receipts; pending receipts are unchanged in
this increment. Round-one parity controls seed both uninterrupted and killed
runs with the same `prev = {'failed_gate': 'G1', 'failed_detail': ...}`; the
failed-detail envelope is authored over the verified saved practice files.
Also produce a completed round-two repair after a retained authored stress report
with blocking findings. After the completion kill, patch `loop_freshness`,
`confirm_hits` and `early_review` to fail if called, and verify unchanged-repair
and malformed-intent refusals precede these hooks. Keep output-hash precedence
as a separate changed-output control.

### Second increment: writer continuation and durable intent

Problem. A modern (schema 2) writer receipt can be interrupted at three
points. Two of them still diverge from the uninterrupted path.

1. **Mid-call** (CLI started, no `done` usage receipt). Resume already reuses
   round `n` and `operation_id`. But it reads intent with `.get` defaults
   (`run.py:1313–1314`). A receipt missing `before_repair_sha256` falls back
   to the hash of the half-edited bytes, so the unchanged-repair decision is
   computed against the wrong baseline. Resume also sends the retained
   findings back through the shared `if report and problems:` block
   (`loop_freshness`, then `early_review`). That block already ran before the
   writer was admitted. Running it again can make model calls, change the
   findings the writer receives, or, if freshness clears them, run
   `early_review` and return `stress_review: completed` on half-written bytes
   with no stress round. The same re-run happens for a `validated` receipt with
   `validation_problems`: its G1 problems are replaced by the old stress
   findings, or cleared and passed, where the uninterrupted loop would have
   sent report and G1 problems to writer `n+1`.
2. **Call returned, completion receipt not yet written.** `ModelRuntime._call`
   writes `usage-receipts/<lease>.json` with `outcome: done`, settles, finishes
   the lease and returns; `_opencode` then runs `on_complete`. A kill in that
   window leaves `phase: pending`, and resume pays for a second author call
   for work that already finished. This is the rehearsal-salvage case
   (`builder-4` recorded, no `attacker-4`), which needed a bundle-only adapter.
3. **Completed receipt.** Handled by increment 1.

Change, all in `factory/run.py`, no new schema or file:

- **Strict intent at load.** One helper, `writer_intent_valid(receipt)`:
  `repair_requested` is a bool, `before_repair_sha256` is 64 lowercase hex,
  and both `findings_report` and `input_problems` keys are present. All four
  have been written into every V2 writer receipt before admission since
  753b33e. In the `modern_writer_unit and not awaiting_stress` block, after
  the existing completed output-hash check (precedence unchanged), a
  `pending` or `completed` writer receipt that fails it is refused as
  `invalid_recovery_receipt` before any model, freshness or validation call.
  The pending-merge in the writer loop then reads the saved values directly
  (no `.get` defaults). `validated` receipts are unchanged.
- **Durable intent at admission.** `pending_call` refuses a `role='writer'`
  receipt that fails `writer_intent_valid` with
  `BudgetError('writer_intent_missing')` before `await_lease`. Every writer
  admission, ordinary or extension, therefore writes intent into the pending
  receipt that `admitted()` publishes as `attack-state.json` (the file B's
  checkpoint carries). A future extension caller cannot pay for a call whose
  resume would be refused. Supports row 9; closes none of it.
- **Retained inputs are final.** Skip the shared `if report and problems:`
  block when `modern_writer_unit`. A modern writer receipt carries the exact
  `findings_report`/`input_problems` (or `validation_problems`) the
  uninterrupted loop would pass to the next writer call; they were already
  freshness-processed after the stress round that produced them. Legacy and
  stress-unit resume keep the block.
- **Completion from the retained usage receipt.** After intent validation, a
  `pending` writer receipt is promoted to `completed` when
  `usage-receipts/<lease_id>.json` exists with that `lease_id`,
  `invocation == 'builder-<round>'` and `outcome == 'done'`, and the ledger
  reservation for that lease has the receipt's `operation_id` and
  `invocation_id`. The lease ID must be 32 lowercase hex (path safety).
  Promotion uses the same producer as `on_complete`: the `writer_completed`
  closure becomes a module function `complete_writer(c, receipt, path)` called
  from both places. The receipt then follows the increment-1 completed path:
  unchanged-repair check, then resumed G1/early validation, then stress. No
  checkpoint is added at promotion. The restored generation already holds the
  final bytes and the `done` receipt; the CLI writes the case before it exits
  and the usage receipt is written after, so any generation with the receipt
  has the bytes. A kill after promotion repeats it from the same evidence.
  The `done` receipt carries no new trust: it lives in the same work directory
  as `attack-state.json`. A receipt whose lease is null (`resumed_from_wait`),
  missing, `interrupted` or bound to another operation is not promoted; the
  call runs again under the same `operation_id` and round, which is the only
  honest option when its output may be partial.

Money and rounds. A mid-call resume pays for one new call under the same
operation and round; the interrupted reservation is settled or estimated by
the existing `reconcile_reservations` at resume. It does not add a writer
round, rewrite `builder_rounds` beyond `n`, or touch any allowance. The writer
continuation still checks the ordinary threshold at its next lease
(Diff-7 decision above). A promoted completion pays nothing more.

Nits folded in from completion diff review 1:

- **N1.** The findings test drops `g1` from its fail-if-called list. `prev`
  carries `failed_gate`, which short-circuits the pre-anchor G1 probe at
  `run.py:1081–1082`, so the guard proved nothing about the refusal. A comment
  says the probe predates both increments and is out of scope.
- **N2.** `completed_writer_control` resets `provider_resume_done` and
  `model_resume_state['done']` before the resumed run, as the neighbouring
  precedent does, so the resume settles through `resume_provider_wait` and
  `reconcile_reservations` like a fresh process.

Tests, in `tests/factory/test_stream_d_runtime.py` on the hash-verified saved
practice case and the captured 5813be ledger. Only model outputs and kills
are authored.

- `completed_writer_control` gains `window='checkpoint'|'returned'`.
  `returned` kills right after `ModelRuntime.call` returns, before
  `on_complete`. The three existing completion tests (unchanged requested
  repair refuses with no new work, changed repair goes to stress without a
  second writer, unchanged first writer without a repair request validates)
  run in both windows.
- Mid-call kill in round two after an authored stress report with blocking
  findings. On resume: exactly one more `builder-2` call, with the same
  `operation_id`, round 2, `builder_rounds == 2` and byte-identical prompt
  context (same `attack_report` and `precheck_problems`). `loop_freshness` is
  not called with `round-1.json` and `early_review` is not called before
  `attacker-2`. The case then completes stress.
- Strict pending intent: from that killed receipt, missing or malformed
  `repair_requested`/`before_repair_sha256` and missing `findings_report`/
  `input_problems` each refuse `invalid_recovery_receipt` with no model call,
  receipt and ledger bytes unchanged after the resume settlement.
- Validated-with-problems parity: kill after a round-one `validated` receipt
  with G1 problems and a retained findings report; resume calls writer 2 with
  that report and the G1 problems, with no freshness or early review first.
- `pending_call` refuses a writer receipt without intent before any lease or
  reservation. The shared `receipt()` helper gains valid intent fields.

Rows. These tests exercise every row-10 boundary (mid-call, returned,
completed, validated) on real saved case and ledger bytes through the real
runtime, router and ledger code, the same standard used to close rows 22, 23
and 36. If diff review accepts that, row 10 closes with these test names.
Otherwise it waits for item 8. Row 9 stays open. Full required suite and a
fresh goldfish diff review follow.

Risk. Old V2 receipts missing intent now refuse instead of guessing; none are
produced since 753b33e. A validated-with-problems resume no longer re-runs
freshness on stale findings. That is a behaviour change, and it matches the
uninterrupted loop.

Second-increment design review 1 corrections (PASS; N1–N5). If row 10 closes,
the same commit scopes the runtime test module docstring to the row-10 tests and
updates the register. `complete_writer` keeps the `builder_rounds = round`
write, and the `returned`-window tests assert it. Promotion proves authoring
finished, not that usage is settled: an estimated or unpriced reservation still
reconciles through the existing path, and `final_usage_known` is deliberately
not required, since requiring it would buy a second author call to fix an
accounting gap. No production extension caller exists yet (item 7);
`extensions.admit` records the extension entry, while the caller of
`pending_call` builds the writer receipt, so the pre-lease check is what makes
intent mandatory for that future caller. The skipped `if report and problems:`
block's founder-feedback branch is already inert under `modern`; skipping it is
also a simplification.

### Third increment: money cleanup and settlement

Problem. New factory jobs are the batch path only: `batch.bind` marks the
job `_batch_job`, strips `--max-cost` from its argv (`batch.py:169–176`), and
`run.py` runs it with `--batch-release-sha256`, so `model_runtime.factory_job`
is true. `batch_money` refuses a manifest job carrying `max_cost`. Two gaps
are left on that path.

1. **Row 8: the $5 default still binds factory evidence.** The call path
   already passes `max_cost=None` (`model_runtime.py:639`, `budget.py:736`),
   so the cap is not enforced. But `run.py`'s `--max-cost` default of 5.0
   stays in `c.args`. It is hashed into the stress binding
   (`gate_state.judge_dependencies` settings, via `run.attack_binding`), the
   G8/G9/G16 fingerprints (`gate_state.inputs`), the calibration identity
   (`run.calibration_identity` limits) and `recovery_config`. So factory
   evidence says it ran under a $5 cap that did not apply, and it cannot be
   told apart from legacy evidence that really ran under the cap. That is the
   binding migration the "Remove the paid cap everywhere" section requires.
2. **Row 21: unknown usage still makes the case total unknown.**
   `budget.complete_invocation` (`budget.py:357`) leaves a call whose receipt
   lacks final usage as a `pending` reservation plus an `unpriced_invocations`
   marker. Until the next `reconcile_reservations`, `case_spending` returns
   `total_spent_usd: None`. Two admissions read that first:
   - the router's retry inside the same `ModelRuntime._call`: the next
     lease's `reserve_invocation` refuses with `money_wait`, so a provider
     blip with partial usage blocks the retry on the next account;
   - writer admission in `run.pending_call` (`run.py:385–387`):
     `spent_usd is None` raises `budget_exhausted`, an ordinary terminal stop
     that sends the case to diagnosis because of an accounting gap.

Change.

- `budget._run_budgeted`: for a factory call (bound to a reservation), do not
  append an `unpriced_invocations` marker when a subscription session ends
  without its usage event. The pending reservation already holds that call's
  remaining maximum in `outstanding_reservations`, and every admission and
  `check_limits` counts it. The marker only turned that bounded gap into
  "total unknown". Non-factory calls keep the marker. This removes the
  window in which a sibling concurrent call's `check_limits`
  (`budget.py:845`) reads an unknown total and stops with `money_wait`.
  A failed stop needs no marker either. `model_call_gate.enforce` closes the
  call's gate on exit, and a closed `Allowance` refuses every further request,
  so a process that outlived the stop cannot spend past the gate's bound.
- `diagnosis.actual_model_work`: markers were also process-start evidence
  for replacement eligibility. A subscription call that dies before its usage
  event leaves no event. With no marker, it would look like zero work. The
  card's `route_receipts` already record each lease's outcome. The runtime
  resets an unstarted call to `denied` (`model_runtime.py:413–414`), so
  `done` or `interrupted` means a process started. Count those rows as work.
  `run.inherit_recovery_history` carries `route_receipts` across a resume,
  as it already does for `diagnosis_state`. `ModelRuntime._call` records the
  outcome before `complete_invocation`, so an accounting error cannot leave a
  started call reading `admitted`.
  This also closes a gap that predates this change: `finalize_accounting`
  reconciles bound markers away before `record_exhaustion` reads them. Saved
  cards carry no `route_receipts`, so their projections are unchanged.
- `budget._settle_leaf`: a receipt without final usage is charged at the
  smaller of the reservation maximum and the closed gate's bound in the
  receipt (`cap_used.settled_usd + held_usd`). The gate holds each request's
  worst case until its usage validates. That bound applies only when the gate
  forwarded at least one request. Otherwise the snapshot is the unstarted
  default, and the maximum stays. With the real $50 Claude maximum, one blip
  without usage now costs one request's hold, not the whole ordinary budget.
  Receipts with no gate snapshot (synthetic reconciliation leaves) keep the
  maximum. Once a reservation is estimated, its charge is a ceiling, and
  evidence without final usage never moves it, up or down. Only booked usage
  above the charge raises it, with a zero gap. In D, an estimated row gains
  events only through `_settle_leaf`, with one exception. The streaming
  accountant books only while its process runs, inside `run_budgeted`, which
  refuses a row that is not pending. `complete_invocation` estimates the row
  after that returns. `reconcile_reservations` at the start of `_call`
  excludes active call names and the call's own lease, and
  `resume_provider_wait` refuses while a call is active. The exception: an
  exam-owner child call still running on its HTTP thread when
  `finalize_accounting` reconciles can book cancelled partial usage onto the
  row that reconcile estimated. That call always ends interrupted with a
  non-final receipt, written once, so its charge can only grow and it never
  writes a release record. Only a final receipt can lower the charge,
  through `reconciled_decreases` (the provenance B's collection requires).
  B's collection check is unchanged by this increment. Its known limits
  (a settled row that grows after its decrease record, and a ledger written
  outside D's producers) predate it and are B's; see design review 8. The row's current charge counts every event already bound to
  it: its `event_ids` plus ledger events tagged with its lease and
  invocation. So a late booking followed by a stale replay keeps the total,
  and the decrease record uses that same charge. A forged first snapshot is not defended against. The receipt
  shares the work directory's trust with the ledger, as before.
- `budget.complete_invocation`: a receipt without final usage settles through
  the existing `_settle_leaf` as `estimated`, charging that bound. That also removes the marker bound to that invocation.
  This is exactly what `reconcile_reservations` already does at the next
  call or resume, done at the point the call ends. A later final receipt
  replaces the estimate once, through the same settler and its
  `reconciled_decreases` record. `settle()` for a provider wait re-reads the
  same leaf and records its wait provenance as before. Unbound legacy markers
  (no reservation) are unchanged and still go through the $33 import.
- `batch_holder._extends` (B-owned, three lines): an estimated reservation
  that becomes settled needs a `reconciled_decreases` record only when its
  settled charge is lower. The producer writes that record only for a
  positive release, so an equal or higher final charge used to leave a
  collection incident that no later generation could clear. Both charges
  are bound events plus the open estimate.
- `run.py` `main`: in the existing `if a.batch_release_sha256:` block, after
  the release digest check, set `a.max_cost = None`. This is before the card
  is built. An explicit `--max-cost` on a
  factory job is historical and ignored (`batch.bind` already strips it).
  The stress binding, the G8/G9/G16 fingerprints and the calibration
  identity then record `max_cost: None`. `recovery_config` records None
  until the first `update_case_budget`, which already drops the key for
  factory jobs (`model_runtime.py:265`). `coordinator.configuration_args`
  already skips `max_cost` once `ordinary_limit_usd` is present. That value is the new
  accounting-policy version. The `max_cost` key stays in each of them, so
  non-factory fingerprints are byte-identical. Merging this is the one-time
  intentional migration: factory evidence already fingerprinted with 5 stops
  matching and reruns once, inside the job commitment. Pass criteria and
  time/call limits are unchanged.

Deliberately not changed. Each site below keeps its numeric cap because no
new factory job reaches it. These paths have no job authority, so deleting
the cap would leave them with no money bound at all. They retire with their
paths (`docs/factory-single-path.md`), not here.

- `g11_review.py`: `batch.bind` refuses `--audit-g11` and
  `--restore-review`, the only launch of `--continue-g11-review`
  (`batch.py:143–151`, `launch.sh:44`). The G11 audit is a
  non-factory audit job, like `bin/run-exam`.
- `ttl_continuation.py`: a batch policy has only `mode: batch` jobs
  (`key_holder.py:128`), and `ttl_continuation.policy_check` requires
  `mode: case`. B's launcher replaces TTL continuation.
- `restart.py`, `coordinator.py`: `launch.sh` `factory_auto_resume` returns
  at once for a batch release (`launch.sh:494`). The coordinator's
  `max_cost` check is already skipped once `ordinary_limit_usd` is present.
- `key_holder.py`: both checks are already skipped for `_batch_job`
  (`:208`, `:355`).
- `carry_over.py` `OPERATIONS`/`INFRASTRUCTURE_LIMIT`: only `project`,
  `admission` and `load` read them, and only `tools/carry-over-corpus.py`
  calls those (a report). No launch, resume or import admission uses them.
  `legacy_import_dry_run` does not refuse on an allowance.
- `gate_state.py`: no code change. Its values follow `c.args`.
- `bin/run-exam`: keeps the $5 owner cap, as the inventory says.

So the plan's "remove" for these entries becomes "prove unreachable from a
factory job". The search exam below holds that line.

Deletes: the `pending` + marker branch in `complete_invocation`, the
factory-call marker in `run_budgeted`, and the factory job's $5 binding
input. Adds one line in `run.py` and one forbidden flag in `batch.py`.

`factory/README.md`: the `--max-cost` paragraph says the flag is the
non-factory and exam-owner cap. Batch jobs use the job money channel's
cumulative commitment.

Tests, in `tests/factory/test_stream_d_runtime.py` on the hash-verified
practice case and the captured 5813be ledger (priced cost already above $5).
Only model outputs and the gate's unknown-request count are authored.

- **Unknown usage settles at the gate bound, and the next admission
  proceeds** (`test_unknown_usage_settles_at_gate_bound_and_next_admission_proceeds`).
  Two subtests through the real `ModelRuntime._invoke`, the real
  `run_budgeted` (so `on_started` and the reset to `denied` run), the real
  router and ledger, and the real `Allowance` arithmetic. The CLI byte
  streams and the one request without usage are authored. Each estimated
  route keeps its real maximum (the reviewer's OpenRouter gate maximum, and
  Claude's $50). The route receipt shows a started outcome and survives
  `inherit_recovery_history`. A later final receipt replaces the estimate
  once. A replayed non-final receipt with a lower snapshot leaves the ledger
  byte-identical. (a) A gated reviewer call books $0.01 and leaves one request
  without usage. It is estimated at the gate hold, and the next writer
  `pending_call`, at the real $50 Claude maximum, is admitted and completes.
  Admitting a writer at $50 after any spend needs an ordinary limit above
  spend + $50. The test sets 100 as authored configuration. Under the
  default $50 ordinary limit, a Claude writer round after any spend is
  refused whether usage is known or not. That is the existing rollout
  prerequisite (E/A route-maximum report against the ordinary limit), not
  part of row 21. (b) A Claude writer blip without usage is
  estimated at one request's hold. The router retries on the second Claude
  account inside the same call. On the committed code, (a) stops with
  `budget_exhausted` and (b) with `money_wait`.
- **Late booking and wait replay** (`test_batch_accounting.py::
  test_late_booking_and_wait_replay_never_lower_until_final`). A defensive
  test: D produces a late booking on an estimated row only in the
  exam-owner case above, and never follows it with a final receipt. On the saved
  ledger through provider-wait `settle()`: estimate, a late booking tagged to
  the row, a stale non-final replay, then a final receipt that lowers, equals
  or raises the charge. Every step passes `collection_facts` against the
  prior facts, and only the lowering receipt writes a decrease record.
- **Equal or higher final receipt clears an incident**
  (`test_batch_holder.py::test_equal_or_higher_final_receipt_clears_incident`).
  A refused generation with an estimated row goes through the holder's
  incident recovery. Equal and higher final charges clear it. A lower settled
  charge without a record still does not extend.
- **Estimate frozen across a resume**
  (`test_batch_holder.py::test_estimate_frozen_across_resume_then_final_decrease_collects`).
  The first ACK sees a $4 gate estimate and a second call's $10 estimate. A
  resume without the receipt file keeps the $4, the final receipt releases
  $4, and the second holder collection accepts it. Negative control: the
  second call's estimate lowered without a final receipt is refused with
  `unsupported_decrease`.
- **Factory jobs carry no paid cap.** A `run.main` subprocess harness (same
  pattern as the existing main test) runs with an authored batch-release file
  (only its digest is checked) and an authored job installer. Both are
  contract configuration, like `job-money.json`. The real artifacts are the
  5813be ledger and the practice case. It records `c.args.max_cost is None` and
  `recovery_config['max_cost'] is None`, then runs the real streaming
  accountant with a priced OpenCode event on the 5813be ledger. The factory
  setting books it past $5 without a stop. The non-factory control (5.0)
  stops with `cost_limit`.
- **Changed-stage membership.** With `max_cost` 5 versus None, only the
  G8/G9/G16 fingerprints, the stress binding and the calibration identities
  change. Every other gate fingerprint is identical.
- **Search exam.** Every `max_cost`/`--max-cost` occurrence in `factory/`
  (`.py`, `.sh`) and `bin/` is counted per file against a classified table:
  factory-none, non-factory protection, historical decode or validation, or
  binding key. A new occurrence fails the test until someone classifies it.

Rows. Row 8 closes with the no-paid-cap and search-exam tests. Row 21 closes
with the settlement, late-booking, incident and frozen-estimate tests. Both run on real saved ledger and case bytes
through the real runtime, router and ledger code. Row 8 closes for batch
jobs only. Non-batch runs and the exam owner keep their cap by design. Row
21 closes for reservation-bound calls. An unbound legacy marker, like the
attempt-6 Codex ledger the row cites, stays on the $33 import path.

Existing tests affected. `test_stream_d_runtime.py::
test_stream_accountant_links_unknown_usage_and_settles_once_above_five_dollars`
asserted the factory marker after `run_budgeted`. It now asserts no marker,
a known total with the reservation outstanding, and the same estimate after
reconciliation. `test_flag_off_keeps_crash_reservation_without_forcing_router_deferral`
asserted `money_wait` on the retry, the row-21 poisoning itself. It now
asserts that the retry is admitted on a new lease with no router deferral,
and that the crashed call's reservation is kept as an estimate with its
marker settled. In `test_model_call_maxima.py`, the dispatch test's
interrupted call is now `estimated` when it ends instead of `pending`, and
the real-route settlement test charges the closed gate's bound (one
request's hold) instead of the $50 maximum. The direct `complete_invocation` callers in
`test_batch_accounting.py`, `test_stream_d_coverage.py` and
`test_router_cheap_maxima.py` plant their own markers, or pass final
receipts, or read saved proof records. A local draft of the
`complete_invocation` change passes all three unchanged. The settlement test
also covers a concurrent sibling call: it streams while the first call fails
with unknown usage, and it finishes without `money_wait`.

Design review 8 responses (Codex, FAIL). B1 and B2: rejected as outside
this increment, pending a second goldfish (`stream-d-money-design-8-codex.md`).
B1 needs a tagged booking on an estimated row outside `_settle_leaf`, which
no D producer makes. B2 is a property of B's collection guard on the
committed code, with or without this increment. The overclaim that B's
check is now exact is removed above. A second goldfish (fresh Claude)
upheld both rejections and found one Major: the stated reason missed two
`reconcile_reservations` call sites and the exam-owner race. Fixed above by
stating the real reasons. No code change.

Design review 7 responses (Codex, FAIL). B1: accepted. The round-6
collection change is withdrawn, because one call's release could cover
another call's drop. Instead an estimated charge never moves on non-final
evidence, so it cannot grow between collections, and B's check is unchanged.

Design review 6 responses (Codex, FAIL; fix superseded by review 7). B1: accepted. Collection credits a
release up to the prior ACK's estimate, so a grown estimate's final decrease
collects. Fixed at the collection check because any non-final evidence
without a gate snapshot can raise an estimate.

Design review 5 responses (Codex, FAIL). B1: accepted. The current charge
counts late-booked events bound to the row. M1: accepted. `_extends` accepts
an equal or higher final charge without a decrease record. M2: accepted.
The late-booking and incident tests above. N1: accepted. The test module
docstring names the money rows.

Design review 4 responses. DeepSeek was interrupted with no report. A Claude
rerun was stopped before it reported, at the founder's direction, and review 4 ran on Codex
(`gpt-6.1-sol`, FAIL). B1: accepted. The admission subtest uses real
maxima for both routes, with the ordinary-limit prerequisite stated above.
M1: accepted. Non-final estimates are monotonic, and the test replays a
stale snapshot. N1: accepted. The round-2 failed-stop text is marked
superseded.

Design review 3 responses. DeepSeek returned no final report, so review 3
was rerun with a fresh Claude reviewer (FAIL). B1: accepted. The failed-stop
marker was removed again by the same call's `complete_invocation`. The
exception is deleted, and the closed gate is the bound. M1: accepted. The
estimate uses the gate's bound and is tested with the real maxima. M2:
accepted. `route_receipts` inheritance is named above. M3: accepted. The
settlement test runs the real `run_budgeted`. N1: accepted. The outcome is
recorded before accounting. N2: accepted as a known gap. A runner killed
mid-call loses the in-memory receipt row until the next checkpoint, so that
call reads as no work. The reservation still settles. N3: accepted.
`run.main` refuses a G11 audit on a batch job. N4: noted, unreachable and
fails closed. N5: accepted. Row 8 is narrowed to batch jobs when it closes.
N6: noted. `route_receipts` grow per call, like `events`.

Design review 2 (DeepSeek, FAIL) responses. B1: accepted. Fixed through
the route receipts above. The settlement test asserts that the estimated
call's receipt shows a started outcome and that `actual_model_work` holds
with no events or markers. The projection test adds denied/admitted
(not work) and interrupted (work). M1: accepted. A failed stop keeps the
factory marker (superseded by review 3: the exception is deleted, and the
closed gate is the bound). N1: the comment beside it is now true. N2: line references
are approximate, as elsewhere in this file.

Design review 1 (DeepSeek, FAIL) responses. B1: accepted. The affected tests
are listed above. Its premise that those tests assert the pending+marker
state is wrong for the three direct callers, which pass under the change. M1:
accepted, and the window is worse than the original text said. A sibling's
`check_limits` stops, so it is not a short wait. Fixed at the source by
deleting the factory marker, not by narrowing the window. M2: accepted as
wording. The release file is authored configuration, and the row-8 proof
rests on the real ledger and the real accountant. N1: accepted. `restart.py`
is protected only by `launch.sh:494`'s early return. Item 8's search exam
must keep it unreachable. N2: accepted. Add `--continue-g11-review` to
`batch.bind`'s forbidden set. N3: noted. The `gate_state` literal stays 5,
because it is the non-factory default.


### Fourth increment: ordinary retry bounds (lane 1, 2026-10-31)

Problem. Batch calls already use the router and cumulative money authority, but
G2 consumes a two-attempt defect allowance for expiry and HTTP outages consume
mechanical-execution retries. Stress cannot identify completed categories.
Malformed JSON stops instead of repairing the answer already bought.
This is batch-only. Legacy bounds remain. No cases launch, diagnosis stays off,
and items 5–7 are not implemented here.

Change.

1. Add durable ordinary-retry helpers under the private work directory. Retry
   declared retrieval failures (InvalidInfra) with capped backoff, checking
   authenticated job authority and cancellation before attempts and during waits.
   Record transport failures separately from completed invalid work. No transport
   retry count retires a funded case. Absolute batch deadline bounds transport;
   actual model costs remain charged by ModelRuntime. Mechanical invalid-execution
   policy stays with C. Batch launch already bypasses legacy restart/holder caps;
   prove that boundary rather than removing protection from legacy launches.
2. Factory G2 refreshes expired rows on every entry, not once per restore. Two
   unsuccessful COMPLETED defect repairs remain distinct from refresh/transport
   work. A provider wait or timeout never increments that counter. Existing
   inflight merge retains old rows. Refresh trusted HTTP receipts before reuse,
   retaining superseded response directories. Flagged and unflagged HTTP failures
   use transport retry, with the unflagged fallback specified below. Confirmed
   missing page/archive keeps existing semantics.
   Final G2 invokes the freshness preparer, so aging after admission refreshes
   automatically. Recheck expiry before reuse; stale evidence never passes.
   Substantive unresolved review remains unresolved.
3. Batch dedup, idea realism, G2 confirmation, G8/G9 and stress use retained-output
   repair. Identity includes logical inputs, schema contract and requested model,
   never timestamped paths. Persist raw answer and validation error before repair.
   One schema-only repair per approved route for an identity, then exclude the
   route through A's router. Repair prompt supplies retained answer and schema,
   not a request for new investigation. Provider interruption keeps the pending
   repair; only completed invalid repair spends a route. Account changes are not
   new model routes. Exhaustion raises a distinct deterministic-output stop,
   never writer feedback. Valid completed output is reusable for exact identity;
   pending output without completion marker cannot grant a verdict. Validators
   keep their scientific criteria.
4. Batch stress runs the existing prompt in four categories: wrong fixes,
   case/freshness, fairness, V2 strategies. Each call gets only an unfinished
   category plus retained findings. Save separate category reports with binding,
   completion marker and digest. Aggregate all blocking findings, unfinished
   validation and freshness requests. Partial reports survive interruptions but
   cannot grant coverage. Changed case/judging binding starts fresh coverage and
   retains old files. Stop early on a definite blocker as before. Calls retain
   writer round and stress operation. The diagnostic execution guard remains
   shared across categories for the round (`attacker-{round}`); no new
   diagnostics are granted.
   Completed output with unfinished validation cannot complete its category.
   Malformed categories use retained-answer repair. Modern receipt resume must
   allow unfinished validation to reach category continuation. Legacy reports
   stay readable.

Publication. Each completed category is locally atomic and uses the existing
quiescent encrypted checkpoint before another category. For production batches
(recipient present, not dry-run), force checkpoint without the 15-minute throttle
and require remote_durable. Failure retries publication in place under batch authority before paid work;
there is no new checkpoint_pending terminal stop. This uses the existing uploader's remote
receipt, not a new holder ACK protocol. Stronger B immutable-generation ACK is
an item-8 activation prerequisite, not a claim of this increment.

Lane-2 interface: category reuse takes attack_binding(c) as opaque JSON. Lane 2
may narrow it to scientific dependencies. No per-gate version or comparison
changes here.

Deletes: batch expiry's two-attempt allowance, two-attempt HTTP retry cap,
whole-review restart for unfinished coverage, and malformed-output terminal
branches. Legacy and mechanical gate retry policy remains.

Tests use the hash-verified practice case, captured 5813be ledger, retained
real HTTP fixtures and saved stress reports. Model outputs, interruptions and
clock changes are authored inputs. Test more than old retry bounds before
success; cancellation/deadline in backoff; repeat expiry without defect debit;
completed defect exhaustion; retained-answer repair across wait/restart; approved
route exhaustion and changed-input reset; no added writer round. Kill a later
stress category, restore tree, assert earlier bytes/findings survive and only
unfinished categories dispatch. Missing remote publication blocks next paid
call. Changed binding cannot reuse coverage. Exercise real dedup, idea, G2,
G8/G9 and stress callers. Run full suite and commit its completed record.

Rows targeted for closure: 11 (batch waits/transport), 12 (refresh/retrieval),
15 (schema repair within approved equivalent chains). Row 13 remains open for
item 7/8 diagnostic recovery; item 4 adds incremental stress coverage only.
Close only with corresponding real-artifact tests;
no legacy-path or live-qualification claim. Item 7 stays separate.


Fourth-increment design review 2 resolutions (all accepted).

Refresh progress. A refresh call which completes but leaves any targeted row
expired consumes one of the two completed-defect attempts. A successful refresh
consumes none. A completed no-op is unsuccessful, even if IDs or formatting
changed. A wait, timeout or kill leaves a pending refresh and consumes no
completed-defect attempt. Re-entry validates the retained call completion before
charging it; a completed failed repair is charged exactly once. Reaching two
unsuccessful completed repairs raises `freshness_evidence_unavailable`.

Unflagged transport. Each unflagged URL gets a 120-second monotonic retrieval
window per G2 invocation (including backoff), bounded also by batch authority.
At that window's end, keep its old rows and bytes, mark the URL unfetched and
use the existing alternative-search top-up. This is exclusion from evidence,
never clearance. HTTP timeout is capped by the remaining window. Flagged URLs
cannot be excluded this way: they remain pending through transport retry until
retrievable or the batch deadline. Confirmed 404/archive-no-copy still uses the
existing explicit unreachable verdict. Successful fetches are reused, so other
URLs do not lose progress. This replaces the former one-shot unflagged fallback
with bounded retries, not with a wait until batch retirement.

Schema journal. `factory/ordinary_retry.py` owns a version-1 record per canonical
input/schema/model digest under `work/ordinary-retries/<digest>/state.json`.
Fields include binding, phase, spent_routes (model route strings, never accounts),
pending_route, retained_answer path/digest, validation_error, output path/digest,
and completed-call marker. Raw answers use immutable attempt-number filenames.
Re-entry reconstructs exclusions for EVERY approved lane whose route is spent,
by enumerating `model_router.routes(requested, accounts)`. Exclusions are scoped
to the helper call; transport exclusions are not written as deterministic spent
routes. Before admission, if every approved route is spent, the helper raises
`malformed_output_exhausted`. It never asks the router to wait in that condition.
The next approved route receives a schema-only repair of the same retained
original answer and schema, not a fresh scientific call. A valid repair is not
allowed to turn missing knowledge into a scientific claim: the schema permits
unresolved/incomplete output and the prompt requires preserving uncertainty.
The original route gets one completed repair too. Pending repairs interrupted by
transport resume without spending a route. Completed malformed repairs spend
one route atomically; completion markers prevent recharging on replay. Changed
logical inputs or schema start a new digest and retain prior records.

Stress contract. `factory/stress_progress.py` defines ordered stable IDs
`wrong_fixes`, `case_freshness`, `fairness`, `v2_strategies`. Its request names
exactly one category and uses a category-specific contract added to
`factory/prompts/attacker.md`. In category mode, `category` is that exact ID and
`category_complete` is a boolean; `complete` does not authorize whole-review
completion. The runner maps category_complete into the existing report shape
only when validating that category, and requires no unfinished_validation for
coverage. The aggregate, not the model, computes whole-review `complete` from
all four validated category markers. A nonempty definite blocker can return
feedback before all coverage finishes. Partial findings stay in their category
file, and are included in continuation prompts. Category IDs and markers live
in `work/attacks/round-N-categories/<binding-sha256>/state.json`, with separate
`<category>.json` reports. Completion digests bind exact bytes. The prompt edit
intentionally changes attack_binding's prompt hash: existing saved stress
receipts rerun once under this contract, never silently grant category coverage.

Files and sequence. First implement ordinary_retry.py and its real-artifact
tests in tests/factory/test_stream_d_retries.py, without changing
bin/run_validity.retry. Then integrate G2 in run.py (ensure_freshness,
freshness_topup, g2, confirm_hits) and timeout/generation handling in
freshness_retrieval.py. Then integrate retained-answer handling in
statement_precheck, idea_realism, review and confirm_hits. Finally implement
stress_progress.py and the attacker prompt contract, joining it at
write_and_attack and testing resume there. Tests exercise each producer before
the next phase. No gate_state or extension-comparison changes.

HTTP generations. Before replacing an existing retrieval directory, rename it
to `<name>-superseded-<uuid4hex>` beside the active directory; never overwrite
old response bytes. A fresh generation owns its receipts.json and body files.
A partial failed generation is retained the same way before retry. Publication
copies these with the private work tree.

Publication scope. Failure blocks all subsequent model dispatch for this case,
not only stress. Before checkpointing a category, persist a stress publication
pending marker in its state. The runner checks that marker before any new model
call, retries the quiescent checkpoint, and clears it only after the new
`durable-checkpoint.json` reports remote_durable true. A prior successful receipt
cannot clear a newer pending marker: require the checkpoint call performed for
that marker to succeed. On crash after upload but before clearing, another
checkpoint is safe. This uses existing whole-tree upload, not a holder ACK.
Up to four forced full archive uploads per stress round add time/storage cost;
item 8 must qualify that overhead before activation. Principal risk is accidental
reuse of incomplete coverage; digest/marker and interruption tests target it.


Fourth-increment design review 3 resolutions (all accepted; these details
supersede earlier ambiguous wording).

Stress operation state machine. One schema-v2 attack-state operation_id spans
all categories and schema repairs for one stress round and binding. Its report
always names the runner-written aggregate round-N.json. The category helper
never substitutes a category path into attack-state. While ANY required category
is pending, attack-state stays phase=pending, review_pending=true, with no
review_completed marker. Category calls use pending_call with that same receipt,
but their on_complete callback commits only their category completion and
rewrites the aggregate; it does NOT complete attack-state. The aggregate is
rewritten atomically after every category return (also on interruption in a
finally block after the model process joins), preserving all parsed partial
findings. Interrupted partial bytes remain separately even when unparseable.
Only all four completed categories, or an explicit definite blocking finding,
complete the stress operation. The runner then writes aggregate digest to both
output_sha256 and review_completed.report_sha256, clears review_pending and
sets phase=completed, followed by existing validation/feedback and phase=validated.
A definite finding may end the round early but never grants a stress pass.

The receipt has category_mode=1 and category_state pointing to the bound state
file. On resume, this mode branches BEFORE the legacy saved-report unfinished
validation and authentication decisions. Validate operation/round/binding and
category digests; if the same binding is pending, retain the aggregate and call
the category helper on the same operation without review_admitted renaming it.
Completed categories skip calls; unfinished ones continue with retained output.
A completed aggregate authenticates against its receipt before normal feedback
or pass. Changed binding creates new coverage and a new operation_id (same writer
round), retaining all old files. A legacy receipt without category_mode retains
legacy validation rules and starts new category coverage when it needs rereview.
The helper cannot return a passing aggregate with any category incomplete.

Mechanical schema-repair guard. A repair cannot supply new scientific values.
Before calling repair, parse the retained answer as JSON (allow only stripping
a single surrounding markdown JSON fence). Extract the caller's decision
projection ONLY if every required decision field is already present with the
right type. After repair, require EXACT equality of that projection; otherwise
that repair is invalid and spends its route. Dedup projection is duplicate_of;
idea projection is approve; panel projection is both fairness.approve and
realism.approve; G2 projection is the ordered list of URL/resolved/same_bug/
retrieved/retrieved_from/archive_checked/archive_available/archive_snapshot_url/
live_failure/app_version/version_scope, with the same optional-field defaults
as its existing validator; stress projection includes category,
category_complete, blocking, unfinished_validation, freshness_review and
cheats_tried. This is deliberately conservative: malformed syntax that cannot
be decoded, missing scientific fields, and empty/missing output cannot be
repaired into ANY decision. They still get the schema-only attempt (which can
return an unresolved envelope), but cannot approve, reject, clear freshness or
be sent to the writer. This avoids heuristic extraction of a word like true
from prose. Repair may fix non-decision shape/metadata only when a trustworthy
projection exists, and still must pass the existing caller validator.

Unresolved is an adapter envelope {status: unresolved, reason: ...}, not a new
scientific verdict schema. Every caller handles it identically: spend that
completed repair's route, try the next approved route on the same original
answer, then raise malformed_output_exhausted when none remain. Never return
it as dedup clear, an idea rejection, a panel vote, G2 clearance or stress
feedback. A missing/empty output after a successful CLI completion is malformed;
if the call did not complete it is pending transport work, never eligible for
schema repair. No new full investigation is hidden inside a repair call.

Freshness outage accounting. At each G2 pass distinguish row metadata defects
from runner transport-unfetched rows. If every otherwise eligible row failed
transport, retry retrieval with capped backoff instead of launching any model
top-up. Partial transport failure still permits alternative-search top-up after
the 120-second URL window. A completed top-up charges a defect only for remaining
metadata defects/missing search minima computed BEFORE excluding transport
failures. It never charges merely because new rows are also unfetchable. If a
top-up yields no metadata progress while transport failures remain the sole
cause, back off and retry retrieval, not another paid top-up of identical rows.
Mixed expired/defect rows are one repair operation: successful means targeted
metadata errors are gone and no new metadata defect was introduced. Otherwise
one completed-defect charge, never one per row or role. The original two-attempt
bound remains for genuine completed bad work.

Freshness state. freshness-repair.json v2 stores statement_sha256,
completed_defects and pending {operation_id, before_rows, targeted_errors,
phase, output_sha256, charged}. Persist pending before work; persist completed
from the call completion callback, before interpreting rows. Recovery finishes
the inflight merge, checks completion and charges once, setting charged in the
same atomic state write as completed_defects. Multi-role top-up tracks each role
completion, so a wait on role two neither repeats role one nor counts the entire
operation as completed. v1 migration preserves attempts as completed_defects
conservatively (old files do not prove whether reservations completed); new
expiry-only work is still allowed, but a new unsuccessful completion stops if
the saved counter is already two. No v1 reset. recovery.expiry_freshness_stop
remains legacy-only; batch G2 reads v2 itself.

Publication retries. No checkpoint_pending terminal label is introduced.
A pending category publication invokes checkpoint_progress(interval=0), validates
that call's remote_durable result, and retries failures with the same capped
backoff helper, under authority and cancellation. No model call may cross that
barrier. Missing recipient on a non-dry production batch fails configuration
closed instead of silently skipping publication. Tests without production
publication install an explicit test callback rather than depending on absence
of recipient. Publication I/O cannot run while a category call is active.

Bound outcomes. Transport/publication retry ends at the authenticated deadline
with retired_batch_bound (the existing job_authority label). A permanently
unavailable flagged URL occupies this worker until then; it cannot be silently
cleared. This may lower throughput, but does not hold other cases' admission
locks. B owns capacity and replacement scheduling; no new slot promise here.
malformed_output_exhausted and freshness_evidence_unavailable are operational
stops, not case fail/pass or writer feedback. This increment will add them to
D's exhaustion-label recognition only (not implement outcome routing), so the
existing pending projection queues them when diagnosis is later enabled.

Caller identities. All include schema version, requested model and role.
Dedup: candidate statement bytes plus sorted case IDs and contents of every
prior/reserved statement. Idea: statement bytes and review contract. Panel:
reviewer index and complete copied case inventory (including freshness.jsonl)
plus reviewer prompt hash. G2: confirmation_contract binding plus trusted
retrieval digest. Stress: attack binding, round, category ID and category
contract version; continuing partial output does not change that identity.
No timestamped paths participate. Scientific binding updates remain lane 2's
separate work. Exclusion contexts copy existing exclusions and UNION spent-route
lanes; they never replace runtime transport exclusions.

Cost and schedule. Four calls repeat case read-in up to four times; no measured
per-category price exists, so claiming a numeric estimate would be fabricated.
Each call is admitted at its enforced router maximum against the same cumulative
job/batch envelope; up to four maxima plus repair maxima are the admission upper
bound, not new money authority. Item 8 must measure this overhead. Serial dead
URL windows can take 2 minutes per URL; this is acceptable for this increment
only within the batch deadline and remains visible as transport time, not model
work. Implementation order is the four phases above, followed by the full suite
and fresh diff review in this task; no calendar delivery promise is made.

Fixture inventory for tests: tests/factory/fixtures/invalid-runs-practice.json.gz
(hash-verified case), tests/factory/fixtures/20261029-real-public-cards.json.gz
(5813be ledger via tests/factory/test_stream_d.py::cards),
tests/factory/fixtures/invalid-runs-http.json.gz (retained HTTP), and existing
stress-report artifacts located by tests/factory/test_attack_report_freshness.py
and test_stream_d_runtime.py. Before implementation, verify whether those tests
actually contain captured stress report bytes; if not, explicitly label authored
category reports and use the real case/ledger as the artifact proof. Do not
claim authored model outputs are captured real stress findings.


Fourth-increment design review 4 resolutions (accepted).

Completed unfinished stress work. Distinguish a killed/transport-interrupted
call from a successful CLI completion whose category remains incomplete. The
latter is failed work, never transport. Each category stores completed_incomplete
and a progress projection: sorted unique blocking findings, freshness requests
and cheats_tried, plus explicit completed subchecks from a fixed list in that
category's prompt. One continuation is allowed after an incomplete completion
only if it added a new fixed subcheck or substantive finding. Rewording a finding
is not progress; findings use stable IDs assigned at first retention, and only
new completed subchecks grant continuation. The fixed subcheck set is finite.
No-progress completion raises stress_validation_exhausted immediately; exhausting
the finite subcheck set with unfinished_validation does the same. Completed
incomplete output is never sent to schema repair merely to change completeness.
Transport interruptions do not spend this count; resume keeps partial bytes.
The operation, findings and incomplete coverage are retained at that label;
D's exhaustion recognizer queues diagnosis under the existing pending projection.
It is never a case verdict or writer feedback.

Diagnostic boundary. This increment does not re-grant the round's diagnostic
claim, whether completed or interrupted. An interrupted diagnostic is invalid
execution and routes to the same operational stress_validation_exhausted outcome
with its saved status, rather than buying another category call which cannot
complete. The old unfinished_diagnostic and unfinished_validation terminal
branches in category mode are replaced by that single recognized exhaustion.
No blind rerun can overlap a surviving diagnostic process. Automatic diagnosis
and repair of this execution remains item 7/8. Therefore row 13 is NOT fully
closed by item 4 alone: incremental coverage and bounded continuation are proved
here, but diagnostic-exhaustion automatic recovery is explicitly left open until
item 7/8 tests it. The earlier target-to-close wording for row 13 is narrowed
accordingly. This is a scope correction, not a claim that a new stop solves it.

Unprojectable output. Supersedes review 3's guaranteed-failure repair calls.
If the original completed answer has no trustworthy decision projection, skip
schema repair and mark that model route spent for this input. Ask the next
approved equivalent route the ORIGINAL full scientific request with the same
logical input binding, in its own clean output file. Its independent valid
answer can supply a verdict; it is new evidence, not a repaired claim. If that
full answer is malformed but has a projection, give that route its one schema
repair; if not, spend it without repair. Exhaustion is checked before admission.
For projectable malformed answers, attempt schema-only repair first. On failed
repair, spend its route and send the original full request to the next route.
Persist kind=judgment|repair, route, original answer path and completion marker
per attempt. Interrupted full/repair calls remain pending of that same kind.
The durable spent_routes bound applies across both kinds and across restarts.
Equivalent-model judgments still run every caller's existing validators and
independence checks; no new model family is allowed.

Archive fallback. Preserve HTTP status failures as typed retrieval evidence.
After the same bounded live retry window (120 seconds), persistent HTTP access
failures (401/403/451/429/5xx) try the existing archive availability API and
snapshot retrieval. A retrieved snapshot may support independent judgment;
record live_failure=http_<status> and retrieved_from=archive. Extend only the
retrieval-agreement validator's accepted failure status syntax, not its criteria
for same_bug or scope. Failed archive lookup/snapshot remains transport pending
under authority. A successful archive lookup with no snapshot does NOT clear a
bot-walled page (unlike confirmed 404/410/DNS disappearance): the live page may
still be public to contestants. That condition stays unresolved with retained
evidence and the same deadline hold; no public-match exclusion is invented.
Unflagged URLs retain their bounded exclusion/top-up policy. Network errors
without an HTTP response also attempt the archive after the window but cannot
prove live disappearance. Batch flagged retrieval no longer calls
run_validity.retry anywhere; all those calls use the new transport helper.

Integration nits. review_admitted initializes/renames the aggregate exactly
once per stress operation, not once per category nor on resume. Dispatch barrier
is checked in model_runtime.dispatch after acquiring its serial lock, before
admission (the already-active nested owner call bypass remains guarded as now).
Install a runner-owned callback for forced checkpointing so model_runtime does
not import run.py. Missing production callback with a pending marker fails
configuration closed. _opencode skips its ordinary throttled checkpoint for
category-mode calls: the helper's forced publication is the single checkpoint.
Partial findings from a call without a completion marker NEVER end a round or
become writer feedback; they only inform continuation. Per-category attempts
use <category>-<attempt-number>.json; completed validated output is referenced
by filename/digest in state.json, never overwritten. <category>.json is not an
output path. The aggregate is the only mutable report view.


Fourth-increment design review 5 resolutions (accepted).

Fixed stress coverage contract. The ordered category/subcheck IDs below name
existing attacker-prompt requirements, rather than new pass criteria. In category
mode the prompt lists the category's full set and requires completed_subchecks
to be a unique subset of it. Unknown IDs, duplicates or wrong types are malformed.

- wrong_fixes: prior_families (recheck prior exploited families), timing_ordering,
  over_refusal, partial_paths, test_data_identity_seed, judge_visibility,
  data_editing. These are inspections of the wrong-fix dimensions already listed
  in section 1; executing them all is not required or authorized.
- case_freshness: plain_reference (inspect break/fix consistency),
  expected_judges, public_search (log searches and request independent review),
  contestant_leaks. These match the four section-2 checks.
- fairness: discoverability, behavioral_grading, acceptable_answers,
  owner_fact_sheet, provenance_realism. These match the five section-3 rules.
- v2_strategies: frozen_first_fix, claim_without_evidence, ask_everything,
  block_all_pending, honest_reference_comparison, intent_and_second_writer,
  pending_and_blind_monitoring. These cover the named strategies and the final
  V2 checks; inspection is distinct from the single optional execution diagnostic.

category_complete=true requires ALL listed subchecks in completed_subchecks,
no unfinished_validation and a completed call marker. A model's assertion alone
cannot omit a subcheck. completed_subchecks joins the decision projection used
for schema repair; repair cannot invent coverage. The first call is compared
with an empty set. Each completed incomplete call may earn ONE MORE continuation
only if it added at least one previously uncompleted subcheck; repeat this rule
after every completion. Substantive findings alone do not earn continuation.
The accumulated subcheck set is monotonic and bounded by the fixed list.
If all subchecks are marked but the category remains incomplete/unfinished,
raise stress_validation_exhausted without another call. If a completed report
contains a definite blocking finding, that finding ends the round FIRST, even
with unfinished validation or no coverage progress. Only completed-call findings
can take this precedence; partial findings remain continuation context.

Archive predicates (factory/run.py::checked_freshness_verdict). Keep dead limited
to http_404, http_410, dns_failure and deleted. Add access_failure for http_401,
http_403, http_451, http_429, http_5xx and network_error. `archived` accepts a
verified retrieved archive snapshot after either dead or access_failure.
`unreachable` still requires dead and verified archive absence. The agreement
check still requires exact runner receipt values; it is not where statuses are
classified. Update confirm_hits' confirmation prompt to list network_error and
HTTP access failures and explain their stricter verdict handling.
An archive behind access_failure may confirm same_bug=true, but may NOT clear
same_bug=false: an older snapshot could miss current public information. A false
or unresolved reviewer verdict in that state keeps the flagged URL pending.
A subsequently successful live retrieval may clear through the ordinary
independent review. For dead pages, existing archived false/exclusion semantics
remain unchanged. Failed archive retrieval also stays pending. Held flagged URLs
recheck live and archive after capped exponential backoff: 5, 10, 20, 40, then
60 seconds between cycles, checking cancellation and authority at least every
second while waiting. This trades archive API traffic for bounded recovery
latency; no busy loop and no additional model call before new retrieval evidence.

Equivalent routes. Claude currently has two accounts but one model route.
Unprojectable completed Claude output therefore reaches
malformed_output_exhausted with no futile schema-repair call and no unauthorized
cross-family fallback. Row 15 closure is limited to retained-answer repair when
there is a decision projection, and equivalent full-call fallback where A has
an approved chain. Single-route unprojectable output remains a documented limit;
it is operational exhaustion, never fabricated feedback or approval.

Additional real-artifact test cases: no-progress stress stops; progress allows
one further call per newly completed subcheck; all-subchecks-but-unfinished stops;
completed blocker takes precedence; interrupted diagnostic becomes recognized
operational exhaustion; undecodable output invokes the original full request on
the next route; single-route Claude exhausts without repair; 403 plus archive
can confirm but cannot clear; 403 plus no archive remains pending until live
recovery/deadline. invalid-runs-http.json.gz supplies only the captured 200
response. HTTP denials, archive availability bodies and snapshots for these
new cases are authored test transport inputs, explicitly not captured evidence.


Fourth-increment design review 6 resolutions (accepted).

Stable G2 evidence identity. Keep digest(receipts) for byte-authentication of the
full timestamped receipts. Add judgment_projection(receipts) and
judgment_digest(receipts) in freshness_retrieval.py for reviewer reuse. The
projection is an ordered list, one entry per supplied URL: url, retrieved_from,
live_failure, archive_available, archive_snapshot_url, and content (ordered
url/final_url/sha256 records ONLY for the live 200 response or actual retrieved
archive snapshot 200 response). Exclude at, local body filename, directory,
request ID, archive availability API response body, and all non-200 access
failure response bodies. Archive metadata contributes only its normalized
availability and selected snapshot URL. Retain access-error bodies privately
when available for diagnosis, but they NEVER participate in judgment identity.
A network failure has network_error and no content. Full receipt/body hashes
must still validate before computing a projection; this does not weaken byte
integrity. Retain both receipt_digest and judgment_digest in verdict records.

G2 retained-output identity is confirmation_contract plus search_binding with
evidence_sha256 replaced by the canonical semantic search-row digest, plus
judgment_digest. Semantic rows include who/kind/query/url/hit/ambiguous/note/
app_version/version_scope; exclude at, retrieved and _search_id (retrieval
status is supplied by the trusted projection). Preserve case context, statement,
reservation and requested models from search_binding. This also prevents model
re-search timestamps from defeating content-identical verdict reuse. Validate
fresh row metadata and fresh trusted receipts BEFORE reuse. Reuse the retained
completed verdict for unchanged judgment identity, including an unresolved
verdict, without a model call. Re-run checked_freshness_verdict against current
receipts so an old false verdict cannot clear an access-failed URL. Retrieval
refresh and receipt integrity remain independent of model-work identity.
A changed page/snapshot content hash, normalized retrieval outcome, substantive
search-row field, case context or contract permits a new judgment.

Test two consecutive identical 403 + snapshot fetch cycles, with changed at,
body filenames, availability API metadata and bot-wall nonce bytes: the second
cycle must perform zero reviewer calls. Changing snapshot body, becoming live
200, or changing case context must require a new judgment. A changed/tampered
body without matching full receipt hash must fail validation before reuse.

Two-phase retrieval API. Extend fetch to return typed non-200 HTTP responses
(including retained body if bounded) and network_error; do not discard status
into a generic exception. Add retrieve(rows, directory, *, archive=True,
deadline=None). With archive=False, access/network failure produces a typed
live failure consumed by transport retry, without an archive request. Dead
404/410/DNS results can proceed directly to archive=True. At the live-window
boundary, archive=True attempts the existing availability/snapshot path even
for access failures. The runner chooses phases and owns backoff; retrieve has
no retry loop. A network failure of archive lookup/snapshot is InvalidInfra,
not proof of absence. Bound each HTTP call by the remaining deadline.

Unflagged access failures also try archive at their window boundary. A verified
snapshot counts as fetched for search minima, but an existing hit/ambiguous row
must go through the stricter flagged policy. Archive absence or lookup failure
keeps an unflagged URL excluded and allows alternative top-up. No unflagged
transport outcome clears any historical hit.

Stress bounds clarified. Retain the explicit category_complete boolean as a
conservative additional model assertion; all subchecks done without it exhausts
rather than guessing consent. The initial call plus strict-subset progress gives
at most one call per subcheck (7+4+5+7=23 completed scientific category calls per
round), before separate route-bounded schema repairs/fallbacks. If a report adds
its final subcheck but is still incomplete, there is no further call. Interrupted
transport calls remain charged actual money but do not consume completed-work
bounds. A category needing the already-used diagnostic can still exhaust even
if another category used it successfully; this is the explicitly deferred row-13
recovery limit, not an extra diagnostic grant.


Fourth-increment design review 7 resolutions (accepted).

Fetch raw archive bytes. Rewrite the validated selected snapshot URL's
/web/<14-digit-timestamp>/ (or existing id_) segment to
/web/<timestamp>id_/ before HTTP retrieval. Retain archive_snapshot_url as the
API-selected URL for existing agreement validation. The response's requested
URL records the raw URL. Hash only the raw response bytes; never replay-toolbar
HTML. A changed closest timestamp is legitimate new evidence. The transport
test supplies different authored replay wrappers per cycle but asserts only
the id_ URL is fetched and that identical raw snapshot bytes reuse judgment.

Live-only receipt shape. An access/network failure has retrieved_from='none',
live_failure='http_<status>' or 'network_error', archive_available=null,
archive_snapshot_url=null. HTTP responses are retained with status/body/hash;
a network error has one synthetic response with status='network_error', empty
body and its hash (not a fetched-content claim). Thus load validates exact bytes
without accepting an empty response list. These are intermediate transport
receipts, never search-minimum or verdict evidence. The runner attempts archive
at the window boundary; it does not pass a live-only failure to a reviewer.

Hold predicate. ensure_freshness holds only when a blocked flagged row currently
has access_failure/network_error, or archive retrieval itself is transport
pending. The first is explicit in the G2 result as transport_pending; the second
is handled inside retrieval transport retry before judgment. All other unresolved
review (including live 200) retains freshness_review_unavailable. Recovery's
legacy classification stays unchanged. Dynamic live-200 bodies can change
judgment identity, but never enter this hold loop: a valid judgment clears or
confirms, and an unresolved judgment stops. No arbitrary HTML normalization is
introduced.

Review 7's single blocker and three nits are accepted and corrected above.
This is a narrow retrieval-URL/receipt correction; implementation proceeds with
no disputed finding. Fresh diff review will verify the implemented contract.


Implementation notes for fourth increment. New modules are ordinary_retry.py,
ordinary_freshness.py and stress_progress.py. Category continuation identity adds
its completed-result ordinal to the stable category/input identity: this is a
new completed-work unit authorized only by strict subcheck progress, not by a
transport retry or partial output. The ordinary JSON helper retains raw attempt
files in ordinary-retries and stress additionally copies each interrupted output
to category-local immutable partial files. Freshness role-completion markers are
written from on_complete; the pending operation becomes completed after every
required role has returned or its completed marker is replayed. This closes the
kill-after-role window without another model call. Old runtime writer/accounting
tests isolate stress through a single-call adapter; new tests run the actual
category orchestrator with the real router and reservation ledger.

Tests/factory/test_stream_d_retries.py labels authored model/HTTP-denial/archive
inputs explicitly. Full-suite result and fresh diff review will be recorded in
docs/reviews/stream-d-retries-suite-1.md and stream-d-retries-diff-1.md.
Rows 11/12/15 are batch-scope closures with the limitations stated in their table
entries; row 13 remains open. No item-7 implementation or activation is included.


#### Diff review 1 resolutions

A shared URL receipt cache separates retrieval from confirmation snapshots. Each
hold cycle marks URLs for refetch, but authenticated live successes remain reused
until their normal expiry. A held URL is refreshed once per cycle; the second G2
consumer copies the same bytes rather than fetching again. A batch confirmation
therefore cannot buy a new judgment just because another successful page has
volatile HTML. Changed snapshot content or case context still changes identity.
HTTP access failures with no archive count toward the broad-outage predicate.

Category completion checks unfinished diagnostic state before authenticating an
aggregate without blockers, including a saved aggregate on resume. The existing
recognized stress_validation_exhausted label handles this case. Definite completed
blockers keep precedence. The pending-publication marker is written before category
state, so a kill between the writes causes an extra publication rather than an
unpublished next call. Partial attempt paths are explicit continuation inputs.

Focused regressions use captured practice/5813be artifacts and authored HTTP/model
failures. They execute real G2 hold orchestration, live recovery, category rebind,
last-category diagnostic timeout, the publication crash window, cancellation during
backoff and v1 migration. Row 11 now also names executed batch launch/holder boundary
tests and five stress interruptions, instead of citing an entire test file.

#### Item 4 handoff after merging item 5/6

Parent reassigned item 7 to lane 2. Lane 1 owns only item 4.
The publication callback is installed by Ctx construction and before resume
dispatch; crash tests rebuild launch inputs and the saved card without retaining
runtime attributes. Review and suite evidence are in stream-d-retries-diff-2.md
and stream-d-retries-suite-4.md under docs/reviews/.

Small interface for lane 2's per-gate versions: item 4 introduces scientific
validation in ordinary_retry.decode/projection (G2, G8/G9, idea/dedup and stress
retained-answer decisions), plus stress_progress.CATEGORIES/valid and category
completion/aggregation in stress_progress.run. These inputs must be covered when
that scientific contract changes. Retrieval waits, publication and transport
backoff remain plumbing. The initial item-4 change also changes the existing
runner evaluators and attacker prompt, but a later edit isolated to these new
modules needs version coverage too. Lane 1 does not change gate_state's item-5
implementation here; this is the explicit integration interface for its owner.

## Item 5 implementation: scientific receipts and per-gate versions (2026-10-31)

Lane 2, based on b500db9. This increment implements only item 5. It leaves
extension comparison isolation, continuation routing and diagnosis enablement
to their ordered increments. No real cases launch here.

### Problem and change

The existing gate cache follows transitive runner functions but also pins whole
runtime/accounting modules and its own source file. A router, ledger, logger or
publication edit can therefore erase scientific passes. Calibration has the same
problem. G10 records stop reasons, but a capped failed submission can still reach
the wrong-fix reviewer. The existing easy-calibrator difficulty threshold is
intentionally unchanged; this increment separates the scientific evidence.

Keep automatic, content-derived per-gate versions rather than hand-maintained
release numbers. Split scientific inventories from receipt schema versions:
`gate_state.scientific_version(c, gate, bench)` returns a digest of the gate's
runner evaluator/transitive scientific helpers, explicit external evaluator and
scenario dependencies, prompts, effective model/effort settings and judge
configuration. It excludes case bytes, seed, slot and plumbing implementation.
Full receipt inputs still bind case bytes, execution settings and evidence bytes.
The inventory covers every pipeline gate and stress for later extension snapshots;
this increment does not implement snapshot comparison or route extensions.

Use one declared boundary for runner transport helpers (model dispatch, shell,
logging, budget admission, publication and cleanup), and remove external router,
ledger, price, registry and runtime implementation hashes from scientific inputs.
Retain calibration/delivery, validity classifiers, judge/checker, strategy,
scenario, case-contract and fairness logic. Shared scientific helpers invalidate
all gates that actually depend on them; changing G4 alone never invalidates G5.
Keep G7's independent fresh execution and G11's fresh-seed execution contracts;
G2 must still enforce retrieval freshness, G3 must prepare the live environment.
These mandatory executions do not revoke any other gate's retained pass.

Delete the whole-cache-file digest from gate identity. Keep the receipt schema
version unchanged unless its reader format changes; include an explicit per-gate
scientific digest in newly written receipts. No permissive historical migration:
old opaque/mismatched identities cannot prove the new dependency partition and
are retained as historical evidence, not relabeled as a new scientific pass.
Only identities created under this new partition remain reusable across later plumbing edits. Missing, changed or invalid
evidence never authorizes reuse. G10 attempts use the same scientific dependency
boundary, preserving their strict prefix and pending-submission checks.

### G10 evidence semantics

Add content-free scientific evidence counts alongside the existing stop/outcome
counts: solved, demonstrated failed execution, capped, no submission and unknown.
Capped failed submissions remain capped even if their saved execution failed;
a capped solve remains a demonstrated solve. A no-submission is never a wrong
fix. Keep existing diagnostic stop/outcome fields for compatibility and retain
original private attempts and execution bytes. New attempt receipts record their
scientific outcome; readers recompute it, rejecting conflicting labels.

G10 retains its existing easy-calibrator admission criterion. This increment
changes evidence classification, not the difficulty threshold. G16/G17 check the scientific eligibility of retained attempts before invoking
the independent reviewer. A capped/unknown failed submission returns None
directly from review_attempts: breadth/diagnose return a scientific gate fail
with verdict_valid:false, review_inconclusive:true and no hard label. This
does not enter independent_review.review and consumes no reviewer family or
infrastructure retry. Missing submissions retain their existing bounded
replacement path; a capped or unknown replacement is likewise inconclusive.
The pure verdict validator also refuses wrong_fix for ineligible rows as a
defense in depth. Malformed model answers retain the existing operational path.
Existing missing-submission recovery remains bounded and keeps its old receipt;
this change does not add a retry allowance. Invalid execution still raises the
existing infrastructure classification before any scientific count.

### Tests, deletions and row closure

Replay the saved public practice case and raw plain/reference/cheat/invalid
execution artifacts in tests/factory/fixtures/invalid-runs-*.json.gz. Reuse their
bytes through the receipt writer/reader, change router/accounting/publication
and unrelated runner source, and prove retained passes and calibration identity.
Mutate a single evaluator and prove only its dependent gate invalidates; mutate
judge/scenario/prompt/model settings and prove the affected versions change.
Test missing and tampered evidence, old schemas, and independent gate inventories.

Replay saved public calibration diagnostics for real cap/no-submission facts,
and raw saved valid/invalid executions for demonstrated failures. Authored stop
variations on those artifacts are explicitly labeled as perturbations. Exercise
G10 acceptance and G16/G17 review validation, including a reviewer incorrectly
calling a capped attempt wrong_fix. Existing item-3 real-ledger settlement tests
supply row 39's usage half. Close row 39 only if these real-artifact tests and the
full suite pass; cite the exact test paths in the register. No other row closes.

Deletes: plumbing byte dependencies and the global cache-source invalidator.
run.py changes also replace strategy_run's whole-manifest and whole-source
signature with scoped scientific dependencies. No A/B/E interface or lane-1
retry/routing contract changes. Full validation is the prescribed tests/run.py suite, with a
unique retained suite log and committed result record, followed by a fresh diff
review.


### Review-1 implementation details and limits

The boundary is conservative, not a semantic Python analyzer. Pure plumbing
modules (model_runtime, model_call_gate, model_router, budget, token_prices,
free_models, registry, launcher, collection and publication) and runner helpers
`sh`, `opencode`, `_opencode`, `model_call`, `resume_provider_wait`, `log`,
`public_progress`, `shred_tree`, `update_case_budget`, `case_budget_boundary`,
`bench_manifest`, `seal` and `wipe` do not enter scientific digests. Remove
model_call from G16's explicit source roots and opencode from stress roots.
Mixed evaluator functions `calibrate`, `checkpoint`, `strategy_run`, `g3`, and
mixed bench executables remain conservatively scientific: edits inside those
functions/modules still invalidate their dependent gates. Plumbing changes
must stay behind the named boundary to preserve passes. Extracting every mixed
executor is not part of this increment; do not silently ignore its code.

Keep the current execution bindings (seed, slot, worker count, concurrent roles,
role/total call limits, time limits, paid limit and UNBUG_FACTORY_SLOT) in full
receipts. Moving slots changes delivered endpoint bytes and is deliberately not
asserted equivalent here. The per-gate *version* removes case, seed, slot,
UNBUG_FACTORY_SLOT, worker count and concurrency, but keeps scientific run
counts, exposure/time/call limits, source mode, model/effort and judge image
configuration. Changing money settings remains a conservative receipt change;
this work does not migrate item 3's paid-cap contracts. Code-only ledger/router
changes preserve every new-partition reusable receipt.

The inventory keys are the exact run.GATES strings (G12 is sealing, not a gate)
and `stress`. All gate inventories include case_contract. Existing MEASURE
means case_permissions, bench, bench_judging, checkpoint/checkpoint_evidence,
claims/refusal, factory_pool, diagnostic_budget, public checker/traffic,
projects and guards. Existing STRATEGY means strategy, strategy_resume,
silent_window, exposure, live_shop/live_traffic, shoppers and calibration;
registry is removed. MODEL becomes calibration only. These mixed scientific
modules stay whole-file bound; pure execution modules above are removed.

| Gate | Additional scientific dependencies and roots |
| --- | --- |
| G1 | case_contract, contract tool dependencies; g1 |
| G2 | admission, freshness_retrieval, independent_review, reviewer prompt; g2 |
| G3 | MEASURE, bin/setup, compose files, project image configuration; g3 |
| G4/G5 | MEASURE, run_validity; own gate root |
| G6 | MEASURE, run_validity, verify-negative; g6 |
| G7 | MEASURE, run_validity; g7 |
| G8/G9 | MEASURE, STRATEGY, calibration, root markdown and harbor, reviewer prompt/models; own gate |
| G10 | MEASURE, STRATEGY, calibration, run_validity, exam_responder and harbor; g10, calibrate, calibration_identity; both calibrator and owner roles |
| G11 | MEASURE, run_validity, fake-pass-check, independent_review; g11, reviewer roles |
| G13/G14/G15 | MEASURE, STRATEGY, run_validity; own gate |
| G16/G17 | G16's existing fairness/owner/exam inventory; own gate, calibrate, make_pilots, family, jload, calibration_identity; strong solver, builder and reviewer roles |
| stress | judge_dependencies plus attack_report/stress_request/g1, attacker prompt/model/effort |

`scientific_version` returns a SHA256 over sorted JSON for this inventory.
New gate receipts store `scientific_version` beside existing inputs/signature;
load checks it when present, and always checks full inputs plus evidence.
The existing pinned compatible_panel fallback and G16 calibration_binding check
remain. No new global schema bump is used to invalidate an unrelated gate.
Strategy receipts use the corresponding G13/G14/G15 inputs plus strategy name
instead of bench_manifest or whole run.py/registry hashes.

`scientific_outcome` on new attempts is one of solved, demonstrated_failure,
capped, no_submission, unknown. Order: a valid solved row is solved; absent
submission is no_submission; time_limit/call_limit is capped; only explicit
completed + submitted + checked_runs>solved_runs>=0 + errors==0 demonstrates
failure; everything else is unknown. Unrecorded never means uncapped. Aggregate
`scientific` is exactly {version:1,outcomes:{<all five keys>:<integer counts>}}.
Old diagnostic fields remain unchanged. Public old-card counts cannot prove an
uncapped failure because marginal stop/outcome counts have no per-row join.

Deployment is a one-time scientific partition migration. All pre-partition gate
cache receipts, strategy signatures, stress bindings and calibration identities
that differ are not reusable, even if their old science was valid. Originals
remain retained; no history is relabeled. In-flight work may need up to all
previously passed gates, stress and all calibrator tries again, paid only under
existing authority. Exact dollar cost is unknown and may exceed a case's current
commitment; no budget increase or run is authorized here. Sealed delivery proofs
also become stale through sealed_audit.delivery_contract/verify_exam and require
ordinary requalification; there is no legacy admission exception. Subsequent
boundary-only plumbing edits preserve all nine reusable gates and calibration
attempt identities. That preservation count is the payoff test. Scope estimate:
one implementation/review increment plus the offline suite; no paid validation.

Row 39's real cap evidence is case-20261017T125556Z-18681d in
invalid-runs-public-cards.json.gz, easy diagnostic counts time_limit=3 and
no_fix_submitted=3. Raw `plain`, `reference`, `cheat` (the saved refuse-all
execution) and `reset-invalid` entries in invalid-runs-real.json.gz prove
execution classification, not actual capped submissions. Authored cap/reviewer
perturbations on these executions do not prove a historical capped-submission
lifecycle. If no such saved attempt can be found, leave row 39 open for item 8
and report the limitation instead of fabricating proof. Usage tests are
`test_stream_d_runtime.py::test_unknown_usage_settles_at_gate_bound_and_next_admission_proceeds`
and `test_stream_accountant_links_unknown_usage_and_settles_once_above_five_dollars`.


Review-2 resolution: a completed replacement with no submitted fix returns
scientific inconclusive too, after attempt_summary validates its row. It has no
execution.json because there is no guard to execute; explicit invalid-infra rows
are still rejected. A missing/malformed replacement row remains operational.
G16/G17 inconclusive retains the ordinary existing writer-repair route, with
review_inconclusive recorded; no new allowance or factory-bug label is added.
The easy threshold is intentionally unchanged. Bind the underlying model_router.family and model_runtime.model_effort with
their same-module constants as narrow scientific source, excluding the rest of
that runtime module, since family independence is a scientific constraint.


Implementation note: serial measurement omits factory_pool as before; switching
from serial to pooled measurement selects additional scientific executor code
and may therefore change the version even though the numeric worker count is
excluded. Endpoint/worker receipt bindings remain conservative. The retained
artifact search found no capped-submission per-attempt receipt, so row 39 remains
open for item 8. The new offline test is tests/factory/test_scientific_receipts.py;
its module docstring explicitly distinguishes saved artifacts from authored stop
metadata. No row closure is claimed by this increment.


## Item 6 implementation: isolated extension comparison (2026-10-31)

### Problem, scope and deletion

Item 5 provides scientific versions and gate receipt bindings. `extensions`
retains immutable revisions, but `retain_comparison` currently assumes both
re-evaluations wrote evidence into the live work directory. There is no producer
that prepares isolated inputs, checks a common version vector, or prevents an
invalid execution from becoming a regression. Item 6 supplies that boundary.
It supports row 9 and closes no Murphy row. Item 7 owns runner dispatch,
continuation routing and money/checkpoint integration; diagnosis stays off.

Add `factory/extension_compare.py`, a worker-owned comparison service. Its
`compare(c, number, bench, evaluate)` reads verified completed extension history,
pins the current ordered scientific version vector once, and processes entry
and outcome from their retained case/evidence copies. It never evaluates the
live candidate or hands the live context to `evaluate`. Delete the assumption
that comparison evidence must be staged in live `c.work`: extend
`retain_comparison` with explicit per-phase evidence roots (defaulting to the
existing root for compatibility). The durable append remains its existing
fsync-before-history transaction and leaves original snapshots unchanged.

### Isolated execution and receipts

The evaluator contract is explicit: `(workspace, stage) -> (passed, detail,
evidence_paths)`. Workspace contains only independent case/work paths and copied
scientific configuration (args, models, roles, seed, slot, case ID), plus the
read-only bench source path. Its card is a new dictionary containing only copied roles, never the live card.
It contains no ledger, job authority,
model runtime, publisher or live work path. The evaluator must use workspace
paths and execute under the ordinary admitted job when item 7 wires dispatch.
There is deliberately no default adapter calling `run.gN`: those functions use
global BENCH/results and would violate isolation. Item 7 must supply an isolated
worker/process adapter with separate bench results and existing shared money
admission. This API grants neither money nor a writer call. No live run here.

Use temporary working copies of each saved revision. The immutable originals
are never passed to the evaluator. Copy retained evidence into each workspace;
never hardlink or follow symlinks. Verify the case digest before and after each
evaluation and before publication. A gate that changes case bytes is rejected
as pending, not accepted as an updated comparison. Mutable evaluator detail
and configuration are independent of the live context. Cleanup temporary work
on success and failure; persisted pair evidence is copied before cleanup.

A new stage receipt binds schema, stage, scientific version, full input digest,
case digest, status, detail and content hashes of supporting local evidence.
Its digest is the snapshot stage evidence digest. Gate binding is item 5's
`gate_state.fingerprint`; stress binds case/seed/slot plus its scientific
version. The snapshot producer records all ordered stages; pending/unreached
rows have no passing receipt. Pass/fail requires nonempty retained support,
a strict bool verdict and no operational detail. Scientific inconclusive results are gate failures as specified below. `InvalidInfra`
and malformed/missing evidence become pending; other exceptions propagate
without publishing a scored comparison. The receipt reader verifies both the
receipt and every supporting byte, current version and full binding. Historical
snapshot rows with authored/opaque evidence remain historical and must be
re-evaluated rather than relabeled.

Only current, fully bound receipts can be reused. Reuse unaffected pass receipts only for the explicit reusable set below,
when their scientific version is equal; no second dependency analysis. Execute in pipeline order until the
first fail/pending; mark the remaining suffix unreached. A later formerly
passed stage that is now unreachable cannot prove no regression and progress
therefore remains pending. Both sides must have the same current version vector;
recompute it after evaluation to detect code/settings changes during the pair.
Version drift leaves the comparison pending, never relabels completed work.

A pending pair is retained with pending stage rows when versions stayed pinned;
`extensions.progress` already refuses to score it. Retry may reuse earlier
passing receipts from the newest retained comparison, while pending work is
re-executed. An incomplete original extension has no outcome and stays pending.
A completed pair is append-only and replay-safe by its digest. No extension ID,
writer round, public projection, or live gate result is advanced by comparison.

### Tests and qualification limits

Add `tests/factory/test_extension_compare.py`. Replay the saved public practice
case, saved plain/reference/invalid executions and real item-5 receipt code.
Authored evaluator orchestration controls are labeled, not called live proof.
Test common-version progress/regression/no-progress, a one-gate version change,
plumbing preservation, full evidence binding, tampered/missing evidence,
invalid-infra pending and retry, version drift, mutation of scratch case/config,
original snapshots and live candidate/card/cache byte preservation, crash before
history append and duplicate replay. Run the full prescribed suite to a unique
retained log and commit its result before fresh diff review.

Row 39 remains open: the saved public card proves time-limit/no-submission
counts, but no retained per-attempt capped-submission artifact was found in
item 5. Item 8 needs an authorized ordinary G10 calibrator run that submits a
guard before reaching its existing time/call cap, retaining the original
results.json attempt receipt, guard, execution.json, stop metadata and bound
usage/reservation settlement; replay it through G16/G17 to prove the capped
failed attempt cannot become wrong_fix. This increment launches no such run.


### Exact contracts and design-review-1 resolutions

`Workspace` is a dataclass with fields `case: Path`, `work: Path`, `bench: Path`,
`args: argparse.Namespace`, `models: dict`, `card: dict` (only roles), `seed: int`,
`factory_slot: int`, `case_id: str`. Configuration comes from the current live
context once at compare entry, deep-copied independently for each side. Versions
and fingerprints use `workspace.bench`, the current read-only source bench,
not a scratch results directory. The callback is trusted worker code, not a
sandbox against malicious Python. No live mutable paths are exposed except the
read-only source bench. Scratch directories use tempfile outside c.work; the
callback must never write the source bench or use global runner paths. The
item-7 process adapter must materialize a separate results/VM execution layout.

The shared original-snapshot producer is `snapshot(workspace,
source_generation, evaluate, previous=None, versions=None)`. `compare` calls it
for each phase, and item 7 calls the same API to produce original entry/outcome
snapshots. It returns the existing validated extension snapshot shape, never a
new history shape. `previous` is a snapshot whose evidence is already copied to
workspace.work; absence means fresh evaluation. `versions` is the pinned ordered
stage-to-SHA map, or computed at entry when omitted. Its stage receipt writer
and reader are private helpers of this API.

Every terminal stage receipt lives at `comparison-receipts/<stage>.json`, with
exact fields `schema_version` (1), `stage`, `scientific_version`,
`binding_sha256`, `case_sha256`, `status` (pass/fail), `detail` (JSON object),
`support` (relative filename-to-SHA map), `calibration_identity` (G16 identity,
otherwise null). Supporting evidence paths returned by the evaluator are a
nonempty list of canonical relative filenames under workspace.work. Reject
absolute paths, dot/parent components, symlinks and names starting `case/`,
`extension-snapshots/` or `comparison-receipts/`. Copy evidence into a private
stage namespace `comparison-support/<stage>/<original-relative-name>` before
writing the receipt. The snapshot evidence map contains the receipt plus these
copied supporting files. This prevents later stages overwriting earlier proof.
Missing/invalid JSON, support, or digest bindings refuse reuse. Detail and
support are JSON-normalized copies, not evaluator-owned references.

Reuse set is exactly gate_state.REUSABLE (G4/G5/G6/G8/G9/G13/G14/G15/G16), and
only pass receipts reuse. G1/G2/G3/G7/G10/G11/G17/stress execute fresh when a new comparison is needed. Fail reuse is not
introduced. The source is the newest retained comparison for each phase if any,
otherwise the original entry/outcome; old opaque receipts cannot reuse. Require
exact fingerprint, scientific version, case digest and every evidence byte.
G8/G9 deliberately require exact identity, with no compatible_panel fallback;
this is conservative extra work, not weaker validation. G16 additionally checks
`gate_state.calibration_binding`; add optional `bench` to that helper and
`run.calibration_identity` so this read-only calculation uses the explicit
source bench without mutating run.BENCH. The supporting evidence must include
all calibration attempt/guard/execution files used by that verdict; the adapter
owns this complete dependency enumeration just as gate_state.save's producer
does. Tampering any retained dependency refuses reuse.

Pending classification is: InvalidInfra (including InfrastructureExhausted),
non-bool verdict, non-dict/non-JSON detail, absent/malformed support, or detail
containing top-level `error`, `classification:"invalid-infra"`,
`invalid_infra:true`, or `execution_valid:false`. These
produce a pending stage, never a scored fail. `review_inconclusive:true` and
`verdict_valid:false` alone preserve the item-5 scientific gate failure when
passed is false and supporting evidence is complete; they must never accompany
a pass. They do not create a wrong_fix verdict. BudgetError (including provider
wait) and other exceptions propagate without publishing a scored pair. No
retry loop exists here: one call attempts each needed stage at most once per
side. Item 4 supplies bounded operational retries inside evaluators; item 7
must admit each new comparison under the batch money/deadline authority and
terminate holds at that bound. Pending pairs and their disk use are bounded by
those admitted attempts, not a new local scientific cap. No deployment until
item 8 verifies those integration bounds.

G2's comparison adapter re-verifies the saved search history by retrieval only:
no author search top-up, freshness repair, or writes to case/freshness.jsonl.
New retrieval responses are work evidence, bound to the saved case history.
Insufficient/malformed history and unavailable retrieval are invalid-infra,
therefore pending under item 4/7 bounds, matching GatePipeline.check. The full case
digest remains immutable, including freshness.jsonl. If an adapter mistakenly
runs the mutating normal path, its mutation is detected and comparison returns
pending with no published pair; it is an adapter error, not endless allowed
normal operation. Test both read-only G2 evaluation and mutation refusal.

For admission, add an internal evidence-root resolver in extensions. Given a
verified history and proposed snapshot, match case/stages/frontier/evidence
against the latest extension's original outcome or retained compared outcomes
(excluding source_generation as propose already does). Resolve to the matching
retained outcome evidence root, preferring the newest comparison. Otherwise use
c.work for ordinary first admission. Both verify_proposal and _save_case(entry)
use that resolver, checking root-relative symlinks and every digest. No arbitrary
root from a proposal is accepted. This copies the retained comparison outcome
into the next immutable entry without polluting live gate evidence. Keep live
case equality and authenticated current source_generation checks unchanged.
Test compare → propose → verify_proposal → admit, including replay, a changed
live case, and changed retained proof. _save_evidence takes an explicit root,
and its symlink checks are relative to that root, including the root itself.

compare and retain_comparison run only on the case's single owning worker,
never concurrently with admit/complete. read() operates on a copied context/card
inside compare, so public-projection recovery cannot mutate the live card.
Persistence adds only comparison history/evidence, never live gate results.
On code/configuration drift or scratch mutation return `pending` without an
append. Otherwise return extensions.progress for the retained pair. A completed same-version pair is sticky: return its result without evaluation.
Only absent/pending pairs may execute. Identical pending pair bytes deduplicate.

Size/cost/risk: one implementation/review increment plus the offline full suite.
Worst case is 17 stages per side; paid-stage families include stress, G2, G8/G9,
G10/G16/G17 and G11, with their existing internal invocation bounds. Exact cash
cannot be predicted from saved receipts. All re-evaluation, including version
drift, consumes the existing batch commitment; item 7 enforces admission and
records infrastructure waste where applicable, without granting extra money.
The main risk is an adapter leaking writes via runner globals: no default
adapter is supplied. This adds a roots API while removing the live-work staging
assumption; it does not claim a net line-count deletion.

Additional required tests from review 1: G16 inconclusive is fail, G16 changed
calibration binding refuses reuse, G2 read-only/mutation paths, comparison-based
next admission, and cross-stage support overwrite isolation. All blockers were
accepted; docs/reviews/stream-d-compare-design-1.md preserves the final report.


### Design-review-2 resolutions (all accepted)

Re-judge the before and after copies with today's rules, so an extension is
counted only when the case got further. Before allocating scratch or invoking
an evaluator, compare examines the original pair then retained pairs in append
order for a non-pending progress() result at the pinned versions. The first
such pair is authoritative and returned unchanged. Original and retained bytes
are verified through extensions.read first. This forbids stochastic rerolls;
propose likewise selects the first non-pending matching pair, falling back to
the latest pending pair only if no scored pair exists. An old opaque same-version
pair is authoritative only if its terminal stage receipts verify under this
module's reader; otherwise it needs reconstruction. Tests cover repeated compare
and prior pending → scored → subsequent compare with zero evaluator calls.

Stress's comparison adapter is a read-only review of the saved candidate:
attacker searches are directed to workspace.work, retained as support, never
appended to case/freshness.jsonl. G2 counts the saved case's builder/attacker
history, not newly authored comparison searches. No original stress writer or
repair loop is called. BudgetError('freshness_unresolved') is recognized only
for stress and becomes pending invalid evidence; other BudgetError propagates.
This does not grant a retry; item 7 bounds any retry/retirement at batch authority.
Test read-only stress evidence, attempted case mutation and freshness_unresolved.

Like GatePipeline.check, CaseProblem becomes a scientific fail with
{'problems': [str(error)]}. Save that exception observation as a local supporting
JSON file before producing its fail receipt. classification:'invalid-infra'
always means pending, even when a bool verdict is supplied. The existing
review_inconclusive failure does count as a gate regression after a baseline
pass in this comparison API: it cannot establish the required retention of a
pass. It still never labels a submitted fix wrong, changes writer feedback or
creates a factory-bug claim. Item 7 uses the ordinary independent-review rule
for substantive disagreement before retirement.

The stress binding is digest({'stage':'stress', 'scientific_version':version,
'case_sha256':case_digest, 'seed':workspace.seed,
'slot':workspace.factory_slot}); digest is extensions.digest's canonical JSON.
retain_comparison(c, number, entry, outcome, *, roots=None) takes optional
{'entry': Path, 'outcome': Path}; omitted roots use c.work as before. Root input
is worker-local, never supplied by public proposal/model output. All retained
proofs are verified before append.

Item 7 produces original snapshots by calling snapshot with a Workspace whose
case/work are the ordinary owning worker's current case/work after admitted
execution, or by copying the returned snapshot's named evidence from scratch
into c.work before admit/complete. The former allows the shared writer to emit
receipts directly at the paths current admission expects; it remains item 7's
responsibility to use a non-mutating evaluator. compare itself always creates
independent scratch workspaces outside the live work tree.


Implementation clarification: propose prefers the first scored retained
comparison before the original pair. If any retained comparison matches the
vector, even pending, the original cannot be used as a fallback. This matters when an opaque original had
current version labels but could not prove them: compare reconstructs it, and
admission must consume that verified reconstruction. compare never produces a
replacement for a valid already-scored original. Scratch card output fields
(such as plain_app_broke) may be written by evaluators; only args, models and
roles are scientific configuration and must remain unchanged. No scratch card
field is copied into the live card.


### Diff-review-1 resolution: portable scientific receipts and shared selection

Blocker 1 and all nits accepted. This paragraph supersedes the earlier use of
full gate_state.fingerprint in comparison receipts. It also explicitly supersedes
all earlier item-6 schema-1 field lists, "Require exact fingerprint" rules and
stress-binding formulas containing seed/slot, including those in the isolated
execution, exact-contracts and design-review-2 sections. The schema-2 field list
and binding in this final resolution are authoritative. Full live-run cache inputs
still bind worker count and slot conservatively; comparison uses the scientific
partition from item 5. Its binding is now exactly
`extensions.digest({stage, scientific_version, case_sha256})` for every stage.
The complete receipt and all supporting bytes remain hashed into the snapshot.
Schema 2 adds `execution: {seed, slot, bench_workers, concurrent_roles,
slot_environment}` for immutable provenance. Those recorded values do not need
to match today's worker. Changing a seed cannot reroll an already-scored sample.
No production item-6 receipts exist yet; schema-1 prototype originals are opaque
and reconstruct through the same guarded path, never relabeled in place.

G16's additional calibration identity remains checked after removing only seed
and slot; these stay in receipt execution provenance. All other identity fields,
including model/effort, scientific code and limits, remain exact. A change of
scientific version still requires comparison at the new common version. As in
item 5, selecting pooled rather than serial execution may add scientific executor
code to the inventory and therefore change versions; numeric worker/concurrency
or slot changes that keep the scientific vector equal cannot revoke the pair.

`extensions.comparison_pair(row, versions)` is the single selector used by both
compare and propose: matching retained reconstructions take precedence over the
original, the first scored matching pair wins, otherwise the latest pending
pair is returned. No matching vector returns None. compare validates that one
selected pair's receipts/support before returning its score. A scored retained
reconstruction that cannot be verified returns pending without rerolling or
appending a rival score. An opaque original may still be reconstructed. Item 7
must call compare before propose; propose's docstring now states that it checks
state and retained bytes, not the scientific truth of opaque originals.
Item 7 must bound even an unverifiable retained score under the existing batch
money/deadline authority: recover infrastructure evidence where possible and
account its waste normally, otherwise retire at the bound. It must never retry
this pending state indefinitely or discard a score to obtain a new verdict.

Only malformed returned results/evidence are caught as pending. ValueError,
TypeError and FileNotFoundError raised by evaluator code itself propagate with
no comparison append. Tests now cover changed workers, concurrency, slot, slot
environment and seed after a scored pair, asserting zero evaluator calls,
byte-identical history and the same admission outcome. G16 receipt validation
also survives moved execution provenance, and support-copy assertions include
G5 as well as stress. The final diff report and responses are retained in
`docs/reviews/stream-d-compare-diff-1.md`.


## Item 7 first increment: admitted extension writer continuation (2026-10-31)

### Problem and review boundary

An extension's initial writer reservation bypasses the ordinary diagnosis
threshold in `run.pending_call`, but its interrupted invocation resumes without
`extension_proposal` and is treated as ordinary work. An already admitted
extension can consequently stop at the same ordinary threshold that led to its
diagnosis. The extension history already binds one writer operation and round;
resuming must use that authority, without admitting a second extension.

This is the first coherent part of item 7, not completion of continuation
routing. It changes only the writer invocation admission seam. It does not wire
new dispatch into the ordinary launcher, remove legacy recovery allowances, or
turn diagnosis on. The founder decision supersedes the older diagnosis-off
launch discussion above: no real cases before the helper is fully on.

### Change and deletion

Add `extensions.writer_continuation(c, receipt, name) -> bool`, called by
`run.pending_call` for writers without a fresh extension proposal, after `resume_provider_wait` and
`job_authority.for_case` checks and before acquiring a provider lease. It
loads and validates the private extension history using the existing `read`
path. With no active extension and no receipt extension marker it returns false
and preserves ordinary admission. Any extension marker without an active
matching history refuses. With an active extension it requires a schema-v2,
pending writer receipt whose integer extension ID, round, operation ID and
call name match that history. If prior lease and invocation are strings, the ledger reservation must match
that invocation, the history's writer operation and builder call name. If both
are None, accept only through `run.provider_continuation(c, receipt, 'writer')`;
reuse its settled wait archive proof. Mixed null/string pairs refuse.
Missing, completed, foreign or mismatched receipts
refuse as `extension_reservation_mismatch` before a lease or invocation.

Only that verified continuation bypasses the ordinary case threshold. It still
uses `job_authority.for_case`, the existing router lease and
`budget.reserve_invocation` with B's current cumulative commitment and deadline.
It keeps the writer operation ID, extension ID and author round; a new provider
attempt receives a new lease/invocation and spends normally. Recheck the binding
immediately before reservation, as fresh extension proposals already do. An
active extension cannot admit another ordinary writer operation. No second
spend ledger, checkpoint schema, allowance, launch mode or environment switch.
Remove the ordinary-threshold check only for this verified continuation;
keep ordinary writer checks and all legacy launch behavior. No tests are deleted.

The helper does not reconstruct a missing attack receipt: a crash between
extension admission and receipt publication must remain fail-closed until the
package router persists/restores writer intent. Completed writer validation,
including unchanged_repair, remains the caller's existing responsibility; this
seam refuses completed receipts rather than invoking them again.

### Tests and Murphy rows

Extend `tests/factory/test_stream_d_admission.py`, using its saved public
practice case and collected 5813be ledger. Test a fresh extension admission,
interrupted/pending receipt, and retry past the ordinary threshold with the same
operation/round/extension and unchanged history length. Test refusal at B's
cumulative commitment and with stale authority. Exercise missing history,
completed history/receipt, wrong extension/round/operation/call/lease/invocation,
including boolean IDs, before provider acquisition. Replay a settled archived
provider wait positively and refuse missing archives or absent matching
wait_settlements entries. These direct pending_call replays do not exercise
launcher round-limit routing, which remains part of the next increment.
No model spend: local replays only, within this reviewable increment. Ordinary writer exhaustion
must still refuse. These are local control-flow replays with authored model
execution and stage evidence, not live qualification. Run the full suite and
retain its unique log and result record. Supports Murphy row 9; closes no row.

### Remaining item 7 work and item 4 seam

The next increment must route validated diagnosis outcomes through the ordinary
B launch/checkpoint path, advance the old completed writer receipt at extension
admission, and join the writer, unfinished stress work, freshness retrieval and
one gate traversal into the durable extension package. It must finish/comparison-
check outcomes, support factory-bug hold/resume and retirement, and remove legacy
recovery allowances only on the qualified ordinary path. Reuse lane 1's current
freshness/stress entry points; this increment introduces no dependency or new
interface for item 4. Item 8 still requires integrated retained-artifact and
authorized live A/B/E qualification, crash/wait/money coverage, review, and only
then the diagnosis switch-on. Row 9 stays open.

### Item 7 receipt publication recovery increment

The next prerequisite is specified in `stream-d-extension-receipt-routing.md`:
retain the admitted writer intent before history publication and select/recover
its attack receipt without restarting completed work. This is not launcher or
package activation. The selector has no production caller; same-round stress
returns no writer work and must be separately validated by package routing.
The package must also fix the existing validated-writer binding hash update and
preserve the admitted round-limit/release fields on pending replay. All remaining
item 7 and item 8 qualification obligations above remain open; no row closes.

## Item 8: live qualification and switch-on

Updated offline on 2026-11-02. The detailed evidence inventory, live order,
per-run ceilings and sized gaps are in
[stream-d-item8-offline-preparation.md](stream-d-item8-offline-preparation.md).
That amendment supersedes stale prerequisite status, scenarios 5/6 packing,
ready-child ordering and timing/affordability gates below;
historical item-7 increment notes later in this document are not readiness claims.

The founder approved **USD 100 all-in within existing Claude/Codex subscription
limits**, separate from the USD 25 stream-B plumbing practice; OpenRouter may use
only existing credit, with no top-ups (authority in batch-practice-manifest.md).
This task is DESIGN ONLY: no code, model call, provider query, worker creation,
deployment or spend is authorized now. The cap does not guarantee qualification.

E's outer-wall rows are closed for their offline scope. Escaped non-isolated
sessions (new-isolation-settlement-1), actual CLI cancellation/settlement and
verified cloud cleanup/billing exposure remain prerequisites; local cleanup is
not a provider deletion receipt.

### Prerequisites and shared practice infrastructure

- [ ] close new-stream-d-current-comparison-1 with a real decision → extension → subsequent_entry comparison exhaustion → factory-bug hold/resume chain on retained artifacts

Use `docs/reports/stream-b-activation-practice-plan-20261031.md` as the launch,
identity, publication, collection and cleanup contract. B must first finish its
reviewed practice and resolve its listed bootstrap, authenticated checkpoint,
legacy ownership, release installation, router transport, money admission and
independent deletion blockers. Read its subsequent evidence, not just the old
preparation claims. Item 7 must be merged and pass its fresh diff/full suite;
item 8 cannot invent missing continuation adapters. Lane 1's public-match,
scored-blocking-stress and post-extension factory-bug
return slices are accepted (c3ee6d9); land11 merge evidence and lane 2's remaining
rejected-writer/partial-entry/all-outcomes work are still required. A/E must qualify
invocation bounds, process cancellation and settlement on selected routes.
Preserve the closed offline scope of E's outer-wall tests without claiming actual
provider/escaped-session cleanup. B must qualify the post-migration store under
`new-single-path-1`; historical
inventory shapes do not establish current restore eligibility.

Use sequential throwaway workers, concurrency one, on the control VM and R2;
no Mac service participates. One throwaway worker described B's plumbing practice,
not a founder restriction on the number of workers in this qualification.
Every worker is created through the normal single launch path, including resumes
from authenticated checkpoints. Collect and publish its durable checkpoint,
settle or conservatively retain its outstanding usage, delete it, and verify its
provider deletion receipt and complete inventory absence before creating the next.
Uncertain creation or deletion blocks the next creation; controller restart must
reconcile the same operation rather than duplicate it. Independent pre-armed
control-VM cleanup covers delayed creation and survives controller failure.
B owes this ordinary launch/retirement evidence, not support for reusing a worker
across launches, batches or releases. Losing the VM must not lose operation IDs,
account routing, ownership, receipts, counters or cumulative money authority.

Use immutable release/batch pairs in this fixed order: alpha (scenarios 1–4,
diagnosis/replacement off), beta-fault (scenario 5 fault and diagnosis), beta-fixed
(scenario 5 child then fixed original, then scenario 7 and initial scenario 6), beta-plumbing (scenario 6 plumbing replay),
beta-science-fault (scenario 6 one-gate comparison infrastructure fault) and
beta-science-fixed (the same scientific vector, hashed transport fix/resume). All beta releases have diagnosis and
replacement enabled only under separately approved qualification authority; the
faulty and fixed releases are both included. Beta-fixed removes scenario 5's injected fault;
scenario 7 and initial scenario 6 never run under beta-fault. The later 6d uses the separately reviewed comparison fault and 6e diagnoses its
retained pending generation, both on beta-science-fault. Scenario 5 first publishes the faulted pending generation on 5a, then restores
it on 5b for real diagnosis under beta-fault. Its queued replacement
is carried to beta-fixed alongside the original via B's reviewed carry-over,
including its own $7.50 allocation and prior spend/reservations; it is not launched
under the fault or given fresh authority. B's carry-over scope must cover both. Each release change needs its
own batch because holder bindings are immutable. All beta batches together share
one $50 NEW-spend envelope, not $50 each; alpha has $40 NEW spend. Each transition uses authenticated checkpoint carry-over after verified deletion;
worker identity changes while ownership and cumulative accounting remain intact.
On beta-fixed run the carried 5c child before 5d original resume, and ready
7b/6b children before their 7a/6a originals, under normal replacement priority.
The reviewed O3 guard must keep 5's child release-ineligible while queued under
beta-fault and allow only 5b's diagnosis restore there; without that guard, the
four-slot packing is infeasible. Run scenario 7 to terminal collection before
admitting scenario 6 at all.
Its worker deletion is verified and usage settled or conservatively retained first.
Scenario 6 then completes fixed-release work and its plumbing/science replays
without an intervening scenario. Finish its replacement on beta-fixed (terminal
collection under its bound, not necessarily sealing); only the original carries
forward through B's reviewed carry-over to the plumbing/science-fault/science-fixed
releases. Exact six-slot packing and the retained X2→comparison exhaustion→later factory_bug diagnosis→comparison
resume exam are in the offline-preparation amendment; no extra slots or money.

For each admitted candidate let S be its authenticated carried-in settled lifetime
spend, and E be its incremental scenario allocation. A root's commitment is S+E,
never E alone. Alpha uses table caps for E. Beta splits E evenly between root and
one fresh replacement: root allocations $7.50/$12.50/$5, replacement allocations
the same. Root diagnosis, extension, resumes and version replays share that root
allocation. For a fresh replacement S=0. The current template copying would copy
S+E from the root and overauthorize the fresh child: **B must add and review an
authenticated practice admission clamp to the child's own S+E**. Never copy the
root's historic spend as fresh replacement authority. No scenario can acquire
another allocation on a new batch or release.

Batch cumulative authority equals the sum of admitted carried-in baselines plus
the still-available new-spend allocation, with earlier new spend carried in rather
than regranted. The concrete manifest must show each S, current settled total,
outstanding reservations, remaining scenario allocation and job commitment;
beta's remaining allowance is $50 minus prior beta incremental charges/reserves.
B must independently verify this across retired releases before issuing authority
for the next. Existing lifetime ledgers are never reset or subtracted from worker
accounting. Incremental spend = settled lifetime total minus authenticated S, and that
amount plus pending incremental reservations is checked against this approval;
S is never ignored in cumulative worker admission. Ordinary exhaustion remains exhausted:
S+E allows work only through admitted extension/factory-bug authority, not a new
ordinary writer allowance. If B's bootstrap/carry-over cannot represent this,
all candidate scenarios are infeasible and require a revised founder-approved plan.

The current replacement policy has only enabled/schema, no generation bound.
**B's qualification-only admission stop is an unconditional prerequisite**: prove
with saved artifacts that only one replacement per scenario can be admitted,
a child exhausting cannot start r2, replay cannot duplicate admission, inherited
S cannot inflate child authority, and release transitions cannot regrant E.
Keep production chain semantics unchanged. Only one scenario's jobs are admitted
at a time through those reviewed controls, never an invented policy field.
Alpha stress exhaustion records pending evidence; beta exercises real dispatch.

Prefer approved free/cheap capped routes within each role's required family.
A route change cannot stand in for a Claude/account-2 acceptance check. Pin actual
request/token/tool maxima, model prices and job commitments in the run manifest;
validate next-call reservations fit each scenario before any dispatch. Bare Claude remains $50; 5.5 small/medium reserve $10/$15.
Bounded 4.5 compact/small profiles now reserve $3/$5. A/D/B must qualify compatible
immutable role/model bindings and useful Linux writer/strong-calibrator/diagnosis
work before adopting them; never relabel an old candidate to fit a cap. Target
at most $5 per invocation (smaller when less remains), fitting both honest
spent+pending+next-call and beta's root half-commitment. Strong G10 can use
Anthropic/OpenAI only; Codex/OpenAI still lacks an enforced maximum. Other-family
cheap routes cannot replace it. A must demonstrate the chosen profile permits a
submitted guard and useful writing within the existing scientific caps. The observed $15.05 writer call shows that success at $5 is NOT
established. The prerequisite table below records which scenarios depend on this evidence. If infeasible, revise the cost proposal
for fresh founder approval; never lower a reported maximum without enforcement. Paid charges, subscription list equivalents,
infrastructure waste and unknown reserved usage all count against the bounds.
No extra case-money allowance and no reclaimed headroom from waste relabeling.

Record public account label, invocation/lease IDs, UTC window and admitted route.
Authenticated account-2 preflight plus founder-confirmed private usage correlation
must show actual worker usage on account 2, with builder traffic excluded or
identifiably correlated. Retain only the public confirmation, no emails, tokens
or token fingerprints. Account 1 is eligible only under real provider-reported
account-2 rate exhaustion. Missing credentials, occupancy and outages cannot
unlock it. Observe a natural 2 -> 1 -> 2 transition if it occurs within the cap;
otherwise record it as unexercised, retain activation hold for that acceptance
criterion and seek separately reviewed qualification, never fake rate evidence.

### Candidate admission is a hard prerequisite

B owns the reviewed bootstrap/import and cross-release carry-over work, including
`new-batch-service-4`. Its preparation found no eligible authenticated checkpoint;
the legacy a869de archive with hash d93308338261cf32d468ec21ca5e619eea06b6585451a2cf51b644e2102ba9c8
is explicitly NOT an input. B must supply authenticated, decryptable, release-bound
candidate generations through the ordinary launch path: (a) writer/stress case,
(b) G10-ready case with executable guard environment, (c) complete-stress near-pass
exhausted case, (d) nonconverging exhausted case. The evidence manifest must name
case ID, archive hash, owner and publication ACK, source generation, eligible
release/batch binding, gate/stress receipts and cumulative settled spend for each.
No such inputs are asserted to exist here. Every candidate scenario depends on this bootstrap; see the table below. Creating cases from scratch is excluded:
historical $51–$52 cases do not fit these caps. If bootstrap cannot admit existing
inputs, request a new design/budget; never forge binding or spend to discover an
input under this approval. Scenario 5 ALWAYS needs B's reviewed cross-release
carry-over, because removing the controlled infrastructure fault changes release.

### Candidate/role map and current launch blockers

Slots below are one-based in rotation-3writers.json; never silently change a saved
candidate's role binding. B must supply eligible inputs in these slots, with
separate immutable copies and case IDs for different jobs. Bootstrap must bind the
batch/job-derived case ID under its reviewed import contract, preserving lineage,
ledger and authenticated artifacts, not editing an old card into eligibility.

| Scenarios | Candidate and required role families | Prerequisites still blocking launch |
| --- | --- | --- |
| 1–3 | separate copies of (a), slot 1: Anthropic writer, MiniMax stress, DeepSeek reviewer | A small Claude writer profile; approved free-route maxima; B bootstrap, sequential launch/deletion evidence and cumulative admission |
| 4 | (b), slot 4: Anthropic strong calibrator; OpenAI reviewer for G16/G17 | A small Claude G10 profile AND an enforced OpenAI maximum for G16/G17; B eligible G10 input/lifecycle/admission |
| 5 | infrastructure-fault copy of (a), slot 1: DeepSeek diagnosis, Anthropic writer | completed item-7 joins; A profile/maxima; B bootstrap, cross-release carry-over, verified deletion and practice admission clamp |
| 6 | (c), slot 6: MiniMax writer, DeepSeek stress, Anthropic diagnosis, OpenAI strong calibrator | A small Claude diagnosis profile AND enforced OpenAI maximum for gate traversal; B near-pass input, cross-release carry-over and all lifecycle/admission prerequisites; item 7 |
| 7 | (d), slot 1: DeepSeek diagnosis | A small Claude writer profile for the slot-1 replacement; B nonconverging input and all lifecycle/admission prerequisites; item 7; approved equivalent-review route maxima |

A additionally owns enforced OpenAI invocation maxima and cancellation/unknown-usage
settlement acceptance, or scenarios 4/6 remain blocked: a cheap other-family model
cannot satisfy those roles. All other selected/free routes also require honest
enforced maxima. Every row above is currently blocked; these are qualification dependencies, not
claims that infrastructure or eligible case fixtures already exist.

### Scenarios, bounds and acceptance evidence

Each figure is an incremental NEW model-money cap for that scenario, including replay,
settlement and any replacement/diagnosis it launches. There is no retry top-up.
All jobs also share the absolute deadline and USD 90 incremental model envelope;
lifetime commitments include the authenticated baselines as specified above. Reserve
USD 10 total for N sequential worker lifecycles and shared storage/egress.
The planning allocation allows at most N=20 creations, including recovery,
replacement and release-replay workers, at USD 0.40 per lifecycle plus USD 2
shared storage/egress/control-VM incremental exposure: I(N) = 0.40*N + 2,
so I(20) = USD 10 and total = **90 + 10 = USD 100**. These are admission
ceilings, not verified provider quotes. Each lifecycle allocation includes creation,
boot, release installation, execution and conservative delayed-deletion exposure,
including billing minimums and per-worker storage. The static USD 0.036/hour
estimate in B's preparation is not a current price or sufficient billing proof.
Before approval, B/E must verify current prices and reserve the full conservative
cost for every planned lifecycle plus shared costs; refuse launch if it exceeds
these ceilings. Do not divide one worker's cost by N or reset infrastructure spend
at a release change. Unattributed/unknown charges stay reserved.

The manifest assigns worker slots by scenario: 1=3 (initial plus two restores),
2=2 (timeout and restore), 3=1 (in-process retrieval/repair), 4=2 (two guard
attempts), 5=4 (fault/pending, actual diagnosis restore, fixed child, fixed
original; idempotence is offline), 6=6 (replacement, initial diagnosis plus extension together, next diagnosis plus
plumbing check, science-fault comparison, later real factory_bug diagnosis,
fixed comparison resume; idempotence check is offline), 7=2 (retire/boundary replay and replacement). Slots are ceilings,
not a claim these paths finish in that many launches; every additional launch,
including provider handoff or retry, consumes a slot. If the manifest needs more
than its assigned slots, revise the plan before approval; runtime exhaustion
leaves the scenario unproved and stops admissions, never bypasses deletion.
Per-scenario model plus worker ceilings are respectively USD 11.20, 10.80, 5.40,
15.80, 16.60, 27.40 and 10.80 (USD 98 total); the shared USD 2 makes USD 100.
No unused slot buys extra model authority.
Scenario 6 must continue its initial diagnosis into the first extension in the
same worker. The next diagnosis and plumbing check share one worker, freeing the slot
for actual diagnosis AFTER comparison exhaustion; no spare recovery slot remains; an extra required launch exceeds its cap. Scenario 2 injects both call timeouts on its first worker, retaining each
attempt's partial/pending evidence, then restores unfinished coverage on the
second. Scenario 4 runs G16/G17 against each retained attempt in that attempt's
worker before deletion. If the reviewed implementation cannot run that packing,
revise slots and costs before approval rather than omit an observation.

| Scenario | Model cap | Required live observation and retained evidence |
| --- | ---: | --- |
| 1. Writer interruption and provider wait | $10 | On an authenticated real candidate, interrupt a writer after durable intent and again at completed-output checkpoint using controlled process faults. Resume through B, with a genuine provider wait if available. Same round/operation, findings and output digests survive; completed writer is not bought twice. Save original/restore archives, intent/completion receipts, lease/call IDs, provider-wait receipt, usage events and settled reservations. Qualifies item 2/rows 10–11 beyond saved-artifact tests. |
| 2. Stress timeout and diagnostic exhaustion | $10 | Let a real stress call hit its configured time limit after one retained category; also expire before a category answer. Save scored-or-pending aggregate, category state, exact partial bytes/digests, stop/diagnostic status and publication generation/ACK. Restore through ordinary launch, finish only unfinished coverage under the same operation; an exhausted diagnostic goes to pending diagnosis without a writer verdict or new allowance. Includes a controlled publication interruption and control-service restart. Tests row 13's live durability; recovery joins scenario 5. |
| 3. Retrieval and malformed output | $5 | Induce a real transport timeout at the runner retrieval boundary, then recover; preserve retained HTTP/search receipts. Exercise schema repair of a retained malformed answer without inventing scientific decisions, then equivalent-route exhaustion if needed using explicitly labeled injected output at the live boundary. Record exact injection, real invocation/receipt chain, retry counters, no writer-round consumption, and no false G2 clearance. Items 4/rows 12 and 15; injected content is not represented as naturally observed provider output. |
| 4. G10 capped submitted guard and no-submission | $15 | Run an authorized ordinary G10 calibrator on a real saved case which submits a guard BEFORE reaching its existing time/call cap AND then ends with the cap stop_reason. Do not weaken a cap, gate or scientific threshold to force success. Also retain a capped no-submission attempt. Keep original results.json attempt, guard bytes, execution.json, stop_reason/capped metadata, transcripts, lease/usage events, reservation and final settlement. Replay through real G16/G17: capped failed or absent guard stays inconclusive/pending, never demonstrated wrong_fix. A submitted guard is executed/scored under ordinary rules. If no natural cap-with-guard appears within $15, row 39 stays open; no fabricated receipt substitutes. |
| 5. Diagnosis: factory bug | $15 | Exhaust an admitted case with a controlled, documented infrastructure fault, queue exactly one eligible replacement immediately without waiting for diagnosis, then obtain the real diagnosis agent's factory_bug decision and independent review required by the implementation. Remove the injected fault via reviewed release, resume original through B's checkpoint adapter, preserve owner/history and charge waste once. Prove original/replacement both remain eligible if they seal, and replay cannot duplicate replacement or resume; preserve cap counters. B cross-release/cross-batch hold support is a mandatory prerequisite. Ledger event IDs and per-invocation settlement entries must prove waste is charged once. No forged verdict. |
| 6. Diagnosis: extension | $25 | Use a saved near-pass real candidate with complete stress and an ordinary rounds/money exhaustion trigger. Obtain actual diagnosis proposing extension; replacement admission precedes diagnosis/extension. Admit one writer + stress + gate traversal with isolated common-version before/after receipts. Prove progress and no regression, one extension counter increment, replay idempotence (offline, retained artifacts), cumulative commitment enforcement and no reopening of exhausted ordinary money. Its $25 cap also includes plumbing replay, one-gate scientific comparison exhaustion, actual factory_bug diagnosis and fixed-release return to that comparison; see the exact six-slot amendment. Preserve rejection evidence if either diagnosis disagrees; the scenario remains unproved instead of overriding it. |
| 7. Diagnosis: retire and limit refusal | $10 | Obtain actual retire diagnosis on a real nonconverging exhausted candidate. Verify terminal collection, settled usage and replacement semantics without resurrecting original. Replay real retained lifetime counters at five extensions/three factory-bug resumes and at batch money/deadline limits: no further paid call; invalid comparisons remain pending and never progress. If these boundary states are replay inputs, label them rather than claiming five paid extensions occurred. |

The $90 sum includes every model call needed for the scenarios, independent
review and replacements. Do not let an automatically queued replacement consume
unbounded work: its job commitment is inside that scenario's cap, and when money
or deadline is unavailable it stays queued/terminal per reviewed policy. Failure
to reach a desired diagnosis or submitted capped guard is a failed qualification,
not authority to coerce the agent or buy more attempts. Account-2 evidence rides
on the already-needed Claude writer call in scenario 1 and strong-calibrator call in scenario 4, using separate correlated windows, never an extra paid probe.

Timing feasibility is now an explicit BLOCKER O9 in the offline-preparation
amendment. The old 70-minute execution / eight-hour total and two-hour worker
limits are known insufficient, not an executable deadline. Scenario 4 means
actual unchanged 30-minute time_limit attempts, not a smaller call/zero-token/
money cap. Two alone need at least 60 minutes plus G16/G17/reset/judging.
Uncached serial G10 can allocate 180 calibration minutes before other work.

Before ANY live admission, re-derive all 20 root/child per-slot execution and
collection windows, lifecycle/billing bounds and the aggregate absolute deadline
from pinned caps and measured serial overhead. Children get separate windows
and cannot consume the original's later slots. Longer live deadlines/lifetimes
need a fresh timing review and founder sign-off; this amendment supplies none.
If normal execution and cleanup cannot fit $0.40 per lifecycle / $100 overall,
return an infeasible plan for revised approval, never truncate scientific caps.

Scenario 6 also needs a BEFORE-LAUNCH sum of all planned honest invocation
maxima through 6f to fit the original's shared $12.50, independently of its
child's $12.50. Current Codex maxima/reuse/call-count gaps make that check fail;
it is not an authorized late-stranding experiment. The runtime next-call checks
remain necessary but cannot stand in for full-critical-path feasibility.

The exact release-specific CLI commands, authenticated input generation hashes,
route profiles, job reservations, absolute deadline, fault injection points and
cleanup commands belong in a concrete run manifest reviewed before execution.
Missing any of them blocks launch. This design is not an executable manifest.
Scenario 1's genuine provider-wait branch and account fallback must be explicitly
marked incomplete when unavailable; saved-artifact replay complements them but
cannot be called a live observation. Search the final release for leftover old
caps/allowances and validate intended exceptions against item 3 before launch.

### Closure and switch-on

Sequential workers change the transport of evidence, not any closure criterion.
Scenario 1 must compare the same writer operation across different worker IDs;
scenario 2 must recover the published partial stress generation on its successor;
scenario 3 must retain the real invocation/retrieval chain; scenario 4 must retain
both distinct capped attempts and real G16/G17 results. Scenarios 5–7 must prove
replacement admission before diagnosis, preserve lifetime counters and settled
plus reserved spend across every deletion/relaunch, and retain original and
replacement lineage independently. Scenario 6 must compare gate receipts across
the fixed/plumbing/science releases even though their workers differ. A restart
on the same worker can qualify controller idempotence, but cannot substitute for
the required checkpoint restores. Row 9 still needs all integrated outcomes and
row 39 still needs natural capped-submission evidence; none closes merely from
using sequential workers.

Rows 9 and 39 stay open now. Row 9 closes only after scenarios 5–7 prove the
integrated outcomes, replacement priority, money/counter bounds and ordinary
checkpoint resume. Row 39 closes only with scenario 4's genuine capped-submission
and no-submission evidence plus usage settlement and G16/G17 replay tests.
Items 2–5's already-closed rows 8, 10, 11, 12, 15 and 21 retain their saved-artifact
scope; add the live evidence above for transport/crash, actual cap enforcement,
collection, settlement and per-gate version behavior. Within scenario 6 alone, change a plumbing-only release and then only G4's
scientific version. Its real subsequent_entry pair attempts exhaust under
the reviewed transport fault; the next worker obtains actual factory_bug and
retains its hold, then a fixed-release worker returns via B to the
same comparison after a hashed plumbing fix with unchanged scientific vector.
Unchanged passes survive, only affected stages rerun, invalid work stays unscored
and no writer starts before the comparison/progress decision. The new Murphy
row stays open until the retained 6a/6c/6d/6e/6f chain proves it.
Row 13 report closure does not waive its live timeout/diagnosis scenario.

Archive the encrypted input/output generations and public evidence manifest,
checksums, invocation receipts, final money state, publication ACK/current pointer,
controller restart trace and authoritative provider deletion receipt plus complete
inventory absence. Retain the full suite log and real-artifact regression tests
for the observed artifacts. Fresh goldfish reviews the resulting diff and evidence;
any blocker needs a fix and another fresh reviewer. No row closes on a plan,
synthetic verdict, incomplete scenario or merely empty worker inventory.

`factory/batch_service.py:DIAGNOSIS_ENABLED` remains False in normal releases.
Qualification needs an explicitly reviewed, separately approved isolated practice
release that sets it True only for this authorized qualification policy, after
all prerequisites above. The normal policy remains disabled. That temporary
release is necessary to test real dispatch; do not monkeypatch the production
service or set an undocumented environment variable. Disable its admissions on
failure and finish collection/settlement/verified cleanup before reusing authority.

After all scenario acceptance checks, B/A/E evidence, full suite and fresh diff
review pass, prepare a small separately reviewed activation commit changing the
constant to True, pin its immutable release/closure and deploy through B's normal
release/policy process with founder approval of the live batch money/deadline.
The record must link the item-8 evidence and prove no pending usage, ownership,
publication or cleanup incident. Missing account identity/fallback acceptance,
unexercised outcomes or cap evidence keeps switch-on blocked. Rollback is a newly pinned reviewed release with DIAGNOSIS_ENABLED=False,
rolled on through B's checkpoint path; stop new admissions while deploying it.
Then plan() returns diagnosis_unavailable and dispatch stops diagnosis_pending,
preserving queued entries, operations and receipts for collection; never erase paid work or kill ownership
by toggling a flag. This plan flips no flag and spends nothing.
### Item 7 launcher recovery increment

`stream-d-launch-recovery.md` wires the retained writer selector into verified
close-to-passing diagnosis replay at ordinary launcher entry. It recovers the
admitted writer receipt before publishing the stopped card and before ordinary
author/gate work. Execution still stops comparison-pending; no new extension
is admitted and diagnosis remains disabled. The full package, launcher execution
and round-limit routing, all diagnosis outcome execution, and qualified-path
legacy allowance removal remain before item 8. Lane 1 item 4 is integrated by
merging 6f30f8d. No Murphy row closes.


## Cross-batch implementation addendum reference

[batch-carry-over.md](batch-carry-over.md) specifies the B transfer and D resume
admission increment under review. It preserves the existing meaning of same
owner: continuing case identity, with a new B reservation for a new batch.
Manifest root maps remain roots only; imported derived jobs are authenticated
through the separate pinned carry_from map and retained derivations, never
inserted as mutable roots. Existing lifetime history and empty causal-attribution
restrictions remain unchanged. The fourth distinct factory-bug admission stops
unscored as `retired_factory_bug_limit`, with the retained history count 3.
The addendum replaces the unspecified B integration prerequisite when implemented
and reviewed; activation and real-artifact Murphy closure remain separate gates.


### Item 7 remaining-increment checklist (lane 2, 2026-10-31)

Sizes include implementation, tests and fresh design/diff review. Receipt
admission/recovery is done. Each line is one intended reviewable increment.

- [x] **Admitted launcher execution and round routing — large.** Route
  authenticated active extensions into the existing writer/stress loop; enforce
  one admitted round across pending/completed/validated replay, preserve receipt
  authority, and stop before gate/package completion.
- [x] **Package increment 1: retained freshness recovery — small.** Preserve the
  completed-review fallback through diagnosis publication; test valid reuse and
  stale/partial refusal. Design: `stream-d-package-freshness.md`.
- [ ] **Package increment 2: stress/gate/outcome completion — large.** Join unfinished
  stress recovery to one gate traversal; retain entry/outcome receipts, complete
  history, and compare current versions without rerolling or extra author work.
- [ ] **All diagnosis outcomes — large.** Admit proposed extensions after comparison;
  execute factory-bug hold/fix/resume (three maximum), extension progress/limit
  decisions (five maximum), and retirement through ordinary launch/checkpoints.
- [x] **Qualified-path legacy allowance deletion — medium.** Remove remaining
  recovery/final-fix/diagnostic allowance branches from the qualified path; prove
  only cumulative batch money/deadline and scientific round rules govern it.

Item 8 remains separate: integrated retained-artifact and authorized live A/B/E
qualification, crash/wait/money coverage, and activation. No row closes by a
checklist entry alone. The current design is `stream-d-admitted-execution.md`.


The admitted-execution implementation, full offline suite and fresh diff review
are complete. Reviews: stream-d-admitted-execution-design-1.md, design-2.md,
diff-1.md and diff-2.md under docs/reviews (all with the same topic prefix). No Murphy row closes. The next
increment is the complete writer/stress/gate package above; activation stays off.


Package increment 1 is complete at c68b819: diagnosis replay preserves the
completed freshness-review pointer, with existing validation still required for
reuse. Full suite: 160 scripts, zero failures; record and unique log at
`docs/reports/stream-d-package-freshness-suite-20261031T141323Z-eb25473b.json`
and the adjacent `.log`. Fresh reviews passed without blockers:
`docs/reviews/stream-d-package-freshness-design-1.md` and
`docs/reviews/stream-d-package-freshness-diff-1.md`. No Murphy rows close.
Next lane-2 increment is stress/gate/outcome completion (large), followed by all
diagnosis outcomes (large). Qualified-path legacy deletion remains lane 1's work.
Activation remains off; item 8 remains separate.
### Qualified-path allowance deletion completion

Implemented in `9ce1737` against merged lane 2 `4d7c63e`. Qualified ordinary
launches no longer consult legacy call-cap/founder/cohort/raised-limit/crash-rescue
policy; modern late repairs use the writer-round limit instead of max_repairs.
No new launch or rescue route. Legacy batch inputs retain B's retire-only handling.
Design: `stream-d-qualified-allowances.md`. Reviews in `docs/reviews/`:
`stream-d-qualified-allowances-design-1.md`, `stream-d-qualified-allowances-design-2.md`
and `stream-d-qualified-allowances-diff-1.md`. Fresh final design and diff reviews
PASS with no blockers. Full suite: 161 scripts, 0 failures; retained logs and
correction history in `docs/reviews/stream-d-qualified-allowances-suite.md`.
No Murphy row closes. Rows 9, 13 and 39 retain their remaining integration/live
qualification requirements; lane 2's package/outcome work and item 8 are separate.

Package increment 2 progress (retained traversal slice): implementation at 895221b
joins completed stress to the ordinary gate pipeline, persists stage evidence and
card/context projections, records an immutable outcome, and routes completed-row
replay without author work. Design reviews 1–6 are under
`docs/reviews/stream-d-package-completion-design-*.md`; review 6 passed.
The second full suite passed 160 scripts / 0 failures at 895221b; record and log:
`docs/reports/stream-d-package-completion-suite-20261031T155420Z-c9044583.json`
and adjacent `.log`. The first full run had only a worker-inventory expectation
failure, fixed in 895221b; its failed record is retained too.

This is NOT package completion. The retained traversal slice passed fresh diff
review 2 at eae085f after the two test blockers in diff review 1 were fixed.
No Murphy row closes. The package checkbox stays unchecked. Remaining within
package increment 2: rejected/unchanged writer and confirmed-public-match outcome
completion, entry receipt capture, isolated current-version comparison and version
drift integration. Draft next-slice design: `stream-d-package-terminal-outcomes.md`.
That draft has no passing review and no implementation. Its review attempts hit
Claude rate limits and the explicitly requested DeepSeek fallback's credit limit;
see `docs/reviews/stream-d-package-review-availability.md`.

All diagnosis outcome routes remain next after the whole package. Qualified-path
legacy allowance deletion remains lane 1's work; this lane did not edit it.
Activation and item 8 qualification remain off/separate.

Retained traversal slice review follow-up: test fixes are committed at 58b2625;
full suite passed 160 scripts with zero failures, recorded in
`docs/reports/stream-d-package-review-fixes-suite-20261031T173136Z-9cc253b4.json`
and adjacent `.log`. Fresh Claude reviews are saved verbatim in
`docs/reviews/stream-d-package-completion-diff-1.md` (BLOCK on two test gaps) and
`docs/reviews/stream-d-package-completion-diff-2.md` (PASS, both blockers closed).
The follow-up changes tests and records only; production code is unchanged.
The parent limited this task to review closure: no next package work was started.
The package checkbox remains open and no Murphy rows close. Optional findings
remain recorded in the reviews. Reviewer order is Claude, free OpenCode, then
fresh Codex gpt-6.1-sol; paid OpenRouter is forbidden.

### First-entry capture increment (after retained package traversal)

This lane split the remaining package work again to provide
`extension_package.entry(c, runner)` for a first extension. Approved design:
`docs/designs/stream-d-entry-capture.md`, fresh design reviews 1–3 (PASS in 3).
Capture uses the existing stage evidence collector only when diagnosis activation
is enabled and ordinary mode permits it. It preserves ordinary gate results and
retry behavior; entry reads proof on a copied context without evaluation. No
changes to lane 1's diagnosis_dispatch.py are included.

The package checkbox remains open. Subsequent-entry isolated current-version
comparison and version-drift integration are next; rejected/unchanged writer and
confirmed-public-match terminal outcomes remain afterward. First-entry holds
mid-gate budget exhaustion and stress-before-gates exhaustion as
extension_comparison_pending, not retirement. The terminal-outcomes producer must
later supply the failed-stress retirement contract lane 1 expects. Old runs with
no entry records need comparison/reconstruction, not invented receipts.

Activation still requires measuring serial G10 overhead: capture serializes it
only once diagnosis is enabled. Historical overlapped timing (144.4 G10 minutes
of 148.1 gate minutes) does not measure that added cost. No live qualification,
workers or paid calls were run here. Murphy 9/13 are supported; no rows close.

First-entry capture is complete for this increment at implementation 10da907.
The full suite passed 167 scripts / 0 failures; its committed record is
`docs/reports/stream-d-entry-capture-suite-20261101T150744Z-6a486d1b.json`
with adjacent `.log`. Design reviews are
`docs/reviews/stream-d-entry-capture-design-{1,2,3}.md` (PASS in 3), and fresh
Claude diff review `docs/reviews/stream-d-entry-capture-diff-1.md` passed without
blockers. Optional findings remain recorded there. No Murphy rows close.

Next increment for lane 1: isolated current-version comparison, subsequent-entry
selection/reconstruction and version-drift integration. Rejected/unchanged writer
and confirmed-public-match terminal outcomes still follow. The larger package
and item-7 checkbox remain open; activation and live qualification are unchanged.


### Item 7 current-version comparison implementation

The isolated comparison producer and subsequent-entry reconstruction are implemented
in `stream-d-current-comparison.md`, including the explicitly replaced pending-pair
routing boundary. Fresh design review 5 passes. Full suite passes at 0224014 (170 scripts, zero
failures), including diff-round-1 blocker fixes. Fresh Claude diff review round 2
passes with no blockers (`docs/reviews/stream-d-current-comparison-diff-2.md`).
This increment is complete for handback; package increment 2 stays unchecked.

Remaining item-7 work after this slice: rejected/unchanged writer outcomes,
confirmed-public-match terminal package outcomes, partial first-entry captures
(including budget exhaustion before gate closure and stress exhaustion before
traversal), and the post-extension factory-bug return target recorded as
`new-stream-d-current-comparison-1`. Integrated outcome qualification and item 8
remain separate. No Murphy row is closed and diagnosis activation stays false.
The temporary `comparison_route=False` compatibility seam remains until item 7
is complete. Linux process containment and live upload/time/cost qualification
remain explicit activation evidence; the Mac suite cannot qualify those paths.


### Item 7 unchanged writer terminal outcome slice

Exact full-tree unchanged writer output now retains the admitted entry observations
as a completed outcome, with immutable authenticated writer proof. Completed
replay performs no writer/stress/gate work; a subsequent close-to-passing diagnosis
retires it for no progress even after scientific version drift. Freshness-only
changes with no repair request keep the existing G1/stress path. Repair-requested
freshness-only changes were deferred here; the following continuation slice removes that hold.

Design: `stream-d-unchanged-writer-outcome.md`, parent-approved after design round
2 (B2 full-tree identity/fallthrough, N3 unknown-frontier acceptance, N4 all-pass
refusal). Implementation is complete at f00b673; 15 new focused tests and 27
existing execution tests pass. The full suite passed 173 scripts / 0 failures
at 3def7d9 after a recorded transient isolation failure and unchanged-code rerun.
Fresh Claude diff review round 1 passes with no blockers or majors:
`docs/reviews/stream-d-unchanged-writer-outcome-diff-1.md`. This slice is complete
for handback. No Murphy row closes. Package increment
2 remains open for rejected writer and public-match outcomes, partial first-entry
capture and the post-extension factory-bug return target. Activation stays off.


### Item 7 freshness-only writer continuation slice

The approved design `stream-d-freshness-only-writer.md` changes both extension
writer completion checks to require full-tree identity for unchanged_repair.
A repair-requested writer that changes search evidence now reaches ordinary G1,
early checks and stress without another writer call. Ordinary non-extension
unchanged behavior and exact full-tree terminal proofs stay unchanged.
Design review round 2 passes. Implementation is 655b5f0; all 18 focused tests
pass and the full suite passes 174 scripts / 0 failures. Fresh Claude diff review
round 1 passes: docs/reviews/stream-d-freshness-only-writer-diff-1.md. This slice
is complete for handback. No Murphy rows close.
The six remaining slices, ownership and estimates are in that design's table;
package increment 2 and All diagnosis outcomes stay unchecked.


### Item 7 rejected-writer G1 observation slice

Design `stream-d-writer-g1-observation.md` passes fresh review round 1. The package
now retains real failed post-writer G1 observations before validation-receipt
publication and replays them across that crash window. Passes are not recorded.
Ten focused tests pass. Implementation fdfab00 passes the shared-lock full suite:
177 scripts / 0 failures. Fresh Claude diff review round 1 passes:
`docs/reviews/stream-d-writer-g1-observation-diff-1.md`. This observation slice is
complete for handback.
This is evidence capture only: terminal completion/progress, early-gate and
saved-cheat observations remain open, alongside partial/legacy entry reconstruction
and final all-outcomes integration. Lane 1 public-match completion has landed.
No Murphy rows close; package increment 2 and All diagnosis outcomes stay open.


### Item 7 early writer rejection observation slice

Design `stream-d-writer-early-observation.md` passes fresh review round 2. The
implementation retains failed early gate and private saved-cheat observations;
replay precedes G1 and every early check and never creates a full G6 result.
Terminal completion/progress remains separate. Implementation caba7e6 passes the
locked full suite: 179 scripts / 0 failures. Fresh Claude diff review round 1
PASS: `docs/reviews/stream-d-writer-early-observation-diff-1.md`. Observation
slice complete; terminal completion/progress and item 7 remain open.
No Murphy row closes. Lane 1 public-match and blocking-stress
outcomes are now merged; post-extension factory-bug return remains lane 1.


### Item 7 rejected writer terminal completion slice

Design stream-d-writer-rejection-terminal.md passes fresh review round 2. The
implementation completes retained G1/early/saved-cheat rejections without stress
or gate rerolls, with all package stages unreached and private terminal proof.
Subsequent close-to-passing retires through the verified no-progress branch before
comparison/admission. Implementation 108e65f passes the locked full suite: 181
scripts / 0 failures. Fresh Claude diff review round 1 PASS:
`docs/reviews/stream-d-writer-rejection-terminal-diff-1.md`. This terminal slice is
complete for handback; item 7 remains open. No Murphy
rows close. Partial/legacy first-entry reconstruction and final all-outcomes
integration (including successful irrelevant-edit progress checks) remain open.
Lane 1 factory-bug return target is merged in ff31d87. Founder has replaced item 8
with a 3-case real pilot immediately after item 7; no pilot is started by this slice.
