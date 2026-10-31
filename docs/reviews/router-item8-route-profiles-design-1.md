# Goldfish design review: `docs/designs/router-item8-route-profiles.md` (round 1)

Mode: REVIEW. Personas: zoom_out, design_critic, implementation_readiness. Standards: heilmeier-standard.md and implementation-readiness-standard.md.

What I read, read-only, in worktree `t3-afe2d824`, branch `t3/router-item8-prereqs`:
- `docs/ENGINEERING.md`
- the design
- `docs/reports/router-item8-funding-20261031.md`
- `tests/factory/fixtures/router-item8-minimax-endpoints.json.gz`
- `factory/token_prices.py`
- `factory/model_router.py`, lines 1–120
- `factory/model_call_gate.py`, the parts that check Claude and OpenRouter requests, the allowance, and the environment
- `factory/codex_login.py`

I made no provider calls, read no credentials and made no edits. I did not use the public source pins (Claude/OpenAI docs, Codex rust-v0.162.1). Where a finding depends on them, I say whether proof is **missing** or the parts are **shown not to fit**.

**Verdict: FAIL.** There is 1 open blocker.

## Recomputed maxima

| Route | Design value | My recomputation | Result |
|---|---|---|---|
| Claude Opus 4.5 worst hold | $2.409600 | 200000×10/1M + 16384×25/1M = 2.4096 | Matches |
| Claude headroom | $0.590399 / $2.590399 | $3 or $5 − 2.4096 − 0.000001 safety margin | Matches |
| Claude input/output limits | 6M/10M; 120000/200000 | — | Match |
| Codex Luna worst hold | $0.3585 | 1050000×.25/1M + 128000×.75/1M | Matches |
| Codex input/output limits | 4M/20M; 1333333/6666666 | — | Match |
| MiniMax worst request | $0.2916352 | $0.29097984 | **Does not match** (blocker 1) |

## Blockers

**1. The MiniMax maximum is wrong, and the design contradicts itself.**
- **Scope:** Routes and maxima, item 2 (lines 63–68).
- **Inputs:** the stated prices (.28 / .056 / 1.1 USD per million) match the saved fixture entry with tag `deepinfra/fp8` (prompt 0.00000028, completion 0.0000011, context 524288, max_completion 131072).
- **Correct numbers:** with those inputs, the worst request is 524288×0.28/1M + 131072×1.1/1M = **0.29097984**. The `openrouter_gate_maximum` formula the design says to reuse (3 windows plus .000001) then gives **max_usd = 0.872940520**.
- **Design numbers:** the design states .2916352 and .8749066. Its worst figure is what an output price of 1.105 would give.
- **Why it blocks:** `valid_maximum` compares every field exactly. So either:
  - the code follows the formula and the design's stated maximum, the number B3 is told to use, is wrong; or
  - someone hardcodes the design's number, and the stated tariff no longer produces it.
- Item 8 exists to give honest maxima, so the headline number must be exact.
- **Fix:** restate the worst request as 0.29097984 and max_usd as 0.872940520. Also state the derived limits: max_input_tokens = floor(0.87294052e6/0.28) = 3117644, and max_output_tokens = floor(0.87294052e6/1.1) = 793582. Then a test can pin all four fields against the fixture.

## Majors

**2. Nobody enforces the $11.63 total across all releases.**
- **Scope:** Funding and scenario contract (lines 31–38) and Deletions (lines 152–154).
- **The gap:** the design requires paid spend across all seven scenarios and all releases to stay at or below the lower of $11.63 and account credit. That covers settled, pending and unknown spend, and must be checked before every paid dispatch. But the design says "add no ledger", gives the job to "B3's manifests", and admits that a per-invocation cap does not enforce the total.
- **Why it matters:**
  - The OpenRouter key has no limit (`limit=null`), so the only hard stop is the account balance running out.
  - When that happens mid-run, it shows up as a provider error, not as a clean "authority exhausted" stop.
  - Concurrent paid dispatches across scenarios need one shared atomic reservation. Checking manifests one at a time cannot give that.
