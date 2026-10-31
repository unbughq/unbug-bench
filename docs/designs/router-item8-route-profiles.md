# Item-8 bounded routes for small commitments

2026-10-31. Branch t3/router-item8-prereqs; merged local factory-simplify f41ce52
before this work. This is an offline implementation design, not launch approval.

## Problem and objective

B3 needs honest per-invocation maxima before preparing manifests. Existing Opus
5.5 reserves $8.655360 per request, exceeding a $5 invocation. Its $10/$15 aliases
cannot serve the small item-8 allocations. MiniMax and OpenAI selected routes lack
maxima. This increment supplies Claude and MiniMax; the new Codex transport is
deferred to its own design and review following design review 1 majors 3/4.
OpenAI maxima remain unimplemented and scenarios 4/6 remain blocked. Provide explicit opt-in bounded routes in those families without changing
saved candidate bindings, scenario caps, gate science or account policy. Useful
writer/guard completion remains a separate live acceptance obligation.

Do not reduce Opus 5.5's maximum using token estimates, CLI compaction settings,
no-cache assumptions or post-response refusal. Keep its existing aliases intact.
Use a provider model with a smaller documented context for the new Claude route.
This changes the selected model only for newly bound manifests; B3 must check
candidate compatibility rather than rewriting an authenticated saved model.

## Funding and scenario contract

Founder authorized using existing OpenRouter credit, with no top-up, and raising
the factory key limit if a management credential is available. The read-only
control-VM audit found no management/provisioning label. The factory key reports
is_provisioning_key=false, limit=null, limit_remaining=null, cumulative usage
$31.494136472. Account balance is $11.626127395. Nothing was changed. Thus the
previous $0.409068839 key-remaining observation is not the current observation.
The exact audit and dashboard instructions will be in the companion report.

All qualification releases/scenarios together may consume at most $11.63 of new
OpenRouter money, additionally bounded by actual available account credit. This
is distinct from $90 model/list-equivalent authority and must never be renewed
per batch, replacement, retry or release. Stream B owns atomic paid reservation enforcement across releases. Paid item-8
dispatch is NOT authorized by this increment and must be refused until B3 lands
and reviews a shared cumulative paid reservation check, including concurrent
admission, pending and unknown usage. No existing test is claimed to prove this
paid sublimit. B3's manifests must also reconcile actual
paid receipts plus pending/unknown paid reservations across all seven scenarios
before each next paid dispatch; a per-invocation cap does not enforce this total.
No funding claim is a promise that all scenarios finish in that amount. Reserve
before dispatch; stop/wait on exhausted authority without scoring a broken case.

Use subscription Claude/Codex for Anthropic/OpenAI roles. Required MiniMax and
DeepSeek roles cannot be substituted by those families. With currently qualified
and proposed bounded routes, scenarios 1–3/6 can use paid MiniMax only after a reviewed stream-D/B3
amendment defining same-model route compatibility, including provider fp8
quantization versus the unknown saved free serving. Scenarios 1–3/5–7 have
DeepSeek roles. This increment does not establish eligible paid consumers.
Scenario 4 has no required OpenRouter route but remains blocked on bounded
OpenAI execution. Source: docs/designs/stream-d.md, Item 8 candidate/role map
(at merged factory-simplify f41ce52). If paid access is unavailable, only
scenario 4 is subscription-only in the present role map; the others remain
blocked pending a genuinely qualified free same-family route or a separately
reviewed scenario change. Do not claim a subscription-only execution of all seven.

## Routes and maxima

1. Add `claude/claude-opus-4-5-20251101:compact` ($3) and `:small` ($5).
   Provider ID is exactly claude-opus-4-5-20251101. Context 200000; per-request
   output clamp 16384. Standard/global rates per million: input 5, cache-read 0.5,
   one-hour cache-write 10, output 25. Cached behavior remains enabled. Worst hold
   is $2.409600. Available validated-spend headroom for another maximum request
   is $0.590399/$2.590399 respectively. Unknown attempts retain the whole hold.
   Input maxima are 6000000/10000000; output maxima 120000/200000. These follow
   USD*1M/min(input rates) and USD*1M/output. Price-source includes exact route,
   model, context/output bounds, tariff, global/standard and joint-gate version.
   Do not claim these are smaller Opus 5.5 aliases or equivalent quality.
   Small serves fresh scenario 3/replacement 7 allocations of $5; compact can admit
   a later call when remaining authority is between $3 and $5. Neither guarantees
   useful completion. Below $3 these profiles cannot start. No automatic fallback.
   16384 output keeps $0.4096 as the output hold; 32768 would double it and
   leave less room for settled work. This is explicit bounded quality tradeoff.

