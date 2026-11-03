**NOT PASS.** Two blockers are open: B1 (the design builds a second router the code doesn't need) and B2 (the main end-to-end test can't pass as written). This was design round 1 of 2.

Checked at 7a3bc82 in t3-21bef30c, read-only. No tests or suites were run.

## Blockers

**B1 — A second router duplicates the existing replay routing, and the stated reason is not true** (zoom_out, design_critic)
- **Where:** design lines 33–37, 66–75 and 114–142. Code: `diagnosis_dispatch.apply` lines 233–257, `replay` lines 262–287, `queued_inputs` manifest branch `diagnosis.py` lines 771–780.
- **The claim:** line 35 says replaying the older close_to_passing decision "would bind its old checkpoint generation against the new owner."
- **What the code does:** that path has no owner check.
  - `queued_inputs` with an existing manifest only checks the frozen inventory and receipt.
  - `replay`/`validate_result` compare the decision against that manifest's own generation.
  - `journal` checks invocations against ledger reservations. Those survive batch moves; nothing I found clears them.
- **The existing apply already routes every case the design rebuilds:**
  - no row → 0;
  - an admitted successor whose `exhaustion_id` equals the state's ID → `extensions.active` → `writer_receipt` → that ID;
  - a committed successor → `completed_route` → that ID;
  - disabled activation → `extension_comparison_pending` (lines 255–259).
- **What this costs:** `resolved`, `mark`, the admission link, history-anchor reconciliation, the package kind and re-authenticating through `_finding` on every launch all re-implement that logic. Two routers that can disagree also break "delete before adding".
- **Fix:**
  1. Keep one private retained record: the validated close_to_passing state (call it X), written in apply's enabled branch, plus its frozen copy in the factory-bug inputs, as designed.
  2. In B, after the existing reconcile/classify, check frozen core == live record, then restore X in the same `admitted_card` write.
  3. In `_dispatch`, when `resume_factory_bug` returns True and `c.card` now holds a completed close_to_passing state, fall through to the existing reconcile → `queued_inputs` → `replay` → `apply` path instead of `return False`.
  4. After the card is cleared, a crash needs nothing new: the card holds X, so the ordinary replay routes it.
  5. Delete `resolved`/`mark`/link/anchor reconciliation and the extra `_finding` checks.
- If the elephant keeps the current design, it must name a concrete check that shows replay fails across owners. Asserting it is not enough.

**B2 — The resumed comparison reuses an already-exhausted retry allowance, so the final test is not executable as specified** (implementation_readiness)
- **Where:** design lines 131–132 ("Do not reset an exhausted comparison journal") and lines 165–172.
- **The code:**
  - `subsequent_entry` runs the comparison through `gate_attempt.execute(..., attempts=2, journal=evaluator.root/'pair-attempts.json')`.
  - `evaluator.root` is keyed by `Evaluator.identity` (extension id, case hashes, versions). A factory fix changes none of these.
  - `bin/run_validity.retry` keys its count on `{identity, runtime_revision()}`, and `runtime_revision` is an `lru_cache` hash of `factory/*.py` plus a few `bin` files. No test touches it.
