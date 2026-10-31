# Goldfish diff review 1 (Codex): stream D item 3, money cleanup

Reviewer: Codex `gpt-6.1-sol`, high reasoning effort, through T3
`delegate_task`. Fresh context, read-only, a different model family from the
writer (Claude), against `cc6726a..78e5fb8` (code in 477d84a). Final report
below, verbatim.

---

**Verdict: PASS.** Mode: REVIEW. No blocking correctness issue or undescribed material behavior found in `cc6726a..78e5fb8`.

**Blockers:** None.

**Majors:** None.

**Nits:**

- `docs/reviews/stream-d-money-design-6-codex.md:16` — Trailing whitespace makes `git diff --check cc6726a..78e5fb8` exit 2. Remove it when convenient.

The money paths match the final design: valid closed-gate snapshots bound initial estimates; non-final replay preserves an estimated charge; `booked_before` includes late-bound events; final decreases retain reconciliation provenance. Immediate settlement and removal of factory markers keep bounded unknown usage from poisoning admission. Holder incident recovery accepts equal or higher final charges while requiring provenance for decreases.

Batch `max_cost=None` is applied before evidence bindings are built. Started route outcomes are recorded before settlement can raise, and inherited receipts preserve that evidence across resume.

Rows 8 and 21 have credible saved-artifact coverage under ENGINEERING §2. Tests use retained practice bytes and captured ledgers through the real accounting, runtime, router and collection paths. Authored model streams, configuration and gate request activity are disclosed. The “Closed by” entries name the relevant tests and correctly limit closure to batch jobs and reservation-bound calls. They do not establish live rollout readiness, eliminate legacy unbound markers, or resolve the documented $50 ordinary-envelope prerequisite. The round-8 adjudicated collection limitations remain outside this increment.

The four requested existing-test changes are honest: they replace assertions for the old behavior with precise assertions for designed settlement, preserved reservations, successful retry admission and gate-bound charges. They retain reconciliation and replay checks.

**Files read:** Requested personas and implementation-readiness standard; zoom-out standard; `docs/ENGINEERING.md`; Murphy rows 8/21; the third-increment design; money-design review records 1–8, including Claude adjudication. Reviewed the specified diff and relevant portions of `factory/{budget,run,batch,batch_holder,diagnosis,model_runtime,model_call_gate,batch_accounting,gate_state,batch_money,coordinator,key_holder,restart,ttl_continuation}.py`, `factory/launch.sh`, `factory/README.md`, the five changed test files, `test_stream_d.py`, and `router_test_support.py`.

**Tests run:** All five passed: `test_stream_d_runtime.py` (42), `test_stream_d_projection.py` (7), `test_batch_accounting.py` (13), `test_batch_holder.py` (39), `test_model_call_maxima.py` (21): **122 tests passed**. Full suite not run. No checkout files changed; `.stream-d-next/` ignored.

---

## Elephant response

PASS, with no blocking or major finding. The one nit is fixed: the trailing
whitespace in `stream-d-money-design-6-codex.md` is removed, and
`git diff --check` is clean.
