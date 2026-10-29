**BLOCKED**

I reviewed the documents and code only; I made no edits and ran no factory code. I judged the design against the parent's contract: A merges with unit tests, D owns reservations and settlement, B owns lifecycle, row 20 and the end-to-end closure test. Under that contract most prior findings are resolved. One blocker remains, plus two majors.

## Blocker

**B1. The route chains for MiniMax, MiMo, Muse and GLM are never stated, so the implementer would decide which billing lane each one uses.** (`docs/designs/router.md:46-56` and `:173`)
- Line 173 deletes `PROVIDER_ROUTES` and `FREE_FALLBACK`. Line 52 then says these four families use "the already-approved same-family routes in model_runtime/rotation config". Today those two tables are the only routes in `model_runtime`, so the design deletes the routes it points to.
- Today's behaviour depends on them (`factory/model_runtime.py:27-33`):
  - MiniMax always goes to `openrouter/minimax/...:free`.
  - MiMo always goes to paid OpenRouter, which draws on the shared wallet.
  - GLM falls back to paid `opencode-go`.
  - Muse has no route in `model_runtime`.
- The founder note in `rotation-3writers.json` (`routes_note`) says "OpenCode Go first for MiMo and Muse; OpenRouter backup". `free_models.provider_config` special-cases native MiniMax on Go.
- Nothing says whether MiniMax now tries native first, or whether MiMo goes native Go first and then paid OpenRouter. Each choice decides whether a call spends OpenRouter wallet money and shares the wallet-wide 402 block. That is a money-routing decision, and it is left to the implementer.
- **Required:** a literal chain table. For each requested model, list the ordered effective routes and each route's billing kind and capacity pool (account or wallet). Cite the founder authority for each order. Add a test that each chain is valid as data: one family, the right billing kind and pool, and paid routes priced in `token_prices`. `family()` already maps every native/OpenRouter pair correctly; I checked all three.

## Majors

**M1. The `provider_wait.json` record has no lifecycle, and existing broad catches can swallow the raise.** (`router.md:136-145`)
- `early_probe` catches every `Exception`, `BudgetError` included (`factory/run.py:2101`). A provider wait there would write the record and raise, the probe would mark itself skipped, and the case would carry on with a stale record. That record then sits in every later checkpoint.
- Nothing removes the record after a relaunch. Concurrent roles (the G10 calibrators, and `gate_pipeline.py:184`) can each write the same file, and the last write wins the `retry_after`.
- **Required:**
  - Either write the record only on the main stop path (the `except (BudgetError, PauseRequested)` block at `run.py:~2590`), or state that optional callers (`early_probe`) re-raise `provider_wait`.
  - Delete the record once the next call is admitted after a resume.
  - For concurrent waits, define the merge as the latest `retry_after`, with `interrupted` winning over `denied_before_work`.
  - Test these cases.

**M2. The Codex credential source changes, but the path is not named.** (`router.md:106-107`)
- The design says "reads the currently installed RAM Codex credential source". Today `_invoke` reads `CODEX_HOME` or `~/.codex/auth.json` (`model_runtime.py:299`).
- Name the exact file, presumably `/dev/shm/secrets/codex-auth.json`, and what happens when it is missing (`credential_expiring` leading to `provider_wait`). Add the path to `interfaces.md` so that B's delivery and A's reader agree. If no change is intended, say "unchanged".

## Nit

**N1.** Row 3 can close only with a real paid-artifact test that shows the wallet-wide 402 denial. None of the saved fixtures contains a 402: the eight limit cards are Muse, MiMo and Claude, and the two DeepSeek cards are successful paid runs. Say up front that row 3 most likely stays partial.

## Prior findings under the contract

**Review 1:**

| Finding | Status |
|---|---|
| #1 Waiting | Resolved: short sleeps with a heartbeat, a checkpoint after 60 seconds, counters moved to D. |
| #2 Scope | Resolved by `interfaces.md` merge order. Rows 2, 4, 20, 47 and 48 are honestly left open. |
| #3 Handoff | Resolved: blacklist deleted, `choose` becomes a router query, transport kept for B. |
| #4 Capacity | Resolved: the router owns capacity, and coordinator/inventory account scheduling is deleted. |
| #5 Tokens | Resolved: labels pinned, exam token and label 3 excluded, one token per worker. |
| #6 Connectivity | Resolved: TLS bind, `router.env`, B delivers the token. |
| #7 Mode flag | Resolved: no production bypass. |
| #8 Classification | Resolved: table at lines 115-121, refusal limit, preflight rule, finite lease. |
| #9 Lane capacity | Resolved. |
| #10 Restart counts | Moved to D, and `restart` recognises the deferral. Acceptable. |
| #11 DeepSeek | Resolved: native route is a probe, paid ledger evidence used, family checked. Superseded by B1 for the other families. |
| #12, #13 | No action. |

**Review 2:**

| Finding | Status |
|---|---|
| #1 B prerequisite | Resolved: B is explicit in the merge order and rows stay open. |
| #2 Reservations | Resolved under the contract: D owns them, and A supplies the `denied_before_work` / `interrupted` evidence and keeps usage. |
| #3 Router unavailable | Resolved: lines 29-31 and 94-96. |
| #4 Codex renewal | Moved to B. What remains for A is M2. |
| #5 Classification | Resolved: structured `provider_failure` from the parser, and refusal coverage reported as partial. |
| #6 One-token transport | Resolved under the contract: B owns installation hygiene and A claims nothing about it. |
| #7 Identity and leases | Resolved: separate call and attempt IDs, UTC epoch on the wire, one lease formula, non-executed release. |

## Verdict: **BLOCKED**

B1 is the only blocker, and fixing it is a short table. M1 and M2 should be fixed in the same revision.


## Elephant response

B1 fixed with literal ordered chain/billing/pool/authority table; no fixed API prices invented. M1: record writing is only main stop path, optional probes rethrow, concurrent waits merge with latest retry/interrupted precedence and aggregate receipt; D archives settled waits before admission. M2: exact RAM source named. Latest parent contract adds rollout flag, parent_generation, wait/lease IDs and idempotent settlement receipts; incorporated. Row3 remains partial because real public 402 evidence is absent. Fresh review requested, no findings rejected.
