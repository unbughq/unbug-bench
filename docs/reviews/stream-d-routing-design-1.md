**Verdict: BLOCK**, on one blocker. The rest of the increment is well-scoped and fits the existing code. One fix to the design text would turn this into a PASS.

Scope: the final section of `docs/designs/stream-d.md` (lines 2674–2746, not yet committed in worktree `t3-4ac6b632`). I checked it against `factory/extensions.py`, `run.pending_call` (`factory/run.py:350-413`), the writer resume path (`run.py:274-305`, `1118-1215`, `1340-1351`), `tests/factory/test_stream_d_extensions.py`, `tests/factory/test_stream_d_admission.py` and section 8 of `docs/designs/interfaces.md`. I used the personas `zoom_out`, `design_critic` and `implementation_readiness`, in Mode: REVIEW, against the Heilmeier and implementation-readiness standards.

---

### Blocker

**B1. The design refuses a writer that was waiting on a provider when it was killed. The code treats that as a normal resume.**

- **Where:** "Change and deletion", the sentence "Its prior lease/invocation must refer to the same ledger operation and call. Missing … receipts refuse as `extension_reservation_mismatch`." Also "Tests and Murphy rows", the item "wrong … lease/invocation".
- **Problem:** The design places the new check after the settlement checks. One of those, `resume_provider_wait` (`run.py:274-305`), handles a writer that was killed while waiting for a provider. It settles the wait record and rewrites the receipt in `attack-state.json` with `lease_id=None, invocation_id=None, resumed_from_wait=<wait_id>`. Then `write_and_attack` labels the resume `kind: 'provider_wait'` through `provider_continuation` (`run.py:308-320`, `1134-1137`) and merges that receipt into the one passed to `pending_call` (`run.py:1344-1345`).
  - An admitted extension writer can hit this. After admission, `opencode` runs fallback attempts under `before_attempt=admitted`.
  - Under the text as written, the receipt has no prior lease or invocation, so it is refused as `extension_reservation_mismatch`.
  - interfaces.md section 8 and lines 759-760 both require that an interrupted extension resume as ordinary same-owner work. Provider waits are the main interruption class in that section.
  - The result is that an admitted extension stops for good on a provider wait. That is the pit stop item 7 exists to remove, and Murphy row 9 gets worse.
- **Required fix:** State the rule exactly:
  - If `lease_id` and `invocation_id` are both strings, the ledger row `invocation_reservations[lease_id]` must have the history's `operation_id` and `call_name == 'builder-<round>'`, and its `invocation_id` must match the receipt.
  - If both are `None`, accept only when `provider_continuation(c, receipt, 'writer')` is true. That function already exists; reuse it rather than adding a new check.
  - Any other combination (one set and one null, or nulls without a verified wait archive) refuses.
- **Required tests:**
  - A positive replay: an admitted extension writer, then a settled and archived provider wait, then a continuation past the ordinary threshold with the same operation, round and extension.
  - A negative replay: nulled lease fields with no wait archive, or a `wait_settlements` entry that doesn't match.

### Major (should be fixed before diff review; not blocking)

**M1. The test to delete can't be identified.**
- **Where:** "Delete the accidental ordinary-threshold test for this verified continuation; keep that test for ordinary writers…"
- **Problem:** No current test asserts `budget_exhausted` on a continuation of a verified extension.
  - The only `pending_call` threshold test with an extension context is `test_ordinary_attribute_cannot_bypass_limit_but_verified_extension_can` (`tests/factory/test_stream_d_admission.py:91`). It covers an ordinary writer with a stray `active_extension_id` and no history. That is exactly the "keep" case.
  - As written, the implementer has to decide which test to delete.
- **Fix:** Name the test, or drop the sentence and say "no test is deleted".

**M2. The tests are pointed at the wrong file.**
- **Where:** "Tests and Murphy rows": "Extend `tests/factory/test_stream_d_extensions.py`, using its saved public practice case and collected 5813be ledger."
- **Problem:** The `pending_call` harness lives in `test_stream_d_admission.py`. Its docstring says "First extension admission over saved practice bytes and the 5813be ledger", and it provides `call`, `refuse` and `assert_unadmitted`, which assert that no lease is taken before the check. `test_stream_d_extensions.py` is the state-replay file and doesn't load the 5813be ledger.
- **Fix:** Put the continuation tests in `test_stream_d_admission.py`, or say explicitly that its harness should be reused. Otherwise the implementer will rebuild the harness, which is what the zoom-out persona is meant to stop.

### Nits

- **N1.** Say that the launcher can't reach this seam yet. In modern mode, `round_limit = min(args.rounds, saved_limit)` (`run.py:1143`), and the writer loop is `range(start_round, round_limit + 1)`. An extension round past the saved limit therefore never calls `pending_call` through `write_and_attack`. This fits the explicit deferral. One sentence should say the increment is tested only by direct `pending_call` replays, and that round-limit routing belongs to the next increment. That stops the diff reviewer from flagging it.
- **N2.** In "after current B authority and settlement checks", name the functions (`job_authority.for_case` and `resume_provider_wait`), since B1 depends on that order.
- **N3.** Cost and timeline are not stated (Heilmeier). For a single helper with replays, one line is enough: no model spend, local replays only.

### Confirmed sound (no action needed)

- **Keeping the operation:** the non-proposal path already reuses `receipt['operation_id']` (`run.py:376-377`), and `receipt.update` in `admitted()` keeps `extension_id`.
- **History check:** `extensions.read` already ties each history row to a ledger reservation with the same operation and call name, so the helper can rely on it.
- **Completed receipts:** `writer_call_done` and `complete_writer` run in `write_and_attack` before `pending_call` (`run.py:1208-1212`). Refusing completed receipts in the helper agrees with that and adds no gap.
- **Money:** a new attempt still goes through `reserve_invocation` under B's cumulative commitment. This matches interfaces.md section 8 (lines 552-561), which says the ordinary threshold is separate from batch authority and that money alone grants no extension.
- **Scope:** routing, diagnosis switch-on, removal of legacy allowances, and item 4 are all explicitly deferred, as the user permits. No second ledger, schema, mode or allowance is added. Row 9 is supported and correctly left open.

## Elephant response

Accepted B1, M1, M2 and all nits. The design now accepts null lease/invocation only through the existing provider_continuation proof; admission tests cover positive settled waits and absent/mismatched archives. No tests are deleted. Tests reuse test_stream_d_admission.py. Launcher round-limit routing is explicitly deferred; local replays incur no model spend.

