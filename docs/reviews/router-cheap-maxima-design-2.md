**Verdict: FAIL.** There is 1 Major finding and 4 Nits. No Blockers. Once M1 is fixed, nothing else stands in the way of implementing this design.

Scope: the uncommitted section `docs/designs/router.md:850-1064`, plus `router-cheap-price-records.json.gz` and `router-cheap-source-evidence.json.gz`, in worktree `t3-b7dfac7a` at `cb434e3`. Mode REVIEW, read-only: I ran no tests and edited nothing. Claude's 2.2× pricing was out of scope. I read OpenRouter's public docs and pages.

## What I checked and found correct

**Arithmetic.** I recomputed every figure with Decimal, rounding up:

| | W | `max_usd` | Input / output token maxima |
|---|---|---|---|
| MiMo | 0.5701632 | 3W + 1e-6 = 1.710490600 | 3932162 / 1966081 |
| DeepSeek | 0.58720256 | 2W + 1e-6 = 1.174406120 | 8388615 / 2796205 |

All match the table.

**Fixtures.**
- Each `raw_text` hashes to its stored `sha256`, and parses to exactly the stored `response` (N1 fixed).
- The `xiaomi/fp8` record is 0.435 / 0.0036 / 0.87, context 1048576, max output 131072, discount 0.
- The `deepinfra/fp8` record is 0.14 / 0.0042 / 0.42, context 1048576, max output 131072, discount 0.3.
- The `deepinfra/fp8/flex` and `deepinfra/fp8/priority` tags are present, so the planned exclusion tests have real records to run against.
- All eight source-evidence entries hash correctly. The two excerpts are labelled as excerpts and their SHA-256 reproduces.

**Real-session replay (M3 fixed).**
- I replayed `router-paid-deepseek.json.gz` independently, grouping by `ses_` prefix in receipt order. Longest sessions: MiMo 29 steps / 1611966 input tokens, DeepSeek 34 steps / 2568428. Both match the design.
- Before each step, every session still admits a full next-request W under all three ceilings.
- Budget-fit totals: e15450 has 17 sessions, $0.8515172860 total, peak $2.4924907220. 873d7f has 14 sessions, $0.6516037902, peak $2.2841285566. Both match exactly.
- The design's disclaimer is accurate: it does not claim a whole historical case fits $3, and two MiMo leases running at once would correctly wait for money.

**MiMo output (M1 fixed).** The frozen Xiaomi API doc defines `max_completion_tokens` as visible plus reasoning output, default 131072, "Required range: [1, 131072]". The endpoint record agrees. Reserving 131072 needs no assumption about how OpenRouter maps parameters.

**Input bound (M2 accepted).**
- The frozen OpenRouter excerpt classes an over-window prompt as a context-length error, and says requests that fail after failover are not billed. The DeepInfra excerpt says prompt and completion share the 1048576 context.
- The design keeps W on every failure, including the 429 and partial-output cases the page admits. So the only remaining exposure is a rejected over-context prompt billed at more than W. That is implausible, and the design's evidence is now primary-source.
- MiMo's endpoint accepts image, audio and video input, so the adapter's text-only rule is load-bearing. The design states it.

**Price and routing controls.**
- The public docs confirm `max_price` with `prompt`, `completion`, `request` and `image` fields, and `allow_fallbacks:false` meaning "fails if DeepInfra fails".
- A base tag does not opt into a tier endpoint.
- The docs do not say whether `max_price` compares the discounted or the list price. The design treats this as an availability risk only, which is correct (N3 fixed): either way the billed price can't exceed the ceiling.

**No money bypass.**
- The real key stays only in the gateway process, and the CLI gets a synthetic per-invocation token. So any config source that escapes the gate (project `.opencode` directories, plugins, managed config) cannot spend from the OpenRouter account.
- The design refuses to start on Linux if `/etc/opencode` exists, and drops `OPENCODE_TEST_MANAGED_CONFIG_DIR` through the environment allowlist. This matches the frozen `managed.ts`.
- `OPENCODE_CONFIG_CONTENT` merges last, so the inline config wins (config.ts:482).
- The fresh `XDG_DATA_HOME` removes the auth entries that trigger remote well-known config.

**Code touch points (M4 otherwise fixed).** The named touch points exist:
- `enforce`'s `GATED_CLAUDE` check (`model_call_gate.py:397`)
- `route_maximum` and `valid_maximum` (`model_router.py:44,49`)
- `empty_usage` (`model_call_gate.py:126`)
- `opencode_config`'s shared 0644 file in `/tmp` (`model_runtime.py:148`)
- the old `PAID_PRICES` DeepSeek `(.02, 1.0)` entry (`token_prices.py:12`) and its users (`token_prices.py:41`, `model_runtime.py:154-156`)

