**Disposition: PASS** for `d1ced53..8b2c1cc`. Merge still has to wait for the clean full-suite rerun to finish green.

I read the scope you named. Production code is unchanged after the diff-4 PASS head `d1ced53`: `factory/` and `tools/` have no diff in this range. The range changes only `docs/designs/router.md` (+18), `tests/factory/test_provider_routes.py` (+4/−1), and adds `docs/reviews/router-diff-4.md`.

## Test change (`tests/factory/test_provider_routes.py:66-85`)

- **The new fixture produces shared evidence, as the test needs.** `classify_provider_failure('model removed', model, status_code=404)` returns `{'reason': 'outage', 'scope': 'route', 'model': ...}` (`factory/budget.py:42-46`). It has no `per_call` key.
- **The runtime keeps that evidence global.** In `factory/model_runtime.py:275-283`, `getattr(error, 'provider_failure')` takes precedence over the label path. The label-to-`per_call` path, and the route exclusion it adds, apply only when `provider_failure` is None. So this failure reaches shared health.
- **Both assertions are now honest:**
  - The first case tries native and then fallback.
  - The second case goes straight to `opencode-go/glm-5.3-flash` because the native route is globally blocked by classified evidence.
- **This matches the distinction diff 3 R2 and diff 4 accepted.** A label-only `opencode_error` is case-local; `test_label_only_budget_errors_leave_peer_capacity_healthy` still covers that. A parser-classified 404 is a shared outage.
- **The old fixture expected behaviour that is now a defect.** It expected global blocking from a bare label, so updating it is a correction, not a weakening.
- **The error shape matches production.** `budget.py:389` raises `BudgetError(label, provider_failure=observation)` the same way.
- **No other stale fixture found.** I grepped `tests/` for a bare `BudgetError('opencode_error')`; nothing else remains.

## Doc change (`docs/designs/router.md`, "Passing diff-review follow-ups")

- It records review 4's F1–F4 accurately and matches the elephant response:
  - **F1:** a B/D diagnosis candidate, bounded by B's relaunch cap.
  - **F2:** the non-response CLI-only 401 scope is accepted, B's renewal clears it, and row 20 stays B-owned and open.
  - **F3:** the injected per-call test and the real silent-limit parser test stay separate, and the combined lifecycle remains B's integration proof.
  - **F4:** the subsecond alias risk is accepted, and the lifecycle and paid-fallback proofs stay open.
- It says plainly that none of these close a Murphy row. That fits the brief: rows 2, 3, 4, 20, 47 and 48 stay open until B's end-to-end proof.
- There are no new interfaces, YAGNI problems or decisions left to the implementer.

## Findings

- **N1. Nit, no action.** In the updated test, the outer `'opencode_error'` label no longer affects routing once `provider_failure` is set. That is intended and matches production.

There are no blocker, major or minor findings.

## Suite logs (read only, not run)

- **`/tmp/router-final-full.log`** ends with "131 test scripts run; 1 failed. FAILED: tests/factory/test_provider_routes.py". The only failure is `test_fallback_is_shared_and_billing_is_explicit` (lines 523-545): it expected `['opencode-go/glm-5.3-flash']` and got native plus fallback. That is exactly the stale bare-label fixture this diff fixes.
  - Two other lines look like test output, not failures: "Unlock diagnostic … RuntimeError" (line 951) and "ERROR ClaudeUsageLimit" in the in-progress log (line 18).
- **`/tmp/router-green-full.log`** is about 1.1K and still running; when I read it, it had reached `tests/bench/test-launch-guards.py`. I can't confirm it is green.

## Handoff conditions (not met by this review)

1. `/tmp/router-green-full.log` must finish at `8b2c1cc` with "0 failed".
2. The parent merges alone, with `Reviewed-by:` trailers for `router-design-1..6` and `router-diff-1..5`.
3. Do not merge or push from this review.

**PASS.**

## Elephant response and completed validation

PASS recorded verbatim. Nit N1 is accepted with no action. No blocking finding
remains. No production code or test changes follow the reviewed head.

- Tested head: `8b2c1cc8dbaeb094a31d83fbe87756eef3c1d1fc`.
- Command: `uv run --with numpy --with scipy python -B tests/run.py`.
- Exit status: 0. Final output: `131 test scripts run; 0 failed.`
- Router regressions: 36 passed; provider-route regressions: 4 passed in that run.
- Complete offline log (ignored verification artifact):
  `results/infrastructure/2026-10-29-router/full-suite.log`.
- Log SHA256: `142e5071422e3ada90bd667ab5a548d7cee952f16fd010948ccfd4b1c43756e2`.
- `git diff --check` and `sh -n factory/launch.sh` pass.

All handoff conditions for A's authorized slice are now met. No Murphy row is
closed: 2, 3, 4, 20, 47 and 48 remain open for the agreed B/D lifecycle,
settlement, credential and real-402 proof. Review 4's nonblocking follow-ups are
recorded in the design. The parent alone merges, with Reviewed-by trailers for
router-design-1..6 and router-diff-1..5. This branch is not merged or pushed.
