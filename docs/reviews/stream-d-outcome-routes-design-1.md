# Goldfish design review: `docs/designs/stream-d-outcome-routes.md` (design commit f121ad1)

**Reviewer:** fresh read-only goldfish, `Mode: REVIEW`
**Personas:** `zoom_out`, `design_critic`, `implementation_readiness`
**Standards:** `heilmeier-standard.md`, `implementation-readiness-standard.md`

**Read:**
- `docs/ENGINEERING.md`
- the design under review
- `factory/diagnosis_dispatch.py`, `factory/extensions.py`, `factory/diagnosis.py`
- `factory/run.py`: `pending_call`, `write_and_attack`, `main`
- `factory/budget.py`: `reconcile_reservations`, `reclassify_factory_bug`
- `factory/late_recovery.py`: `invalidate`
- `docs/designs/interfaces.md` §8
- `docs/designs/stream-d.md` §§ first-extension and one-extension
- lane 2's `docs/designs/stream-d-package-completion.md` and `factory/extension_package.py`, at lane 2 HEAD 40822e7, read-only
- `t3/batch-carry-over` (f55c8e0): `factory/diagnosis.py`, `factory/carry_over.py`
- `docs/murphy-register.md`: rows 9 and 13, and `new-batch-service-4`

## Summary

The design points the right way. The diagnosis model chooses only an enumerated outcome. Code builds the proposal. Money flows only through the existing `pending_call` reservation against B's commitment. There is no new launch path, allowance, schema or resume counter. The design also says openly that factory-bug waste attribution is not delivered.

It is not ready to implement:
- The package seam it defines collides with code lane 2 has already committed.
- The fresh-admission writer step leaves several receipt and prompt choices to the implementer.

## Blockers

### B1. The seam and file ownership contradict lane 2's committed code

**Severity:** Blocker
**Scope:** §Problem and scope, lines 12–18; §Validated routing, lines 31–38; §Small lane-2 seam, lines 40–62.

**Finding.** The design says lane 1 "owns diagnosis_dispatch". It also says lane 1 will replace `main`'s writer-only stop with `diagnosis_outcomes.run(c, runner, prev, number)`. Lane 2's commit 40822e7 has already edited both places. That commit is not an ancestor of f121ad1.
- **`diagnosis_dispatch.apply`:** lane 2 looks up the last row when no row is active, and for a completed row calls `extension_package.completed_route`. It still returns the ID only on `resume`.
- **`run.main`:** lane 2 replaced `write_and_attack(...); raise extension_comparison_pending` with `extension_package.run(c, r, prev_card, extension_id)`. It bypasses `build` with an `elif` and guards `validate_and_repair` with `elif extension_id is None`.

The consequences:
- **Same lines, both lanes.** Implementing this design as written edits the same lines a second time and gives `main` two different callees.
- **The 0 sentinel crashes in lane 2's code.** Lane 2's `run` refuses any `number` that is not the last history row's ID. A 0 that reaches lane 2's `main` seam would stop as `extension_history_invalid`.
- **`entry()` has no owner.** `extension_package.entry(c, runner) -> snapshot` does not exist in lane 2's module (it has `refuse`, `workspace`, `project`, `stress`, `completed_route`, `run`). Lane 2's design defers "entry capture and current-version comparison" to a later slice that has no design yet. Lane 2 has not agreed to the signature, return contract or raise semantics this design gives it.

**Recommendation.**
1. Say that lane 1 is implemented on top of lane 2's merged commit. Either merge lane 2 into `factory-simplify` first, or rebase onto it, and state the merge order.
2. Remove positive-ID routing and the completed-row `completed_route` call from lane 1's change list. Lane 2 already delivered them; cite 40822e7.
3. Narrow lane 1's `main` change to one thing: a `number == 0` branch that admits and then calls lane 2's existing `extension_package.run` with the new positive ID. State that `extension_package.run` never receives 0.
4. Write the `entry()` contract into lane 2's design or checklist as lane 2's commitment, or mark it as a lane 2 prerequisite. Lane 1 should not define it unilaterally.

### B2. The fresh-admission writer step leaves design choices open and duplicates `write_and_attack`

**Severity:** Blocker (zero-decision rule)
**Scope:** §Admission and one writer, lines 73–85.

