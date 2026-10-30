# Goldfish design review: stream D, "Remaining increments after 4f291fb" and "First increment: completed writer validation parity"

Mode: REVIEW. Personas: zoom_out, design_critic, implementation_readiness. Standards: zoom-out, Heilmeier, implementation-readiness. Read-only. I read the working-tree `docs/designs/stream-d.md` (uncommitted, +79 lines over 4f291fb), plus `factory/run.py` (`write_and_attack` receipt load at lines 1085–1290, the writer loop at 1290–1350, `loop_freshness` at 920–985, `pending_call` and `provider_continuation` at 308–330), `factory/batch_service.py:21,296`, `factory/diagnosis_dispatch.py:318` and `tests/factory/test_stream_d_runtime.py:468–500`.

## Verdict: BLOCKED (1 blocker, 1 major, 2 nits)

---

### B1 — Blocker — Implementation readiness / correctness: the plan does not say where the check goes, and the obvious reading breaks parity

**What the design says.** Apply the unchanged-repair check "before resumed G1/early validation". Separately, missing or malformed intent fields "must refuse before any model or resumed validation call".

**What the code does.** The code labelled "resumed G1/early validation" is the `elif modern and resume_writer_validation:` branch at `factory/run.py:1344`. Code runs earlier than that branch whenever a completed writer receipt carries `findings_report`, and a requested repair carries one by definition, since `repair_requested = bool(report or problems)` at line 1297. The sequence is:

1. Lines 1175–1182 set `report` and `problems` from the receipt.
2. Line 1257 (`if report and problems:`) calls `loop_freshness(c, saved, report)`.
3. `loop_freshness` can call `confirm_hits` (a model call). It can also raise `freshness_public_match` or `freshness_unresolved` (lines 960–985).
4. If the findings clear, the branch can call `early_review(c)` and record `stress_review: completed` (lines 1274–1279). That happens before the restored branch at line 1344 is reached.

**What goes wrong.** An implementer who reads "before resumed G1/early validation" will put the check in the line-1344 branch. Then:

- **Parity is lost for no-op repairs.** An unchanged requested repair that was killed at its completion checkpoint can end with a freshness model call, or with a freshness stop or stress pass, instead of `unchanged_repair`. The uninterrupted path stops at line 1323 before any of that. This is exactly the divergence the increment exists to delete.
- **The refusal fires too late.** The malformed-receipt refusal would run after a possible model call, which breaks the design's own "before any model call" rule.

**Why tests will not catch it.** The existing harness, and therefore the planned tests, patch `loop_freshness` to identity and `early_review` to `None` (test file lines 485–486). With those patches, either placement passes.

**Required fix.**

1. **Name the anchor.** Put the intent-field validation and the unchanged-repair check in the `if modern_writer_unit and not awaiting_stress:` block at `factory/run.py:1173`. They go right after the existing `resume_writer_validation and receipt.get('output_sha256') != case_hash(c)` check (lines 1176–1177), guarded by `resume_writer_validation`. That placement:
   - keeps "output hash first";
   - runs before `loop_freshness`, `early_review`, G1 and every model call;
   - needs no change to the line-1344 branch.
2. **Make one test catch the wrong placement.** At least one killed-unchanged-repair test and one malformed-field test must run with a non-empty findings report. They must fail if `loop_freshness`, `confirm_hits` or `early_review` is called, for example by patching those to `self.fail` instead of identity.

### M1 — Major — Test plan: the requested-repair setup at round 1 is left to the implementer

"Run an unchanged requested repair … retain round 1" needs `repair_requested` to be true at round 1. A fresh round 1 has `report = problems = None`, so `repair_requested` is false. Two routes are possible, and they exercise different code:

- (a) `prev['failed_gate']` seeding `problems` at lines 1068–1071. This also enables the late-gate logic.
- (b) Seeding `report`/`problems` some other way.

State which route the tests use. The smallest choice is `prev = {'failed_gate': 'G1', 'failed_detail': …}` with a G1 detail from the saved practice case. Also state that the uninterrupted and killed runs share the same `prev`.

### N1 — Nit — Batch claim: name the real stop

The bounding paragraph matches the code:

- `DIAGNOSIS_ENABLED = False` (`batch_service.py:21`);
- `plan()` returns `diagnosis_unavailable` with `queue=[]` (`batch_service.py:296`);
- the paragraph says outright that it does not claim A/B/E qualification or an unattended finish, and that exhausted cases can stop.

That is accurate and properly bounded. Two optional edits would help a fresh reader:

- Name the per-case stop reason, `diagnosis_pending` (`diagnosis_dispatch.py:318`).
- Say this is a case-level hold, not a batch halt. "Can stop on exhausted cases" can be read either way.

### N2 — Nit — Scope of intent validation

Say explicitly that the new refusal applies only to `phase: completed` writer receipts. Pending receipts keep their current `.get` defaults (lines 1302–1305) until increment 2. Otherwise an implementer may extend the refusal to pending receipts and break provider-wait resumes.

---

### What passes

- **Zoom-out.** The root cause is correct. The restored `completed` path skips the line-1323 check that the uninterrupted path runs. The fix deletes that difference and adds no schema, toggle or subsystem. The fields it relies on, `before_repair_sha256` and `repair_requested`, are already persisted by the V2 producer: lines 1306–1311 set them, and the `writer_completed` checkpoint keeps them (both added together in 753b33e). Failing closed on malformed V2 receipts is the right choice.
- **Heilmeier.** The objective, the current gap, the cost (no new storage or model cost; a stress call is saved) and the risk (old malformed V2 receipts are refused) are all stated. Row 10 is correctly left open, because these controls are not a live interrupted-writer exam. The full suite and a fresh diff review are named.
- **Increment ordering (2–7).** Each increment names its target rows and says it closes nothing before increment 7. This matches the Murphy rule that only real-artifact exams close rows. "Enable diagnosis only after these prerequisites pass review" is consistent with the bounded batch claim.
- **Phasing.** Increment 1 is self-contained and leaves the codebase in a testable state.

**Path to PASS:** fix B1 (name the anchor and add the non-identity freshness/early-review assertion) and M1 (name the round-1 requested-repair setup).

## Elephant response

B1 and M1 accepted. The design now names the early receipt-load anchor and requires findings-bearing tests whose freshness and early-review hooks fail if reached. Round-one tests use failed_gate G1; an additional round-two test retains an authored stress report over the saved practice case. N1 and N2 accepted: the plan names the case-level hold and limits strict validation to completed writer receipts. No finding rejected.
