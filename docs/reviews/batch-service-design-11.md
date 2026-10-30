No implementation or activation readiness: as a draft it is incomplete, with 1 blocker and 5 major findings. The full review for `docs/reviews/batch-service-design-11.md` is below; I did not save it. Every step was read-only: I edited nothing in the worktree or the parent checkout, and I did not run the test suite.

---

# batch-service design review 11: Increment2b.2 draft (D collection accounting proofs)

**Reviewer:** fresh goldfish (read-only). Personas: `zoom_out`, `design_critic`, `implementation_readiness`. **Mode: REVIEW**. Standards: `heilmeier-standard.md`, `implementation-readiness-standard.md`.
**Scope:** `docs/designs/batch-service.md` at `fbdce83`, lines 982–1199 ("Increment2b.2 draft"). Checked against `git show 1cc880a:docs/designs/interfaces.md` §8, mainly "D coverage, reconciliation, and diagnosis APIs (increment 3)" at lines 457–666, plus "Conservative resume" and "Replacement derivation". Also checked against the existing `factory/batch_money.py`, `factory/batch_service.py` and `factory/budget.py` in worktree `t3-ded79ec5`.
**Context given by the parent:** the D contract exists but has not been reviewed. This is a draft: nothing is merged or enabled until the parent reports a D interface PASS. `DIAGNOSIS_ENABLED` stays `False`. The present-projection rule was already reviewed at `175cba3`/`165a0fd`. Host composition gates are deliberately the next piece of work and are not claimed here.
**Test status:** not run by this reviewer. The full-suite result after the correction is being checked separately, and this review does not infer that it passes.

## Verdict

**DRAFT: NOT READY FOR IMPLEMENTATION OR ACTIVATION.** 1 Blocker and 5 Major findings are open. Even after they are fixed, this design gives no implementation or activation readiness until all of these have happened:
1. D's interface and implementation are reviewed and pass, at a named SHA.
2. This draft is reconciled against that SHA.
3. A final B design review passes.

After that, the usual implementation, full-suite and diff-review steps apply. `DIAGNOSIS_ENABLED` must stay `False`.

## What matches the D contract (no finding)

- **Coverage call.** `usage_coverage(continuation_budget)` takes one argument. The draft lists the exact result shape and has no stored or historical `usage_coverage` field. It compares `covered_total_usd` directly to `held` and does not re-sum the rounded per-row amounts. It does not reproduce D's joins, legacy remainders or waste. All of this matches interfaces.md lines 471–513.
- **Decrease receipt fields.** The draft's field set matches 1cc880a, including `booked_before_usd`. It uses `released = booked_before + previous_estimate − actual` in exact nanodollars, requires `released > 0`, and identifies a release by `invocation_id` alone. Hashes are treated as evidence, not identity.
- **Qualification.** A record qualifies when its ID was in the previous ACK's estimated map, the row is now settled, and `0 < released ≤ previous gap`. An in-run estimate counts zero and is not a refusal. Qualification is evaluated even when P or T is null. The estimated map is replaced on every ACK, including null-total ACKs. No consumed-ID set is kept. `k` counts distinct IDs, `epsilon = (k+1)` nanodollars, and acceptance is `T ≥ P − R − epsilon`. A null P permits a known `T ≤ held`. All of this matches lines 556–580.
- **Feasibility.**
  - `budget.py:165,235–236` already writes `invocation_id` (UUID4), `state ∈ {pending, estimated, settled}` and a canonical `format(estimate,'.9f')` gap string. The estimated-map extraction is therefore feasible.
  - `case_spending`'s `models_used` affects only `breakdown`, not `total_spent_usd` (`budget.py:319–329`). The total-agreement check without `models_used` is sound.
  - `batch_money.amount` already gives exact integer nanodollars.
- **Projection rule.** Lines 1158–1166 restate the parent ruling: present `replacement_eligible:true` is required, None never derives, the child and its generation are preserved, and no stop predicates are copied. This matches the reviewed `_replacement` code in `batch_service.py`.
- **Boundaries.** The pure function cannot authenticate where its inputs came from. It does no I/O, uses no clock and moves no money. These are stated plainly (lines 1012–1016, 1033–1035).

## Findings

### 1. Blocker: an overrun ACK refusal leaves real spend uncounted, contradicting the existing money logic
**Scope:** lines 1083–1084 ("Known totals must also be <= held; an accounting overrun refuses new authority…") and line 1121. Compared with `factory/batch_money.py:140`, interfaces.md lines 314–317 and 500–501 ("Actual charges exceeding a maximum count in full; no spend is truncated").

