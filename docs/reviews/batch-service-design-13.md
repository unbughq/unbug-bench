I've read everything required. Writing the verdict now.

# batch-service design review 13: Increment2b.2 provenance-gate resolution against reviewed D interface 6055678

**Verdict: PASS. No Blocker or Major findings. Three optional Nits.**

**Reviewer:** fresh goldfish, read-only. Personas: zoom_out, design_critic, implementation_readiness. Mode REVIEW. Standards: heilmeier-standard.md and implementation-readiness-standard.md.

**Scope:**
- Worktree `/Users/bugsincode/.t3/worktrees/unbug-bench/t3-ded79ec5`, branch `t3/batch-service-control-vm`.
- Diff `f941923..3eac4b4`: commits dc3ffff and 3eac4b4.
- The complete Increment2b.2 section and the affected 2b.1 paragraphs of `docs/designs/batch-service.md` at 3eac4b4.
- Reference: `git show 6055678:docs/designs/interfaces.md` §8.
- I also read review 12 (verbatim, including the elephant resolutions) and review 11.

No files were written or saved. I did not touch the parent checkout and ran no tests.

## Bottom line

Review 12's one Major is resolved. The interface says (§8, "D's runner records…"): *"Legacy exhausted cards without diagnosis_state project pending until the runner records their first ID; B still requires an authenticated explicit import/migration record before acting on any legacy projection."*

The design now refuses planning with `legacy_projection_unbound` when the top-level `diagnosis_state` is missing or not an object (batch-service.md 2b.1, "Activation prerequisite…"). The refusal leaves facts and queue unchanged, and the design accepts no import format in this increment.

I checked this choice against the interface itself, not against review 12's recommendation:

- **It is stricter than review 12's suggestion, and that is correct.** Review 12 suggested keeping the unknown-total settlement resume for legacy cards. But that resume is B acting on a legacy card's D facts. The interface says "before acting on **any** legacy projection", so an automatic legacy resume would be an import in all but name.
- **The rest of the interface agrees.** §8 conservative resume says "unknown legacy usage refuses this exception". The interface's legacy-checkpoint paragraph requires "an explicit manifest import record". The design's own existing text says "G2's future import-record format must get its own reviewed addendum" (batch-service.md, around line 737).
- **Nothing the interface grants B is taken away.** The refusal falls only on cards the interface already sends through import. Existing independently authorized work does not go through this plan path.
- **The gate checks provenance only.** It looks at whether the field is present and is an object. It does not copy D's stop predicates and does not validate the object's contents; D keeps that job.

No codebase integration or activation readiness is claimed or granted. The design says correctly that D3a is not yet reviewed and merged to B, and that the adapter flag (DIAGNOSIS_ENABLED) stays False.

## Contract checks

| Check | Result |
|---|---|
| Review 11's nine findings | Still resolved as review 12 recorded. The 3eac4b4 diff changes none of those passages in a way that reopens them. |
| Review 12 Major M1 (provenance gate) | **Resolved.** See above. Tests are planned: a legacy exhausted state with actual work runs through D's real `pending_projection`; even when that projection is present and eligible, the outcome is refusal, no child, no resume request and unchanged journal bytes. They cover known and unknown totals and a pre-existing `facts:null` entry collected with the adapter off. No import fixture is allowed. |
| N1 | Resolved. The 2b scheduling hook now calls the predicates "diagnostic predicates (consistency checks only)". This matches the interface: "diagnostic helpers, never a fallback authorization." |
| N2 | Resolved. The fixture path `tests/factory/test_stream_d_projection.py` is to be named at D's reviewed merged SHA. Its infrastructure states are authored D states layered on the real paused 5813be card, not saved artifacts. 8b8ece6 is supporting evidence only. |
| N3 | Resolved. The extension priority class comes only from a verified same-owner §8 `money_wait.priority` request. The interface's `money_wait` record includes `priority`, and it says "Scheduling priority belongs to an admission/revision request." The class is never inferred from `close_to_passing`. |
| N4 | Resolved. The freeze clears automatically only when, under the lock: authentic same-owner evidence covering every refused collection has been ACKed, all implicated incidents are reconciled, and the full aggregate has been recomputed. Known overruns count in full and keep the overrun owner blocked. No founder approval step is added. This is a factory rule, so the founder is not needed under ENGINEERING §1. |
| epsilon = (2·len(M)+1) nanodollars on every known-P/known-T comparison, accepting T ≥ P−R−epsilon | Unchanged and consistent with 6055678. |
| D review 18 obligations | All preserved: (1) a child is derived only from a present `replacement_eligible:true` projection, with no predicate fallback; (2) actual-D tests show infrastructure exhaustion with actual work gives no child both while pending and after completion; (3) D owns extension eligibility and B only schedules. |
| No B stop predicates added | Holds. |
| Readiness claims | None made. Code integration is gated on the named reviewed D merge SHA, the fixture paths and a final B design review. |

## Heilmeier / readiness notes

- The objective, current limits, risks (a legacy card turning into silent import) and exams (the named refusal tests) are stated.
- Cost is $0, with no models, cloud or VM.
- One implementer decision is still underspecified; see Nit 1.

## Nits (optional)

1. **Gate order inside `plan`.** The text does not say whether the gate runs before or after `plan` calls D's three functions. The test wording ("pass … through D's real pending_projection … B must refuse") can be read either way. The visible outcome is the same either way (refusal, no state change). But it decides which label wins when D raises or contradicts itself on a legacy card. It also leaves open whether the gate runs before replaying stored facts. Suggestion: "Check the gate first, before replaying stored facts and before importing or calling D." The test can still call D's real `pending_projection` itself to show that the eligible answer is ignored.
2. **Non-exhausted cards.** Read literally, the gate is unconditional, so it also refuses non-exhausted cards that have not yet recorded `diagnosis_state`, and they show up as "legacy". No request is lost, because such cards never produce one. The label is misleading in status output, though, and leaves `facts:null` forever. Either say this is intended or apply the gate only when D work is needed, and add one test.
3. **Malformed `diagnosis_state` object.** A malformed object passes the gate, because D validates the contents. D then fails closed to a None projection. If the total is unknown, the existing text queues a same-owner settlement resume. That outcome is fully specified and bounded by §8 money admission, but there is no test for it. One authored-state test would pin it down.

No finding was rejected. Nothing in this review blocks merging the design record.

## Elephant resolution

PASS accepted for contract consistency against reviewed D interface6055678.
No blocking or major findings remain; none was rejected. Optional nits about
gate ordering, non-exhausted cards and malformed-state testing are retained for
the final design review against D's reviewed merged implementation and fixtures.
No implementation or activation readiness is claimed by this record.

Parent clarification after design12: the strict legacy gate stands. D proposes
the reviewed section8 import record; B owns later manifest/holder wiring in its
own reviewed increment. The frozen nine-field RAM config stays unchanged, and
import grants no money: the founder authorizes exact amounts from D's dry-run.
This does not expand the current2b.2 scope or accept an import format now.

Next prerequisite: parent identifies D3a's reviewed merged implementation SHA;
name its ledger/projection fixture paths and run the final B design review.
DIAGNOSIS_ENABLED remains False. No source/test changes in this record, no new
test claim, no Murphy row closure, no spend, no VM changes, no merge or push.
