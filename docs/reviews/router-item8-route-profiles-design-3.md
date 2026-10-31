I've finished checking the design read-only. All the stated maxima match the code's formulas. No blocker is left, so the verdict is **PASS** with 3 majors and 6 nits. The full review is below for you to save as `docs/reviews/router-item8-route-profiles-design-3.md`.

---

# Fresh goldfish design review: `docs/designs/router-item8-route-profiles.md` (round 3)

**Verdict: PASS.** There is no open blocker. There are 3 majors and 6 nits.

**Setup:**
- **Mode:** REVIEW.
- **Personas:** zoom_out, design_critic, implementation_readiness.
- **Standards:** heilmeier-standard.md, implementation-readiness-standard.md, docs/ENGINEERING.md.
- **Worktree:** `t3-afe2d824`, branch `t3/router-item8-prereqs`, HEAD 351fb51. There are no code changes. The untracked files are the design, the funding report, reviews 1–2 and four fixtures.
- **What I did:** read-only. No edits, secrets, provider or model calls, web fetches or subagents. The only things I ran were decompressing fixtures and offline Decimal arithmetic.

**Read:**
- The three persona files and both standards.
- `docs/ENGINEERING.md`.
- The design, and reviews 1 and 2 in full.
- All four `router-item8-*` fixtures, decompressed:
  - `router-item8-minimax-availability.json.gz`
  - `router-item8-minimax-endpoints.json.gz`
  - `router-item8-claude45-cli.json.gz`
  - `router-item8-source-evidence.json.gz`
- `factory/token_prices.py`, lines 1–140.
- `factory/model_router.py`, lines 25–135.
- `factory/model_call_gate.py`:
  - constants (lines 28–40);
  - `request_body` and `empty_usage` (lines 89–139);
  - `amount` and `reserve` (lines 160–200);
  - `openrouter_body` and `OpenRouterUsage` (lines 316–470);
  - `enforce` (lines 642–672).
- `factory/model_runtime.py`, the selection and invoke greps.
- `factory/rotation-3writers.json`.
- `docs/designs/stream-d.md`: the item-8 role map and scenario table (lines 3530–3610).
- `docs/reports/router-item8-funding-20261031.md`, the relevant lines.

## Exact maxima: offline recomputation

All values below were recomputed with Decimal, using the existing `openrouter_gate_maximum` and `claude_gate_maximum` formulas and the gate's `reserve` rule.

| Item | Design value | Recomputation | Result |
|---|---|---|---|
| Opus 5.5 hold (motivation) | 8.655360 | 1,000,000×8/1M + 32768×20/1M = 8.65536 | Matches |
| Opus 4.5 worst hold | 2.409600 | 200,000×10/1M (dearest input rate, the 1h cache write) + 16384×25/1M = 2.4096 | Matches |
| Opus 4.5 headroom | 0.590399 / 2.590399 | 3 or 5 − 2.4096 − 0.000001 (HEADROOM) | Matches |
| Opus 4.5 input / output maxima | 6,000,000 / 10,000,000; 120,000 / 200,000 | USD×1M/min(5, 0.5, 10) and USD×1M/25 | Matches |
| MiniMax M3.1 Flash worst request | 0.230000 | 1,000,000×0.05/1M + 900,000×0.2/1M | Matches |
| MiniMax max_usd | 0.690001000 | (3×0.23 + 0.000001), ceiling to 9 places | Matches |
| MiniMax input / output maxima | 13,800,020 / 3,450,005 | int(690001/0.05) and int(690001/0.2) | Matches |
| MiniMax fixture inputs | 0.05 / 0.005 / 0.2; context 1,000,000; output 900,000; discount 0 | Availability fixture, tag `tenstorrent/fp8`: prompt 5e-8, cache_read 5e-9, completion 2e-7, discount 0, same limits | Matches. It is the only `tenstorrent*` tag, so there is no flex sibling |
| MiniMax `:free` variant | "endpoint list empty" | Second GET, at 2026-10-31T14:58:37Z, status 200, returned `endpoints: []` | Matches |
| DeepSeek (unchanged) | 1.174406120; 8,388,615 / 2,796,205 | 2×(1,048,576×0.14 + 1,048,576×0.42)/1M + 0.000001 | Matches. Review 2's major 2 is closed |
| MiniMax source string | `token_prices:2026-10-31:openrouter:minimax/minimax-m3.1-flash:tenstorrent/fp8:0.05,0.005,0.2:joint-gate-v1` | Existing formula: `route.replace('/', ':', 1)`, then the endpoint, then the joined price strings, with the date made per-profile | Consistent, provided the price strings are exactly `'0.05'`, `'0.005'`, `'0.2'` |
| Claude source string | `…:5.0,0.5,10.0,25.0:…:profile=<compact\|small>:usd=<3\|5>` | `str(Decimal(str(float)))` gives `5.0`, `0.5`, `10.0`, `25.0`. The existing suffix renders `usd=3` and `usd=5` | Consistent |

