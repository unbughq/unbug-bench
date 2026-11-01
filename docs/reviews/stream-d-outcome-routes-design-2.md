# Goldfish design review: `docs/designs/stream-d-outcome-routes.md` (revision 2, HEAD 2e9d457)

**Reviewer:** fresh read-only goldfish, `Mode: REVIEW`
**Personas:** `zoom_out`, `design_critic`, `implementation_readiness`
**Standards:** `heilmeier-standard.md`, `implementation-readiness-standard.md`

**Read:**
- `docs/ENGINEERING.md`
- the design under review
- `docs/reviews/stream-d-outcome-routes-design-1.md`
- `docs/murphy-register.md` row `new-stream-d-outcome-routes-1`
- `factory/diagnosis_dispatch.py` (whole file)
- `factory/extension_package.py` (whole file)
- `factory/extensions.py`: `active`, `writer_continuation`, `writer_receipt`, `propose`, `verify_proposal`, `admit`, `complete`, `retain_comparison`
- `factory/extension_compare.py`: `snapshot`, `compare`
- `factory/run.py`: `writer_intent_valid`, `complete_writer`, `pending_call`, `write_and_attack` lines 1128–1500, `main` lines 3300–3420
- `factory/late_recovery.py`: `invalidate`
- `factory/budget.py`: `reconcile_reservations`
- `factory/job_authority.py`: `money_wait` raises
- `factory/diagnosis.py`: `_state`, `exhaustion`
- `docs/designs/stream-d-package-completion.md`: entry and comparison deferral

**Verified:**
- 40822e7 is an ancestor of HEAD.
- `factory-simplify` has since moved to 7ab397e (lane 2 freshness). Its one change to `diagnosis_dispatch.py`, adding `loop_freshness` to `CARRY`, is already present at HEAD.

## Summary

Revision 2 fixes both blockers from review 1.
- **Shared seams.** Lane 1 now sits on lane 2's merged seam. Positive-ID routing, `completed_route` and the build/repair bypass stay lane 2's. The only new piece in `main` is the 0→positive conversion before the existing `extension_package.run` call.
- **Writer request.** The fresh writer request is now one extracted helper, with a source for each frozen field. I checked each field against `run.py` lines 1466–1483, and against the key ban in `pending_call` and `writer_intent_valid`. They match.
- **Scope.** The design is honest about scope:
  - entry/comparison is a lane-2 prerequisite;
  - factory-bug attribution is a required follow-up with a register row;
  - B's three-resume import stays B's.

**What this slice does not deliver.** Until lane 2 ships `extension_package.entry`, a production `close_to_passing` decision in this slice still ends at `extension_comparison_pending`. That is the same terminal label as today, reached by a longer path. The only new production behaviour is:
- `retired_extension_limit` before entry;
- refusals before reservation.

So the user's overall task, all three diagnosis routes working end to end, is **not** done by this slice. What remains:
1. lane 2's entry/comparison;
2. merging B's `t3/batch-carry-over`;
3. `stream-d-factory-bug-attribution.md`, its design and its producer;
4. the integrated item-7 exam.

## Prior blockers

### B1 (seam/ownership collision): **resolved**

- The baseline is stated and checked: 40822e7 via dc13368.
- Positive-ID routing, `completed_route` and `main`'s bypasses are cited as dependencies, not lane-1 additions. The design adds no second copy of the positive-ID path.
- `main` changes in one place. It adds `extension_id == 0 → admit_extension → positive ID`, immediately before the existing package call, and states that "package.run never receives 0".
  - I checked that the existing mode refusals at `run.py:3322–3325` run for 0, because `type(0) is int`.
  - I checked that `elif extension_id is None: validate_and_repair` is skipped for 0.
- `entry()` is labelled a *proposed consumer contract*. The design says lane 2 may revise it. Lane 2's own design (`stream-d-package-completion.md:10–11, 173–174`) confirms entry capture is still unfinished there.
- With entry absent, admission refuses before any mutation. It does not invent an evaluator. `extension_compare.snapshot` is the existing shared producer, and the design does not duplicate it.

### B2 (writer request open choices and duplication): **resolved, one residual Major (R1)**

The field table matches the code:

