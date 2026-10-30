**Verdict: not a PASS. 5 blockers are open.** All five fixes from review 15 landed in substance:

- B1: a pure `usage_coverage`, with no stored field.
- B2: unbound historical events count in full.
- B3: one decrease record per invocation_id.
- B4: the T ≥ P − R rule.
- B5: infrastructure exhaustion goes to diagnosis only, `diagnosis_state` is defined, completed diagnoses clear the projection, and work evidence comes from the card only.

What remains:

- **N3:** a rounding mismatch I reproduced by hand, which refuses a valid collection.
- **N2:** a double-release path through acknowledgments that have a null total.
- **N1:** an emission rule whose result depends on settlement order.
- **N4:** an older paragraph in §8 that now contradicts the new matching rule.
- **N5:** an undefined public `extension_history` shape that `exhaustion()` depends on.

Each one has a fix of one or two sentences. Nothing in the diff enables runtime work or adds a spend ledger. I edited nothing. The text below is ready for `docs/reviews/interfaces-design-16.md`.

---

# interfaces design review 16: §8 "D coverage, reconciliation, and diagnosis APIs (increment 3)", plus stream-d increment 3

**Reviewer:** fresh goldfish, read-only. Mode: REVIEW. Personas: zoom_out, design_critic, implementation_readiness. Standards: heilmeier-standard.md and implementation-readiness-standard.md.
**Scope:** committed diff `4274a48..HEAD` (09b4471, docs only), in worktree t3-21bef30c:
- `docs/designs/interfaces.md` lines 456–611
- `docs/designs/stream-d.md` lines 918–979
- the review-15 file

## Reads
- **Persona and standard files:** `tools/egm/agents/{zoom_out,design_critic,implementation_readiness}.md`; `tools/egm/document_standards/{heilmeier,implementation-readiness}-standard.md`.
- **docs/ENGINEERING.md:** all of it, but the shell output came back compressed. I saw the flow, the review/escalation rules, the diagnosis routing and the design rules. I did not see every sentence verbatim.
- **docs/reviews/interfaces-design-15.md:** all of it, verbatim, including the elephant resolution.
- **interfaces.md §8:** lines 276–671 in full. That covers money authority, conservative resume, replacement derivation, the new subsection and worker installation.
- **stream-d.md:**
  - 496–543, verbatim
  - 316–362: partly compressed in the shell output, but the diagnosis schema, routing and factory-bug paragraphs were visible
  - 244–260: compressed, apart from the `extension_history` paragraph at 257–260
  - 918–979, through the diff
  - greps for `extension_history`, `outcome_sha256`, `immutable`, `active extension`, `close_to_passing`
- **invalid-runs.md:** 150–160.
- **factory/budget.py:**
  - 89–135, 137–183, 209–340, 368–472
  - 746–770, 890–910, 1070–1095
- **factory/model_runtime.py:** 356–374 and 395–465.
- **factory/recovery.py:** 1–30.
- **Other factory files:**
  - `factory/key_holder.py` 240–256
  - `factory/coordinator.py` 166–176
  - `factory/sealed_audit.py` 178–190
  - `factory/late_recovery.py` 95–116
  - `factory/run.py` 1090–1100, plus greps for `terminal_stop`, `builder_rounds` and `recovery_config`
- **Not read:** batch-service.md, the rest of stream-d.md, and invalid-runs.md beyond 150–160. As expected, `factory/diagnosis.py`, `usage_coverage` and `reconciled_decreases` don't exist in the code yet.

## Review-15 fixes: what holds
- **B1.** There is a pure `budget.usage_coverage(continuation_budget)` with no stored field (lines 475–476). B's remaining owner, source and commitment checks are listed (510–517).
- **B2.**
  - Unbound historical events count in full and reduce no row (496–499).
  - Duplicate markers fold into one row (490–491).
  - `booked_total_usd` is defined against `case_spending`'s `known_total_spent_usd` minus the gaps, avoiding the shared-name double count (503–505).