**What is enforceable offline.** These are invocation ceilings that `valid_maximum` and `reserve` can enforce offline, before upstream:
- a lease that cannot be forged;
- a hold for every request;
- an unknown result keeps its whole hold.

**What is left to live acceptance.** The design keeps these apart from the ceilings (lines 15, 69–70, 144–145, 177, 206–210, 281–284): whether a role finishes useful work inside those ceilings, and whether the transport and model IDs are compatible.

That split is correct. The practical consequence also needs stating, because it is where the money binds:
- `:compact` can run exactly one maximum-size request at a time, since 2×2.4096 > 3. A side call made through `ANTHROPIC_SMALL_FAST_MODEL` waits behind the main request rather than failing.
- After settled spend reaches $0.590399, `:compact` admits no further maximum-size request.
- `:small` reaches the same point after $2.590399.

Scenarios 1–3 and 7 have whole-scenario budgets of $10 or $5, and a real writer round has cost up to $15.05. So whether a role finishes useful work inside these ceilings is genuinely unknown. The design correctly declines to infer it from aggregate card data.

## Rechecking review 2

| Review 2 finding | Status |
|---|---|
| 1. Blocker: M3 was a model substitution | **Closed.** The route is now the same model, `minimax/minimax-m3.1-flash`, pinned to `tenstorrent/fp8`. Lines 93–102 state the binding rule explicitly: new compatible manifests only, no CHAINS change, no rewrite of a saved candidate, and the free bindings stay unbounded. The code agrees: `routes('opencode/minimax-m3.1-flash-free')` still returns only the free chain, and `routes('openrouter/minimax/minimax-m3.1-flash')` returns one paid lease on `openrouter-key`, family `minimax`. One leftover inconsistency with stream-d is finding 2 below |
| 2. DeepSeek misquote | **Closed.** See the maxima table |
| 3. Geo contract | **Closed** as a rule. Lines 268–275 keep the strict check (absent or `global` only) and record the live risk. The source record is weaker than the claim; see nit 6 |
| 4. Lifecycle evidence | **Closed** as evidence. The record shows the model Active, not deprecated, with retirement not before 2026-11-24. The consequence for this design is finding 3 |
| 5. Claude wire evidence | **Closed**, within the stated limits. The fixture holds two full request bodies and two synthetic SSE responses. Request 2 replays a `thinking` block with a `synthetic-signature-…` signature, then `tool_use` and a user `tool_result`. Both requests show `max_tokens` 16384, thinking enabled with budget 8192, effort high, tools Bash/Edit/Read/Write and no `context_management`. The upstream responses contain no `inference_geo`. The binary SHA matches. Request headers are not saved in `wire`; only the beta string is in `shapes`, which is enough for the beta allowlist test. Linux and side calls are labelled unproved |
| 6. MiniMax wire contract | **Mostly closed.** The response model-ID and OpenCode parameter questions are accepted as live risks that fail closed. The named fixture test conflicts with the file list; see finding 1 |
| Nits 7–11 | Normalized excerpts are labelled; paid refusal is stated as procedural; effort is in the compatibility rule; Codex wording is removed; the probe platform is stated. **All closed** |

## Majors

