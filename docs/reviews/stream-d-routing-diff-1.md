The design document ends at line 2753. My review is complete. Here is my report.

---

# Goldfish Diff Review — Item 7 first increment: admitted extension writer continuation

**Verdict: PASS**

Scope reviewed: `git diff 4fecb01..fc290da` on `t3/stream-d-gates` (HEAD `fc290da`), against the final section of `docs/designs/stream-d.md` (lines 2674–2753) and `interfaces.md` §8. Mode REVIEW, personas `zoom_out` + `implementation_readiness`, standard `implementation-readiness-standard.md`. I verified the code, tests, and committed suite record. The design-review response in `docs/reviews/stream-d-routing-design-1.md` was accepted in full; I checked each of B1/M1/M2/nits landed.

## What the diff does

`extensions.writer_continuation(c, receipt, name) -> bool` (new, `factory/extensions.py:236-256`) plus a two-point call in `run.pending_call` (`factory/run.py:375-378` before the lease, and `388-390` re-check after the lease wait, before reservation). It bypasses the ordinary `budget_exhausted` threshold only when a pending schema-v2 writer receipt is provably bound to its already-admitted extension, and preserves the ordinary path otherwise. 9 new tests in `tests/factory/test_stream_d_admission.py`.

## Findings

### Blocker — none.

### Major — none.

### Confirmed sound (design-review findings correctly landed)

- **B1 (null-lease continuation must route through `provider_continuation`).** Correctly implemented. `writer_continuation` accepts `lease_id`/`invocation_id` both-strings only when the ledger reservation matches the history's operation, builder call name and invocation ID; both-None only through `run.provider_continuation(c, receipt, 'writer')`; mixed/absent pairs fall through to `raise BudgetError('extension_reservation_mismatch')`. The helper is reused, not duplicated. Verified against `provider_continuation` (`run.py:308-320`), which already requires `settled`, matching `wait_id`, `case`, `role`, `batch`, `job`, and `lease_id is None`.
- **M1 (name the deleted test / no test deleted).** The design now says "No tests are deleted"; the diff adds only. Confirmed no test removed.
- **M2 (tests belong in `test_stream_d_admission.py`).** Correct — the 9 tests are in `test_stream_d_admission.py` and reuse its `call`/`refuse`/`assert_unadmitted` harness versus `test_stream_d_extensions.py`, matching the accepted fix.
- **N1/N2/N3.** The design names the ordering (`resume_provider_wait` then `job_authority.for_case`), states launcher round-limit routing is deferred to the next increment, and notes no model spend (local replays only). `pending_call` calls `resume_provider_wait` and `job_authority.for_case` before `writer_continuation` (run.py:358-359, 375-378), matching the required order.

### Checks on the ordinary path (no unintended behavior change)

- `writer_continuation` returns `False` immediately when there is no active extension and the receipt carries no `extension_id` (`extensions.py:240`). Ordinary writers pay for one `active(c)` call (`read(c)`), which returns `[]` cheaply when `extension-history.json` is absent. No error is raised, so the ordinary admission flow is untouched.
- A **fresh** writer round builds `writer_receipt` from a fixed key set at `run.py:1347` and does **not** copy `extension_id`; a **completed/validated** extension receipt resumes into a fresh `n+1` round (`run.py:1209`), also without `extension_id`. So a stale `extension_id` cannot leak into an ordinary later round and trigger the "marker without active history" refusal. The only way `extension_id` reaches the refusal branch is a genuine pending-extension resume, which is the intended seam.
- The re-check after `await_lease` (`run.py:388-390`) exists and the test `test_continuation_rechecks_binding_after_lease_wait` proves a mutation during the lease wait is caught and the ledger is left unchanged. This closes the TOCTOU between verification and reservation.

### Tests are real replays, not fixtures generated under test

The harness (`test_stream_d_runtime.RuntimeTests.setUp`) loads the verified public practice bundle `invalid-runs-practice.json.gz` (hash-checked per file) and the collected 5813be ledger above the old $5 cap; snapshot, router, reservation, reconciliation and publication run for real, only the model CLI is authored. This satisfies the "real artifacts" rule and correctly claims no live qualification.

### Suite record

`docs/reports/stream-d-routing-suite-20261031T101019Z-441d1dee.json` records exit_code 0, base_sha `4fecb01…`, 157 scripts / 0 failed. The log shows `test_stream_d_admission.py` ran **26** tests OK (17 prior + 9 added), confirming the new tests execute and are not skipped. The record filename matches the base-`sha`-independent convention.

## Nits (optional, non-blocking)

- **N1.** `writer_continuation` imports `provider_continuation` for each call even on the fast `return False` path (`extensions.py:238`). Harmless; a deferred import below the early-return would avoid importing `run` on every ordinary writer admission. Cosmetic only.
- **N2.** The double call (`run.py:378` then `389`) re-invokes `active(c)`→`read(c)` (full history re-validation) on the second pass. This is deliberate re-verification, but it means the history file is read and validated twice per continuation. Acceptable for a recheck seam; worth a one-line comment noting the second call is the TOCTOU guard, not redundant work.
- **N3.** `writer_continuation` reads `c.ledger` again itself (line 250) despite `reserve_invocation` reading it shortly after in `pending_call`. No correctness issue; a transient ledger change between the two reads is already covered by re-verification semantics.

Nothing above blocks. The increment is correctly scoped: direct `pending_call` continuation binding only, with launcher/package routing and switch-on deferred, and row 9 correctly left open.

---

Skipped: I did not run the suite myself (relied on the committed, hash-recorded result, which the parent verified as passing per the brief); I did not re-read `interfaces.md` §8 in full beyond the admission/continuation sections since the increment touches only the §8 binding already established. Risk for the parent: the TOCTOU re-verification reads the ledger twice without an interleaving guarantee between `writer_continuation` and `reserve_invocation` — correct today because both run under the same `dispatch` case-lock (`run.py:357`), but a future refactor that relaxes that lock must preserve it.

## Elephant response

PASS accepted. No blocking or major findings. Optional nits are left unchanged to keep this increment tight; the existing dispatch lock and second binding verification remain required. Claude's initial diff review failed with API ENOTFOUND and produced no report; this final review uses the user-authorized OpenCode DeepSeek fallback. No code changed after the passing full suite.

This completes only item 7's admitted writer continuation seam. Remaining: ordinary launcher round-limit routing; durable receipt advancement and admission/publication crash recovery; one writer/stress/gate package including freshness and unfinished stress; diagnosis outcome routing through B, factory-bug resume and retirement; qualified-path removal of legacy recovery allowances. Item 8 live qualification and switch-on follow those changes. No Murphy rows close; row 9 remains open. Nothing was pushed or merged into factory-simplify or main.

