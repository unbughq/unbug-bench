**Verdict: not a PASS. 5 blockers are open.** The addition enables nothing and adds no second spend ledger. It also has no generation self-reference: `source_generation` is the input, and `ledger_sha256` hashes `continuation_budget` rather than the checkpoint. Even so, B can't implement increment2b against it yet. The coverage check is underspecified. The replay key for decreases could release the same estimate twice. Three predicates in the projection rely on fields that don't exist or on stop rules that conflict with other docs.

I made no edits. The review text below is ready for `docs/reviews/interfaces-design-15.md`, since 12–14 already exist.

---

# interfaces design review 15 — §8 "D public coverage, reconciliation, and diagnosis projections (increment 3)"

**Reviewer:** fresh goldfish, read-only. Mode: REVIEW. Personas: zoom_out, design_critic, implementation_readiness. Standards: heilmeier-standard.md, implementation-readiness-standard.md.
**Scope:** only the uncommitted additive hunk from `git diff -- docs/designs/interfaces.md`, lines 456–591 in worktree t3-21bef30c.

## Reads
- tools/egm/agents/zoom_out.md, design_critic.md, implementation_readiness.md
- tools/egm/document_standards/heilmeier-standard.md, implementation-readiness-standard.md
- docs/ENGINEERING.md (all)
- docs/designs/interfaces.md §8: lines 276–651 in full (money authority, conservative resume, replacement derivation, the new subsection, worker installation)
- docs/designs/stream-d.md: 316–461 (diagnosis; resume/accounting), 496–543 (exhaustion routing), 742–966 (incremental obligations, increment 2, B obligations, increment 3)
- docs/designs/invalid-runs.md: 150–185 (infrastructure_exhausted)
- docs/designs/batch-service.md: 130–140, 420–430, plus grep hits at 471 and 656
- factory/budget.py: 93–105, 137–471, 1075–1090
- factory/key_holder.py: 240–260, 345–360, 386–400
- factory/model_runtime.py: 440–455
- factory/model_router.py: grep for outcome
- factory/recovery.py: 10–20
- greps: `continuation_budget`, `invoked`, `diagnosis_pending`, `extension_incomplete`, `usage_coverage`, `reconciled_decreases`. `factory/diagnosis.py` does not exist yet, as expected.

## What holds
- The hunk is fail-closed and enables nothing (lines 459, 589–591). No production code changes.
- No generation self-reference. `source_generation` is always the acknowledged input. `ledger_sha256` hashes `continuation_budget`, which excludes `usage_coverage`. B adds the output generation in its own ACK.
- No second spend ledger. Decreases replace a cumulative total and never add a refund event. Held authority stays held until terminal collection.
- The covered-total arithmetic ($3 booked under a $10 maximum covers $10, overruns count in full) matches `outstanding_reservations` and `_settle_leaf`'s `max(0, maximum - booked)` in budget.py.
- The example decrease (3 + 7 → 8, release 2) matches `_settle_leaf`.

## Blockers

### B1. B's coverage check is undefined, and the stored field duplicates the ledger (zoom-out + readiness), lines 475–519
"B validates the projection against the collected ledger" doesn't say what B recomputes. B either:
- trusts D's `booked_usd` and checks only the hash and the sums, or
- re-implements the join of events to reservations.

The second option is predicate copying, which this same hunk forbids for diagnosis (line 589). Everything in `usage_coverage` can be derived from the `continuation_budget` already on the card: `invocation_reservations`, `unpriced_invocations`, events, `wait_settlements`. Storing it adds a second representation that must agree with the ledger, plus the hash binding and the canonical-hash rules.

**Correction (pick one):**
- **(a), preferred:** delete the stored card field. Specify a pure `budget.usage_coverage(continuation_budget) -> dict | None` with the same output shape, minus `ledger_sha256` and the binding fields, which B already holds. B calls it on the verified collected ledger. Same purity rules as the diagnosis functions.
- **(b):** keep the field, and state that B accepts it only if it is byte-equal (canonical JSON) to `budget.usage_coverage(card['continuation_budget'])` and the binding fields equal B's journal and held job_money.

Either way, list B's remaining checks explicitly:
- `covered_total_usd <= held committed_total_usd`;
- case, reservation_id and revision equal the held owner;
- `source_generation` equals the journal's input generation for that worker.

