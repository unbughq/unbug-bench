# Fresh Goldfish DESIGN Review — `stream-d-factory-bug-attribution.md`

**Mode:** REVIEW (fresh, read-only, no edits made) — reviewer persona mix `zoom_out` / `design_critic` / `implementation_readiness`; standards applied: `docs/ENGINEERING.md`, `tools/egm/document_standards/heilmeier-standard.md`, `tools/egm/document_standards/implementation-readiness-standard.md`, plus the zoom-out standard.

**Verdict: PASS — no blockers.**

---

## Ground truth verified (read-only)

- Checkout: `/Users/bugsincode/.t3/worktrees/unbug-bench/t3-21bef30c`, **HEAD `a17167afebbde89afcf8bfd869a7595ba430b83c`** (`a17167a` "Record Beam Free regional unavailability").
- Design file `docs/designs/stream-d-factory-bug-attribution.md` is **unchanged since the canonical rewrite commit `1c5e355`** ("Unify attribution design around finding ownership and concrete held/drain seams"); `git diff 1c5e355..HEAD -- <design>` is empty. Design content = the rewritten 265-line spec.
- Design is **unimplemented** at this HEAD — verified against code: no `factory/factory_waste.py`; `_read_factory_bug_finding` still enforces `eligible_operation_ids == []` / `failure_receipts == []` (`diagnosis.py:329–330`); `_write_input_tree` names tuple (`diagnosis.py:523–527`) lacks `factory-failures`, `factory-replays`, `job-money.json`, `job-money-history.json`; `_settle_leaf` still writes v1 float-only; `reclassify_factory_bug` still rejects growth (`budget.py:440–441`); no `FactoryBugHeldWait` exists; `_dispatch` carries the guards but not the B admission hook. Consistent with the brief ("Design unimplemented").
- B baseline confirmed via read-only `git show` on `t3/batch-carry-over`: `resume_factory_bug(c)` at `t3/batch-carry-over:factory/diagnosis.py:441`, `_resume_bindings(c)` at `:387`, single caller `diagnosis_dispatch._dispatch:292` (`if d.resume_factory_bug(c): return False`), guards at `:295–313` (active call / reconcile / ledger-active-or-pending → `usage_reconciliation_pending`).

## Accepted-findings verification — design-6 `B1–B5` and `M1-a–M4-a` vs the canonical rewrite

