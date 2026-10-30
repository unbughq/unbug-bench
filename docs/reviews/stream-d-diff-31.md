# Review: stream-d diff 30. PASS (0 blockers, 0 majors, 2 nits)

**Reviewer:** fresh goldfish, read-only, `Mode: REVIEW`, no conversation history. Personas: zoom_out, implementation_readiness. Standards: zoom-out-standard, implementation-readiness-standard.

**Scope:** `git diff 55752f6` against the worktree `/Users/bugsincode/.t3/worktrees/unbug-bench/t3-21bef30c`. That covers two things:
- **Commit `239c6a0`**, "Reject incomplete extension receipts before reservation", which is a cherry-pick of `9ec3a12`. It touches `factory/run.py` (+1), `tests/factory/test_stream_d_admission.py` (+7), `docs/designs/stream-d-extension-admission.md` (+8/−1) and `docs/reviews/stream-d-diff-29.md` (+9).
- **An uncommitted edit** to `docs/designs/stream-d.md` (+5/−5), which records the founder decisions of 2026-10-30.

**Reviewed against:** the commit message, `docs/designs/stream-d-extension-admission.md`, and the N1 finding in `docs/reviews/stream-d-diff-29.md`. I did not look at `.stream-d-next/`.

## Verdict

**PASS.** The change fixes N1 exactly as diff 29 asked and does nothing beyond the receipt guard. There is no active-extension recovery, no new caller, and no claim that a Murphy row closes.

## Findings

### Correctness: no issues

- **The guard sits in the right place.** `run.py:337` adds `not isinstance(receipt.get('binding'), dict)` to the existing receipt-contract refusal. That check runs before `extensions.verify_proposal`, `model_router.await_lease`, `reserve_invocation` and `extensions.admit`.
  - A receipt with a missing, `None`, list, string or `False` binding now fails with `extension_reservation_mismatch` before any lease is taken. No extension ID is used up.
  - This closes the diff-29 N1 path: history was published, then `admitted()` raised `KeyError('binding')` at `run.py:367`.
- **Short-circuit order is safe.** `isinstance(receipt, dict)` is checked before `receipt.get`, so a receipt that is not a dict still refuses cleanly.
- **The ordinary (non-extension) path is untouched.** The guard only runs inside `if extension_proposal is not None`. Ordinary writer and stress-tester admission behave exactly as before.
- **Design text matches the code.** The pre-lease contract in `stream-d-extension-admission.md` line 43 now lists "a dictionary `binding`", and the code enforces exactly that.

### Tests

- **The new test** is `test_missing_or_nondictionary_binding_refuses_before_admission`. It reuses the existing `refuse` helper, which:
  - patches `await_lease` to raise `AssertionError('lease before verification')`;
  - asserts the ledger bytes are unchanged;
  - asserts there is no extension history, no snapshots, no `attack-state.json`, `builder_rounds == 0`, no callbacks and no writer calls.

  That covers every outcome the design asks for: no lease, reservation, history, receipt, callback or writer.
- **The fixtures are real saved artifacts.** The test uses the same setup as the rest of the file: saved practice bytes and the 5813be ledger, via `RuntimeTests.setUp`. It adds no new authored fixtures.
- **Focused run:** `python3 -m unittest tests.factory.test_stream_d_admission` ran 19 tests and passed. That matches the "19 admission tests pass" claim in diff-29's N1 correction section.
- **Mutation check:** I deleted the guard line in a throwaway copy of HEAD in the scratchpad. The worktree was not touched, and I confirmed `factory/run.py` was still clean afterwards. The new test then **failed** with `AssertionError: lease before verification`. So the test is not tautological; it really depends on the guard.

### Process