2. Add `openrouter/minimax/minimax-m3.1-flash`, pin `tenstorrent/fp8`, no
   fallback. This supersedes the reviewed M3 proposal: public metadata confirms
   a paid route of the saved M3.1 Flash model exists, while its :free endpoint
   list is empty. Evidence: router-item8-minimax-availability.json.gz (real public
   GET responses with UTC timestamps). M3's older endpoint fixture is retained
   only as review history, not an input to the implemented profile.
   Context 1000000, provider maximum output 900000, rates .05/.005/.2 USD/M,
   no cache-write fee. Keep requested output clamp 32768 but reserve full provider
   output as existing cheap routes do. Worst request .230000; three windows plus
   .000001 gives max_usd=.690001000; input maximum 13800020 and output 3450005.
   Three windows allow one worst hold after two unknowns while keeping max below
   $1. No discount assumption. Exact source:
   `token_prices:2026-10-31:openrouter:minimax/minimax-m3.1-flash:tenstorrent/fp8:0.05,0.005,0.2:joint-gate-v1`.
   Provider only pin and price caps remain mandatory. There is no flex sibling
   in this saved endpoint response. Runtime drift fails closed through the price
   caps; live transport/model-ID compatibility is unproved (below).
   Existing DeepSeek maximum 1.174406120, input 8388615, output 2796205 stays
   unchanged. The final report obtains all four fields directly from route_maximum.

   This is a paid route address, NOT the saved free-address binding. It preserves
   the underlying model/family but does not attach itself to existing CHAINS.
   B3 may select it explicitly only in NEW compatible manifests, exactly like
   the new Claude model profiles. Never rewrite an authenticated candidate or
   silently replace free billing with paid billing. Candidate compatibility must
   cover model ID, role family, effort (Claude low/medium/high, MiniMax default),
   gates/fairness and carried evidence under B's existing admission contract.
   The profile supplies a manifest option, not a changed science decision or
   evidence that current saved candidates are eligible. Existing free bindings
   remain unbounded until a separate compatible routing/admission change.

## Source contracts and implementation

Primary public sources, frozen in router-item8-source-evidence.json.gz:
- https://platform.claude.com/docs/en/models/opus-4-5/overview (200K context).
- https://platform.claude.com/docs/en/about-claude/pricing (Opus 4.5/cache tariff).
- https://support.claude.com/en/articles/11940350-claude-code-model-configuration
  (exact dated model selection in subscription CLI).
- https://platform.claude.com/docs/en/about-claude/model-deprecations lists
  Opus 4.5 Active, with retirement not sooner than 2026-11-24, as of 2026-10-31.
  B3 must recheck before scheduling; this evidence is for qualification before
  November 24, not permission to ignore a later retirement notice.

Extend code-owned profile data in token_prices.py with provider ID, context,
output, prices and invocation USD. Preserve constants/default helpers used by
existing Opus 5.5 tests. Route-specific request/usage parsing in model_call_gate.py
must check the exact provider ID and limits, not the alias; claude_cost must price new alias receipts without affecting old routes. Router
route_maximum admits only exact entries and valid_maximum still compares every
field. Runtime keeps configured_model/models_used/lease aliases but sends the
provider ID to its pinned CLI. Existing pool/account preference remains intact.