**1. The fixture list names the retired M3 fixture as the MiniMax contract source, and leaves out the actual evidence.**
- **Scope:** lines 74–79 against lines 248–251 and lines 149–152.
- **The conflict:**
  - Lines 77–79 say `router-item8-minimax-availability.json.gz` is the evidence, and that the M3 endpoints fixture is "retained only as review history, not an input".
  - The Fixtures entry in "Exact files" lists only `router-item8-minimax-endpoints.json.gz` as "real public provider metadata".
  - That file holds `minimax/minimax-m3` and `-20260531`, tags `deepinfra/fp8` and `deepinfra/fp8/flex`, and no Tenstorrent entry.
  - `test_minimax_endpoint_contract` does not name its fixture.
  - The disposition on line 260 still says "both standard/flex variants explicitly covered", which describes M3.
- **Why it matters:** the implementer has to pick which fixture pins the tariff, limits and `supported_parameters`. Under the zero-decision rule that is a readiness gap. If the wrong file is picked, the test fails or, worse, asserts M3's DeepInfra contract.
- **Fix:**
  - Name `router-item8-minimax-availability.json.gz` in the file list as the source for `test_minimax_endpoint_contract`.
  - Have the test assert, from the `tenstorrent/fp8` entry: prompt `0.00000005`, cache_read `0.000000005`, completion `0.0000002`, discount 0, `context_length` 1000000, `max_completion_tokens` 900000, and that `max_tokens`, `tools`, `tool_choice` and `reasoning` are in `supported_parameters`.
  - Have it assert that the `:free` response has `endpoints == []`, and that exactly one endpoint tag starts with `tenstorrent`.
  - Either delete the M3 fixture or mark it history-only in the file list.
  - Correct the line-260 disposition.

**2. The scenario claim cites stream-d, but stream-d's role map still asks for free-route MiniMax maxima.**
- **Scope:** lines 46–54 and 93–102, against `docs/designs/stream-d.md`, lines 3540–3549.
- **The conflict:**
  - The design says scenarios 1–3/6 "need paid MiniMax" and cites the stream-d role map.
  - That map lists "approved free-route maxima" as the scenario 1–3 prerequisite.
  - It also says "never silently change a saved candidate's role binding".
  - The saved family binding is `opencode/minimax-m3.1-flash-free`.
  - In the runtime, a card role's `model` is what `routes()` resolves. So the only way to use the new paid route is a card or manifest whose MiniMax role model is the paid route string, which is a different binding from the saved one.
- **What the design gets right:** the change is explicit, not silent. The design says it supplies "a manifest option, not … evidence that current saved candidates are eligible", and it adds no CHAINS entry.
- **What is still undecided:** the meaning of "compatible" ("must cover model ID…"). Does a different route string for the same underlying model pass? That is left to "B's existing admission contract", and the design does not show that contract has any such rule. Until it does, the route has no admissible consumer.
- **The evidence gap:** the empty `:free` list covers OpenRouter's free variant only. It does not show anything about the OpenCode free route that the saved binding actually names.
- **Why this is not a blocker:** this increment creates no manifest or launch path, and the money ceilings are correct whatever B3 decides.
- **Fix:**
  - State that adopting the paid route for scenarios 1–3/6 requires a reviewed stream-d/B3 amendment that defines when a route string counts as model-ID compatible for the same model. Same-model compatibility should also cover the provider's quantization (fp8 on Tenstorrent; the saved free route's serving is unknown).
  - Reword line 47–48 from "need paid MiniMax" to "can use paid MiniMax only after that amendment".
  - State that the free-variant evidence covers OpenRouter `:free` only.

**3. Opus 4.5's retirement floor is 24 days away, and the design does not say why it chose that model or what happens when it retires.**
- **Scope:** lines 17–21, 111–114 and 175–176 (Heilmeier: new approach, risks, timeline).
- **The facts:**
  - The saved lifecycle record says Active, with retirement not before 2026-11-24.
  - Every item-8 scenario is still blocked on B3. Scenarios 4/6 are also blocked on the deferred OpenAI maxima.
  - So qualification will plausibly run after 2026-11-24, when Opus 4.5 is no longer guaranteed.
