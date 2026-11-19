# Diff review 2: neuralwatt-routes (goldfish, Mode: REVIEW, zoom_out + implementation_readiness)

Goldfish review: Neuralwatt routes, money and safety lens

**BLOCKING 1: Rollout step 3 can take the router down and stop every worker.**
- The router runs from its own checkout: `control/unbug-model-router.service:14` runs `/home/user/unbug-bench/factory/model_router.py`. That is not `source-current`, and neither `unbug install` nor `release.py switch` updates it.
- Runbook step 3 (`docs/designs/neuralwatt-routes.md:155`) adds `neuralwatt-key` to router config `accounts` and restarts, but never moves that checkout to the release.
- On old code, `Store.__init__` (`factory/model_router.py:410`) raises `unapproved account`. `main()` then exits with "router startup failed", systemd keeps restarting it, and every acquire on every batch hits `router_unavailable`.
- A second path: an old router that receives one new-code request offering `neuralwatt-key` fails every acquire for about `LEASE_SECONDS`. Its queue scan (`model_router.py:552`, `self._routes(p['model'], p['accounts'])`, unfiltered) raises on that request.
- Fix: step 3 first fast-forwards `/home/user/unbug-bench` to the release commit. It then checks `python3 -c "import sys; sys.path.insert(0,'factory'); import model_router; assert 'neuralwatt-key' in model_router.ACCOUNTS"` before editing `router.json`. Rollback must drain the router and remove the account from `router.json` before moving the checkout back.

**BLOCKING 2: An NW call can book more than its lease maximum, with real money.**
- An NW step is booked when its `step_finish` arrives (`factory/budget.py:1398-1401`). `check_limits` then calls `check_reservation` (`budget.py:276`, `booked > maximum_usd`), so the call stops only after the step that crosses the bound.
- So booked money (and real Neuralwatt spend) can pass `max_usd` by one request: up to $0.570 on MiMo or $0.629 on GLM.
- `reserve_invocation` admitted only `max_usd` against the attempt and case limit, so case authority can be passed by that amount.
- Go books $0 and gated OpenRouter holds money before forwarding, so neither has this overshoot. NW is the only real-money lane where it happens.
- Fix: in `check_limits` (`budget.py:1103-1112`), for `reserved and configured_model in NW_ROUTES`, raise `usage_reservation_exceeded` once `reservation_booked + nw_request_worst(route) > maximum_usd`. That stops the call before the next request. Add a test where a step lands within one worst-case request of the max and the call stops with `booked <= max_usd`.

**NIT 1: The design's pre-merge gate is not met.**
- Item 8 is not in the diff: `classify_provider_failure` is unchanged and there are no captured Neuralwatt bodies. The tests use a synthetic 402 (`tests/factory/test_neuralwatt_budget.py:4,31`).
- The design says the bodies are captured before merge and "item 8 lands in this branch" (`neuralwatt-routes.md:141,150`). It also contradicts itself at `:132` and `:236` ("after rollout step 5").
- Impact if a real out-of-credit body has no `statusCode` 402: it falls to `opencode_error`, which reroutes as `outage`. The call then waits instead of moving on, and books a phantom tail of one worst-case request (`budget.py:1444`, `max(...,1)`) on every retry.
- Fix: capture the bodies before merge as step 1 says, or change the design to the generic 402/429 classifier and accept the follow-up.

**NIT 2: Phantom tail on a finished error.**
- `open_steps` counts at least one open request for any stop that is not a classified refusal (`budget.py:1444`). That includes an `opencode_error`, where the provider already ended the request, so it books $0.57–0.63 for nothing.
- Fix: also count `n = open_steps` with no minimum when `str(error) == 'opencode_error'`.

**NIT 3: The design says to leave the NW key out of `diagnosis_environment`; the code adds it.**
- `factory/model_runtime.py:291` passes `NEURALWATT_API_KEY` into diagnosis. It is unreachable today, because walled diagnosis excludes ungated lanes at `model_runtime.py:536-541`. It still puts a key inside the walled boundary if that exclusion ever regresses.
- Fix: delete line 291.

