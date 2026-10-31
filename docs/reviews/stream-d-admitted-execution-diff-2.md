I re-reviewed `f029571` against `0d3259f` in read-only mode. **Verdict: passes. B1 is resolved and no blocking finding is left open.** The review text is below, ready to save verbatim.

---

# Goldfish diff review 2: `stream-d-admitted-execution`, diff `0d3259f..f029571`

**Mode:** REVIEW. **Personas:** zoom_out, implementation_readiness. **Standards:** zoom-out-standard.md, implementation-readiness-standard.md.

I read `docs/ENGINEERING.md`, both persona files and both standards. I also read the design, diff review 1, the suite-2 record and the whole diff. I traced the production paths the new tests depend on: `model_runtime` provider-failure handling, `write_provider_wait`, `resume_provider_wait`, `provider_continuation`, and the exception handlers in `run.main`. The design was not skipped.

**Verdict: passes. No blocking finding is open.**

## Scope checks
- **Production code is unchanged.** `git diff 0d3259f HEAD` outside `docs/` and `tests/` is empty. The diff only touches the design doc, two review records, the suite log and the test file.
- **The suite record matches its log.** The log's SHA-256 is `94cb2f62…ae34`, as recorded. The log ends "159 test scripts run; 0 failed." Its `test_stream_d_execution.py` section shows `Ran 11 tests … OK`.
- **The tests pass on an independent run.** I ran `tests/factory/test_stream_d_execution.py -v` myself. All 11 pass, including both new tests. The tests use a `TemporaryDirectory`, and the worktree was still clean afterwards.

## B1: resolved

### `test_writer_provider_wait_resumes_same_intent_through_loop`
- **It uses the real machinery.** The stub raises only at the CLI boundary (`_invoke`). It raises a `BudgetError` carrying `provider_failure={'reason':'quota','scope':'account'}`.
  - The real `ModelRuntime` failure handling turns this into a `ProviderWait`. The test asserts `str == 'provider_wait'`, which is exactly the string `main` checks before calling `write_provider_wait`.
  - The real `write_provider_wait` publishes `terminal_stop == 'provider_wait'`.
  - The real `resume_provider_wait` clears `lease_id` and `invocation_id`.
  - The real `provider_continuation(c, resumed, 'writer')` returns True. That needs a settled, archived wait record and a ledger `wait_settlements` entry, so it exercises real settlement.
- **The same operation and intent are kept.**
  - Fields outside `_WRITER_MUTABLE` are equal to the original both after the resume and at stress entry, after the writer completes.
  - `operation_id` equals the row's `writer_operation_id`.
  - `lease_id` differs from the original, so a new lease was issued under the same operation.
- **No extra writer and no new row.** The calls are exactly `['builder-9', 'builder-9', 'attacker-9']`: one more writer call than the interrupted one, then stress. The `extension-history.json` bytes are unchanged.
- **The end state is right.** It ends with `next_phase == 'extension_comparison'`. `terminal_replays` shows that re-entry refuses with `extension_comparison_pending`, does no work and leaves the receipt bytes unchanged.

### `test_stress_infrastructure_exhaustion_resumes_only_stress`
- **The exception type and label are right.**
  - The raised exception is `InfrastructureExhausted`, and the test asserts it is not a `BudgetError`.
  - So in `main` it skips the `BudgetError` handler. It lands in the `Exception` handler, which uses `isinstance(error, InfrastructureExhausted)` to label it `infrastructure_exhausted`.
  - It is therefore never treated as a scientific stress result or a `rounds_exhausted` stop.
- **The interrupted state is right.** After the interruption, the receipt is `('stress_tester', 'pending')`, with no `exhausted` field and no completed `stress_review`.
- **Only stress reruns.** On re-entry the calls are `['builder-9', 'attacker-9', 'attacker-9']`, with no second writer. `operation_id` is unchanged, and the run ends at the terminal marker with refusing replays.

Both tests do what diff review 1 asked for. The label is checked through the exception type, which diff review 1 allowed as an alternative to going through `main`.

## M1 and N6: addressed in the design
- **M1:** The narrower guarantee is now stated in the design. Binding-keyed `freshness-verdict.json` recovery is kept. The scorecard-only `verdict_path` fallback is lost across `apply`, at a cost of at most one reviewer call under the batch bound, and it is deferred to full-package integration. That is accurate and matches what I traced in diff review 1.
- **N6:** The design now says audit `prepare` copies a workspace before the refusal, and that the refusal comes before Compose, model selection and model work. That is accurate.

## Nits (optional)
- **NIT-1:** The design says the `InfrastructureExhausted` check covers "the exact type". In fact `assertRaises` is an `isinstance` check plus a not-`BudgetError` check, not an exact-type match. That still matches how `main` maps the error, because `main` also uses `isinstance`. Consider rewording to "the type `main` maps".
- **NIT-2:** The writer provider-wait test calls `write_provider_wait` and `resume_provider_wait` directly, not through `main`'s exception handler. Then `execute()` resets the resume flags, so `write_and_attack`'s own `resume_provider_wait` runs a second time. That shows it is idempotent, but only implicitly. This is acceptable as is.
- **The earlier nits are still deferred, as intended.** N1–N5 from diff review 1 remain open, and none of them blocks.

## Zoom-out
The change is proportionate. It adds only tests, plus two paragraphs of design text. It adds no production code, helper, fixture generator or schema. The tests reuse the existing `RuntimeTests` and `ExtensionTests` setup, the saved 5813be ledger fixtures, and the real receipt, reservation and wait machinery. No Murphy row is claimed closed, which is consistent with offline controls.

**To merge:** no further changes are required. List both `docs/reviews/stream-d-admitted-execution-diff-1.md` and this file in the `Reviewed-by:` trailers.

## Elephant response

Pass recorded. B1 was independently verified as resolved. NIT-1 wording corrected to match main's isinstance check. Other optional nits remain deferred; no blocking finding is open. No additional production or test changes follow this review.

