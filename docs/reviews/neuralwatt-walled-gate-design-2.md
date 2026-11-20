# Design review 2: neuralwatt-walled-gate (goldfish)

## Scope

- **Design reviewed:** `docs/designs/neuralwatt-walled-gate.md` (the whole file, at HEAD 3bc37499).
  - Checked against round 1 (`docs/reviews/neuralwatt-walled-gate-design-1.md`, including the elephant's record of fixes).
  - Checked against option B in the parent spec, `docs/designs/neuralwatt-routes.md:494-551`.
  - Checked against the founder's 2026-11-20 words as given in the task.
- **Lenses:** zoom_out, design_critic, implementation_readiness. Mode: REVIEW. Standards: Heilmeier and Implementation Readiness. Rules: `docs/ENGINEERING.md`.
- **Code read:**
  - the full diff `77f25170..HEAD`;
  - `model_call_gate.py`: `openrouter_body`, `Handler.do_POST`, `Gate`, `openrouter_environment`, `enforce`;
  - `model_runtime.py`: `call_window`, `offered_accounts`, `bounded_route`, `_call`, `_invoke`, `opencode_config`;
  - `model_router.ungated_lanes` and every caller of it (`run.py:477`, `ordinary_retry.py:138`);
  - every caller of `request_hold`, `empty_usage` and `gate_profile` (`durable/runtime.py:185`, `model_runtime.py:61,574,603`);
  - `budget.py`: `_gate_bound`, `_settle_leaf`, `check_limits`;
  - `durable/checkpoints.verdict_code`, `gate_state.release_pins`;
  - helper credential delivery (`durable/runtime.py:220-256`, `durable/workers.py:581-596`, `durable/helper_link.py:200-245`);
  - `docs/designs/cached-window.md`.
- **What I ran (read-only):**
  - The four touched test files all pass:
    - `test_neuralwatt_walled_gate`: 7 tests;
    - `test_neuralwatt_routes`: 10;
    - `test_neuralwatt_runtime`: 8;
    - `test_free_routes`: 9.
  - On `git archive` trees of 77f25170 and HEAD (in the scratchpad):
    - Base `verdict_code(model)` gives `802bfc8f…`, and that is its raw digest (its stored pin is stale).
    - HEAD's raw digest is `e1b82d17…`, and with its pin HEAD answers `802bfc8f…`. Both match the design's lines 90-91 and `invalid-runs-compat.json`.
    - The bench digest is unchanged (`d4a7127a…`).
    - The identity script (`myident.py`) printed byte-identical JSON for base and head (166,016 bytes each). That JSON covers model_science, delivery_contract, runner and deps for every gate, judge sources, prompts and release_pins.
  - In memory:
    - Holds and prices for all three Neuralwatt routes and their twins.
    - The real `: cost` SSE comments and `cached_tokens` fields in the streams fixture.
    - What the gate counts for a 97%-cached GLM request.
- **Not run:** the full factory suite.

## Round-1 blocking findings

- **B1: closed.**
  - `model_call_gate.py:936` maps `usage_reservation_exceeded` to `model_call_cap` for a Neuralwatt lease behind the wall, inside the same `except` that wraps `_wall_access`. This matches the unwalled branch (`:883-885`).
  - Test: `test_neuralwatt_walled_gate.py:268-273` raises the stop inside a walled `enforce`, and also asserts the gate snapshot is closed.
- **B2: closed.**
  - `tests/factory/fixtures/neuralwatt-gate-opencode-requests-20261120.json` records real OpenCode 1.19.0 output against a loopback stub. Its second body carries an assistant message with exactly `{content: "", reasoning_content, role, tool_calls}`, followed by a tool message.
  - Both bodies pass the real `openrouter_body` and are forwarded unchanged (`test_neuralwatt_walled_gate.py:202-224`).
  - The second half of the original finding (the preflight runs unwalled and therefore ungated) is now stated as a decision (design lines 72-74). It is acceptable because the body filter is pinned on real OpenCode output.
- **B3: closed.** I judged the scope myself against the founder's words: "let walled roles (the G10 easy calibrator and any WALLED_ROLES) use Neuralwatt through the wall's gate".
  - The ruling names roles and a provider. It does not name a model: "any WALLED_ROLES" is deliberately broad, and "use Neuralwatt" covers every route Neuralwatt serves.
  - The fp8 note is the science caveat the founder accepted for the case at hand. It is not a filter.
  - The evidence gap is also closed. The fixture now holds real MiMo and DeepSeek text and tool streams. The parser test (`:64-78`) and the end-to-end gate test (`:164`) run on them, including the model-name check that round 1 flagged as unproven.
  - Remaining hygiene is in N2.

## Findings

### N1. NIT: the cached-token ceiling is justified against the wrong window, and Neuralwatt's own charge is already in the stream

- **Evidence:**
  - Design lines 49-52 justify counting cached tokens at the full input price against "its $12.50 window".
  - The only real walled windows on record for the target case are smaller. cb5e26's G10 easy calibrator on GLM ran with **$1.26** windows at 97% cached (`docs/designs/cached-window.md:28-31`, leases 1d921598 and e11c7bb2). Those windows were cut by `model_call_cap`.
  - On main, the cached-window fix discounts cached tokens only when OpenRouter's `usage.cost` is present (`token_prices.openrouter_gate_cost`). A Neuralwatt usage frame has no `cost`, so a walled Neuralwatt call goes back to full-rate counting.
  - Measured in memory: a GLM request with 100k prompt tokens (97k cached) and 500 output tokens is counted at $0.01525 against a list bill of $0.00361. That is 4.2×.
  - Every real Neuralwatt stream ends with `: cost {"request_cost_usd": …, "cache_savings_usd": …}`.
  - No fixture request has `cached_tokens > 0`.
- **Why it is not blocking:** 1d921598 billed $0.05.
  - At 4-5× that is about $0.22 counted, plus $0.17 for each request in flight, against $1.26. That still fits.
  - The cuts recorded in cached-window.md were driven by holds on streams that ended without usage. Every real Neuralwatt stream carries its usage frame.
- **Ask:**
  - State the real window ($1.26 on cb5e26's G10) and the headroom computed from real data.
  - Note that each Neuralwatt 429 (decision N4) takes $0.17 of that headroom, so about five 429s plus one in-flight hold end the call.
  - Name the upgrade concretely: use the `: cost` comment's `request_cost_usd` as the charge floor, mirroring cached-window. Capture one cached request (two identical long prompts, well under $0.001) before relying on it.

### N2. NIT: the cost section covers GLM only

- **Evidence:** design line 105 says a walled call "bills Neuralwatt's list, the same as its OpenRouter twin's pin". That is true for GLM and MiMo.
- **DeepSeek on Neuralwatt is on its own, dearer list** (`NW_OWN_PRICES`):

  | | Neuralwatt | OpenRouter twin |
  |---|---|---|
  | Output, per million | $0.60 | $0.42 |
  | Cache read, per million | $0.015 | $0.0042 |
  | Hold per request | $0.1769 | $0.1606 |

- **No expected spend.** There is no estimate of walled spend per day against the Neuralwatt balance. The parent spec gives about $0.47/day for the GLM easy calibrator (`neuralwatt-routes.md:542-544`).
- **Ask:**
  - Add DeepSeek's prices and the expected daily spend.
  - Record DeepSeek's and MiMo's serving precision on Neuralwatt, if known, beside the GLM fp8 note. The founder's acceptance is then on record for each model the ruling opens.

### N3. NIT: the hotfix pin reverses an earlier decision, and it needs its own argument

- **Evidence:**
  - Design lines 92-93 say the `hotfix/cb5e26-nw-gate` pin "also vouches for the backported Neuralwatt lane commits".
  - The neuralwatt-first review recorded the opposite: those commits' `model_runtime.py`/`model_router.py` edits "change model effects", and they were left unpinned (`docs/reviews/neuralwatt-first-design-3.md:56-58`, `neuralwatt-routes.md:696-699`).
  - The pin argument for this branch's own change is sound: it adds a lane, and saved receipts are untouched. I verified the main-branch numbers.
  - The backported commits' argument is deferred to a hotfix review that does not exist yet. The branch does not exist either.
- **Ask:** have the hotfix's diff review argue each backported SHA against that earlier note, and run the identity script on the hotfix tree (design line 83 already requires the second part).
- **Also:** ENGINEERING §4 says "Do not add per-case bundles, rescue branches". Per-case hotfix branches are existing practice here (`hotfix/cb5e26-diag` and others), and the deploy section is the operator's call. Even so, the design should acknowledge the rule it is leaning on.

### N4. NIT: the identity proof tool is not in the repo

- **Evidence:** design line 82 cites `myident.py`. It lives only in a session scratchpad, so a fresh reader cannot reproduce the proof.
- **Ask:** check the script in under `tools/`, or inline what it hashes (it is 17 lines). I reran it, and the JSON is identical.

### N5. NIT: the deploy note on helper keys can be sharper

- **Evidence:**
  - Design lines 157-159 say `neuralwatt-key` "must reach" the G10 helper machines.
  - Helpers are BoatPool workers in the same pool, so they get the same `credential_bundle` as case workers (`durable/runtime.py:220-231`, `helper_link.py:285`). The key reaches helpers automatically once the worker bundle's `accounts` include it.
  - However, a helper uses the case worker's `router_accounts` (`helper_link.py:213`) rather than its own `offered_accounts()` (`model_runtime.py:70-75`). So the guard that keeps a keyless worker away from Neuralwatt lanes does not apply on a helper.
- **Ask:**
  - Say this in the deploy note.
  - Optionally, intersect the helper's accounts with its own `offered_accounts()`. That turns the account-wide `credential_expiring` risk the design describes into a no-op.

### N6. NIT: one side effect on unwalled calls is not described

- **Evidence:** `request_hold` now returns a hold for every Neuralwatt route (`model_call_gate.py:183`), including unwalled ones. This changes:
  - the funding floor in `_call` (`model_runtime.py:574-578`);
  - `empty_usage(...)['max_request_output_tokens']` in unwalled Neuralwatt receipts. The field has no reader.
- **Impact:** benign in practice. Go lanes usually keep `min(holds)` at 0, and budget.py's `nw_request_worst` stop is stricter anyway.
- **Ask:** one line in "Change" or "What it deletes" stating this.

## Holds up on its own

- **Problem:** correct and specific. The wall's real property (the key never enters the walled process) is stated, and the stuck cases are named.
- **Change:** every branch the code takes is described, and the code matches the description:
  - `openai`/`paid`/`nw` flags;
  - body allowlist (`:404-416, :447`);
  - random gate token (`:747`);
  - Neuralwatt account check (`:914`);
  - no router RPC (the test makes `_rpc` raise);
  - the diagnosis exclusion (`model_runtime.py:541`);
  - `ungated_lanes` (`model_router.py:209`).
- **Other `ungated_lanes` callers:** `ordinary_retry` is walled only for `WALLED_ROLES` (`run.py:410`), so its approved lanes agree with `_call`. The diagnosis never reaches it walled.
- **Identity and verdict pin:** verified for main. 1108c's loss of in-flight receipts is stated honestly.
- **Tests:** they use real artifacts throughout (real Neuralwatt bytes for all three models, real OpenCode bodies, real 11-19 router health). The key-isolation assertions are present.
- **Murphy row:** it is closed by those tests, with a live check after deploy.
- **Deploy:** worker-only. The router needs no change.

## Verdict

PASS

---

## Elephant's record: what was fixed

- **N1:** the design now states the real $1.26 window, the 4.2× count on a cached request, the headroom, the five-429 limit, and the `: cost` upgrade with its precondition (capture a cached request first).
- **N2:** cost table for all three routes and twins, the expected $0.47/day GLM spend, and a precision line (MiMo/DeepSeek precision unknown; the ruling names roles).
- **N3:** the design names the reversal of neuralwatt-first's unpinned choice and the §4 rule; the hotfix review argues each backported SHA.
- **N4:** the design inlines what `myident.py` prints.
- **N5:** the deploy note says helpers get the bundle but lease with the case worker's `router_accounts`. The optional `offered_accounts()` intersection is not done (helper_link is outside this change; a keyless helper is a deploy check).
- **N6:** one line added under item 3.
- Also found by the full suite after this review: three cae763 tests in `test_stream_d_retries.py` assumed a walled calibrator has one gated lane. They now expect Neuralwatt, then the twin (design, Tests).
