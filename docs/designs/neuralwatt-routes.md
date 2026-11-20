# Neuralwatt routes for MiMo and GLM

Founder, 2026-11-19:
- "Yes, build it": build Neuralwatt routing for MiMo-V2.6-Pro and GLM-5.3 Flash. Using the same
  models from a different provider is fine. Test on the $5 trial credit before any subscription.
- "Let's do it for existing launches too, or is it not possible": running cases should use it where
  possible.

## Problem

- MiMo and GLM run on the founder's two OpenCode Go plans first. When both are on weekly quota, the
  only paid fallback is OpenRouter.
- Over the router's history:
  - MiMo on OpenRouter cost $103: 1.23B input tokens (1.05B of them cached) and 16M output.
  - GLM-5.3 Flash cost $21.
- On 2026-11-19 the OpenRouter balance ran down to $4.38. The paid pool blocked, and seven cases
  parked behind it.
- Neuralwatt serves the same two models: `mimo-v2.6-pro` and `glm-5.3-flash` (`/v1/models`, saved
  as a fixture).
- Its listed token prices equal our OpenRouter pins:
  - MiMo: 0.435 / 0.0036 / 0.87;
  - GLM: 0.15 / 0.03 / 0.50.
- It bills by measured energy and states that a request never costs more than its listed token
  price. Over the last 7 days, paid prices ran about 20% (MiMo) and 27% (GLM) below list.
- Until 2027-01-01, a free daily energy grant covers the Flash models.

**Success metric.** After 7 days live:
- the Neuralwatt share of MiMo/GLM paid calls;
- dollars saved against list, from Neuralwatt's usage API, compared with case money booked;
- zero cases stopped by a Neuralwatt fault, since a fault moves the call to OpenRouter.

**Impact now.** The cases parked today are waiting on OpenRouter credit. This change does not
unpark them; only a top-up does. It gives future fallbacks a second paid provider.

**Cost and timeline.** About 3 hours of build and review, then a drained router restart, a
controller restart and the founder's key install.

## Change

Add one lane per model, in each chain between the Go plan route and the OpenRouter route.

The lane is an OpenCode provider lane with no gate, the same shape as the Go lanes
(`model_call_gate.enforce`, `GO_ROUTES` branch). It differs from Go in two ways:
- it books real money at its OpenRouter twin's list price, where Go books $0;
- its unseen tail is bounded by the requests actually in flight.

1. **`token_prices.py`**
   - `NW_TWINS`:
     - `neuralwatt/mimo-v2.6-pro` → `openrouter/xiaomi/mimo-v2.6-pro`;
     - `neuralwatt/glm-5.3-flash` → `openrouter/z-ai/glm-5.3-flash`.
   - `NW_ROUTES`.
   - `nw_maximum(route)`: the twin's `openrouter_gate_maximum` with
     `price_source='neuralwatt:<model>:twin=<twin source>'`.
   - `runtime_prices` and `go_step_cost` resolve twins through one shared map: `TWINS = {**GO_TWINS, **NW_TWINS}`.
   - `nw_request_worst(route)`: the twin's `(context × input + output × output) / 1e6`. That is
     $0.570 for MiMo and $0.629 for GLM.
   - Price evidence goes in `tests/factory/fixtures/neuralwatt-price-record-20261119.json.gz`: the
     `/v1/models` entries for both ids, the pricing-page figures, and the "never more than listed"
     statement with its URL.
2. **`model_router.py`**
   - Append `neuralwatt-key` at the end of `ACCOUNTS`, so the positional `ACCOUNTS[2:4]` is
     unchanged.
   - CHAINS:
     - mimo: `('opencode-go/mimo-v2.6-pro', 'neuralwatt/mimo-v2.6-pro', 'openrouter/xiaomi/mimo-v2.6-pro')`;
     - glm: `('opencode-go/glm-5.3-flash', 'neuralwatt/glm-5.3-flash', 'openrouter/z-ai/glm-5.3-flash', 'opencode/glm-5.3-flash-free')`.
   - In `routes()`, a `neuralwatt/` route gets billing `paid`, label `('neuralwatt-key',)` and pool
     `neuralwatt-key`.
   - `route_maximum` returns `nw_maximum`.
   - `ungated_lanes` includes `NW_ROUTES`.
   - `lasting()` is unchanged, so a credit or quota block on `neuralwatt-key` expires on its backoff.
   - Router config: `capacities['neuralwatt-key'] = 3`, the Paid level's concurrent floor (Rollout step 1). The off switch is
     `disabled_routes: ["neuralwatt/"]`.
3. **Offered accounts** (`run.Ctx.__init__`, `factory/run.py:163-167`; all three construction sites go through it, and the `helper_link.py:213` override stays)
   - `c.router_accounts` is computed once, when the case context is built:
     `tuple(a for a in ACCOUNTS if a != 'neuralwatt-key' or (SECRETS / a).is_file())`.
   - Every caller already reads `getattr(c, 'router_accounts', ACCOUNTS)`: `_account_order`,
     `await_lease`, `ordinary_retry`, preflight, `bounded_route` and `valid_lease`. So a box without
     the key never counts the lane, and nothing else needs a filter.
   - Only `neuralwatt-key` is filtered. Other missing keys keep today's `credential_expiring`
     behaviour.
4. **`model_runtime.py`**
   - `opencode_config` adds:
     ```
     "neuralwatt": {"npm": "@ai-sdk/openai-compatible",
       "options": {"baseURL": "https://api.neuralwatt.com/v1", "apiKey": "{env:NEURALWATT_API_KEY}",
                   "includeUsage": true},
       "models": {"mimo-v2.6-pro": {"cost": price(twin), "limit": {"context": 1048560, "output": 32768}},
                  "glm-5.3-flash": {"cost": price(twin), "limit": {"context": 1048560, "output": 32768}}}}
     ```
     - The context is Neuralwatt's `max_model_len`, 1048560, which is below the twins' 1048576.
     - The output is `OPENROUTER_OUTPUT`, the same cap the gated OpenRouter config gives OpenCode.
   - `cfg["small_model"] = model` for `neuralwatt/` models, as for `openrouter/` and `opencode-go/`.
   - The env key for `neuralwatt-key` is `NEURALWATT_API_KEY`, at the key-loading site (around line
     600). Not in `diagnosis_environment`: diagnosis runs walled (`user='pilot'`), which excludes
     ungated lanes.
   - `bounded_route` excludes `NW_ROUTES` for `WALLED_ROLES`, as it does Go.
   - Move-on: `go_quota_moves_on` becomes true for an NW lease on reason `quota` or `credit`, so the
     call moves to the OpenRouter twin inside the attempt.
