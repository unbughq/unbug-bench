# Fresh goldfish design review: `docs/designs/router-item8-route-profiles.md` (round 2)

**Verdict: FAIL.** There is 1 blocker and 5 majors.

**Setup:**
- **Mode:** REVIEW.
- **Personas:** zoom_out, design_critic, implementation_readiness.
- **Standards:** heilmeier-standard.md, implementation-readiness-standard.md, docs/ENGINEERING.md.
- **Worktree:** `t3-afe2d824`, branch `t3/router-item8-prereqs`, HEAD 351fb51. The worktree has no code changes; only the new design, report, review and fixture files are untracked.
- **Scope:** the Claude Opus 4.5 `:compact`/`:small` aliases and the bounded MiniMax profile only. Codex is deferred in full. This increment does not claim to finish all item-8 prerequisites.
- **What I did:** read-only. No edits, secrets, provider or model calls, web fetches or child agents. The only things I ran were offline arithmetic and the existing `token_prices` functions.

**Read:**
- The three persona files and the design.
- Review 1, in full.
- `docs/reports/router-item8-funding-20261031.md`.
- All three new fixtures, decompressed:
  - `router-item8-claude45-cli.json.gz`
  - `router-item8-minimax-endpoints.json.gz`
  - `router-item8-source-evidence.json.gz`
- `router-maxima-cli-audit.json.gz`, to compare the binary SHA.
- `factory/token_prices.py` (all of it).
- `factory/model_call_gate.py`: lines 20–672, covering the request, usage, allowance, OpenRouter body/usage, handler and enforce code.
- `factory/model_router.py`: lines 25–130.
- `factory/model_runtime.py`: lines 141–142, 535–575 and 616.
- `factory/rotation-3writers.json`.
- `docs/designs/stream-d.md`: the item-8 role map, lines 3540–3560.

## Independent verification of review 1's corrections

| Item | Design value | My recomputation | Result |
|---|---|---|---|
| MiniMax worst request | 0.29097984 | 524288×0.28/1M + 131072×1.1/1M = 0.29097984 | Matches |
| MiniMax max_usd (3 windows + .000001, ceiling to 9 places) | 0.872940520 | 0.872940520 | Matches |
| MiniMax max_input / max_output | 3117644 / 793582 | int(Decimal) of 872940.52/0.28 and /1.1 gives 3117644 / 793582 | Matches the existing `openrouter_gate_maximum` formula |
| MiniMax fixture inputs | .28/.056/1.1; context 524288; output 131072 | Entry tagged `deepinfra/fp8` has prompt 2.8e-7, cache_read 5.6e-8, completion 1.1e-6, discount 0, same context/output | Matches |
| MiniMax flex sibling | "cheaper, same bounds" | `deepinfra/fp8/flex`: .224/.0448/.88, context 524288, output 131072 | Matches; max_price stays an upper bound |
| Claude worst hold | 2.409600 | 200000×10/1M + 16384×25/1M = 2.4096. The `reserve` method puts the full context at the dearest of the three input rates | Matches |
| Claude headroom | 0.590399 / 2.590399 | 3 or 5 − 2.4096 − 0.000001 (HEADROOM) | Matches |
| Claude input/output maxima | 6M/10M; 120000/200000 | USD×1M/min(5, .5, 10) and USD×1M/25 | Match |
| Existing DeepSeek maximum | **1.174406121** | `openrouter_gate_maximum` returns **1.17440612** | **Does not match** (finding 2) |
| Pinned CLI SHA | "matches previous capture" | `ba5ab7b8…44b3` is also in `router-maxima-cli-audit.json.gz` | Matches |
| `MAX_THINKING_TOKENS` added to ENV_KEYS "for sudo" | — | ENV_KEYS feeds `sudo --preserve-env` at `model_runtime.py:616` | Justified. The reason to remove the inherited value on old profiles holds |
| Review 1 major 2 ($11.63 total) | B3 launch blocker | Lines 36–42 say dispatch is not authorized and claim no proving test | Addressed as a stated blocker, not as a proof |
| Review 1 majors 3/4 (Codex) | Deferred in full | Lines 131–136; no Codex code in the file list | Addressed |
| Review 1 major 5 (thinking/env) | Fixed contract | The probe shows `max_tokens` 16384, thinking enabled with budget 8192, effort high, and BETAS exactly equal to `model_call_gate.BETAS` | Addressed for the single probed request (see finding 5) |

## Blockers

