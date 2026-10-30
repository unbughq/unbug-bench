**Verdict: PASS.** The held factory-bug amendment at `305c10c` has no open blockers. It leaves one major finding and five nits, none of which block a pass. I made no edits. The full review text is below, for you to save as `docs/reviews/stream-d-factory-bug-design-3.md`.

---

# Review: stream-d factory-bug design amendment 3 (bounded hold phase): PASS

**Reviewer:** a fresh goldfish working read-only in `Mode: REVIEW`, using the `zoom_out`, `design_critic` and `implementation_readiness` personas. Standards: `heilmeier-standard.md`, `implementation-readiness-standard.md` and `docs/ENGINEERING.md`.

**Commit:** worktree `t3-21bef30c` at `305c10c` ("Bound factory-bug hold phase and test real D projections through B core"), on top of `390c9c1`.

**Scope:**
- **Reviewed:**
  - `docs/designs/stream-d.md`, §Diagnosis and factory-bug routing (about lines 339–502 at `305c10c`), including the new "Implementation decisions for the held lifecycle" block and the stop-to-stage table.
  - `docs/designs/interfaces.md` §8 (about lines 640–720).
- **Checked against:**
  - rounds 1 and 2 (`stream-d-factory-bug-design-1.md` and `-2.md`), including both elephant resolutions;
  - the parent clarification (pending infrastructure exhaustion stays present with `replacement_eligible:false`; a completed factory_bug diagnosis projects `None` with `terminal_stop: factory_bug_held`).
- **Code read to verify claims:** `factory/diagnosis.py`, `factory/run.py` (`GATES`), `factory/budget.py` (v1 `factory_bug` validation), and `tests/factory/test_stream_d_projection.py`.
- **Excluded:**
  - `.stream-d-next/`;
  - the uncommitted edits in the worktree (`factory/diagnosis.py`, `factory/run.py`, `tests/factory/test_stream_d_runtime.py`). They are not part of `305c10c`, and the production held-state producer has not landed.

**Supporting evidence (not a substitute for the design):** in a clean `git archive 305c10c` export, `tests/factory/test_stream_d_projection.py` runs 7 tests and all pass. The new test `test_b_core_queues_pending_infrastructure_but_never_derives_a_child` behaves as follows:
- It uses D's real predicates on saved card 5813be, through B's core planner.
- A pending infrastructure stop projects `{status:"pending", replacement_eligible:false}`, queues exactly one same-owner `resume`, and derives no child.
- A completed `factory_bug` with `terminal_stop: factory_bug_held` projects `None`, queues nothing for that source and derives no child.

The test uses B's harness envelope bindings, which are authored, so it is not rollout qualification. None of the 30 saved cards I listed has a `factory_bug` field, a `factory_bug_resume_count` or an `infrastructure_gate`. So the pre-rollout path (history missing at first hold) is the real case, not a hypothetical one.

## What holds

**Round-2 B1 (eligible-waste receipt): resolved by option (a).**
- The hold phase states that `eligible_operation_ids` and `failure_receipts` are always `[]`, that `affected_operations` must be empty for an accepted factory_bug diagnosis, and that no schema-v2 waste record is emitted.
- Historical charges stay on the case line.
- The design no longer claims that `infra-attempts.json` proves which operations a bug caused.
- The future v2 schema and the per-attempt causal producer are explicitly marked as requirements for a later reviewed addendum, not enabled paths. `interfaces.md` §8 says the same.
- This closes ordinary per-case budget headroom completely for this increment.

**Round-2 B2 (pre-rollout history): resolved.**
- Missing history is created at the first held finding only when the card has none of the following: a `factory_bug` field, a count, a retained finding, or a `factory_bug` waste record of any schema.
- Writes are durable and ordered: history, then finding, then public marker.
- A crash before the finding replays the empty history.
- An existing finding or hold with missing history refuses.
- Malformed history never resets.
- This covers both fresh cases and cases already running at rollout, without inventing prior resumes.

**Ma1 (stop-to-stage mapping): resolved.**
- The table is exact. It is limited to `run.GATES` (which has no G12, matching the `_trigger` regex in `diagnosis.py`) or `unknown`, and it never uses the model's `component`.
- `budget_exhausted → unknown` is justified, because that stop literal does not say which role ran out.
- `failed_gate` is an existing card field (`run.py:423`).

**Ma2 (resume count): resolved.**
- `factory_bug_resume_count` is a top-level integer equal to the history length.
- It is present only once a valid history exists, and shows 0 on the first hold.
- Unreadable history shows no count and stops with the new `factory_bug_history_invalid`. Per `status.md`'s unknown-stop rule, that surfaces as "check case".

**Nits n1–n5 from round 2: all addressed.**
- **n1:** the canonical encoding is UTF-8 JSON with sorted keys, compact separators and `allow_nan=False`, the `carry_over.digest` convention.
- **n2:** a future v2 amount must remain a nine-place string.
- **n3:** replay applies only within the same binding; replay across batches belongs to B's addendum.
- **n4:** an unresumed hold stays on the case line.
- **n5:** future replay counted as waste is bounded by the 3 admissions and the eligible units.

