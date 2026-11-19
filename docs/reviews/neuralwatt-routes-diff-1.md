# Diff review 1: neuralwatt-routes (goldfish, Mode: REVIEW, zoom_out + implementation_readiness)

**Goldfish diff review: Neuralwatt routes, compared against `docs/designs/neuralwatt-routes.md`**

Most design items match the code: items 1–5, 6 (step and tail), 7 and 9. Items 1 and 6 are the twin map and the tail, items 7 and 9 are classify/stop_registry and setup-secrets. I ran four test files on the branch head and all passed: `test_neuralwatt_routes`, `test_neuralwatt_runtime`, `test_neuralwatt_budget` and `test_provider_routes`. I did not run the full suite.

**BLOCKING 1: item 8 and the captured fixtures are missing, though the design says they land before merge.**
- Evidence:
  - Rollout step 1 says the capture happens "before merge" and "item 8 lands in this branch". Nothing in `factory/budget.py` handles Neuralwatt bodies.
  - `tests/factory/test_neuralwatt_budget.py:3-5` says its step part and 402 are stand-ins.
  - `test_neuralwatt_budget.py:31`: `CREDIT_402` is the OpenRouter 402 shape, not a Neuralwatt body.
  - The design's tests call for "the real captured NW step part" and "the real captured 402 body … moves to the OpenRouter twin, with case money unchanged by the tail".
  - `tests/factory/test_neuralwatt_runtime.py:99-109` only unit-tests `go_quota_moves_on`. No test runs the move-on through `ModelRuntime.call`.
- Why it matters:
  - Nothing real shows that OpenCode's openai-compatible provider with `includeUsage` gives non-zero `tokens` on a Neuralwatt step. If tokens come back as zero, `budget.py:1398-1400` books $0 and `unpriced_usage` (`budget.py:1427`) does not fire.
  - Nothing real shows the request carries `max_tokens ≤ 32768`. `nw_request_worst` assumes the twin's 131072 output, but Neuralwatt's `max_output_tokens` is 393216 (price fixture), so without that cap the per-request bound does not hold.
  - These are fixtures of the shape the code expects, not real artifacts (ENGINEERING §2 and §4).
- Fix, either way:
  - Do rollout step 1 now. Commit the captured step part, the 402 and the 429 bodies, plus the outgoing request body showing `max_tokens`. Swap them into `test_neuralwatt_budget.py`. Add item 8 if `classify_provider_failure` (`budget.py:42-44`) does not already map them. Add a move-on test through `ModelRuntime.call`, using the Go quota pattern in `test_provider_routes.py:103-121`: NW lease, captured 402, then the next try is `openrouter/xiaomi/mimo-v2.6-pro`, with the NW row's `estimated_gap_usd` equal to 0.
  - Or amend the design so capture, item 8 and these tests are explicitly a post-merge follow-up, with the lane switched off (`disabled_routes: ["neuralwatt/"]`) until then. Today the design and the branch disagree.

**BLOCKING 2: no test covers the tail falling back to the full bound.**
- Evidence:
  - `factory/budget.py:1441` drops `open_steps` when a `cancellation-failed:` or `unverified-*` key is open. `budget.py:1699` adds `cancellation-failed:` and calls `open_steps()`.
  - The design's test list includes "With a `cancellation-failed:` key open, the tail falls back to `bound − booked`".
  - `test_neuralwatt_budget.py` covers only a killed worker with no row written (`:128-132`), not this path.
- Why it matters: this is the only guard against under-booking real money when an orphaned process may still send paid requests. If the pop regressed, the tail would book `n × worst` instead of the whole bound.
- Fix: in `NeuralwattBudget`, add a test that patches `stop_process` (or the containment kill) to raise after `start(0)`. Assert that `open_steps` is absent from the row and the settled `estimated_gap_usd == maximum − booked`. Add a second case for `unverified-buffered-usage:`, with a malformed trailing line after a stop.

**NIT 1: dead code that contradicts the design.**
- `factory/model_runtime.py:291` adds a `NEURALWATT_API_KEY` branch to `diagnosis_environment`.
- The design (item 4) says "Not in `diagnosis_environment`". Diagnosis runs with `user='pilot'`, so `model_runtime.py:536-541` excludes ungated lanes, and `model_call_gate.enforce` refuses NW under a user.
- Fix: delete the branch and its test at `tests/factory/test_neuralwatt_runtime.py:94-97`.

**NIT 2: the price-record test skips `service_tier`.**
- `tests/factory/test_neuralwatt_routes.py:105-115` never checks `service_tier == "standard"`, which the design's tests require. The "never above list" statement excludes speed lanes, so this is what supports the upper-bound claim.
- Fix: add `self.assertEqual(models[name]['metadata']['pricing']['service_tier'], 'standard')`.

**NIT 3: the health fixture's source query is not recorded.**
- The docstring at `tests/factory/test_neuralwatt_routes.py:1-7` does not include the source query, which the design requires. So it cannot be shown that `router-health-20261119.json` is a real extract.
- Fix: add the exact `sqlite3 … 'SELECT pool, value FROM health'` command.

**NIT 4: `event_bound_charge == cost` is never asserted.**
- `test_neuralwatt_budget.py:73-82` checks only that `plan_list_cost_usd` is absent.
- Fix: assert `budget.event_bound_charge(e) == e['cost']` for each NW event.

**NIT 5: the "OpenCode cost is higher" case of `max(...)` is not tested.**
- `test_neuralwatt_budget.py:75` only covers OpenCode reporting less than list.
- Fix: add one step where OpenCode's cost is above `STEP`, and assert that its cost is booked.

**NIT 6: no test that `Ctx` sets `router_accounts` as a list.**
- `factory/run.py:170` builds it, but only `offered_accounts()` is tested.
- Fix: construct `run.Ctx()` with SECRETS patched, and assert `router_accounts` is a list without `neuralwatt-key`.

**NIT 7: the runbook leaves the router's code version implicit.**
- In design rollout step 3, the router's `Store` filters offered accounts against its configured accounts (`model_router.py:522`). `routes()` raises `unapproved account` for names missing from its `ACCOUNTS` (`model_router.py:158`).
- Fix: in step 3, say that the router restarts on the new release's `model_router.py`.

VERDICT: FAIL

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
