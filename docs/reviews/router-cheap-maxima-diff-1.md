**PASS** on the diff review: no Blockers, no Majors, 3 optional Nits. This is not a merge clearance yet. The full suite for `ff0d6f0` is still running (status file says `running`; the log has reached `test_admission_handoff.py`). Merge waits for a final exit code of 0 and a log with 0 failures. Below is the text for `docs/reviews/router-cheap-maxima-diff-1.md`.

---

# Router cheap-route maxima — diff review 1

**Verdict: PASS.** No Blockers, no Majors, 3 Nits (all optional).

**Gate condition:** the full suite (`/tmp/router-cheap-maxima-full-ff0d6f0.json`) was still `running` at review time. This PASS does not mean the suite passed. Merge needs a final exit code of 0 and a log with 0 failures.

**Scope.** Worktree `t3-b7dfac7a`, branch `t3/router-maxima-rounding`, frozen HEAD `ff0d6f0`, diff `e26afc6..ff0d6f0` (15 files, +926/−57). Mode REVIEW, read-only: no edits, tests, compiles, launches or secrets.

I read the zoom_out and implementation_readiness personas, `docs/ENGINEERING.md`, both standards, design reviews 1–3 with their responses, `router.md` "Cheap-route enforced maxima" and `interfaces.md` §7. The Claude tariff and gate wall are out of scope; I only checked that their behaviour is unchanged.

## What I checked and found correct

**The bounds are exact.** I recomputed them by hand:
- MiMo:
  - W = (1048576·0.435 + 131072·0.87)/1e6 = 0.5701632.
  - max_usd = 3W + 1e-6 = 1.710490600.
  - Token maxima: floor(1.7104906e6/0.435) = 3932162 input, floor(…/0.87) = 1966081 output.
- DeepSeek:
  - W = 1048576·(0.14+0.42)/1e6 = 0.58720256.
  - max_usd = 2W + 1e-6 = 1.174406120.
  - Token maxima: 8388615 input, 2796205 output.
- `openrouter_gate_maximum` uses Decimal with ROUND_CEILING and is keyed from exact profile strings.
- `price_source` includes the endpoint tag and all three rates.
- `valid_maximum` still requires exact type and value equality.

**The price and source fixtures are real and faithful.**
- The prices in `GATED_OPENROUTER` equal the saved raw endpoint records (×1e6) for `xiaomi/fp8` and `deepinfra/fp8`. Neither record has an `input_cache_write` charge, and both contexts are 1048576.
- `deepinfra/fp8/flex` and `/priority` are present in the record and excluded from the request.
- Every fixture SHA-256 in `router-cheap-maxima-evidence.json` matches the files on disk.
- The source-evidence archive grew from 13 to 14 entries; `tool/mcp-websearch.ts` was added. It contains `mcp.exa.ai`.
- All full-text hashes reproduce. The two excerpt hashes also reproduce, and both entries are labelled "verbatim relevant excerpt".

**Pricing and the response parser fail closed.**
- Refunds price every prompt token at the uncached rate and every completion token at the output rate. That overestimates cached input.
- When OpenRouter reports `usage.cost`, it must be finite, ≥ 0 and ≤ the conservative amount, or nothing is refunded.
- `OpenRouterUsage` refunds only when all of these hold:
  - one stable `id`;
  - the exact model echo;
  - at most one choice, with index 0;
  - exactly one terminal `finish_reason` from a closed set;
  - exactly one usage object, after the terminal;
  - `total = prompt + completion`;
  - detail counts within their parents;
  - prompt ≤ context and completion ≤ the profile's output hold;
  - streams end with exactly one `[DONE]` and nothing left in the buffer;
  - responses are under 4 MB.
- An `error` event, an encoded response or a non-200 status leaves W retained.
- Late `finish` after close is ignored, so the snapshot stays immutable (tested).

