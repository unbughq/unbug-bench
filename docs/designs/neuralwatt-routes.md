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
8. **`budget.classify_provider_failure`**: Neuralwatt's out-of-credit and rate-limit bodies, as
   captured on the trial (Rollout step 1), map to `credit` and `rate`. Until then the generic check
   holds: any 402 or "insufficient credits" is `credit`, any 429 or "rate limit" is `rate`. Item 8 is
   the follow-up commit that lands with the captured fixtures; the lane stays off until it does
   (Rollout step 6).
9. **`bin/setup-secrets neuralwatt`**
   - It prompts for the key without echo and checks that the key starts with `sk-`.
   - It writes `$tmp/neuralwatt-key`, the same as the `opencode-2` branch, and re-encrypts the bundle.

## Rollout runbook

Strictly in this order. No release reaches any batch until step 3 is done.

1. **Key on the VM, before merge.**
   - The founder puts the trial key in `/home/user/.neuralwatt-trial-key` (mode 600). It is not in
     the worker bundle yet.
   - A one-off direct API call from the VM reads that file and never prints it. It runs a
     non-case prompt on both model ids and records:
     - non-zero usage;
     - tokens per second;
     - the real out-of-credit and rate-limit bodies, provoked with a request too large for a tiny
       remaining balance if possible, or else taken from Neuralwatt's error docs and marked as such.
   - Also one OpenCode run on the VM with the factory's `opencode_config` for each model, recording
     the `step_finish` part (non-zero `tokens`) and the outgoing request's `max_tokens` (≤ 32768,
     which `nw_request_worst` relies on).
   - The bodies, step part and request are committed as fixtures in a follow-up commit with item 8,
     the move-on test through `ModelRuntime.call`, and the budget tests swapped to them. That commit
     goes through its own diff review. This branch may merge before it, because the lane ships
     switched off (step 3).
2. **Merge and install**, after the diff review.
   - Run `unbug install` for the release. Nothing uses it yet: a batch's plumbing is fixed in its
     start spec (`contract.py:357`), and only `plumbing_release <batch>` or a new start spec moves
     a case.
3. **Router: new code, config, then a drained restart.**
   - The router runs from its own checkout (`control/unbug-model-router.service`:
     `/home/user/unbug-bench/factory/model_router.py`), which neither `unbug install` nor
     `source-current` moves. Fast-forward that checkout to the release commit first, then check
     `python3 -c "import sys; sys.path.insert(0,'factory'); import model_router; assert 'neuralwatt-key' in model_router.ACCOUNTS"`
     in it. Old router code refuses `neuralwatt-key` in its config (`Store.__init__`: `unapproved
     account`), so it would not start, and every acquire on every batch would fail
     `router_unavailable`.
   - Record `git -C /home/user/unbug-bench rev-parse HEAD` first (the rollback target), and check
     whether `unbug-durable.service` is active: it runs `factory/durable/cli.py` from the same checkout.
   - Add `neuralwatt-key` to the router config `accounts`, set `capacities['neuralwatt-key'] = 8`,
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
6. **Lane on.** Only after the step 1 follow-up commit is reviewed, installed and live on the
   controller: steps 2, 4 and 5 again for the follow-up release (and step 3 if it touches
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
        offering it. In an emergency, end those steps instead: SIGTERM to `worker_step` books
        `infra:step_crashed`, an infra retry, and its retry gets the new secrets.
     3. Only then drain the router, put `neuralwatt/` back in `disabled_routes`, and restart it.
        Done in the other order, a keyed step counts a lane it can never lease, and a malformed
        answer loops on outage waits (the cae763 shape).
     4. A case whose `ordinary-retries/*/state.json` lists an NW route in `spent_routes` fails
        `infra:ordinary_retry_state_invalid` once the key is gone (`ordinary_retry.py:128-130`).
        Delete that call's state file. This resets that one call's retry count, at most one extra
        round of retries.
     5. Remove `neuralwatt-key` from `worker_credentials.accounts` before any controller downgrade,
        or the controller refuses to start (`invalid_worker_accounts`).
   - A case that ran an NW call is never moved below this release: its ledger's reservation rows
     carry `open_steps`, which older `usage_coverage` reads as unknown coverage.

**Known costs, recorded.**
- A case with less money left than one whole request ($0.57 MiMo, $0.63 GLM) gets an NW
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
