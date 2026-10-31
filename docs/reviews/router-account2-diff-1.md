## Verdict: PASS, no blockers

The code change does what was asked, and it lives only in the authoritative router, `Store.rpc` in `factory/model_router.py`. Claude lanes are now always tried account 2 (`claude-factory-token-2`) first, then account 1, whatever order the caller gives. A new `eligible()` check allows account 1 only when account 2 has a `rate` or `quota` health record whose `blocked_until` is later than now. Three places use that same check: capacity and acquisition (through `free()`), the list of candidate lanes, and the queue-order comparison with older waiting requests. Renewing or replaying a lease that was already issued is unchanged.

I checked these points against the design:
- **Evidence:** rate and quota reports are stored per account, not per route (`model_router.py:305`), so the check reads the right record. After a block expires its `reason` stays but `blocked_until` drops to 0, so stale evidence can't unlock account 1.
- **No evidence:** credit, outage, `credential_expiring`, `router_unavailable`, an excluded account-2 lane, and an allowlist with only account 1 (or nothing) all wait with no lease. With no eligible Claude lane, the wait reason is `credential_expiring`, as agreed in design review 2.
- **Capacity:** a healthy Claude pool now reports one account's slots instead of both. Every other `routes()` caller only checks membership, so the fixed order affects nothing else.
- **Out of scope:** I did not reopen the transport question; nothing new about admission correctness came up there.

## Murphy row `new-router-account2-1`: closure accepted
The four tests listed under "Closed by" replay real saved Claude limit cards from `router-provider-limits.json.gz` against real SQLite router state. Each would fail if the change were reverted:
- `test_real_claude_reset_shared_switch_expiry_and_restart`: after the reset passes, a request allowed only account 1 waits, account 2 is chosen again, and there is 1 slot.
- `test_account2_policy_replays_real_limit_card`: covers account 2 by default, a busy account 2 not counting as evidence, fallback after rate evidence, a healthy report closing fallback, and the existing account-1 lease still replaying and renewing.
- `test_account2_non_rate_failures_and_allowlists_never_unlock_account1`
- `test_saved_account1_preference_and_only_local_key_cannot_run_account1`: goes through the real `await_lease`. A saved account-1 preference plus only the account-1 key on disk ends in a `credential_expiring` wait, with no lease and no health record.

The row correctly says it covers routing seen in code, not a live account-2 identity incident. The changes to the three older tests match the design's list: `test_model_call_maxima`, `test_stream_d_admission` (now uses an explicit HTTP 429 in immediate-fallback mode) and `test_stream_d_runtime` (now uses a rejected `rate_limit_event`).

## Findings (none blocking)
- **Major (test accuracy):** in `tests/factory/test_model_router.py:92-94`, the comment says "The older busy request retains FIFO priority once fallback is eligible." The test then moves the clock forward by `LEASE_SECONDS+1`, which makes that older request stale so it no longer competes. So the test sidesteps the claim instead of checking it. Only the other direction is tested: an older request that can use only account 1 doesn't block account 2 (`test_account1_only_waiter_does_not_block_eligible_account2`). Suggested fix: assert that a newer fallback request waits while the older eligible request is still active, or correct the comment. This affects queue fairness, not whether account 1 is wrongly admitted.
- **Nit:** in `tests/factory/test_model_call_maxima.py:463`, `'claude-factory-token-2-2'` looks like a search-and-replace leftover. It still works as a made-up account name.
- **Nit:** `_account_order` is now only ordering-for-show on Claude routes. The design keeps it on purpose, so it's fine.

## Validation
- **Run here, all passing:** `test_model_router.py` (41), `test_model_call_maxima.py` (21), `test_stream_d_admission.py` (19), `test_stream_d_runtime.py` (42). `test_model_router.py` only imports with `BENCH` set, which `tests/run.py` sets.
- **Still pending:** the final uninterrupted run of `uv run --with numpy --with scipy python -B tests/run.py`, plus its committed record. Only the first run (3 failures) is committed, so the full-suite requirement isn't met until the elephant records a passing run.
- **Still pending before activation:** confirming that the two labels belong to two different people's accounts (the profile calls returned 403). This is the founder's job.
- **Still pending before activation (stream B):** fixing the controller handoff and proving a real 2 → 1 → 2 round trip, and setting the policy to `initial_accounts.claude=2` and `claude_accounts=[2,1]`.
- **Not claimed:** nothing here claims the batch is ready to activate. Nothing was deployed or run live.

## Elephant response

Accepted the test-accuracy finding: corrected the FIFO comment to say the
older busy waiter expires before the fallback/lease-continuity assertions.
No extra fairness claim is made by that test. The malformed-label nit remains
nonblocking: both the previous and current authored labels are unapproved and
exercise identical rejection behavior; exam-label rejection also has an explicit
router regression. _account_order is retained for non-Claude compatibility.

Clarification: these are two accounts belonging to the same founder, not two
different people's accounts. Distinct account identity remains unverified.
B's controller round-trip work and account policy remain activation prerequisites.
Final full-suite result will be recorded below once the running suite completes.
