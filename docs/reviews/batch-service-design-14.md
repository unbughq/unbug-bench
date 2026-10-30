I found two blocking problems, so the design fails this round: it is not ready to implement yet. I ran no paid calls and changed nothing. Two facts behind the findings came from running real D code, not just reading it:

- **5813be card:** the saved card has `case_budget: null`, but D's `case_spending` on its ledger returns a known `13.779870815`.
- **Malformed `diagnosis_state`:** `{}`, `{status:pending}`, an object with a bad `status`, a list or `None` all make D's `exhaustion` return False and `pending_projection` return None.

The review text follows, verbatim.

---

# batch-service design review 14: Increment2b.2 final integration against merged D increment3a (9cb25e6 / cfe616f)

**Verdict: FAIL. Two blocking findings (both Major, implementation readiness). Three Nits.**

## Scope and inputs

- **Personas read first:** `tools/egm/agents/zoom_out.md`, `design_critic.md`, `implementation_readiness.md`. Mode: REVIEW.
- **Standards:** `heilmeier-standard.md`, `implementation-readiness-standard.md`, `docs/ENGINEERING.md`.
- **Design under review:** `docs/designs/batch-service.md` §Increment2b.2, working-tree diff on `t3/batch-service-control-vm` (HEAD 34bffa2).
- **Prior reviews:** `batch-service-design-11/12/13`, with their resolutions.
- **Merged D code:** `factory/budget.py` (`usd`, `_spending`/`case_spending`, `_bound_events`, `usage_coverage`, `_settle_leaf` decrease records) and `factory/diagnosis.py`. Confirmed: `git diff cfe616f HEAD` is empty for these files, for `tests/factory/test_stream_d{,_coverage,_projection}.py`, and for `interfaces.md`.
- **Interface:** `docs/designs/interfaces.md` §8.
- **B code:** `factory/batch_service.py` (`plan`, `_enqueue`, `_replacement`, `_facts`, `_load`) and `tests/factory/test_batch_service.py`.
- **Probes:** I ran real D read-only on the saved cards via `test_stream_d.cards()`. The results are quoted below.

## What the design gets right (checked against real D)

- **Coverage API shape:** `usage_coverage` returns exactly `{schema_version, booked_total_usd, covered_total_usd, invocations:[{invocation_id, lease_id, wait_ids, maximum_usd, booked_usd, remaining_usd}]}`. Rows are sorted by `invocation_id`, `wait_ids` are sorted, and `covered_total_usd` is rounded once with ROUND_CEILING from a raw Decimal sum. This matches the design's null-coverage section, including "compare covered_total_usd directly to held; do not sum rounded rows".
- **Decrease record shape:** `_settle_leaf` emits exactly the nine keys the design lists. It emits only when `released > 0`, and refuses a second record for the same `invocation_id` (`usage_receipt_regressed`). This matches the "identity is invocation_id alone" rule, and the B-side arithmetic check `released = booked_before + previous_estimate − actual`.
- **D-produced ledger sequences:** these exist in `test_stream_d_coverage.py` at cfe616f:
  - 10-to-8 release: `test_wait_replay_retains_new_lease_provenance`.
  - Release once, then a growing final receipt with no second record, plus authored duplicate metadata leaving `case_spending` unchanged: `test_estimate_to_final_receipt_retained_once_and_metadata_never_books`.
  - Null total with a release present: `test_other_unknown_does_not_suppress_release_and_pending_settle_emits_none`.
  - Sub-nanodollar re-estimate and zero-rounded release: `test_reestimate_…` and `test_release_uninvoked_…`.

  These are an adequate producer basis for the P-R-epsilon, estimated-map replacement and null-P/null-T sequences. B authors the previous maps and held amounts on top.
- **Projection fixtures:** `test_stream_d_projection.py` gives the authored-on-real-5813be infrastructure states.
  - Pending infrastructure returns `replacement_eligible:false`.
  - Completed infrastructure returns None, while `exhaustion` and `actual_model_work` are both still True.
  - This is what B needs for "no child from absent/completed infrastructure projection". The design's existing `_replacement` requires a present projection with `replacement_eligible`, so no child is derived in either state.