- **Effect in tests:** the resumed comparison sees `invalid_attempts >= 2` and raises `InfrastructureExhausted` immediately. "Actual successful entry/progress admission" can never be reached.
- **Effect in production:** the same thing happens for any fix outside the hashed files (launch.sh, VM image, `bin/strategy`'s neighbours). Each one burns a factory-bug resume without running a comparison.
- **Fix:**
  - State the rule: the comparison only gets fresh attempts when `runtime_revision` or the stage versions change; otherwise an immediate re-exhaust is expected and capped at three resumes.
  - In the final test, change a hashed runtime input explicitly (for example, clear `run_validity.runtime_revision.cache_clear()` after an authored source change). Never reset the journal.
  - Add an exam that an unchanged revision re-exhausts with no writer and no extra B debit beyond its one admission.

## Major (if the current design is kept)

- **M1 — When `prepare` runs is ambiguous.** Line 91 says "Before appending any new resume." But line 110 (crash after append, before `mark`) relies on reusing the admission, and `mark` then needs a target. State that `prepare` runs on both the new and the reused branch of `resume_factory_bug` (after `_factory_bug_history`, before `model_runtime.prepare_dispatch`).
- **M2 — The test plan names fixtures that don't exist or aren't pinned.**
  - `HeldResumeTests` does not exist. It is `tests/factory/test_stream_d_held.py::ResumeTests`, built on `test_stream_d_inputs.InputTests.setUp`.
  - "Real extension receipts/records" has no named source. Pin the producers:
    - completed extension history from the real `extensions.admit`/`complete` flow in `test_stream_d_outcomes.OutcomeTests` or `test_stream_d_comparison.ComparisonTests`;
    - the exhaustion → pending → frozen-inputs step from `test_stream_d_comparison.DiagnosisBoundaryTests.check_handoff`.
  - Without this, a hand-authored history could slip into the test that closes the row.
- **M3 — The active-package target is unreachable (YAGNI).** `record_exhaustion` refuses while the last row is active (`history[-1]['outcome_sha256'] is None`). So no real factory-bug hold can exist on an active package, and the "already-held active-package fixture" must be hand-authored. Drop the active-package branch. Under B1's fix, apply's existing `writer_receipt` branch covers it at no cost.
- **M4 — Routing to a committed successor through B replays work that can't change.** When a factory bug follows a completed package (stop `extension_incomplete`), routing to the positive ID makes `run` replay the committed outcome (replay only). It raises `extension_incomplete` again and burns a resume. State this as accepted behaviour, capped at three, and test it. It is still correct for crash recovery after the card is cleared.

## Nits

- Line 134: the early `resolved` check skips `_dispatch`'s lock, reconcile and provider-wait block. Model calls downstream redo these (`pending_call`, `opencode`, `model_runtime`), so it is safe, but say so. This goes away under B1.
- Heilmeier: the objective (lines 5–7) is plain, but the rest leans on "B", "lane 2", "held" and "admission link" without defining them. "Who cares" is only implied.

## Scope assessment

- **Excluding active-extension diagnosis production is honest for the row.** A comparison after a completed extension runs in `subsequent_entry` with no active row. `record_exhaustion` then produces the new pending state and the existing diagnosis produces the factory_bug, as `check_handoff` shows. That needs nothing from lane 2.
- **Excluding legacy reconstruction is safe today.** Diagnosis is disabled, so there are no live held post-extension cases.
- **Package routing:** only completed-package routing is reachable (M3).
- **Row closure:** closing new-stream-d-current-comparison-1 through the named final test is the right exam once B2 is fixed and the M2 fixtures are pinned.

## Skipped checks and risks

- **Skipped:**
  - I did not trace `extension_package.Records`, `comparison.current_pair` or `extension_public_match.verified` internals.
  - I did not check the launch-manifest expected-file test.
  - I did not confirm that ledger reservations survive every carry path; I only found no code that clears them (relevant to B1).
  - No test or suite run, as instructed.
- **Risk:** B1's simplification depends on the X decision's `attempts.json` and inputs staying intact across batches. That is an existing replay assumption, and the diff review should confirm it with a test across a real release change.

## Elephant disposition

Accept B1 and B2 and M1–M4. Replace the second router and linked admission record with one retained completed state, restored by the existing admission and replayed by the existing dispatcher. Validation runs for new and reused admissions before any new append; original retirement priority remains. Pin real fixture producers and changed-runtime versus unchanged-runtime exams; delete the unreachable active-package hold test. Committed-package replay's immutable-result limit is explicit. Main passes the cleared previous card so infrastructure failures cannot become writer feedback. No finding is rejected. Fresh final design review required before implementation.