**Request limits are code-owned.**
- `openrouter_body` uses a closed top-level allowlist.
- `max_tokens` becomes min(32768, any requested value) and `max_completion_tokens` is dropped. `reasoning.max_tokens` is clamped to that cap.
- `usage.include` and `stream_options.include_usage` are forced on.
- Content must be text-only blocks, tools must be local functions, and reasoning details and tool calls have fixed shapes. NaN and duplicate keys are rejected.
- `provider = {only:[exact tag], allow_fallbacks:false, require_parameters:true, max_price:{prompt, completion, request:0, image:0}}` is written after validation, so the caller cannot supply it.
- The allowance reserves the profile's output hold (131072 / 1048576), not the sent cap, so the dollar proof does not depend on how OpenRouter maps the requested limit.
- The upstream is fixed: an `HTTPSConnection('openrouter.ai')` with one explicit connect, no redirects and no proxy.

**Lease maximum and D wiring.**
- `route_maximum`, `valid_lease`, `_start` binding and `model_runtime.invocation_maximum` are all unchanged in shape. D reserves `Lease.max_usd` as before.
- In the native ledgers, `maximum_usd` equals `route_maximum`.
- On the retry path, MiMo forwards exactly 3 requests and DeepSeek exactly 2, and the next request hits `model_call_cap` without forwarding. All of these attempts stay unknown, D keeps the full maximum pending, and reconciliation charges the whole gap. Replaying reconciliation is byte-identical.
- `empty_usage(route)` reports the profile's output hold for the paid routes.
- In the real-receipt replay test, sessions pass through the real `reserve_invocation`/`complete_invocation` under a $3 authority. The longest sessions (29 steps / 1611966 input tokens; 34 / 2568428) and the peak figures (2.4924907220 and 2.2841285566) match the design.

**Key custody and isolation.**
- `enforce` rebuilds the paid-route environment from the design's exact allowlist.
- The real key stays in `Gate.upstream_token`. The CLI gets a `secrets.token_urlsafe(32)` token, checked with `hmac.compare_digest`.
- The CLI config arrives as inline `OPENCODE_CONFIG_CONTENT` with `enabled_providers` and a whitelist set. `PURE`, `DISABLE_PROJECT_CONFIG`, `DISABLE_MODELS_FETCH` and `DISABLE_AUTOUPDATE` are all set.
- Every OpenCode call gets fresh XDG config, data and cache directories. Bounded routes skip the shared `/tmp` config. Cleanup goes through the existing `finally`.
- Paid setup is refused unless the platform is Linux, `/etc/opencode` is absent and all three XDG variables are set. The refusal happens before any Gate exists (tested).
- The loopback test shows the HTTP side: the upstream key is refused at the gate (401), the synthetic token is accepted, and only the gateway sends the real key upstream.
- If `enforce` refuses, the process never started, so the runtime records `denied` with final usage known and completes the reservation. No money is held.

**Exa is preserved.**
- `OPENCODE_ENABLE_EXA=1` stays set, and the Parallel and test-managed-config variables are dropped.
- The native Exa probes, for writer and stress_tester on both routes, show `websearch` advertised. The actual CLI makes an HTTPS request to exactly `https://mcp.exa.ai/mcp`, calling `web_search_exa` with no Authorization header.
- The test-only DNS entry and CA trust are recorded in `test_overrides`.

**The native archive is honest.**
- 12 probes, all on OpenCode 1.19.0 with a single binary hash, `--network=none`, as `pilot`.
- The real runtime, router Store, gate, D and `run_budgeted` are used. Only `subprocess.run`'s iptables calls are faked, and that is declared in `scope`.
- The embedded probe source equals `tests/factory/router_cheap_pin_probe.py` byte for byte.
- All recorded source hashes (gate, runtime, prices, probe) equal the frozen HEAD.

**Claude is unchanged.**
- For Claude, `Gate.token == upstream_token`, so the forwarded `Authorization` is byte-identical to before.
- The Claude path, environment, betas, tariff and values are untouched. `empty_usage()` keeps the Claude default.

**The legacy test edits are legitimate.**
- The old DeepSeek `PAID_PRICES` override (.02/1.0) was removed, as the design says.
- 1.12 = 2 × (.14 + .42) and .01956 follow from the new rates.
- The `test_model_runtime` enforce fake is labelled config-only and uses the production `openrouter_environment`.

**Claim limits are respected.** The validation doc:
- says real provider calls and Boat workers were 0;
- makes no claim of live provider acceptance;
- does not claim a case including Claude writers fits $3;
- adds no batch override and closes no Murphy row;
- keeps the full suite marked "pending".