- **Unchanged rules:** P-R-epsilon (`(2·len(M)+1)` nanodollars on every known/known comparison), known-overrun returning full T, the null-T-only coverage call, full estimated-map replacement on every success, and "no money ACK / holder / source grant / adapter stays False" are all stated without ambiguity. They are unchanged from the contract that review 13 passed.
- **Review 13's three Nits:** the gate-order wording ("after snapshot verification and disabled-adapter check, before stored-facts replay or importing D") and non-exhausted coverage are addressed. Malformed-object coverage is addressed in intent; see Blocker 1 for its correctness.

## Blocking findings

### B1 (Major, implementation readiness / faulty assumption): the malformed-`diagnosis_state` behaviour the design pins contradicts real D

The design says (status paragraph): *"A malformed object may yield no projection while an exhausted unknown owner still queues settlement; that queue grants no money. Regressions pin this behavior."*

In merged D, `exhaustion()` returns False for any card that carries a `diagnosis_state` key whose contents fail `_state`:

```python
if 'diagnosis_state' in card and _state(card, history) is None: return False
```

Probe on the 5813be-based fixture (`terminal_stop=budget_exhausted`, unknown total):

| `diagnosis_state` | `exhaustion` | `pending_projection` |
|---|---|---|
| (absent) | True | eligible:true |
| `{}` | False | None |
| `{status:pending}` | False | None |
| valid keys, bad status | False | None |
| `[]` | False | None |
| `null` | False | None |

So with real D, no malformed object ever produces "an exhausted unknown owner". B's `_enqueue` condition `facts['exhaustion'] and unknown` is False and `pending_projection` is None, so B queues nothing: no settlement resume and no child.

An implementer who writes the promised regression against real D sees the opposite of the design text. They must then choose one of two paths:
- assert "no request", which contradicts the design; or
- make B infer exhaustion itself to restore the settlement request, which copies D's stop predicates and violates the design's own "B copies no stop predicates" rule.

That is a design decision handed to the implementer, so it fails the Zero-Decision Rule.

There is also an unstated consequence. An exhausted, unknown-total owner with a corrupt `diagnosis_state` keeps its full hold with no queued settlement. That is a quiet hang, which is exactly the kind of failure the Murphy register exists to record.

**Required:** state the real behaviour: a malformed object gives `exhaustion:false`, None, and no request of any kind. The regression must assert that against real D's `exhaustion`/`pending_projection` for unknown and known totals. Also add one line saying where this stranded-hold case is handled before activation (D fail-closed incident, or holder batch freeze). If none exists, add a `new-batch-service-<n>` Murphy row. Do not reintroduce a B-side exhaustion inference.

### B2 (Major, real-D fixture adequacy): the expected outcomes for the "unmodified saved 5813be/e15450" tests are undetermined, because 5813be's card and ledger disagree

The test plan says: *"Unmodified saved 5813be/e15450 card ledgers exercise known-total and legacy/unbound-event behavior through reviewed D APIs."* The consumer rule says: *"Call accountant.case_spending … require its total to agree after the same normalization with the card total (including null)."*

Probe on the saved cards:

| card | card `case_budget` | D `case_spending.total_spent_usd` | D `usage_coverage.covered_total_usd` | reservation rows |
|---|---|---|---|---|
| e15450 | `{total_spent_usd: 52.786583492}` | 52.786583492 | 52.786583493 | 0 |
| 5813be | `null` | 13.779870815 | 13.779870815 | 0 |

This has four consequences:

1. **The unmodified 5813be card refuses.** Under the agreement rule its normalized card T is null, but D reports a known total. So the card cannot exercise "known-total behaviour" through `collection_facts`. The design neither says this refusal is the expected result nor which of the five fixed labels it carries. The labels are listed, but only `malformed_reconciliation` is mapped to conditions; the card-vs-D disagreement could be either `invalid_accounting_input` or `accounting_api_refused`.
2. **Neither saved ledger reaches the coverage call through `collection_facts`.** `usage_coverage` is called only when T is null, and the agreement rule requires D's total to be null too. Neither saved ledger has a null D total, so no unmodified saved card exercises "legacy/unbound-event behaviour" through `collection_facts`. That proof exists only in D's direct test (`test_legacy_coverage_is_pure_and_uses_raw_total`). The B null-T path must therefore rely on D-produced unknown-marker ledgers.
3. **The real-D projection regressions inherit `case_budget:null`.** Those regressions sit on the 5813be card, so B's new total-normalization helper classifies them as unknown even though D's ledger is known. The pending-infrastructure state then queues a `settlement` resume. The completed-infrastructure state (projection None, `exhaustion` True) also queues a `settlement` resume. The design only says "no child" for these regressions. It does not give the full expected queue, nor say whether the fixture keeps the real `case_budget:null` or authors a known total.
4. **Covering known and unknown totals needs an authored total.** For the legacy provenance regression, which must cover both, the known variant needs an authored `case_budget`. The design should say so explicitly. As written, "unmodified" is misleading.

