# Verbatim goldfish review

**Verdict: FAIL.** There are 3 blockers, 8 majors and 6 nits.

The cost math is right, and the per-request limits hold for any request that goes through the gate. The problem is that the route almost never lets real work finish. In this repo's own saved cards, 143 of 153 real Claude calls needed more than 8 requests. The $143.68 maximum is also above the $50 limit, and stream D's reviewed design treats that as a failed qualification. In practice that is the all-refusal outcome the user already rejected. The gate itself is the right component; what it counts is wrong.

**What I reviewed.** The files changed twice while I was reading, so I reviewed the final state: HEAD `f8722c1` plus the uncommitted `router.md` edits. Hashes: `router.md` 708b27f3…, `interfaces.md` add91514…, fixture 90c71dfb…. I did not read `docs/reviews/router-maxima-design-1.md`, to keep this review independent.

## Judgments you asked for

- **Proof that Claude calls reach the gate: partly proven.** The docs, the pinned client code excerpt and the network-denied probe show the CLI sends its OAuth token and main request to `ANTHROPIC_BASE_URL`. Not proven: web tools, multi-turn tool loops, compaction, the Linux worker binary (B2, M5).
- **Hard input ceiling: sound.** Each request is capped at 1M input tokens, all cache types included, and 8192 output tokens including thinking. No server tools, compaction or fallbacks get through, so no request runs a second sampling pass. The $143.683584 figure is correct. I checked the rates against the Claude API reference: input $4/M, 1-hour cache write $8/M, cache read $0.20/M, output $20/M, no long-context premium, fast mode 2×, US-only 1.1×. The flaw is how the ceiling is used, not whether it holds (B1).
- **Allowed betas and body fields: OK.** They now match the pinned CLI's successful probe: 4 betas, `context_management` stripped, thinking normalised. Header handling still has gaps (M3).
- **Auth, security and ENGINEERING §4: mostly OK.** No new credential, key, Mac dependency or control-VM payload. The isolated-user `sudo` env gap is fixed. Two gaps remain: the loopback port has no authentication (M1), and the design claims nothing escapes the gate when model-run tools can (M2).
- **One-use start marker: fine** (N1). **No automatic retry after `model_call_cap`: right**, but what happens next is undefined (M7).

## Blockers

**B1. A fixed cap of 8 requests makes the route unusable, and D refuses it anyway.**
- Scope: `router.md:461`, `:509-535`; `interfaces.md:276-295`.
- Evidence from `20261029-real-public-cards.json.gz`, 153 real Claude invocations:
  - 143 used more than 8 requests. Most used 20–110; the largest used 187. The real $15.05 writer, `builder-1`, used 110.
  - 32 exceeded 8M aggregate input tokens, and 37 exceeded 65,536 output tokens.
- The probe saw the CLI make 2 HTTP attempts for one logical request (`router.md:486`), so 8 slots can mean about 4 real turns.
- Stream D's design then refuses this route:
  - `stream-d.md:529-531`: a writer maximum above $50 fails qualification, so no case launches.
  - `:67-70`: D sends the case to diagnosis without making the call.
  - `:21-23`: a case that made no model call retires its replacement chain.
- Result: Claude writers never run, and other Claude roles are refused or stop at request 9.
- Fix: keep the gate, but enforce dollars, not a request count. Before forwarding each request, require: exact cost of finished responses (from their usage) + a worst-case allowance W for each in-flight request + W for this one ≤ `lease.max_usd`.
  - W = 1M × the highest input rate + the per-request output cap × the output rate.
  - A response with missing or cut-off usage counts as W.
  - This is still enforced before sending and allows no overshoot. The same rule can also enforce the input and output token ceilings. It lets `max_usd` sit under $50; the largest real aggregate in the corpus is $32.61.
  - The gate now blocks `speed` and priority tier, so the 2× fast-mode factor cannot apply to gated requests. Dropping it halves W.
  - Re-derive the 8192 output cap from real per-response needs: Write-tool file bodies can exceed 8K tokens. A 32K cap adds only about $0.7–1.4 to W.
- Add a mid-term exam: replay the 153 real receipts against the rule and report how many fit. Today's rule fits 10.

**B2. Web tools and side requests kill Claude writer and stress-tester calls every time they are used.**
- Scope: `router.md:472-507`, `:563-565`; `model_runtime.py:439-440`; `prompts/builder.md:55-59`.
- Writers and stress testers get WebSearch and WebFetch. The G2 freshness gate requires at least 3 web and 3 GitHub searches.
- The CLI's WebSearch makes a separate request using the hosted search tool, and WebFetch summarises pages with a small, fast model. The gate rejects both: one is a hosted tool, the other is not exactly `claude-opus-5-5`. Any rejection raises `model_call_cap`.
- Side requests are routine, not hypothetical: 58 of 153 real invocations were billed beyond their main-model tokens. That includes 10 of 31 writer rows, for example `builder-freshness`. The probes covered only Bash/Edit/Read/Write and a single-request "OK".
- Fix: decide per role.
  - Either drop web tools from gated calls and state the G2 effect. That is bench logic and may need the founder.
  - Or bound them: point the CLI's small-model setting at the allowed model, or add a priced row for it, and for search enforce `max_uses` with its fee and per-pass context in W.
  - A rejected request that was never forwarded costs nothing. Return an error to the CLI and stop the call only on the money ceiling.
  - Images and PDFs already count inside the 1M context; rejecting them adds failures without tightening the bound.