- **The design-step skip is allowed.** ENGINEERING step 2 says: "A fix under about 20 lines with an obvious cause may skip the design. It still gets step 5." The source change is one line, with a 7-line test, and the cause was identified in diff 29. The docs say the full suite and this fresh diff review are still required. The suite result is not claimed here (see below).
- **No Murphy row closes.** The design addendum, the diff-29 addendum and the commit all avoid claiming a row closure, activation or readiness. Correct.
- **Founder decisions.** The `stream-d.md` edit replaces the "parent ruling, founder has not separately confirmed" wording with founder decisions dated 2026-10-30:
  - cumulative `max_total_calls` is removed for new-schema cases and their extensions, and call counts remain telemetry;
  - dollar ceilings apply to paid routes only;
  - the 47 old cases are retired;
  - cb5e2 and 14d35 are set aside.

  It keeps the historical D1 metadata and the per-invocation, time, route-maximum and `bin/run-exam` protections. No other line in `stream-d.md` still describes the `max_total_calls` change as unconfirmed.

### N1 (nit): the `stream-d.md` edit is uncommitted

- **Where:** `docs/designs/stream-d.md`, lines 1076–1080. `git status` shows it as ` M`, and it is not part of `239c6a0`.
- **Fix:** commit it with this correction, or in its own docs commit, before merging. Otherwise the founder-decision record will not be in the merge that this review is cited in.

### N2 (nit): "Money … still bound every call" now reads as overbroad

- **Where:** `stream-d.md:1083`, "Money and the absolute batch deadline still bound every call." This sits right after "Dollar ceilings apply to paid routes only."
- **Problem:** a free or subscription route has no dollar ceiling. Read literally, the two sentences conflict.
- **Suggested wording:** "Paid-route dollar ceilings and the absolute batch deadline still bound every call." Or: "Money (paid routes) and the absolute batch deadline …"
- **Severity:** wording only. No code depends on this sentence in this diff.

## What I ran

- I read `docs/ENGINEERING.md`, the `zoom_out` and `implementation_readiness` agent files and their standards, the diff, `run.py:323–378`, the admission test file setup and `refuse` helper, and diff-29 N1.
- I ran the focused admission module: 19 tests, OK.
- I ran a guard-deletion mutation on a scratch copy outside the worktree. The new test fails without the guard.

## Did not run

- **The full suite.** It is running separately in `/tmp/stream-d-binding-suite.log`, and its result is not claimed here. This PASS depends on that suite passing.

## Not qualified

- Active-extension recovery or continuation, B2, M5 and M6.
- A live provider, any production caller, and activation.

No Murphy row closes.

## Other

- No model, cloud or launch calls.
- No secrets.
- No writes, commits, pushes or merges to the worktree or the parent checkout. The only file activity was the mutation copy in the session scratchpad.

## Elephant response

*(to be completed by the elephant)*


## Elephant resolution

Accepted PASS from fresh Claude Opus 5.5. The review above is preserved
verbatim, including its original review-30 heading. It is saved as review 31
because review 30 already existed in the starting commit and is retained unchanged.
N1 is addressed by including the founder-decision documentation in this increment.
N2 is addressed: dollar ceilings bound paid routes; the absolute batch deadline
bounds every call. No finding is rejected. No Murphy row closes.
The small-fix exception applies; no new design or design review was required.
Active-extension recovery remains outside this increment.

The unrelated active-extension design review was saved in stash
`86528d014c0a610b0e9d206a50c1d11097c61ec3`, named
`stream-d-next-increment-active-extension-review`. The `.stream-d-next/` drafts
remain untracked and unchanged.

## Elephant full-suite result

`uv run --with numpy --with scipy python -B tests/run.py` passed:
**154 test scripts, 0 failed**, exit 0. The guard source was `239c6a0`;
only documentation changed during the run. Launch guards passed.
Log: `/tmp/stream-d-binding-suite.log`. SHA-256: `9713844763171de0d465b6881ca7c28d293faed10ed09fa9349d42f8a2e7f896`.
No Murphy rows closed. No active-extension recovery was implemented.
