I now have complete understanding of the join point. The design says "resolve only the diagnosis dispatcher join by preserving both B's resume-before-dispatch hook and D's fresh extension routing." I can see B's `resume_factory_bug` is a separate function; the dispatcher's `replay`/`_dispatch` currently calls only `restore_factory_bug` (same-batch). The B branch adds `resume_factory_bug` that must be invoked before `_dispatch`/`replay` in the cross-batch case.

I have enough to write a complete, thorough review. Let me compile my findings across the three personas. Let me verify two remaining details: the design's "null resume pair" concern (section about resume_id/resume_binding_sha256 both null at hold, then becoming real at admission), and the exact reservation owner binding in the attempt receipt.

Let me quickly check what `reserve_invocation` stores (already seen: lease_id, invocation_id, operation_id, call_name, parent_call_name) vs what the design's attempt receipt records (`reservations:[{lease_id, invocation_id, operation_id, call_name}]`).

I now have everything needed. Here is my complete review.

---

# Goldfish Review — `docs/designs/stream-d-factory-bug-attribution.md`

**Mode:** REVIEW (read-only)
**Personas applied:** zoom_out, design_critic, implementation_readiness
**Standards:** heilmeier-standard.md, implementation-readiness-standard.md
**Scope reviewed:** the proposed addendum only, against ENGINEERING.md, interfaces.md §8, stream-d.md held lifecycle, and the referenced code (`factory/budget.py`, `diagnosis.py`, `model_runtime.py`, `gate_pipeline.py`, `run.py`) plus B branch `t3/batch-carry-over` (`9ddb70e`) `resume_factory_bug` / `_resume_bindings`.

I did not review the separate "routing consumer slice" diff (correctly excluded per brief). The full suite is running; this review is design-only and does not verify tests.

---

## Verdict

**Not ready. Two blockers and several Majors.** The addendum's core insight — prove invalid-infra work and its replay from an existing reservation ledger, reclassify rather than create a second allowance — is sound and consistent with §8's "reclassification never creates headroom" rule. But it is not actionable as written: it leaves the exact "owner binding" join between a produced attempt receipt and `reclassify_factory_bug`'s settled-row validation unspecified, and it contradicts the current held-lifecycle code it claims to extend on two concrete points (the immutable `eligible_operation_ids != []` guard, and the null-then-admitted `resume_id` schema). Those are fixable, but they must be fixed before implementation.

---

## Blockers

### B1 — "Exact reservation owner" join is underspecified (readiness + design critic)

- **Severity:** Blocker
- **Affected scope:** §"Producer: one code-owned execution attempt" (receipt schema), §"Existing ledger, v2 hold and late growth" ("the record's owner matching the reservation's bound owner"), §"Diagnosis eligibility and immutable finding".
- **Finding:** The addendum repeatedly requires that each received attempt reservation be validated against the frozen ledger's reservation whose *owner matches the record's owner*, and against "known reservation identities" — but never says what field is the owner. The proposed receipt binds `{lease_id, invocation_id, operation_id, call_name}`; `budget.reserve_invocation` additionally stores `parent_call_name`, `route`, `account`, `billing`, `pool`, `family`. The design's phrase "the decoration's bound owner" and "current owner against B's existing `_resume_bindings` chain" conflates two different notions: (a) the **money owner** (`batch/job/case/reservation_id` from §8), and (b) the **reservation row identity** (`lease_id`/`invocation_id`) already in `reserve_invocation`. The addendum never states precisely which of the five fields must be byte-equal to make an attempt receipt bind to a reservation, so the implementer must invent the join. Under `implementation-readiness-standard.md`'s Zero-Decision Rule this fails.
- **Correction:** Spec the exact equality predicate. Minimum: attempt receipt `reservations[i]` binds iff `(lease_id, invocation_id, operation_id)` is byte-equal to a settled `invocation_reservations` row AND `call_name` equals that row's `call_name` AND (where present) `parent_call_name` matches — and the whole record only qualifies inside a `scope` whose `case`, `stage`, `case_sha256`, and operation/reservation identity match. Also state that the money-owner equality (`case` + `reservation_id` + `source_generation`) is checked *separately* via the frozen `restore-accounting.json`/`job_money` (the B `_resume_bindings` invariant), not inferred from the reservation row (which carries no `case`).

### B2 — `_read_factory_bug_finding` hard-codes the empty-set invariant this addendum deletes