**Finding.** The ordinary writer step in `run.py` (around lines 1467–1483) builds a receipt with these fields:
- `round`, `binding`, `report`, `round_limit`, `repair_pending`
- `release_rereviews`, `release_review_attempts`
- `actor`, `before_repair_sha256`, `repair_requested`
- `findings_report`, `input_problems`, `next_phase`, `output_sha256`

It then calls `prompt('builder', run_context(c, round=n, attack_report=..., precheck_problems=...))`.

The design says only "input_problems from the code-recorded failed gate/stress evidence" and "the existing release-rereview fields". That leaves the implementer to decide:
- which card or work fields feed `input_problems`, and in what form (`failed_detail`? the stress report findings? both?);
- what `findings_report` and `attack_report` point to: the last `attacks/round-N.json`, or `None` after a gate failure;
- what values `release_rereviews` and `release_review_attempts` take: copied from the previous receipt, or reset;
- how `repair_requested` is derived;
- whether `attack_binding(c)` and `before_repair` are captured before or after `entry()`.

`pending_call` rejects any receipt that is not `writer_intent_valid`. `extensions.retain_writer` freezes every field outside `_WRITER_MUTABLE` forever. A wrong choice here is permanent for that extension ID. Writing a second, parallel copy of this receipt and prompt construction is also exactly what ENGINEERING §4 warns against ("Delete before adding").

**Recommendation.** Pick one of these and specify it exactly:
- **(a) Reuse the writer loop.** `write_and_attack` accepts `extension_proposal` and passes it to its existing `pending_call` site. Its one-round range for the new ID already exists in stream-d.md.
- **(b) Extract one helper.** Pull the ordinary receipt-and-prompt construction into a single helper called from both paths.

Either way, give a field-by-field source table for every frozen field, including the gate-failure and stress-failure cases.

## Major findings

### M1. Factory-bug waste is deferred honestly but tracked nowhere, and its consequence is understated

**Severity:** Major
**Scope:** lines 99–107.

**Finding.** Deferring the waste attribution is correct: interfaces §8 requires empty eligible sets until a reviewed producer exists. But the design records the gap only in prose ("completion reporting must identify it"). The gap is also more than a labelling problem:
- **It costs the resumed case real headroom.** Until reclassification exists, spend caused by a factory bug stays in the case's ordinary `spent_usd`. The ordinary writer admission check (`run.py` around lines 436–438, `spent_usd + maximum > ordinary_limit_usd`) then counts it against the resumed case.
- **This is the exact loss the rules forbid.** It is the "our-bug losses on a separate line" property ENGINEERING §3 requires.
- **The ledger mechanism already exists.** `budget.reclassify_factory_bug` (`budget.py:423`) already performs the reclassification. Only the code-linked producer of eligible operations is missing.

**Recommendation.**
- Add a branch-local Murphy row (`new-stream-d-outcome-routes-1`) for "factory-bug resume spend is charged as ordinary case spend". Name its owner and the follow-up design.
- State that the producer must feed `reclassify_factory_bug`, not a new path.
- State in the design's exit criteria that the factory-bug route is "hold + retire only, attribution open".

### M2. The three-resume test depends on an unmerged B branch

**Severity:** Major
**Scope:** lines 15–18, 91–97, 121–125.

**Finding.** The three-resume limit and the `retired_factory_bug_limit` refusal exist only on `t3/batch-carry-over` (its `diagnosis.py` around line 484). They are not in this branch's base. The test "A held case reaching three resumes must retire through B's carry-over refusal" cannot be written against f121ad1.

**Recommendation.** State the merge order: carry-over must merge before lane 1's lifecycle exam. Either name the post-merge test file and assertion, or move that assertion out of lane 1's test list and into the integrated exam. Keep `new-batch-service-4` B-owned, as the design already says.

### M3. A crash between admission and `on_admitted` leaves gate-continuation state that is never cleared

**Severity:** Major
**Scope:** lines 78–84.

**Finding.** In the extension branch of `pending_call`, the steps run in this order:
1. `retain_writer`
2. `admit`: history appended
3. `admitted()`: attack-state written
4. `on_admitted()` (around lines 441–457)

A kill after step 2 and before step 4 leaves `gate_continuation` and `gate-continuation.json` in place; `late_recovery.invalidate` is what clears them. The restart then takes the positive-ID route, `extension_package.run` → `write_and_attack(extension_id=…)`. Nothing on that route is specified to run `invalidate` again.

**Recommendation.** Make invalidation idempotent and run it at positive-ID entry for an active row whose writer has not completed. Alternatively, prove that a stale continuation cannot be consumed by the package traversal. Add a kill-point test at that window.

