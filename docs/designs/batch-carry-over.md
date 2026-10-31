# Cross-release checkpoint carry-over

Baseline: factory-simplify 56b4c13. Owns new-batch-service-4. This is a design
for review, not launch authorization. No workers or paid calls are authorized.

## Problem and scope

A held factory-bug case, or its deadline-stopped replacement, must continue in
a fixed release without losing its ledger, owner, scientific progress or lifetime
resume count. Removing the release comparison in batch.bind is insufficient:
batch_money derives case identity from the batch name, holder journals are
release-specific, restore_ledger and run reject a different release, job_config
requires identical batch/deadline, and diagnosis_dispatch unconditionally
replays a completed factory-bug finding as a hold.

Use batch.launch(batch, job, checkpoint) and the existing holder/controller,
collection verifier, restore transport and worker installer. There is no second
launcher, rescue branch, plaintext import, case-copy operation or fresh budget.
Carry-over preserves the case, job and reservation UUID; batch membership,
deadline, source generation and monetary revision advance. This follows the
current task's explicit same-owner requirement and supersedes stream-d's older
sentence allowing a different reservation owner across batches. A replacement
remains a separate owner; it can independently carry forward without becoming a
second copy of its original. Neither import nor release change grants another
replacement or resets ordinary exhaustion/extension eligibility.

## Explicit manifest authority

An optional per-job `carry_from` is part of the tracked, digest-pinned target
manifest. It has exactly `{batch, job, manifest_sha256, release_sha256,
generation, generation_manifest_sha256, reservation_id, authority_sha256}`.
Batch/job identifiers, UUID4 and hashes use the existing validators. Target job
name must equal source job name; target case must equal the authenticated source
case. A job without carry_from retains today's case-name derivation. The target
batch and release must both differ from the source. This is an explicit operator
selection of a fixed release, not independent evidence that the fix works.
Do not accept a model's fix assertion or a caller-supplied card as authority.

The source manifest and release remain immutable retained artifacts. Verify
their hashes/inventories without demanding that the old host files equal the
new checkout. The new manifest still receives the normal host/release check.
The target manifest does not contain credentials or private findings.

The source must have an acknowledged current generation, matching immutable
generation manifest and card, matching money ACK and operation, no accounting
incident, and a verified worker deletion receipt. Use holder._source and the
existing snapshot validator against the source manifest/release, not a rewritten
copy of the old generation. No operation for the owner may remain live, pending,
uncertain or unpublished. Unknown totals stay blocked for this increment; settle
under existing source authority first. Terminal scientific retirement and
sealed cases cannot be revived. Deadline expiry is operational: its verified
stopped checkpoint may move under explicit new manifest authority, without
erasing the old deadline event. This narrows the blanket retired_batch_bound
refusal only at this authenticated boundary; ordinary same-batch revival remains
forbidden. A held case additionally requires D's worker validation below.

## One owner and crash-safe transfer

Use the existing source and target batch locks in lexicographic batch-ID order.
All source admission paths must check a durable export marker while holding
the source lock, including reserve replay, _post immediately before dispatch,
and the legacy fresh-only authorize path. A pending operation blocks export;
an export blocks new source authority. Do not rely on deadline expiry alone.

Write the source export first with the exact target manifest/release/job,
generation, owner, old authority and a canonical digest of the complete source
money row. It is an irrevocable transfer intent, not released headroom. The
target then installs the same owner with source_generation set to the selected
checkpoint and revision old+1. Retry of the exact transfer repairs target state;
a competing target, altered request or older generation refuses. A crash before
the export changes nothing; a crash after it leaves the owner unavailable until
the exact target replay completes. Never roll back by deleting the export.
Further carry-over exports the current target, preserving the predecessor chain.

Retain the original source state, generation and publication ACK unchanged.
Store a target import receipt binding their hashes rather than fabricating a
local predecessor worker or rewriting old ACK authorities. Holder source lookup
resolves that receipt for the first launch; later generations use ordinary local
ACKs. Money validation recognizes one imported initial floor and an authenticated
prior source chain, then uses the existing local advancement rules. Both bind
and source_directory resolve the exact same source. The initial import cannot
be selected with an empty checkpoint. The target operation UUID remains the
ordinary batch/job/source/release UUID5, so lost launch replies remain idempotent.

## Cumulative money

Target requested_total_usd is a lifetime commitment, never an incremental grant.
It must be at least the source held commitment and collected floor; preserving
the same amount is the default. Any increase requires the explicitly pinned
target manifest and its money bound. Target admission charges the imported owner
once at max(commitment, lifetime collected floor), alongside all other owners.
Scientific cost and infra-waste both count. A replay cannot add the total twice
or turn a reclassification into headroom. The source's retained accounting is
historical and stays closed to admission after export.