**The flaw:** the current conservation code counts each owner as `max(committed, collected_total)`. A collected total above the commitment is a supported state and is counted in full. The draft makes `collection_facts` *raise* whenever a known `T > held`. Because the function raises, no money-state write happens, `collected_total_usd` stays at P, and the batch sum counts that owner at `max(held, P) < T`. Other owners then get headroom that has already been spent. The draft also calls this "never a zero or a refund", but in effect it under-counts.

The D contract only requires `T ≤ held` in the null-P case (line 576). It does not impose this on every known total. The draft therefore creates a stricter rule on the B side, and that rule conflicts with B's own aggregate.

**Recommendation:** pick one, and state it explicitly:
- **(a)** A known T that passes the P−R−ε check is always returned and ACKed, so it is recorded in full. An overrun only marks the owner as blocked for new authority or revision and raises an incident. The output gains no new field, because the host compares `total_usd` with `held` itself.
- **(b)** Keep the refusal, and also say what conservation counts for a refused-but-authentic collection. It must count at least T, so it cannot be a bare refusal.

The same question applies to null-P with `T > held` and to null-T with `covered > held`, which D requires to refuse. The draft must say what the batch aggregate holds for that owner afterwards: full held plus an incident, owner blocked. This is a B-side decision and needs no new D contract.

### 2. Major: the older increment-2 receipt rule is still in the doc and contradicts this draft
**Scope:** lines 653–663 ("Acknowledge it only when D's authenticated settlement matches an existing unpriced invocation ID or wait_id…") and lines 469–471 ("verify its invocation/wait ID"), compared with lines 1191–1193 ("replaces the speculative accounting proof language in the increment2 addendum").

**The flaw:** under D's contract, a pending (unpriced) row produces *no* decrease record. A record qualifies only when it was *estimated in the previous ACK*. The older text says the opposite, and the draft only claims to replace it without editing it. An implementer reading the design top to bottom gets two incompatible qualification rules.

**Recommendation:** in the same commit, amend or strike lines 653–663 and the practice-exam wording at lines 469–471 so they point to 2b.2. Don't rely on a forward reference to override them.

### 3. Major: no mapping from existing money state to `previous` and `held`
**Scope:** lines 1037–1044 and 1127–1129, compared with `batch_money.py:128–152`.

**The flaw:** money rows today hold only `authority` and a non-null `collected_total_usd`. There is no estimated map, no nullable total, and no separate full-held amount. The draft defines the inputs (`previous = {total_usd|null, estimated}` and a separate `held`) and says a "missing historical ACK… refuses outside an explicit reviewed import". It does not say:
- whether an existing schema-1 row (`collected_total_usd:"0.000000000"`, no ACK) counts as the initial state or as a missing ACK;
- what the new row schema is, and whether `schema` changes;
- which code writes the null total and the map (`authorize` writes neither today).

Deferring the format to the "holder addendum" is acceptable for a draft. As written, though, `collection_facts` cannot be fed from real state, so its tests can only use authored inputs.

**Recommendation:** for this increment, state that inputs are built only in tests. Name the row-schema change (or an explicit deferral to the holder addendum) as a precondition for wiring. Decide how existing fresh rows map to `previous`.

### 4. Major: unclear when `usage_coverage` is called
**Scope:** lines 1067–1084.

**The flaw:** the section is titled "Null-total coverage", but its text never limits the call to `T == null`, and the same paragraph applies the held check to known totals. D returns None for some ledgers that have known totals too. For example, a marker that names an already-settled row, or invalid `_event_components`, both return None (lines 484–490). If B calls the API on every card, those cases refuse known-total ACKs that D's contract does not ask B to refuse. If B calls it only for null T, they pass. This is a behaviour choice left to the implementer.

**Recommendation:** state "call `usage_coverage` iff normalized T is null; never on known T", or the reverse with a reason. Add a test for a known-total card where the API would return None.

### 5. Major: matching decrease records to reservation rows is underspecified
**Scope:** lines 1058–1061 and 1107–1114.

**The flaw:** `invocation_reservations` is keyed by lease, and records name an `invocation_id`. The draft says "IDs must be unique" without naming which IDs: lease keys are unique by construction, so it must mean `invocation_id` across rows. It says "The current public reservation for a record must be settled" without saying:
- whether a record with no matching row refuses the checkpoint or simply doesn't qualify;
- whether a record whose row is pending or estimated refuses or doesn't qualify;
- whether this applies to all records or only to candidates in `previous.estimated`.