**Parent ruling: respected.**
- None of the following remains in the design: a maintainer component, a fix-delivery contract, or an in-batch wait.
- A resume uses the normal later-batch manifest and the ordinary bind/import path, with a cap of 3.
- The public field is exactly `{finding_id, gate_or_stage, summary_class}` and carries no content.
- The later-batch resume and its tests stay blocked on B's cross-batch addendum.

**Scope claims:** the amendment closes no Murphy row and claims no resume or waste activation. That is correct.

## Blockers

None.

## Major (non-blocking; settle before the producer lands)

**Ma1. During the hold phase, it is unclear whether a non-empty `affected_operations` is rejected or narrowed to empty.**

*Where:* stream-d's result schema (about line 340: "the operation list may be empty when code proves no eligible charged operation"), the "may narrow … never enlarge" bullet, and the hold-phase paragraph ("`affected_operations` must be empty for an accepted factory_bug diagnosis").

*Problem:*
- Two readings exist. The narrowing rule makes a non-empty list narrow to `[]` (the intersection with an empty set). The hold-phase sentence makes a non-empty list an unaccepted, malformed result.
- If the list counts as malformed, it goes through the deterministic-failure path (about lines 577–583): a schema-only repair on each same-family route, then retirement.
- The schema text still allows a non-empty list, and the prompt is not told the list must be `[]`. So a model that names operations for a real factory bug may never converge, and the case retires instead of being held.
- The money side is safe either way. What is at risk is the outcome: a real factory bug could end as a retirement.

*Fix (one sentence):* for this phase, either:
- pin the diagnosis output schema and prompt to `affected_operations: []` (`maxItems: 0`), so repair converges; or
- have the code drop the list to `[]` (intersection with the empty eligible set) instead of rejecting it. This is recommended: it matches the existing "narrow only" rule and deletes a failure path.

## Nits

- **n1. Two labels can never be produced.** `writer` and `diagnosis` are in the allowed `gate_or_stage` set (stream-d about line 409, interfaces about line 687), but no row of the table produces them. Delete them, or add the row that produces each.
- **n2. "Non-sealing" is still undefined.** "Non-sealing `run.GATES` names" remains in the stream-d bullet and in interfaces §8. The table says "valid `run.GATES` labels (that list itself excludes G12)". Use the table's wording in both places.
- **n3. Where the completed `diagnosis_state` falls in the write order.** The order is history, then finding, then public marker. Say that the completed `diagnosis_state` (together with `terminal_stop` and the `factory_bug` field) belongs to the last write, not before the finding. If it is written early, `pending_projection` returns `None`, the diagnosis never reruns, and the card is completed with no finding.
- **n4. A replayed diagnosis can meet an existing finding.** A crash after `finding.json` but before the marker leaves the diagnosis pending. A rerun reuses the same `finding_id` and may return a different outcome. Say whether the rerun rewrites the retained finding, or must match it byte for byte, and that a non-factory_bug outcome leaves it as unused evidence.
- **n5. The stop for history that cannot be created needs a name.** interfaces §8 says "otherwise it fails closed" for missing history that cannot be created. Say that it stops as `factory_bug_history_invalid`, the same as unreadable history.

## Heilmeier / readiness

- **Heilmeier:** the objective, the current approach and its limits (no per-attempt receipt), the new approach (hold now, attribute later), the risk bounds (no headroom, cap of 3) and the exams (named replays on 5813be) are all stated.
- **Readiness:** phasing is sound. The hold, validation, refusal and history creation ship now. Resume and attribution wait for B's addendum and a reviewed producer. The tests are pinned to saved card 5813be and its retained ledger. Apart from Ma1, an implementer is left no on-disk format or authority decision.

## Private content and cost headroom

- **Private content:** none exposed. The public field and stage labels come from code, and the finding stays inside the encrypted checkpoint.
- **Cost headroom:** none created. The eligible set is always empty in this phase, so no charge moves to waste, and the case and batch totals are unchanged.

**Verdict: PASS.** No blocking finding is open.

---

The one decision left is Ma1: the design says both that a non-empty `affected_operations` gets narrowed and that it gets rejected. If it is rejected, a model that names operations for a real factory bug could get the case retired instead of held. Narrowing the list to empty in code is the smaller fix. The 7 passing projection tests were run on a clean export of `305c10c`. I did not review your uncommitted edits to `diagnosis.py`, `run.py` and the runtime test.

## Elephant resolution

PASS accepted. Ma1 chooses narrowing: validate the result schema, then intersect affected_operations with the empty code-eligible set; retain raw model output privately, but the accepted finding grants no attribution. N1/N2 use only run.GATES, stress and unknown. N3 writes completed diagnosis_state/terminal_stop/public field together last, after durable history/finding. N4 reuses an existing immutable finding before invoking another model; any differing replay refuses and never overwrites it (a non-factory result cannot delete it). N5 uses factory_bug_history_invalid for any unusable/missing history that cannot safely initialize. No finding rejected. No Murphy row closed.
