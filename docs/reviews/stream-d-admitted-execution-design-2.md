# Goldfish design review 2: `docs/designs/stream-d-admitted-execution.md`

**Mode:** REVIEW. **Personas:** zoom_out, design_critic, implementation_readiness. **Standards:** heilmeier-standard.md, implementation-readiness-standard.md, zoom-out-standard.md.

I reviewed read-only in worktree `t3-4ac6b632` at HEAD `80d16ea`. The tree has the untracked revised design, the untracked review-1 file, and an uncommitted `stream-d.md` checklist diff. I read the revised design and review 1. I checked them against:
- `factory/diagnosis_dispatch.py`: `apply`, `replay`, `_dispatch`, `dispatch`, `invoke`, `STOPS`, `CARRY`;
- `factory/extensions.py`: `active`, `writer_continuation`, `_WRITER_MUTABLE`, `_writer_shape`, `retain_writer`, `writer_receipt`;
- `factory/run.py`: `write_and_attack` (1120–1590), `build`, `main` (3230–3300), `complete_writer`, `writer_intent_valid`, `loop_freshness`, `confirm_hits`, `attack_unresolved`, `g1`, `resume_provider_wait`;
- `factory/diagnosis.py`: `exhaustion`, `record_exhaustion`;
- `factory/late_recovery.py`: `gate_marker`, `stop_defect`.

**Verdict: passes. No blocking finding is open.** All three review-1 blockers are resolved in the design text, and the code supports each resolution. M1–M5 are resolved. Two new Major findings remain. They should be fixed in the design before or during implementation, but neither leaves a spend or correctness decision unbounded enough to block.

---

## Verification of review-1 blockers

### B1. Guarded entry and modes: resolved
- **Seam.** The design names it: an optional keyword-only `extension_id=None` on `write_and_attack`. The guard `extension_id is None` covers the whole selection and prototype block (run.py 1133–1179), including the `complete` calculation and the `elif` statement/admission branch. So `statement_precheck`, `reselect_candidate` and `opencode(... "builder-prototype")` cannot run for admitted work, even when case files are missing.
- **Identity.** It is the integer `extension_id`, and it is checked against the active row. `writer_receipt` and `writer_continuation` already enforce `receipt['extension_id'] == row['extension_id']`.
- **`main` insertion.** It captures `dispatch`'s return (today ignored at run.py 3259) and accepts only an `int`. It refuses `dry_run`, `rehearse_only`, `audit_fairness`, `late_gate_rehearsal`, `statement_only`, `skip_build`, `audit_source` and `salvaged_from` with `extension_execution_mode_invalid`. It skips `raised_limits`/`restore_gate_crash`, replaces `build(c)`, and raises `extension_comparison_pending` unconditionally on return. So `validate_and_repair`, the audit branch and the seal are unreachable on success.
- **Code check.** All modes the review asked about are covered. Skipping `build()` also skips `build`'s own `freshness_first`/`ensure_freshness` and its `late_defect_needs_ruling` re-injection (run.py 536–559), which is correct for this route.
- **Remaining gap.** The design does not say where `prev` comes from (Nit N1).

### B2. failed_gate stress replay: resolved
- **Fix.** The design strips `failed_gate`/`failed_detail` from a copy of `prev` and skips `restore_gate_crash`.
- **Effect.** With the stripped copy, the stress-recovery condition at run.py 1301 (`… and not prev.get("failed_gate") and n > 0`) holds for a stress receipt at the admitted round. The pending stress round therefore resumes, instead of falling to `report = None` and ending in an empty `range(n+1, n+1)`.
- **Other `prev` uses.** The same copy neutralises `prev['failed_gate']` in the problems block (1182), `skip_writer` (1187) and `transient_resume`. The post-loop `late_gate = prev.get('failed_gate')` (1572) cannot be reached on the modern path, because the `if modern:` block at 1546 always raises first.
- **Feedback.** The writer's feedback still arrives through the admitted intent's `input_problems`.
- **Test.** The test "pending stress from a failed-gate origin" is listed.

