**Verdict: PASS.** I found no blockers and no majors, only five optional nits. This is a fresh goldfish diff review of `351fb51..14d40b7` on `t3/router-item8-prereqs`, in Mode: REVIEW with the zoom_out and implementation_readiness personas. I read the persona files first, then `docs/ENGINEERING.md` and the readiness standard. I checked the diff against `docs/designs/router-item8-route-profiles.md`, reading the production code, the tests, the fixtures and the reports. I did not rerun the suite. The committed record shows 161 scripts, 0 failures, exit 0, and the log ends "161 test scripts run; 0 failed."

## What I checked and found correct

**Maxima.** I recomputed every figure by hand and all of them match the design and `docs/reports/router-item8-route-maxima-20261031.json`:
- **Opus 4.5 worst hold:** 200000 × $10/M + 16384 × $25/M = $2.4096.
- **Compact ($3):** 6,000,000 input / 120,000 output.
- **Small ($5):** 10,000,000 input / 200,000 output.
- **MiniMax:** (1M × .05 + 900k × .2)/1M = .23 per request; 3 × .23 + .000001 = .690001; 13,800,020 input / 3,450,005 output.
- **Price-source strings:** byte-equal to the design, including `:profile=<name>:usd=<3|5>`.
- **Headroom:** with `HEADROOM = .000001` (`model_call_gate.py:194,198`), a further full request is admitted only while validated spend is at most $0.590399 / $2.590399. That matches the report's claim.

**Admission stays exact.**
- `route_maximum` covers only exact `CLAUDE_PROFILES` and `GATED_OPENROUTER` keys. Bare `claude/claude-opus-4-5-20251101`, `:medium`, `:unknown` and the `:free` MiniMax addresses all return None.
- `valid_maximum` still compares all four fields, and the test proves a lease with forged Opus 5.5 maxima is rejected.
- `CHAINS` is untouched. The new MiniMax address is not in the `minimax-m3.1-flash-free` chain, and a test asserts it.
- `git grep` finds no existing card, prompt or config that uses either new route, so no current binding newly gets paid admission.

**Existing Opus 5.5 behaviour is preserved.**
- **`request_body`:** for profiles with `thinking=None` it still forces adaptive thinking, sets `inference_geo='global'` and accepts the 5-level effort set.
- **Defaults:** `empty_usage` still falls back to `CLAUDE_OUTPUT`, and `claude_gate_cost` still defaults to `GATED_CLAUDE`.
- **`MAX_THINKING_TOKENS`:** it is stripped for legacy profiles, which is equivalent to before, when it was never in `ENV_KEYS`.
- **Legacy-only tests:** the tests narrowed to `LEGACY_CLAUDE_PROFILES` are the ones tied to Opus 5.5 captures, which matches the design's clarification.

**Opus 4.5 gate.**
- The model ID is checked exactly on both the request and the streaming and non-streaming responses.
- Context limits apply per usage field and per sum.
- Output is clamped to 16384 before the thinking check, so the "budget below the clamped max_tokens" check is correct.
- The thinking whitelist accepts only `{type: disabled}` or `{type: enabled, budget_tokens: int in [1024, 8192], < max_tokens}`, and rejects adaptive.
- Effort is restricted to low/medium/high.
- `inference_geo` is not in `BODY_FIELDS`, so a caller cannot inject it. Leaving it out for 4.5 is safe.
- The `anthropic-beta` header is replaced with the `BETAS` allowlist; the 1M-context header test proves this.
- The `enforce` environment overwrites `MAX_THINKING_TOKENS`, `CLAUDE_CODE_MAX_OUTPUT_TOKENS` and `ANTHROPIC_SMALL_FAST_MODEL` from code.
- sudo `--preserve-env` now includes `MAX_THINKING_TOKENS`, but `enforce` replaces the environment first, so only the value set in code is carried through.

