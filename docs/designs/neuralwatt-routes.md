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
   - Router config: `capacities['neuralwatt-key'] = 8`. The off switch is
     `disabled_routes: ["neuralwatt/"]`.
3. **Offered accounts** (`model_runtime.py`, case context set-up)
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
   - The env key for `neuralwatt-key` is `NEURALWATT_API_KEY`: at the key-loading site (around line
     600) and in `diagnosis_environment`.
   - `bounded_route` excludes `NW_ROUTES` for `WALLED_ROLES`, as it does Go.
   - Move-on: `go_quota_moves_on` becomes true for an NW lease on reason `quota` or `credit`, so the
     call moves to the OpenRouter twin inside the attempt.
5. **`model_call_gate.py`**
   - `enforce` gets an NW branch with the Go branch's checks: `valid_maximum`, `max_usd > 0`, no
     walled user, scratch XDG dirs. It also requires `lease.account == 'neuralwatt-key'` and
     `NEURALWATT_API_KEY`; otherwise it raises `credential_expiring`.
   - `free_environment` passes `NEURALWATT_API_KEY` for an NW lease, and never `OPENCODE_API_KEY`.
6. **`budget.py`**
   - **Step.** An NW step books `max(OpenCode's cost, go_step_cost(route, tokens))` as case money.
     It is not zeroed. It keeps `plan_list_cost_usd`, the same as Go.
   - **Unseen tail.** For an NW route the tail is
     `min(bound − booked, open_steps × nw_request_worst(route))`, where `open_steps` is the number
     of OpenCode `step-start` parts with no matching `step-finish`.
     - No step in flight books $0, so a 402 before any token is free.
     - Neuralwatt never bills above list, so this is an upper bound.
7. **`durable/classify.py`**
   - Add `("neuralwatt/", "router:neuralwatt_limit")` to the limit-family prefixes.
   - Add `router:neuralwatt_limit: WAIT` to `stop_registry.py:59` and to `PUBLISHED_REASONS`.
   - A Neuralwatt 402 then reads as that provider's limit with its short backoff. It is not
     `router:credit`, which parks for an OpenRouter top-up.
8. **`budget.classify_provider_failure`**: Neuralwatt's out-of-credit and rate-limit bodies, as
   captured on the trial (see Rollout step 5), map to `credit` and `rate`.
9. **`bin/setup-secrets neuralwatt`**
   - It prompts for the key without echo and checks that the key starts with `sk-`.
   - It writes `$tmp/neuralwatt-key`, the same as the `opencode-2` branch, and re-encrypts the bundle.

## Rollout runbook

Strictly in this order. Each step is safe on its own.

1. Merge, then install the release (`install`), and make it `current_plumbing` for new batches.
2. Restart the router on the new code, only when drained (no model calls in flight). The router
   offers Neuralwatt lanes only to callers that offer the account, and nobody does yet.
3. Restart the controller on the new code. `ACCOUNTS` now knows `neuralwatt-key`, so step 4 passes
   `invalid_worker_accounts`.
4. The founder runs `bin/setup-secrets neuralwatt` and copies the re-encrypted bundle to the VM's
   `bundle_file`. Then add `neuralwatt-key` to `worker_credentials.accounts` and to the router
   config `accounts`, and restart the controller. Every new box now carries the key. If the bundle
   lacks the key, step 4 is undone, because `pack` raises.
5. Smoke test on a worker box, with a non-case prompt, before any case gets the release. Check:
   - both model ids answer through OpenCode with `@ai-sdk/openai-compatible`;
   - tokens and usage are non-zero;
   - speed (tokens per second).

   Capture a real 402 body by exhausting a tiny request budget if possible, or from Neuralwatt's
   error docs, and save it as the move-on fixture. Save one real NW step part as the budget-test
   fixture.
6. Send `plumbing_release <batch>` to each batch that should use it: new launches, and running
   cases that have not yet passed G10. Never send it to cases past G10 (standing rule).
   - A case picks the release up at its next checkpoint, which reruns its changed gates.
   - That cost is accepted per batch, by operator choice.

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
  - Load the real 11-19 health rows (`openrouter-key` credit block, Go quota blocks) from
    `factory.before-force-lift-20261119.sqlite3`; health rows only, no keys.
  - Acquire for a real saved MiMo and GLM role (from a real card fixture) with `neuralwatt-key`
    offered. It gets `neuralwatt-key/neuralwatt/…`.
  - With the old `ACCOUNTS`, or no key file (via `router_accounts`), the same acquire gets no NW
    lane.
  - Walled roles get no NW lane (`bounded_route` and `ungated_lanes`).
- **Maximum.** `nw_maximum` equals the twin's maximum except `price_source`, and `valid_maximum`
  accepts a funded NW lease.
- **Budget.**
  - Using the real captured NW step part, the step books the twin list cost.
  - The same step on Go books $0.
  - A 402 receipt with no steps books a $0 tail.
  - One open step books `min(bound − booked, nw_request_worst)`.
- **Gate.** In the `enforce` NW branch:
  - no key → `credential_expiring`;
  - walled user → `route_feature_unsupported`;
  - the environment carries `NEURALWATT_API_KEY` and no other provider key.
- **Move-on.** The real captured 402 body classifies as `credit` and moves to the OpenRouter twin,
  with case money unchanged by the tail.
- **Classify.** A Neuralwatt 402 wait maps to `router:neuralwatt_limit`, not `router:credit`.
- **Config.** `opencode_config` contains the exact Neuralwatt provider block above.
- Full suite.

## Murphy rows

- New row `new-neuralwatt-1`: "single paid provider: OpenRouter balance exhaustion parks every case
  on the MiMo/GLM fallback" (seen 2026-11-19; seven cases parked).
  - It is closed by the real-router-state routes test plus the move-on test on the captured 402.
  - The move-on fixture exists only after rollout step 5, so the row closes in that follow-up commit.
