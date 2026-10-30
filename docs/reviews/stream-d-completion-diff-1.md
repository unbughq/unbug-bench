# Goldfish diff review 1: stream D, completed writer validation parity

Mode: REVIEW (read-only). Personas: zoom_out, implementation_readiness. Standards: zoom-out, implementation-readiness. Scope: `4f291fb..HEAD` (c62f5f2, 3642c6b) in worktree `t3-21bef30c`, branch `t3/stream-d-implementation`. Reviewer model: Claude. Files read:
- `docs/designs/stream-d.md:1568–1686`;
- `docs/reviews/stream-d-completion-design-1.md` and `-2.md`;
- `docs/ENGINEERING.md`;
- `docs/murphy-register.md`, rows 8–13, 15, 21 and 39;
- `factory/run.py`: `opencode` at 190–220, `resume_provider_wait` at 274–304, `pending_call` at 323–379, `case_hash` at 776, `attack_binding` at 853, `attack_unresolved` at 901, `loop_freshness` at 920ff, and `write_and_attack` at 1015–1470;
- `factory/late_recovery.py:13–56`;
- `factory/budget.py:384–401`;
- `factory/model_runtime.py:45–53` and `:632–642`;
- `factory/diagnosis.py:217–230`;
- `factory/recovery.py:11–48`;
- `tests/factory/test_stream_d_runtime.py:40–95` and `:468–595`;
- the practice fixture file list.

I did not run the test suite.

## Verdict: PASS

There are no blockers and no majors. Four nits are optional.

---

## Checks against the design

**Anchor and order: matches.** The new block is at `factory/run.py:1177–1185`. It sits inside `if modern_writer_unit and not awaiting_stress:` (1172) and is guarded by `resume_writer_validation`, right after the output-hash check at 1175–1176. It comes before:
- the `problems`/`findings_report` load at 1186–1191;
- the shared `if report and problems:` block, with `loop_freshness` and `early_review`;
- the resumed-G1 branch at 1353.

Output-hash verification runs first. Intent validation runs second. The unchanged-repair decision runs third.

**Scope: matches.**
- `resume_writer_validation` (1104) needs three things: `schema_version == 2`, `actor == 'writer'` and `phase == 'completed'`.
- Pending writer receipts still use the `.get` defaults at 1313–1314, unchanged.
- `validated`/`awaiting_stress` receipts never reach the block. The 1165 branch handles them, and the guard is false for them anyway.
- V1 receipts have no `schema_version`, so `modern_writer_unit` stays false and V1 behaviour is untouched.
- Modern stress-tester receipts have `modern_writer_unit` false.
- `final_repair` receipts are written only on the non-modern path (1440ff). Modern raises or refuses first.
- Founder rulings are `None` when `modern` (1023).

**Parity with the uninterrupted check (1332): identical for the same bytes.**
- The uninterrupted path tests `repair_requested and case_hash(c) == before_repair`. The values it uses are the same ones written into the receipt at 1315.
- `output_sha256` is set to `case_hash(c)` in `writer_completed` at 1319. Nothing between that write and line 1332 changes case bytes: `checkpoint_progress` only snapshots.
- On restore, 1175 has already proved `output_sha256 == case_hash(c)`. So `before_repair_sha256 == output_sha256` matches the uninterrupted test exactly.
- The only remaining divergence is deliberate fail-closed. A completed receipt whose `repair_requested` is truthy but not a bool would be judged by truthiness when uninterrupted and refused when restored. No producer emits that: `bool(report or problems)` is always a bool, and V2 pending/completed writer receipts have carried both fields since 753b33e introduced `schema_version=2`. The design accepts this risk ("fail closed instead of guessing").

**No new work before the refusal.**
- Between function entry and 1185, nothing reserves (`pending_call` is reached only at 1324/1401), renumbers or invokes a writer or stress tester.
- `resume_provider_wait` and `reconcile_reservations` at 1023/303 run before the anchor. They existed before this diff, run on every modern entry, and only settle earlier calls. They are not new admission (see nit 2).
- A legitimate completed receipt cannot lose its fields. Both are written at 1315 before `pending_call`, and `{**resume_unit, **writer_receipt}` keeps them. `provider_resume_done`'s pending reset (297) only touches pending receipts. The extension path (`extension_proposal`) is not called from the writer loop.

