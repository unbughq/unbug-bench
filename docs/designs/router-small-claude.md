# Smaller Claude subscription reservations

2026-10-31. Base factory-simplify 45b89a5, fast-forwarded into t3/router-item8-prereqs.

## Problem and objective

A writer or calibrator currently needs $50 of unused job authority to start any
Claude subscription call. Many real writer calls cost much less. Supply explicit
$10 and $15 reservations using the same model, cache behavior and enforcement,
so eligible roles can start under smaller commitments without under-reserving.
This is an incremental improvement, NOT completion of item 8's at-most-$5 target.
It does not alter scenario caps, authorize more spend, or activate qualification.
Scenarios whose remaining authority is below $10 stay blocked. The earlier $5
no-cache proposal is withdrawn following design review B1/M1: its $4.655360
request hold leaves only $0.344639 for total validated spend before refusal,
and its subscription no-cache contract was unproved.

## Change

Add exact local route aliases `claude/claude-opus-5-5:small` ($10) and
`claude/claude-opus-5-5:medium` ($15). Keep the base route at $50. These are
opt-in role model strings for NEW admitted jobs, never automatic rewrites of
saved candidate bindings. No fallback to another profile. All use the exact
provider model claude-opus-5-5, context 1000000, max output 32768 per request,
existing supported local tools, and existing denial of provider-hosted tools.
Do not add a request-count cap: the joint money/token gate remains the bound.
Caching is unchanged, including the conservative one-hour write rate.

Define CLAUDE_PROFILES in token_prices.py mapping the three exact route strings
to Decimal invocation USD limits. Keep GATED_CLAUDE, CLAUDE_CONTEXT, CLAUDE_OUTPUT
and CLAUDE_CALL_USD for compatibility. Unknown aliases remain unbounded.

Exact lease fields (USD float, input/output int):
- small: max_usd=10.0, max_input_tokens=50000000, max_output_tokens=500000.
- medium: max_usd=15.0, max_input_tokens=75000000, max_output_tokens=750000.
- base stays 50.0, 250000000, 2500000 with its unchanged price_source.
Token limits use invocation USD * 1000000 / $0.20 cheapest input and / $20
output. The money gate is joint; these are not independently spendable grants.
Alias price_source is the base price_source plus `:profile=small:usd=10` or
`:profile=medium:usd=15`. valid_maximum compares every exact field as today.

Each request reserves $8.655360 at max output, including possible one-hour
cache creation. Refusal occurs once settled + held + next worst + $0.000001
exceeds the lease. Therefore small offers $1.344639 of settled-spend headroom,
medium $6.344639. These are NOT fully usable $10/$15 spending targets. Unknown-attempt tolerance is zero for both profiles. An
unknown attempt retains $8.655360; any next request (even zero output) sets
exhaustion and raises model_call_cap.
Concurrent requests of any size cannot both fit; they serialize via existing
condition waits. This limitation is explicit, not hidden by a nominal 64-call cap.

## Evidence and usefulness

Committed public-card fixture has 153 unique Claude receipts. Under the existing
standard/global tariff, 67 have cost <= $1.344639 and 132 <= $6.344639. These
are conservative aggregate-envelope checks, not replayed HTTP traces or quality
proof. The saved paid-DeepSeek cards contain Claude writer event
252e6df1-f899-427e-aa07-7b98ba7eb156:result (35 requests, about $1.116127), which
fits small, and 0d4adf8f-0ef4-4cef-aeb0-c974454eaee8:result (62 requests, about
$5.152199), which fits medium. Tests must find these immutable records and verify
role/call count and max(recorded list_cost_usd, re-priced aggregate) plus worst hold. They show useful
writer workloads can fit the envelope, unlike the withdrawn no-cache proposal.
They do not establish live role success, individual
request-size validity. Strong-calibrator feasibility remains open.

## Exact implementation sites

- token_prices.py: add CLAUDE_PROFILES; claude_gate_maximum(route=GATED_CLAUDE)
  returns the above fields or None. claude_cost maps only known aliases to base
  Opus before _claude_list_cost. The unused invocation_maximum helper is unchanged.
  claude_gate_cost remains unchanged (one actual provider model).
- model_router.py route_maximum: map membership instead of singleton equality,
  passing route into claude_gate_maximum. Existing valid_maximum requires no
  change. Existing routes already accept colons and choose subscription billing,
  Anthropic family and account-2-first labels via startswith('claude/'); do not
  alter account selection or pools.
- model_call_gate.py Allowance.amount/reserve and enforce: replace singleton
  route equality with exact CLAUDE_PROFILES membership. Keep all request/response
  model equality checks at base provider ID. No changes to request_body, Usage,
  cache_control, output clamp, environment, empty_usage defaults or socket logic.