### B2. Coverage rejects every case with a legacy history (exact semantics), lines 501–514
"An unbound event … means no coverage record." Legacy events carry no `invocation_id`/`lease_id`; only factory events do (budget.py:763, 903). Read literally, this disables conservative resume for every real resumed ledger, such as the 5813be replay corpus. The rule is also stricter than safety needs. An unbound event only raises `known_total` and never lowers any `remaining_usd`, so counting it is conservative.

**Correction:** replace that clause with:
- Every event counts once in `known_total_usd`.
- An event contributes to one row's `booked_usd` only if its ID is in that row's `event_ids`, or its `invocation_id` and `lease_id` both match that row.
- An event with no binding reduces no row.
- Refuse coverage only when one event binds to two rows, when metadata names a reservation that doesn't exist, or when `_event_components` fails.

Also define `known_total_usd` against the existing function: `case_spending(ledger)['known_total_spent_usd']` (or `total_spent_usd` when numeric) minus the sum of `estimated_gap_usd`. Or rename it `booked_total_usd`. Today's `case_spending.known_total_spent_usd` includes the gaps, so the shared name invites the very double count the hunk is guarding against.

### B3. The decrease replay key allows double release, and the per-record totals are ill-defined, lines 521–559
**Replay key.** The identity is (invocation_id, receipt_sha256). `_settle_leaf` accepts further final receipts for a row that is already settled (budget.py:219–242), and each has a new hash. "The amount has not already been acknowledged" gives B no key. So a second record for the same invocation is a fresh identity and can release again.

**Totals.** `released_usd` is defined as "the actual decrease in cumulative ledger total". But one `settle()` transaction settles every unsettled leaf (budget.py:283–288), so several records share one transaction and per-record old/new totals have no defined value. When an `unpriced_invocations` entry remains, `total_spent_usd` is null, and the strings-only schema can't represent that.

**Correction:**
1. The identity is `invocation_id` alone. D emits at most one `reconciled_decrease` per invocation_id, ever, and only on that row's transition from `estimated` (gap greater than 0, counted in a numeric total) to `settled`. `receipt_sha256` is evidence, not identity. B refuses any second record for an invocation_id it has acknowledged.
2. Define `released_usd = booked_before + previous_estimate_usd - actual_charge_usd`. Here `actual_charge_usd` is the once-counted charge of the settled row's `event_ids`. If the result is 0 or less, emit no record. Refuse when an event ID is shared with another row.
3. Delete `old_total_usd` and `new_total_usd` from the record. B's ACK already persists its own collected old/new totals (line 555).
4. A pending row whose prior total was unknown (null) settles with no decrease record. Going from null to known is not a decrease.

### B4. B's acceptance rule can refuse a legitimate collection and stall the case, lines 548–557
"Unsupported decreases … refuse ACK," combined with "accepts at most the sum of their unused released_usd", leaves B unable to tell two cases apart:
- a record whose estimate was created and released within one worker run, so it never appeared in an acknowledged ledger;
- an actual decrease in the total.

If B refuses the first, a valid collection is refused and the case hits a pit stop.

**Correction:** state the rule as an inequality.
- Let P be the previous acknowledged total.
- Let R be the sum of `released_usd` over records whose invocation_id was `estimated` in an earlier acknowledged ledger of this owner's lineage and isn't yet in B's ACK set.
- Accept the collected total T only if T ≥ P − R. Then add those invocation_ids to the ACK set.
- Records that don't qualify contribute 0 and are never grounds for refusal.
- Refuse only when T < P − R.
- If P is null (conservative resume), any known T is accepted, subject to `T <= held commitment`.

Separately, say whether B checks receipt retention itself or relies on D's invariant. The receipts are private files inside the encrypted generation, and B's existing readers use the public card (key_holder.py:247). If B can't open them, write that `receipt_sha256` is audit evidence and that retention is a D invariant covered by D's test.

### B5. The projection predicates name fields and states that don't exist or conflict, lines 561–583
1. `infrastructure_exhausted` is listed as an exhaustion trigger. stream-d.md:498–501 ("Exhaustion routing") omits it, and ENGINEERING §3 starts replacement only for rounds/budget exhaustion. Infrastructure failures are retried and unscored. With `replacement_eligible = actual_model_work`, every infrastructure exhaustion would now spawn a replacement chain. invalid-runs.md:156 sends it to diagnosis only.
   **Correction:** either amend stream-d's routing list with a recorded ruling, or keep it in `exhaustion()` for diagnosis and set `replacement_eligible = actual_model_work(card) and not recovery.infrastructure_exhausted(card)`. Reuse the existing helper in recovery.py:14 rather than a new predicate.