| Finding | Design-6 required fix | Present in canonical rewrite (design @ `1c5e355`) | Status |
|---|---|---|---|
| **B1** (M1) second hold re-claims first finding's operations | Make eligibility finding-scoped; disjoint holds; "no candidates → successful hold"; two sequential/same-batch holds disjoint; pin classify's all-attributed → hold succeeds | §"Frozen eligibility and immutable findings": `eligible(evidence_root, case, finding_id)` finding-scoped, excludes ops owned by *another* finding's valid v2 record, "No candidates means no new waste record and a successful hold, not an error. This makes two sequential or same-batch holds disjoint." + "Remove the exact []/[] guard … recompute `eligible(..., finding.finding_id)` and require exact equality." | **FIXED** |
| **B2** (M2) held terminal clobbered by generic `BudgetError` handler | Dedicated `HeldWait`/held exception that `run.main` maps to `factory_bug_held` + no `exhaustion_occurred`; or self-catching resume | §"B resume hook and held refusal (B2, B5)": `diagnosis.FactoryBugHeldWait(BudgetError)` carrying reason; run.main checks it **FIRST** before provider-wait handling/generic terminal assignment; `terminal_stop=factory_bug_held`, `factory_bug_wait_reason=error.reason`, no `exhaustion_occurred`; keep completed state + finding ref; finalize/seal via stopped path; no scored seal; no dispatcher return for held refusal; success clears `wait_reason`, writes `admitted_card` atomically, returns True, `_dispatch` → False, main continues ordinary; existing append is only debit commit; held card never cleared before phase 3 succeeds. | **FIXED** |
| **B3** | reclassify existing-record path version-aware: v2 grow-only (`operation_ids` superset growth, event union, single null→actual resume-pair transition; shrink/nonnull-replace → `waste_attribution_mismatch`); replace validated v2 in same ledger txn + rerun `case_spending`; `_settle_leaf` v2 refresh preserves exact string amount + paired identity; v1 float-compatible unchanged | §"Shared accountant and live settlement (B3, M2-a, M3-a)": v2 compares only `schema_version, kind, id, finding_id, diagnosis_sha256` as immutable identity; superset growth required; "Replace the validated v2 record in the same ledger transaction and rerun case_spending there"; "Classification preserves total; only ordinary/waste split changes"; "_settle_leaf v2 refresh preserves exact string amount and paired identity; v1 float-compatible refresh stays unchanged." | **FIXED** |
| **B4** (M3) drain attached to wrong scope | Pick one drain design + pin exception precedence + snapshot-after-join | §"Per-call owner drain (B4, M4-a)": keep per-calibrator-call owner endpoint (do not move to gate lifetime); drain in `owner_server.finally` before context returns; subclass `ThreadingHTTPServer`, register in `process_request` under lock before start, remove in finally, notify condition; closing sets accepting flag false before shutdown; no later start; shutdown+join finish before snapshot; one 30s monotonic deadline; tracked shutdown helper; deadline → permanently unpublishable; never freeze partial proof; standalone responder unchanged; body error wins unchanged (incl. `BudgetError`/`CaseProblem`); drain timeout marks unpublishable + private cleanup diagnostic without masking; no body error → `InvalidInfra` for incomplete cleanup, no proof; scope exit classification/proof freezing only after every per-call owner context drained; test late owner completion relative to calibrator call, not gate exit; never forcibly settle active calls. | **FIXED** |
| **B5** | ledger-active refusal + `resume_provider_wait` + pending guards inside phase 3 | §"B resume hook and held refusal (B2, B5)": after B validates + durably appends/reuses admission, before `admitted_card`: `prepare_dispatch`; acquire `model_dispatch_lock`; `active_model_calls` → `BudgetError('usage_reconciliation_while_active')`; read live ledger, **refuse `ledger.active` before settlement**; call `r.resume_provider_wait(c)` with unchanged held card/checkpoint + current authenticated owner; reconcile live reservations; re-read ledger; **refuse any active or remaining pending row as `usage_reconciliation_pending`**; post-reconcile pending guard matches B's ordinary path (do not reject reconcilable orphan pendings prematurely); then `classify(c, finding, admission)`; selected estimated row → `money_wait` after publishing settled subset; no new lease/model work. | **FIXED** |
| **M1-a** | which set does `classify` use? | `classify always uses finding.eligible_operation_ids, independent of model narrowing; … Remove the exact []/[] guard … recompute eligible(..., finding.finding_id) and require exact equality. … Findings and their retained input trees are immutable.` | **FIXED** |
| **M2-a** | `_spending` v2 branches by reference; exact shared validator | §"Shared accountant": one internal factory-bug record validator used by **both** `_spending` and `reclassify_factory_bug`; unknown versions/malformed v2 → `invalid_waste_attribution`; v1 keeps historical invalid/unpriced behavior; v2 amount = exact nine-decimal string `format(usd(_waste_amount(events, ids)), '.9f')`; `event_ids` sorted unique, empty only when all related reservations settled with zero charge; all included ops settled with `estimated_gap_usd == 0`; events = exact union; amount via `event_charge`/Decimal; V2 no `fix_commit`/`fix_attribution_sha256` checks; refuse cross-record overlap. | **FIXED** |
| **M3-a** | late settlement has no ledger source | §"Shared accountant": classify authenticates frozen op identities, then looks up those exact identities in the **LIVE** ledger for current settlement, rechecking owner joins; frozen eligibility never changes when late live usage arrives; later explicit dispatch reconciles live receipts and re-runs classify for the same finding/admission; only settled subset enters record; pending selection stays in finding; empty settled subset → no record; replay proofs can grow original v2 record; replay scope-exit classify before later hold persists finding; later hold freezes ledger and excludes already-owned ops. | **FIXED** |
| **M4-a** | "request context retains original closed attempt" has no site | Design now states plainly: late reservations accumulate into the discarded scope object, do not refuse a lease or alter pricing, no late reservation enters another scope; **no new budget-level closed-attempt admission guard**; exception precedence pinned (body error wins; drain timeout marks unpublishable + private cleanup diagnostic, no mask; no body error → `InvalidInfra` for incomplete cleanup; no proof because unpublishable; scope exit classify/proof-freeze only after all per-call owner contexts drained). | **FIXED** |

**All eight accepted findings verified as fixed in the canonical rewrite.** Design-6's elephant disposition — "All B1–B5 and M1-a–M4-a are accepted. Rewrite the design as one specification; no blocker is rejected. Reconciliation ordering follows the actual B code: remaining pending rows are checked after reconciliation, with a pre-reconciliation active-ledger guard. Fresh review required before implementation." — is satisfied by the current design text.

## Task focus seams — confirmed resolved in the canonical design

