# Goldfish design review: `docs/designs/router-small-claude.md` (revision 2)

Mode: REVIEW. Personas: zoom_out, design_critic, implementation_readiness (read first). Standards: heilmeier-standard.md, implementation-readiness-standard.md. Worktree `/Users/bugsincode/.t3/worktrees/unbug-bench/t3-afe2d824` at 45b89a5. The design, the funding report and design review 1 are untracked. The review was read-only. I made no model calls, touched no credentials and made no edits. The only computation was local arithmetic over committed fixtures using `factory/token_prices.py`.

**Verdict: PASS.** No blocker is open. There are three Major findings and five Nits. B1 from design-1 is resolved; see the next section.

---

## B1 disposition, checked independently

Design-1 B1 asked for three things: state the real ceiling, then either name a role whose real spend fits with fixture evidence or withdraw; and drop the 64-attempt cap. I checked each against the code:

- **The ceiling is stated correctly.** `Allowance.reserve` (`model_call_gate.py:167-193`) holds 1M tokens at the dearest input rate ($8, the one-hour cache write) plus the requested output at $20/M. That is 8 + 0.65536 = **$8.655360** per request at 32768 output. Admission needs settled + held + worst + $0.000001 ≤ max_usd:
  - small: 10 − 8.655360 − 0.000001 = **$1.344639**
  - medium: 15 − 8.655360 − 0.000001 = **$6.344639**

  Design lines 42–45 give both numbers and say plainly that they are not usable $10/$15 budgets.
- **The fixture evidence matches.** I re-walked `20261029-real-public-cards.json.gz` the same way `real_iterations()` does: 153 receipts, none unpriced. 67 are ≤ $1.344639 and 132 are ≤ $6.344639, the same as the design. The counts don't change under the existing test's conservative `max(list_cost_usd, claude_gate_cost)` rule (`test_model_call_maxima.py:142`).
- **Both named writer records exist** in `router-paid-deepseek.json.gz`, both standard/global:
  - `252e6df1…:result`: writer, `builder-6`, 35 calls, $1.1161268. Fits small.
  - `0d4adf8f…:result`: writer, `builder-selection`, 62 calls. Recorded list cost $5.1521987, re-priced cost $5.1152906. Fits medium.

  Admission only needs the settled total *before* each request to be under the headroom. A whole-invocation total under the headroom is therefore a sufficient condition, as long as every request validates. The design's "conservative aggregate-envelope" label is accurate.
- **The no-cache path and the 64-attempt cap are both removed** (lines 26, 87). Design-1's M1 (the unproved no-cache contract) goes away with the no-cache path. Caching is unchanged.
- **The token maxima are exact** (design-1 M2 resolved): 10×1e6/0.20 = 50,000,000 and 10×1e6/20 = 500,000; 15 → 75,000,000 and 750,000. These follow the base formula at `token_prices.py:122-123`. Token limits bind only when USD binds too, so there is no hidden second ceiling.

**B1: closed.**

---

## Major findings

### M1: one unknown attempt ends the whole invocation, not just "another full-size request" (design_critic: Risks)

**Where:** design line 46; `model_call_gate.py:181-184`, `:551-568` (any non-200 or unvalidated reply settles as unknown), `:671-672`.

A retained unknown hold is $8.655360. Even a request with zero output has a worst case of at least $8 (1M × $8/M input). After one unknown:
- small leaves 10 − 8.655 = $1.34;
- medium leaves 15 − 8.655 = $6.34.

Both are below $8. Line 181 checks `settled + retained + allowance > max` with no waiting, so the next request of *any* size sets `exhaustion`. The client gets 400 `model_call_cap`, and `enforce` then raises `BudgetError('model_call_cap')`.

So both profiles tolerate **exactly zero** unknown attempts. A single 429/529/5xx, malformed SSE or interrupted response ends the invocation. Compare the base profile, where the existing test tolerates 3 and 2 unknowns for the two real writers (`test_model_call_maxima.py:137-150`). Line 46 reads as if smaller requests could still go through, and an implementer could write a wrong assertion from it. Line 61 lists "unknown-attempt tolerance" as not established, but it can be established offline and the value is 0.

