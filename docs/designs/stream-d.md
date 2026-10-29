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
HTTP thread cannot publish. Its non-threading HTTPServer serializes questions,
so only one owner is live beside the tester. These are minimal exam_responder.py
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
`extension_id`, `state` (active/complete), `writer_operation_id`,
`entry`, `outcome` (null until complete), each snapshot with the fields above.
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
affected_operations:[operation_id], fix_required}` (nonempty strings/list).
Bind results to the queued checkpoint; stale output cannot authorize newer work.
Malformed/interrupted diagnosis is infrastructure, not a fourth case outcome;
retain and repair/retry under the batch bounds. `not_converging` retires.

Factory bugs enter the coordinator’s maintainer queue with reproducer/evidence.
The maintainer follows ENGINEERING’s design/tests/goldfish flow; no automatic
production edit. A reviewed qualified release identifies the finding and affected
operations; the coordinator then resumes the checkpoint, at most three times.
Move affected failed operations and their replay to `infrastructure_waste` by
unique operation ID, keeping batch spend. Require operational receipts and the
reviewed fix’s attribution; a model assertion alone cannot refund spend. Add a
validator branch in `budget.py` for schema-v1 waste records
`{kind:"factory_bug", id, diagnosis_sha256, fix_commit, fix_attribution_sha256,
operation_ids, event_ids, infrastructure_waste_usd}`. Require unique operation/
event IDs and amount equal to their settled receipt sum; replay operations are
added once as they settle. Reclassification moves existing cost, never adds it
twice or reduces batch total. `case_spending` excludes the classified event IDs
from ordinary `spent_usd` and includes their sum once in `infrastructure_waste_usd`;
`total_spent_usd` stays unchanged. Example: $12 booked, $4 classified → case $8,
waste $4, batch total $12. Preserve the additive legacy infrastructure_kill
validator because its charge has no already-booked event IDs.
A fourth resume retires. Only conflicting substantive case judgments reach the founder.
At batch bounds unfinished work retires, without holding the replacement.

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