### M4. The test plan is not executable as written

**Severity:** Major
**Scope:** lines 115–127.

**Finding.**
- **No test file is named.**
- **Kill points are not enumerated.** Needed: before reservation; after reservation and before `admit`; after `admit` and before `on_admitted`; mid-writer; after writer completion and before `package.run`.
- **One phrase is undefined.** "Include actual main routing and checkpoint refusal so model work cannot bypass B": which refusal, under which input, with what expected stop label?
- **The orphan-reservation charge is not asserted.** "Interruption before admission consumes no ID" is true, but `reconcile_reservations` will charge the orphaned writer reservation's full maximum on restart (`budget.py:406–420`). The test should assert that charge and its single booking explicitly.

**Recommendation.** Give a table of kill points, the expected restart route and stop label for each, and the exact assertions on the ledger and history.

### M5. Heilmeier standard gaps

**Severity:** Major (non-blocking)
**Scope:** whole document.

**Finding.** There is no cost section: offline tests cost $0, and production extensions draw on B's commitment with no new authority. There is no timeline, and no separate midterm and final exam. Risks and payoff are scattered. Lane 2's design shows the expected form.

**Recommendation.** Add a short objective / cost / timeline / exams block.

## Nits

- **N1. The 0 sentinel.** Zero means "admission required", but lane 2's `run` treats any non-matching number as invalid history. Assert at the single consumer (`diagnosis_outcomes.run`) that 0 is turned into a positive ID before any package call. Never let 0 reach `main`'s package seam.
- **N2. Fewer files.** `diagnosis_outcomes` would hold one admission routine. It could live in `diagnosis_dispatch.py`, which lane 1 already owns, to keep the file count down. This matters less if B2 is resolved by reusing `write_and_attack`.
- **N3. Name the propagation sites.** Name the three call sites whose `apply` return value is currently discarded: `diagnosis_dispatch.py:272` (replay), `:325` (valid journal, no decision), and `:428` (inside `invoke`'s `while True`).
- **N4. Cite the stress-pass rule.** `extensions.propose` (`extensions.py:396`) retires a first extension as `retired_no_progress` when the stress stage did not pass. This is intentional (stream-d.md:251–253), but it means a `stress_review_unresolved:rounds_exhausted` exhaustion with a `close_to_passing` diagnosis always retires. Cite this so testers don't file it as a defect.
- **N5. Name who clears the stale stop label.** `apply` writes `status='stopped'` and `terminal_stop='extension_comparison_pending'` to the card and scorecard before returning an ID. State that lane 2's stress-pass clear is the only place this label is cleared, and that admission does not clear it.
- **N6. Readability.** Lines 22–29 pack four routing rules into one paragraph. A four-row table (no row / active same exhaustion / active other exhaustion / completed same or other exhaustion) would be clearer.

## Assessment

| Area | Assessment |
|---|---|
| Explicit unresolved scope | Honest about waste attribution and Murphy closure ("closes none"). The open item still needs a register row and an owner (M1). |
| Trust boundaries | Sound. Model output is reduced to an enumerated outcome. Code builds the proposal. No prose becomes feedback or authority. Money goes only through `pending_call` reservations against B's commitment. The 5-extension limit is enforced before scientific work, and progress is checked same-version through `extensions.propose`. |
| Interruption correctness | Mostly inherited from correct existing seams. One gap remains (M3), and the kill-point coverage is unspecified (M4). |
| Minimal package seam | Not yet minimal or agreed. It duplicates code lane 2 already committed and invents an `entry()` contract lane 2 has not accepted (B1). |
| User requirements | All three routes: present, with factory-bug waste explicitly open. At most 3 resumes via B's carry-over, no duplicate counter: respected. At most 5 extensions, one writer + stress + gates, same-version progress: respected in intent, but the writer construction is under-specified (B2). |

## Verdict

**Not passing.** Two blocking findings are open (B1, B2). Re-review after the design:
- is rebased onto lane 2's committed seam with the merge order stated;
- has an agreed `entry()` contract;
- fully specifies the extension writer receipt and prompt, preferably by reusing `write_and_attack`.

---

Elephant disposition: all findings accepted; no rejection. Revision 2 merges lane 2 baseline 40822e7, makes entry an explicit dependency, extracts shared writer request/feedback helpers, and specifies restart tests. Attribution remains a separate required design, tracked in the register. Fresh review must judge these corrections.
