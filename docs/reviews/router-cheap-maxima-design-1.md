**Verdict: FAIL.** There are 4 Major findings and 3 Nits. No Blockers.

Scope: uncommitted section `docs/designs/router.md:850-972` and `tests/factory/fixtures/router-cheap-price-records.json.gz`, worktree `t3-b7dfac7a` at `aef4309`. Mode REVIEW, read-only, no tests run.

## What I verified and found correct

- **Prices match the fixture.** `xiaomi/fp8` is 0.435 / 0.0036 / 0.87 per million tokens with context 1048576 and max output 131072. `deepinfra/fp8` is 0.14 / 0.0042 / 0.42 with context 1048576, max output 131072 and `discount` 0.3.
- **Arithmetic is right.**
  - MiMo: W = (1048576·0.435 + 32768·0.87)/1e6 = 0.48463872. 2W + 1e-6 = 0.969278440 ✓.
  - DeepSeek: W = 1048576·(0.14 + 0.42)/1e6 = 0.58720256. 2W + 1e-6 = 1.174406120 ✓.
  - Token maxima of twice each request allowance ✓.
- **The design matches the gate code.** `Allowance.reserve` (`factory/model_call_gate.py:151`) reserves the full-context W and checks settled + retained + active + W + headroom against all three ceilings.
- **Routing controls are in OpenRouter's public docs.** `max_price` is a hard filter in USD per million tokens. `only` accepts endpoint tags, and "dropping the tier never matches a tier endpoint", so `deepinfra/fp8` does not match `/flex` or `/priority`. `require_parameters` excludes providers that lack a parameter, and `allow_fallbacks:false` turns off backup providers.
- **The free route correctly stays `unbounded_route`.** A zero price is not a token bound.
- **No retry bypass.** There is no retry inside the gateway. CLI retries and compaction go back through the same allowance.

## Major

**M1. MiMo's 32768-token output reservation depends on a provider guarantee the design rejects for DeepSeek.**
- The design reserves the full context for DeepSeek output because OpenRouter's reasoning-token coverage applies only to "most providers". It then trusts OpenRouter's mapping of `max_tokens` to a reasoning-inclusive cap for MiMo.
- MiMo's own doc defines only `max_completion_tokens` as covering reasoning. The design does not show which field OpenRouter actually sends to the `xiaomi/fp8` endpoint.
- Failure case: reasoning goes past 32768 tokens, up to the endpoint's 131072 maximum. The request then costs up to 0.5701632 against a retained W of 0.48463872. `finish()` retains W for usage over the allowance, so this is under-reserved spend that never shows up.
- Smallest fix: reserve 131072 output tokens. The MiMo doc gives "Required range: [1, 131072]" and a default of 131072, covering visible and reasoning tokens, so this holds whatever OpenRouter maps. The new values are W = 0.5701632, Lease `max_usd` 1.140327400, and output tokens 262144. Otherwise, cite a primary source for OpenRouter's parameter mapping on this endpoint.

**M2. MiMo's 1048576 input allowance has no provider-semantics source.**
- The only evidence is OpenRouter's advertised `context_length`. The cited MiMo doc does not state a context length for mimo-v2.6-pro, and does not say that prompts over the context are rejected.
- Per the brief, a published context count alone is not proof.
- Fix: cite a primary source (Xiaomi or OpenRouter) saying that prompts over the context are rejected before billing. Otherwise MiMo stays unqualified.
- For DeepSeek, the DeepInfra blog (`deepinfra.com/blog/deepseek-v4-1-flash-deepinfra`) refused connections when I tried it, so I could not check that prompt and completion share the 1048576 context. The design should save a copy or excerpt of it under the planned documentation provenance (Validation item 2).

