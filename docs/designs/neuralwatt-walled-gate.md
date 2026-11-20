# Neuralwatt through the wall's gate (2026-11-20)

Option B of `neuralwatt-routes.md` §"Walled roles (easy_calibrator) and Neuralwatt". Founder, 2026-11-20
~05:45 UTC, "build the neuralwatt door": let walled roles (the G10 easy calibrator and any `WALLED_ROLES`) use
Neuralwatt through the wall's gate. He accepted the science note: the easy calibrator reads GLM at fp8 on
Neuralwatt instead of OpenRouter's fp4/fp8 pinned endpoints. The ruling names walled roles, not one model, so
every Neuralwatt route (GLM, MiMo, DeepSeek) is opened to them; all three have real stream bytes below.

## Problem

- A walled role (`model_router.WALLED_ROLES`: the strong and easy calibrators) runs as `pilot`. The wall
  (`run.pilot_wall`) rejects local and private destinations, except one iptables rule per lease to the gate's
  port (`model_call_gate._wall_access`). What protects a provider key is that it never enters the walled
  process: only the gate holds it.
- Neuralwatt has no gate: OpenCode calls `api.neuralwatt.com` itself with the key in its environment. So
  `ungated_lanes` and `bounded_route` keep every Neuralwatt lane away from walled roles, and a walled GLM or
  DeepSeek call has one lane left: its OpenRouter twin.
- OpenRouter credit is $2.50 and the founder will not top it up. Cases 1108c and cb5e26 sit at G10
  `waiting_for_credit` on their GLM easy calibrators.

## Change

1. **The gate serves Neuralwatt for a walled caller** (`model_call_gate`).
   - `enforce`: a Neuralwatt lease with `user` set takes the gate path. Without `user` it runs ungated, as today.
   - The gate holds the real `NEURALWATT_API_KEY`. The walled process gets only a random per-gate token
     (`Gate.token`), in an inline OpenCode config (`openrouter_environment`, extended): provider `neuralwatt`,
     `@ai-sdk/openai-compatible` (bundled in OpenCode 1.19), `baseURL http://127.0.0.1:<port>/v1`, `includeUsage`,
     the route's one model at its list price (`runtime_prices`) and Neuralwatt's context (1048560, now
     `token_prices.NW_CONTEXT`, shared with `opencode_config`).
   - Fixed upstream: `api.neuralwatt.com`, path `/v1/chat/completions` only. No override. The lease must be on
     `neuralwatt-key`.
   - budget.py's Neuralwatt stop (`usage_reservation_exceeded`: one more whole request no longer fits) is mapped to
     `model_call_cap` on the gate path too, as on the ungated path (review 1, B1).
2. **Body allowlist** (`openrouter_body`, one `nw` switch). The same checks as OpenRouter: text only, local
   function tools only, the leased model, `max_tokens` clamped to `OPENROUTER_OUTPUT`, `stream_options.include_usage`
   forced on a stream. For Neuralwatt:
   - refused: OpenRouter's `usage`, `reasoning`, `include_reasoning` fields, and message-level `reasoning` and
     `reasoning_details`;
   - not added: `usage` and `provider`; `bound_reasoning` (diagnosis only) adds nothing;
   - allowed: an assistant message's `reasoning_content` string. Real OpenCode 1.19, run with this exact walled
     config against a loopback stub, sends it with `content: ""` and `tool_calls` on its second turn (fixture below).