- **B3.**
  - The identity is invocation_id alone (529).
  - Records are emitted only on the estimated → settled transition.
  - The `released_usd` formula is per-invocation and has no global old/new totals.
  - Null → known emits nothing (536–537).
- **B4.** T ≥ P − R is defined. Records that don't qualify contribute zero (546–556). Receipt retention is a D invariant, not something B decrypts (541–545).
- **B5.**
  - `infrastructure_exhausted` triggers diagnosis but sets `replacement_eligible` false. It reuses `recovery.infrastructure_exhausted` (565–567 and 581–583; stream-d 936–937 agrees).
  - `diagnosis_state` has an exact shape. A completed diagnosis clears the projection, and a fresh ID is created per distinct exhaustion (587–598).
  - `diagnosis_pending` and `extension_incomplete` both have producers (600–608).
  - `actual_model_work` uses card fields only, with no `invoked` flag (572–577).
  - The late-defect predicate is exact (568–569).
- **Majors from review 15.** `case_spending` ignores the new fields and a test is promised (560–561). Duplicate unknown markers fold.
- **Arithmetic checks against budget.py.**
  - The coverage example (booked 3 under max 10 covers 10) matches `outstanding_reservations` (budget.py:174–181).
  - For an estimated row, booked + remaining equals booked + gap, so `covered_total` equals the numeric total.
  - `released = b + g − a` matches `_settle_leaf` (budget.py:228–237).
  - `released ≤ previous_estimate` always holds, because settlement takes the union of event IDs and charges are nonnegative.
- **Scope.** No runtime enablement (458, 609–611; stream-d 955–958). No new spend ledger, no self-referencing generation, and `coordinator.py:173`'s cost-regression check is unaffected because ledger `cost` aggregates never fall.

## Blockers

### N1. Whether a decrease record is emitted depends on settlement timing, which refuses a valid collection (lines 529–531)
The rule says "Transition from estimated (positive gap counted in a numeric total)". A single `settle()` settles several leaves in one transaction (budget.py:285–289), so whether the total is numeric changes from leaf to leaf, and the result depends on the order of settlement.

**Failure scenario:**
1. L1 is acknowledged with row X estimated, gap 7, and P = 5.
2. The next run adds an unpriced marker Y, so the total becomes null.
3. X then settles with actual charge 8.
4. Because the total is null at that moment, D emits no record for X.
5. Y later resolves, and T < P with R = 0. B refuses the collection, and the case hits a pit stop.

**Fix:** emit whenever the row's own state immediately before that `_settle_leaf` call is `estimated` with `usd(estimated_gap_usd) > 0`, and the call makes it `settled`. Delete "counted in a numeric total". B's qualification (N2) already handles whether the record counts.

### N2. Lineage qualification double-releases through null-total ACKs, and B's retained state is unspecified (lines 546–556)
The rule says "Estimated in an earlier acknowledged ledger of this owner's lineage", combined with "if P is null, any known T is accepted". It doesn't say whether consumption happens on a null-P or null-T ACK.

**Failure scenario:**
1. L1 is acknowledged with X estimated and a null total.
2. L2: X settles and releases 2. P is null, so B takes the early-accept branch and doesn't mark X consumed.
3. L3: P = T₂ and X still qualifies, because it was estimated in L1. R includes 2 again, so B accepts an unsupported $2 decrease.

B's retention is also unspecified. It isn't clear which earlier ledgers B keeps, or for how long.

**Fix, which also simplifies:** a record qualifies iff all three hold:
- its invocation_id was `estimated` in the immediately previous acknowledged ledger;
- that row is `settled` in the collected ledger;
- `released_usd ≤` that previous row's `estimated_gap_usd`.