- **Missing proof:** I have not shown that the existing cumulative bound cannot do this job. But the design does not name which component does it. Candidates are `batch_money.py` ("Manifest-bound cumulative job authority") and stream B's money channel.
- **Fix:** name the existing component and its test that enforces the release-wide paid total, including pending and unknown spend, under concurrency. Otherwise state that paid OpenRouter dispatch for item 8 is refused until B3 lands that enforcement. "Reserve before dispatch; stop/wait" then needs an owner.

**3. The Codex route bundles a new transport and a credential move, and too much is left open.**
- **Scope:** Codex (lines 121–144).
- **The scale:** this is not a profile addition. It is a new gate that relays a ChatGPT-subscription bearer token held in RAM to `chatgpt.com/backend-api/codex/responses`. Several choices are left to the implementer:
  - **(a) Auth mode.** The design says to replace scratch `auth.json` with a synthetic gate bearer. Today `codex_login.worker_auth` keeps a real token whose expiry is checked from its JWT, and the pinned CLI reads JWT claims from it (the account ID, and `exp` for the refresh window). The design does not say whether:
    - the custom provider uses `env_key` (then no `auth.json` is needed at all), or
    - it uses ChatGPT auth (then the synthetic bearer must be a JWT the CLI accepts, with stated claims, and must not trigger a refresh).
  - **(b) Upstream token lifetime.** The design does not say that the token kept in RAM is checked with `codex_login.validate` over the gate's lifetime, or that a 401 from upstream counts as an infrastructure failure and never as a refresh.
  - **(c) Headers.** The forwarded and stripped request headers are not listed. "Only required subscription account header" leaves out `OpenAI-Beta`, `originator`, `session_id` and others.
  - **(d) Streaming.** "Full stateless POST responses" (line 122) conflicts with "truncated streams" (line 129). The design should state that SSE is required or allowed, and how many terminal events there must be.
- **Fix:** pin each of (a)–(d) in the design.
- **Phasing:** split Codex into its own increment and review. Claude and MiniMax are profile extensions of an existing gate; Codex is new transport plus moved credentials. Under the readiness standard, each phase must leave the code stable and testable. With all three in one increment, a failure in the Codex contract blocks the two low-risk routes, even though line 160 rightly says such a failure means revising the design.

**4. The Codex input allowlist probably rejects multi-turn requests, and the planned probe would not catch it.**
- **Scope:** lines 125–127 and 141–143.
- **The gap:** "Validate model, text-only input and local call/result shapes" does not cover reasoning items that the CLI replays.
- **Why it probably breaks:** with `store=false` and stateless turns, recent Codex CLIs request `reasoning.encrypted_content` and send reasoning items back on the next turn. This comes from what I know of public Codex source; I did not verify it against rust-v0.162.1, so proof is missing rather than a conflict shown.
- **Why the probe misses it:** the planned admission probe has the CLI consume a single synthetic terminal response. That never exercises turn 2.
- **Fix:**
  - Make the probe at least two turns, with a function call, its result, and a reasoning item.
  - Enumerate the allowed input item types.
  - State what happens to `GET {base_url}/models`, and any other non-POST calls the CLI makes, under "only POST responses".

**5. The Opus 4.5 thinking budget and the 16384 output limit may reject every request.**
- **Scope:** Claude section (lines 107–114) and item 1 (line 51).
- **The gap:** the gate lowers `max_tokens` to 16384 using `min()`, as the existing `request_body` does with `CLAUDE_OUTPUT`. The design accepts thinking only when `budget_tokens` is below the lowered `max_tokens`.
- **Why it may break:** if the pinned Claude Code sends its usual thinking budget (often far above 16k) with a larger `max_tokens`, then after lowering, `budget_tokens >= max_tokens` and every request is rejected.
- **What is undecided:** the design does not say whether to:
  - set `CLAUDE_CODE_MAX_OUTPUT_TOKENS` or `MAX_THINKING_TOKENS` in the profile environment, or
  - lower `budget_tokens` in the gate, or
  - reject.