3. **Hold and refund.** The same `Allowance`: each request holds its worst case (`worst_request`) before it is
   forwarded; only a validated terminal usage frame refunds it. Neuralwatt routes are priced by a new
   `token_prices.gate_profile(route)`: the OpenRouter pin, or `_nw_profile` for a Neuralwatt route (the twin's
   context and output, Neuralwatt's list). `openrouter_gate_cost`, `worst_request`, `request_hold`,
   `empty_usage`, `Allowance.amount` and `OpenRouterUsage` read that profile. GLM's hold is $0.1736704 a request.
   - The usage parser is `OpenRouterUsage`, unchanged in logic. Real Neuralwatt streams are OpenAI-style: one
     terminal choice, then one usage frame with `choices: []`, then `: energy` and `: cost` SSE comments, then
     `data: [DONE]`. Comments are not `data:` lines and are ignored. Neuralwatt's usage has no `cost`, so a cached
     prompt token is held at the full input price (never below the bill).
   - ponytail: that ceiling counts a cache-heavy request above its bill (a 100k prompt, 97k cached, 500 out:
     $0.0153 counted, $0.0036 billed, 4.2×). cb5e26's real G10 windows were $1.26 and its call 1d921598 billed
     $0.05, so about $0.22 counted plus one $0.17 hold in flight still fits; each 429 (below) takes $0.17 more, so
     about five 429s end the call `model_call_cap`. Upgrade if a calibrator stops on that: take the stream's
     `: cost {"request_cost_usd": …}` comment as the charge floor, as cached-window does with OpenRouter's
     `usage.cost`, after capturing one real cached request (no fixture request has `cached_tokens > 0`).
   - Side effect on unwalled calls: `request_hold` now answers for every Neuralwatt route, so `_call`'s funding
     floor and the unwalled receipt's `max_request_output_tokens` see a Neuralwatt hold. Benign: budget.py's
     `nw_request_worst` stop is stricter, and no reader uses that receipt field.
   - Decision (review 1, N4): a Neuralwatt 4xx keeps its hold, as OpenRouter's does. Only Claude's JSON error is
     refunded (`Usage.rejected`). Case money is still bounded by `open_steps` (a refused request leaves none), so
     a 429 costs only window room ($0.17 each).
4. **No router `paid_reserve` for Neuralwatt.** The router's paid path keys on `GATED_OPENROUTER`, which never
   holds a Neuralwatt route. In the gate, `paid` (router reservation, `openrouter.ai`) stays OpenRouter only; a
   new `openai` flag (OpenAI-style path, body, parser, no Anthropic headers, no Claude `rejected()`) covers both;
   `nw` picks the host, the path and the key. Spend is bounded by the gate's hold, the lease maximum and case money,
   plus budget.py's per-step Neuralwatt stop.
5. **Who may take the lane** (`model_router.ungated_lanes`, `model_runtime.bounded_route`, `ModelRuntime._call`).
   - `ungated_lanes` returns free and Go lanes only. Neuralwatt has a gate now. Go and free stay excluded.
   - `bounded_route`: a walled role is bounded on a Neuralwatt lane.
   - A diagnosis is also walled (`user='pilot'`) but is not a `WALLED_ROLES` role and was not in the founder's
     decision. `_call` still excludes Neuralwatt lanes for a walled caller outside `WALLED_ROLES`: its
     OpenRouter-only handling (`bound_reasoning`, the webfetch deny edit) has no Neuralwatt form.
   - Callers of `ungated_lanes` that mean "a WALLED_ROLES call" (`ordinary_retry`, run.py's preflight dedupe)
     need no edit: they now count the Neuralwatt lane as leasable, which it is.
6. **Chain order.** Unchanged `CHAINS`. For a walled GLM call, Go and free are excluded, so the order is
   Neuralwatt, then the OpenRouter twin. Neuralwatt quota or credit moves on (`go_quota_moves_on`, unchanged);
   the gate passes Neuralwatt's 402/429 through to OpenCode, so budget.py classifies it as it does today.
   A calibrator preflight (unwalled, `easy_calibrator` role) leases the same Neuralwatt lane and runs it ungated:
   same provider and model, not the gate (review 1, N9: gating every Neuralwatt call would make it one path;
   not done here).

## Gate identity (no lost progress)

The change touches `model_call_gate.py`, `model_router.py` (`ungated_lanes` only), `model_runtime.py`
(`bounded_route`, `_call`, `opencode_config` constant), `token_prices.py`. None is a gate dependency file, and
`model_router.family` / `model_runtime.model_effort` and their transitive names are untouched. run.py,
calibration.py, gate_state.py, bin/**, harbor/** and top-level *.md are not edited. Proof:
`myident.py` on `git archive` trees of base and head must print identical JSON, for origin/main and for the
hotfix `hotfix/cb5e26-nw-gate` (cb5e26's source d038ab59 + the Neuralwatt lane commits it lacks + these commits).
`myident.py` (a scratch script, 17 lines) prints, with `factory/` on the path: `gate_state.model_science()`,
`sealed_audit.delivery_contract()`, `runner_inputs` and `dependency_files(..., include_pool=True)` for every gate
in `STAGE_DEPENDENCIES` (plus `factory/case_contract.py`), `source_inputs` of the calibration and stress judges,
the sha256 of every `factory/prompts/*` file, and `release_pins()`.

**Model verdict code.** `durable.checkpoints.verdict_code(model=True)` digests ten files: `BENCH_VERDICT_CODE`
plus `model_call_gate.py`, `model_router.py`, `model_runtime.py` and `ordinary_retry.py`. It scopes the
engine-checkpoint folder of the model-stage gates that are not in the gate cache (G10, G11, G17) and of every
model call receipt. Editing these files changes it, so a case moved onto this release would redo its in-flight
G10 calibrator calls. This change changes no saved verdict or model effect (it only adds a lane a walled call may
lease next), so each branch repins `verdict_code_pins.model` (`factory/invalid-runs-compat.json`): `from` = the
digest the predecessor release answers, `to` = this tree's raw digest. On main, `from` = 77f25170's `802bfc8f…`;
on the cb5e26 hotfix, `from` = d038ab59's answer, and the pin also vouches for the backported Neuralwatt lane
commits. That reverses neuralwatt-first's choice to leave them unpinned (`neuralwatt-first-design-3.md`), so the
hotfix's review argues each backported SHA by name. The pin must be recomputed after any merge that touches any of
the ten files. Not covered: 1108c's source 3dfdde3c answers `60be464f…`, not main's `802bfc8f…`, so 1108c moved
onto main loses its in-flight G10 receipts whatever this change does (REUSABLE passes G4-G9, G13-G16 live in the
gate cache and are kept).

## What it deletes

Nothing. The "Neuralwatt is ungated" special case in `ungated_lanes`/`bounded_route` is replaced, not guarded.

## Cost and time

- Money spent building it: about $0.00004 of Neuralwatt trial credit (seven tiny real calls). Nothing else.
- Running cost, per million tokens (input / cache read / output) and hold per request:

  | Route | Neuralwatt | OpenRouter twin |
  |---|---|---|
  | GLM 5.3 Flash | 0.15 / 0.03 / 0.50, $0.1737 | same |
  | MiMo v2.6 Pro | 0.435 / 0.0036 / 0.87, $0.4846 | same |
  | DeepSeek v4.1 Flash | 0.15 / 0.015 / 0.60, $0.1769 | 0.14 / 0.0042 / 0.42, $0.1606 |

- Expected walled spend: the GLM easy calibrator cost about $0.47 a day on OpenRouter (parent design, 7 days);
  the same on Neuralwatt's list. A DeepSeek calibrator bills up to about 1.4× its twin on output.
- Precision: GLM is fp8 on Neuralwatt (founder accepted). MiMo's and DeepSeek's serving precision on Neuralwatt
  is not published in anything we hold; the founder's ruling names roles, so it covers them as served.
- Half a day of work; deploy is a worker-only plumbing release.

## Tests

- **Real stream bytes** (`tests/factory/fixtures/neuralwatt-gate-streams-20261120.json`): seven real calls to
  `api.neuralwatt.com` on 11-20 (trial key, generic prompts): GLM reasoning text, tool call and non-streaming;
  MiMo and DeepSeek text and tool call. Raw response bytes as `http.client` `read1()` returned them, with request
  bodies; no key, no case content.
  - `OpenRouterUsage` on every real answer, fed whole and in 1-byte and 7-byte chunks, returns the real usage.
  - Altered real bytes are refused: no `[DONE]`, no usage frame, two usage frames, two terminal choices, another
    model, an error frame, prompt above the context, a wrong total, a cut tail, another generation id, a GLM
    answer on a MiMo lease.
- **Real OpenCode requests** (`tests/factory/fixtures/neuralwatt-gate-opencode-requests-20261120.json`): OpenCode
  1.19.0 on an idle worker box, run with `openrouter_environment`'s walled Neuralwatt config against a loopback
  stub that logged each body and replayed the real GLM bytes; no key, no network beyond loopback. Both of its
  requests (the second carries the assistant's `reasoning_content` and `tool_calls`, and the tool's answer) pass
  the real gate and are forwarded as sent.
- **The gate end to end** on the real bytes, with an upstream stub on loopback: one iptables rule inserted and
  deleted, host `api.neuralwatt.com`, path `/v1/chat/completions`, upstream bearer is the key, the walled env holds
  no key and the gate token is not the key, the forwarded body has no `provider`/`usage`/`reasoning` and a clamped
  `max_tokens`, one validated request settled at its real usage price, nothing held, no router RPC at all
  (`model_router._rpc` raises if called). Refusals: OpenRouter's path, the real key as the gate token, OpenRouter
  fields, `reasoning_details`, non-text reasoning, image parts, server tools, another model, unknown fields.
  Neuralwatt's real 429 body keeps its hold. A non-`neuralwatt-key` lease or a missing key: `credential_expiring`;
  budget.py's stop inside the walled gate: `model_call_cap`. Unwalled Neuralwatt still runs without a gate; Go
  with `user` is still refused.
- **Routes on real 11-19 router health** (`test_neuralwatt_routes.py`): the flip of
  `test_walled_roles_never_take_the_neuralwatt_lane`. A walled GLM / DeepSeek calibrator acquire gets the
  Neuralwatt lane first; after a Neuralwatt `credit` observation it waits on the OpenRouter twin. `ungated_lanes`
  is exactly the chain's Go and free lanes, so no walled acquire is leased one (an unwalled one still is).
- **Runtime**: `bounded_route` flipped (`test_neuralwatt_runtime.py`); `_call`'s exclusions for the easy
  calibrator, its preflight and a diagnosis (`test_free_routes.py`): the diagnosis still excludes Neuralwatt.
- **Ordinary retry** (`test_stream_d_retries.py`, the cae763 tests): a walled GLM calibrator's empty answers
  spend Neuralwatt, then the twin, then count as exhausted and reset on the next engine attempt; with the key
  withdrawn, the spent Neuralwatt route is still accepted and only the twin is called.
- Every changed line above was mutated once; a test failed each time.
- Identity proofs (above) and the full factory suite.

## Murphy rows

The register is the untracked local `docs/murphy-register.md`; the parent appends the row there.

- **`new-neuralwatt-walled-1`:** "a walled role has one paid lane (OpenRouter); with OpenRouter credit gone and
  no top-up, every walled GLM/DeepSeek call parks `waiting_for_credit` (1108c and cb5e26 at G10, 11-20)".
  Closed by `tests/factory/test_neuralwatt_walled_gate.py` and
  `test_neuralwatt_routes.py::test_walled_roles_take_the_neuralwatt_lane_first_then_the_twin_and_never_go_or_free`.
  Live check after deploy: a G10 easy calibrator books a Neuralwatt step.

## Deploy (operator; this change does none of it)

- Worker-only. The router needs no restart: it already leases the Neuralwatt GLM lane to a chainless 3dfdde3c
  caller, and it never reserves for Neuralwatt.
- cb5e26: `plumbing_release` of `hotfix/cb5e26-nw-gate`; 1108c: main (coordinator's call, see the verdict-code
  note). The gate identity is unchanged, so no gate-cache pass reruns.
- `neuralwatt-key` must reach every machine that runs a walled try: the case's worker credentials bundle and
  its G10 helper machines (`helper_link`, review 1, N8). Helpers are workers of the same pool and get the same
  `credential_bundle`, so the key reaches them once the bundle's accounts include it. But a helper leases with
  the case worker's `router_accounts` (`helper_link.py:213`), not its own `offered_accounts()`, so a keyless
  helper is not kept off the lane: it fails `credential_expiring` account-wide and blocks the Neuralwatt pool.
  The router already has the key.
- `hotfix/cb5e26-nw-gate` is a per-case release branch, the existing practice (`hotfix/cb5e26-diag`), which
  ENGINEERING §4 ("Do not add per-case bundles, rescue branches") leans against; it is the coordinator's call
  and carries only code that is on main or in this change.
- A malformed Neuralwatt answer in an ordinary retry (the calibrator dedup) moves the next try to the twin,
  which parks on OpenRouter credit while it has none (diff review 1, N2).
- A case parked in `wait_for_credit` is not woken by a plumbing release: check its engine status; it may still
  need the operator's credit lift (hotfix review, N1).
- Rollback: once a case has run a Neuralwatt step, never move it back to a pre-Neuralwatt source (d038ab59 or
  older rejects `open_steps` ledger rows, Neuralwatt `spent_routes` and a `neuralwatt-key` account list);
  withdraw the key instead (hotfix review, N2). The live router must be neuralwatt-first or later (it accepts
  `chain`).
- First check: a G10 easy calibrator receipt (worker and helper try) shows `neuralwatt/glm-5.3-flash`,
  `cap_used.validated_requests > 0` and a booked step. Watch `capacity` waits on `neuralwatt-key`: walled G10
  tries now share its 3 seats (review 1, N10).
