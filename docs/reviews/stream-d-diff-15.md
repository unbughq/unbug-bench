# Stream D diff review 15: pending diagnosis producer (re-review of B1 and M1)

**Reviewed:** `/Users/bugsincode/.t3/worktrees/unbug-bench/t3-21bef30c`, branch `t3/stream-d-implementation`, **HEAD `9aa72a1ae90c402eac63efe541266c3c11ddce23`**. Clean tree apart from the out-of-scope `.stream-d-next/` folder, which isn't tracked by git.
**Diff:** `390c9c1..9aa72a1` (commits `305c10c`, `703ba99`, `9aa72a1`). Code: `factory/diagnosis.py`, `factory/gate_pipeline.py`, `factory/run.py`, `tests/factory/test_stream_d_runtime.py`, `tests/factory/test_stream_d_projection.py`.
**Checked against:** `docs/designs/stream-d.md`; `interfaces.md` §8, the "Replacement derivation and D's exhaustion projection" and "Final diagnosis projection APIs" parts, plus the `diagnosis_state` producer paragraph; `docs/reviews/stream-d-diff-14.md`.
**Personas:** zoom-out and implementation-readiness goldfish, read-only.
**Out of scope:** `.stream-d-next` drafts, held-outcome production, diagnosis dispatch, extensions, money enablement, and closing any row.

## Verdict

**PASS. No blockers.** One major: M1's fix has no regression test. Fix it in this change, or reject it with a written reason.

## Re-review of review 14

### B1 (infrastructure marker loses to an overwritten `terminal_stop`): fixed and well covered

- `record_exhaustion` now does `stop = 'infrastructure_exhausted' if infrastructure_exhausted(card) else card.get('terminal_stop')` before the `_trigger` check. This matches §8: "When that helper triggers despite another terminal_stop, diagnosis_state.stop is the literal infrastructure_exhausted." `pending_projection` then reads `state['stop']`, so `replacement_eligible` is false.
- The marker is per-run. `main` builds a fresh `c.card`, and `inherit_recovery_history` copies only `builder_rounds`, `models_used`, `budget_raised`, `rounds_raised`, `founder_ruling`, `diagnosis_state` and `extension_history`. It never copies `infrastructure_gate`. So a marker from an earlier run can't mislabel a later budget exhaustion. The docstring's "a retained infrastructure marker alone is not a new exhaustion" holds.
- `gate_pipeline.stop_infrastructure` now sets `c.exhaustion_occurred = True`. That makes an infrastructure exhaustion during an extension run (completed state present) count as new.
- Tests:
  - `test_infrastructure_marker_wins_over_overwritten_stop_at_checkpoint` covers both `budget_exhausted` and `runner_error:KeyError`, plus idempotency on a second `finalize_accounting`.
  - `test_g10_finally_crash_keeps_budget_exhaustion_ineligible` drives the real `GatePipeline.run` retry path and G10 `finally` path, with an outer `BudgetError('budget_exhausted')` from the second boundary.
- **Mutation evidence:** each mutation below was run on an export of HEAD.
  - Reverting the marker line to `stop = card.get('terminal_stop')` makes both new tests fail (2 failures, 1 error).
  - Deleting `c.exhaustion_occurred = True` in `stop_infrastructure` makes the G10 test fail.

### M1 (`main` wipes out an exhaustion already recorded this run): fixed in code, no test

- `except Exception` now does `c.exhaustion_occurred = getattr(c, 'exhaustion_occurred', False) or isinstance(error, InfrastructureExhausted)`. The `BudgetError` branch is now OR-preserving too. The provider-wait branch doesn't touch the flag. `finalize_accounting` runs in `main`'s `finally`, after these assignments, and passes the flag as `new_exhaustion`. Correct by inspection.
- I added a probe test in the export only (not committed). It passes on HEAD:
  - **Setup:** a completed `close_to_passing` state, then a G10 marker, `terminal_stop='runner_error:KeyError'` and `exhaustion_occurred=True`.
  - **Result:** `finalize_accounting` creates a fresh UUID4 with `stop='infrastructure_exhausted'`, status pending and `replacement_eligible: False`. With the flag false, the completed state is unchanged.

## Findings

### Major

**Ma1. Nothing tests M1's fix or the flag wiring.**
- **Where:** `factory/run.py:3058`, `:3070` and `:2793`; `tests/factory/test_stream_d_runtime.py`.
- **What surviving mutations show:** each of these mutations still leaves the focused suite at OK:
  - (a) `c.exhaustion_occurred = isinstance(error, InfrastructureExhausted)`: this is review 14's M1, reintroduced.
  - (b) `c.exhaustion_occurred = False` in the `BudgetError` branch.
  - (c) `new_exhaustion=False` hard-coded in `finalize_accounting`.