### B3. Finished receipt, no reroll: resolved
- **Early review.** `early_review` (G8/G9) is skipped at every call site (1367, 1399, 1541). `loop_freshness` stays, and the design gives the reason.
- **Success marker.** It uses existing fields: `next_phase='extension_comparison'` on the attack receipt. The code already sets `phase='validated'` at 1526, before `loop_freshness`, so `next_phase` is the only distinguishing field. That is unambiguous, because ordinary stress receipts carry `next_phase='gates'`.
- **Failure marker.** It reuses the existing `exhausted=True` and `stop_reason` publication at 1546–1550. That publication covers every modern loop exit:
  - stress findings at the ceiling;
  - writer validation failure via `continue`.

  The writer-receipt form is accepted on replay because `exhausted` and `stop_reason` are in `_WRITER_MUTABLE`.
- **Re-entry check.** It sits before freshness, early checks, stress and writer calls. It authorises only a stop, and malformed evidence refuses.
- **Tests.** Two resumes after success and two after exhaustion, plus a lagging scorecard, are listed.
- **Placement detail.** One detail can contradict the "zero gate calls" test (Major A1).

## Verification of M1–M5
- **M1: resolved.** `round_limit == row.round` is enforced in `retain_writer` and `writer_receipt`. Stress receipts must match the round exactly. The ceiling comes from history, not `args.rounds`. The `0 <= n <= saved_limit` parse then holds at `n == saved_limit`.
- **M2: resolved.** Only `replay` passes `resume=True`. The second `apply` call inside `_dispatch` (valid journal, no decision file) and `invoke` keep the unconditional stop. That is correct: no admission can exist before `decision.json` exists.
- **M3: resolved.** `row.exhaustion_id == manifest.exhaustion_id` is required, with `diagnosis_input_invalid` on mismatch, and it is tested.
- **M4: resolved.**
  - Immutable-intent preservation is limited to admitted writers.
  - The binding hash fix applies to all modern writers. It is a pure consistency fix, because every modern writer receipt already carries `binding_sha256` (run.py 377, 445, 452). Only the 1446 update omits it.
- **M5: resolved.** The plain objective, impact and cost are present (lines 3–13).

---

## Major findings

