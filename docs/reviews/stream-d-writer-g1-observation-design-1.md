**Verdict: PASS.** Nothing blocks this design. I found two Major issues worth fixing before or during implementation, and three Nits.

I checked the design against the actual code: `factory/run.py` (`write_and_attack` at lines 1159–1680, `g1` at 1855, `complete_writer` at 380); `factory/extension_package.py` (`Records`, `stress`, `run`); `extension_compare._pending`; `gate_state`; `bin/run_validity.retry`; and `tests/factory/test_stream_d_execution.py`. I ran one existing test locally, with no network: `PackageRecordTests.test_real_g1_retains_practice_contract_result`. Real G1 on the saved practice case returns `ok=False` with one problem: `'case.json source differs from the run argument'`. So a real failed G1 can be produced for the tests.

## Blockers
None.

## Majors (not blocking)

**M1. A G1 version change shows up as a different stop label than the design says.**
- **Where:** "Records already bind…" paragraph, and the tests bullet "changed G1 version refuse before invoke".
- **What happens:** the package's `Records(c, r, row)` has no `expected_versions`, so `load` refuses with `extension_comparison_pending`. But `extension_package.run` deliberately catches exactly that label from `write_and_attack` and carries on into `stress()`. `stress()` then refuses with `extension_execution_pending`, because the writer receipt's actor is still `writer`.
- **Effect:** state is still safe. G1 is never called and no receipt is written before the line-1549 check. But the label the caller actually sees is not the one the design promises.
- **Fix:** either say the stop seen through `package.run` is `extension_execution_pending`, or test `writer_g1` directly. Have the test assert the label for the layer it uses. Pick one so the implementer doesn't have to.

**M2. The design never says why it doesn't simply re-run G1 at the end.**
- **Where:** Problem / Change.
- **Alternative:** the later terminal increment could call the existing `Records.capture('G1', g1)` when it runs. That needs no new callback in `write_and_attack` and no new method.
- **Why it might still be the wrong choice:** a re-run uses the current G1 version and current settings. The failure seen here depends on `c.args.source`, so a re-run could pass and contradict the receipt's `validation_problems`. Keeping the observation that actually rejected the writer is better evidence.
- **Ask:** add one sentence recording that reason. The proposed change is small (one keyword argument, about 15 lines in `Records`), so this is a documentation gap only, not a scope problem.

## Nits

1. **Callback shape.** The design says `(writer_g1 or g1)(c)` takes `c`, while `Records.writer_g1(c, invoke)` takes two arguments. State the binding: the package passes `lambda c: records.writer_g1(c, lambda: r.g1(c))`, with `r.g1` resolved when called so that patching `run.g1` (the "forbidden g1" test) still works.
2. **The real failure is about the run's settings, not the case content.** The practice failure is `case.json source differs from the run argument`. The test should assert that exact problem list. The design should describe it as a real G1 failure rather than "real contract diagnostics", so nobody reads it as a case-content defect.
3. **`g1`'s `precheck_problems` short-cut** returns `False` without running the contract. Nothing in the extension path sets it today (`run.py` lines 577/799–851 are outside extension mode), so no change is needed. Recording one sentence of that assumption is optional.

## Checks that confirmed the design

- **Exactly two call sites.** There are exactly two post-writer G1 calls with an extension active: line 1528 (fresh writer) and line 1549 (completed or done-writer recovery). At lines 1211 and 1258, `extension is None` short-circuits before G1. Line 1675 is unreachable in modern mode.
- **Crash between record and receipt.** `complete_writer` writes `phase=completed` before G1. A kill after the record rename therefore resumes through `resume_writer_validation`, which reaches site 1549, where the retained failure replaces the G1 call. The run then goes validated → exhausted → `rounds_exhausted` → `stress()` refuses with `extension_execution_pending`. That is the unchanged hold, as the design claims.
- **Restart after the receipt is written.** Once the receipt is validated and exhausted, a restart stops at the `saved['exhausted']` check before reaching G1, so the record is never replayed there. The legacy case with no record behaves the same as today.
- **A retained failure can't leak into the final gates.** A G1 failure always exhausts the extension's single round, so `stress` is never saved and `run_gates`/`replay` never sees a G1 record. Refusing pass-shaped records closes the only way a stale pre-stress card could be replayed.
- **Identity and tamper checks.** `Records.load` already checks the writer operation id, round, case hash, record digest, support-file digests and version, so no new identity rule is needed. G1's `inputs` already exclude `freshness.jsonl`.
- **Exceptions and retries.** `g1`'s `retry(..., interruption=BudgetError)` raises on infrastructure exhaustion, never returning a pending-shaped result, so passing exceptions through unchanged is correct. `_pending` filtering matches `save`'s own guard.
- **Tests can be built.** The existing `writer_call_done` patching in `test_stream_d_unchanged.py` and the `run.g1` patch pattern in `ExecutionTests` cover the done-writer and forbidden-g1 cases.
- **Branch base.** HEAD `e81c532` is a single docs commit on top of `655592a`, so the requested base is already present.
- **Heilmeier:** objective, current practice, approach, payoff, risks, cost, timeline and midterm/final exams are all present. Murphy rows: supports 9 and 13, closes none, which is consistent with the scope.

## Writer disposition

PASS accepted. M1 and M2 and all three nits are incorporated in the design: package-visible versus direct callback labels, retaining the actual rejecting observation instead of re-running at terminal completion, exact callback binding, the real source-setting diagnostic, and the precheck assumption. No production edits before land9 merges.
