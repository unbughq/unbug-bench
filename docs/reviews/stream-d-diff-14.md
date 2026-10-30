# Stream D diff review 14: durable pending diagnosis producer

**Reviewer:** fresh goldfish (read-only), Mode REVIEW
**Personas:** `zoom_out`, `implementation_readiness`
**Standard:** `implementation-readiness-standard.md`

**Scope:** the code is reviewed cumulatively from `390c9c1` to HEAD `703ba99`.
- `703ba99` "Checkpoint durable pending diagnosis on first exhaustion" changes `factory/diagnosis.py` (`record_exhaustion`), `factory/gate_pipeline.py` (`stop_infrastructure` flag), `factory/run.py` (`inherit_recovery_history`, `finalize_accounting`, and the `main` exception handlers), and `tests/factory/test_stream_d_runtime.py`, which gets 2 tests.
- `305c10c` is in scope only for `tests/factory/test_stream_d_projection.py::test_b_core_queues_pending_infrastructure_but_never_derives_a_child`.

The factory-bug held design amendment in `305c10c` (`interfaces.md`, `stream-d.md`, `stream-d-factory-bug-design-2.md`) has its own goldfish and is excluded. The only part of it used here is the parent clarification that pending infrastructure projects as present with `replacement_eligible: false`, and that completed diagnoses project `None`. The `.stream-d-next/` drafts are also excluded.

**Checked against:**
- `interfaces.md` §8: "Replacement derivation and D's exhaustion projection", and "Final diagnosis projection APIs" together with the `diagnosis_state` lifecycle paragraph;
- the stream-d design;
- `recovery.infrastructure_exhausted`;
- the `GatePipeline.run` stop and finally paths;
- `model_runtime.case_budget_boundary`.

**Prior findings on this producer:** none. **Rejected findings:** none. **Row closures claimed:** none, which is correct. `docs/murphy-register.md` is not in the diff.

## Verdict: FAIL (1 blocker, 1 major, 3 nits)

The basic shape is right:
- The producer runs after the final accounting and before the seal.
- No diagnosis model call happens inline.
- A pending ID survives retries and `finalize_accounting` replays.
- A completed state is replaced only when an explicit flag says this run had a new exhaustion.
- An active extension or `factory_bug_held` never mints a new ID.
- `inherit_recovery_history` deep-copies the state, so the restored card does not alias the old one.
- The three pure APIs did not change.

But the producer breaks one explicit §8 rule about the infrastructure marker, and that changes what B is allowed to do.

## Blockers

### B1: an infrastructure exhaustion recorded under another stop label makes the case eligible for a replacement

**Where:** `factory/diagnosis.py`, `record_exhaustion`, the last 4 lines.

**The rule:** §8 says: "When that helper [`recovery.infrastructure_exhausted`] triggers despite another terminal_stop, diagnosis_state.stop is the literal infrastructure_exhausted." The parent clarification adds that infrastructure exhaustion "does not spawn replacement chains".

**What the code does:** `record_exhaustion` gates on `_trigger(card, card['terminal_stop'], ...)` and then writes `stop=card['terminal_stop']`. It never checks the `infrastructure_gate.exhausted` marker.

**How it happens in real code:** `GatePipeline.run` handles one case explicitly. `budget_boundary` raises `BudgetError('budget_exhausted')` while G10 is running. The `finally` block then waits for G10. If G10 crashed, `stop_infrastructure('G10', ...)` sets `terminal_stop='infrastructure_exhausted'` and the marker. The `BudgetError` then reaches `main`, which overwrites `terminal_stop` with `'budget_exhausted'`.

The same overwrite also happens on the normal path. An infrastructure stop does `break`, and then `if not failed_gate: self.budget_boundary(c)` runs and can raise.

**Probe** (in memory, on the HEAD `diagnosis.py`):
```
card: terminal_stop=budget_exhausted, infrastructure_gate.exhausted=True, one event
before record_exhaustion: {'status':'pending','replacement_eligible': False}
after  record_exhaustion: state.stop='budget_exhausted', {'replacement_eligible': True}
```
Before the producer existed, the legacy projection correctly said the case was not eligible. The new producer turns an infrastructure exhaustion into a case that B is allowed to replace with a child. That is exactly what the parent ruling forbids.

**A second effect:** with `terminal_stop='runner_error:KeyError'` plus the marker, nothing is recorded, because `_trigger` is false. `pending_projection` still returns a present pending record, but no `exhaustion_id` is ever created. That breaks "On first exhaustion it creates the ID once, before the checkpoint."

