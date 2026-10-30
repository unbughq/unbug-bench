# Review: stream-d factory-bug design amendment 1 (`9111751..085c60a`): FAIL

**Verdict: FAIL.** There are 3 blockers and 4 missing decisions. I made no edits, and the parent can save this text as `docs/reviews/stream-d-factory-bug-design-1.md`.

**Scope:** `docs/designs/stream-d.md` and `docs/designs/interfaces.md` only. The `stream-d-diff-13.md` review text and the `.stream-d-next` drafts were excluded. I checked the change against B's consumer contract (`docs/designs/batch-service.md`), `docs/designs/status.md`, ENGINEERING §3 and the current `factory/budget.py`.

**What holds:**
- The maintainer service, fix-delivery contract and in-batch wait are deleted in both docs, and no live references remain.
- ENGINEERING §3 still says "resume after the fix, cost on the infra-waste line, at most 3 resumes", so it matches.
- The public `factory_bug` field and the encrypted private finding path keep the reproducer and model prose private.
- The waste example ($12 booked, $4 classified → case $8 + waste $4 = batch $12) keeps batch spend unchanged.
- Infrastructure exhaustion spawning no replacement matches both the earlier rule and the new ruling.

## Blockers

**B1. Projecting `None` for pending infrastructure exhaustion means its diagnosis never runs.**
- B only schedules the diagnosis relaunch from the projection. `batch-service.md:921-923` says: "Queue an ordinary same-owner resume when pending_projection is present or the exhausted total is unknown."
- So an infrastructure-exhausted case with a known total gets no relaunch. Its `diagnosis_state` stays pending, and nothing ever reads it.
- The amendment says "requests read-only diagnosis through diagnosis_state, but pending_projection returns None" (`interfaces.md:663-664`, `stream-d.md:384-387`). B has no rule that reads `diagnosis_state`, and `interfaces.md:686` says "B needs no extra projection".
- The case would sit until the batch bound. The status table has no rule for it either.
- **Decision needed, pick one:**
  - (a) Recommended: keep the earlier projection, which is present with `replacement_eligible:false`. B already handles it: no child, but the same-owner resume is queued. That already meets "infrastructure gets no replacement". It is also what the runtime does today, so no code changes.
  - (b) Keep `None` and amend B's planner to queue a same-owner diagnosis resume from a new D fact. That means new B coupling and a B design review.
- The ruling's words were "no replacement projection". (a) meets that without breaking diagnosis, so the "strict reading" goes further than the ruling needs.

**B2. The waste-record schema for the new lifecycle is undefined.**
- `factory/budget.py:421` and `:491-492` require `fix_commit` (40 hex) and `fix_attribution_sha256` (64 hex) on every `kind:"factory_bug"` record. Both fields are part of the record's immutable identity.
- The amendment makes them decode-only, "not a fix-delivery prerequisite" (`stream-d.md:376-377`, `:799-802`), but never says what a new record contains.
- An implementer would have to choose between:
  - a schema v2 without those fields;
  - filling `fix_commit` with the later batch's release source commit;
  - some other field.
- That is an on-disk format choice, and it cannot be left to the implementer.
- **Decision needed:** state the exact field list of the new record and its schema version, and how `id` is derived (for example from `finding_id`). Also state which binding `diagnosis_sha256` is checked against, and that v1 records are decode-only.

**B3. The amendment no longer says who decides which operations count as waste, which opens per-case budget headroom.**
- The deleted text said "a model assertion alone cannot refund spend". The fix's review attribution was what confirmed the affected operations.
- The new text bans only "a model's asserted dollar amount" (`stream-d.md:380-381`). The `operation_ids` set still comes from the diagnosis model's `affected_operations`.
- Reclassified spend leaves `spent_usd`, and `spent_usd` is what the ordinary $50 diagnosis trigger compares (`stream-d.md:61-64`). So the diagnosis model can reset a resumed case's ordinary budget headroom by naming operations.
- Receipts prove that an operation happened and what it cost. They do not prove the bug caused it.
- How far this goes:
  - The batch total and the job commitment are unchanged.
  - The writer-round limit still holds.
  - Stress and gate spend per resume is not bounded by rounds. Over 3 resumes this could add up to roughly 3× the ordinary limit per case.