| Field | Check |
|---|---|
| `report` | `round-<n>.json` |
| `repair_pending` | `True` |
| `actor` | `writer` |
| `before_repair_sha256` | `case_hash` after entry/propose |
| `repair_requested` | `bool(problems)` when the report is `None` |
| `findings_report` | `None` |
| `input_problems` | from the extracted `writer_feedback`, which is the `failed_gate` block at `run.py:1223–1226` verbatim |
| `next_phase` | `G1` |
| `output_sha256` | `None` |
| prompt | exactly the `run.py:1481–1482` formula |
| admission-owned keys | absent; this matches the refusal set at `pending_call` lines 410–414 |

- `binding_sha256` is supplied by `pending_call`, through `retain_writer`'s argument and through `admitted()`.
- `round_limit == proposal.round` satisfies `writer_receipt`'s and `write_and_attack`'s `round_limit` checks.
- Using the checkpoint card rather than diagnosis prose is right. Excluding stress findings follows from `propose` at `extensions.py:396`.

## Prior Majors

- **M1: resolved.** Register row `new-stream-d-outcome-routes-1` exists (`murphy-register.md:77`). It names its owner (D lane 1) and its follow-up design, and says the producer feeds the existing `reclassify_factory_bug`. The design adds:
  - "hold + retire only, attribution open";
  - a statement that model-supplied IDs cannot grant attribution;
  - no row closure.

  The consequence for headroom is now stated correctly.
- **M2: resolved.** The integrated three-resume and `retired_factory_bug_limit` assertion is moved to a post-merge exam in the same test file, and is explicitly "not promised against this slice's base".
- **M3: resolved, but over-specified (see N1).** The kill after `admit` and before `on_admitted` is covered:
  - `writer_receipt` repairs the lagging attack-state;
  - gate-continuation is invalidated before any paid writer resume;
  - a kill-point test exists.
- **M4: resolved.**
  - The test file is named.
  - The table has five kill points, each with its route and assertions.
  - The checkpoint refusal is now concrete: tampered RAM job-money/source binding gives `money_wait`, then `seal(checkpoint=True)`, with no candidate seal.
  - The orphaned reservation's full maximum is asserted to be booked once across two reconciles, matching `budget.py` `reconcile_reservations`.
