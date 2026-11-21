# Goldfish review: owner error masking (diff 1)

Reviewer: fresh general-purpose subagent (claude-opus-5-5), personas zoom_out + implementation_readiness,
Mode: REVIEW. Design step skipped (small fix); reviewed against the bug description and commit 28311ce7.

## Review (verbatim)

Verdict: FAIL

The test passes (2 passed, run with `uv run --with pytest --with dbos==3.4.0`). The two halves of the fix work for the reported case: a credit wait now reaches the classifier as router:credit. One real consumer breaks, though, and the commit message understates the blast radius.

The persona files and standards are not in the worktree. I read them from the main checkout under `/Users/bugsincode/Developer/unbug-bench/tools/egm/`.

**BLOCKING: an owner timeout now gets scored as a tester try**
- Where: `factory/exam_responder.py:235`, together with `factory/run.py:2573`.
- The owner's model call has a 120-second limit (`exam_responder.py:111`). When it runs over, it raises `BudgetError('timeout')`, from `model_runtime.py:627/909` or `budget.py:1527/1555`. Its own call cap raises `BudgetError('call_limit')` the same way.
- With this fix, `owner_server` now raises that error instead of "cancelled". `_author_try` reads `str(error) in ("timeout","call_limit")` as the tester's own time or call cap.
  - It sets `capped`, then `force_budget_resume = True`.
  - The try is saved with `save_pending` and committed with `stop_reason` "time_limit" or "call_limit". It is scored as a failed or partial strong-tester attempt.
- The hosted path does the same: `hosted_try` sends it to `pack_try(capped=...)`.
- Before the fix, this case was "cancelled", counted as an interruption and raised as a stop. `interruption_label`'s own rule is "Interrupted calls remain stops, never scored failed attempts".
- Effect: a slow owner now cuts the strong tester's solve count. That can push G10/G17 toward "zero strong solves", which is a science change.
- What a fix needs: an owner stop must never carry the tester's cap labels when it surfaces. Either rename the owner's timeout/call_limit before raising, or keep "cancelled" for those two labels.
- The test misses this because it patches out `calibrate`, so `_author_try` and `owner_channel` never run. A test that raises the owner error through `_author_try` with `BudgetError('timeout')` would catch it.

**BLOCKING (disclosure): the change reaches further than "G10/G16/G17, new launches only"**
- `factory/exam_responder.py` is hashed raw into `contract()` (`code_sha256`). Both `sealed_audit.verify_exam_metadata` (`sealed_audit.py:73`) and `bin/run-exam:384` require it to match the current code.
- Any case already sealed or qualified under the old code is now refused with "case needs qualification with the current reviewer owner". This is the same trap as the calibration.py seal freeze.
- `calibration_identity` (`run.py:2512-2515`) also hashes `exam_responder.py`. Saved exam tries and hosted-try identities from cases mid-G10 stop matching, so those tries re-run and cost money again.
- I checked `run.py` gate hashes old vs new with `gate_state.source_inputs`. Only G10 changes (`g10`), and G3 is unchanged. So the gate-identity claim itself is accurate; the exam admission and try identity are what is missing.
- What's needed: confirm no case is sealed or qualified before merging, and say this in the commit message.

**NIT: the "masked" condition is sound**
- `masked` is computed before `cancel.set()` and before the drain, so failures appended during the drain are not counted.
- The owner's own model call watches its private `cancel`, not `c.role_cancel`. An outside cancel therefore cannot produce a failure in `failure[0]` that the cancel itself caused.
- The only false positive is a race: an outside cancel lands while the owner fails on its own. Both errors are real, so this is acceptable.
- `failure[0]` is read after the drain but was already present. List append and read under the GIL are safe.
- Chaining works: Python sets `__context__` to the body's "cancelled" when raising inside the `finally`.

**NIT: `g10` change at `run.py:2944-2948`**
- `futures` is always bound: "cancelled" can only come from `future.result()`.
- Neither future is ever cancelled (two workers, two futures), so `exception()` cannot raise `CancelledError`.
- Blocking on `exception()` joins the same threads the executor's exit would join anyway, inside the same `concurrent_section`. No new hang.
- One side effect: `raise real[0]` overwrites the owner error's `__context__` with the easy tester's "cancelled" instead of the strong one's. Both say "cancelled", so the test can't tell the difference.

**NIT: behaviour change in `gate_pipeline` (intended, but worth stating)**
- Owner stops that are `BudgetError`s (ProviderWait, owner_invalid_answer, money) now become a parked G10 stop (`gate_pipeline.py:599`) instead of being raised at once. This matches the 2026-11-12 founder rule.
- When the pipeline is itself cancelling G10 (`gate_pipeline.py:670`), a real owner error now replaces the pipeline's own error rather than being suppressed. That was already true for any non-cancelled tester error.

**NIT: hosted helper path loses detail**
- An owner ProviderWait on a helper becomes `pack_stop("provider_wait", "unknown")`. It is classified as router:provider_wait, not router:credit.
- This already happens for the pilot's own waits, so it is not new.

**NIT: what the test proves (`tests/factory/test_exam_responder.py:122`)**
- Each half is needed. Without the `owner_server` half, both futures raise "cancelled". Without the `g10` half, the easy tester finishes first, because strong waits on `easy_stopped` plus 0.1 s plus the drain, so "cancelled" wins.
- The test feeds a fake `calibrate` into `run.calibrate`. That skips `_author_try`, `owner_channel` and the `calibration_interruptions` counting, which the task asked to be checked. That gap is how the first blocking issue got through.

## Elephant's response

- BLOCKING 1 (owner timeout scored as a tester try): fixed in 49afe08f. `answer()` now records an owner
  `timeout`/`call_limit` as `owner_invalid_answer` (an existing, classified infra stop) with the original as
  `__cause__`. This also closes the same pre-existing hole on the body-succeeded path
  (`elif failure and body_error is None`). The test now asserts both labels surface as `owner_invalid_answer`.
  `_author_try` matches the bare strings exactly, so asserting the surfaced label proves it is not scored.
- BLOCKING 2 (disclosure): stated in the commit message of 49afe08f and in the PR. Whether any case is
  sealed or mid-G10 is a merge/deploy decision for the parent and founder; not changed here.
- NITs: accepted as written; no code change.