**Required:**
- State that tolerance is 0 for both profiles.
- State that the first unknown followed by any further request sets `model_call_cap`.
- Extend the `test_real_writer_envelopes_fit_with_bounded_unknown_attempts` pattern to both aliases with `tolerated = 0`: 0 unknowns admitted, 1 refused with exhaustion set. Do this for the two named records under their profile.

### M2: Impact doesn't name who can actually use this, or what happens when the headroom is exceeded (zoom_out / Heilmeier: Impact, Risks)

**Where:** design lines 5–17 and 50–62.

The objective says "eligible roles can start under smaller commitments" but names no concrete job that becomes runnable. Two concrete facts change the usefulness picture, and the design states neither:

1. **There is a real production consumer.** `run.py:436-438` refuses an ordinary writer round when `spent_usd + maximum > ordinary_limit_usd`, and the default ordinary limit is $50 (`model_runtime.py:258`). With the $50 base profile, a Claude writer round can start only when the case has spent $0. I checked only the ordinary branch; the extension and continuation branches skip this test. With `:medium`, later rounds can start up to $35 spent; with `:small`, up to $40. That is the strongest "who cares" answer, and it should be in the design.
2. **The item-8 scenarios are a weak consumer.** The caps are $10/$10/$5/$15/$15/$25/$10 (`docs/designs/stream-d.md:3599-3607`).
   - A `:small` reservation uses the whole $10 cap of scenarios 1, 2 and 7.
   - Those scenarios need more than one invocation: interrupt then resume, a retained partial, a replacement. After the first call retains $8.655 or settles anything, less than $10 remains, so the second invocation is blocked.
   - Scenario 4 needs two guard attempts under $15, so `:medium` admits only the first.

   The design rightly avoids claiming scenario completion (lines 11–13, 130–131). It should still say plainly which scenarios this unblocks — likely none of them end-to-end — so nobody budgets on it.

The design also gives no rule for choosing a profile, and none for what happens when the envelope is exceeded. A `--builder` binding (`run.py:3084`, `model_runtime.py:114`) applies to every writer round of the case, and fallback is forbidden by design. By role, real writer invocations within the headroom are:

| Fixture | ≤ small ($1.344639) | ≤ medium ($6.344639) |
|---|---|---|
| public cards | 16/31 | 30/31 |
| paid-DeepSeek | 13/25 | 24/25 |

So about half of real writer rounds would hit `model_call_cap` mid-work under `:small`, versus about 3–4% under `:medium`. The design's 67/153 and 132/153 mix in 122 receipts with no role, which hides this.

**Required:**
- Name the ordinary-limit writer-round consumer.
- Give the per-role figures.
- State the expected exhaustion rate and its existing consequence: `model_call_cap` is re-raised as plumbing (`run.py:512`, `:2715`) and is not a pass.
- Give the operator a recommended default (e.g. "use `:medium` for writers; `:small` only where a role's history fits").

No new mechanism is needed.

### M3: one open-ended instruction is left to the implementer (implementation_readiness: Zero-Decision Rule)

**Where:** design lines 82–83: "Check other exact-model assumptions during implementation and amend design if any additional behavioral change is required."

That defers a decision. I did the sweep; the design should record the result instead.

- **Need no change** (alias flows through as-is):
  - `budget.py:807`: compares `reservation.route` with `configured_model`. Both are the alias, because `model_runtime.py:650` passes `configured_model=model`. Keep that argument.
  - `budget.py:769-771`: parses `--model` only when `configured_model` is None.
  - `budget.py:458-470`: maps roles by alias.
  - `free_models.apply` (`free_models.py:59`): an alias doesn't match the `before` signature, so roles are kept. The paid-to-free cutover never rewrites alias bindings.
  - `model_runtime.py:126` and `:142`, `model_router.family`, `routes()` labels and pools: all keyed on the `claude/` prefix.
  - `model_call_gate.empty_usage` and the `Handler` `paid` test: an alias is not in `GATED_OPENROUTER`, so it takes the Claude path and `CLAUDE_OUTPUT`.
  - Router capacity (`model_router.py:194-196`): counted per account pool. Alias and base share account concurrency, which is correct.