- **Decision needed:** a rule code can check. Recommended: `operation_ids` must be a subset of code-recorded failed operations at the recorded gate/stage (operations with infrastructure-failure receipts), and the model may only narrow that set. Otherwise state that the merged fix's review names the set, and say where that is recorded without restoring a delivery contract.

## Missing decisions (must be settled before implementation)

**M1. Where `factory_bug_held` is recorded.**
- It is not stated whether `factory_bug_held` is a `terminal_stop` literal or a state shown only by the `factory_bug` field.
- `status.md` flags any unknown `terminal_stop` as `check case`, so B's single new rule needs the exact field and value to read.
- `status.md` has no row for it yet. It is B's change, but D must name the source.

**M2. How D detects a "later batch".**
- The finding records no batch identity for the hold. D therefore cannot refuse a same-batch relaunch, which the test list requires ("same-batch refusal"), against a binding check.
- "Same-owner" across batches also conflicts with the owner key in `interfaces.md` (same batch/job/case/reservation).
- **Decision needed:**
  - Store the held `batch_id` in the private finding or public field.
  - Define resume as a verified binding whose `batch_id` differs, with lineage bound.
  - Say what "owner" means across batches.

**M3. Whether D checks that the fix is actually in the later release.**
- With no fix ID, D cannot verify that the later release contains the fix.
- State it plainly: the operator including the case in the later batch's manifest is the authority, D does not verify the fix, and a resume without the fix still uses one of the 3.

**M4. Where the resume counter lives, and its dependency on B.**
- The design says to "record admission before work" and allows three lifetime resumes, but names no field, file or authentication for that record.
- The counter has to carry across batches. The only cross-batch path today is the retirement-only legacy import (`lifetime_history: null`). `batch-service.md:150` and `:733-735` refuse cross-batch import until a reviewed addendum lands.
- The "normal later-release resume" test therefore cannot pass until B's resumable-import design exists.
- **Decision needed:**
  - Name the counter field and where it is stored.
  - Mark the resume path and its test as blocked on that B addendum, so D's increment can ship the hold and refusal without it.

## Minor

- **m1.** `interfaces.md:657-658`: once infrastructure exhaustion projects `None`, the clause "AND the current exhaustion is not infrastructure_exhausted" is dead. If B1(a) is chosen, revert the text to the earlier version. If B1(b), simplify the formula to `replacement_eligible = actual_model_work(card)`.
- **m2.** "factory_bug_held also projects None" adds nothing: a completed `diagnosis_state` already gives `None`. It is harmless, but say it is the same rule, not an extra branch.
- **m3.** `gate_or_stage` has no defined set of values. Say it comes only from `diagnosis_state.stop` or `infrastructure_gate`, from a fixed list or `unknown`, and never from the model's `component`. This shuts off a path for private content to reach the public card.

## Private content and cost headroom

- **Private content exposure:** none, once m3 is fixed.
- **Cost headroom:** the batch-level total is unchanged. Per-case ordinary headroom is open until B3 is fixed.

## Elephant resolution

All findings accepted. B1 requires parent clarification because the literal pending-None interpretation conflicts with B's existing diagnosis scheduling. Recommended resolution is present/ineligible while pending, completed None while held. B2/B3 and M1–M4/m3 will be resolved with exact schema, code-proven failed-operation attribution, terminal_stop/source ownership, held batch identity, ordinary manifest authorization, and durable lifetime admission history. The later-batch resume remains blocked on B's reviewed cross-batch bind/import addendum. No finding rejected and no Murphy row closed.

Parent resolved B1 explicitly: present pending infrastructure projection with
replacement_eligible false; completed factory_bug state is None with terminal_stop
factory_bug_held. B2/B3 now specify exact v2 waste schema and only code-linked
invalid-infra operations (model may narrow). M1–M4/m3 now name terminal_stop,
fixed public labels, held batch/release, normal manifest authority, private
lifetime resume history and B cross-batch prerequisite. No finding rejected.