- **Severity:** Blocker
- **Affected scope:** §"Diagnosis eligibility and immutable finding" (lines 88–93) vs `factory/diagnosis.py:322–337` (current and in `t3/batch-carry-over`).
- **Finding:** Both this worktree and B's branch have:
  ```python
  finding['eligible_operation_ids'] != [] or finding['failure_receipts'] != []
  ```
  as a *retained-finding invariant*, raising `diagnosis_finding_invalid` otherwise. The design says the retained finding "now contains the code-derived set/proof references rather than unconditional empty lists" and that `_read_factory_bug_finding` "recomputes those values." This is a real contract change to the held lifecycle: replay/persist idempotence (`previous != finding`) and cross-batch re-read (`_read_factory_bug_finding(c, path, read(old, old), ...)`) all flow through this comparison. The addendum does not enumerate that this exact line must change from `!= []` to "recompute from the frozen input tree and revalidate," nor account for the byte-equivalence claim "old empty findings remain byte-equivalent when their old frozen inputs lack this producer." That byte-equivalence is load-bearing: if the recomputed value is non-empty for an old input that happens to *have* a producer directory, the old stored empty finding no longer round-trips.
- **Correction:** Add to the deletions list: replace the `!= []` guard in `_read_factory_bug_finding` with recomputation-and-revalidation, and spell out the backward-compat clause precisely (empty producer dir ⇒ empty set ⇒ byte-equal; presence of a producer dir without matching attempt records ⇒ still empty and, critically, must *not* manufacture a non-empty set). This is a §"Tests, deletions and rows" item but is missing from the explicit deletion line 180–181.

---

## Majors

### M1 — Null resume pair admitted only "at hold"; B admission timing is under-specified and partly wrong

- **Severity:** Major
- **Affected scope:** §"Existing ledger, v2 hold and late growth" (lines 103–116), §"Code-linked replay work" (lines 140–159), and B's `resume_factory_bug` (line 441–504).
- **Finding:** The v2 record requires `resume_id`/`resume_binding_sha256` both null at hold, both real at "a validated B admission," and "mixed null/non-null refuses." But B's `resume_factory_bug` performs the admission *before* any D model work and *before* `settle()` of the resumed case's interrupted receipts (that settle happens inside `_dispatch` → `reconcile_reservations`). The design's replay hook (`classify(c, finding, admission)`) is stated to run "after its durable history admission, before work," but the waste record for the *original failed attempt* is written at **hold time** (with null resume). Those null resume fields then must be backfilled with the admission's `resume_id`/hash only after the replay's operations settle. The addendum never states the ordering invariant that makes the "null→single admitted value" transition monotonic and crash-safe: if the process dies after `resume_factory_bug` appends history but before `classify` backfills the original hold's v2 record, the paired fields can be left null while history has the admission — which the "mixed null/non-null refuses" rule does *not* cover (both-null is legal). The "never drops or rewrites attribution identity" rule (line 123) and "admission replay is already idempotent… consumes no second resume" (line 135) implicitly rely on this, but the atomic ordering is left to the implementer.
- **Correction:** State the three-phase durability contract explicitly: (1) hold writes v2 with null pair and persists finding first; (2) admission appends history durably; (3) replay classify transitions the pair null→admitted value inside the same ledger transaction as the newly settled operations, re-running on replay until non-null-idempotent, refusing any differing admitted value. Name which of these is the commit point that B's "durable admission before work" must precede, and confirm B's `resume_factory_bug` already returns before D's `_dispatch` (it does in the B branch) so the hook sits between `resume_factory_bug` and `replant`/`_dispatch`'s settle.

### M2 — `_settle_leaf`'s existing factory_bug branch will double-serve and needs a schema-version split, not just "preserve string amounts"

- **Severity:** Major
- **Affected scope:** §"Existing ledger…" (lines 120–129, "Extend `_settle_leaf`…") vs `factory/budget.py:322–335`.
- **Finding:** The current `_settle_leaf` already has a factory-bug late-growth branch:
  ```python
  waste['event_ids'] = sorted({...})
  waste['infrastructure_waste_usd'] = float(usd(_waste_amount(...)))
  ```
  i.e. it rewrites `infrastructure_waste_usd` as a **float** and matches on `kind == 'factory_bug'` + `row['operation_id'] in operation_ids`, with no `schema_version` discrimination. The addendum's v2 mandate ("amounts are exact nine-decimal strings," "preserve string v2 amounts while refreshing events") contradicts this existing code path directly. The addendum says only "extend `_settle_leaf` to preserve string v2 amounts" — but as written it will either (a) convert v2 string amounts back to floats on the first late receipt, or (b) require a v1/v2 branch that is nowhere specified. There is no mention that `_settle_leaf`'s `infrastructure_waste_usd = float(...)` line and its missing `schema_version` guard are the *specific* things to change.
