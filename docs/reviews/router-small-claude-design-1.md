# Goldfish design review: `docs/designs/router-small-claude.md`

Mode: REVIEW. Personas: zoom_out, design_critic, implementation_readiness. Standards: heilmeier-standard.md, implementation-readiness-standard.md. Branch `t3/router-item8-prereqs` @ 45b89a5; the design file is untracked. Read-only. I made no model calls and touched no credentials. The only computation was local arithmetic over the committed fixtures.

**Verdict: FAIL.** One blocker is open, plus four Major findings and three Nits.

---

### B1 — Blocker: the budget math works, but a profile can only forward about one real request (design_critic / zoom_out: Impact, Risks, proportional scope)

**Where:** design lines 43–61 (the "$1–$4 remains" limitation) and line 48 (the 64-attempt limit). Code: `factory/model_call_gate.py:167-193` (`Allowance.reserve`) and `:550-561` (an upstream reply that isn't a validated 200 settles as an unknown full hold). Evidence: `tests/factory/fixtures/20261029-real-public-cards.json.gz` and `router-paid-deepseek.json.gz`.

The worst-case figures are right: 1M × $4/M + 32768 × $20/M = $4.655360, and 1M × $4/M + 8192 × $20/M = $4.163840. But `reserve` only forwards when `settled + held + worst + HEADROOM ≤ max_usd`. That leaves very little room:

- small: $5 − $4.655360 − $0.000001 = **$0.344639**
- compact: $4.50 − $4.163840 − $0.000001 = **$0.336159**

That room covers all settled spend for the whole invocation. Once validated spend passes about $0.34, the next request is refused, with about $4.66 still unused. The design says it "may exhaust after substantial actual spend even while $1–$4 remains". That is wrong in both amount and direction.

I repriced the saved real Claude receipts at the no-cache tariff:

| Fixture | Real Claude invocations | Uncached total ≤ $0.3446 | Median uncached per invocation | Median uncached per request | Median calls |
|---|---|---|---|---|---|
| public cards | 153 | **1** | $10.93 | ≈$0.41 | 40 |
| router-paid-deepseek | 32 | **0** | $10.93 | ≈$0.38 | 43 |

The real writers the existing test cites made 110 and 135 calls (`test_model_call_maxima.py:116-118`). A typical request at about $0.41 uses up the whole room on its own, so a typical invocation gets one forwarded request.

Three more things make this worse:
- Any non-200 reply (429, 529, 5xx) keeps the full $4.66 hold as unknown, which ends the invocation at once.
- Each background request on `ANTHROPIC_SMALL_FAST_MODEL` (`model_call_gate.py:658`) also takes a full hold.
- Concurrent requests can never run together, because two holds never fit.

So the 64-attempt limit can't be reached in practice, which makes it a YAGNI addition. The profile, as designed, can't carry any role seen in the real artifacts.

**Required:** the design must state the real ceiling: about $0.34 of total settled spend, typically one request. It must then do one of three things:
- name a role whose real per-invocation uncached spend fits under that, with fixture evidence;
- change the hold model and show it is still sound;
- withdraw the profile, or say plainly that it is admission-only scaffolding with no usable role.

It should also drop the 64-attempt limit, or show a reachable case where it binds.

---

### M1 — Major: what happens if the provider writes cache anyway is under-reserved and not stated (design_critic: no-cache contract)

**Where:** design lines 41–45 and 52–54; `model_call_gate.py:197-203`; `token_prices.py:106-111`.

Soundness depends entirely on Anthropic never writing cache when there is no `cache_control`. The design cites the public docs, but the gate forwards `anthropic-beta: claude-code-20250219,oauth-…` with subscription OAuth (`model_call_gate.py:34, 531`), and nothing shows that path follows the same opt-in contract.

If a cache write does happen, the real list cost of one request can reach $8.655360. But the design's fail-closed path only keeps the $4.655360 hold that was reserved. That books roughly $4 less than the actual cost while calling itself "no refund".

**Required:**
- state this leftover exposure explicitly;
- decide what the receipt records for a breached request: the base worst case or the parsed actual, flagged as over-cap;
- decide whether a breach must set `exhaustion` and leave a distinct marker, not just a generic unknown;
- the test at line 85 must assert the booked amount, not just "no headroom".

---

### M2 — Major: the per-profile lease token maxima are not defined (implementation_readiness: Zero-Decision Rule)

**Where:** design lines 26–30; `token_prices.py:119-124`; `model_call_gate.py:180-186`.

`reserve` checks three limits: USD, `max_input_tokens` and `max_output_tokens`. The base profile derives them as `USD×1M / min(rates[:3])` (cache-read $0.20 → 250M) and `USD×1M / output rate`. The design never says how the small profiles derive them.

The choice matters. If the implementer uses the $4 ordinary rate, small gets 1.25M input tokens. Since each hold is 1M, that caps total settled input at 250k, which is a second, unstated ceiling. The `price_source` string format is also left open: it has to differ per profile, or `valid_maximum` cannot tell a forged base maximum from a real one.

**Required:** give exact formulas or literal values for all four `MAXIMUM_FIELDS` for each alias.

---

### M3 — Major: "replace singleton equality checks where needed" is not actionable (implementation_readiness)

**Where:** design lines 26–27 and 65–67.

The plan must list every call site and what it becomes. The ones I found:

- **Router and prices:**
  - `model_router.py:44-46`: `route_maximum`
  - `token_prices.py:114-124`: `claude_gate_cost`, `claude_gate_maximum`
  - `token_prices.py:127`: `claude_cost` → `CLAUDE_PRICES.get(alias)` is currently None. Through `budget.py:919-920` this makes partial estimates unpriced and adds to `unpriced_invocations` (`budget.py:1256`).
- **Gate:**
  - `model_call_gate.py:91, 271, 305`: provider-model equality. This must stay the base ID.
  - `:95`: `CLAUDE_OUTPUT` clamp
  - `:134-138`: `empty_usage` `max_request_output_tokens`
  - `:160, 168-171`: `amount` / `reserve` dispatch. Worst-case input must use the $4 field, not the most expensive one.
  - `:645`: `enforce` route admission
  - `:659`: `CLAUDE_CODE_MAX_OUTPUT_TOKENS`
- **Runtime:** `model_runtime.py:545` takes `model.partition("/")` → `model_id = "claude-opus-5-5:small"`. This needs an explicit mapping to the base ID before the `--model` argument at `:607`.

The design also says the cache_control stripping happens "first validates … then removes". It should name the function: is it `request_body(raw)` taking a profile parameter, or a separate function?

---

### M4 — Major: Heilmeier gaps, and a section that's off scope (zoom_out / Heilmeier)

**Where:** design lines 1–61 and 110–128.

- **Objectives** (lines 7–10) are written entirely in internal jargon ("item 8", "useful-role qualification", "invocation reserves"). A fresh reader can't tell which role or batch outcome this unblocks.
- **Timeline** and implementation **cost** are absent.
- **Mid-term and final exams** (Metrics) are absent: nothing says what result from a later live qualification would count as success.
- The "Read-only funding check" section (lines 110–128) covers OpenRouter credit and free routes. That is a different route family, and this design explicitly puts it out of scope (lines 67–68). Move it to the item-8 tracking record, or say why it gates this change.

---

### Nits

- **N1:** "Same Anthropic family, subscription billing, account-2 preference and account pools" (line 23) holds today without changes: `routes()` labels by `startswith('claude/')` and the route regex allows `:` (`model_router.py:97-117`). Say so, so nobody adds code for it.
- **N2:** Line 75: "saved public cards remain immutable real evidence". Name the actual fixture files (`20261029-real-public-cards.json.gz`, `router-paid-deepseek.json.gz`, `router-claude-mode-cli.json.gz`).
- **N3:** The Murphy statement (lines 102–108) is honest, and no row closes. I checked that rows 9 and 39 exist (`docs/murphy-register.md:19, 49`). Fine as written.

---

### Checks that passed
- **Base profile:** stays unchanged and opt-in; no silent rewrite of roles; no fallback to a larger profile; no new ledger or launch path. Consistent with ENGINEERING §4.
- **Cache_control stripping:** the protocol-location list matches the validator's accepted locations (`model_call_gate.py:67-80, 106, 119-129`). Not editing user data is correct.
- **Real-artifact limits:** stated honestly. Lines 90–91 and 93–94 correctly say the tests don't prove live CLI, TLS, or no-cache quality.

**Blockers open: B1.** Result: **FAIL.**


## Implementer disposition (pending fresh review)

B1/M1 accepted: withdrew no-cache $5/$4.50 proposal. Revised design retains the
existing sound cached request hold with opt-in $10/$15 reservations and real
writer aggregate-envelope evidence. The at-most-$5 target remains explicitly
unmet. No finding rejected. M2/M3 addressed with exact fields and call sites;
M4 with objective, timeline, exams and separate funding record. Nits addressed.
Fresh reviewer must assess the revision; implementer does not certify the fix.
