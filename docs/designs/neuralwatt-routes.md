# Neuralwatt routes for MiMo and GLM

Founder ruling, 2026-11-19 ("Yes, build it"): build Neuralwatt routing for new launches only, for
MiMo-V2.6-Pro and GLM-5.3 Flash. Using the same models from a different provider is fine for new
cases. Test on the $5 trial credit before any subscription. Running cases stay on OpenRouter.

## Problem

- The paid fallback for MiMo and GLM is OpenRouter. It runs whenever the founder's two OpenCode Go
  accounts hit their weekly quota.
- Over the router's history:
  - MiMo cost $103: 1.23B input tokens (1.05B of them cached) and 16M output.
  - GLM-5.3 Flash cost $21.
- Neuralwatt serves the same two models (`mimo-v2.6-pro`, `glm-5.3-flash`, from
  `https://api.neuralwatt.com/v1/models`). Its listed token prices are identical to our OpenRouter
  pins:
  - MiMo: 0.435 / 0.0036 / 0.87;
  - GLM: 0.15 / 0.03 / 0.50.
- It bills by measured energy and guarantees a request never costs more than its listed token
  price. In the last 7 days, paid prices ran about 20% (MiMo) and 27% (GLM) below list.
- Until 2027-01-01 there is a free daily energy grant for the Flash models.
- On 2026-11-19 the OpenRouter balance ran down to $4.38. The paid pool blocked, and seven cases
  parked behind it.

## Change

Add one more lane per model, in each chain between the Go plan route and the OpenRouter route.

The lane is an OpenCode provider lane with no gate, the same shape as the Go plan lanes
(`model_call_gate.enforce`, the `GO_ROUTES` branch). The difference is that it books real money at
its OpenRouter twin's list price, where Go books $0.

1. **`token_prices.py`**
   - `NW_TWINS`:
     - `neuralwatt/mimo-v2.6-pro` → `openrouter/xiaomi/mimo-v2.6-pro`;
     - `neuralwatt/glm-5.3-flash` → `openrouter/z-ai/glm-5.3-flash`.
   - `NW_ROUTES`.
   - `nw_maximum(route)`: the twin's `openrouter_gate_maximum`, with
     `price_source='neuralwatt:<model>:twin=<twin source>'`.
   - `runtime_prices` resolves NW twins the same way as Go twins.
   - The list price bounds every Neuralwatt charge, because Neuralwatt never bills above its
     listed token price, and its list equals the pin.
2. **`model_router.py`**
   - Add `neuralwatt-key` to `ACCOUNTS`.
   - CHAINS for mimo and glm become `opencode-go/…`, then `neuralwatt/…`, then `openrouter/…` (glm
     keeps its trailing free route).
   - In `routes()`, a `neuralwatt/` route gets billing `paid`, account label `('neuralwatt-key',)`
     and pool `neuralwatt-key`.
   - `route_maximum` returns `nw_maximum`.
   - `ungated_lanes` includes NW routes, so walled calibrators never take one; they keep the gated
     OpenRouter lane.
   - A credit or quota block on `neuralwatt-key` expires like any non-`PAID_POOL` block
     (`lasting()` is unchanged).
3. **Which workers see the lane.**
   - A worker offers `neuralwatt-key` in its lease `accounts` only when
     `/dev/shm/secrets/neuralwatt-key` exists.
   - Running cases run older releases whose `ACCOUNTS` lack the name, so the router never leases them
     the lane. That is the "new launches only" property, and it holds with no per-case flag.
   - A new release on a box without the key also never sees the lane, so there is no
     `credential_expiring` failure.
4. **`model_runtime.py`**
   - `opencode_config` adds the provider
     `neuralwatt: {npm: "@ai-sdk/openai-compatible", options: {baseURL: "https://api.neuralwatt.com/v1", apiKey: "{env:NEURALWATT_API_KEY}"}, models: {<id>: {cost: twin price, limit: …}}}`.
   - The key for `neuralwatt-key` is `NEURALWATT_API_KEY`, in the run environment and in
     `diagnosis_environment`.
   - In-attempt move-on: `go_quota_moves_on` also covers NW routes, for reasons `quota` and `credit`.
     A Neuralwatt 402 or quota moves the call to the OpenRouter twin instead of ending the attempt.
5. **`model_call_gate.py`**
   - `enforce` has an NW branch: the Go branch's checks, with the key `NEURALWATT_API_KEY`.
   - `free_environment` passes `NEURALWATT_API_KEY` (and only that key) for an NW lease.
6. **`budget.py`**
   - An NW step books `max(OpenCode's cost, go_step_cost(twin, tokens))` as real case money. It is
     not zeroed like Go.
   - An NW call's unseen tail books its remaining bound, like a gated call. It is not zeroed.
   - This is a deliberate over-count: the real bill is at or below list, and the ledger reads high,
     never low.
7. **`durable/classify.py`** maps `neuralwatt/` failures the way it maps `opencode-go/`
   (`router:…_limit`), so a stop reads correctly on the board.
8. **Secrets delivery**
   - `neuralwatt-key` travels the same way `opencode-go-key` does to durable boxes, with
     `bin/setup-secrets neuralwatt`.
   - The founder installs the key on the VM; the agent never handles it.

## What it deletes

Nothing. Go and NW share one twin mechanism, so `GO_TWINS` and `NW_TWINS` feed one helper rather
than two copies.

## Not in scope

- Reconciling against Neuralwatt's usage API. Booking at list is an upper bound. Add reconciliation
  if the over-count ever blocks a case.
- DeepSeek V4.1 Flash. Neuralwatt's cached-input price is twice OpenRouter's, so it saves nothing
  until the free Flash grant is measured.
- Subscriptions (founder: after the trial).
- Moving running cases.

## Tests

- Routes: the mimo and glm chains are Go, then NW, then OpenRouter. An NW lane appears only when
  `neuralwatt-key` is in `accounts`. An old-`ACCOUNTS` caller gets no NW lane. A walled role
  (`ungated_lanes`) excludes it. The family check passes.
- Maximum: `nw_maximum` equals the twin's maximum, except for `price_source`, and `valid_maximum`
  accepts a funded NW lease.
- Budget, using a real saved OpenCode step part (the Go fixture shape): the NW step books the twin's
  list cost as case money; the same step on Go books $0; the unseen tail books the remaining bound.
- Gate: `enforce` NW branch. A missing key gives `credential_expiring`. A walled user gives
  `route_feature_unsupported`. The environment carries `NEURALWATT_API_KEY` and no other provider
  key.
- Move-on: an NW `credit` or `quota` failure moves to the OpenRouter twin.
- Full suite.

## Murphy rows

- New row `new-neuralwatt-1`: "single paid provider: OpenRouter balance exhaustion parks every case
  on MiMo/GLM fallback" (seen 2026-11-19, seven cases parked). This change gives that fallback a
  second paid provider. The row is closed by the routes and move-on tests above.

## Rollout

- Merge, then install as new plumbing for new launches and relaunches only.
- The router restart needed for the new CHAINS and ACCOUNTS waits until the router is drained (no
  model calls in flight).
- Before any case uses the lane, run a smoke call on the trial key with a non-case prompt. It checks
  the model ids, the speed, and that OpenCode loads `@ai-sdk/openai-compatible` offline on a worker
  box.