Line 1114, "Historical records remain harmless", suggests non-qualifying records are ignored, which conflicts with a hard settled check. Different answers change which ledgers can be ACKed.

**Recommendation:** spell out the rule. Suggested wording, which is B-side and consistent with D lines 522–549: "`invocation_id` is unique across rows. Every record must name exactly one row, and that row must be settled; otherwise refuse with `malformed_reconciliation`. Only records whose ID is in `previous.estimated` are candidates for qualification." Add the refusal labels to a fixed list.

### 6. Major: some tests belong to D, and the source of each ledger is not stated
**Scope:** lines 1170–1182.

**The flaw:** "Leaf-order permutations" and "estimated-to-settled once then growing final receipts" test D's producer transitions (`_settle_leaf`). D's contract says "D proves the producer transitions… B proves its ACK inequalities/map updates" (lines 662–664). The draft does not say how B's tests obtain those ledgers. If B writes them by hand, ENGINEERING §4 says they prove nothing. If B drives D's private `_settle_leaf`, B depends on D internals. The saved 5813be/e15450 artifacts are legacy cards with no reservations or receipts: `e15450-round9-collected-card.json` has `events`/`cost` and no `invocation_reservations`. They can only exercise the legacy/unbound and known-total paths.

**Recommendation:** for each listed case, say which source it uses:
- a saved real card;
- a ledger produced by D's reviewed public settlement path or D's reviewed test fixtures (to be named once D lands);
- an authored owner/ACK input.

Move the leaf-order and growing-receipt producer properties to D's suite. B should keep only the ACK sequence over D-produced ledgers.

### 7. Nit: two definitions of "unknown total"
**Scope:** lines 1046–1048, compared with `batch_service.py:255` (`card.get('case_budget', {}).get('total_spent_usd') is None`).

The scheduler's existing check raises `AttributeError` when `case_budget` is `null`, and it doesn't refuse non-object values the way the draft does. **Recommendation:** have the draft say `_enqueue` uses the same normalization helper, so B has one definition.

### 8. Nit: the `accountant` parameter
**Scope:** line 1003.

Injecting a module that has one production implementation is a seam that exists only for tests. It is acceptable while D's module is unreviewed and the mutation and extra-field refusal tests need a double. Record that this is the reason, and let the double tests be deleted once real-D tests cover the same refusals.

### 9. Nit: Heilmeier timeline and exam
**Scope:** lines 1193–1199.

The cost is given as "one offline increment", but there is no timeline, and no mid-term exam separate from the final practice qualification. Add one line for each. For example: the mid-term exam is the pure suite passing on D-produced ledgers at D's reviewed SHA; the final exam is the practice lifecycle at lines 1184–1189.

## Readiness statement

The draft gives no implementation readiness and no activation readiness. Findings 1–6 must be fixed first. After that, every gate listed under the verdict still applies, `DIAGNOSIS_ENABLED` stays `False`, and nothing is merged or enabled. No Murphy row closes. This review is not evidence that host authentication or source transitions work. It is not a test result.

## Elephant resolution

All findings accepted; none rejected. B1: valid known-P/known-T overruns are
returned and counted in full; new owner authority is blocked. Authentic refused
collections must durably freeze batch admission until reconciliation, retaining
the full hold; wiring this incident state is a holder-schema prerequisite.
M2: replace the old unpriced/wait-ID qualification language in both locations.
M3: this increment has test-built inputs only; specify exact fresh-row conversion
conditions and defer schema migration/ACK writer to the holder addendum.
M4: coverage is called only for null T; add a known-T no-call assertion.
M5: unique invocation IDs across all reservation rows; every record must name
one settled row; malformed mappings refuse, including historical records.
M6: split saved real-card tests, D-produced reviewed fixture sequences, and
authored ACK/contract tests; producer leaf/growing-receipt properties stay in D.
N7: one total-normalization helper for consumer and eventual scheduler wiring.
N8: document the accountant seam as temporary contract-test injection.
N9: add an estimated schedule and a separate offline mid-term exam.
The draft remains unready pending D's reviewed sources and final B design PASS.

Subsequent parent evidence: D interface review18 (bcec881) passes source6055678.
Use that source, which changes epsilon to (2*len(previous.estimated)+1)
nanodollars even with no qualifying receipt. D3a code review/merge still pending.
The next B review includes D18's three obligations: remove predicate fallback,
test pending and completed infrastructure exhaustion through actual D APIs,
and defer extension eligibility to D plus section8 money admission.