5. **`model_call_gate.py`**
   - `enforce` gets an NW branch with the Go branch's checks: `valid_maximum`, `max_usd > 0`, no
     walled user, scratch XDG dirs. It also requires `lease.account == 'neuralwatt-key'` and
     `NEURALWATT_API_KEY`; otherwise it raises `credential_expiring`.
   - `free_environment` passes `NEURALWATT_API_KEY` for an NW lease, and never `OPENCODE_API_KEY`.
6. **`budget.py`**
   - **Step.** An NW step sets the part's cost to `max(OpenCode's cost, go_step_cost(route, tokens))`
     and books it as case money.
     - `plan_listed` stays None, so the event carries no `priced:'plan'` and no
       `plan_list_cost_usd`.
     - `event_bound_charge` is `cost + plan_list_cost_usd`, so keeping both would count each step
       twice.
     - `check_limits` stops a reserved NW call once `booked + nw_request_worst > maximum`. A step
       books only when it finishes, so without this the next step could book, and be billed, above
       the reservation by up to one request.
   - **Unseen tail.**
     - `_run_budgeted` writes `invocation_reservations[lease_id]['open_steps']` inside its exit
       transaction, for a reserved call. The value is the number of OpenCode
       `session:messageID` keys in `starts − finishes`.
     - `_settle_leaf`, for `NW_ROUTES`, books `min(bound − booked, n × nw_request_worst(route))`.
       This applies only when the field is present, no `cancellation-failed:` or `unverified-*`
       key is open, and `cleanup_errors` did not grow. Otherwise it keeps today's `bound − booked`.
     - `n` is `open_steps` for a classified credit, rate or quota refusal, or OpenCode's own `error`
       event (`opencode_error`), since each ends the request. It is
       `max(open_steps, 1)` for any other stop (stall, timeout, cancel), because a request can be
       in flight before its step-start part appears.
     - A credit refusal with no step open books $0.
     - Neuralwatt never bills above list, so this is an upper bound. One request is bounded by
       `nw_request_worst` only because OpenCode sends `max_tokens` ≤ `limit.output` (32768),
       which is below the twin's output.
7. **`durable/classify.py`**
   - Add `("neuralwatt/", "router:neuralwatt_limit")` to the limit-family prefixes.
   - Add `router:neuralwatt_limit: WAIT` to `stop_registry.py:59`. `REASONS` and
     `PUBLISHED_REASONS` derive from `_LIMIT_FAMILY`.
   - A Neuralwatt 402 then reads as that provider's limit with its short backoff. It is not
     `router:credit`, which parks for an OpenRouter top-up.
8. **Neuralwatt errors, pinned on real bodies** (Rollout step 1).
   - Every Neuralwatt 402 is type and code `payment_required`; the message never says "insufficient
     credits". The status code alone makes it `credit`, scope `wallet`: no classifier change.
   - Every 429 (`concurrent_budget_exceeded`, `tpm_uncached_exceeded`, `tpm_uncached_request_too_large`)
     is `rate`; 503 `model_overloaded` and 404 `model_not_found` are `outage`; 401 is unclassified
     and ends the call as `opencode_error` (a revoked key is not reported to the router).
   - **Fix in `budget._run_budgeted`, Neuralwatt lanes only.** The first `rate` error is let through as
     a notice, for CLIs that keep going. OpenCode's error event with an HTTP status comes after
     OpenCode's own retries, so nothing follows it: a Neuralwatt 429 ended the call as `missing_usage`,
     never told the router, and booked one whole request ($0.57) as a phantom tail. On an NW lane such
     an event is now terminal and stops the call as `provider_limit` with `rate`. A status-less
     "retrying" message stays one notice
     (`test_budget.test_rate_limit_must_persist_and_tool_text_is_not_a_provider_error`).
   - Go and free lanes are unchanged on purpose. Their status-coded 429 still ends as `missing_usage`,
     which excludes that one lane; `rate` is keyed on the pool (`model_router.observe`) and would block
     the whole Go account, plan routes included, for 900-3600 s.
   - **What `rate` then does on NW.** `go_quota_moves_on` is false for `rate`, so the attempt defers. The
     router blocks the whole `neuralwatt-key` pool for 900 s, rising to 3600 s (no reset time is passed
     on: `retry_strategy` and `Retry-After` are not read). The next lease takes the chain's next open
     lane: Go if its plan has quota, else the OpenRouter twin.
   - `tpm_uncached_request_too_large` is not retryable. It fires when one request's uncached prompt
     exceeds the level's per-minute window: 75,000 tokens on Trial, which ordinary factory steps
     exceed, and 1,000,000 from Paid up. Hence step 6's precondition: the account is at Paid level or
     higher (an operator check; responses carry `x-subscription-plan`). Known cost, recorded: on Paid, a
     cold request between 1,000,000 tokens and the 1,048,560 context blocks Neuralwatt for every case
     for 15-60 minutes. MiMo steps have run to about 500k (the 2026-10-17 compaction note in
     `model_runtime.opencode_config`), so no code for it.
   - Tests: `tests/factory/test_neuralwatt_budget.py` runs OpenCode's real event streams for both
     models, and every body in `tests/factory/fixtures/neuralwatt-smoke-20261119.json` inside
     OpenCode's real `APIError` event (captured with a bad key).
9. **`bin/setup-secrets neuralwatt`**
   - It prompts for the key without echo and checks that the key starts with `sk-`.
   - It writes `$tmp/neuralwatt-key`, the same as the `opencode-2` branch, and re-encrypts the bundle.

## Rollout runbook

Strictly in this order. No release reaches any batch until step 3 is done.

1. **Key on the VM, smoke on the trial. Done 2026-11-19** (`tests/factory/fixtures/neuralwatt-smoke-20261119.json`).
   - The founder put the trial key in `/home/user/.neuralwatt-trial-key` (mode 600). A one-off script
     read it without printing it and ran generic prompts on both model ids, directly and through
     OpenCode 1.19.0 with the factory's `opencode_config`, behind a relay that logged request bodies.
   - Usage is streamed (`include_usage`) and every OpenCode step part carries non-zero tokens, priced
     at the twin. Prompt caching works (6,288 of 6,432 tokens read from cache on a second step).
   - OpenCode sends `max_tokens` 32000 (≤ 32768). Neuralwatt itself accepted `max_tokens` 5,000,000,
     so the cap is OpenCode's alone.
   - Billed: $0.00085 for all of it (energy pricing); the OpenCode steps alone were $0.0041 at list.
   - Speed, one sample each: GLM-5.3 Flash ~90 tokens/s; MiMo-V2.6-Pro ~10 tokens/s, 3.6 s to first token.
     Recheck MiMo on a paid level before relying on it for long writer steps.
   - 401 and 404 bodies are real. 402, 429 and 503 bodies come from Neuralwatt's docs (marked
     `source: docs`); provoking them would spend the trial.
   - Limits per account level (docs): Trial 2 concurrent / 75k uncached tokens a minute; Paid (any
     payment) 3 floor, 6 burst / 1M; Standard ($50 total spend) 5/10; Pro ($500) 10/14.
2. **Merge and install**, after the diff review.
   - Run `unbug install` for the release. Nothing uses it yet: a batch's plumbing is fixed in its
     start spec (`contract.py:357`), and only `plumbing_release <batch>` or a new start spec moves
     a case.
3. **Router: new code, config, then a drained restart.**
   - *Superseded for the VM (2026-11-20):* the router runs from `source-current` through a systemd
     drop-in. See "Neuralwatt first", Deploy step 3.
   - The router runs from its own checkout (`control/unbug-model-router.service`:
     `/home/user/unbug-bench/factory/model_router.py`), which neither `unbug install` nor
     `source-current` moves. Fast-forward that checkout to the release commit first, then check
     `python3 -c "import sys; sys.path.insert(0,'factory'); import model_router; assert 'neuralwatt-key' in model_router.ACCOUNTS"`
     in it. Old router code refuses `neuralwatt-key` in its config (`Store.__init__`: `unapproved
     account`), so it would not start, and every acquire on every batch would fail
     `router_unavailable`.
   - Record `git -C /home/user/unbug-bench rev-parse HEAD` first (the rollback target), and check
     whether `unbug-durable.service` is active: it runs `factory/durable/cli.py` from the same checkout.
   - Add `neuralwatt-key` to the router config `accounts`, set `capacities['neuralwatt-key'] = 3`,
     and add `"neuralwatt/"` to `disabled_routes`, keeping any existing entries, then restart the router while no model calls are in
     flight. That is the only time config changes take effect (`model_router.py:1153-1156`).
   - Harmless on its own: no caller offers the account until step 6, and the lane is off.
   - Rollback: drain, remove `neuralwatt-key` from the router config, restart, and only then move
     the checkout back. An old router that still sees a request offering `neuralwatt-key` fails
     every acquire for about `LEASE_SECONDS` (its queue scan, `model_router.py:552`), so no caller
     on this release may still be running when the router goes back.
4. **Controller on new code.**
   - Point `source-current` at the release source, then run
     `sudo -n /usr/bin/systemctl restart unbug-durable-case-campaign.service`.
   - `ACCOUNTS` now knows `neuralwatt-key`.
5. **Which cases get the release.**
   - Send `plumbing_release <batch>` to each batch that should use it: new launches, and running
     cases not yet past G10. Never cases past G10 (standing rule).
   - A case picks it up at its next checkpoint, which reruns its changed gates. That cost is
     accepted per batch, by operator choice.
   - Safe before step 6: no box carries `neuralwatt-key` yet, so `offered_accounts()` never offers
     it. No client counts a lane it can't spend, so there is no cae763-style retry loop.
6. **Lane on.** Only on an account at Paid level or higher (item 8), and only after the step 1
   follow-up commit is reviewed, installed and live on the controller: steps 2, 4 and 5 again for the follow-up release (and step 3 if it touches
   `model_router.py`), because item 8 runs on the worker. Key and switch go together, never the key alone:
   1. Back up `bundle_file` and the controller config.
   2. The founder runs `bin/setup-secrets neuralwatt`, starting from a Mac bundle that holds every
      key the VM bundle holds.
   3. On the VM, check the new bundle before installing it: `age -d -i <identity_file> <new> | tar -t`
      must list every name in `worker_credentials.accounts` plus `neuralwatt-key`.
   4. Drain the router. Remove only the `neuralwatt/` entry from `disabled_routes`, keeping any
      other entry, then restart the router.
   5. Install the bundle with `mv`, add `neuralwatt-key` to `worker_credentials.accounts`, and
      restart the controller.
   - Rollback, key first and lane last (the forward order reversed):
     1. Restore the bundle backup, remove `neuralwatt-key` from `worker_credentials.accounts`, and
        restart the controller. From now on, every new acquire delivers secrets without the key.
     2. Wait until every live case has started a new step, which re-delivers secrets. Each step's
        `router_accounts` is fixed at `Ctx` init, so a step that already holds the key keeps
        offering it. In an emergency, end those steps instead: SIGTERM every process of the attempt
        (the forked attempt child and the agent programs it started, as `stop(key)` finds them,
        `factory/durable/worker_step.py:172-180`), but not the `supervise` parent. The parent then
        finds no result and books `infra:step_crashed` (`factory/durable/worker_step.py:470-471`),
        an infra retry, and the retry gets the new secrets. Send no helpers during the wait: a
        helper's job copies the parent's `router_accounts` (`factory/durable/helper_link.py:213`),
        key included, onto a box that has none.
     3. Only then drain the router, put `neuralwatt/` back in `disabled_routes`, and restart it.
        Done in the other order, a keyed step counts a lane it can never lease, and a malformed
        answer loops on outage waits (the cae763 shape).
     4. Nothing to clean up in retry state. A case that spent an NW lane keeps that route in
        its snapshot's `ordinary-retries/*/state.json`. `ordinary_retry.answer` checks saved routes
        against every account the code knows, not the ones offered now, so the route stays valid
        with the key gone (test: `test_a_spent_neuralwatt_route_survives_the_key_being_withdrawn`).
     5. Remove `neuralwatt-key` from `worker_credentials.accounts` before any controller downgrade,
        or the controller refuses to start (`invalid_worker_accounts`).
   - A case that ran an NW call is never moved below this release: its ledger's reservation rows
     carry `open_steps`, which older `usage_coverage` reads as unknown coverage.

**Known costs, recorded.**
- A case with less money left than one whole request ($0.57 MiMo, $0.63 GLM, $0.79 DeepSeek) gets an NW
  reservation that stops before sending and books its small bound. This over-counts only.
- The pre-stop at `booked + nw_request_worst > maximum` can label a call that finished within one
  request of its maximum `usage_reservation_exceeded`. That is retried as infra.
- Not verified: OpenCode's side calls on `small_model`, such as session titles, may emit no step
  parts. Step 1 compares the trial account's Neuralwatt usage against the booked steps, and the
  "upper bound" claim waits on that check.

## What it deletes

Nothing. Go and NW share one twin map, not two copies.

## Not in scope

- Reconciling against Neuralwatt's usage API. Booking at list is an upper bound; add
  reconciliation if the over-count ever blocks a case.
- A router-side money ceiling. `paid_ceiling_usd` covers only gated OpenRouter, so Neuralwatt spend
  is bounded by case and batch money only. The prepaid trial plus the backoff on a 402 is the
  provider-side stop.
- DeepSeek V4.1 Flash. Neuralwatt's cached-input price is twice OpenRouter's.
- Subscriptions (founder: after the trial).

## Tests

- **Routes, on real router state.**
  - Load the real 11-19 health rows (`openrouter-key` credit block, Go quota rows whose backoff
    had lapsed, so the replay observes Go's quota answer) from
    `factory.before-force-lift-20261119.sqlite3`; health rows only, no keys. Saved as
    `tests/factory/fixtures/router-health-20261119.json`, with the source query in the test
    docstring.
  - Acquire for a real saved MiMo and GLM role (from a real card fixture) with `neuralwatt-key`
    offered. It gets `neuralwatt-key/neuralwatt/…`.
  - With the old `ACCOUNTS`, or no key file (via `router_accounts`), the same acquire gets no NW
    lane.
  - Walled roles get no NW lane (`bounded_route` and `ungated_lanes`).
- **Maximum.** `nw_maximum` equals the twin's maximum except `price_source`, and `valid_maximum`
  accepts a funded NW lease. The price record has `service_tier == "standard"`, and its listed prices
  equal the pins.
- **Budget.**
  - Using the real captured NW step part (step 1 follow-up; a Go-shaped stand-in until then), the
    step books the twin list cost.
  - The same step on Go books $0.
  - An NW event has no `plan_list_cost_usd`, and `event_bound_charge == cost`.
  - A credit refusal with no step open books a $0 tail.
  - One open step books `min(bound − booked, nw_request_worst)`.
  - A stall with no step-start books one `nw_request_worst`.
  - With a `cancellation-failed:` key open, the tail falls back to `bound − booked`. (`unverified-*`
    keys are set only for Codex and Claude streams, so no NW call reaches them.)
  - A step within one `nw_request_worst` of the maximum stops the call; the next step never books.
- **Gate.** In the `enforce` NW branch:
  - no key → `credential_expiring`;
  - walled user → `route_feature_unsupported`;
  - the environment carries `NEURALWATT_API_KEY` and no other provider key.
- **Move-on** (step 1 follow-up commit). The real captured 402 body classifies as `credit` and moves to the OpenRouter twin,
  with case money unchanged by the tail.
- **Classify.** A Neuralwatt 402 wait maps to `router:neuralwatt_limit`, not `router:credit`.
- **Config.** `opencode_config` contains the exact Neuralwatt provider block above.
- Full suite.

## Murphy rows

The register is not on `main`. The row is recorded here and goes into the register when that file
lands.

- New row `new-neuralwatt-1`: "single paid provider: OpenRouter balance exhaustion parks every case
  on the MiMo/GLM fallback" (seen 2026-11-19; seven cases parked).
  - It is closed by the real-router-state routes test plus the move-on test on the captured 402.
  - The move-on fixture exists only after rollout step 1's capture, so the row closes in that follow-up commit.

## Neuralwatt first (2026-11-20)

Founder, 2026-11-20: no OpenRouter top-up (about $10 left). Paid traffic goes to Neuralwatt, with
OpenRouter as the fallback only. Go stays first, because it is a subscription.

### Which paid OpenRouter models Neuralwatt serves

The inventory comes from three sources:
- `CHAINS`;
- the role models in all 101 `inputs-*.json` files on the control VM, which the `$SP/handfix/*/`
  launchers write;
- the router's paid ledger for the last 7 days (`paid_requests`, read-only).

Neuralwatt's catalog is `/v1/models`, read 2026-11-19 23:51Z and saved as
`tests/factory/fixtures/neuralwatt-price-record-20261120.json.gz`.

| OpenRouter route | Roles (VM inputs) | Paid OR, 7 days | Neuralwatt | Moves |
|---|---|---|---|---|
| `xiaomi/mimo-v2.6-pro` | builder, reviewers | $79.66 | `mimo-v2.6-pro`, list = pin | live since 11-19 |
| `z-ai/glm-5.3-flash` | reviewers, easy_calibrator | $15.49 | `glm-5.3-flash`, list = pin | live since 11-19 (not for easy_calibrator, see below) |
| `deepseek/deepseek-v4.1-flash` | attacker, builder (October cards also have a walled DeepSeek easy_calibrator) | $12.37 | `deepseek-v4.1-flash`: 0.15 / 0.015 / 0.6, against the pin's 0.14 / 0.0042 / 0.42 | **yes, this change** |
| `minimax/minimax-m3.1-flash` | attacker, builder | $9.52 | not served | no |
| `meta/muse-spark-1.3-contributor` | builder | $0.29 | not served | no |

- **DeepSeek.** It was deferred on 11-19 because Neuralwatt's list price is above OpenRouter's. The
  founder now prefers Neuralwatt anyway.
  - Neuralwatt bills by measured energy: about 45% of list by the operator's 11-20 measurement (lines
    23-24 above give 20-27% below list for MiMo and GLM over 7 days).
  - DeepSeek V4.1 Flash is in the free Flash promo: 50 Wh a day on Basic, until 2027-01-01.
  - **Case money is still booked at list (review 1, B2).** Every Neuralwatt step books
    `max(OpenCode cost, go_step_cost)` (`budget.py:1410-1413`), and for DeepSeek that is now Neuralwatt's
    own list. So the list is both the reservation bound and what each step books, not what Neuralwatt
    bills.
    - On the real 7-day OpenRouter DeepSeek token mix (1,962 requests with usage: 156.5M prompt tokens,
      149.7M of them cached, 2.75M completion; read-only from `paid_requests.usage`), the booking is:
      - $2.73 at the OpenRouter pin;
      - $4.91 at Neuralwatt's list, 1.8×, mostly cache reads (0.015 against 0.0042).
    - On 11-19, with OpenRouter credit-blocked and both Go plans on quota, DeepSeek parked on credit.
      Its free lane runs on the Go account pools, so it was blocked too (the routes test shows this).
      It now runs and books list.
    - **For the founder to confirm (review 3, N4).** This change assumes that "Neuralwatt anyway"
      covers booking case money at Neuralwatt's list: 1.8× OpenRouter's pin on the 7-day DeepSeek
      mix. That is the author's reading, not a ruling yet. Reconciliation with Neuralwatt's usage API
      stays out of scope, as before.
- **Lanes not used:**
  - `-speed` lanes, which are billed above list;
  - `-flex` lanes, which are a different service tier and are held during peaks.
- **MiniMax and Muse** stay on OpenRouter, after Go. Among the routes that still fall back to
  OpenRouter, MiniMax spends the most.

### Change

1. **`token_prices.py`**
   - **New twin.** `NW_TWINS['neuralwatt/deepseek-v4.1-flash'] = 'openrouter/deepseek/deepseek-v4.1-flash'`.
   - **Own prices.** `NW_OWN_PRICES = {'neuralwatt/deepseek-v4.1-flash': ('0.15', '0.015', '0.6')}`.
     - It holds Neuralwatt's list for a route whose list is above its twin's pin.
     - The route's profile is the twin's profile with these prices:
       - context 1048576, output 1048576, windows 2, cache_write 0;
       - `endpoint='standard'` (the service tier);
       - `source_date='2026-11-20'`.
   - **Shared maximum.** The maximum body moves into `_gate_maximum(name, profile)`.
     `openrouter_gate_maximum(route)` calls it with `GATED_OPENROUTER.get(route)`, so its output does not change.
   - **`nw_maximum(route)`.**
     - A route with no own prices keeps exactly today's value, `neuralwatt:<model>:twin=<twin source>`.
       MiMo and GLM leases are byte-identical, so a worker on 3dfdde3c still validates them.
     - DeepSeek gets
       `neuralwatt:deepseek-v4.1-flash:own=token_prices:2026-11-20:neuralwatt:deepseek-v4.1-flash:standard:0.15,0.015,0.6:joint-gate-v1`.
       That is $1.572865 (2 × 0.786432 + 0.000001). Funded windows scale from it, as for every route.
   - **Prices used for booking.** `runtime_prices(route)` and `nw_request_worst(route)` read the
     route's profile, so its own prices win. They feed:
     - booking (`go_step_cost`);
     - OpenCode's step cost;
     - the tail and pre-stop bound.
   - **One request's bound.** `nw_request_worst('neuralwatt/deepseek-v4.1-flash')` is $0.786432. It
     holds as in N8:
     - the profile's output is 1048576, while Neuralwatt allows 393216 (`limits.max_output_tokens`);
     - OpenCode sends `max_tokens` ≤ `limit.output` = 32768 (the 11-19 smoke saw 32000);
     - so one request costs at most 1048560 × 0.15 + 32768 × 0.6 = $0.177, below the bound.
   - **Evidence for the upper bound.** In the saved record, DeepSeek's entry has
     `service_tier == "standard"` and context 1048560. The pricing statement reads "no standard or
     flex request costs more than its listed token price (speed lanes are priced above it)". So
     booking at Neuralwatt's own list is an upper bound.
2. **`model_router.py`**
   - **Chain.** The DeepSeek chain becomes
     `('opencode-go/deepseek-v4.1-flash', 'neuralwatt/deepseek-v4.1-flash', 'openrouter/deepseek/deepseek-v4.1-flash', 'opencode/deepseek-v4.1-flash-free')`.
     `routes()`, `ungated_lanes()` and `route_maximum()` already cover every member of `NW_ROUTES`.
   - **The caller's chain** (cross-version fix, below). `chain(model)` is factored out of `routes()`.
     - `_admit` sends `chain=chain(model)` in `acquire`.
     - The router validates it: a list of at most 16 route-shaped strings.
     - The router leases only lanes the caller `knows`, in two places: its `choices` and its
       queue-ahead check over older requests.
     - `knows(request, route)`:
       - if the caller sent a chain, `route in request['chain']`;
       - if it did not, `route not in LATE_ROUTES`, where `LATE_ROUTES = {'neuralwatt/deepseek-v4.1-flash'}`
         is every lane added to `CHAINS` after 3dfdde3c.
     - Five lines in the acquire path. The parallel router-retry change edits nearby lines, so merge it
       with care.
3. **`model_runtime.opencode_config`.** The Neuralwatt provider's model cost becomes `price(route)`
   instead of `price(NW_TWINS[route])`.
   - The value is the same for MiMo and GLM, and Neuralwatt's own list for DeepSeek.
   - The provider block gains `deepseek-v4.1-flash` with `limit {context 1048560, output 32768}`.
4. **Nothing else changes.** All of these are keyed on `NW_ROUTES` or the `neuralwatt/` prefix:
   - the gate (`enforce`) and key handling;
   - move-on and classify;
   - the item 8 terminal 429;
   - the tail settle.

### Cross-version hazard: an old worker handed a lane it does not know

**How the versions mix.** Each worker runs its batch's plumbing release, so the shared router serves
callers on several releases at once.
- **Where the router runs.** On the control VM it runs from `source-current`. Checked 2026-11-20 with
  `systemctl cat unbug-model-router.service`: the last `ExecStart`, in the drop-in
  `zzz-approved-ceiling.conf`, is
  `…/durable-first-case-20261106/source-current/factory/model_router.py --config …/router-approved-config.json`.
  It overrides the checked-in unit's `/home/user/unbug-bench` path. The 11-19 runbook (its step 3)
  and `control/unbug-model-router.service` still name that path; the deploy steps below supersede both
  for the VM.
- **The controller** (`unbug-durable-case-campaign.service`) also runs from `source-current`.

**Who is exposed.** Workers on 3dfdde3c already offer `neuralwatt-key`, but their `CHAINS` know only
MiMo and GLM on Neuralwatt.
- These batches are 04d417-h6 and 5813be-h2, plus cae763-h4 and f46dac-h6 by `plumbing_release`.
- Every live case has a DeepSeek attacker or builder.
- The router ledger holds a real 3dfdde3c DeepSeek request that offers the key, saved as
  `router-request-3dfdde3c-deepseek-20261120.json`.

**What happens.** Suppose a new router hands such a worker `neuralwatt/deepseek-v4.1-flash`:
1. The worker's `_admit` finds the lease outside its own `routes()`. It raises
   `RouterUnavailable('invalid lease response')` and never finishes the lease.
2. The lease holds one of the three Neuralwatt seats until it expires (180 s).
3. The worker replays the same lease until `WAIT_SECONDS`, then parks as `router_unavailable`.
4. The next attempt repeats all of this.

That is the cae763 loop, and it also starves the MiMo and GLM Neuralwatt calls.

A waiting 3dfdde3c DeepSeek request does further harm. The router computes its lanes with the new
`CHAINS`, so the request queues ahead of every newer request for the `neuralwatt-key` pool, MiMo and
GLM included, on a lane it can never take.

**Who is safe.**
- Releases without `neuralwatt-key` in `ACCOUNTS` never offer the key.
- 6ed7c545 (PR #197) offers the key and has the same `CHAINS` as 3dfdde3c, so it is covered the same
  way. No `source-6ed7c545` is installed on the VM, so no batch runs it.

**Why the off switch is not enough (review 1, B1).** Putting the lane in `disabled_routes` protects the
3dfdde3c workers, but it loops the new ones instead:
- their own chain counts a lane the router never leases;
- `ordinary_retry.answer` never reaches exhausted;
- the router answers `outage`.

This is diff-3's B1 shape.

**Fix: the caller sends its chain** (Change item 2).
- **Old callers.** A 3dfdde3c caller sends none, so it is never offered `LATE_ROUTES` and never queues
  on them. It still gets the MiMo and GLM Neuralwatt lanes it knows.
- **New callers.** A new caller sends its chain, so it gets every lane it counts.
- **No switch.** Nothing is disabled and no second router restart is needed. Every future chain
  change is guarded too, because a new caller is offered only what it sent.
- **Removing `LATE_ROUTES`.** It can be deleted once no batch on a key-offering release that sends no
  chain (6ed7c545 or 3dfdde3c) is live or held.
- **Deploy order.** The router must restart on this code before any worker runs it. An old router
  refuses the unknown `chain` field (`invalid admission fields`). That is the deploy order below,
  which the router-retry restart already needs.

### Walled roles (easy_calibrator) and Neuralwatt

**What the wall requires of a route.** A walled role runs as `pilot`. That user's only network path
is one iptables owner rule, inserted per lease, to the gate's port on 127.0.0.1
(`model_call_gate._wall_access`). So a walled lane needs a `Gate` in the worker that:
- holds the real key, while the walled process gets only a random per-gate token;
- forwards only to one fixed upstream host, `openrouter.ai` or `api.anthropic.com`, with no override;
- accepts only allowlisted request bodies (`openrouter_body`):
  - text only;
  - local function tools only;
  - the leased model;
  - `max_tokens` clamped;
- holds each request's worst case before forwarding (`Allowance.reserve`);
- refunds only on a validated terminal usage frame (`OpenRouterUsage`);
- for OpenRouter, also takes a shared paid reservation in the router (`paid_reserve` and
  `paid_settle`), bound to `openrouter-key` and the OpenRouter credit ledger (`model_router.py:672`).

**Why Neuralwatt fails it today.** Neuralwatt is an ungated OpenCode provider: OpenCode talks to
`api.neuralwatt.com` directly, with the key in its environment. That is exactly what the wall
forbids, so `test_walled_roles_never_take_the_neuralwatt_lane` is correct and stays.

**Can Neuralwatt be gated safely? Yes, but not in this change.**
- **It is safe.** The wall is network isolation plus a request allowlist, and neither depends on the
  provider. A gate that forwards to `api.neuralwatt.com` keeps the wall intact.
- **It is not a routes, prices or chains change.** It adds a new upstream to the security-critical
  gate, which needs:
  - a per-route upstream host and path;
  - a body filter without OpenRouter's `provider` and `usage` fields;
  - a usage parser pinned on real Neuralwatt streams. A generic DeepSeek smoke on 11-20 (two calls,
    about $0.000002 each) showed an OpenAI-style stream:
    - one usage frame with `choices: []`;
    - `: energy` and `: cost` SSE comments;
    - no repeated terminal choice.

    `OpenRouterUsage` would probably accept it, but that has to be proved.
  - no router `paid_reserve`. Spend would be bounded by the gate's per-request hold and by case
    money, as Neuralwatt lanes are today.
  - `ungated_lanes` and `bounded_route` switched from "Neuralwatt is ungated" to "Neuralwatt is gated
    for walled roles".
- **It also touches the router's paid path**, which the parallel router change is editing.

**Science note for the founder.** The easy calibrator is a measuring instrument.
- Today it reads GLM through OpenRouter's pinned endpoints: deepinfra/fp4, relace/fp4 or morph/fp8.
- Neuralwatt serves GLM at fp8.
- The founder's ruling of 11-19, "same models from a different provider is fine", technically covers
  this. Calibrator precision already varies between fp4 and fp8.
- Still, moving the calibrator to another provider mid-campaign is the founder's call, not ours.

**Options for the founder.** None of these has code in this change.
- **A. Keep walled roles on OpenRouter (the default).**
  - Over 7 days, easy_calibrator GLM cost $3.29 on OpenRouter, about $0.47 a day.
  - If only walled roles use OpenRouter, $10 lasts about three weeks, less whatever the MiniMax and
    Muse fallbacks spend.
- **B. A gated Neuralwatt lane for walled roles.**
  - A follow-up branch, after the router-retry change lands.
  - Its own design, real Neuralwatt streams through the gate, and a goldfish review.
  - About half a day.
- **C. B plus a ruling** that the calibrator may move providers mid-campaign.

### Seats

- Neuralwatt Basic gives 3 concurrent requests (6 burst), and the router has
  `capacities['neuralwatt-key'] = 3`.
- With OpenRouter nearly empty, those 3 seats are all the paid capacity for MiMo, GLM and DeepSeek
  whenever both Go plans are on quota. Both plans were on quota for most of 11-19 and 11-20.
- Over the last 7 days, OpenRouter served 13,153 MiMo, GLM and DeepSeek requests for unwalled roles.
- **Concurrency (review 1, N7),** read-only from the router ledger. Each lease runs from its request's
  `created` to `expires − 180`. Counted over all Go, Neuralwatt and OpenRouter leases of these three
  models in the last 7 days, the concurrent count was:
  - 0 for 55% of the time;
  - 1 for 30%;
  - 2 for 7%;
  - 3 for 4%;
  - more than 3 for about 4%;
  - 10 at its peak.

  So 3 Neuralwatt seats cover about 96% of the time, even with Go fully on quota.
- **When the seats are full.** A call takes the next open lane in its chain.
  - GLM spills to its anonymous free lane.
  - MiMo and DeepSeek wait for a seat (`capacity`, up to 30 minutes) or use OpenRouter credit.
    DeepSeek's free lane runs on the Go account pools, so it is blocked whenever Go is on quota.
  - The DeepSeek attacker on every live case now competes with MiMo for the 3 seats. That is still
    better than parking on credit.
  - Any spill onto OpenRouter eats into the $10 that option A keeps for walled roles.
- More seats need a higher Neuralwatt level:
  - Standard (5 floor, 10 burst) after $50 of total spend;
  - or a larger plan.

  That is the founder's money call.
- **Recommendation: no more seats now.** Revisit if the router's `capacity` waits on `neuralwatt-key`
  grow.

### Tests (real fixtures)

- **`test_neuralwatt_routes.py`**
  - **DeepSeek on real 11-19 state.** It uses the real 11-19 router health (Go on quota, OpenRouter
    credit-blocked) and e15450's real DeepSeek stress_tester model.
    - An acquire that offers the key gets `neuralwatt-key/neuralwatt/deepseek-v4.1-flash`.
    - The same acquire without the key does what it did on 11-19.
  - **The caller's chain.** It replays the real 3dfdde3c request, which sends no chain.
    - It is never offered the DeepSeek Neuralwatt lane, which lies outside 3dfdde3c's chain, pinned as
      a literal.
    - The same request from this release, with its chain, gets the lane.
    - The 3dfdde3c caller still gets MiMo's Neuralwatt lane.
    - A waiting 3dfdde3c DeepSeek request does not queue ahead of a newer MiMo request on the
      Neuralwatt pool.
    - `_admit` sends the chain.
    - A malformed chain is refused.
    - Each `knows` filter was removed in turn, and the tests failed each time.
  - **The wall.** Walled GLM and DeepSeek (a real October card has a DeepSeek easy_calibrator) still
    never get a Neuralwatt lane.
- **Maximum**
  - MiMo and GLM `nw_maximum` values are byte-identical to 3dfdde3c's, pinned as literals.
  - The twin-equality checks loop over `NW_TWINS` minus `NW_OWN_PRICES`.
  - DeepSeek's maximum is built from Neuralwatt's own list in the 11-20 record. The record shows
    `service_tier == "standard"` and context 1048560.
  - `runtime_prices` and `go_step_cost` for DeepSeek on Neuralwatt use 0.15 / 0.015 / 0.6, never the
    twin's prices.
  - `nw_request_worst` is $0.786432, which is at least the clamped worst case of one request ($0.177).
  - `funded_maximum` and `valid_maximum` accept a funded DeepSeek Neuralwatt lease.
- **Runtime.** The exact provider block has three models, and DeepSeek's cost is Neuralwatt's list.
  - No provider-block id ends in `-speed` or `-flex`.
  - Each id's catalog entry is `service_tier == "standard"`. That check is secondary, because `-speed`
    entries are also listed as standard.
- **No OpenCode capture for DeepSeek on Neuralwatt (review 1, N6).**
  - The 11-19 OpenCode capture ran in a worker sandbox with the trial key. Copying the key onto a live
    case's box is not done here.
  - The direct 11-20 smoke does show:
    - a streamed usage frame (`include_usage`) for `deepseek-v4.1-flash`, with reasoning tokens counted
      in `completion_tokens`;
    - the same model id as the provider block.

    The capture is saved under the operator scratchpad, not as a fixture: no test reads it.
  - DeepSeek runs through the same `@ai-sdk/openai-compatible` provider block as MiMo and GLM.
  - First-hour check after deploy: a DeepSeek Neuralwatt step books non-zero tokens (deploy step 4).
- Full suite.

### Murphy rows

`docs/murphy-register.md` is still not on `main` (review 3, N5). So, as with `new-neuralwatt-1`, these
rows are recorded here, together with their closing tests, and go into the register when that file
lands.

- **`new-neuralwatt-2`:** "no OpenRouter credit (founder: no top-up), so every DeepSeek paid fallback
  parks". The DeepSeek real-state routes test closes it.
- **`new-neuralwatt-3`:** "a router whose chains name a route that an older worker does not know hands
  that worker a lease it rejects; the lease dangles and holds a seat (the `invalid lease response`
  loop)".
  - It is closed by the caller's-chain tests on the real 3dfdde3c request.

### Deploy (operator, after merge; this change does none of it)

**The router goes first.** An old router refuses the new `chain` field, so no worker may run this
release before the router does.

1. **Check the merged tree.** On the tree that merges this change and the router-retry change, run
   `BENCH="$PWD" python3 -B tests/factory/test_neuralwatt_routes.py`. It fails if the merge dropped
   `chain` from the acquire's allowed fields.
2. **Stage, but switch nothing.** Run `control/release.py build-plumbing <release>`.
   - It archives the tree to `~/.unbug-release/plumbing-<short>/source` and builds its bundle. The 11-19
     hand form (`nw-deploy.sh`: `source-<short>` plus `workers.py release`) is equivalent; below, "the
     release tree" is whichever was built.
   - Check that tree with the router's own interpreter:
     `cd <release tree>; /usr/bin/python3 -c "import sys; sys.path.insert(0,'factory'); import model_router as m; assert 'neuralwatt/deepseek-v4.1-flash' in m.CHAINS[0] and 'neuralwatt-key' in m.ACCOUNTS and hasattr(m, 'knows')"`.
   - Do not install or launch anything, and do not touch `source-current`.
3. **Confirm the loaded router unit.** `systemctl show -p ExecStart --value unbug-model-router.service`
   (the loaded unit, not just the files on disk) must run
   `…/durable-first-case-20261106/source-current/factory/model_router.py --config …/router-approved-config.json`.
   If it names another checkout:
   - move that checkout to the release in step 4, as well as `source-current`, which the controller
     still needs;
   - name both checkouts in the rollback.
4. **Drain, then switch both services back to back.** Run
   `control/release.py switch --config <controller config.json> --plumbing <release> --source-current ~/durable-first-case-20261106/source-current --router-db ~/.unbug-control/router/factory.sqlite3 --unit unbug-model-router.service --unit unbug-durable-case-campaign.service`.
   - It refuses unless `control/check-drained.py` exits 0: no attempt holds a worker without a recorded
     step, and no router lease is unexpired. Rerun it until it passes. Also wait until the router has
     no pending paid request.
   - It then prints `ln -sfn <release tree> source-current` and both restarts. Run them at once, in
     that order.
   - The symlink moves only after both services are drained, and the controller (which imports
     `model_router` lazily) restarts right behind the router, so no old process runs on new files.
   - The router config is unchanged: `neuralwatt-key` stays at 3 seats, and no `disabled_routes`
     entry is added.
   - Verify before going on:
     - `readlink -f source-current` is the release tree;
     - `/proc/$(systemctl show -p MainPID --value unbug-model-router.service)/cmdline` names `source-current`;
     - the router answers `status`, and `unbug status` is clean.
5. **Release to workers, router first, as 11-19 did.**
   - Run `unbug install` for the bundle.
   - Set `current_source*` and `current_plumbing` in `campaign-request.json`.
   - Set `PLUMBING` in `resume_case.py`.
   - Launches and `plumbing_release` may resume now, and not before step 4 is verified.
   - What each batch gets:
     - running batches keep their own release and run as before;
     - the 3dfdde3c batches keep their Neuralwatt MiMo and GLM lanes and never see DeepSeek's;
     - a batch gets DeepSeek on Neuralwatt once it runs this release, and new launches get it at once.
   - **Cost of `plumbing_release` (review 3, N3).** Moving a running batch reruns its model-stage
     gates, because the model `verdict_code` digest changes (`model_runtime.py` and `model_router.py`
     changed). That is the operator's choice per batch, as on 11-19.
6. First hour: check one DeepSeek Neuralwatt step in a case ledger.
   - It books non-zero tokens at 0.15 / 0.015 / 0.6.
   - Neuralwatt's usage for that hour is at or below the booked amount.
7. **Rollback (review 2, B1).**
   - **Never move a batch that ran this release back to 3dfdde3c.**
     - A DeepSeek Neuralwatt route in its `ordinary-retries/*/state.json` `spent_routes` fails
       3dfdde3c's check against its own `CHAINS`, raising `ordinary_retry_state_invalid`.
     - Its ledger's DeepSeek `open_steps` tail would also book the whole bound.
     - This is the existing rule: "a case that ran an NW call is never moved below this release".
   - **Never downgrade the router** below this release while any worker on this release is live. An
     old router refuses `chain`.
     - The router's code is the checkout named in step 3: `source-current` on the VM today.
     - Re-pointing `source-current` back moves the router at its next restart, and moves the
       controller too.
   - **Loop-free rollback of every Neuralwatt lane:** withdraw the key, using "Rollout runbook" step 6,
     rollback steps 1-4.
     - `offered_accounts()` then drops the Neuralwatt lanes from every chain a worker counts.
     - Spent routes stay valid, because they are checked against `ACCOUNTS`.
   - **DeepSeek only:** a fix-forward release that takes it out of `CHAINS`.
   - **Emergency only:** a `disabled_routes` entry alone with a drained restart. It brings back review
     1's B1 loop for keyed workers on this release.
