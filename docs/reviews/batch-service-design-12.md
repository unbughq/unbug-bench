**Verdict: FAIL, on one Major finding.** The design is consistent with the reviewed D interface (6055678) on everything you asked me to check, but it leaves out one obligation the interface places on B. The fix is one sentence plus one test.

Everything was read-only. I saved nothing, edited nothing, never touched the parent checkout, and ran no tests.

- **All nine findings from review 11 are fixed.** I checked each one against the design text.
- **The new rounding allowance is adopted faithfully.** It is (2×len(M)+1) nanodollars on every comparison where both totals are known, including when no receipt qualifies and when M is empty.
- **D review 18's three B obligations are met.**
  - The old sentence that fell back to D's predicates is gone. A child is derived only from a present projection with `replacement_eligible` exactly true.
  - The design requires actual-D tests showing no child for infrastructure exhaustion, both while diagnosis is pending and after it completes.
  - Extension eligibility is left entirely to D and section 8 money. B only schedules.
- **The open Major:** the interface says B needs an authenticated import record before acting on an old exhausted card that has no `diagnosis_state`. The B design never says this. It can actually happen: entries collected while `DIAGNOSIS_ENABLED` is off are re-planned when it turns on, so an old card could produce a child with no import record.

Four optional nits are in the review text.

---

# batch-service design review 12: Increment2b.2 draft against reviewed D interface 6055678

**Verdict: FAIL. One Major is open; the rest of the scope is consistent with the D contract.** The Increment2b.2 draft and the paragraphs amended in the same diff match `git show 6055678:docs/designs/interfaces.md` §8 on every point checked below, except one B obligation the interface states but this design never adopts (finding 1). Fixing it takes one sentence and one test.

Even with finding 1 fixed, a PASS here would mean **contract consistency only**. It would not mean implementation or activation readiness. D increment3a code is still under diff review and is not merged. The design correctly says it must name D's reviewed, merged implementation SHA and its fixture/test paths, and then pass a final B design review, before any code depends on D. `DIAGNOSIS_ENABLED` stays `False`. No D commit is imported. No model, cloud, VM, crypto or spend action is authorized.

**Reviewer:** fresh goldfish, read-only. **Mode: REVIEW.** Personas: `zoom_out`, `design_critic`, `implementation_readiness`. Standards: `heilmeier-standard.md`, `implementation-readiness-standard.md`.

**Scope:**
- Worktree `t3-ded79ec5`, branch `t3/batch-service-control-vm`.
- Diff `fbdce83..f941923`, touching `docs/designs/batch-service.md` and `docs/reviews/batch-service-design-11.md`.
- Covers the complete "Increment2b.2 draft" section (lines 987–1270) and the earlier paragraphs this diff amended (lines 468–471, 655–663, 794–806).

**Test status:** I did not run any tests. The full-suite result is being checked separately, and nothing in this review depends on it.

## Reads
- `~/.codex/RTK.md`
- `docs/ENGINEERING.md`
- `tools/egm/agents/zoom_out.md`, `design_critic.md`, `implementation_readiness.md`
- `tools/egm/document_standards/heilmeier-standard.md`, `implementation-readiness-standard.md`
- `git diff fbdce83..f941923`
- `docs/designs/batch-service.md` lines 110–125, 455–475, 650–665 and 767–1290
- `docs/reviews/batch-service-design-11.md`, including the elephant resolution
- `git show 6055678:docs/designs/interfaces.md` §8, lines 276–700
- `git show bcec881:docs/reviews/interfaces-design-18.md`
- `factory/batch_money.py:140`; `factory/batch_service.py:20,296`; `factory/budget.py` lines 150–182, 236 and 366–385
- `sealed/case-20261017T212113Z-5813be.scorecard.json` (it has `terminal_stop: paused`, a null total and no `diagnosis_state`)
- Supporting evidence only, not merged-code authority: `git show 8b8ece6 --stat` and `8b8ece6:tests/factory/test_stream_d_projection.py`

## Review-11 fixes verified
- **B1 (an overrun refusal undercounts spend).** Fixed at lines 1110–1123.
  - When both totals are known, pass reconciliation, and T exceeds the held amount, the function returns T in full. The host counts it as `max(held, T)`, which matches `batch_money.py:140`, marks an incident and blocks new authority.
  - The two refusals the interface keeps (null P with known T > held, and null T with covered > held) now freeze all new batch admission. The freeze is durable before the lock is released, survives restart, and keeps the full hold and the refused evidence. The freeze and its reconciliation are correctly listed as holder-schema prerequisites.
