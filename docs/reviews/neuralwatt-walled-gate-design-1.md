# Design review 1: neuralwatt-walled-gate (goldfish)

## Scope

- **Design reviewed:** `docs/designs/neuralwatt-walled-gate.md` (whole file), checked against option B of `docs/designs/neuralwatt-routes.md` §"Walled roles (easy_calibrator) and Neuralwatt".
- **Lenses:** zoom_out, design_critic and implementation_readiness. Standards: Heilmeier and Implementation Readiness. Mode: REVIEW.
- **Code read:**
  - all of `factory/model_call_gate.py`;
  - `factory/token_prices.py`;
  - `factory/model_router.py`: routes, `CHAINS`, `ungated_lanes` and the paid-path keys;
  - `factory/model_runtime.py`: `bounded_route`, `opencode_config`, `_call` and `_invoke`;
  - `factory/budget.py`: Neuralwatt booking, `_gate_bound`, `_settle_leaf` and `check_limits`;
  - `factory/ordinary_retry.py`;
  - `factory/durable/checkpoints.py` (`verdict_code`), `factory/gate_state.py` (`source_inputs`, `model_science`), `factory/durable/classify.py`, `factory/durable/stop_registry.py` and `factory/calibration.py:539`;
  - `factory/run.py`: `pilot_wall`, preflight, dedup;
  - `factory/durable/helpers.py` and `factory/durable/helper_link.py`;
  - existing tests `tests/factory/test_neuralwatt_runtime.py` and `tests/factory/test_neuralwatt_routes.py`.
- **Fixtures:** I decoded `tests/factory/fixtures/neuralwatt-gate-streams-20261120.json`. I also read `neuralwatt-smoke-20261119.json` and `neuralwatt-price-record-20261120.json.gz`.
- **What I ran (read-only, in memory):**
  - I added `neuralwatt/glm-5.3-flash` with `_nw_profile` into an in-memory `GATED_OPENROUTER`.
  - I fed the three real responses through `OpenRouterUsage`, whole and in 1-byte and 7-byte chunks. All of them returned the real usage: (19,77), (162,13) and (19,17).
  - `openrouter_body` accepted all three real request bodies.
  - `request_hold` gave $0.1736704, which matches the design.
  - Main's model `verdict_code` answers `802bfc8f…` (the raw digest; the stored pin is stale), which matches the design.
- **Confirmed sound:**
  - The router's paid path keys only on `GATED_OPENROUTER` (`model_router.py:573,584,635,709`), so Neuralwatt never reaches `paid_reserve`.
  - Gate identity: `model_effort` reaches only `family` through the import node at `model_runtime.py:28`. `token_prices.py` is in no gate dependency list.
  - Helpers install the case's own release (`helper_link.py:10`), so the pin does not route tries to stale code.

## Findings

### 1. BLOCKING: on the gate path, budget.py's Neuralwatt per-step stop ends a walled call as `infra:usage_reservation_exceeded`, not `model_call_cap`

**Evidence**
- `budget.py:1113-1118` stops a Neuralwatt call when booked + `nw_request_worst(route)` > the maximum.
  - `nw_request_worst` is built from the twin's whole output limit (`token_prices.py:100-102,127-129`).
  - For GLM that is $0.629 (1,048,576 × 0.15 + 943,718 × 0.5, per million).
  - The gate's own hold is $0.174, because it clamps output to 32,768 tokens.
  - So whenever settled spend tracks booked spend, budget.py's stop fires before the gate's exhaustion.
- The ungated Neuralwatt branch maps that stop to the call's cap: `model_call_gate.py:866-868` (`usage_reservation_exceeded` → `model_call_cap`).
- The gate branch has no such mapping: `model_call_gate.py:903-918` maps only `paid_failure`, `exhaustion` and `rejected`.
- `classify.py:156` books `usage_reservation_exceeded` as `infra:usage_reservation_exceeded`, which is an infra retry.
- `calibration.py:539` recognises `model_call_cap`, not `usage_reservation_exceeded`.
- The design (lines 49-50) relies on "budget.py's existing per-step Neuralwatt stop" but never says how it surfaces on the new path.

**Failure scenario**
1. A walled GLM easy calibrator with low cache reuse books about $11.87 of a $12.50 window.
2. budget.py raises `usage_reservation_exceeded`, and the gate re-raises it unchanged.
3. The step is classified as infra and retried. Each retry spends another window.
4. The case should instead stop on money and go to diagnosis.

**Fix:** put the same mapping in the gate branch for a Neuralwatt lease, and add a test that raises `usage_reservation_exceeded` inside a walled Neuralwatt `enforce`. An alternative is to have budget.py use the gate's clamped hold for a walled Neuralwatt call, but the mapping is the one-line fix.

### 2. BLOCKING: no real OpenCode 1.19 multi-turn request exercises the Neuralwatt allowlist, and nothing before G10 runs the gate path

