# Diff review: router-small-claude (`45b89a5..5c99209`)

**Reviewer:** fresh goldfish, read-only. Personas: `zoom_out`, `implementation_readiness`. Mode: REVIEW. Standard: `implementation-readiness-standard.md`.
**Worktree:** `/Users/bugsincode/.t3/worktrees/unbug-bench/t3-afe2d824`, branch `t3/router-item8-prereqs`, HEAD `5c99209`.
**Reviewed against:** `docs/designs/router-small-claude.md`, `docs/reviews/router-small-claude-design-1.md` (FAIL, B1), `docs/reviews/router-small-claude-design-2.md` (PASS, M1–M3/N1–N5 accepted), and `docs/reports/router-small-claude-suite-20261031T135857Z-a5bc42a0.md`.

## Verdict: **PASS**

No blocker is open. There are no Major findings. There are five Nits.

## What I checked myself

**1. The $10 and $15 maxima are enforced and truthful**
- `route_maximum` returns exactly what the design specifies:
  - small: `10.0 / 50000000 / 500000`, with suffix `…joint-gate-v1:profile=small:usd=10`;
  - medium: `15.0 / 75000000 / 750000`, with suffix `…:profile=medium:usd=15`;
  - base: `50.0 / 250000000 / 2500000`, with its `price_source` unchanged (empty suffix).
- `claude/claude-opus-5-5:large` and `:Small` return `None`. Unknown or wrong-case aliases stay unbounded.
- Worst-case hold: 1,000,000 input tokens × $8/M + 32,768 output tokens × $20/M = **$8.655360**.
- The refusal check in `Allowance.reserve` (`factory/model_call_gate.py:181,186`) uses `settled + held + W + 0.000001 > max`. That gives settled-spend headroom of exactly **$1.344639** (small) and **$6.344639** (medium), and $41.344639 for base. These match the design.
- The design states plainly that the full $10 or $15 is not usable. The claims are truthful.
- A forged lease (alias route carrying base maximum fields) fails `valid_lease`, because `price_source` is compared exactly. `enforce` raises `unbounded_route`. A test covers this.

**2. Alias routing, CLI and accounting**
- `model_router.routes()`: the aliases are not in `CHAINS`, so the chain is `[alias]`. There is structurally no fallback to base.
- The `startswith('claude/')` checks keep the aliases on subscription billing, the Anthropic family, and account 2 first. Quota and credential handling is prefix-keyed too (`model_router.py:256`, `model_runtime.py:437`).
- `model_runtime._invoke` (`factory/model_runtime.py:546-547`) maps `--model` to `claude-opus-5-5`. `models_used`, `configured_model` and the route receipt keep the alias. Tests assert all of these.
- Effort selection (`model_effort`) is prefix-based, so it is unaffected.
- `claude_cost` (`factory/token_prices.py:135`) maps only the exact known aliases to base pricing. That closes the partial-receipt "unpriced alias" risk at `budget.py:920`, and the test asserts the estimate equals base.
- Request and response model checks in the gate (`model_call_gate.py:91,271,305`) and `ANTHROPIC_SMALL_FAST_MODEL` stay on the base ID, as the design requires.
- I swept every `GATED_CLAUDE`/`claude-opus-5-5` reference in `factory/`. Every other use is either base-ID equality on provider payloads or rotation/cutover JSON bindings, and the aliases are intentionally not added there (opt-in only). `--builder` is a free string (`run.py:3084`).

**3. Base compatibility**
- `CLAUDE_CALL_USD`, `GATED_CLAUDE`, `CLAUDE_CONTEXT` and `CLAUDE_OUTPUT` are kept.
- `claude_gate_maximum()` defaults to base. `claude_gate_cost` is unchanged.
- The base tests were widened (looped over all profiles), not weakened. Base remains one iteration of each loop, with identical assertions.

**4. Unknown attempts keep their hold after an interruption**
- `test_runtime_close_mid_response_retains_hold_once` now covers 3 profiles × 3 HTTP variants. Each case asserts:
  - the $8.655360 hold is retained once;
  - the reservation `maximum_usd` equals the profile cap;
  - the alias appears in the route receipt and `models_used`;
  - `--model` carries the base ID and the credential label is kept.
- The new alias test asserts: one unknown attempt → the next `reserve(0)` returns `None`, exhaustion is set, and `held_usd == 8.655360`.
- `test_successful_cli_cannot_hide_gate_unknown_usage_in_real_runtime_receipt` now loops over all profiles. Receipt maxima equal `route_maximum(model)`.

**5. Fixture evidence**
- I recomputed the counts from the committed fixtures:
  - 153 public-card receipts: **67** fit within $1.344639 and **132** within $6.344639;
  - paid-DeepSeek writers (envelope = max of recorded and re-priced cost): **25** total, **13** fit small, **24** fit medium.
- All of these match the design. I did not recompute the public-card per-writer 16/31 and 30/31.
- The two named writer events (`252e6df1…`: 35 calls, small; `0d4adf8f…`: 62 calls, medium) are looked up by identity, with role and call count asserted and `max(list_cost, gate_cost)` used. That satisfies design-2 N1.