**Fix:**
1. Compute `stop = 'infrastructure_exhausted' if recovery.infrastructure_exhausted(card) else card.get('terminal_stop')`.
2. Use that value for both `_trigger` and the stored `stop`.

For a completed state, the existing `new_exhaustion` gate still stops a marker that was merely kept from an earlier run from minting a new ID.

**Tests to add:**
- `terminal_stop='budget_exhausted'` with the marker gives `stop == 'infrastructure_exhausted'` and `replacement_eligible is False`.
- `runner_error:*` with the marker gives a pending ID.

Ideally, also drive the G10-finally path through `GatePipeline.run` with a fake crashed G10 and a raising `budget_boundary`.

## Majors

### M1: `main`'s generic exception handler wipes out an exhaustion that already happened in the same run

**Where:** `run.py`, `main`, `except Exception`.

The handler sets `c.exhaustion_occurred = isinstance(error, InfrastructureExhausted)`. That overwrites a `True` that `stop_infrastructure` already set if a non-infrastructure exception follows in the same run.

When a completed state exists, this hides the new exhaustion, and no fresh ID is created. The `BudgetError` handler has the same pattern, but it is harmless there because it can only set the flag to `True`.

**Fix:** use `c.exhaustion_occurred = getattr(c, 'exhaustion_occurred', False) or ...` in both handlers.

This is not a blocker, because it needs a completed state plus 2 failures in one run. The fix is 2 lines.

## Nits

- **N1:** `BudgetError` in `main` sets the flag for every message, including `statement-ready`, `cancelled` and `diagnosis_state_invalid`. This is safe today only because `_trigger(terminal_stop)` filters those out afterwards. A comment, or narrowing the check to trigger stops, would make that dependency visible.
- **N2:** `record_exhaustion` validates the history and state, and then `exhaustion(card)` validates them again. This is redundant but harmless.
- **N3:** `test_first_exhaustion_is_checkpointed_pending_without_inline_diagnosis` patches `run.model_call`. Diagnosis has no dispatcher today, so the assertion is vacuous. It is still useful as a guard for when one is added.

## Independent checks

- **Focused tests:** I ran `python -B -m unittest test_stream_d_runtime test_stream_d_projection` at HEAD with `PYTHONPATH=factory:tests/factory:tests`. Result: 30 tests, OK.
- **The B-core test (`305c10c`):** it calls the real D API on the real 5813 ledger, through B's saved-ciphertext harness.
  - Pending infrastructure gives a present, ineligible projection, a `resume` queue entry for `j`, and no derivations.
  - Completed `factory_bug_held` gives a `None` projection, no queue entry for that generation, and no derivations.
  - The test correctly says it uses the harness's authored envelopes, and it asserts only on D's predicates. It is acceptable.
- **Full suite:** the first line of `/tmp/stream-d-state-suite.log` is `703ba99e...`, which matches HEAD. The suite was still running (in `tests/bench/`) when I read it, so this review does not claim the full suite passed.
- **Integration with `cfe616f`:** no source conflicts. The pure API bodies are byte-identical apart from the appended `record_exhaustion`.

## Scope confirmations

None of these are in the diff, and none are claimed: an outcome producer, diagnosis dispatch, an extension runner, enabling money, or closing any Murphy row.

## Disposition

The review fails. B1 must be fixed and re-reviewed. M1 is recommended in the same change.

---

**For you:** the review fails on one blocker, B1. On a card that ran out of infrastructure retries but whose stop label was later overwritten (for example with `budget_exhausted`), the producer records that label instead of `infrastructure_exhausted`. That makes the projection `replacement_eligible: True`, which the parent ruling forbids. I confirmed it with an in-memory probe, and the overwrite path really exists in `GatePipeline.run`. The fix is to store `infrastructure_exhausted` whenever the marker is set, plus 2 tests.

The 30 focused tests pass. The full suite was still running when I checked, so I'm not claiming it passed. I'm in read-only mode, so I didn't write the file. The text above is what goes in `docs/reviews/stream-d-diff-14.md`.

## Elephant resolution

B1 and M1 accepted. Normalize the new exhaustion to infrastructure_exhausted whenever the code marker is set, and preserve an exhaustion already recorded in this run through subsequent exception handling. Add regressions for overwritten budget and runner-error stops. No findings rejected; no Murphy row closes.