**Evidence**
- The allowlist rejects any message key it does not list (`model_call_gate.py:441-443`, `set(message) - {...}`). The design adds `reasoning_content` based on reading the worker binary (design lines 32-35).
- The test body is "built from the bundled provider's message mapping" (design lines 105-106), so it is hand-built, not captured.
- The 11-19 smoke fixture kept only top-level keys and `n_messages` per request (`neuralwatt-smoke-20261119.json`, `requests`). It holds no message-level evidence.
- The calibrator preflight runs unwalled (`user=None`), so after this change it takes the ungated Neuralwatt branch (`model_call_gate.py:850-869`). It no longer goes through a gate.
- The invariant in `model_runtime.py:539`, "so they test the real route", silently stops being true.

**Failure scenario**
- If OpenCode puts any unlisted key on a message (an interleaved-reasoning field, provider-option metadata, a different reasoning field name), every walled turn after the first reasoning step gets 400 `route_feature_unsupported`.
- That would break 1108c's G10 again, which is the case this change exists to unblock, and no earlier check would catch it.

**Fix (costs $0, no key needed):**
1. Run OpenCode 1.19 with the walled inline config against a loopback stub that replays the recorded tool-call stream, then the reasoning text stream.
2. Capture the second and third request bodies, which carry an assistant message with reasoning and `tool_calls`, and a tool message.
3. Save them in the fixture and pin the allowlist test on them, per ENGINEERING §4 "Real artifacts".

### 3. BLOCKING: the change opens Neuralwatt to walled DeepSeek (and MiMo), which the founder did not approve and which has no real stream bytes

**Evidence**
- The founder's ruling (design lines 3-5) covers "the easy calibrator reads GLM at fp8 on Neuralwatt".
- The parent design says a calibrator's provider move is "the founder's call, not ours".
- But the `ungated_lanes` and `bounded_route` flip is generic over routes (design item 5). The test plan explicitly expects "A walled GLM / DeepSeek calibrator acquire gets the Neuralwatt lane first" (lines 107-110).
- A real October card has a DeepSeek easy calibrator.
- DeepSeek on Neuralwatt is also priced at its own, dearer list (`NW_OWN_PRICES`, `token_prices.py:78`).
- The real-bytes fixture is GLM only. The parser checks `event['model'] == route.partition('/')[2]` (`model_call_gate.py:517`), and that is unproven for DeepSeek and MiMo on Neuralwatt.

**Failure scenario**
- The science risk: a DeepSeek easy calibrator moves provider mid-campaign without a ruling.
- The money risk: if any frame differs (the model name, or an extra terminal shape), every request keeps its hold. The call then stops `model_call_cap` (money) after about 7 requests on an unfunded $1.26 window, or about 72 on $12.50.

**Fix:** either
- (a) scope the walled flip to `neuralwatt/glm-5.3-flash`, the only route with a ruling and real bytes; or
- (b) get an explicit founder ruling for DeepSeek and MiMo, and capture their stream and tool bytes the way the 11-20 GLM capture was made (about $0.00002).

### 4. NIT: Neuralwatt's free 4xx rejections keep their whole hold

- The Claude path refunds a JSON error that carries no usage (`Usage.rejected`, `model_call_gate.py:378-385,693-699`), for exactly this reason (the 429 that exhausted a window).
- Neuralwatt's 429 `concurrent_budget_exceeded` and its 402s are JSON errors with no usage (smoke fixture, `errors`). With three seats shared batch-wide, the 429 is plausible.
- Case money is protected by `open_steps` (`budget.py:433-438`), so nothing leaks to case money.
- But each 429 that OpenCode retries shrinks the call's window by $0.17, and it makes `final_usage_known` false.
- Either state this as a decision, or add an OpenAI-style `rejected()`.
- Also note: with `MAX_REJECTIONS` limited to Claude, a permanent Neuralwatt 400 relies only on budget.py's terminal-error handling.

### 5. NIT: the problem statement misdescribes the wall

- Design lines 9-10 say the walled user's "only network path is one iptables rule to a gate port". In fact `run.pilot_wall` (`factory/run.py:131-133`) says "Public provider/web access and DNS remain available". It rejects only local and private destinations; the gate rule is an exception to the local reject.
- The property that actually protects the key is that it never enters the walled process (env, inline config, argv).
- The security test should assert that, including `Gate.token != NEURALWATT_API_KEY`.
- Today `Gate.__init__` reuses the real credential as the gate token for any route outside `GATED_OPENROUTER` (`model_call_gate.py:732`).

### 6. NIT (readiness): name every `paid` / `GATED_OPENROUTER` branch that switches to the new `openai` flag or to `gate_profile`

