# interfaces design review 17: §8 "D coverage, reconciliation, and diagnosis APIs (increment 3)" and stream-d increment 3

**Verdict: not a PASS. 1 blocker is open (R1).** All five blockers from review 15 and all N1–N5 and M1–M5 fixes from review 16 have landed in substance. One case was missed: a rounding-only decrease with no qualifying receipt still refuses a valid collection. The fix is one sentence on B's side. Nothing in the diff enables runtime work, adds a spend ledger or makes a record name the checkpoint that contains it.

**Reviewer:** fresh goldfish, read-only. Mode: REVIEW. Personas: zoom_out, design_critic, implementation_readiness. Standards: heilmeier-standard.md and implementation-readiness-standard.md.
**Scope:** docs-only diff `4274a48..1cc880a` (09b4471, 1cc880a) in worktree t3-21bef30c, on branch t3/stream-d-implementation:
- `docs/designs/interfaces.md` §8, lines 376–389 and 456–680
- `docs/designs/stream-d.md` lines 918–991

**Not reviewed:** the worktree also has uncommitted, unrelated changes to `factory/budget.py`, `factory/run.py` and a new `factory/diagnosis.py`. They are outside this range, and this review neither covers nor endorses them.

## Reads
- **Persona and standard files:**
  - `tools/egm/agents/{zoom_out,design_critic,implementation_readiness}.md`
  - `tools/egm/document_standards/{heilmeier,implementation-readiness}-standard.md`
- **Engineering rules and prior reviews:**
  - `docs/ENGINEERING.md`, in full
  - `docs/reviews/interfaces-design-15.md` and `-16.md`, in full, including the elephant resolutions
- **interfaces.md:** lines 330–392 and 456–690, verbatim.
- **stream-d.md:**
  - 255–275 (extension history)
  - 498–499 (exhaustion routing)
  - 918–991
  - greps for `$33`, `state`, `exhausted`
- **invalid-runs.md:** 170–190 (the `infrastructure_gate` schema).
- **factory/budget.py at HEAD:**
  - 89–470: `usd`, `_event_components`, `reserve_invocation`, `outstanding_reservations`, `_settle_leaf`, `settle`, `complete_invocation`, `release_uninvoked`, `reconcile_reservations`, `case_spending`
  - 744–800 and 880–912: the streaming accountant, which binds events to rows
- **Other factory files:**
  - `factory/recovery.py` 1–30
  - `factory/gate_pipeline.py` 140–165
  - `factory/model_runtime.py` 280–340
  - `factory/run.py` 340–362 and 1097
  - greps for `infrastructure_gate`, `continuation_budget`, `recovery_config.rounds`, `release_uninvoked`

## Review-16 fixes: what holds
- **N1 (order independence).** A record is emitted per row, on that row's own estimated → settled transition in `_settle_leaf`. Unrelated unknown totals and leaf order are explicitly excluded (547–551). `_settle_leaf` refuses settled → estimated (budget.py:219), and `reconcile_reservations` skips settled rows (332), so "at most one per invocation" holds in code.
- **N2 (replay).** Qualification uses only the immediately previous ACK's `{invocation_id: estimated_gap_usd}` map. The map is replaced on every ACK, including null totals (568–577), and no consumed-ID set exists.
  - I re-ran the review-16 null-P chain (L1 null with X estimated, L2 settles X, L3 known). X is absent from L2's map, so there is no second release.
  - I checked the re-estimation path (estimated → re-estimated → settled). It gives `released = usd(b') + max − floor9(b') − usd(a) ≤ max − floor9(b) = g_prev`. So `released ≤ previous gap` never refuses a legitimate record.
- **N3 (rounding).** `released_usd` is computed from the three nine-place strings (553–555), and ε = (k+1)·1e-9 when k > 0 (578–580). For a qualifying record the per-record error is under 1 nanodollar and the two total roundings add 1 at most, so the bound holds. The review-16 counterexample now passes: P − R − ε = 0 ≤ T.
- **N4.** The older §8 sentence (380–383) now defers to the increment-3 qualification.
- **N5.** The public `extension_history` shape is exact (592–603):
  - lifetime IDs 1..5;
  - "active" means the last `outcome_sha256` is null, and no earlier entry may be active;
  - there is no public `state` field;
  - every substantive failure inside an extension, including a late defect, becomes `extension_incomplete`.