Item 8 additionally requires an allocation shared across beta releases: old
incremental consumption cannot become another E on each transfer. This task
must not pretend that a per-batch bound alone proves that condition. The smallest
B seam is its reviewed practice admission clamp taking authenticated owner,
original baseline S, previous held authority and target requested lifetime total
before import admission. It must account for non-imported beta owners too.
Absent that clamp, general carry-over cannot be used to authorize item-8 practice.

## Worker authentication and D's resume boundary

The existing authenticated RAM job config stays the launch authority. The target
manifest binds the import; the transport verifies the selected source generation
against its original release, then the worker installer validates the old
job-money.json and restore-accounting receipt before installing the new channel.
Keep the original encrypted history files and archived scorecard. Append the
old/new config transition to job-money-history.json; do not replace history with
the target authority. The worker checks same case/job/reservation, old authority
digest, exact source, revision and cumulative amount. A normal same-release
restore still uses today's checks. run's early release-equality check moves to
this unified verified installation boundary, before any model dispatch.

D must authenticate the retained finding and diagnosis inputs against the OLD
binding before consuming the NEW one. A public factory_bug marker alone cannot
grant a resume. Its existing factory-bug-resumes.json validator is the lifetime
counter. Append the specified history entry durably before resumed work; retries
of that admitted finding retain its UUID and slot. A distinct fourth finding
retires without a model call. Carrying an already admitted resume to another
batch preserves that admission and requires a verified money transition from
its recorded binding; it does not append another finding or lose the active
replay identity. Clear infrastructure_gate and the active hold only after durable
admission. Preserve the completed finding and old diagnosis evidence privately.

The smallest D seam is a worker function after job_config.install and before
diagnosis_dispatch replay that either returns an authenticated active resume,
retains the hold, or retires at the lifetime limit. It must also provide the
code-derived failed-unit/replay operation mapping to the runtime settlement
boundary. Use the schema-v2 attribution in stream-d, with settled event sums and
one record per finding. Reclassify only causally evidenced failed/replay
operations; absent evidence must not invent historical waste. Later receipt
growth updates that attribution once with exact nine-place amounts. The replay
cost goes to infra-waste while total lifetime spend is unchanged. New unrelated
scientific work keeps ordinary classification and ordinary exhaustion limits.

At this baseline that D seam is not implemented: finding producers deliberately
write empty eligible_operation_ids/failure_receipts, the dispatcher always holds,
and budget._spending accepts only schema-v1 fix-credential waste. Implementing
transport alone cannot satisfy the requested factory-bug lifecycle. A reviewed
D causal-receipt/replay contract is required before enabling the resume path;
this design does not authorize fabricating those receipts or broadening all
post-resume work into waste. This is an implementation-readiness issue for the
fresh reviewer to assess, not a claim that row 4 is fixed.

## Deletions and implementation boundaries

Replace duplicated same-release equality refusals with the one authenticated
checkpoint transition predicate. Extend existing manifest, money, holder,
restore and installation paths; no migration CLI, scheduler or rescue mode.
Keep source export/import transaction code in batch_carry_over.py so B's
practice increments can integrate narrow calls in manifest validation, source
resolution, admission and pre-dispatch checks. Do not copy B's active worktree
or its unreviewed changes. D owns the worker replay semantics described above;
the same-owner interpretation must be reflected in interfaces §8 and stream-d
when the implementation lands. Activation switches remain unchanged.

## Tests and acceptance

Required regression inputs are real saved held and deadline-stopped collected
cards with their authenticated generations, retained histories, money ownership,
publication ACKs and deletion evidence. Existing test_batch_holder fixtures have
real saved ledgers and ciphertext but authored authority/deletion fields; they
are useful adversarial/offline tests, not evidence of a real held transition.
No matching held saved card was found in this checkout's sealed or JSON fixtures
at design time. Item 8 explicitly says no eligible bootstrap input is yet proven.

Test: successful later-release launch retains owner and exact ledger/history;
target bound includes all prior spend; replacement carries separately; export
prevents an old or competing launch; crash at each durable write repairs exactly
once; stale pointer, changed card/archive/history, unknown usage, missing ACK,
missing deletion and changed source authority refuse; first/second/third distinct
factory-bug admissions succeed and fourth retires; same finding replay and an
admitted resume crossing another release debit no extra slot; causally linked
replay charges are waste exactly once, including late settlement growth; no new
ordinary writer/extension/replacement allowance appears after import.

Run the full suite with a unique retained log:
`uv run --with numpy --with scipy python -B tests/run.py`.
Commit the exit status, exact tested commit and log path, and all verbatim fresh
design/diff reviews. Any blocking fix needs another fresh review. Close only
new-batch-service-4, and only in the implementation commit whose real-artifact
test proves the complete held/deadline transition. Without that evidence it
remains open even if offline tests pass. No merge or push is authorized.