B persists only `{invocation_id: estimated_gap_usd}` for the estimated rows of each ACKed ledger, in that ACK. Rows never go back from settled to estimated (budget.py:219), so each record qualifies exactly once and the consumed-ID set can be deleted. Evaluate qualification on every ACK, including ones where P or T is null. Apply T ≥ P − R only when both are known. A null T goes through coverage. A null P accepts any known T ≤ the held commitment.

### N3. Per-record rounding can't satisfy T ≥ P − R exactly (lines 533 and 549)
`case_spending` rounds the cumulative total once (`usd(model_total + additive_waste)`, budget.py:458). The record fields are rounded separately. Real float event costs and legacy remainders carry sub-nanodollar digits (budget.py:131–133 comment).

**Counterexample:**
- Other spend S = 4e-10 (a legacy remainder). Booked b = 1e-10. Gap g = 9.000000000.
- P = usd(9.0000000005) = 9.000000001.
- After settlement, actual a = 6e-10, so T = usd(1e-9) = 0.000000001.
- The record has `booked_before` = 0.000000000, `actual` = 0.000000001, so released R = 8.999999999.
- P − R = 0.000000002 > T. B refuses a valid collection.

**Fix:** D computes `released_usd` from the three nine-place strings, and B checks exactly that. B accepts iff T ≥ P − R − (k+1)·0.000000001, where k is the number of qualifying records. That bound covers k per-record roundings plus the two total roundings. Add a test on a real ledger with sub-nanodollar event costs.

### N4. An older §8 paragraph contradicts the new matching key (lines 380–386 vs 529–549)
Line 382–383 still says B acknowledges a decrease "only when … a receipt matching an existing `unpriced_invocation` invocation ID or `wait_id`".

Under the new rule, a decrease arises only from an `estimated` row. `_settle_leaf` removes that invocation's unpriced marker when the row becomes estimated (budget.py:255–256). A pending row that still has a marker settles with no record, because null → known is not a decrease. So the old key never matches a record the new rule allows. B's implementer is left with two incompatible rules.

**Fix:** replace that sentence with: "B acknowledges the lower total only under the `reconciled_decrease` qualification in the increment-3 subsection below (an invocation estimated in the previous acknowledged ledger and settled now)."

### N5. The public `extension_history` shape is undefined and contradicts "immutable", but `exhaustion()` depends on it (lines 567–569 and 604–608; stream-d 257–260)
`exhaustion()` needs "no active extension_history entry", and a valid `extension_incomplete` needs a final entry with `state="complete"` and a non-null `outcome_sha256`.

Stream-d defines the entry as immutable, in the checkpoint, and lists no `state` or `outcome_sha256` field. "Active" is never defined. `exhaustion()` is card-only, so the public projection and its update rule must be exact.

The late-defect path during an active extension is also left open:
- `late_recovery.stop_defect` raises `late_defect_needs_ruling:<gate>`.
- An active entry disqualifies that stop.
- If the runner doesn't convert it, the case has no projection and stalls.

**Fix:**
- Define the public card `extension_history` as a list of `{schema_version:1, extension_id:<uuid4>, outcome_sha256:null|<sha256>}`.
- The private immutable checkpoint entry stays as stream-d defines it.
- `outcome_sha256` changes exactly once, from null to a hash, when D completes the outcome.
- "Active" means the last entry has `outcome_sha256 == null`.
- Delete `state`.
- State that any substantive gate failure inside an active extension, including a late defect, completes the outcome and emits `extension_incomplete`, never `late_defect_needs_ruling`.

## Majors (fix with the blockers)

**M1. Coverage misses some unknown parts of the total (lines 489–492).**
- `case_spending` also counts as unpriced:
  - invalid gap rows;
  - invalid waste records;
  - non-numeric aggregates.
- An `infrastructure_kill` record with a non-numeric amount is excluded from the total (budget.py:455–456). That is uncovered unknown spend that the spec's list doesn't name.
- The general "malformed records fail closed" clause arguably covers this, but it isn't exact.
- **Fix:** return None unless `case_spending(ledger).get('unpriced_events', 0) == len(ledger.get('unpriced_invocations', []))`. Use the raw count, before folding. Also return None when a marker names a row that is already `settled`.