1. **Two holds / disjoint eligibility & immutable recomputation** → §"Frozen eligibility and immutable findings". **Resolved.**
2. **HeldWait through main** → §"B resume hook and held refusal (B2, B5)". **Resolved.**
3. **v2 ledger monotone growth / exact shared validator** → §"Shared accountant and live settlement (B3, M2-a, M3-a)". **Resolved.**
4. **Live settlement versus frozen proof** → same section + classify paragraphs. **Resolved.**
5. **Per-call owner drain with registration/join/exception precedence** → §"Per-call owner drain (B4, M4-a)". **Resolved.**
6. **Concrete `resume_factory_bug(c, r)` + active ledger/provider-wait/pending guards** → §"B resume hook and held refusal". **Resolved.**
7. **Pending check intentionally after reconciliation, as actual B** → design: "Then reconcile live reservations, re-read ledger and refuse any active or remaining pending row as `usage_reconciliation_pending`. The post-reconcile pending guard matches B's ordinary path; do not reject reconcilable orphan pending rows prematurely." **Resolved** (post-reconcile placement confirmed against B's ordinary path).

## Full findings

- **Blockers: NONE open.** All design-6 blockers now carry concrete, implementable fixes in the canonical rewrite; none re-opened.
- **Majors: NONE new.** No fresh major contradicted the rewritten design.

### Minors — policy / interface gaps, with exact fixes required before implementation

1. **MIN-1 (policy).** The phase-3 `BudgetError` → held mapping is scoped with "including …", and the never-final terminal (`money_wait`) is defined at design:199–200 but not enumerated in the wrap list; the disposition of adjacent phase-3 errors surfacing from B's `_resume_bindings` chain (`retired_batch_bound`) and pre-admission validation errors is implicit. **Exact fix:** enumerate the phase-3 set that wraps into `FactoryBugHeldWait` (`money_wait`, `invalid_provider_wait`, `usage_reconciliation_while_active`, `usage_reconciliation_pending`, `invalid_waste_attribution`, `waste_attribution_mismatch`) and pin the mapping to `factory_bug_wait_reason`; keep B's post-admission filesystem error → `FactoryBugHeldWait('factory_bug_resume_io_wait')`, and all other B validation/retirement semantics outside the held-refusal mapping.
2. **MIN-2 (interface / implementation-readiness).** The design repeatedly presupposes a "scope" (`opens one scope`, `scope exit`, "the scope object carries an unpublishable flag") without naming the `factory_waste` scope/context surface (ContextVar key, enter/exit API). Zero-Decision Rule requires this be pre-determined. **Exact fix:** name the ContextVar attribute and the scope enter/exit interface in `factory_waste`.
3. **MIN-3 (policy).** `factory_bug_wait_reason` vocabulary should be pinned explicitly (held reasons: `money_wait`, `invalid_provider_wait`, `usage_reconciliation_while_active`, `usage_reconciliation_pending`, `invalid_waste_attribution`, `waste_attribution_mismatch`, `factory_bug_resume_io_wait`).
- **Nits:** none functional; design's Heilmeier catechism fields (objective, state of the art, new approach, impact, risks, cost, timeline, metrics/exams) are all present and answered.

## Explicit verdict

**PASS — no blockers.** Fresh read-only goldfish design review of `docs/designs/stream-d-factory-bug-attribution.md` @ `a17167a` (design unchanged since canonical rewrite `1c5e355`): design-6 blockers B1–B5 and majors M1-a–M4-a are all verifiably fixed in the canonical rewrite; no open blocker remains; no new blocker found.

## Non-blocking context for the record

- Design remains **unimplemented**; **B import / lane2 entry / integrated exam** remain open; **no Murphy rows closed** (`new-stream-d-outcome-routes-1`, row 9 stay open by design).
- Review attempts 7/8 failed before producing a review (free-tier limit / model unavailable) — no approval yet; this is the fresh review.
- After implementation: full suite to unique committed log, wait for result, then **fresh independent diff review**; never self-verify a blocking fix.

---

**Skipped / not checked:** no code execution, no tests, no diff review, no delegation, no writes/commits/tests/merges/pushes performed. **Risk you should know:** the three MINs above are pre-implementation folds; if the elephant declines to name the `factory_waste` scope API (MIN-2) before implementing, the Zero-Decision Rule fails at implementation-readiness.

## Elephant disposition

Accepted MIN-1–MIN-3. The explicit wrap vocabulary, ContextVar and contextmanager signatures are pinned before implementation. No blockers rejected; no rows closed.