Claude: parameterize request_body, Usage, empty_usage, Allowance reserve/amount
and enforce environment by profile. Opus 4.5 uses extended thinking: accept only
`enabled` with integer budget_tokens from 1024 through 8192 and below clamped
max_tokens, or disabled;
reject adaptive on this model. Set CLAUDE_CODE_MAX_OUTPUT_TOKENS=16384 and
MAX_THINKING_TOKENS=8192 for this profile; ignore user overrides by replacing
these values in enforce. The gate rejects (does not silently rewrite) a budget
outside those limits. Restrict effort to low/medium/high. ANTHROPIC_SMALL_FAST_MODEL
becomes the exact profile provider ID. Keep the outbound beta allowlist BETAS;
never forward any inbound beta header, including 1M/context-extension headers. Keep Opus 5.5 adaptive behavior unchanged. Validate
existing cache fields, local tools and standard tier; omit inference_geo on
Opus 4.5 (the geo selector applies to 4.6+; first-party default is global), keep
the explicit global override on 5.5; reject hosted tools and
premium modes. Reject unsupported fields before upstream. The pinned 2.1.299 two-request CLI probe in router-item8-claude45-cli.json.gz already
returned exit 0/OK against synthetic SSE, with max_tokens 16384, enabled thinking
budget 8192, effort high, and the existing BETAS set. SHA matches the previously
captured pinned CLI. It saves full request/response UTF 8 bytes from synthetic loopback, including
Read tool_use/tool_result and replayed synthetic signed thinking. Replay these
bytes directly, not reconstructed summaries. Probe platform is darwin-arm 64;
Linux CLI shape equivalence and small-fast side calls remain unproved and must
be covered in worker/live acceptance. It is not real inference/role evidence;
replay those bytes through the real gate tests before advertising the route; never adapt the provider model to fit a fabricated test request.

OpenRouter: reuse current gate/Usage/environment with the new exact profile;
version per-profile provenance rather than globally repricing old leases.
No endpoint fallback or discount assumption. Check the saved endpoint for supported
parameters and zero non-token fee contract in
`test_minimax_endpoint_contract` using router-item8-minimax-availability.json.gz; this is test-time, not a runtime metadata GET.
The test asserts max_tokens/tools/tool_choice/reasoning support and quoted
prices/context/output. The gate already forces OpenRouter usage reporting;
stream_options/usage are aggregator controls, not asserted native parameters.
Actual paid response model-ID normalization and pinned OpenCode parameters for
this model are unproved live risks: retain the exact model equality rule, and
missing/mismatched usage keeps the full $.23 hold. Do not broaden acceptance to
dated IDs without evidence. No MiniMax paid-call success is claimed.

Codex is deferred in full. No Codex price, parser, credential handling, maximum,
or runtime behavior changes in this increment. Its separate design must settle
custom-provider auth mode, validated token lifetime, exact headers, response SSE
and encrypted reasoning replay, two-turn tool probing, GET/models, compact/lite
and WebSocket refusal. The tentative Luna figures in review 1 are not advertised
maxima or manifest inputs.

The protected scope remains CLI-owned inference, matching the existing gate;
this does not claim the gate sandboxes arbitrary Bash credential/network use.
Linux worker firewall and cancellation acceptance remain independently required.

## Deletions, risk, tests and acceptance

Delete singleton-model assumptions where needed; add no ledger, launch path,
role selector or automatic model rewrite. Do not add a nominal request-count
bound: money/token holds already bound dispatch. Main risks are legacy Claude
availability, false accounting on truncated streams,
and insufficient role quality. No live quality claims arise from loopback tests.

Implementation order: freeze public/pinned evidence and synthetic CLI shapes;
prices/router; codecs/gate; runtime; regression tests; manifest-facing report.
A source or CLI-contract failure causes design revision, not an invented maximum.
Estimated one implementation/review session for Claude/MiniMax, zero benchmark/provider
spend. Codex requires a separate source/protocol investigation and review cycle.

Mid-term tests: exact lease maxima/provenance; unknown aliases and forged maxima;
provider-model mapping; family/account policy; independent pricing of saved real
cards under the stated new tariffs as envelope analysis only. No assertion that
old Opus 5.5 traces came from these new models. Saved provider endpoint/source
artifacts prove contracts; synthetic CLI/HTTP artifacts prove protocol wiring.

