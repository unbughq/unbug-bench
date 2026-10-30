**Verdict: PASS** for `fab9014a9773784538450faa9cc4bd4469b2e210` (diff `7c36097..fab9014`). There are no blockers, but two majors must be fixed before the diagnosis dispatcher calls this producer. I wrote no files, so the review text below is for you to save as `docs/reviews/stream-d-diff-17.md`.

---

# Review: stream-d diff 17 (held-outcome producer): PASS

**Reviewer:** fresh goldfish, read-only, `Mode: REVIEW`, using the zoom_out and implementation_readiness personas. Checked against ENGINEERING.md, implementation-readiness-standard.md, stream-d.md's held lifecycle and the three factory-bug design reviews with their elephant resolutions. `.stream-d-next/` was excluded.

## What holds
- **Result validator.** `validate_result` checks the exact keys and that `schema_version` is the int 1, not a bool. It binds the case and the checkpoint generation, and checks the outcome against its allowed set. It rejects any evidence path that is absolute, contains `..` or `.`, is a symlink at any level, or has the wrong SHA-256. The `factory_bug` keys are exact, and the operations must be unique UUID4s. A non-factory outcome requires `factory_bug: null`. The returned result is a deep copy with `affected_operations: []`, which is the narrowing that design-3's Ma1 chose.
- **Finding schema.** The finding has exactly the 7 fields. The UUID, batch and release are supplied by code, and `eligible_operation_ids` and `failure_receipts` are always `[]`. No v2 waste record is written. In the test on the real 5813be ledger, the ledger bytes are unchanged.
- **Raw result file.** It is a content-addressed private file written before the finding. It carries no authority and is never read back.
- **Write order.** The order is history, then raw result, then finding, then an fsync of the new parent directories, then `scorecard.json`. The scorecard write carries the completed `diagnosis_state`, `terminal_stop`, `factory_bug` and the count together. This matches design-3's N3.
- **First-hold history.** History is created only when all of these are absent: a `factory_bug` field or count on either card, any `finding.json`, and any `factory_bug` waste row in the ledger or in `continuation_budget`. Malformed history never resets. A retained finding with missing history refuses with `factory_bug_history_invalid`, and the count is removed.
- **Replay.** `restore_factory_bug` re-verifies the stored finding and completes the hold without a model. `persist` with a different finding refuses and does not overwrite.
- **Same-batch refusal.** `require_model_work` sits at the top of `model_runtime.dispatch`, before `prepare_dispatch` and the lease. I confirmed that every `await_lease` caller goes through `dispatch`: `run.pending_call` (`run.py:332`) and `Runtime.call` → `_call` (`model_runtime.py:322`). `record_exhaustion` never mints a new ID on a `factory_bug_held` card.
- **Recovery.** `inherit_recovery_history` deep-copies `factory_bug` and `factory_bug_resume_count`.
- **carry_over.** `diagnosis_state`, `extension_history` and `factory_bug` are FACTS, and the count is DERIVED, which is correct because it equals the history length. Before this change, `v0_to_v1` would have refused cards carrying these fields as unclassified.
- **Scope.** Nothing claims more than the slice does. Nothing calls `persist_factory_bug` or `restore_factory_bug` yet. Cross-batch resume, waste attribution and extension execution are still off, and no Murphy row is closed.

## Blockers
None.

## Majors (fix before the dispatcher is wired)

**Ma1. `factory_bug_history_invalid` leaves an infrastructure case projecting `pending`.**
- `_factory_bug_history` sets the stop to `factory_bug_history_invalid` but leaves `diagnosis_state` pending.
- For an infrastructure stop, `infrastructure_exhausted(card)` is still true through `infrastructure_gate.exhausted`. So `pending_projection` still returns `{status:'pending', replacement_eligible:false}`.
  - Probe on an export of the commit: invalid history file → stop is `factory_bug_history_invalid`, projection is present.