- **M5: resolved.** Objective, cost ($0 offline, B's commitment only, no new allowance), risk, payoff, timeline (one cycle), midterm, final and integrated exams are all present. See N6 on jargon.

## New findings

### R1. How the ordinary loop calls the helper is still ambiguous for pending continuation

**Severity:** Major (non-blocking; a one-sentence fix)
**Scope:** §Shared writer request, lines 241–247 and 263–266; `run.py:1468–1483`.

**Finding.** The ordinary modern loop builds the base receipt, then does one of two things:
- **Ordinary continuation:** merges `{**resume_unit, **writer_receipt}`, so current `binding`, `round_limit` and release lists override the saved values.
- **Extension continuation:** takes `deepcopy(resume_unit)`.

In both cases it then overwrites `before_repair` and `repair_requested` from `resume_unit`, and `findings_report` and `input_problems` from the `report` and `problems` locals. Lines 1328–1333 already rebuilt those locals from the receipt.

The design says "use it for ordinary modern fresh writer work" and "pending writer continuation retains its existing frozen receipt". That leaves the implementer two choices:
- **(a)** Skip the helper on continuation. The base dict is still needed for the ordinary merge, so duplication survives.
- **(b)** Read "retains its frozen receipt" as applying to ordinary continuation too. That stops refreshing `binding` and release lists, which changes ordinary behaviour.

Neither is what the design intends.

**Recommendation.** State: every modern writer iteration first applies the existing `resume_unit` substitution of `before_repair` and `repair_requested`, then calls `writer_request(...)`. Ordinary continuation then applies the existing `{**resume_unit, **receipt}` merge, and extension continuation the existing `deepcopy(resume_unit)`, both unchanged. The prompt is always the helper's. Every value stays the same, and one construction site is left.

### R2. Some admission refusal labels are not named

**Severity:** Nit
**Scope:** lines 272–276.

"Validates completed close_to_passing state" and "Active history refuses new admission" give no stop label. Reuse `propose`'s labels so there is one vocabulary:
- `extension_diagnosis_required`;
- `extension_already_active`.

"Five entries retire" should compare against `extensions.LIMIT` and raise `retired_extension_limit`, not a new constant.

## Nits

- **N1. The extra invalidation duplicates an existing call (delete before adding).** For an extension writer in phase `pending`, `write_and_attack` already reaches the loop's `invalidate(c)` at `run.py:1466–1468`:
  - `skip_writer` is `False`, because line 1229 requires `extension is None` and line 1315 gives `resume_writer_validation=False`;
  - nothing between `writer_receipt` (line 1145) and the loop reads gate-continuation;
  - a completed writer implies `on_admitted` already ran.

  The design itself admits the loop "also invalidates". Either drop the new call at positive-ID entry and cite the loop as M3's closure, or name the consumer before the loop that makes it necessary. The kill-point test should stay either way.
- **N2. Orphaned intent after a kill between reservation and admission.** `retain_writer` runs before `extensions.admit`, so a kill between them leaves `extension-writers/<op>.json` with no history row. Add one assertion to that kill-point row: the orphaned envelope grants nothing, and the restart admits under a new operation ID.
- **N3. "Preserve label".** In the before-reservation row, name the expected label: `provider_wait` with its wait record, or `money_wait`.
- **N4. The name `report` means two things.** The helper argument `report` is the findings-report path. The table row `report` is the receipt's `round-<n>.json`. Call the argument `findings` (or similar).
- **N5. The base has moved.** `factory-simplify` is now at 7ab397e. Rebase onto it before implementation. Its only change to a file this design touches is already present at HEAD.
- **N6. Objective wording.** Heilmeier asks for an objective with no jargon. "hold/retire paths", "single writer/stress/gate extension package" and "B's cumulative money authority" are jargon. A plain lead sentence would help, for example: "When a diagnosis says a case is close to passing, start one more paid writing round automatically; code enforces the limits." Also add the scope sentence from the summary above, that this slice alone does not change production `close_to_passing` stops until lane 2's entry lands. That keeps a reader from taking the payoff line as delivered by this slice.

## Checklist

| Area | Assessment |
|---|---|
| Shared writer helper field specification | Complete and matches the code. The call order for continuation is still open (R1). |
| Route propagation and cleanup | All three sites named: replay, the valid-journal branch, and `invoke`'s validated result, where the return leaves `while True` and `finally` disposes of the pilot and restores operation and exclusions. Admission and the writer run in `main`, outside `model_dispatch_lock`. The routing table matches what `apply` naturally does: no row or a different completed exhaustion gives 0, a different active exhaustion gives `diagnosis_input_invalid`. |
| Mode and money boundaries | Mode refusals run for 0 before setup. Extension writers skip the ordinary-limit check and reserve only through `job_authority` and B's commitment. There is no new ledger and no per-extension allowance. A `money_wait` refusal goes through `main`'s checkpoint seal. |
| Restart tests | Five kill points with routes, assertions and orphan booking. Small gaps: N2, N3. |
| No positive-ID duplication | Confirmed. `completed_route`, `writer_receipt` and package traversal stay lane 2's. Lane 1 removes only `apply`'s resume-only gate. |
| Scope honesty | Explicit: the slice does not complete item 7 and closes no rows. Attribution is tracked; B's import and lane 2's entry are prerequisites. |
| User requirements | Fresh admissions stay within ≤5 extensions, one writer + stress + gates, same-version progress, ≤3 factory-bug resumes (B's) and no duplicate counter. End-to-end delivery of all diagnosis routes is still outstanding (see the summary). |

## Verdict

**Passing.** No blocking finding is open. B1 and B2 are resolved, and M1–M5 are resolved.

Before or during implementation, fix R1 with the one-sentence call-order rule. Nits N1–N6 are optional, but N1 (delete the redundant invalidation) and N6 (scope sentence) are recommended.

This passes a **consumer routing slice only**. It is not completion of the diagnosis-outcome task. The remaining work is listed in the summary.

---
Elephant disposition: accepted R1 and nits; call order clarified, redundant invalidation omitted, orphan/label assertions specified. Latest factory-simplify merged before implementation. No blockers remain; full task still requires attribution and integration.