**6. Tests**
- I re-ran the focused tests on `5c99209`:
  - `test_model_call_maxima.py`: 24 OK;
  - `test_model_router.py`: 41 OK;
  - `test_model_runtime.py`: 3 OK.
- The committed suite log's SHA-256 matches its record (`66415b49…248b`). The log shows the maxima module at 24 OK.
- As instructed, I did not re-run the full suite.

**7. Mutation reasoning (could the tests catch a broken implementation?)**
- Removing the `claude_cost` alias mapping makes `claude_cost(alias)` return `None`. Both the equality assertion and the partial-estimator test would fail.
- Removing the runtime `model_id` mapping fails the `--model` assertions.
- Reverting `enforce` or `Allowance` to singleton equality fails the alias interruption and serialization tests.
- Dropping the price-source suffix makes the forged-lease assertion fail.

**8. The claims are kept narrow**
- The design, suite record and commit all say:
  - the at-most-$5 item-8 target is not met;
  - no scenario is unblocked end to end;
  - no scenario cap is changed;
  - no Murphy row closes;
  - there is no live CLI, provider, TLS or account-2 acceptance.
- The diff does not touch `docs/murphy-register.md`. No overclaim was found.

## Findings

**N1 — Nit (zoom_out): unused import.** `factory/model_router.py:27` still imports `GATED_CLAUDE`, but `route_maximum` no longer uses it. Nothing else in `model_router` or the tests references `router.GATED_CLAUDE`. Drop it.

**N2 — Nit (readiness / test precision): the headroom boundary is tested on one side only.**
- `test_small_profiles_fit_real_writer_envelopes_and_retain_unknowns` (`tests/factory/test_model_call_maxima.py`) tests two points:
  - admission at real settled cost, which is well inside the headroom;
  - refusal at `cap − W`, which is $0.000001 over the headroom.
- It never admits at exactly `cap − W − HEADROOM`. An off-by-one in `HEADROOM` would only be caught if existing base tests cover that edge.
- The "zero unknowns permit another request" case also reserves only once over the settled history. It never validates a request and then reserves again. Both are acceptable as written but thin.

**N3 — Nit: "no base fallback" is proven by code structure, not by a test.** The test checks that the first `acquire` returns the alias on account 2. It does not exhaust both Claude accounts and assert that no base lease is offered. `routes()` makes fallback impossible today (the aliases are not in `CHAINS`), so this is coverage-only.

**N4 — Nit: the suite log has no provenance.** The log and its record carry no commit or tree hash. The record also says a test was corrected after the first focused run. So the record cannot by itself prove the 159/0 run was on `5c99209`. My focused re-runs on `5c99209` pass, which reduces the risk. Embedding `git rev-parse HEAD` and `git status --porcelain` in future logs would fix this.

**N5 — Nit (zoom_out, scope): the funding report is mostly off-topic and unverifiable.**
- `docs/reports/router-small-claude-funding-20261031.md` is mostly about OpenRouter credit, free-route availability and scenario caps, which is outside the Claude-profile change. It records authenticated read-only GETs that I could not check offline.
- The report is honest that it authorizes nothing and changes nothing. Treat its figures as unverified context, not evidence for this diff.

## Blocker fixes and regressions

- **Design-1 B1** (the withdrawn $5 no-cache plan) is resolved by the withdrawal. No no-cache code, request-count cap or new path exists in the diff.
- **Design-2 M1–M3** are reflected in the design's "Review 2 clarifications" and in the code: no extra seams were touched beyond the list, and outage health per lane is unchanged.
- No regressions found. Base lease fields, base `price_source`, gate payload checks and socket logic are unchanged.

## Scope limits of this review

- **Read-only.** No edits, no secrets read, no live inference or network calls, no push, merge or delegation.
- **No full-suite re-run.** I rely on the committed log plus the focused re-runs of the maxima, router and runtime modules.
- **Not verified:** the funding report's OpenRouter figures, and the public-card per-writer counts (16/31, 30/31).
- **Not established by this diff or this review:**
  - live writer or strong-calibrator success under `:small` or `:medium`;
  - real request-size validity;
  - account-2 acceptance;
  - TLS or worker cancellation;
  - closure of any Murphy row (including 9/39);
  - progress on the item-8 at-most-$5 target.

## Implementer disposition

PASS accepted; no blockers or major findings. Optional N1–N3 are deferred to
keep the reviewed and full-suite-tested implementation unchanged. N4: the suite
ran on the uncommitted implementation subsequently committed as 5c99209; no
production or test edits occurred between that run and the commit. This is an
implementer provenance statement, not evidence retroactively embedded in the log.
Future suite records should capture source hashes before execution. N5: funding
was an explicit founder-requested read-only check; its amounts are point-in-time
observations, not offline-verifiable evidence for Claude enforcement. No row
closes and no live or at-most-$5 acceptance is claimed.