**The tests discriminate.**
- If the check moved to the resumed-G1 branch, `test_completed_findings_repair_refuses_before_freshness_or_review` (`test_stream_d_runtime.py:571`) would fail. Its receipt carries `findings_report='round-1.json'` and non-empty `input_problems`, so `if report and problems:` would call the patched `loop_freshness`, which raises `AssertionError`. That is not the expected `BudgetError`.
- If the hash order flipped, the variant at :584 (bad `output_sha256` plus `repair_requested: None`) would yield `invalid_recovery_receipt` instead of `writer_output_changed`.
- If the check were removed, `test_unchanged_repair_completion_resume_refuses_without_new_work` (:547) would reach `attacker-1`, and its assertion `calls == ['builder-1']` would fail.
- The type coverage is tight: `0`/`1` are refused by `type(...) is not bool`, and `'F'*64` and `'f'*63` are refused by the regex.
- The case bytes are the hash-verified practice fixture and the 5813be ledger, both from `setUp`. Only model outputs and kills are authored, as the design states.

**Doc claims match the code.**
- No Murphy row is closed, and `docs/murphy-register.md` is not in the diff.
- Row 10 is explicitly left open.
- Cited lines `model_runtime.py:639` and `budget.py:736` match the factory-job cap bypass.
- `DIAGNOSIS_ENABLED = False` (`batch_service.py:21`) matches the diagnosis-off description.

---

## Nits (optional)

### N1: the `g1` "must not be called" guard holds only because of how the test sets up `prev`
- **Evidence:** `run.py:1081–1082` evaluates `not g1(c)[1]["problems"]` before the anchor whenever `prev` has no `failed_gate` and the case is complete. The findings test patches `g1` to fail (:575), but its `prev` carries `failed_gate: 'G1'` (:507), which short-circuits 1082.
- **What goes wrong:** A real round-two resume driven by stress findings, with a `prev` card that has no `failed_gate`, still runs the G1 contract inspection before the refusal. The result is discarded (1174 overrides `skip_writer`), and no model is called. So decisions are unaffected, but the test asserts more than it proves.
- **Fix:** Either drop `g1` from the fail-if-called list in the findings test, or add a comment that the 1082 probe existed before this diff and is out of scope.

### N2: the resumed run is not a fresh process, so the ledger-unchanged assertion is weaker than it reads
- **Evidence:** `completed_writer_control` (:536–539) does not reset `provider_resume_done`/`model_resume_state['done']`. The neighbouring precedent does reset them, at :494.
- **What goes wrong:** The resumed call skips `resume_provider_wait`/`reconcile_reservations` (303), which a real restart runs inside a `ledger_transaction` before the anchor. So `self.ledger.read_bytes() == ledger` (:553, :593) does not cover the resume-time settlement path. Any such write would be settlement of the completed call, not new work. This does not affect the decision.
- **Fix:** Add the two resets after :538, as at :494, so the resume is a real fresh-process resume.

### N3: "done" is stated before this review and the suite run
- **Evidence:** `docs/designs/stream-d.md:1595` says "(small; done in c62f5f2)". The design's own Tests paragraph (:1665–1666) requires "the full required suite and a fresh diff review from another model family". The suite is still running, and this reviewer is Claude.
- **What goes wrong:** Under `docs/ENGINEERING.md` §1, a change passes at merge. If the elephant is also Claude, this review does not meet the design's stated "another model family" condition. ENGINEERING says only "preferred".
- **Fix:** Reword to "implemented in c62f5f2; merged after diff review and suite". If the writer was Claude, also either record the same-family review as acceptable under ENGINEERING's "preferred" wording, or get a non-Claude diff review.

