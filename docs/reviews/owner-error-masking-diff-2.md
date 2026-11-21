# Goldfish review: owner error masking (diff 2)

Reviewer: fresh general-purpose subagent (claude-opus-5-5), personas zoom_out + implementation_readiness,
Mode: REVIEW. Design step skipped (small fix); reviewed the full diff 3dfdde3c..49afe08f against the bug
description and commit messages.

## Review (verbatim)

Verdict: PASS

The fix does what the bug asks. When the owner fails, its real error now reaches G10, and an owner timeout or call cap can no longer be scored as a tester try. The test file passes (8 tests). Removing any one of the three parts would make the new test fail. I found no blocking issues.

**What I checked**
- **The surfacing condition** (`factory/exam_responder.py:226`) only fires when the owner has failed and the body then stopped with `'cancelled'`. `answer()` records the failure before it sets `c.role_cancel`, so the failure is always visible by the time the tester sees the cancel. A cancel from G10 or the pipeline doesn't reach the owner's call, because the owner listens to its own `cancel` event. So it can't fire falsely. Owner errors that appear during teardown are added after `masked` is computed, so they can't hijack the result.
- **Chaining:** the owner's error gets the cancellation as `__context__`. In the timeout/call_limit case it also has `__cause__` set, so the cause is what gets printed.
- **The g10 change** (`factory/run.py:2944-2948`) doesn't add a hang. `role_cancel` is set before `f.exception()` waits, and the executor's `__exit__` already waited on both testers before this change. No future can be cancelled, since 2 workers run 2 futures, so `exception()` can't raise `CancelledError`.
- **Owner timeout/call_limit mapping:** the owner's model call has no `deadline` (`model_runtime.py:625-627`), so its `'timeout'` is always its own 120 s window, never the tester's. Mapping it to `owner_invalid_answer` is correct. This also fixes an older bug: when the body ended normally, an owner `'timeout'` used to be scored as a tester cap. The fix lives in `answer()`, so the helper path (`hosted_try` → `_author_try`) is covered too.
- **Downstream consumers:**
  - `ProviderWait` is a `BudgetError` and is classified as `router:credit` through `classify_wait`; `owner_invalid_answer` is classified as `infra:owner_invalid_answer`.
  - In `gate_pipeline.py:599`, these stops are now parked until the bench gates finish, instead of being raised at once as `'cancelled'` was. That matches the 2026-11-12 parking rule.
  - In `_author_try`, only bare `'timeout'` and `'call_limit'` are treated as the tester's cap, and no owner error can now produce those labels.
- **Gate identities:** `g10` is reached only from G10's runner roots. `exam_responder.py` sits in the G10 and G16/G17 file inputs, in `calibration_identity` (`run.py:2511-2515`) and in `owner_contract` (`sealed_audit.py:73`). Commit 49afe08f discloses the requalification and re-run consequences. That is more accurate than 28311ce7's "new launches only".

**NITs**
1. `factory/run.py:2575`: `interruption_label` turns `'provider_wait'` and `'owner_invalid_answer'` into `"unknown"`. So owner stops that used to be counted as `'cancelled'` in `calibration_interruptions` now show up as `'unknown'`. This was already true for the tester's own ProviderWait, and `calibration.py` is frozen.
2. `factory/exam_responder.py:226`: there is a narrow race. If the owner fails and the pilot hits its own `'timeout'` before the cancel lands, the body's cap wins. The try is then scored as capped even though an owner question went unanswered. This predates the change; the window is roughly the cancel latency. A stricter version would set `masked` whenever `failure` is non-empty and the body raised `'timeout'` or `'call_limit'`.
3. `factory/gate_pipeline.py:670`: when the main loop cancels G10, it now waits for the slower tester. So a genuine owner or tester error that races the cancel will consistently be raised over the swallowed `'cancelled'`; before, whichever tester finished first decided. Real errors were already raised under the existing rule, so this is not a regression, just worth knowing.
4. The test calls `g10` with `calibrate` mocked, so `_author_try`'s cap and interruption handling and the `gate_pipeline` parking path are only checked by reading the code, not by a test. That's acceptable at this size.

**Would the test fail without each part?**
- Without the `masked` raise, both testers raise `'cancelled'`, `real` is empty and the test's `assertRaises(ProviderWait)` fails.
- Without the g10 change, the easy tester stops about 100 ms before the strong one, so `as_completed` raises its `'cancelled'` first, and the test fails.
- Without the label mapping, the second loop gets `'timeout'` back instead of `owner_invalid_answer`, and the test fails.

## Elephant's response

PASS, no blocking findings. NITs 1-4 accepted as written; no code change. NIT 2 is a pre-existing race
(pilot's own cap landing before the owner's cancel), left as-is to keep the diff minimal.