**M3. The design never shows the $3 practice-case goal is reachable.**
- Each request reserves the full context. With `max_input_tokens` = 2×1048576, a new request is admitted only while settled input ≤ 1048576 tokens. The dollar ceiling limits it the same way: settled spend must stay ≤ W.
- So each invocation can use about 1M cumulative input tokens, with cached input counted in full. OpenCode resends the whole conversation every turn, so that is roughly 10–30 turns before `model_call_cap`.
- Under a $3 job commitment, D reserves `max_usd` per invocation: $0.97 for MiMo and $1.17 for DeepSeek. That allows roughly two or three invocations in a row before `money_wait`.
- Neither limit is checked against saved real OpenCode cards (per-invocation input totals, invocation count per practice case).
- Without that, the routes can pass the qualification proof and still fail B's actual run.
- Required: a budget-fit example built from real cards, or a change to the design, for example a smaller per-request input allowance that is provably enforced.

**M4. Implementation readiness: the design leaves choices to the implementer.**
- **OpenCode 1.19.0 controls are unnamed.** It does not say which environment variables or config keys:
  - disable the global, project and plugin configs;
  - fix the provider `baseURL` and model;
  - point `small_model` and title generation at the gate.
- **The credential path is unstated.** `model_runtime.py:366-369` currently puts `OPENROUTER_API_KEY` into the CLI environment. The design does not say whether it stays there, or how the built-in openrouter provider is stopped from reaching `openrouter.ai` directly.
- **The adapter allowlist is vague.** "Supported sampling/reasoning options" is not a field list, unlike the Claude path's `BODY_FIELDS`.
- **Code touch points are not named:**
  - `enforce()`'s `GATED_CLAUDE` check;
  - `route_maximum` and `valid_maximum`;
  - `empty_usage`'s `max_request_output_tokens=CLAUDE_OUTPUT`;
  - `opencode_config`'s shared 0644 `/tmp` file;
  - removing the old `PAID_PRICES` DeepSeek override (`.02` / `1.0`) and its users.
- **One decision is deferred.** "If a remaining config source bypasses the gate, fix or reject that route" leaves the decision to the implementer.

## Nits

**N1. The fixture is not the raw response its description claims.** The design says "raw ... records ... with response SHA-256", but the fixture stores re-serialized parsed JSON. The stored `sha256` does not match `json.dumps` of the response under default, compact or `sort_keys` settings. Either store the raw bytes (base64) or reword the claim as "parsed response; SHA-256 of the original bytes, not reproducible".

**N2. The headroom label is wrong.** "2*W + 0.000001 (the existing gate's conservative headroom)": the existing headroom is only `HEADROOM = 0.000001`. The 2× factor is a new choice and sets the invocation's whole budget, so say why it is 2.

**N3. Two `max_price` gaps should be written down.**
- OpenRouter's `max_price` has no cache-price field. That is harmless here because the gate charges all input at the uncached rate.
- The docs don't say whether `max_price` is compared with the discounted or the list price. DeepInfra lists a 0.3 discount, so the ceiling may wrongly reject the endpoint. That is an availability risk, not a spend risk, and it can only be seen in a live call.

Also add a test that `only:["deepinfra/fp8"]` with `allow_fallbacks:false` cannot match the `/flex` or `/priority` endpoints.

No prior findings existed for this increment, and the rounding diff was out of scope.


## Author response for round 2

M1 fixed: MiMo reserves the documented provider-wide 131072 output maximum.
M2 addressed with OpenRouter's primary context-error/billing semantics and saved
DeepInfra source; the reviewer must judge this evidence, not an author rejection.
M3 fixed: replay measured real session totals, increase MiMo to 3W, derive token
ceilings from dollar caps, and exercise D's release on completion with a $3 job.
M4 fixed: enumerate config/environment/credential/adapter controls and touch points,
including a definite Linux managed-config refusal.
N1 fixed with original raw_text bytes and reproducible SHA-256. N2 fixed by
explaining capacity factors. N3 documented and endpoint-tier tests specified.
No finding rejected. All proposed paid routes remain disabled pending passing
review and implementation proof.