**NIT 4: Helper boxes trust the case's account list without checking their own key.**
- `factory/durable/helper_link.py:213` copies the case's `router_accounts`. A helper box whose RAM bundle is older than step 5 would then offer `neuralwatt-key` with no key file. Its call fails `credential_expiring` (no spend, but the try stalls), which is the cae763 loop `offered_accounts` was written to avoid.
- Fix: `c.router_accounts = [a for a in x["router_accounts"] if a in model_runtime.offered_accounts()]`. `helper_link.py` is not release-pinned.

**NIT 5: Rollback risk from the new ledger field.**
- `open_steps` on reservation rows is accepted only by the new `usage_coverage` (`budget.py:812-813`). A case ledger written by the new release and read by old code returns `None`, so coverage looks unknown.
- Fix: the runbook rollback says cases that ran an NW call are never downgraded below this release.

**NIT 6: The new tests depend on test order.**
- `tests/factory/test_neuralwatt_routes.py` and `tests/factory/test_neuralwatt_runtime.py` pass alone. Run after `test_provider_routes.py`, 3 fail: `nw_maximum` comes back as `max_usd 50.0` with an `...only` price source.
- That file's pollution also fails 5 tests in `test_model_router.py` on `origin/main`, so that part is older than this branch.
- Fix: the NW tests reset or patch `route_maximum` / `GATED_OPENROUTER` themselves, or `test_provider_routes` restores what it patches.

**Lens checks that passed:**
- **Non-NW routes are unchanged:**
  - `opencode_config` adds the provider only for NW models.
  - `free_environment` and `enforce` keep the same Go branch.
  - `router_accounts` without the key equals the old `ACCOUNTS`.
  - Old-release callers never offer `neuralwatt-key`, so the new router filters the NW lane out.
- **Walled roles are excluded** in `bounded_route`, in `ungated_lanes`, and by `enforce` refusing any walled user.
- **The NW tail falls back to the full bound** after a failed kill, an unverified stream, or a killed worker.
- **A credit block on `neuralwatt-key`** expires on its own backoff and does not park cases waiting for an OpenRouter top-up.

Verdict: FAIL

## Elephant response (2026-11-19)

Fixer report, verbatim:

Both money bugs from review 1 and the missing failed-kill test from review 2 are fixed. The other two blocking findings, the router runbook and item 8, are handled in the design. Item 8 could not be built: it needs the founder's trial key and a live call to Neuralwatt. Everything is in one commit, `afca11c6` on `feat/neuralwatt-routes` in `/Users/bugsincode/Developer/ub-neuralwatt`, not pushed. The full suite passed with no failures: 210 test scripts as 227 jobs.

**Review 1 (money and safety)**
- **B1, router restart can take every worker down: fixed in the design** (`docs/designs/neuralwatt-routes.md`, rollout step 3).
  - The router's own checkout at `/home/user/unbug-bench` must be fast-forwarded to the release, and the `ACCOUNTS` assert run, before `router.json` names `neuralwatt-key`.
  - Rollback is: drain, remove the account from the config, restart, then move the checkout back.
- **B2, an NW call can book past its maximum: fixed** (`factory/budget.py`, `check_limits`).
  - A reserved NW call now stops once `booked + nw_request_worst > maximum`, so the next step can't book above the reservation.
  - A reservation smaller than one whole request is stopped at the first check, before any step books. Its tail is then the whole small bound.
  - New test: `test_an_nw_call_stops_while_one_more_request_still_fits_its_reservation`.
- **NIT1, item 8 missing: handled by changing the design**, same as review 2's B1 below.
- **NIT2, phantom tail on a finished error: fixed.** `opencode_error` now counts open steps with no minimum of one. New test: `test_an_opencode_error_event_books_no_phantom_tail`.
- **NIT3, Neuralwatt key in diagnosis: fixed**, by a small change from the reviewer's wording.
  - Deleting the line outright would hand an NW lease the OpenCode key. Instead, `diagnosis_environment` now gives an NW lease no key at all (`factory/model_runtime.py:~291`).
  - The test was flipped to match.