- **Correction:** Specify that `_settle_leaf` must branch on `waste['schema_version']`: v1 keeps decode-only/legacy float-compat behavior; v2 refreshes `event_ids` only and keeps `infrastructure_waste_usd` as a nine-place string, recomputed from `_waste_amount` and re-`format(..., '.9f')`, never `float(...)`. Add this to the deletions/changes list rather than the vague "extend."

### M3 — Replay "successful resumed attempts" grants spend to the *same* finding but the resume-side owner/binding check omits the concrete source

- **Severity:** Major
- **Affected scope:** §"Code-linked replay work" (lines 140–159).
- **Finding:** `factory_waste.resume_scope(c, stage, case_sha256)` must "validate latest factory-bug-resumes history and the current owner against B's existing `_resume_bindings` chain; authenticate its finding/input proof." Two gaps: (1) the addendum does not state that `resume_scope` is only callable *after* `resume_factory_bug` has returned True (B's admission), so a naive implementer may call it on a held (not-yet-admitted) case and get a `replay_of`/`resume_id` for an admission that was never durable — this is exactly the "null resume pair before actual admission" hazard the brief flags. (2) It references `_resume_bindings` (a B-private helper) as the authority source but does not state that D must *not* reimplement it, matching the §8 rule "B never re-implements these predicates" in reverse. D must treat `_resume_bindings` as the single source of the owner transition chain.
- **Correction:** State the precondition (admission must already be durable in `factory-bug-resumes.json` with matching reservation/source binding) and the ownership rule (reuse B's binding chain; D duplicates no transition logic; the `replay_of`/`resume_id` are copied from that admission, never free-form). Note the tension with B1: "current owner against the binding chain" is a money-owner check, distinct from the per-reservation identity check.

### M4 — "Late receipts" and "empty reservations retained but no charge" reach into `reclassify_factory_bug` without specifying the growth assertion

- **Severity:** Major
- **Affected scope:** §"Existing ledger…" (line 120 "may only grow…"), §"Code-linked replay work" (line 158 "classify adds newly settled operations"), vs `factory/budget.py:423–447`.
- **Finding:** `reclassify_factory_bug` today refuses on any difference in `operation_ids` (`waste_attribution_mismatch` via the identity tuple) and refuses non-settled rows. The addendum wants a *grow-only* update of `operation_ids` and `event_ids`, and dropping of mis-/pending operations to "pending attribution." These are opposite predicates: growth-vs-identity and pending-allowed-vs-pending-refused. The addendum never enumerates the exact set of "identity fields" that must now be permitted to change (adding operation_ids) vs those that stay frozen (`id`, `kind`, `finding_id`, `diagnosis_sha256`), and it says the update happens "independently validated" without saying who re-validates (the classifier must both re-run `factory_waste.eligible` and re-check settled-only). Without this, the implementer will either hard-fail on growth (replay can never add a newly settled operation) or weaken `waste_operations_pending` into a money bug.
- **Correction:** Specify the precise grow predicate: allowed `operation_ids` additions = only `factory_waste.eligible` operations not already attributed, whose reservations are `settled` with zero `estimated_gap_usd`; `event_ids` must remain exactly the settled-reservation event union; any operation that is still estimated/pending is *retained in the finding* but not entered into the record; reclassification still validates via `case_spending` in one transaction.

### M5 — Immutable-evidence and frozen-tree claim ("record no model prose as authority") is incomplete against the current input tree

- **Severity:** Major
- **Affected scope:** §"Producer" (line 70 "add factory-failures to the selected diagnosis input tree"), §"Diagnosis eligibility" (lines 77–83), vs `factory/diagnosis.py:_write_input_tree` (lines 478–554).
- **Finding:** The input tree is produced by `_write_input_tree`, which includes an explicit allow-list of work names (`'infra-attempts.json'`, `'usage-receipts'`, etc., lines 523–527). Adding `factory-failures/` and `factory-replays/` requires editing this list and the `add_tree` selection, plus the `_input_inventory`/`manifest` hash closure so the produced directories are frozen. The addendum says "add factory-failures to the selected diagnosis input tree" but does not note that the producer directory is written *inside `c.work`* by the gate/stress attempt and therefore must be included by name in `_write_input_tree`'s names tuple, nor that `eligible()` reads only the frozen tree (`root['work']/factory-failures/*`) and never the live `c.work` directory. A failure to freeze means the finding can be re-derived from mutable live evidence, violating "immutable evidence."
- **Correction:** Add `'factory-failures'` and `'factory-replays'` to the `names` tuple and state that `factory_waste.eligible(evidence_root, case)` reads only under `evidence_root` (the frozen `inputs/` tree) with the same no-follow path discipline as `_input_bytes`.

---

## Nits

- **N1 (lines 29–36):** "An exception escaping the scope is eligible only if `isinstance(InvalidInfra)`" — note `InfrastructureExhausted` *is* a subclass of `InvalidInfra` (`bin/run_validity.py:13`). The addendum's "not BudgetError, cancellation, pause or arbitrary Exception" is correct, but it should state whether `InfrastructureExhausted` (the exhausted, terminal form) also produces a failure record or is excluded as a *different* terminal. Currently ambiguous.
- **N2 (line 46, "Stage stress and current semantic hash; only an escaping InvalidInfra produces failure proof"):** `stress_categories` in `run.py:206` wraps `stress_progress.run`, but the InvalidInfra raised inside gates is handled in `gate_pipeline.check` (converted to `InvalidInfra` raise, line 57–59) rather than escaping through `stress_categories`. The scope placement "around `stress_categories`" must specify that the *gate evaluation inside* the stress run raises through, or the stress producer will never see `InvalidInfra`.
- **N3 (line 51 "Nested scope defaults to innermost attempt"):** G10's owner (`exam_responder`) runs in the HTTP thread (`run.py:2661 owner_channel`) and the design disclaims it. But the tester and owner both hold model leases; the innermost-default rule needs to explicitly say the tester's attempt is the innermost and the owner's calls (which carry `parent_call_name`) are therefore attributed to the *tester's* attempt, not a separate scope — otherwise concurrent G10 attribution (a stated midterm exam) is undefined.
- **N4 (line 67 "Sort reservations by lease_id; no duplicate lease/operation invocation binding"):** this is self-consistent, but the "no duplicates" invariant is already enforced by `_bound_events`/`reserve_invocation` keying. Redundant but harmless.

---

## Concurrency & safety summary (brief-required checks)

- **Concurrent attribution:** addressed only via "innermost attempt" + G10 `copy_context().run`; not fully specified for the owner thread (N3). Needs the tester/owner ownership rule pinned down.
- **Exact reservation owner and usage bindings:** **Blocker B1** — the join predicate is unspecified.
- **Schema compatibility:** v2 string amounts vs `_settle_leaf`'s `float(...)` is a **Major M2** conflict that must be re-specified.
- **Immutable evidence:** intent is sound but the input-tree allow-list edit is missing (**M5**).
- **Late receipts:** growth-vs-identity conflict in `reclassify_factory_bug` is unresolved (**M4**).
- **Null resume pair before actual admission:** **M1/M3** — the null→admitted transition ordering and the `resume_scope` precondition are under-specified.
- **B join:** correctly identified as "preserve B's resume-before-dispatch hook + D's extension routing"; concrete and sound given `diagnosis_dispatch._dispatch`/`replay` structure, but must state that `resume_factory_bug` precedes `_dispatch`'s settle.

---

**Skipped / not checked:** the separate routing-consumer diff (per brief), the still-running full suite, and whether `new-stream-d-outcome-routes-1`'s "close only on real saved monetary events" (murphy-register line 77) is satisfiable — that correctness depends on the live-run artifacts this design review cannot inspect. I did not run any tests or attempt self-verification against the writer.

**Risk the user must know:** the byte-equivalence clause in B2 is the most likely silent regression: if an old frozen input *already contains* a `factory-failures/` directory (e.g., from a partially-deployed earlier producer), the "old empty findings remain byte-equivalent" guarantee can silently fail replay, converting a benign old finding into `diagnosis_finding_invalid`. Recommend making the producer directory name fresh-scoped (e.g., only present when the new producer actually wrote it) rather than relying on absence alone.

---
Elephant disposition: accept B1/B2 and all majors. Revision 2 below makes joins, compatibility, transaction ordering and growth predicates explicit. No rejected findings; fresh review required.