- B will therefore keep queueing same-owner diagnosis resumes, and each one fails the same way.
- Non-infrastructure stops project `None` in the same situation, so the two kinds of stop behave differently. The design wants a terminal "check case" stop.
- The same path also overwrites `factory_bug_held` on an already-held card when its history is later damaged. After that, `record_exhaustion(new_exhaustion=True)` mints a fresh pending ID, which reopens the projection. Money stays safe because `'factory_bug' in card` still refuses dispatch, but the card no longer reads correctly.
- **Fix:** make `exhaustion()` false when the stop is `factory_bug_history_invalid`, or never let the history-invalid stop replace `factory_bug_held`. Add a projection assertion for both cases.

**Ma2. Replay re-hashes evidence that can change, so a crash can block the hold for good.**
- `restore_factory_bug` re-runs `validate_result`, and that re-checks the SHA-256 of every evidence file under `evidence_root`.
- The tests use `evidence_root=self.work` with the live ledger as evidence, and the ledger is append-only and grows.
- Probe: a crash before `scorecard.json`, then one byte appended to the ledger. Both `restore` and `persist` then raise `diagnosis_result_invalid`. The immutable finding can never complete, and the case stays pending.
- **Fix:** pin `evidence_root` to the immutable queued input checkpoint (the one `generation` names) and state that in the design. Or verify only the finding binding on replay, not current evidence bytes. Then re-point the test's evidence at immutable bytes.

## Nits
- n1. `persist_factory_bug` raises `diagnosis_outcome_changed` for a valid non-factory outcome. The name suggests a replay mismatch. `diagnosis_outcome_not_factory_bug` would be clearer.
- n2. Two spots raise `AttributeError` instead of a `BudgetError`:
  - `_complete_factory_bug` calls `recorded.get('diagnosis_state', {}).get(...)`, which raises if the checkpoint's `diagnosis_state` is not a dict;
  - `_held_stage` calls `card.get('infrastructure_gate', {}).get('gate')`, which has the same problem.
- n3. The finding-binding check is duplicated between `persist` (equality with the rebuilt finding) and `restore` (field checks). One shared validator would keep the two from drifting apart.
- n4. `require_model_work` refuses whenever the card has a `factory_bug` field. The later-batch resume will have to relax this together with B's addendum. Note it as a known edit point so that addendum cannot bypass it silently.
- n5. There is a stray triple blank line before `_held_stage`.

## Tests
- Run on a clean `git archive fab9014` export with `python3 tests/factory/<file>.py` (pytest is not installed):
  - `test_stream_d_held`: 10 OK
  - `test_stream_d_runtime`: 26 OK
  - `test_stream_d_projection`: 7 OK
  - `test_carry_over`: 10 OK
- Total: 53 pass, matching your count.
- My three probes in `/private/tmp/claude-501/-Users-bugsincode-Developer-unbug-bench/abe35750-5312-43ec-911f-213b2a3636c4/scratchpad/probe17.py` reproduced Ma1, Ma2 and the case in Ma1 where a damaged history on a held card gets a fresh pending ID.
- The pinned full suite at `/tmp/stream-d-held-suite.log` was still running when I last checked (it had reached `tests/bench/test-launch-guards.py`), so I have no result for it.

**Private content and cost headroom:** none exposed and none created. The public field holds only the code-sourced stage and the fixed class, and the eligible set is always empty.

---

Both majors are fine while nothing calls the producer, but each would leave a case stuck once the dispatcher is wired. Check the full-suite log before merging.

## Elephant resolution

PASS accepted for the explicitly unwired producer. Ma1 and Ma2 accepted and required before dispatcher wiring: factory_bug_history_invalid is a terminal attention stop with no pending projection, and the result/replay evidence root must be the immutable queued input snapshot, never the live work ledger. Add regression assertions for pending and completed history-invalid cards and a live-ledger append after an interrupted finding write. N2 will receive type guards; N4 remains an explicit edit point in B's later cross-batch addendum. No finding rejected and no Murphy row closed. Keep the currently running fab9014 suite pinned; the dispatcher slice must include and review these fixes before activation.