- **NIT4, helper boxes trust the case's account list: not fixed.**
  - `factory/durable/helper_link.py` is listed in `gate_state.DEPENDENCIES` for G5, G6, G7 and G10. Editing it would force those gates to rerun on every case that takes this release.
  - Nothing else on the branch touches a gate dependency, so that cost isn't worth a NIT.
  - The risk only exists if a helper box's bundle is older than rollout step 5. Step 5 installs the bundle before any `plumbing_release`.
- **NIT5, rollback and the new ledger field: fixed in the design.** The rollback now says a case that ran an NW call is never moved below this release.
- **NIT6, tests depend on order: fixed.**
  - The cause was a module-level `_ROUTING = offline_router()` in `tests/factory/test_provider_routes.py`. It is now `setUpModule`/`tearDownModule`.
  - Running `test_provider_routes` and the three NW test files in one process now passes (28 tests).
  - Six other test files use the same pattern. I left them alone because `tests/run.py` isolates each script.

**Review 2 (correctness and tests)**
- **B1, item 8 and the captured fixtures are missing: the design is changed instead (the reviewer's option 2).**
  - Capturing real Neuralwatt bodies needs the founder's trial key and a live API call, which I'm not allowed to make.
  - The design now has the lane ship switched off: router step 3 sets `disabled_routes: ["neuralwatt/"]`.
  - Step 1 now also records an OpenCode step part (non-zero `tokens`) and the request's `max_tokens` (32768 or less).
  - The captured bodies, item 8, the move-on test through `ModelRuntime.call` and the swap to real fixtures land in a separate reviewed follow-up commit.
  - A new step 7 turns the lane on after that. The stale references to "rollout step 5" are fixed.
- **B2, no test for the tail falling back to the full bound: fixed for `cancellation-failed`.**
  - New test `test_a_failed_kill_keeps_the_whole_remaining_bound_booked` patches `os.killpg` to fail. It checks that `open_steps` is gone, `terminal_stop` is `cancellation_failed`, and the gap is `5 − booked`.
  - The `unverified-buffered-usage` case is not written because no NW call can reach it. Every `unverified-*` marker is only set on Codex or Claude paths (`budget.py` around lines 1304–1329, 1622 and 1644), and NW runs through OpenCode. The design now says so.
- **NIT1, diagnosis key branch:** fixed, as review 1 NIT3 above.
- **NIT2, `service_tier`:** fixed; the price-record test now asserts it is `standard`.
- **NIT3, health fixture's source query:** added to the `test_neuralwatt_routes.py` docstring as `sqlite3 -json factory.before-force-lift-20261119.sqlite3 'SELECT pool, value FROM health'`. It matches the `health` table, but I couldn't check it on the VM. The fixture has only three pools, so the original extract may have been filtered.
- **NIT4, `event_bound_charge == cost`:** fixed; asserted for each NW event.
- **NIT5, OpenCode cost above list:** fixed; there is now a step with OpenCode's cost at twice `STEP`, and that cost is what gets booked.
- **NIT6, `Ctx` sets `router_accounts` as a list:** fixed; new test `test_a_case_context_offers_accounts_as_a_list_without_a_missing_neuralwatt_key`.
- **NIT7, router code version in the runbook:** fixed, as review 1 B1 above.

**Other design fixes**
- Item 6 now records the new `check_limits` stop and the `opencode_error` rule.
- The health-row wording now says the Go rows' backoff had lapsed, so the replay sees Go's quota answer.

**Tests**
- Touched files, each run alone, all pass: `test_neuralwatt_budget` (10 tests), `test_neuralwatt_runtime` (8), `test_neuralwatt_routes` (5) and `test_provider_routes` (5).
- The full suite log is at `/private/tmp/claude-501/-Users-bugsincode-Developer-unbug-bench/35da1f8b-8fdf-431c-a84e-d725cb8c71d1/scratchpad/nw-suite.log`.