- **M2 (contradictory old rules).** Fixed. The rule at lines 655–663 now uses "estimated in the immediately previous ACK and settled now", says identity is invocation_id and never wait_id, and drops the pending/unpriced qualification. The practice-exam text at 468–471 now refers to the bounded rounding allowance.
- **M3 (mapping from money rows to inputs).** Fixed at lines 1022–1028 and 1055–1064.
  - Inputs are built only by tests, and no ACK is persisted.
  - An existing schema-1 row may map to the fresh input only if it is revision 1, has `source_generation:null`, has `collected_total_usd` exactly zero, and the full history proves no prior ACK.
  - The versioned migration and the nullable ACK writer are deferred to the holder addendum as prerequisites.
- **M4 (when coverage is called).** Fixed at lines 1094–1096. `usage_coverage` is called if and only if T is null. A test also asserts no call on a known T, even when the API would return None.
- **M5 (matching receipts to reservation rows).** Fixed at lines 1081–1086 and 1148–1157. `invocation_id` must be unique across all rows, even identical ones. Every record, historical and in-run, must name exactly one settled row; otherwise it refuses with `malformed_reconciliation`. Qualification is checked only after that. The five refusal labels are fixed.
- **M6 (test sources).** Fixed at lines 1215–1244. The tests are split four ways:
  - saved real cards, for known-total and legacy behaviour only;
  - D-produced reviewed ledger sequences, whose paths and SHA must be named at final review;
  - authored ACK maps and held amounts;
  - labelled mutations, for rejection tests only.

  Producer properties stay in D's suite, and B never calls `_settle_leaf`.
- **N7–N9 (optional nits).** All addressed:
  - N7: one shared normalization helper (lines 1075–1077).
  - N8: the accountant seam is declared temporary (1013–1016).
  - N9: a schedule plus separate mid-term and final exams (around 1276–1281).

## Adoption of the reviewed 6055678 rule
- **Rounding allowance.** Lines 1159–1167 state epsilon = (2·len(M)+1) nanodollars for every known-P/known-T comparison, including when no record qualifies and when M is empty. The acceptance test is `T ≥ P − R − ε`. An unsupported decrease above the allowance refuses; a rounding-only decrease within it passes. This matches interfaces 582–588.
- **Estimated map.** M is the immediately previous estimated map, including zero-gap estimated rows (1087–1090). It is replaced on every ACK, including null-total ACKs. That matches interfaces 573–575.
- **Null cases.** Null P permits a known `T ≤ held`. Null T goes through coverage against the full hold. The margin never creates headroom (1165–1167). All three match interfaces 588–591.
- **Coverage.** The API's result shape, the direct `covered_total_usd ≤ held` comparison, the ban on re-summing rounded rows, and the absence of any stored coverage field all match interfaces 482–513.
- **Receipt record.** The exact key set, the exact nanodollar arithmetic, `released > 0`, identity by invocation_id alone, and treating the hash as evidence rather than identity all match interfaces 532–551.
- **Feasibility.** Settled rows cannot become estimated again (`budget.py:236`), and no code removes reservation rows. So the rule that every record must name a settled row does not refuse valid historical records.

## D review 18 obligations
1. **The predicate-fallback sentence is deleted.** Old lines 794–795 are replaced (now 796–799): a child requires a present projection with `replacement_eligible` exactly true; None never derives; the one-child journal is applied first. This agrees with 2b.1 (925–936) and lines 1203–1211. **Met.** See nit 1 for one leftover phrase at line 780.
2. **Actual-D tests for pending and completed infrastructure exhaustion.** Lines 1246–1256 require D's public diagnosis API, run on D's 5813be-based projection fixture, with the returned facts fed into B's journal using authored collection bindings:
   - pending: `replacement_eligible:false`, no child;
   - completed: None, no child, even when both predicates are true.

   The design labels 8b8ece6 correctly as supporting evidence, not authority. `test_stream_d_projection.py` at 8b8ece6 covers both states on an authored copy of the real 5813be card. **Met as a planned obligation.** See nit 2 on naming the paths.
3. **Extensions belong entirely to D and §8 money.** Lines 801–806: D alone decides count, package and progress, and starts admitted extensions. B schedules continuations and authenticated `money_wait` requests under §8. B never decides an extension, needs no extension projection, and grants nothing from a public `close_to_passing` label. This is consistent with lines 118–120 and interfaces 659–661. **Met.** See nit 3 for a leftover scheduling question.

## Findings

### 1. Major: B never adopts the interface's import-record gate for old exhausted cards
**Scope:** 2b.1 lines 913–940, projection handling at lines 1203–1211, and the obligations at 1246–1256. Compared with interfaces 656–658.

**The flaw:** the interface says old exhausted cards without `diagnosis_state` "project pending until the runner records their first ID; B still requires an authenticated explicit import/migration record before acting on any legacy projection". D review 18's lifecycle trace #6 depends on this B-side gate: "No silent authority."

The B design states no such gate anywhere. The only "legacy" sentences (lines 954 and 1064) are about money rows and coverage, not projections.