- The capture step finds this, but the fix is a design decision the implementer would then have to make.
- **Also unstated:**
  - why the limit is 16384, when the existing Opus 5.5 limit is 32768;
  - whether `output_config.effort` values (`xhigh`, `max` are allowed today) are limited per profile;
  - whether `ANTHROPIC_SMALL_FAST_MODEL`, which is hardwired to Opus 5.5 in `model_call_gate.py:658`, becomes the profile model.

**6. Pinning MiniMax to `deepinfra/fp8` may not reach just one endpoint.**
- **Scope:** item 2 (line 61) and OpenRouter (lines 116–119).
- **The gap:** the saved fixture lists two DeepInfra fp8 endpoints, tagged `deepinfra/fp8/flex` (service_tier flex, cheaper) and `deepinfra/fp8`. The existing pin is `provider.only=['deepinfra/fp8']`. Whether OpenRouter treats that as an exact tag or a prefix is unproved.
- **Money risk:** none. Flex is priced lower and has the same limits, so the maximum stays an upper bound.
- **Remaining risk:** the service tier and reliability are not fixed, and a live result could come from a different tier than the one the evidence describes.
- **Fix:** state the exact pin semantics. Either assert the endpoint or provider in the response, or explicitly accept both tags and record that.

**7. The readiness standard's file list is incomplete.**
- **Scope:** Source contracts and implementation, and Deletions.
- The following are left vague:
  - "Delete singleton-model assumptions where needed". The known sites include the `GATED_CLAUDE` uses at `model_call_gate.py:91, 170, 271, 305, 658`, `empty_usage`, `enforce`, and `claude_gate_maximum`'s `price_source`.
  - The source-evidence fixture's filename.
  - The test file paths.
  - Where the new Codex codec lives.
- **Fix:** list each file to create or modify and each test file. The "Final offline tests" list is good on behaviour but is not tied to files.

## Nits

**8. The scenario role map has no source.** Lines 40–46 say scenarios 1–3/6 need MiniMax, 1–3/5–7 need DeepSeek, and only 4 runs on subscriptions alone. These claims drive the funding limits. Cite the role-map file or commit they come from.

**9. Two aliases per route are not justified.** `:compact` and `:small` are added for both Claude and Codex. Show which B3 allocations each one serves, or drop one.

**10. The small Claude profile leaves little room for work.** A `$3 :compact` Claude profile with a $2.4096 hold allows about $0.59 of settled work before it is exhausted. The design rightly makes no quality claim. Still, the "envelope analysis" of saved real cards should report how many requests each profile allows, so B3 does not bind a profile that cannot finish a turn.

**11. The window count for MiniMax is unexplained.** "three windows" is unexplained for MiniMax (MiMo uses 3, DeepSeek uses 2). Give the reason in one line.

**12. "One implementation/review session" is optimistic** for three codecs, including a new Codex gate. Split timelines if majors 3 and 7 are taken up.

**13. "Context 200000" should name the beta-header rule.** Say that the gate rejects any 1M-context beta header, or other context-extension header, on this profile.

## Strengths (no action needed)

- The design does not reduce Opus 5.5's maximum by estimate, and it leaves the existing aliases unchanged.
- No zero-price route is admitted, and failing to fit the source or the CLI forces a design revision instead of an invented maximum.
- Unknown attempts keep the whole hold. Live acceptance is kept separate from offline maxima, and scenario limits are stated honestly.
- The funding audit is careful:
  - it changed nothing;
  - it correctly flags that a literal $11.63 lifetime cap would exhaust the key immediately;
  - its arithmetic is right: 31.494136472 + 11.63 = 43.124136472.
- Saying that no Murphy row closes is consistent with `ENGINEERING.md` §2.

**Result: FAIL (blocker 1 open; majors 2–7 should be resolved or explicitly rejected through the second-goldfish process).**


## Implementer disposition (pending fresh review)

All findings accepted. Corrected MiniMax arithmetic; made B3's shared paid
reservation enforcement an explicit launch blocker; deferred Codex transport
in full; specified Claude env/thinking/effort/beta rules and captured pinned CLI
shape; accepted covered standard/flex endpoints; named files/tests. Nits covered
in revised design. No blocker is self-certified; request a fresh goldfish.