**MiniMax gate.**
- The existing paid path is reused unchanged: `only=['tenstorrent/fp8']`, `allow_fallbacks=False`, `require_parameters`, and `max_price` caps of .05/.2/0/0.
- Requested output is clamped to 32768 while the full 900k provider output is held.
- An unknown response model ID keeps the .23 hold, and the test proves it with a dated-suffix ID.
- `source_date` is per profile with a 2026-10-30 default, so the DeepSeek and MiMo provenance stays byte-identical. The cheap-maxima test's pinned 1.174406120 still passes.

**Runtime and receipts.**
- `model_runtime.py:547` sends the provider ID to the CLI while `models_used` and the lease keep the alias.
- `budget.py:920`'s `claude_cost(configured_model)` prices alias receipts at Opus 4.5 rates. The ledger test with a real saved writer counter confirms the subscription estimate.

**Interruption regression.** The design asked for it over the new routes and the diff delivers it. `test_runtime_close_mid_response_retains_hold_once` now runs every Claude profile plus MiniMax, through the real Store, ModelRuntime and ledger, over HTTP/1.0, HTTP/1.1 keep-alive and Connection: close. The expected holds are independent literals (2.409600, .23, 8.655360), not values taken from the code under test.

**Evidence limits are stated honestly.** The report and design claim:
- no live inference;
- no Linux CLI or side-call proof;
- no MiniMax paid-call success;
- no Murphy row closed;
- paid item-8 dispatch blocked on B3's atomic cross-release cap at min($11.63, credit), with no claim that the generic router enforces it.

That matches the code: the diff adds no such cap and claims none. The new fixtures contain no credentials, and the CLI fixture's environment and arguments are synthetic.

**Scope.** No Codex changes, no manifests or chains, no candidate rewrites, no new ledger or launch path. This is consistent with YAGNI and the design.

## Nits (optional)

1. **`factory/token_prices.py:110-114` (`claude_profile`):** the descriptor is three repeated `if model == GATED_CLAUDE45` conditionals rather than the code-owned data table the design describes. A small `{model: dict(context=…, output=…, thinking=…)}` table would be shorter, and the next profile would add a row instead of three more conditionals.

2. **`factory/token_prices.py:147-148`:** the Opus 4.5 `price_source` hardcodes `context=200000:output=16384` instead of building it from `claude_profile(route)`. If the profile's output ever changes, the provenance would silently stop matching the enforced bound. Today they agree, and the test pins the full string.

3. **`factory/model_call_gate.py:98` and `:120`:** whether geo is set to global, and which effort levels are allowed, both hang off `profile['thinking'] is None`. That couples two unrelated provider facts to the thinking flag. A future 4.6+ profile with a fixed thinking budget would silently lose the global geo override. An explicit `geo` field, or keying on the model, would be clearer.

4. **`tests/factory/test_router_item8_profiles.py:120-144`:** a few edges are untested.
   - The headroom test checks only the refusal at $0.5904 / $2.5904, not admission at exactly $0.590399 / $2.590399. That boundary is the report's stated claim.
   - Thinking `{type: disabled}` is never checked as accepted.
   - No test rejects `budget_tokens=1023`.

5. **Effort is fail-closed but unflagged:** a card role effort of xhigh or max on these routes will make every request "unsupported" at the gate. That is fail-closed, but the runtime surfaces it only as unsupported requests. Worth a line in the B3 compatibility checklist, which the design already says must cover effort low/medium/high.

## Elephant disposition

PASS; no blockers or majors. Optional nits 1–3 are deferred: the current exact profiles and provenance are pinned by tests; a future provider-profile change must update the descriptor and contracts together. Nit 4 is recorded as optional boundary coverage for a future test increment; no tested runtime behavior was changed after the full suite. Nit 5 is accepted: B3 compatibility must reject unsupported role efforts (xhigh/max); the reviewed design already requires low/medium/high. No existing manifests are activated. No Murphy rows close.

Implementation reviewed: 14d40b7; diff baseline: 351fb51. Full suite: 161 test scripts, 0 failed, exit 0. This follow-up commit records the review only.