- model_runtime.py _invoke: after model.partition('/'), map model_id to base ID
  for known Claude profiles before assembling CLI command. Keep model/lease route
  alias for configured_model, models_used and runtime receipts. Unknown aliases
  never get a valid lease. budget.py configured_model/route comparisons and role
  mapping preserve alias; --model parsing is only a fallback when configured_model
  is absent. free_models.apply does not match aliases and leaves them unchanged.
  Prefix-based effort/family/account selection needs no change. empty_usage and
  Handler choose Claude because aliases are not OpenRouter routes. Capacity is
  shared per account pool. Outage health remains pool/route-specific: alias/base
  outages are independent, while quota/credit/credential health is pool-wide.

## Deletions, risk, timeline and cost

Delete the proposed no-cache path and extra request-count limit from scope;
no new launch path, profile-selection service, provider or ledger. Preserve base
behavior. Alias pricing is a key risk: unmapped aliases currently become unpriced
partial receipts. Regression tests must prove they do not. A malformed profile
or stale maximum must fail before process/network. Future enforceable <=$5 Opus
profiles require a provider-backed smaller context/cost contract; token-count
estimates are not bounds. No caching assumption is weakened here.
One implementation session plus fresh design/diff reviews and full suite.
Offline benchmark/model/infrastructure spend $0. Reviews use the requested
Claude subscription. Other route maxima have separate contracts and stay out of
this increment. Funding evidence is in
../reports/router-small-claude-funding-20261031.md.

## Tests and exams

Extend tests/factory/test_model_call_maxima.py; do not fabricate provider evidence.
Real saved inputs: 20261029-real-public-cards.json.gz,
router-paid-deepseek.json.gz, router-claude-mode-cli.json.gz in its fixtures dir.

Mid-term exam: exact lease fields for all profiles; unknown alias and forged
maximum rejection; account-2 preference/no base fallback; alias prices equal
base prices for real saved counters. Replay the two real writer aggregate
bounds through actual Allowance and check further admission with worst hold,
then refusal above headroom. Preserve existing base tests unchanged.

Final offline exam: use actual loopback HTTP gate, Store, ModelRuntime receipt
writer and money ledger, with only process/provider boundaries synthetic.
Parameterize existing real runtime mid-response interruption regression over
base/small/medium and all three HTTP variants. Each must retain $8.655360 once,
release lease, close client before upstream release, and reconcile idempotently
under its selected invocation reservation. Add successful alias CLI capture:
--model uses base provider ID, credential account stays selected, receipt and
configured model keep alias and partial usage is priced. Verify gate enforces
cap before upstream, handles concurrency and refuses forged alias maxima.
Run focused tests, then full required command
`uv run --with numpy --with scipy python -B tests/run.py`; wait for completion,
commit unique UTC+nonce log and result record. Fresh diff reviewer checks design
and tests. Each blocker correction gets a fresh reviewer.

Later live exam (not claimed here): B supplies eligible authenticated candidates;
a real writer submits useful work and strong calibrator submits executable guard
under the selected exact lease, receipt list cost and unknown holds fit the job
commitment, actual account-2 usage is correlated. An exhausted call is not success.
At-most-$5 item-8 target and below-$10 scenario authority remain blocked even if
these $10/$15 profiles pass. No scenario cap is revised by this design.

## Murphy rows

No row closes: rows 9/39, useful live role feasibility, other route maxima,
TLS/worker cancellation and account-2 acceptance remain open. No new runtime
failure has been observed. The design blocker is recorded and withdrawn, not
misrepresented as a repaired production failure.

## Review 2 clarifications before implementation

The concrete consumer is ordinary writer-round admission in run.py: with the
default $50 ordinary limit, the base $50 reservation admits only at zero spend.
Medium can admit up to $35 spent and small up to $40, subject to other authority.
Use medium for writers; small only when role history fits. Public-card writer
envelopes fit 16/31 small and 30/31 medium; paid-DeepSeek writer envelopes fit
13/25 small and 24/25 medium. Nonfits indicate exhaustion risk, not observed
profile failure rates: aggregate sufficient bounds do not reconstruct traces.
model_call_cap is re-raised as plumbing by run.py, never scored as success.
No item-8 scenario is asserted unblocked end-to-end: its later invocations can
fail admission even after a first profile lease fits. Scenario caps stay fixed.

Implementation order: prices/router, gate, runtime, tests. Extend named tests:
test_real_routes_fail_closed_except_exact_qualified_profiles;
test_real_writer_partial_estimator_uses_captured_cli_mode_surface;
test_runtime_close_mid_response_retains_hold_once;
test_successful_cli_cannot_hide_gate_unknown_usage_in_real_runtime_receipt.
For the two real writer records, verify zero unknowns permit another request and
one unknown refuses even a zero-output request with exhaustion.