**Other.**
- The free route stays `unbounded_route`.
- Both new multipliers are explained as capacity choices, not price factors (N2 fixed).

## Major

**M1. The OpenCode environment contract silently drops web search for writers and stress testers.**
- Today `_invoke` always sets `OPENCODE_ENABLE_EXA=1` for OpenCode calls (`model_runtime.py:522`). On the Claude path, those two roles get `WebSearch` and `WebFetch` (`model_runtime.py:567`).
- The new setup lists exactly which variables the CLI gets and says no other OPENCODE variables survive. It never mentions `OPENCODE_ENABLE_EXA`.
- Failure case: an implementer following the list exactly ships cheap-route writers and stress testers with no Exa search. Freshness and admission behaviour then differ from the current route, and nothing fails loudly.
- The opposite choice also needs saying. Exa traffic is non-model and has no credential, so it sits outside the gate's money bound.
- Both outcomes are the implementer's guess, which the implementation-readiness standard forbids.
- Fix: state explicitly whether `OPENCODE_ENABLE_EXA=1` is kept for writer and stress-tester roles (noting it is outside the money bound), or dropped (noting the capability change). Add an outbound-capture test in Validation item 4 for whichever is chosen.

## Nits

**N1. The four new OpenCode flags are not in the frozen source.**
- `OPENCODE_PURE`, `OPENCODE_DISABLE_MODELS_FETCH` and `OPENCODE_DISABLE_AUTOUPDATE` are defined in `flag.ts`, which is not archived. `ConfigPaths.directories` (`paths.ts`) is not archived either.
- The frozen `config.ts:438` loop loads `.opencode/opencode.json`, agents, commands and plugins from every discovered directory, whether or not `OPENCODE_DISABLE_PROJECT_CONFIG` is set.
- Gateway-only custody of the credential already prevents spend, but add both files to the evidence archive. Then say whether a case worktree's `.opencode` is still loaded, or let Validation item 4's capture of the real binary prove it.

**N2. Cache-write pricing has no ceiling.** Neither endpoint record has an `input_cache_write` price, and `max_price` has no cache field. If a provider later added a cache-write price above the input rate, a request could cost more than W, and the refund check (OpenRouter cost ≤ conservative estimate) would only catch it after the fact. Add one line saying a record with a cache-write price invalidates the profile, and add a test that rejects it.

**N3. A cheap local input bound is available.** Real per-step input never exceeded 130576 tokens. For text-only, byte-level-BPE requests, tokens are at most UTF-8 bytes plus template overhead. A request-body byte cap set safely below the context (with margin for overhead) would make the input bound hold locally, without trusting the provider. This is defence-in-depth, not required.

**N4. Wording conflict between the managed-config guard and the environment allowlist.**
- `/etc/opencode` is refused, while `OPENCODE_TEST_MANAGED_CONFIG_DIR` is removed by the "no inherited OPENCODE variables" rule. Say explicitly that this variable is dropped.
- That same rule appears to conflict with the variables the design sets itself. "Allowlist = exactly the listed keys" would remove the ambiguity, which also bears on M1.

## Prior findings

| Finding | Status |
|---|---|
| M1 | Fixed |
| M2 | Fixed (evidence accepted) |
| M3 | Fixed (reproduced) |
| M4 | Fixed, apart from the EXA gap now raised as M1 |
| N1 | Fixed |
| N2 | Fixed |
| N3 | Fixed |

Sources: [OpenRouter provider selection](https://openrouter.ai/docs/guides/routing/provider-selection), [OpenRouter reliability/failover](https://openrouter.ai/blog/insights/reliability-failover/), [MiMo OpenAI API](https://mimo.mi.com/static/docs/api/chat/openai-api.md), [DeepInfra DeepSeek V4.1 Flash](https://deepinfra.com/blog/deepseek-v4-1-flash-deepinfra)

This review has not been written to `docs/reviews/router-cheap-maxima-design-2.md` (I stayed read-only); the text above is the verbatim content for that file.


## Author response for round 3

M1 fixed: preserve existing OPENCODE_ENABLE_EXA=1, explicitly classify its
credential-free non-model traffic outside the model bound, and require native
coverage of advertised search and the offline outbound attempt.
N1 fixed by archiving flag.ts, paths.ts and websearch.ts and describing remaining
.opencode discovery. N2 adds cache-write profile invalidation and a negative
test. N3 remains optional; no tokenizer-byte theorem is assumed. N4 makes the
environment allowlist and removal of the test managed-config override explicit.
No finding rejected. Claude tariff and gate-wall fixes have implementation
priority; this design remains a separately reviewed pending increment.