Final offline tests: parameterize real Store/ModelRuntime/ledger interruption
regression over new routes and HTTP 1.0, keep-alive, Connection:close. Require EOF
and handler/runtime completion before upstream release, retained exact holds,
no live lease, immutable receipt on late response and idempotent reconciliation.
Test cap refusal before upstream, concurrent holds, wrong model, hosted tools,
provider/config bypass, partial/error usage, alias pricing and CLI provider IDs.
Report saved-card aggregate envelope counts, but do not infer per-request fit or
number of fitting requests: full request traces are absent and model/tokenizer
changed. A claimed request count from those aggregates would be invented.
Capture pinned CLI probes separately and label them synthetic, not live role
acceptance. Preserve all base-route regressions. Run full suite exactly
`uv run --with numpy --with scipy python -B tests/run.py`, redirect to unique
UTC+nonce log, wait for exit, commit log and result record, then fresh diff review.
Every blocker correction receives another fresh goldfish; no self-verification.

Later live acceptance: B's authenticated candidate under these exact selected
routes completes useful writer work and executable strong guard, reconciles all
known/unknown usage under per-job and cross-release paid ceilings, and correlates
account 2 usage. Model unavailable or exhausted is not success. Scenario manifests
must distinguish implemented maxima from live-qualified roles.

## Murphy rows

No row closes in this increment merely from price/profile implementation. Rows
9/39, useful live role feasibility, worker/TLS cancellation and account 2 acceptance
remain open. Register a newly observed real failure before fixing it. A narrowly
proved local failure may close only with its real-artifact test and fresh review.

## Exact files and review 1 disposition

- factory/token_prices.py: keep CLAUDE_PROFILES as route->USD for callers; add
  code-owned route->provider descriptor lookup with context/output/thinking and
  rates; add Opus 4.5 CLAUDE_PRICES and route mapping. claude_gate_cost(usage,
  route=GATED_CLAUDE) remains backward compatible. claude_gate_maximum derives
  exact alias fields; base/small/medium Opus 5.5 provenance remains byte-identical.
  New source string is `token_prices:2026-10-31:claude-opus-4-5-20251101:5.0,0.5,10.0,25.0:context=200000:output=16384:standard-global:joint-gate-v1:profile=<compact|small>:usd=<3|5>`.
  MiniMax provenance is the exact string in Routes item 2 above.
  Add MiniMax GATED_OPENROUTER entry and per-profile source date defaulting to
  existing 2026-10-30. runtime_prices already reads these entries.
- factory/model_router.py: existing CLAUDE_PROFILES membership covers new aliases;
  no route-chain/pool changes. Tests verify no free-route fallback changes.
- factory/model_call_gate.py: profile lookup in request_body, Usage init/merge/
  event/final, Allowance.amount/reserve, empty_usage, Handler request/parser
  construction, enforce environment. Replace exact Opus 5.5 request/response IDs
  with selected descriptor ID. Preserve old defaults. Add MAX_THINKING_TOKENS
  to ENV_KEYS for sudo, then remove inherited value on existing profiles and set
  the code-owned value on Opus 4.5. Do not forward caller beta headers.
- factory/model_runtime.py: replace known-alias mapping to GATED_CLAUDE with
  profile provider model. Keep alias in receipts. No credential changes.
- tests/factory/test_model_call_maxima.py: preserve legacy tests by restricting
  assumptions like small/medium serialization to Opus 5.5; extend real runtime
  interruption helpers with route-specific model/output/hold and MiniMax wire
  format/credential setup. Pin explicit expected dollar values independent of
  implementation, not expectations obtained by calling the function under test.
- tests/factory/test_router_item8_profiles.py (new): source/endpoint fixture
  contracts, exact maxima, captured CLI shape replay, pricing, unknown/forged
  aliases, beta/effort/thinking/hosted-tool rejection, concurrency and exhaustion.
- Fixtures: router-item8-source-evidence.json.gz (public source facts and short
  excerpt hashes, not raw-page hashes); router-item8-claude45-cli.json.gz
  (synthetic SSE capture); router-item8-minimax-availability.json.gz (current
  M3.1 Flash public provider metadata); router-item8-minimax-endpoints.json.gz
  (superseded M3 proposal, history only). No real credential or model request in these artifacts.
