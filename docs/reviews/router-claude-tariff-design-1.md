**FAIL: 0 Blocker, 3 Major, 3 Nit.** I'm treating Majors as blocking findings under `docs/ENGINEERING.md:44`.

What I reviewed: the working tree of `/Users/bugsincode/.t3/worktrees/unbug-bench/t3-b7dfac7a` at HEAD `cb434e3` (`docs/designs/router.md:1067-1150` and `docs/murphy-register.md:66` are uncommitted edits). I read the code the design touches (`factory/token_prices.py`, `factory/model_call_gate.py:151-260`, `factory/budget.py:895-970,1210-1230`), the saved fixtures, and Anthropic's pricing and data-residency pages. I made no edits and ran no tests. As asked, I did not write the review file; the text below is meant to be saved word for word.

```markdown
# router-claude-tariff-design-1 — goldfish design review

Reviewed: docs/designs/router.md §"Claude standard/global tariff correction"
(lines 1067–1150, working tree on t3/router-maxima-rounding @ cb434e3) and
docs/murphy-register.md row new-router-maxima-1 (line 66). Mode: REVIEW.
Standards: zoom-out, heilmeier, implementation-readiness.

Verdict: **FAIL** — 0 Blocker, 3 Major, 3 Nit.

## Independently verified (holds)

- Official pricing page (checked 2026-10-30): Opus 5.5 is $4 input, $5 5m write,
  $8 1h write, $0.20 cache hit, $20 output. The full 1M context is at standard
  rates (no long-context premium). US-only inference_geo costs 1.1x; fast mode
  costs $8/$40 (2x) and stacks. Rates (4, .2, 8, 20) in CLAUDE_GATE_FIELDS order
  are correct; 8 is the conservative 1h write rate.
- Ceilings: 50e6/0.2 = 250,000,000 input; 50e6/20 = 2,500,000 output.
  W = 1e6·$8/M + 32768·$20/M = $8.655360. Matches `Allowance.reserve`, which
  picks the dearest input field.
- Old-cap claim: (50 − 19.041792)/2.2 = $14.07 list. Correct.
- Fixture: router-paid-deepseek.json.gz has exactly 32 Claude `:result`
  receipts. All 32 are speed=standard, inference_geo=global.
  - b741739e…: 110 calls, recorded $15.0531879, 1x estimate $14.9806896,
    34,564,923 input / 213,431 output.
  - 013eaa17…: 135 calls, recorded $19.076881, 1x estimate $19.0400556,
    47,245,956 input / 266,853 output.
- Envelope arithmetic: max(recorded, estimate) + W + HEADROOM is
  $23.708548 and $27.732241, both ≤ $50. Input/output with one worst request
  added are far under 250M / 2.5M.
- Mutation run: at 2.2x the totals are $52.00 and $60.93. Both > $50, so the
  stated mutation test fails for both writers, as required.
- Budget seams: the design correctly names that budget.py strips non-token
  metadata at both places. `partial_usage` keeps only `required` counters
  (budget.py:963-964). The lost-result session sum rebuilds
  `{k: sum(...) for k in required}` (budget.py:1220-1222). Without sticky
  wiring, claude_cost could not see the mode. Wiring is needed and minimal.
- Completed results still book the CLI's own total_cost_usd. Only the
  `partial=True` path calls claude_cost (budget.py:901). No historical repricing.

## Major

### M1 — The safety premise is false for inference_geo
Location: router.md:1069-1071 ("prices modes the gate cannot request …
closed BODY_FIELDS rejects speed/inference_geo"). Also the
unknown-retention design at 1080-1081 and 1101-1105.

The official data-residency page documents a workspace
`default_inference_geo`. It is "the fallback geo" used when a request
omits `inference_geo`, and the response `usage.inference_geo` reports where
inference actually ran. So a body the gate accepts can still be billed at
1.1x, and the receipt will say `"us"`. Fast mode does stay unreachable: it
needs `speed` plus a beta header, and the gate rejects `speed` and supplies
its own beta header.

The outcome happens to be safe, but the design states the wrong reason.
Retaining W (a 1x hold) for an unknown request is sound only because the
reachable premium is small:
- With settled S and k retained W, admission ensures S + (k+1)W ≤ 50.
- Real spend is at most S + 1.1·k·W ≤ 50 − W + 0.1·kW
  < 50 − 8.66 + 4.13 < 50.
- At the fast×US factor of 2.2, five admitted unknowns could really cost
  about $95 against a $50 lease.

Required changes:
- Replace the "cannot request" sentence with the true argument: geo is
  reachable via workspace default and is bounded by the margin above; fast
  is unreachable through the gate.
- Cite the data-residency page.
- Say what operators see if the workspace default is "us": every request is
  unknown, each retains W, and a writer stops after at most 5 requests,
  fail-closed. Say that this is the intended signal, not a regression.

### M2 — The envelope proof is conditional, but stated as unconditional
Location: router.md:1125-1132 ("All valid nonnegative prefixes … cannot hit
this gate cap before its recorded end").

The monotonic step is sound. Validated per-request amounts are
nonnegative, so every prefix of the settled sum is at most the total. That is
an honest proof from real artifacts, not a fabricated replay.

It rests on two unstated assumptions:
- (a) The CLI's aggregate result counters are at least the sum of the
  usage the gate validated for that invocation.
- (b) No request in the run ended as gate-unknown.

The fixture has no trace, so neither can be checked. The gate's view and
the CLI's totals can diverge: requests aborted mid-stream, retried or
overloaded responses, or HTTP that the CLI did not count. Each unknown
retains a full W outside the settled envelope. The real margins are:
- 873d7f: 50 − 23.71 = $26.29, which tolerates 3 unknowns.
- e15450: 50 − 27.73 = $22.27, which tolerates 2 unknowns.

Required changes:
- State (a) and (b) as the proof's hypotheses.
- Give the per-writer unknown-request tolerance (3 and 2) in the design and
  as asserted values in the regression test.
- Reword the conclusion to "under (a) and (b), and with up to N gate-unknown
  requests, the gate cannot stop this run before its recorded end."
- Do not claim more than that.

### M3 — Empty string and the CLI surface are decided without evidence; "estimator and gate consistent" is not shown
Location: router.md:1080-1081 (empty string is unknown), 1106-1112
(budget.py wiring), 1141-1145 (budget-monitor transport test).

The only saved artifacts of the pinned CLI's own output when upstream omits
the mode show it emits `"inference_geo": ""` with `"speed": "standard"`:
- router-maxima-cli-audit.json.gz `pinned_offline_success_probe.final.usage`
- all 8 receipts in router-maxima-linux-gate.json.gz

The gate reads raw HTTP usage, where absent stays absent and is priced.
budget.py reads CLI stream-json `assistant.message.usage`. No fixture shows
whether that surface passes the upstream field through or rewrites absent
to `""`. If it rewrites, every interrupted partial becomes unknown in D while
the gate prices the same request at 1x. That is still fail-closed, but it
contradicts the design's "consistency" claim and its test line "standard
partial usage uses the same 1x formula as the gate".

The proposed transport test uses synthetic envelopes. It would pass whatever
the real CLI emits, so it cannot settle this.

Required changes:
- Name the two surfaces (HTTP usage vs CLI assistant/result usage) and say
  which saved artifact fixes each surface's shape.
- If the CLI assistant shape is unknown, say so and pick one:
  - keep `""` unknown in budget.py and drop the consistency claim for that
    surface, or
  - capture one pinned-CLI assistant event, which must not be invented.
- Make the transport test's envelope copy that captured shape.

## Nit

- **N1 (router.md:1101-1105):** Two mechanisms are described. One is a
  sticky invalid marker in `Usage.merge`; the other is `claude_gate_cost`
  returning None, which `finish` treats as unknown. Pick one so no design
  choice is left to the implementer. The simplest: `merge` sets the existing
  `self.invalid` on a non-priceable mode, which already makes `finish`
  retain the allowance. The shared predicate then lives in token_prices for
  both callers.
- **N2 (router.md:1125-1127):** "Larger of recorded cost and list-rate
  estimate" in the gate's settled totals is conservative but foreign to the
  gate, which never sees total_cost_usd. Say it is a test-only upper bound so
  no one wires recorded cost into `Allowance`.
- **N3 (murphy-register.md:66):**
  - The mitigation should say that "absent" means absent, not null or
    empty, matching the design.
  - The closure note should name the fixture limitation (no request trace)
    and the conditional form of the proof from M2.
  - Otherwise the row's evidence, severity, owner and closure test match the
    brief and the fixture.

## Out of scope (not reviewed)

Cheap-route design and the wall-time fix. Neither is opened here.
```

The main gap is M1. The design says the gate cannot request premium modes, but a workspace default of US-only (1.1x pricing) applies to requests the gate does accept. The fix still holds up, since one full-price hold per unknown request covers a 1.1x premium, but the design gives the wrong reason for it.


## Author response for round 2

M1 fixed by stronger prevention: explicitly normalize outbound inference_geo to
global after rejecting caller overrides, citing the provider's per-request
override/error contract. The design no longer relies on spare headroom for US
premiums. This addresses the finding, not an author rejection.
M2 fixed: name aggregate/unknown hypotheses, assert exact 3/2 unknown tolerances,
and limit the real-artifact closure to the conditional envelope proof.
M3 fixed by actual pinned-Linux-CLI capture: assistant usage preserves missing
mode fields and passes explicit values through. The saved fixture distinguishes
that surface from the final result's empty-string normalization.
N1 clarifies shared predicate, sticky parser invalidation and direct helper
contract. N2 labels recorded-cost max as test-only. N3 clarifies absent and the
conditional fixture limitation in the Murphy row. No finding rejected.