**1. The MiniMax route does not attach to any saved MiniMax role, and the design never says it is a model substitution.**
- **Scope:** Problem (lines 10–11), Funding (lines 46–48), Routes item 2 (lines 74–89).
- **What the code says:**
  - `factory/rotation-3writers.json` binds the MiniMax family to `opencode/minimax-m3.1-flash-free`.
  - `model_router.CHAINS` maps that model only to `openrouter/minimax/minimax-m3.1-flash:free`.
  - The stream-d role map (lines 3546–3549) asks for "approved free-route maxima" for scenarios 1–3.
- **Where M3 comes from:** no document or code selects `minimax/minimax-m3` (M3, not M3.1 Flash). I searched `docs/designs` and `docs/reports`; the only hits are this design.
- **What follows:**
  - `routes('opencode/minimax-m3.1-flash-free')` will never return the new route.
  - So the claim that "MiniMax … selected routes lack maxima" (line 10) is not what this increment bounds.
  - The claim that scenarios 1–3/6 "need paid MiniMax" works only if B3 rebinds the role to a different model.
  - The Claude section states that model change explicitly (lines 19–21: newly bound manifests only, and B3 checks candidate compatibility). The MiniMax section has no equivalent.
  - The design also promises "without changing saved candidate bindings" (line 14).
- **Why it blocks:** whether, when and how to replace the saved MiniMax model with a different one is a science/fairness decision. It would currently fall to the implementer or B3, by inference.
- **Fix:** state explicitly that `openrouter/minimax/minimax-m3` is a different model from the saved binding, used only in newly bound manifests under the same B3 compatibility check as Claude, with the role-family rationale. Also either:
  - give source-backed reasons for not bounding a paid route of the same M3.1 Flash model. Whether such an OpenRouter endpoint exists is **missing**: I made no calls and nothing saved shows it. Or
  - switch the profile to that same model.

## Majors

**2. The existing DeepSeek maximum is misquoted.**
- **Scope:** line 88.
- The design says "Existing DeepSeek route maximum1.174406121 stays unchanged".
- The unchanged code returns `max_usd=1.17440612`, with `max_input_tokens` 8388615 and `max_output_tokens` 2796205: 2×(1048576×.14 + 1048576×.42)/1M + .000001 = 1.174406120.
- `valid_maximum` compares exactly, and B3 is meant to copy the numbers this document reports.
- **Fix:** quote 1.17440612. Make the final manifest report quote the code-derived values, not prose.

**3. The response-side Opus 4.5 geo/tier contract is missing, and the geo claim has no source.**
- **Scope:** lines 117–119, plus `claude_standard_usage` in `token_prices.py`.
- **The unsourced claim:** "omit inference_geo on Opus4.5 (the geo selector applies to4.6+; first-party default is global)". The source-evidence fixture has no record for it.
- **What the gate does today:** `Usage.merge` marks a response invalid unless `usage.inference_geo` is absent or `'global'`.
- **What the probe shows:** the CLI's own final usage reports `"inference_geo": ""`. The fixture does not save the synthetic SSE response, so I cannot tell whether that came from the upstream body or is a CLI default.
- **Why it matters:** if real Opus 4.5 responses carry `""` or another non-global value, every request settles as unknown. One unknown retains $2.4096, so `:compact` exhausts after one call and `:small` after two. This fails closed, so no money is at risk. But the implementer must choose between keeping the strict rule and accepting `""`, and that is a design decision.
- **Fix:**
  - State the rule: keep accepting only absent or `'global'`; any other value, `""` included, counts as unknown.
  - Record this as a live-acceptance risk.
  - Add a public source record for the 4.6+ geo-selector claim, or mark it **unproved**.

**4. Whether Opus 4.5 is still offered (deprecation/retirement) is not in the source evidence.**
- **Scope:** Source contracts (lines 93–97), and the main risks (line 147: "legacy Claude availability").
- **What is there:** the support article excerpt shows the model ID is listed for Claude Code model selection.
- **What is missing:** no record of the model's deprecation or retirement status as of 2026-10-31. Today's date is about 11 months after the model's release.
- **Fix:** freeze the public model-deprecations status in `router-item8-source-evidence.json.gz` before implementation. If a retirement date falls inside the qualification window, revise the design rather than ship a route that cannot be used.

**5. The Claude CLI evidence is one single-turn request shape, and the implementer has to rebuild the request to "replay" it.**
- **Scope:** lines 120–124 and the planned "captured CLI shape replay" in the new test file.
- **What the fixture holds:** `shapes` has one entry ("Return OK."). It lists field names, `max_tokens`, the thinking block, effort, beta and tool names.
- **What it does not hold:**
  - the raw request body, system prompt or message content;
  - the synthetic response stream;
  - a second turn, i.e. a tool_use → tool_result round with a signed thinking block replayed (which `_content` allows);
  - any small-fast-model side call.