- **What is missing:** the design gives the reason for a smaller-context model ("smaller documented context"). It does not record:
  - which other subscription-CLI Anthropic models were considered and rejected. I made no calls, so whether a current-generation model with a small enough context exists is unproved;
  - what B3 does if the model is retired.
- **What a retired model does to the gate:** retirement probably shows up as an upstream error. An error with no validated usage settles as unknown and keeps the $2.4096 hold. So `:compact` stops after one attempt and `:small` after two. That fails closed, but it is easy to misread as a capacity limit, not a dead route.
- **Fix:**
  - Add one line on the alternatives considered and why Opus 4.5 won.
  - State the post-2026-11-24 rule: B3 re-freezes the lifecycle record before each paid or subscription dispatch; a retired or deprecated status refuses the profile before any lease; and a not-found model error is recorded as infrastructure route loss, not as role failure or a capacity limit.
  - Note that a later model swap gets a new design, not an edit to this one.

## Nits

**4. The bare 4.5 route should be explicitly unbounded.**
- Adding `claude/claude-opus-4-5-20251101` to `CLAUDE_PRICES` is required.
- State that only `:compact` and `:small` enter `CLAUDE_PROFILES`, so the bare route has no lease.
- Add an assertion to the unknown-alias tests.

**5. Pinning a single low-traffic provider is an availability risk to name.**
- `tenstorrent/fp8` shows `latency_last_30m` and `throughput_last_30m` as null, and the pin has no fallback.
- A routing or availability error before generation still keeps the $0.23 hold. Three such errors exhaust the invocation, and the unknown holds count against the $11.63 until they are reconciled.
- Name this as a live risk next to the model-ID risk.

**6. The geo source record claims more than its excerpt says.**
- The saved excerpt states only that `inference_geo: us` costs 1.1× for 4.6 and later.
- Its `facts` add `first_party_default: "global"` and `geo_selector_minimum_model_version: "4.6"`, and the excerpt states neither.
- The behaviour stays safe either way: the request omits geo on 4.5, BODY_FIELDS already rejects any caller-supplied `inference_geo`, and strict response validation fails closed.
- Either save an excerpt that supports both facts, or mark them as inferred.

**7. Say whether `output_config.format` stays allowed on Opus 4.5.**
- The design limits effort to low/medium/high, but says nothing about `format`, which `request_body` allows today.
- State whether it stays allowed on 4.5, or is rejected for it.

**8. Line 106 is stale.**
- It says the source fixture is "to be frozen … before code". It already exists.
- Change it to "frozen in".

**9. The prose runs words into numbers.**
- Examples: "Opus4.5", "context1000000", "budget8192", "November24".
- The Heilmeier objective asks for no jargon. Restore the spaces so the prose is readable.

## Strengths (no action needed)

- Every exact maximum is right in all four fields, for both Claude profiles, the new MiniMax route and the unchanged DeepSeek route. Each follows the existing code formula, and the final report reads them from `route_maximum`, not from prose.
- The binding rule for paid MiniMax is explicit and touches no CHAINS. The free bindings stay unbounded, and saved candidates are not rewritten.
- The Claude wire evidence is now a real two-request tool loop with replayed thinking, saved as raw bytes. Its stated limits (darwin only, no side calls, no real inference) are accurate.
- Geo and tier validation stays strict, and the empty-geo exhaustion risk is stated, not waived.
- The $11.63 total and B3's shared paid reservation are framed honestly:
  - no test is claimed to prove them;
  - paid item-8 dispatch is refused until B3 lands;
  - it is acknowledged that the generic router can already issue paid leases, as it does for DeepSeek and MiMo.
- Codex is fully deferred, with no prices, parser or advertised maxima.
- No Murphy row is closed. Offline maxima are kept clearly apart from live qualification of useful roles.

**Result: PASS.** No blocker is open.
- **Majors 1–3** should be corrected, or explicitly accepted, before implementation starts. Major 1 is a direct zero-decision gap in the test and fixture list.
- **Nits** are optional.


## Implementer disposition

PASS acknowledged. All three majors accepted and clarified in the design before
implementation: correct fixture, stream-D/B3 route-compatibility amendment, and
lifecycle checks/alternatives. Nits addressed; geo source inference labelled.
No blocking finding rejected or self-verified.