**Free route and fallback (the clarification), checked against the brief and interfaces.**
- `route_maximum('opencode/deepseek-v4.1-flash-free')` is None, so the free route stays unqualified, as the brief requires.
- Router code is unchanged. With the new profiles, `_bounded_routes` sends a request for the free route to the bounded paid DeepSeek lease when `openrouter-key` is authorized. Without it, the existing `bounded` branch returns `outage`, with no lease and no reservation.
- `test_router_cheap_maxima` pins both cases. The money effect is bounded by the same Lease/D path, so this is consistent with the interfaces wording "qualification is on the effective route".

## Nits

**N1. The clarification lists one request name; three now reach paid leases.**
- Affected: `router.md` ≈916–923, `interfaces.md` ≈318–321.
- `test_model_call_maxima` now treats `opencode-go/mimo-v2.6-pro` as qualified (via `CHAINS` → `openrouter/xiaomi/mimo-v2.6-pro`). The `opencode-go/deepseek-v4.1-flash` alias (model_router.py:100) maps to the free route as well.
- Both can now receive bounded paid OpenRouter leases. The docs name only the free DeepSeek route.
- Also, for a request naming the free route on a worker without `openrouter-key`, the effective wait changes from `unbounded_route` (zero relaunches) to `outage` (the 10-per-reason cap). `capacity()` for the requested free route stays 0.
- No money risk. Fix by listing the three names and stating B's consequence in one sentence, so "no classification change" is not read as "same wait outcome".

**N2. The native proof is arm64 only.**
- Affected: `router-cheap-maxima-validation.md`, "actual Linux arm64 binary".
- The archive pins one arm64 binary hash. If production workers are x86_64, say the proof is per-architecture and that the amd64 binary is unproven. Code and source equivalence are already pinned.

**N3. Real response shape is untested (claim note).**
- Affected: `OpenRouterUsage.event`.
- The parser requires the response's `model` to equal the request slug exactly. If OpenRouter returns a versioned or aliased slug, every call becomes unknown. MiMo would hit `model_call_cap` after 3 calls and DeepSeek after 2.
- This fails closed, so it is an availability risk only, and live calls are out of scope. Add it to the known availability risks next to DeepInfra's discounted max_price, so the first live run isn't misread.

Wording only: `interfaces.md` drops some spaces ("to32768", "is0.5701632"). This matches the existing house style there and is harmless.

## Prior findings

| Finding | Status |
|---|---|
| Design R1 M1–M4, N1–N3 | Fixed and present in the code |
| Design R2 M1 (Exa) | Fixed; native proof shows the exact Exa URL |
| Design R2 N1/N2/N4 | Fixed (frozen sources, cache-write negative test, env allowlist) |
| Design R2 N3 (byte cap) | Not adopted; accepted as optional |
| Design R3 N1–N3 | Addressed: `$HOME/.opencode` wording, PURE consumer and runtime-flags source archived, npm attempt named, exact Exa assertion |

No findings were rejected. No Murphy row is closed. No merge or push.

## Author response

- N1 addressed in router.md and interfaces.md: name all three requested-route aliases/fallbacks, distinguish unchanged classifier code from changed outcomes, and state B's outage retry consequence.
- N2 addressed in validation.md: native qualification covers Linux arm64 only; the amd64 binary remains unproven by this archive.
- N3 addressed in router.md and validation.md: exact response-model echo is a known fail-closed availability risk pending live provider acceptance.
- No findings rejected. No production or test source changed after the frozen review SHA. Full-suite status is recorded separately when terminal; the review's at-review pending statement is retained verbatim.

### Terminal validation (after review)

Full suite on frozen `ff0d6f0184db682f266196cd43004ec5b1ac5168` finished
2026-10-30T07:16:58.436895Z: **146 scripts, 0 failed, exit 0**.
Archived JSON/log and SHA-256 are in `router-cheap-maxima-full-ff0d6f0.json`
and `router-cheap-maxima-full-ff0d6f0.log.gz`. No production/test changes after
review; the acceptance commit contains documentation and evidence only.