**Why it can happen:**
- With `DIAGNOSIS_ENABLED` off, `plan` returns `diagnosis_unavailable` and leaves `facts:null` (`batch_service.py:296`; design 893–895, 915).
- So batch generations collected before the D3 runner was deployed stay unplanned and are planned again when the gate flips.
- An exhausted card from such a run carries no `diagnosis_state`. If D projects it as pending with `replacement_eligible:true`, B's rule at 925–927 derives a child with no import record.

**Recommendation:** add one B rule to 2b.1/2b.2. Derivation from a present eligible projection also requires the card to carry D's top-level `diagnosis_state` object, or an authenticated import record. No import-record format exists in this increment, so a card without the field derives nothing.

This is a field-presence binding, not a copied stop predicate. The ordinary same-owner settlement or diagnosis resume is still queued, so the runner records the first ID and a later collection can qualify.

Add one test: an old exhausted card with actual work and no `diagnosis_state`, passed through D's real `pending_projection`, derives no child but keeps the resume. Alternatively, cite a reviewed D rule that projects None for absent state and test that.

### Nits (optional)
1. **Line 780** still calls `exhaustion`/`actual_model_work` B's "eligibility function". Interfaces 640–641 calls them diagnostic helpers, never fallback authorization. Suggested wording: "D's diagnostic predicates (consistency checks only) and its pending projection".
2. **Lines 1224–1226** require exact D source paths and SHA at the final review only for the ledger sequences. Extend that to the projection fixture: `tests/factory/test_stream_d_projection.py` at D's merged reviewed SHA. Also label it as authored D state layered on a real card. The sealed 5813be card is `paused` and has no `diagnosis_state`, so the infrastructure-exhaustion states are authored mutations, not saved artifacts.
3. **Lines 774, 849 and 959** still have an "extension" priority class and a "same-owner extension" test, but B now has no extension projection. Say where that class comes from (for example, the authenticated `money_wait.priority` field in §8), or fold it into ordinary scheduling. Settle this before the dispatcher addendum; it is not needed for 2b.2.
4. **Lines 1118–1123:** the batch-wide freeze keeps money safe, but nothing says what clears it. The holder addendum should say whether reconciliation is automatic (a later authentic collection that passes) or a founder incident. Either way it should be a deliberate exception to ENGINEERING §3's "no pit stop".

## Zoom-out
Nothing in scope is speculative.
- The design reuses `batch_money.amount`, D's `case_spending`/`usage_coverage`, the existing journal and the `max(held, T)` aggregate.
- It adds one pure module, no ledger, no launcher and no new D field.
- The accountant seam is declared temporary.
- The detail level is high but justified by the money-conservation stakes. No altitude finding.

## Heilmeier
- Problem, change and deletions: lines 1001–1007 and 1265–1268.
- Risks: 1282–1283.
- Cost and schedule: one to two sessions after D3a merges and the final B review passes.
- Exams: mid-term is the pure suite on named D-produced ledgers; final is the bounded practice lifecycle.

All are present. Nothing is claimed as done.

## Readiness statement
- No implementation readiness and no activation readiness.
- After finding 1 is fixed, this design can PASS for contract consistency with 6055678 only. Code integration still needs all of the following:
  1. D3a's reviewed, merged implementation SHA;
  2. named D fixture and test paths;
  3. a final B design review against that SHA;
  4. implementation, the full suite and a fresh diff review;
  5. a parent merge.
- `DIAGNOSIS_ENABLED` stays `False` until the activation review and practice qualification.
- No Murphy row closes; rows 6, 27, 28, 35 and 51 remain open. This review is not a test result.

## Elephant resolution
_(to be appended by the elephant)_

## Elephant resolution (recorded after review)

Finding 1 accepted. Before acting on D facts, require a top-level diagnosis_state
object or an authenticated import record. No import format exists here, so a
missing/non-object state refuses projection planning without changing facts or
queue. This is deliberately stricter than the review's suggested legacy resume:
interfaces6055678 requires import before acting on ANY legacy projection, and
an automatic resume must not become a silent import. Ordinary already-authorized
work is not revoked; this gate creates no new launch or resume authority.
Add an actual-D regression for absent state with eligible legacy projection,
known and unknown totals, proving no child/request and unchanged journal.
No finding is rejected; a fresh reviewer checks this chosen resolution.

N1 accepted: call the predicates diagnostic consistency checks. N2 accepted:
name tests/factory/test_stream_d_projection.py at the reviewed merged D SHA and
label authored infrastructure states layered on the real paused5813be card.
N3 accepted: extension priority comes only from an authenticated section8
money_wait.priority request, never a public outcome or invented projection.
N4 accepted: holder reconciliation clears incidents automatically only after
later authentic same-owner evidence is ACKed, all implicated incidents resolve,
and full conservation is recomputed under the same lock. Missing proof keeps
admission frozen; no routine founder approval is added.
No implementation/activation readiness, spend or row closure is claimed.
