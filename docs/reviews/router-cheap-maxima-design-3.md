**PASS.** M1 is resolved, the new wording hangs together, and there are no new Blockers or Majors. Three optional Nits are below. I stayed read-only (no edits, tests, launches or secrets), so the file isn't saved yet. The text below is the verbatim content for `docs/reviews/router-cheap-maxima-design-3.md`.

---

**Verdict: PASS.** No Blockers, no Majors, 3 Nits. Nothing stands in the way of implementing this design. Implementation is still pending behind the Claude tariff and gate-wall fixes, and no merge or launch is authorized.

Scope: the uncommitted section "Cheap-route enforced maxima", `docs/designs/router.md:850-1083`, plus `router-cheap-price-records.json.gz` and `router-cheap-source-evidence.json.gz`, in worktree `t3-b7dfac7a` at `cb434e3`. Mode REVIEW, read-only. The Claude tariff and gate-wall sections, and their Murphy rows, are out of scope. I read reviews 1 and 2 and both author responses. Round 2 accepted all bounds, the arithmetic and the real-receipt budget fits, so I did not recompute them.

## What I checked and found correct

**Round-2 M1 is resolved (`router.md:1044-1063`).**
- The design keeps `OPENCODE_ENABLE_EXA=1` "exactly as the existing OpenCode path does". That matches `model_runtime.py:522`, which sets it for every OpenCode role, writers and stress testers included.
- It states that Exa is credential-free non-model traffic that sits outside the lease's model money bound. It also says this does not authorize a hosted model search tool or expose the OpenRouter key.
- Native validation now requires three things:
  - `websearch` stays in the writer and stress-tester tool lists;
  - a synthetic tool call runs with the network disabled and records where it tried to connect;
  - no other paid inference request is made, and the real credential is never sent.
- So the implementer no longer has to choose, and the capability is pinned by a test. M1 is closed.

**Round-2 N4: the environment wording is now coherent.**
- The environment is rebuilt from exactly: PATH, HOME, LANG, LC_ALL, TMPDIR, the three fresh XDG paths, `FACTORY_STRATEGY_*`, and the OPENCODE settings the code sets, including EXA.
- `OPENCODE_TEST_MANAGED_CONFIG_DIR` is dropped explicitly.
- This settles the old conflict between "no inherited OPENCODE variables" and the variables the design sets itself.
- The allowlist also drops `OPENCODE_WEBSEARCH_PROVIDER` and `PARALLEL_API_KEY`. In the frozen `websearch.ts:34-40`, that leaves the Exa flag selecting Exa unless the Parallel runtime flag is set. That flag's source (RuntimeFlags) is not archived (see N3).

**Round-2 N1: the evidence is frozen.**
- `flag.ts`, `config/paths.ts` and `tool/websearch.ts` are now in the source-evidence fixture. All 11 entries reproduce their SHA-256, including both excerpt hashes.
- `flag.ts` defines `OPENCODE_PURE`, `OPENCODE_DISABLE_MODELS_FETCH`, `OPENCODE_DISABLE_AUTOUPDATE` and `OPENCODE_DISABLE_PROJECT_CONFIG` (read at access time).

**Round-2 N2: cache-write is covered.** A record with any nonzero `input_cache_write` invalidates the profiles, and a negative test is required (`router.md:1065-1067`).

**Round-2 N3: not adopting the byte cap is acceptable.** The finding was explicitly defence-in-depth, and the design adds no new tokenizer assumption.

**No new money path.**
- `OPENCODE_CONFIG_CONTENT` still merges last (frozen `config.ts:482-490`).
- The real key stays only in the gateway.
- The added environment keys carry no provider credential.

## Nits

**N1. The `.opencode` discovery sentence describes more than the frozen source shows.**
- `router.md:1054` says ".opencode directory discovery still occurs". Frozen `paths.ts:directories` skips the project/worktree `.opencode` walk when `OPENCODE_DISABLE_PROJECT_CONFIG=1`.
- What remains is `Global.Path.config` (the fresh XDG directory), `$HOME/.opencode`, and `OPENCODE_CONFIG_DIR` (unset).
- Say "only the worker user's `$HOME/.opencode` is still discovered". The safety argument does not change.

**N2. "OPENCODE_PURE prevents its external plugins" has no frozen source behind it.**
- The frozen files only define the flag. The code that consumes it (the plugin loader) is not archived.
- Frozen `config.ts:452-470` also starts a background `npm install @opencode-ai/plugin` for every discovered directory, whether or not PURE is set. That is credential-free, non-model and fails offline.
- Either archive the code that consumes PURE, or let Validation item 4's outbound capture prove it. In both cases, list the npm install alongside Exa as allowed non-model traffic.

**N3. Have the search test assert the Exa endpoint.**
- Validation "records" the attempted non-model destination but does not check it. The RuntimeFlags source that decides `enableParallel` is not archived.
- If search went to Parallel instead, it would silently pass today.
- Assert that the destination is `McpWebSearch.EXA_URL` (credential-free), and fail on anything else.

(Wording only: the clarification at `router.md:1044` is labelled "Round-2" but answers review 2's findings in round 3. Harmless.)

## Prior findings

| Finding | Status |
|---|---|
| R1 M1–M4, N1–N3 | Fixed (confirmed in round 2) |
| R2 M1 (EXA) | Fixed |
| R2 N1 (frozen flag/paths/websearch, .opencode) | Fixed; wording refinement N1/N2 above |
| R2 N2 (cache-write) | Fixed |
| R2 N3 (byte cap) | Not adopted, accepted as optional |
| R2 N4 (env allowlist, managed override drop) | Fixed |

No findings were rejected. No implementation exists yet. The paid routes stay disabled until the diff review and the native proof pass.


## Author response

PASS recorded. Optional nits addressed: corrected remaining $HOME/.opencode
discovery, archived the PURE consumer and RuntimeFlags, named npm's allowed
non-model attempt, and required the exact Exa destination assertion. No finding
rejected. Implementation remains after the prioritized Claude fixes.