- **M1 (unknown marker joins).** `case_spending.unpriced_events == raw len(unpriced_invocations)` refuses every other unknown, because `case_spending` counts each one into `unpriced` (budget.py:380–456). That covers invalid events, non-numeric aggregates, invalid gaps, invalid waste and invalid `infrastructure_kill` records. Other rules also hold:
  - Markers must match both `invocation_id` and `lease_id`. Legacy markers without IDs give None.
  - Duplicates fold into one row.
  - A marker on an already-settled row gives None.
- **Pure coverage.**
  - Event binding (event_ids, or a matching `invocation_id` and `lease_id`) agrees with the streaming accountant. That accountant appends each event's ID to `row['event_ids']` as it streams (budget.py:762–764, 909), so a crash estimate already counts streamed spend in `booked`, with no double count.
  - Unbound historical events count in full and reduce no row.
  - `covered_total` rounds up once on raw Decimals, so the separately rounded report fields are never used as admission money.
  - Pending rows contribute `max − booked`. That is less conservative than `outstanding_reservations` (which ignores events on pending rows) but still correct, because events stream into `event_ids`.
- **M2 (card-only diagnosis predicates).**
  - The predicates read `card['terminal_stop']` and top-level `diagnosis_state` / `extension_history`.
  - The late-defect predicate uses `recovery_config.rounds`, which really is a card field (run.py:1097).
  - `actual_model_work` counts every event and accountant marker, and consults no private file and no `invoked` flag.
- **M3.** After diagnosis: `close_to_passing` continues in the same worker, `factory_bug` goes to the maintainer queue, and `not_converging` retires (652–656).
- **M4.** The all-event wording for model work is fixed (619–625).
- **M5.** The real-ledger test plan is restored and extended (670–680).
- **Scope.**
  - No runtime enablement (interfaces 458; stream-d 955–958, 978, 991).
  - `case_spending` ignores the new records (589–590).
  - Decreases release no held authority and transfer no headroom (583–588).

## Blocker

### R1. A rounding-only decrease with no qualifying record still refuses a valid collection (interfaces 553–556 and 578–582)
The ε allowance applies only when k > 0, and D emits a record only when `released_usd > 0` at nine places. A sub-nanodollar settlement or re-estimate can lower the rounded total by 1 nanodollar while producing no record. The rule "with no qualifying record, any unsupported decrease still refuses" then stops a valid collection, which is the same pit-stop class as N3.

**Counterexample 1** (all values reachable with real float event costs):
1. Other spend X has a raw value of 5e-10: a float event cost or a legacy remainder, counted because `usd(5e-10)` = 0.000000001.
2. Row Y is estimated after a crash with no receipt: event_ids [], gap = 10.000000000. Previous ACK: P = usd(10.0000000005) = 10.000000001.
3. A late final receipt arrives with raw actual charge 9.9999999996. The record strings are booked_before 0.000000000, previous_estimate 10.000000000 and actual usd(…) = 10.000000000, so released = 0 and nothing is emitted.
4. T = usd(10.0000000001) = 10.000000000, which is P − 1 nanodollar, with k = 0. B refuses.

**Counterexample 2:** a row in the previous map is re-estimated (a non-final receipt with more events) without settling. Its raw `booked + ceil9(max − booked)` can fall by up to 1 nanodollar, for example from booked 0.9e-9 to 1.0e-9. That again gives T = P − 1 nanodollar with no record.

When re-estimation and settlement are combined, the error per record can reach 1.5 nanodollars, so (k+1) is also too tight from k ≥ 3.

**Fix (B side, one sentence):** whenever P and T are both known, accept iff T ≥ P − R − ε, with ε = (2·|M| + 1)·0.000000001. Here M is the previous ACK's estimated map, which B already persists.
- Only rows in M can lower the rounded total: pending rows add charges or ceil-rounded gaps, and in-run estimates were never in P.
- Each row in M contributes less than 2 nanodollars of rounding loss, and the two total roundings add less than 1.
- The bound is fixed, needs no new state, and creates no commitment or headroom, because held authority is still held.
- Add a real-ledger replay with a released-rounds-to-zero settlement and a re-estimated row.