2. `diagnosis_pending` and `extension_incomplete` appear nowhere else in the designs or code.
   **Correction:** define each as an exact card field or `terminal_stop` value, and give its producer in stream-d.md.
3. `pending_projection` never goes back to null once a diagnosis outcome exists: extension active, factory-bug resume queued, or retired. B would schedule the diagnosis resume again on every collection and loop on paid diagnosis.
   **Correction:** return None when the card records a completed diagnosis for the current exhaustion (name the field), or once the case is terminal/retired.
4. `actual_model_work` cites "a route receipt explicitly marked `invoked:true`". No such field exists: route outcomes are `done|interrupted|denied` (model_router.py:226), and `invoked` is a local variable in model_runtime.py:449. The function also promises it reads no files, yet receipts are private files.
   **Correction:** define it over card fields only. It is true if and only if `continuation_budget` has any priced or subscription event (historical included), or any `unpriced_invocations` entry. The accountant appends those only after process start (budget.py:1083: `process is not None`). Otherwise false, including for a reservation charged conservatively after a crash with no events. Drop the receipt clause.
5. "An ordinary-round-limit `late_defect_needs_ruling:<gate>`": name the exact card fields that prove the ordinary limit (e.g. round equals `round_limit` with no active extension entry).

## Majors (fix with the blockers)
- **When `usage_coverage` is present** (if B1(b) keeps it). Say whether D emits it on every factory checkpoint where it can be computed, or only when the total is null. B4's lineage check needs the earlier estimated rows, and it can get them from the earlier acknowledged ledger. State that and don't depend on the field being present.
- **Duplicate `unpriced_invocations` entries.** budget.py:1083 appends without a dedup check, unlike complete_invocation at 309. Say whether two entries for the same invocation_id refuse coverage or fold into one row. Recommended: fold, because both map to the same reservation and maximum.
- **`case_spending` must ignore the new fields.** State explicitly that it ignores `reconciled_decreases` (and `usage_coverage`), and add one test asserting totals are unchanged when they're added. This keeps the "no second spend ledger" guarantee checkable.

## Nits (optional)
- Lines 490–491: the "notation only" caveat for null goes away if the example writes `null` directly.
- `reconciled_decreases` could be dropped entirely if B keeps the previous acknowledged ledger and computes `b+g−a` per invocation_id from the before/after rows. Only worth it if B already retains that ledger.
- Line 592 onward (the `batch-money/` paragraph) sits under the new heading but predates this hunk. Consider moving the heading so the increment-3 scope boundary is clear.

## Required tests (closes no Murphy row; docs-only)
Each runs against the real saved 5813be / e15450 ledgers:
- coverage with legacy unbound events present;
- an estimated row going to settled lower, accepted once, then refused on a second receipt for the same invocation;
- a release created and settled within one run that doesn't block the ACK;
- the T ≥ P − R boundary;
- `pending_projection` returning None after a recorded diagnosis outcome;
- a denied-only reservation giving `actual_model_work == False`, and a subscription event giving True.

---

The most important ones to fix first are B3 (one decrease record per invocation_id) and B5.3 (the projection never clears, so diagnosis loops).

## Elephant resolution

All five blocking findings and all majors are accepted. No finding is rejected.
B1: choose (a), a pure budget.usage_coverage(ledger) API; no stored duplicate field.
B2: unbound historical events count fully and reduce no reservation; duplicate unknown markers fold by invocation ID.
B3: one decrease record per invocation ID, only estimated-to-final, with per-invocation released amount and no global old/new totals.
B4: specify T >= P - R; nonqualifying evidence contributes zero without refusing an otherwise valid collection. Private receipt retention is a D invariant, not a B decryption requirement.
B5: infrastructure exhaustion is diagnosis-only; define diagnosis_state and extension_incomplete producers, completed-state clearing, card-only work evidence, and the exact late ordinary-round predicate.
The next fresh goldfish reviews these corrections before any increment-3 implementation. No Murphy row closes.

