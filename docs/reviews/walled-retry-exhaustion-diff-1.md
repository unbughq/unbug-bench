# Goldfish review: walled retry exhaustion (diff 1)

- Branch: fix/walled-retry-exhaustion, commit df7f131e on main.
- Reviewer: goldfish (fresh agent), read-only. Ran tests/factory/test_stream_d_retries (66 OK); rebuilt the pre-fix code and confirmed the new test fails there.
- Verdict: **FAIL** (1 blocker). All findings addressed in the next commit.

## Findings and disposition

1. BLOCKER: the state cae763-h3 actually saved ends `[..., invalid, pending]` (a judgment queued before its call found no lane). The reset fired only after an `invalid` row, so that state stayed stuck.
   **Fixed:** a pending judgment with every leasable lane spent resets too, without queueing another row. New test `test_cae763_saved_stuck_pending_judgment_resets_on_the_next_attempt` builds that exact shape; it fails without the change.
2. SHOULD: lanes with no price maximum (e.g. `openrouter/minimax/minimax-m3.1-flash:free`) can never be leased, so they could never be spent either: the same loop for any role on such a chain.
   **Fixed:** exhaustion counts `model_router._bounded_routes` (what `_call` leases), minus ungated lanes for walled roles. If no lane is leasable at all, the answer is not "exhausted": the call reports unbounded_route as before.
3. SHOULD: narrowing the validity check would refuse an older calibrator state that spent a free lane (before walling, 2026-11-08).
   **Fixed:** `spent_routes` is still validated against the whole chain; only exhaustion uses the narrowed set.
4. NIT: assert the reset record. **Fixed:** the first test checks `exhausted_attempts[0].spent_routes` and the attempt phases.
5. NIT: Murphy row. `docs/murphy-register.md` is not on main; the incident is recorded in the commit messages and this review.

## Re-review (diff 2, commit 9c73480b): PASS

- All five findings verified fixed; 67 retry tests OK.
- NIT kept: lanes switched off only in the router's live config (`disabled_routes`, capacity 0) still count as leasable. Today the VM disables two MiniMax free lanes; no retained-answer role uses a MiniMax chain, so no answer can loop on them. Pre-existing and config-only.
- NIT kept: `answer` walls by role only; `_call` also walls calls with a `user`. No retained-answer caller passes one.
- Full suite on df7f131e: 199/201 scripts pass; boat_settlement and helper_transport failed under parallel load and pass alone on 9c73480b.