The design names some of these, not all. The list is:
- `model_call_gate.py:157` (`empty_usage`);
- `:174` and `:181` (`worst_request`, `request_hold`);
- `:225` (`Allowance.amount`);
- `:399` and `:543` (profile lookups);
- `:602-615` (path and body);
- `:661` and `:664` (headers and host);
- `:683` (parser);
- `:732` (token);
- `:783` (environment);
- `:885-892` (Linux, `/etc/opencode` and XDG checks, and the key's env var).

Two decisions are also left to the implementer:
- **The `not paid` branch at `:693`.** If it is flipped naively, it calls `OpenRouterUsage.rejected()`, which does not exist. The resulting AttributeError escapes the `except` clause.
- **Message-level `reasoning` and `reasoning_details` for Neuralwatt.** The design does not say whether they are allowed or refused.

### 7. NIT: verdict_code pin details

- The model digest covers ten files: `BENCH_VERDICT_CODE` plus `MODEL_CODE` (`durable/checkpoints.py:133-135`). Design line 80 says "those four files". The pin must be recomputed after any merge that touches any of the ten.
- The pin reasoning ("adds a lane only") is sound for main.
- On the cb5e26 hotfix, the pin also vouches for "the Neuralwatt lane commits it lacks". List their exact SHAs, so the "changes no verdict" claim is reviewed for them too.

### 8. NIT: G10 tries on helper machines

- G10 calibrator tries run on helpers with the case's `router_accounts` (`helper_link.py:213,232-255`).
- A helper without `neuralwatt-key` raises account-scope `credential_expiring` (`model_runtime.py:618`).
- That is observed router-wide (`model_runtime.py:726`), which blocks the Neuralwatt pool for the whole batch.
- Today helpers never lease Neuralwatt for walled tries. The deploy note (lines 132-133) mentions the worker bundle only. Name helpers explicitly, and include a helper-run try in the first check.

### 9. NIT (zoom-out): unwalled easy-calibrator calls

- After the change, the preflight and `easy-calibrator-dedup` (`factory/run.py:810-814`) run Neuralwatt ungated with the key. That is acceptable, since they are unwalled.
- A simpler end state is worth stating as the alternative: gate every Neuralwatt call and delete the ungated Neuralwatt branch. That leaves one path, and the preflight would test what G10 uses.
- It is not required now, given the hotfix scope.

### 10. NIT: concurrency

- Several G10 tries now draw on the same three Neuralwatt seats that unwalled MiMo, GLM and DeepSeek calls use.
- The parent design's concurrency numbers (96% of the time covered) predate walled demand.
- Note it, and watch `capacity` waits on `neuralwatt-key`.

### 11. NIT: Heilmeier and Murphy hygiene

- The design has no cost section and no timeline section.
- The Murphy row is "Closed by … it stays open until …", which contradicts itself. ENGINEERING §2 closes a row with a real-artifact test in the fix commit, so pick one.
- Optional hardening: the parser could require `service_tier == "standard"`, which is present in every real Neuralwatt frame.

## Verdict

**FAIL:** blocking findings 1, 2 and 3 are open.

---

## Elephant's record: what was fixed

- **B1, fixed.** `enforce` maps `usage_reservation_exceeded` to `model_call_cap` for a walled Neuralwatt lease. Test: `test_neuralwatt_walled_gate.py::test_the_gate_is_only_for_neuralwatts_own_account_and_key_and_its_stop_is_the_calls_cap`; deleting the mapping fails it.
- **B2, fixed as proposed.** OpenCode 1.19.0 (the worker box's `/usr/local/bin/opencode`) ran with `openrouter_environment`'s walled Neuralwatt config against a loopback stub replaying the real GLM bytes; no key, loopback only. Saved as `tests/factory/fixtures/neuralwatt-gate-opencode-requests-20261120.json`. Its second request carries an assistant message `{content: "", reasoning_content, tool_calls}` and a tool message; both requests pass the real gate and are forwarded as sent (`test_real_opencode_turns_pass_the_gate_and_openrouter_or_unsafe_fields_are_refused`). The preflight note is in the design (item 6).
- **B3, evidence half fixed; scope settled by the founder's own words.** MiMo and DeepSeek text and tool-call streams were captured from Neuralwatt the same way ($0.00002) and added to the real-bytes fixture; the parser and the end-to-end gate test run on all seven answers. On scope: the founder's decision, as relayed to the elephant, reads "let walled roles (the G10 easy calibrator and any WALLED_ROLES) use Neuralwatt through the wall's gate". It names roles, not GLM. The design's opening now quotes it. Not an elephant rejection: a founder ruling covers it. If the diff goldfish reads it differently, the GLM-only scope is a one-line `ungated_lanes` filter.
- **N4:** stated as a decision (design item 3).
- **N5:** problem statement corrected; the end-to-end test asserts no key in the walled env and `Gate.token != key`.
- **N6:** every branch switched; `not paid` at the Claude `rejected()` became `not openai`; message-level `reasoning`/`reasoning_details` are refused for Neuralwatt (tested).
- **N7:** "ten files" corrected; the hotfix review lists the backported SHAs.
- **N8, N10:** deploy section names helper machines and the seat watch.
- **N9:** noted in the design; not done.
- **N11:** cost/time section added; the Murphy row is closed by the named tests, with a live check after deploy. `service_tier` check not added (optional).