## Majors (non-blocking; fix before implementation)

**J1. The `infrastructure_gate.exhausted` marker never clears, which corrupts later replacement eligibility (interfaces 606–610 and 629–630).**
- `recovery.infrastructure_exhausted(card)` also reads `infrastructure_gate.exhausted`. Nothing in `factory/` ever clears that marker: `gate_pipeline.py:150` even skips re-recording it.
- Once a case has exhausted on infrastructure and later resumes after a factory-bug fix, every later budget or rounds exhaustion will:
  - be relabelled `diagnosis_state.stop = "infrastructure_exhausted"`;
  - get `replacement_eligible = false`.

  ENGINEERING §3 requires a replacement at once for those exhaustions.
- **Fix:** base replacement eligibility on the current exhaustion, as `diagnosis_state.stop != "infrastructure_exhausted"`. Also state that a factory-bug resume archives or clears `infrastructure_gate`. (invalid-runs currently makes restart refuse exhausted states, so also say how such a resume is admitted.)
- This fails closed (no replacement rather than an extra one), which is why it is a Major.

**J2. `release_uninvoked` can settle an estimated row without a record (budget.py:314–319).**
- It settles any row that has no event_ids, including a crash-estimated row with gap = max, and emits no `reconciled_decrease`. B would then refuse the lower total.
- Today it is only called on a lease reserved in the current call, which is a pending row, so the path looks unreachable. The contract should still make it a D producer invariant: `release_uninvoked` refuses non-pending rows. Add it to D's tests.

## Nits (optional)
- **stream-d 267 vs interfaces 599–600.** stream-d still lists a stored private `state` (active/complete) on the "immutable" entry. interfaces says the private state is derived. Pick one: delete `state` from stream-d 267, or say that it is the only mutable private field.
- **booked_total_usd vs covered_total_usd.** `booked_total_usd` is derived from `case_spending`'s rounded float, while `covered_total_usd` uses raw Decimals. State that the implementation exposes one shared raw helper from `case_spending` rather than re-parsing floats. Each is fine alone.
- **Old nits still open.** The `wait_id` field in the record is still unused by B (YAGNI). The `batch-money/` paragraph has been moved under its own heading, which closes that older nit.
- **The `max_total_calls` → telemetry ruling** (stream-d 920–925) is honestly labelled as the parent's ruling. Since it touches no §4 rule or security property, founder approval isn't required under ENGINEERING §1.

## Heilmeier / readiness
- **Heilmeier:** the objective is clear: make D's money and diagnosis facts callable by B without copying predicates. So are the limits of current practice (B lacks coverage, reconciliation and projection rules), the payoff (B's increment2b can enable conservative resume and replacement safely) and the risks (no runtime enablement, fail-closed refusals). Cost and timeline are N/A for a docs contract.
- **Readiness:** the shapes, field names, owners, purity rules and test list are exact enough for B to implement against. The only implementer decision left is the rounding allowance in R1.

## Required tests (no Murphy row closes)
Review 16's list stands, plus:
- R1: a released-rounds-to-zero settlement, and a re-estimated row with a sub-nanodollar boundary, both accepted;
- J1: an infrastructure-exhausted case, then a factory-bug resume, then a budget exhaustion that is replacement-eligible;
- J2: `release_uninvoked` refuses an estimated row.

---

Close R1 before B enables increment2b; it is the only blocker. J1 and J2 should be fixed in the same pass so the D implementation doesn't inherit them.

## Elephant resolution
(to be filled)

## Elephant resolution

R1 accepted: use epsilon=(2*len(M)+1) nanodollars on every known-total ACK,
where M is the immediately previous estimated map. J1 accepted: identify the
current exhaustion from validated diagnosis_state; reviewed factory-bug resume
archives/clears infrastructure_gate. J2 accepted: release_uninvoked refuses
non-pending rows. Private history state is derived; coverage shares the raw
Decimal valuation helper. No finding rejected and no row closed.

The parent additionally ruled that B requires a PRESENT eligible projection
for first replacement derivation; None is never permission. This landed in
683ec05 after the reviewed range and requires the next fresh review.