- Docs: this design, docs/reports/router-item8-funding-20261031.md, a final
  router-item8-route-profiles report with manifest inputs and remaining blockers,
  docs/reviews/router-item8-route-profiles-design-N.md and -diff-N.md, and unique
  docs/reports/router-item8-route-profiles-suite-<UTC>-<nonce>.log/.md.

Review 1 finding 1 accepted/corrected;2 accepted, B3 enforcement explicitly blocks
paid dispatch;3/4 accepted and Codex split out, with no Codex admission claim;
5 accepted with fixed env/thinking/effort/small-model/beta contract and real pinned
synthetic probe;6 accepted initially for M3; superseded by the same-model M3.1 Flash profile;
7 accepted with this file list. Nits 8–13 addressed above. No finding rejected.
Fresh review is required before implementation; this disposition is not a pass.

## Review 2 clarifications

All findings accepted. Finding 1 uses the same-model paid M3.1 Flash route with
an explicit new-manifest binding rule, no chain rewrite. Finding 2 corrects the
DeepSeek amount and requires code-derived manifest output. Finding 3 keeps usage
validation strict: speed absent/standard, geo absent/global only; empty string,
unknown/premium geo and modes remain unknown (no refund). Request standard_only
remains required; service tier accounting relies on that request restriction.
The CLI final summary's empty geo is a CLI default in the synthetic probe; its
upstream bytes have no geo. Real response empty geo would therefore exhaust
compact after one unknown, small after two: a live-acceptance risk, not waived.
The geo-selector primary-source fact is now saved.

Finding 4 adds lifecycle evidence;5 replaces summary-only fixture with full
synthetic two-request tool-loop capture, but Linux/side-calls remain unproved;
6 names fixture assertions and accepts exact response-ID/OpenCode parameter
compatibility as live risk with strict fail-closed usage. Normalized source
excerpts are labelled explicitly. The cross-release paid refusal is procedural:
this change creates no item8 launch manifest/path; B3 must enforce its paid gate
before activation. The generic router can issue paid leases as it already can
for DeepSeek/MiMo, so this profile is not itself an $11.63 global spend control.
No finding rejected or self-certified. Request fresh design review.

## Review 3 disposition before implementation

PASS with no blockers. All three majors accepted: fixture/test source now names
availability.json.gz exclusively for M3.1 Flash; adopting paid MiniMax requires
reviewed stream-D/B3 compatibility rules before any item-8 consumer; lifecycle
checks remain a launch prerequisite. The fixture test pins Tenstorrent's three
rates, zero discount, context/output, supported max_tokens/tools/tool_choice/
reasoning, exactly one tenstorrent tag, and the empty OpenRouter :free endpoints.
The empty list proves nothing about OpenCode's separate native free route.

Opus 5.5 was rejected for the $8.65536 hold. The public model comparison shows
Sonnet 5.5's 1M context and $4 one-hour cache write rate; its full-context hold
leaves much less useful headroom under $5 than Opus 4.5. Haiku was not selected
for the intended strong roles; useful role quality still needs live proof.
For qualification on/after November 24, 2026, B3 must refresh lifecycle evidence
before each dispatch and refuse deprecated/retired profiles before requesting
leases. This is a required future admission check, not code supplied here.
An unexpected model-not-found response is infrastructure route loss, not a scored
role failure; the gate retains its unknown hold. A replacement model needs a new
design and profile, never a silent swap of this profile's provider ID.

Bare claude/claude-opus-4-5-20251101 stays unbounded; only the two exact aliases
enter CLAUDE_PROFILES. Opus 4.5 retains the existing validated JSON-schema format
field (no hosted-tool fee); compatibility remains live-unproved. Tenstorrent's
null recent throughput/latency and no fallback are availability risks: three
unknown routing failures retain $.69 and exhaust the invocation. Geo evidence
facts extending beyond the saved normalized excerpt are marked inferred.
The implementation and final report will preserve these limitations.

Implementation clarification: tests/factory/test_router_cheap_maxima.py pins
its historical-price/real-session/CLI-probe assertions to the two routes actually
present in those saved captures. Generic protocol/environment tests still cover
all GATED_OPENROUTER entries, including MiniMax. No new route is credited with
old CLI acceptance evidence.