**M2. The `exhaustion()` input fields aren't named (lines 565–569).**
- Both `card['terminal_stop']` and `continuation_budget.terminal_stop` exist (run.py:3041; recovery.py:250).
- **Fix:**
  - Read `card['terminal_stop']` only.
  - Store `diagnosis_state` at card top level.
  - When the trigger is `infrastructure_gate.exhausted` and `terminal_stop` differs, set `diagnosis_state.stop` to the literal `"infrastructure_exhausted"`.

**M3. After a completed diagnosis there's no next-step signal for B (lines 591–596 vs line 285).**
- `pending_projection` returns None after `close_to_passing`, but B has an "extension" scheduling class and nothing feeds it.
- **Fix:** add one sentence:
  - a validated `close_to_passing` continues in the same worker run into D's extension admission, so no B projection is needed and an interrupted extension resumes as ordinary same-owner work;
  - `factory_bug` goes through the existing coordinator maintainer queue;
  - `not_converging` retires.

**M4. `actual_model_work` wording (line 573).**
- "Priced/subscription model-usage event" could exclude opencode events. Those carry `cost` with no `priced` key (budget.py:896–903).
- If they're excluded, paid opencode cases could never be replaced.
- **Fix:** "any `continuation_budget.events` entry, whatever its pricing kind or price validity, including cost-0 free routes".

**M5. The test plan was dropped.**
- The diff carries only the `case_spending`-ignores test (560).
- **Fix:** restore review 15's six real-ledger tests (5813be, e15450). Add:
  - N1: a mixed-order settle with a concurrent unpriced marker;
  - N2: a null-P ACK followed by a known ACK, with no second release;
  - N3: a sub-nanodollar boundary;
  - N4: a marker-backed pending row settles with no record;
  - N5: a late defect inside an extension maps to `extension_incomplete`, and "active" detection works;
  - M1: a non-numeric `infrastructure_kill` makes coverage None.

## Nits (optional)
- Drop `wait_id` from the record, under YAGNI. The identity is `invocation_id`, and under N2 B never uses `wait_id`.
- `covered_total_usd` mixes a once-rounded total with per-row rounded `booked_usd`. It can be off by up to k nanodollars at an exact commitment boundary. Either say so, or compute it as `usd(raw)`.
- `pending_projection`'s legacy clause (597–598): say explicitly that legacy imports still need the migration record before B acts on the projection.
- The `batch-money/` paragraph (613–617) still sits under the increment-3 heading. Review 15 raised this nit and it wasn't addressed.

## Elephant resolution
(to be filled)

---

Close N2 and N3 first: N2 can release money twice, and N3 stalls real ledgers on nanodollar rounding.

## Elephant resolution

All blocking concerns and majors are accepted; none is rejected.
N1: the producer transition uses the individual estimated row, independent of unrelated unknown totals or leaf order.
N2: qualify only against the immediately previous ACK's estimated map, replacing that map on every ACK including null totals; no consumed-ID set.
N3: compute receipt release from its nine-place strings; define the bounded nanodollar comparison allowance only when at least one record qualifies.
N4: replace the older matching sentence with the new immediately-previous-ACK qualification.
N5: define the exact public history and completion rule, and convert all substantive extension late defects to extension_incomplete. Extension IDs remain consecutive integers 1..5 as in the passed D design; no UUID is needed for these lifetime ordinal IDs. Public active state derives from null outcome_sha256. The private entry snapshot is immutable; outcome appends once.
M1-M5: require complete unknown coverage, name top-level card fields, specify post-diagnosis control flow and all-event model-work evidence, and restore the real-ledger test plan.
No runtime work is enabled and no Murphy row closes. A fresh review follows.

