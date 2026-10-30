**Verdict: FAIL.** I found 2 blockers. I wrote no files; the full review text is below. Save it as `docs/reviews/stream-d-factory-bug-design-2.md`.

---

# Review: stream-d factory-bug design amendment 2 (held lifecycle): FAIL

**Reviewer:** fresh goldfish, `Mode: REVIEW`, read-only. Personas: `zoom_out`, `design_critic`, `implementation_readiness`. Standards: `heilmeier-standard.md`, `implementation-readiness-standard.md`, ENGINEERING.

**Commit:** worktree `t3-21bef30c` at HEAD `390c9c1`, on top of `cfe616f`. The five D commits are 15ad8ec, 90f41f7, 88a83f5, bf2a8a0 and 390c9c1.

**Scope:**
- **Reviewed:** the held-lifecycle changes from `88a83f5..390c9c1` in `docs/designs/stream-d.md` (§Diagnosis and factory-bug routing, about lines 339–461, plus the edits at about 866, 1037, 1090 and 1105) and in `docs/designs/interfaces.md` §8 (about 640–712).
- **Checked against:** round 1 (`stream-d-factory-bug-design-1.md`), including its elephant response and the parent clarification.
- **Code read to verify claims:** `factory/budget.py`, `bin/run_validity.py`, `factory/gate_pipeline.py`, `factory/run.py`, `docs/designs/status.md` and `docs/designs/batch-service.md`.
- **Excluded:** the unwired legacy-import helpers, which already passed review, and `.stream-d-next/`.

**The verdict is FAIL, iff-rule:** two blocking findings remain open.

## What holds

**Round-1 items resolved:**
- **B1 (pending infrastructure projection):** resolved as the parent clarified. Pending infrastructure exhaustion stays present with `replacement_eligible:false`, so B queues the diagnosis and derives no child. A completed diagnosis returns `None`, and a factory bug sets `terminal_stop: factory_bug_held`. `interfaces.md` and `stream-d.md` agree, and the formula at stream-d:~1037 matches.
- **Maintainer service and in-batch fix wait:** removed. The maintainer queue, fix-delivery contract and mid-batch fix wait no longer appear in the live text. "Factory-bug maintainer queue" is replaced by `factory_bug_held`.
- **M1 (where the held state is recorded):** resolved. `factory_bug_held` is exactly a `terminal_stop` literal with `status: stopped`, it is unscored, and no model work follows while held. B owns the one status rule, and D names the source.

**Public field and status:**
- The public field is exactly `{finding_id, gate_or_stage, summary_class:"factory_bug"}`.
- `gate_or_stage` comes from a fixed list (or `unknown`) and is code-sourced, never the model's `component`. This closes round-1 m3 for private-content leakage.
- The status action is `factory bug: see finding <id>`.

**B2 (waste-record schema), resolved:**
- The v2 waste-record fields are exact.
- `id = factory-bug:<finding_id>`.
- `diagnosis_sha256` is the canonical digest of the private finding.
- The record is bound to a resume through `resume_id` and `resume_binding_sha256`.
- An empty set emits no record, and later settlements extend the same record.
- v1 records are decode-only, with no dummy fix commits.

**M2–M4, resolved:**
- **M2 (later-batch detection):** `held_batch_id` is recorded. Resume requires a different authenticated `batch_id` and release.
- **M2 (owner across batches):** "same-owner" across batches means the same continuing case with a new B money owner.
- **M3 (fix check):** the operator's manifest decides whether the fix is present. D does not attest the fix, and a resume without the fix still uses one of the 3.
- **M4 (resume counter):** an append-only history holds at most 3 entries and is appended before any work. A replay of the same finding is idempotent, a missing history never resets to zero, and the public count is derived from the history length.
- **M4 (B dependency):** the later-batch resume and its test are explicitly blocked on B's cross-batch addendum. The legacy import record grants no authority.

**Money:**
- The worked example ($12 booked, $4 classified → case $8 + waste $4 = batch $12) keeps the batch total unchanged.
- The model can only narrow `affected_operations`.
- Finding authority fields are code-supplied.
- I found no route for model output to create batch headroom.

## Blockers

**B1. The "code-linked invalid-infra attempt receipt" that bounds eligible waste does not exist, and the design does not define it.**

*Where:* stream-d "Eligible failed operations…" bullet and the finding's `eligible_operation_ids`/`failure_receipts`; interfaces §8 "Code-linked invalid-infra attempt receipts bound the eligible waste operations".

*Problem:* the design says "the code's attempt receipt must list the operation IDs admitted in that attempt and bind their ledger reservations/usage receipts." No such receipt exists today:
- `bin/run_validity.py:59-104` (`retry`) writes `infra-attempts.json` keyed by a hash of the execution identity.
- Each row holds only `invalid_attempts`, `running` and `error_type`.
- A row has no operation IDs and no per-attempt entries.
- A successful attempt resets the row (`invalid_attempts=0`), which overwrites the evidence.
- `gate_pipeline.stop_infrastructure` (`factory/gate_pipeline.py:~148`) records only `{gate, error_type, classification, exhausted}`.

*Decisions left to the implementer:*
- the receipt's file and schema;
- who writes it, and when (per attempt, or before reservation);
- how it is kept when a later attempt succeeds;
- what `failure_receipts[].path` points at.