**Required:** state the expected result for each saved card:
- e15450 unmodified: known T passes. Pair it with authored previous/held values.
- 5813be unmodified: refuses with a named label on card-null versus D-known. Pin this as a real legacy shape.
- 5813be known-total variant (if wanted): authors `case_budget.total_spent_usd` equal to D's total and is labelled as authored.

Also:
- Map every refusal condition to exactly one fixed label, at least: card/D total disagreement, API None/exception/mutation, coverage > held, null-P with T > held, and T < P−R−ε.
- State the full expected queue (reason and kind) for the pending and completed infrastructure regressions, given the 5813be `case_budget:null`.
- Name which D harness methods supply each B ledger sequence, or state that B re-drives `budget.settle`/`complete_invocation` itself via `test_stream_d.AccountingTests` helpers, as `test_stream_d_coverage.py` already does.

## Nits (optional)

1. **Gate and adapter-off replay.** In `plan`, the disabled-adapter check sits inside the `facts is None` branch, so stored facts currently replay whatever the flag says. "After the disabled-adapter check, but before stored-facts replay" therefore requires restructuring `plan`. Say whether a stored-facts entry is gated when the adapter is off. In production this cannot occur, because facts are written only while enabled, but tests patch the flag.
2. **Activation consequence of the gate on non-exhausted cards.** Per `interfaces.md`, D's runner writes `diagnosis_state` only on first exhaustion. So once the adapter is enabled, every non-exhausted card from the new runner refuses with `legacy_projection_unbound`. That is harmless now, because `_enqueue` queues nothing for non-exhausted cards. But the activation review must either have the runner always write the field or narrow the gate. The current label also mis-names such cards as "legacy". Record this as an activation prerequisite.
3. **Rounding direction.** B normalizes "upward once"; D's `usd()` rounds ROUND_HALF_UP and `case_spending` returns `float(usd(total))`. Agreement holds for card totals written from `case_spending` output, as with e15450. However, a hand-written or legacy card total with more than nine decimal places that sits below the half-way point would round up in B and down in D, and would refuse as a disagreement. One sentence, or one authored test, should pin this as intended fail-closed behaviour.

## Prior findings

- Reviews 11, 12 and 13: all previously resolved findings stay resolved. No finding was rejected.
- Review 13's Nit 3 (malformed-state test) is superseded by B1: the test it asked for now has a wrong expected outcome.

## Readiness summary

| Requirement | Status |
|---|---|
| Strict legacy provenance gate before D/facts replay | Specified; Nit 1 on adapter-off ordering |
| No child from absent/completed infrastructure projection | Met by real D fixture + existing `_replacement`; full expected queue missing (B2.3) |
| Canonical accounting shapes | Match real D exactly |
| P-R-epsilon, known overrun, estimated-map replacement | Specified; producer sequences exist at cfe616f |
| Null coverage | API shape matches; unmodified saved cards cannot reach it (B2.2) |
| Malformed `diagnosis_state` | **Contradicts real D (B1)** |
| Queue total normalization (`case_budget:null`) | Scoped correctly; interacts with the 5813be fixture (B2.3) |
| Adapter False; no holder/ACK/source grant | Held |

Activation readiness was not assessed, as instructed.

---

**Elephant resolution:** (to be filled by the design author)


## Elephant resolution

B1 accepted: the design now follows real D (false/None/no queue for malformed
objects at both totals), without B exhaustion inference. New Murphy row
new-batch-service-3 keeps incident/freeze recovery an activation prerequisite.
B2 accepted: saved e15450 passes; saved 5813be refuses invalid_accounting_input;
known variants are explicitly authored. Fixed labels, full known/unknown
infrastructure queue outcomes, and exact D harness methods are specified.
All nits addressed: adapter-off blocks stored facts; absent non-exhausted state
is an activation prerequisite; higher-precision disagreement is fail-closed.
No finding rejected. Submitted for fresh design15 review.