### N4 (forward-looking): the refusal now persists, so item 7 must plan for it
- **Evidence:** After either path refuses `unchanged_repair`, `attack-state.json` stays a completed V2 writer receipt. Every later entry to `write_and_attack` now refuses at 1184 before the writer loop. `unchanged_repair` is not in `recovery.RETRY` (`recovery.py:11`), and diagnosis maps it to stage `stress` (`diagnosis.py:224`).
- **What goes wrong:** The behaviour is correct and consistent: before this diff, a re-entry went to stress on unchanged bytes. But continuation routing (item 7, extensions) cannot start another writer round for such a case without a defined receipt transition.
- **Fix:** No code change now. Add one line under item 7 saying an extension after `unchanged_repair` must replace or advance the completed receipt through B's checkpoint adapter, not re-enter at receipt load.

---

## What passes

- **Zoom-out.**
  - The diff is 9 lines at the single receipt-load point. It closes the semantic gap the design names, and adds no schema, toggle, helper or subsystem.
  - It reuses the existing `attack_unresolved` and `invalid_recovery_receipt` vocabulary and the existing `re.fullmatch(r'[0-9a-f]{64}', …)` pattern from 1130/1136.
  - It also brings back into line a case the design did not name: re-entering a case that the uninterrupted path had already stopped at `unchanged_repair` no longer proceeds to G1 and stress.
  - V1 and pending V2 behaviour are untouched.
- **Implementation readiness.**
  - The code follows the design and its B1/M1/N1/N2 corrections exactly: the anchor, the guard, output hash first, intent validation only for completed V2 writer receipts, and no change to pending receipts.
  - Every test the design names exists: unchanged requested repair uninterrupted (:541) and killed (:547), changed repair resuming without a second writer (:557), and an unchanged first writer with no repair request validating (:564).
  - The findings-driven round two runs with `rounds = 2` and with `loop_freshness`, `confirm_hits`, `early_review`, `early_checks` and `g1` set to fail if called. It covers malformed and missing intent in both fields, and output-hash precedence (:571).
  - Each refusal also asserts the receipt bytes are unchanged and that `builder_rounds` is unchanged.
- **Murphy discipline.** No row is claimed. The test-module docstring and the design both say these are control-flow replays that leave row 10 open, which matches the register's closure rule.

## Reviewer note

The requested goldfish was `openrouter/~deepseek/deepseek-pro-latest` on the
`opencode` provider instance (T3 `delegate_task`). It read the files but ended
its run without emitting a review document. As instructed for that case, this
review comes from a fresh Claude subagent with no conversation history. It is
therefore a same-family review, which `docs/ENGINEERING.md` allows ("preferred",
not required). The design's "another model family" wording is not met.

## Elephant response

PASS accepted. No blocking or major findings; no finding rejected.

- **N3 fixed.** Item 1 now says "implemented in c62f5f2; full suite and diff
  review 1 passed, not yet merged" instead of "done". The same-family review is
  recorded above.
- **N4 fixed.** Item 7 now states that a case refused as `unchanged_repair`
  keeps refusing on re-entry and that an extension must replace or advance the
  completed receipt through B's checkpoint adapter.
- **N1 and N2 deferred to increment 2.** Both tighten test fidelity (drop the
  `g1` fail-if-called guard the `prev` short-circuits; reset
  `provider_resume_done`/`model_resume_state['done']` for a true fresh-process
  resume). Neither changes a decision. Increment 2 rewrites the same resume
  tests for durable intent and will carry both.

## Validation

Command: `uv run --with numpy --with scipy python -B tests/run.py` at 3642c6b
(code identical to c62f5f2).

Result: `154 test scripts run; 0 failed.` Exit status 0. The local full log is
`/tmp/stream-d-completion-suite-142105.log`.

An earlier run to `/tmp/stream-d-completion-suite.log` printed the same summary
but its runner process did not exit and kept starting further test scripts for
over 15 minutes; the cause was not diagnosed. It was stopped and is not counted.

No Murphy rows close. D rows 8, 9, 10, 11, 12, 13, 15, 21 and 39 remain open.
`DIAGNOSIS_ENABLED` stays false. Nothing pushed, merged into factory-simplify,
or changed on main.
