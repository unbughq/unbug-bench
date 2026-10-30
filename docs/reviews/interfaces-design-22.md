# interfaces design review 18: §8 "D coverage, reconciliation, and diagnosis APIs (increment 3)" after the review-17 fixes and the parent ruling (683ec05)

**Verdict: PASS. No blocker is open in the reviewed scope.** One Major sits outside the diff: `docs/designs/batch-service.md:794–795` still states the replacement rule that the parent ruling replaced. B must fix that sentence in its own increment2b change before it implements the adapter. Three Nits are optional.

**Reviewer:** fresh goldfish, read-only. Mode: REVIEW. Personas: zoom_out, design_critic, implementation_readiness. Standards: heilmeier-standard.md, implementation-readiness-standard.md.

**Scope:** docs-only cumulative diff `4274a48..6055678` (commits 09b4471, 1cc880a, 683ec05, 6055678) in worktree t3-21bef30c, branch `t3/stream-d-implementation`. I checked it against surrounding interfaces §§2, 3, 5, 7, 8 and the passed `docs/designs/stream-d.md`. The uncommitted code and tests are implementation drafts and were not reviewed. I opened them only as supporting evidence.

## Reads
- `tools/egm/agents/zoom_out.md`, `design_critic.md`, `implementation_readiness.md`
- `tools/egm/document_standards/heilmeier-standard.md`, `implementation-readiness-standard.md`
- `docs/ENGINEERING.md` (all)
- `docs/reviews/interfaces-design-15.md`, `-16.md`, `-17.md`, including the elephant resolutions
- `git diff 4274a48..6055678 -- docs/designs/interfaces.md docs/designs/stream-d.md`, and `git show 683ec05`
- `docs/designs/interfaces.md` 339–466 and 467–696 in full
- `docs/designs/stream-d.md` 316–365, 850–880, 935–1000
- `docs/designs/batch-service.md` 128–170 and 775–848
- `factory/recovery.py` 1–30; `factory/gate_pipeline.py` 140–160; `factory/budget.py` at HEAD (reservation `state` field and `release_uninvoked` guard, lines 156–181 and 370–375)
- Supporting evidence only: uncommitted `factory/diagnosis.py` and `tests/factory/test_stream_d_projection.py`

## Review-17 fixes verified
- **R1 (rounding-only decrease refuses a valid collection).** Fixed at interfaces 582–588. The rule is `epsilon = (2*len(M)+1)` nanodollars, where M is the immediately previous ACK's estimated map, and it applies to every known-P/known-T ACK, whether or not any record qualifies.
  - Each row in M can lose less than 2 nanodollars, which covers review 17's 1.5-nanodollar worst case per record. The final total rounding adds less than 1.
  - Qualifying records are a subset of M, so R and epsilon cannot double-count a row.
  - An unsupported decrease larger than the allowance still refuses (585–587).
  - The margin creates no commitment and moves no headroom to another owner (590–591).
- **J1 (stale `infrastructure_gate` marker).** Fixed at interfaces 635–637 and 663–667.
  - When `diagnosis_state.stop` is valid, it identifies the current exhaustion. Legacy cards fall back to `recovery.infrastructure_exhausted`.
  - A reviewed factory-bug resume archives and clears the marker before it does any work.
  - Clearing is also required for correctness: `gate_pipeline.py:150` silently ignores later infrastructure stops while `exhausted` is still set.
- **J2 (`release_uninvoked` on an estimated row).** Fixed at interfaces 562–563. HEAD `budget.py:374` already refuses `state != 'pending' or event_ids`. The contract now names the estimated-with-no-events case, and only settlement can release that row's gap.
- **Derived private state and the raw valuation helper.** Both are clarified: private state is derived (604–606), and the shared raw valuation helper is named (519–528).

## Parent ruling (683ec05): consistency check
I traced every lifecycle path against interfaces 404–415, 632–644 and 646–667, and stream-d 992–1000.

1. **First known-total exhaustion with actual work.**
   - The runner creates the `exhaustion_id` once, before the checkpoint (649).
   - Diagnosis never runs in the run that hit exhaustion. It runs on the ordinary same-owner resume (363–365, 418; batch-service 780–792, 843–844).
   - So the first collected card shows `status:"pending"` with `replacement_eligible:true`. B derives immediately and does not wait for diagnosis.
2. **First exhaustion with an unknown total.**
   - The projection is present and eligible, but admission stays blocked (375–377).
   - The settlement resume exits as `diagnosis_pending`, still with the same pending ID (669–672). B then collects or ACKs a known total, and admission proceeds.
   - No path requires a None projection to authorize anything.