- **Behaviour difference to accept and state:** router outage health is keyed `pool/route` (`model_router.py:187`, `:305`). An outage seen on the base lane doesn't block the alias lane, and vice versa. Quota, credit and credential health stay pool-wide.

**Required:** replace lines 82–83 with this list, or an equivalent one, and note the outage-lane behaviour.

---

## Nits

- **N1:** Line 59 says "exact re-priced aggregate", but $5.152199 is the recorded `list_cost_usd`; the re-priced value is $5.1152906. Tell the test to use the existing `max(list_cost_usd, claude_gate_cost(tokens))` rule. The higher recorded cost probably includes background calls that the result `usage` leaves out.
- **N2:** Mapping aliases in `token_prices.invocation_maximum` (line 68) has no production caller. Only `tests/factory/test_stream_d_runtime.py:90` uses it; runtime admission uses `model_runtime.invocation_maximum`, which reads `lease.max_usd`. Drop it, or say it's for test parity. Only the `claude_cost` mapping is needed, for `budget.py:920`.
- **N3:** Name the tests to extend:
  - `test_runtime_close_mid_response_retains_hold_once` (`:645`, which already has the three HTTP variants);
  - `test_real_writer_partial_estimator_uses_captured_cli_mode_surface` (`:176`);
  - `test_successful_cli_cannot_hide_gate_unknown_usage_in_real_runtime_receipt` (`:749`);
  - `test_real_routes_fail_closed_except_exact_qualified_profiles` (`:78`). Add the two aliases to its `qualified` set plus one unknown alias such as `claude/claude-opus-5-5:large`.
- **N4:** The phasing is implicit. One safe order: token_prices/router → gate → runtime → tests. Each step keeps the suite green.
- **N5:** Line 48: concurrent requests of *any* size serialize, not just full-sized ones (2 × $8 > $15). That includes the CLI's background `ANTHROPIC_SMALL_FAST_MODEL` requests. This is correct behaviour; the wording just understates it.

---

## Checks that passed

- **Heilmeier:**
  - the objective is in plain language (lines 7–12);
  - the earlier approach and its limits are given (lines 13–16);
  - cost ($0 offline), timeline (one session plus reviews) and the mid-term, final and later live exams are present;
  - the funding material has moved to `docs/reports/router-small-claude-funding-20261031.md` (design-1 M4 resolved).
- **Scope is minimal (§4 delete-before-adding):** no new launch path, ledger, selection service or fallback; base is unchanged; unknown aliases stay unbounded; provider-model equality checks stay on the base ID; `--model` maps to the base ID at `model_runtime.py:545/607`; the alias is kept in `configured_model`, `models_used` and receipts.
- **Call sites match code** (design-1 M3 resolved): `route_maximum` (`model_router.py:46`); `Allowance.amount`/`reserve` (`:160`, `:168`); `enforce` (`:645`); `_invoke` (`:545`); `claude_cost` (`token_prices.py:127`). `valid_maximum` compares every field by exact type and value, so an alias-specific `price_source` rejects a forged base maximum.
- **Murphy:** "No row closes" is honest and consistent with the open live exams.

**Blockers open: none. Result: PASS.** M1–M3 should be fixed in the design before implementation. They are Major, not blocking.


## Implementer disposition

Accepted M1–M3 and N1–N5 before implementation: clarified zero unknown tolerance,
ordinary writer consumer and per-role envelope counts, recommended profile,
plumbing exhaustion, outage lanes, exact unchanged alias seams and test names.
Dropped unused invocation_maximum mapping. No blocker remained or was rejected.