Under the zero-decision rule, these cannot be left open. This is the B3 headroom boundary from round 1, so a loose choice here (for example, every reservation made during the attempt window) reopens per-case ordinary headroom.

*Fix, pick one:*
- (a) **Recommended, smallest:** this increment states that the eligible set is always empty and that `failure_receipts` is `[]`, so no reclassification happens. The bug is still held, and the cost stays on the case line. A per-attempt receipt with an exact schema comes in a later reviewed addendum. This matches "without that code evidence the eligible set is empty" and deletes a path rather than adding one.
- (b) Specify the receipt exactly: the file, its append-only per-attempt entries `{attempt_id, execution_key, gate, operation_ids, reservation_ids, outcome}`, a write before each reservation, and keeping the entries after success.

**B2. Cases already running at rollout get no resume history, so every hold on one is stuck forever.**

*Where:* stream-d's `factory-bug-resumes.json` bullet: "A new-schema fresh case creates the empty history once; a restore with missing/malformed history never resets it."

*Problem:* ENGINEERING §3 rolls plumbing onto running cases at the next checkpoint. A case started before this ships has no history file. If it later becomes `factory_bug_held`, the resume path finds the history missing and must refuse. The case would never be resumable, and nothing tells the implementer whether to create the file, refuse, or migrate.

*Fix:* create the empty history atomically with the first `diagnosis/<finding_id>/finding.json` write, when it is absent and the card has no prior `factory_bug` field or v2 waste record. Resumes only follow holds, so one creation point covers both fresh and in-flight cases. At resume, missing history with an existing hold stays a refusal. Add a test with a real pre-rollout card that becomes held and then resumes.

## Major (non-blocking, settle before implementation)

**Ma1. Mapping from the stop to `gate_or_stage` is undefined.**
- "Comes only from code-recorded stage/stop metadata" does not say which value each stop produces.
- Give a table:
  - `infrastructure_exhausted` → `infrastructure_gate.gate`;
  - `late_defect_needs_ruling:<gate>` → `<gate>`;
  - `stress_review_unresolved:*` → `stress`;
  - `budget_exhausted` → `writer`;
  - `extension_incomplete` → the failing gate if recorded, otherwise `unknown`;
  - anything else → `unknown`.
- "Non-sealing `run.GATES` names" is defined nowhere in the docs or code. Either name the excluded gates or say "`run.GATES` names". `run.GATES` itself has no G12, while `carry_over.GATES` does.

**Ma2. `factory_bug_resume_count` has no location or shape.**
- Say whether it is a top-level card integer.
- Say it is present only once a history exists.
- Say what a held card that has never resumed shows (0).
- Say what a card with an unreadable history shows: fail closed, with no count and `check case`.

## Nits

- **n1. Hash encoding.** `resume_binding_sha256` should name the canonical JSON encoding, as `binding_sha256` does elsewhere.
- **n2. Float vs string amount.** The v2 `infrastructure_waste_usd` is a nine-place string. `budget.py:310` and `:530` currently write a float when extending a record, so the implementation must change both.
- **n3. Replay across batches.** Replay is defined only for the same admitted binding. A resume admitted in batch B and continued in batch C falls to B's cross-batch addendum. Say so.
- **n4. Unresumed holds.** If a held case is never resumed, its cost stays on the case line and is never moved to waste. This matches ENGINEERING's "resume after the fix", but should be stated.
- **n5. Replay as waste.** A replay of eligible failed units after the fix is a successful gate re-run, yet it still counts as waste. This is bounded by 3 resumes × the eligible units and is not a backdoor. Note the bound explicitly.

## Private content and cost headroom

- **Private content exposure:** none. The public field and stage list are code-sourced, and the finding and reproducer stay encrypted.
- **Cost headroom:** the batch total is unchanged. Per-case ordinary headroom is bounded only once B1 is settled; option (a) closes it completely for this increment.

## Readiness

- **Phasing:** sound. D ships the hold, state validation, attribution restriction and same-batch refusal now. The later-batch resume and its test wait for B's addendum.
- **Tests:** named but abstract. Pin each test to the real saved card or ledger it uses, per ENGINEERING §4.
- **Murphy register:** no row is claimed, which is correct.

---

The worktree is at HEAD `390c9c1`, five D commits on top of `cfe616f`. All round-1 items are settled; the two blockers are new gaps:

1. **The receipt that limits which costs count as waste doesn't exist in code.** Today's `infra-attempts.json` holds no operation IDs and is wiped when an attempt succeeds. The quickest fix is to declare the eligible set empty for this increment.
2. **Cases already running when this ships never get a resume history,** so any hold on them can never be resumed. The fix is to create the history file together with the first finding.

The two majors (the stop-to-stage mapping table and where `factory_bug_resume_count` lives) are quick text fixes. I found no way for model output or the new fields to create budget headroom.

## Elephant resolution

All findings accepted. B1 option (a): the hold increment always stores empty eligible_operation_ids and failure_receipts and emits no v2 waste record. Attribution/replay activation requires a separately reviewed per-attempt producer and B resume addendum; no existing receipt is claimed to prove operation causation. B2: initialize missing history before the first finding only when no prior hold, count or factory-bug waste record exists; write history first, finding second, public marker last, with atomic durable writes. Existing holds with missing history still refuse. Ma1/Ma2 and n1–n5 are made explicit in the revised design; budget_exhausted maps to unknown because its literal does not identify the executing role. No finding rejected; no row closed.