- **Why it matters:** §8 says "Only a later, distinct code-recorded exhaustion … creates a fresh ID". Mutation (c) cuts the only production route to that, and no test notices. The existing regressions cover B1's label normalization only. `test_held_or_pending_extension_never_creates_a_new_diagnosis_id` calls `record_exhaustion` directly, so it never exercises the runner wiring.
- **Guidance:** add one runtime test through `finalize_accounting`:
  - Completed state, then `stop_infrastructure` (or the real `GatePipeline.run` G10 crash), followed by a non-infrastructure exception in the same run. Assert a fresh ID with `stop='infrastructure_exhausted'` and ineligible.
  - Ideally the test goes through `main`'s handler. If that's too heavy, factor the two flag lines so a test can reach them.
  - Also cover a completed state plus `BudgetError('budget_exhausted')`: assert a fresh, eligible ID. This kills mutations (b) and (c).

### Nits

- **N1.** Review 14's N3 still stands. Patching `run.model_call` in `test_first_exhaustion_is_checkpointed_pending_without_inline_diagnosis` proves nothing while there's no dispatcher. This is noted again only so it isn't read as resolved.
- **N2.** If a G10 crash marker is set in the `finally` while the outer error is `provider_wait` or a pause, `exhaustion()` excludes those stops, so nothing is recorded. The next run builds a fresh card without the marker. This is consistent with §8 ("provider wait … do not qualify"), and the resumed run re-executes the gates. No change requested; just flagging that a provider wait drops the in-flight infrastructure marker.

## 305c10c B-core projection test

`test_b_core_queues_pending_infrastructure_but_never_derives_a_child` calls D's real `pending_projection` through B's saved-ciphertext harness, using the real 5813 ledger.
- **Pending infrastructure:** projects as present `{schema_version:1, status:'pending', replacement_eligible:False}`, gives the queue entry `[('resume','j')]`, and leaves `derivations == {}`.
- **Completed `factory_bug`:** projects as `None`, with no queue entry for that generation and still no derivations.
- **Mutation:** dropping `and not infrastructure` from `pending_projection` makes the test fail.
- Matches §8 "Infrastructure exhaustion requests read-only diagnosis with a PRESENT pending projection whose replacement_eligible is false". Pass.

## Held-docs consistency (9aa72a1, checked only; no outcome producer claimed)

- **Allowed stage labels:** both docs now say valid `run.GATES` names, which exclude G12, plus `stress` and `unknown`. Matches `run.GATES` (`factory/run.py:33`, no G12) and the `crash_stop` regex `G(?:[1-9]|1[013-7])`.
- **`affected_operations`:** stream-d.md and interfaces.md agree. The list is intersected with the empty eligible set rather than rejected, and raw output stays private.
- **Write order and replay:** the durable write order (history, then finding, then completed state together with the stop and public marker) and the rule that a replay reuses the finding are worded the same in both docs.
- No conflict with the design PASS in `stream-d-factory-bug-design-3.md`.

## Zoom-out

The fix is minimal: one marker conditional in the shared producer, one flag assignment at the single place infrastructure exhaustion is recorded, and two OR-preserving handler lines. Both callers go through `record_exhaustion`, so the fix sits in the shared function, not per caller. No new abstractions, and the pure APIs (`exhaustion`, `actual_model_work`, `pending_projection`) are unchanged in `703ba99..9aa72a1`.

## Tests run (reviewer, export of `9aa72a1`, outside the worktree)

- `python3 -B -m unittest test_stream_d_runtime test_stream_d_projection`: **32 tests, OK** (17.1 s).
- **Mutations:**

| Mutation | Result |
|---|---|
| Marker revert | killed |
| Delete pipeline flag | killed |
| Projection drops `not infrastructure` | killed |
| `main` `except Exception` flag (M1 reintroduced) | **survived** |
| `main` `BudgetError` flag | **survived** |
| `new_exhaustion=False` wiring | **survived** |

- **M1 producer probe:** 2 tests, OK.
- **Full suite:** not run by this reviewer. Per the brief, the run from `703ba99` is superseded, and a fresh SHA-pinned run is pending for the parent to verify. No full-suite pass is claimed.

No Murphy row closes in this review.

---

**For you:** review 15 passes on `9aa72a1` with no blockers. B1 is fixed: reverting it fails both new tests. M1 is fixed in code, and my probe confirms the producer handles it correctly. But nothing tests M1: reintroducing the bug, or hard-coding `new_exhaustion=False`, still leaves all 32 tests passing. That's the one major. A single runtime test through `finalize_accounting` (a completed state, then an infrastructure exhaustion, then a non-infrastructure exception in the same run) closes it. I made no changes to the worktree. The scratch export is at `/private/tmp/claude-501/-Users-bugsincode-Developer-unbug-bench/6eb90111-9227-4085-a46d-25863627b335/scratchpad/r15`, and the probe at `/private/tmp/claude-501/-Users-bugsincode-Developer-unbug-bench/6eb90111-9227-4085-a46d-25863627b335/scratchpad/probe/test_probe_m1.py`.

## Elephant resolution

PASS accepted. Ma1 accepted: add a regression through main's exception handlers and finalize_accounting, covering completed state followed by a fresh infrastructure exhaustion plus a runner error, and completed state followed by budget_exhausted. Require new IDs and the correct replacement eligibility. No findings rejected; no Murphy row closed. Full suite will run on the router-maxima rebase, not the superseded 703ba99 run.