3. **Infrastructure exhaustion.**
   - While pending, the projection is present with `replacement_eligible:false`, so there is no child.
   - Once completed, the projection is None. `exhaustion()` and `actual_model_work()` may both still return true, and that is still no child (638–642).
   - The draft test `test_completed_infrastructure_none_is_never_replacement_authority` asserts exactly this on the real 5813be card: exhaustion true, actual work true, projection None.
4. **Infrastructure exhaustion, then a factory-bug resume, then budget exhaustion.**
   - The resume clears the marker. The new exhaustion gets a new ID with `stop: budget_exhausted`, so the projection becomes eligible.
   - Because the infrastructure exhaustion produced no child, this is the parent's first and only child. That matches 665–667.
5. **A second exhaustion after a child exists.** This covers `extension_incomplete` after close_to_passing, and budget exhaustion after a factory-bug resume.
   - The new pending projection may be eligible again.
   - B's durable one-child-per-parent journal is checked before derivation (641–642, 409–411, 430–434), and replay returns the existing child.
   - D's API correctly does not claim to read that latch (stream-d 999–1000).
6. **Legacy exhausted cards with no `diagnosis_state`.** These project as pending, but B still requires the authenticated import/migration record (656–658). No silent authority.
7. **Provider wait or retry during diagnosis.** The ID is kept (650). A mid-diagnosis checkpoint that still projects pending cannot produce a second child because of the latch.

The interfaces and stream-d texts agree on every path above. The predicates are card-only and pure, and no new spend ledger, stored coverage field or launch mode is introduced. Under zoom-out, nothing reviewed is speculative: each rule closes a concrete pit stop found in reviews 15–17.

## Majors

**M1. B's own design still states the replacement rule the parent ruling replaced (`docs/designs/batch-service.md:794–795`, outside the diff).**
- The current text says: "Immediately enqueue one replacement when D's eligibility says the original is exhausted and did actual model work."
- That is exactly the fallback that interfaces 404–407 and 638–641 now forbid. It is wrong for two reachable states:
  - infrastructure exhaustion with actual work (stream-d already makes this diagnosis-only);
  - a completed infrastructure diagnosis, whose projection is None.
- interfaces §8 says it is part of B's design (batch-service 418). A B implementer would still face two contradictory sentences.
- **Required before B's adapter is implemented:** replace that sentence in B's increment2b design with: "Derive only from a present D `pending_projection` with `replacement_eligible` exactly true; None never permits derivation. Apply the one-child journal first."
- Add one B test: an infrastructure-exhausted card with actual work derives no child, whether its diagnosis is pending or completed.
- Lines 798–799 have the same issue. They say extension revision old+1 happens "only after D projects close_to_passing", but interfaces 659–661 says B needs no extra projection for extensions and that D enforces eligibility. B's change should state the actual extension money admission input, or defer it explicitly. That part does not block replacement.
- This is not a blocker on the D contract under review, which is internally consistent. It is a precondition on B's next design change.

## Nits (optional)
- **N1.** Add one explicit sentence at interfaces 649: "The run that records an exhaustion checkpoints and stops; it never starts diagnosis in that run." The rule is already implied by 365, 418 and batch-service 843. However, "close_to_passing continues in the same worker" (659) could lead an implementer to run diagnosis inline. If that happened, the pending state would never be collected and replacements would silently never derive for known-total cases. Add a matching D runner test.
- **N2.** stream-d 937–939 still says `recovery.infrastructure_exhausted(card)` sets `replacement_eligible` false. That is the pre-J1 wording. It only differs from interfaces 635–637 if a marker is left uncleared, which the contract forbids. Align the wording anyway, since interfaces 678 says the rules also apply in stream-d.
- **N3.** "Archives and clears the old infrastructure_gate marker" (664–665) does not say where the archive goes. Under YAGNI, simply clearing it is enough: the completed `diagnosis_state` and the factory-bug outcome are already the evidence. Either name the archive field or drop the word "archives".

## Murphy rows
No row closes, and none is claimed (679–680, 682–692). The authored-state replays in the draft tests explicitly do not close rows. That is correct.

## Summary
The contract leaves B no open decision for replacement derivation, decrease qualification, coverage or the diagnosis projection, and every finding from reviews 15–17 is resolved. **PASS.** B must apply the M1 sentence fix in batch-service.md as part of its own increment2b design change before it codes the adapter.

## Elephant resolution

PASS accepted for 4274a48..6055678. No blocking finding remains; none was rejected.
M1 is a stream B design/adapter obligation: require a present eligible projection,
never predicate fallback; test pending and completed infrastructure exhaustion.
The extension admission wording in B must defer to D eligibility and §8 money.
N1–N3 are retained as optional clarifications and runner obligations. No Murphy
row closes. The completed-infrastructure None regression passes in the 3a draft.