- **The consequence:** "Replay that shape through the real gate tests" means reconstructing a request from a summary. That is the fabricated test request that line 124 warns against.
- **How serious:** this matches the precedent in `router-maxima-cli-audit.json.gz`, which is also shape-only, and a mismatch fails closed before upstream. So it does not block.
- **Fix:** say explicitly that multi-turn, tool-loop and side-call shapes are **unproved** and are accepted as live risk. Or add a two-turn synthetic, network-denied capture that saves the request and response bytes.

**6. The MiniMax wire contract is assumed from other models, not proved for this one.**
- **Scope:** OpenRouter section (lines 126–129).
- **(a) Response model ID.** `OpenRouterUsage.event` requires `event['model'] == 'minimax/minimax-m3'`. The saved endpoint names carry `minimax/minimax-m3-20260531`. Nothing saved shows which ID the response carries. A mismatch makes every paid call unknown at the full hold of 0.29097984, counted against the $11.63.
- **(b) Request parameters.** `require_parameters=True`. The DeepInfra fp8 `supported_parameters` list leaves out `reasoning_effort`, `stream_options` and `usage`. What the pinned opencode client sends for this model with `effort: default` has not been captured.
- **(c) Vague wording.** "Check the saved endpoint for supported parameters … before admission" does not say whether that is a runtime check or a test-time assertion.
- **Fix:** state (a) and (b) as **unproved**, and either cover them with a synthetic opencode capture or accept them as live risks. Make (c) a named test assertion against the fixture.

## Nits

**7. The source excerpts are rewritten, not verbatim.**
- The pricing excerpt's column order (input, output, 5m, 1h, read) is not the published table's order, which ends with output.
- Retrieval was by web tool after a 403.
- The hash therefore proves only the stored string, not the page. The design already says "excerpt hashes, not raw-page hashes"; label the excerpts as normalized as well.
- The values themselves are consistent with the standard multipliers: 5m write 1.25×, 1h write 2×, read 0.1×.

**8. The paid-dispatch refusal is procedural, not enforced in code.**
- Once `openrouter/minimax/minimax-m3` is added to `GATED_OPENROUTER`, `route_maximum` returns a value, so a valid paid lease is possible on an unlimited key.
- State that the refusal rests on there being no item-8 launch path or manifest, and on B3's gate. That is the same exposure DeepSeek and MiMo already have.

**9. B3's compatibility check should include effort.**
- `model_runtime._invoke` takes `effort` from the card role, which overrides `model_effort`.
- A candidate whose Claude role effort is `xhigh` or `max` would have every Opus 4.5 request rejected.
- Today's rotation sets `high`.

**10. Leftover Codex wording.**
- Line 147's main risks still list "Codex protocol compatibility".
- Lines 153–154 still mention Codex timing.
- Harmless, but the increment should read as Claude/MiniMax-only.

**11. Probe platform.**
- The probe ran under a macOS `sandbox-exec` policy. Production workers are Linux.
- The SHA matches the prior audit binary. Say explicitly whether the Linux binary's request shape is assumed identical.

## Strengths (no action needed)

- Review 1's MiniMax arithmetic correction is right in all four fields and follows the existing formula exactly.
- Codex is cleanly deferred.
- The $11.63 total is honestly framed as a B3 launch blocker; no test is claimed to prove it.
- The Claude env/thinking/effort/beta contract is now specific, and the one probed request agrees with it.
- The two aliases are justified by allocation.
- The file list is concrete.
- No Murphy row is closed.

**Result: FAIL.**
- **Blocker 1** (the MiniMax route is an unstated model substitution with no binding rule) must be corrected and re-reviewed by a fresh goldfish.
- **Majors 2–6** should be corrected, or explicitly accepted as unproved risks, in the same revision.


## Implementer disposition (pending fresh review)

All findings accepted. Switched proposed M3 to public paid M3.1 Flash same-model
route, with explicit new-manifest binding rule. Corrected DeepSeek quote; added
strict response geo rule/lifecycle sources; captured full two-request synthetic
Claude wire traffic; named MiniMax fixture assertions and remaining live risks.
Normalized source excerpts/platform limitations explicitly labelled. No finding
rejected. Fresh goldfish must verify the blocker correction.