**B3. Disclosure and contracts for the routes that wait forever are missing.**
- Scope: `interfaces.md:99`, `:186-191`; `router.md:569-574`; both rotation files.
- Every rotation slot has one Anthropic role and three others. With every non-Claude route on `unbounded_route`, no case can finish after this merges. The user chose that scope; the design must say so plainly.
- The other-stream contracts are incomplete:
  - The wait record requires `retry_after`, but this reason has none.
  - B's per-reason cap table has no `unbounded_route` row.
  - "Reviewed enforcement release" gives B no signal to act on.
  - D's qualification check fails for those roles too.

## Majors

- **M1. The loopback gate has no authentication.** `router.md:461`, `:499`, `:563`. Any local process, including model-run Bash commands or the isolated calibrator user, can send a valid-looking POST that uses a slot. Worse, any rejected request fails the victim call with `model_call_cap`. "Forward only the exact chosen OAuth bearer" is ambiguous: if the gate substitutes the lease's token, it lends the credential to any local caller.
  - Fix: put a random secret path segment in the base URL, or require the incoming token to equal the lease's. Unauthenticated requests get a local 401, are not counted, and do not change the call's outcome. The gate never injects a token.
- **M2. The design overclaims.** `router.md:507` ("No arbitrary endpoint … escapes") contradicts `:608-610`. Model-run Bash commands inherit `CLAUDE_CODE_OAUTH_TOKEN` (`model_runtime.py:262-264`, and the sudo preserve list) and can call `api.anthropic.com` directly, outside `max_usd` and the ledger.
  - Fix: state that the cap covers only requests the CLI itself sends, and put that in `interfaces.md` §7.
- **M3. The protocol between gate and CLI is unspecified.** The design does not say:
  - which status code and body the CLI gets for exhaustion, unsupported features, or upstream failure (the CLI's retry behaviour depends on it);
  - whether the gate stops the CLI on exhaustion;
  - how SSE streams pass through, how Content-Length is recomputed after clamping, or which upstream timeout to use.
  - It also needs verbatim response-header passthrough. The CLI builds the `rate_limit_event` that `budget.py` uses for Claude reset times from upstream headers.
- **M4. The environment cleanup is a category list, not an exact list.** `router.md:501-504`. A missed variable (provider switch, proxy, custom headers) can send the CLI around the gate.
  - Fix: build the CLI env and the sudo preserve list from one enumerated allowlist. Include the factory variables roles need, such as `FACTORY_STRATEGY_*`.
- **M5. The tests never drive the real CLI through the gate.** `router.md:598`.
  - Specify how tests redirect the fixed upstream (the destination is not configurable).
  - Add tests that run the Linux package workers actually install through the gate to a fake upstream under network deny. Cover: the writer tool set including web tools, a multi-turn tool loop, a `max_tokens` stop, compaction, and the sudo path.
  - Assert that every connection goes to the gate and every forwarded body passes the allowlist.
- **M6. No final exam.** Heilmeier "exams" and ENGINEERING "real artifacts": the offline tests prove the adapter, but a production batch would be the route's first real use. Require one Claude role through the gate in B's practice-case end-to-end run, with `cap_used` and the real usage receipt recorded.
- **M7. The downstream outcome of `model_call_cap` is undefined.**
  - Not stated: the terminal stop per role (writer, stress tester, reviewer, G2-confirm, G16, G17, calibrator); that it is unscored; how D's diagnosis classifies it (a factory limit, not "not converging"); and that it never becomes writer feedback.
  - G10 treats `call_limit` as a capped scientific try (`run.py:2179`, `calibration.py:486`). The new label raises instead of counting as a try.
- **M8. Old leases kill in-flight calls on deploy.** Leases without caps fail renewal after a router deploy, cancelling in-flight calls within 60 seconds rather than at the next checkpoint (ENGINEERING §3). Moot while no batch runs, but say so.

## Nits

- **N1.** The start marker shares the namespace that `observe()` uses for its IDs. Use a prefix `observe()` rejects. Also say what happens after a lost start acknowledgement: finish the lease as denied, get a new one, and name the wait reason.
- **N2.** The client can attach caps from the shared code-owned policy, so the server only needs to know "bounded or not". That also removes spurious `unbounded_route` waits when the control-VM and worker versions differ.
- **N3.** Fixture gaps:
  - The docs "facts" are paraphrases with no quotes or hashes.
  - The probes don't record argv/env (beta-disable, `MAX_RETRIES`, tool list), platform, or binary hash.
  - `scope` still says "version/help only".
  - Quote the three facts the bound rests on: context includes all input and cache, input over context returns 400, `max_tokens` includes thinking.
- **N4.** The Objective paragraph is jargon-dense (D, Lease, "$33 import estimate"). Add two plain sentences.
- **N5.** `interfaces.md` §2 still shows `Lease(lease_id, route, account, expires_at)`. Add the caps there or point to §7.
- **N6.** No Murphy rows are named as closed. That is acceptable, but if the "no enforceable maximum" gap is tracked, add a `new-router-maxima-1` row.

To pass, the design needs B1–B3 resolved, most simply by switching to the dollar-based admission rule and making an explicit web-tool decision, plus M1–M7 specified.

## Author response

All blockers and majors are accepted for resolution; none is rejected. The fixed eight-request cap will be replaced by pre-forward monetary and token allowances, using actual completed-response usage only to release previously reserved worst-case allowances. Missing/cut-off usage retains the full allowance. The next design will specify nonfatal rejection of unsupported never-forwarded requests, small-model routing, authentication, exact protocol/env controls, independent pin probes, B/D wait and cap-stop contracts, rollout and practice-run qualification. A fresh review is required before implementation.