### A1. The `skip_writer` heuristic still runs `g1`, before the terminal-marker check
- **Severity:** Major (implementation readiness; it contradicts the design's own test at lines 116–118)
- **Scope:** design lines 42–44 and 80–83; run.py 1187–1188
- **Finding:** The design keeps the later `skip_writer` heuristic, with `complete=False`. But `skip_writer` is also true when `prev['models_used']` has any `attacker*` key, and an admitted case always has one. When it is true, the heuristic calls `g1(c)`, which runs `CaseContract` through `sh` and the infra-attempts retry. This happens at line 1187, before the receipt block, and so before the design's "after history/receipt identity validation" check. A terminal re-entry would therefore run the G1 contract every time. That breaks "zero … gate calls".

  The heuristic's value is also dead for admitted work. Every admitted path overwrites `skip_writer`:
  - for a writer receipt, at 1272;
  - for a stress receipt, at 1358/1372.
- **Guidance:** For `extension_id` set `skip_writer=False` outright, with no `g1` call. Place the terminal check immediately after `writer_receipt` and the attack-receipt read at function entry. State the position explicitly: before line 1182 in today's numbering.

### A2. Other stops inside the admitted round are not enumerated, and some re-enter into repeated paid work
- **Severity:** Major (design_critic, an unmitigated risk; it extends N3 and B3)
- **Scope:** design lines 80–93; run.py 1006–1008, 1232, 1354, 1086–1090, 1365/1538
- **Finding:** The terminal markers cover only success and loop exhaustion. The admitted round can also end in these stops:
  - `attack_unresolved` with any of: `unchanged_repair`, `writer_output_changed`, `case_changed_during_review`, `unfinished_validation`, `unfinished_diagnostic`, `interrupted_review`, `missing_or_malformed_report`, `invalid_recovery_receipt`;
  - `stress_validation_exhausted`;
  - `freshness_public_match` or `freshness_unresolved`.

  None of these writes a marker, so every re-entry goes back through the receipt machinery:
  - Most re-stop deterministically with no model call. Examples: `unchanged_repair` at 1279, and freshness, which reuses `freshness-verdict.json` through `confirm_hits`.
  - `interrupted_review` and `missing_or_malformed_report` are different. On a modern receipt they take the re-review branch, and modern skips both the `rereview_limit` check (1232) and the `exhausted` refusal (1354). So each resume re-runs the paid stress round. Only the batch money bound limits it.

  `freshness_public_match` also writes `gates.G2='fail'` and `failed_gate='G2'` into the card mid-round (1084–1088). That is a gate result produced inside an increment that "stops before final gates". The carried `failed_gate` is then stripped on the next entry, as B2 requires.
- **Guidance:** Add one sentence and one table row per class:
  - infrastructure-type stops (`interrupted_review`, `missing_or_malformed_report`) are retried under existing modern semantics and the batch money bound, and that retry is intended;
  - scientific stops re-stop without model calls;
  - a freshness public match keeps its G2 failure label, and the next increment owns that label.

  Add these labels to the enumerated interruption tests, or state that the existing ordinary suites cover them unchanged.

---

## Nits
- **N1.** Name the source of `prev` in `main`. `build` reads `scorecard.json` (run.py 523), and `apply` has just rewritten that file from `c.card`. `main` also holds `prev_card`, the checkpoint card. The two differ in non-`CARRY` keys.
- **N2.** Name all three success-return sites that must publish `next_phase='extension_comparison'`: the pre-loop recovery at 1369, the freshness-cleared recovery at 1401, and the in-loop site at 1543. "A successful admitted stress round" covers them, but a kill-recovered pass returns from the first two.
- **N3.** The design's `budget_exhausted` with `exhausted=True` label (line 83) cannot arise on the modern path. The `break` with `stop_reason='budget_exhausted'` at 1411 is non-modern only, and modern money refusal raises from the reservation. The label is harmless but misleading. Keep only `rounds_exhausted`, or note it as defensive.
- **N4.** `apply(resume=True)` publishes `status='stopped'` and `terminal_stop='extension_comparison_pending'` to `scorecard.json` before execution starts. That is the same label as a completed round. The design already says the receipt, not the card, is the completion signal. Add that no consumer may read this card label as evidence that the round ran.
- **N5.** "Add execution cases as needed" (line 108): name the target test files, for example `tests/test_stream_d_dispatch.py`, `tests/test_stream_d_admission.py`, and a new `tests/test_stream_d_execution.py` if intended.
- **N6.** The Murphy citation is still correct: row 9 is open and this design closes no row. The `stream-d.md` checklist diff matches this scope.

## Confirmed sound
- **Lock.** `_dispatch` returns from inside `with c.model_dispatch_lock`, so the reconciliation lock is released before any writer call.
- **No new spend authority.** `record_exhaustion` returns silently while history is active (diagnosis.py 132–142). An `extension_comparison_pending` or `rounds_exhausted` stop cannot open a new diagnosis.
- **Spend path.** The writer still goes through `pending_call` → `writer_continuation` → the existing reservation. No new money authority, allowance or ledger is added.
- **No second writer.** Writer validation failure (`continue`) and stress findings both end at the history-round ceiling, which leads to `exhausted=True` and `rounds_exhausted`. No `round+1` exists, and the final-repair `opencode("builder-precheck")` cannot be reached on the modern path.
- **Reuse.** The design reuses the existing loop, receipt fields and phase vocabulary. It adds no new file, schema or helper module. Zoom-out: proportionate.

**To pass (already met):** no blocker is open. A1 and A2 should be written into the design before implementation, because the diff review will check the "zero model/freshness/gate calls" and interruption-label tests against them.

## Elephant response

A1–A2 and N1–N5 accepted. Entry checks precede every heuristic; admitted skip_writer starts false. Retry classes, checkpoint-card source, all three success sites and defensive budget marker are clarified in the design. No findings rejected.

