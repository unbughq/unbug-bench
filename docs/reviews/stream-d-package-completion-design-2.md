# Goldfish design review (round 2): `docs/designs/stream-d-package-completion.md`

**Verdict: BLOCK.** Two blockers remain. Both are small to fix, but each breaks the main promise of this slice: a saved result is replayed and never rerun, and a replayed all-pass seals a card that can be used as an exam.

**Personas:** zoom_out, design_critic, implementation_readiness. **Mode:** REVIEW. **Standards:** `heilmeier-standard.md`, `implementation-readiness-standard.md`.
**Worktree:** `t3-4ac6b632` @ `54344fc`. I reviewed read-only. I did not write anything or start any subagents.
**Code checked:** `run.py` (`main`, `write_and_attack`, `_gate_pipeline`, `run_gates`, `validate_and_repair`, `finalize_accounting`, `early_probe`, `g7`, `g10`, `g11`), `gate_pipeline.py`, `gate_attempt.py`, `bin/run_validity.retry`, `gate_state.py`, `extension_compare.py`, `extensions.py`, `diagnosis.py`, `diagnosis_dispatch.py`, `late_recovery.py`, `run_artifacts.py`, `sealed_audit.retain_delivery`, the `stream-d.md` checklist, and `test_stream_d_execution.py`.

**Scope:** I accept the first-slice scope. Comparison, entry capture, writer-validation and public-match outcomes, and version drift are explicitly left open. Package increment 2 stays unchecked (`stream-d.md:3726`).

---

## Status of the earlier blockers

| Finding | Status | Notes |
|---|---|---|
| B1: reuse contradiction | **Fixed in design** | There is one record per stage. A valid pass or fail is replayed without calling invoke, and `snapshot()` is unchanged. One remaining window is NB2 below. |
| B2: support evidence | **Mostly fixed** | `support/inputs.json` (from `gate_state.inputs`) means support is never empty, so `_save` (`extension_compare.py:144`) cannot go pending. The evidence roots are named wrongly or contradict each other: see M1 and M2. |
| B3: isolated layout | **Resolved by deferral** | Explicitly sequenced inside the same increment, and the checklist stays open. |
| B4: card/seal contract | **Mostly fixed** | Uses `run_gates`, `mark_gates`, `after_gate`/`early_probe`, `stop_infrastructure`, a serial G10 and the ordinary `finally` seal. There is no second publisher. What remains is NB1 (card effects) and M3. |
| B5: fail label and diagnosis | **Fixed** | The label is `extension_incomplete` and `exhaustion_occurred` is set. Verified: `record_exhaustion` with `new_exhaustion=True` → `_trigger` is true only once the outcome is committed (`diagnosis.py:49`, `:141-144`) → one new pending exhaustion. Tests are listed. |
| Earlier Majors M1–M6, nits N1–N2 | **Fixed** | One record. Snapshot is taken after traversal, so the `case_hash` check against `freshness.jsonl` holds. Early and cache reuse is covered. Entry capture is deferred. Heilmeier answers are present. Tests use real evidence. |

**Main and dispatch routes, verified against the code:**
- **Today:** after "history written, card not written", `apply` → `extensions.active()` returns `None` for a completed row, so the run stops at `extension_comparison_pending` forever. The proposed change to `apply` (match on `exhaustion_id`, skip `writer_receipt`) is necessary and sufficient.
- **The lagging card is tolerated upstream:**
  - `extensions.read` allows the public view to lag by one completed outcome (`extensions.py:139-146`).
  - `_state` switches its origin once the outcome lands (`diagnosis.py:65-68`).
  - `queued_inputs` checks only frozen inputs.
- **The same route also recovers a `seal_error` after an all-pass.**
- **In `main`:** routing with an `elif`, the guard on `validate_and_repair`, and clearing the carried `status`/`terminal_stop` set by `apply` all work. `c.stopped` stays False, so the run reaches the ordinary `seal`.

---

## Blockers

### NB1. The closed list of card keys drops gate-owned fields, so a replayed seal is not exam-eligible
- **Scope:** design lines 91-96. `run.py:2831` (G10 sets `owner_contract`). `sealed_audit.py:73` (`verify_exam_metadata` refuses when `owner_contract` is missing or different).
- **Finding:**
  - The design lists the card keys to capture and does not include `owner_contract`.
  - `CARRY` does not carry it, so the key disappears whenever G10 is replayed instead of run. That covers:
    - a kill after the G10 record, then resume;
    - every outcome replay through dispatch.
  - The run reaches G12 and is marked `pass`, then exam admission rejects it with "case needs qualification with the current reviewer owner".
  - Other gate-written keys are also missing from the list:
    - `flakiness_rerun` (G7, `:2495`; it is G7's actual `info`);
    - `negative_probes_ok` (`:2484`);
    - `bench_workers_effective` (G3, `:2406`);
    - `freshness_confirmation`, `admission_freshness`, `freshness_reverify`, `freshness_topup` (G2 path, `:677-726`, `:2290-2393`);
    - `strategy_reuse` (`:1936`, `:1960`);
    - `calibration_progress` and `calibration_interruptions`.
- **Required change:** capture the card as a diff around invoke, covering every key that was added, changed or removed, and drop the explicit allow-list. Keep the exclusion list the design already has (accounting, diagnosis, history, money, route receipts, terminal/status, `gates`/`gate_results`/timings). Add a test that the gate-owned card keys after a replayed traversal equal those after a fresh traversal, with `owner_contract` asserted by name.

### NB2. Looking up the record inside the retry journal can turn a valid record into a permanent `infrastructure_exhausted`
- **Scope:** design lines 40-45 ("wraps invoke *inside* gate_attempt.execute"). `gate_pipeline.py:139-146`. `bin/run_validity.py:77-85`.
- **Finding:** `execute` → `retry` runs `start()` before calling invoke, so the record check runs after the journal has decided.
  - `start()` turns a leftover `running` flag into an invalid attempt.
  - Failure case: attempt 1 crashed (`invalid_attempts=1`), attempt 2 finished and published its record, then a kill hit before `running=False` was written. On resume, `start()` raises `InfrastructureExhausted`. The record is never consulted, and `stop_infrastructure` stops the run.
  - The raise happens inside `update()` before the write, so the journal never changes. Every later resume repeats the same stop, so a scored result sits on disk while the case parks forever.
  - This contradicts line 75 ("Once record exists, any valid pass OR fail is replayed without calling invoke") and the listed "kill before/after stage record" test.
- **Required change:**
  - Check for a valid record in `run_gate` **before** `gate_attempt.execute`. For example, split the callback into `replay(c, gate)` and `around_gate(c, gate, invoke)`, or have the callback wrap the `execute` call itself.
  - Keep capture inside invoke.
  - Add a test: journal row `{running: true, invalid_attempts: 1}` plus a valid record → the record is replayed and the journal is untouched.

---

## Major

### M1. The support roots for G10/G11/G16/G17 name directories that don't hold the proof
- **Scope:** design lines 86-89. `run.py:50` and `:2800`. `run.py:2582-2583`. `fairness.py:63`, `:97`, `:123`, `:156`. `gate_state.inventory` (`:225-235`).
- **Finding:** `pilot-strong` and `pilot-easy` are Unix pilot **home directories**, not work folders.
  - They live outside `c.work`, need sudo, and are shredded by `early_probe` (`:2767-2772`) and `wipe`.
  - Under the serial override, G10 uses the user `pilot`, not those two.
  - The real calibration proof lives under `c.work`:
    - `strong_calibrator/` and `easy_calibrator/`: `results.json`, per-try `execution.json`, and `guard/` (the G11 inputs);
    - `early_probe/`, `judge_breadth/`, `fairness-*`;
    - `g11-evidence/`.
  - Only `judge_breadth` and `review-*` are in `inventory()`, so as written G10's actual verdict inputs would not be copied.
  - "Relevant work outputs" also leaves the choice to the implementer.
- **Required change:** list exact roots per gate, and say which files (`results.json`, `execution.json`, `guard/**`) rather than whole try workspaces. Each byte is copied three times: stage support, `comparison-support`, then `extension-snapshots`.

### M2. The rule for `gate-details` contradicts itself
- **Scope:** design line 72 ("Include existing gate-details/<gate>.json, even unchanged") against line 78 ("retain gate-details/<gate>.json containing the actual returned info").
- **Finding:** the implementer has to choose between two readings:
  - Write a new live `c.work/gate-details/<G>.json`. This collides with the files G5, G8, G15 and G16 own, and feeds later writer feedback (`run.py:1213-1215`).
  - Copy an unchanged file from an earlier run. That attributes evidence from another run to this execution.
- **Required change:** `record.info` already holds the returned info. Never write live `gate-details`. Copy only the `gate-details` files this invocation changed, plus gate-cache evidence when a cached result is reused.

### M3. Carried state on the outcome-replay path, and the infrastructure stop after `run_gates`
- **Scope:** design lines 36-38 and 138-147. `gate_pipeline.py:149-157` and `:200`. `run_artifacts.py:73`. `diagnosis_dispatch.CARRY`.
- **Finding (a):** the design clears carried `failed_gate`, `gates` and `infrastructure_gate` only "after successful stress".
  - On the completed-row replay path, `write_and_attack` is skipped.
  - If the clear doesn't run there, a stale carried `failed_gate` blocks the end-of-run `budget_boundary` and causes seal to skip `retain_delivery`, even though every gate passed.
- **Finding (b):** `stop_infrastructure` sets `c.stopped` and **returns** without raising.
  - If the package then builds a snapshot, there is no record for that gate, so the read adapter goes pending and `complete` raises `extension_execution_pending`.
  - `main` then replaces `terminal_stop` (`infrastructure_exhausted` becomes `extension_execution_pending`).
- **Required change:**
  - Run the clear whenever the stress record is a pass, whether fresh or replayed.
  - After `run_gates`, if `c.stopped`, return without calling snapshot or complete.

### M4. Outcome replay must not rebuild the snapshot
- **Scope:** design lines 141-144. `extension_compare._execution` (`:70-73`). `extensions.complete` (`:498-500`).
- **Finding:** each receipt embeds execution provenance (`seed`, `slot`, `UNBUG_FACTORY_SLOT`).
  - If replay calls `snapshot()` and then `complete()` again to be idempotent, the receipts will differ after a restore onto another slot or VM.
  - `complete` then raises `extension_outcome_changed`.
- **Required change:** for a completed row:
  - Never call `snapshot` or `complete`.
  - Check that the per-stage pass/fail and the failing stage from the replayed traversal match `row['outcome']`; on a mismatch, stop with `extension_outcome_changed`.

---

## Nits
- **Snapshot inputs are unnamed.** Say which object `snapshot()` receives (the live `c`, or `Workspace(c.case, c.work, BENCH, …)`), and that `source_generation = job_authority.for_case(c).source_generation`.
- **Only record results `_pending` would accept.** Otherwise treat the result as invalid-infra and write no record. A recorded result in a pending shape (`error`, or `verdict_valid: False` on a pass) would replay forever as `extension_execution_pending`.
- **`early_probe` slot.** `early_probe` calls the global `g10_overlap_reason` (`run.py:2757`), not the serial override. Its slot then differs from serial G10's slot 0, so the probe try isn't reused and one extra strong try is spent. It can also start a model call during the "no fresh evaluations" outcome replay if no completed probe try was retained. State whether either is allowed.
- **Statement listed twice.** `statement` appears both as a captured context effect and as "G1 reconstructs statement". Pick one.
- **"Package records exist" check in `apply`.** Name the exact check, for example a valid `extension-package/<id>/stress/record.json`.
- **Phasing.** "One large cycle": the midterm exam is fine, but name the two stable commits (record and replay hook; then package plus dispatch).
- **Murphy.** "Supports rows 9/13, closes none" is correct. Lines 13 and 136 also say there is no new stop string, and that holds: `extension_snapshot_changed` and `extension_incomplete` already exist.

## Zoom-out
The architecture is now right. It uses the ordinary pipeline with one hook, one record per stage, and `snapshot()` unchanged as the single producer of receipts. Both blockers are small changes to that design; neither needs a new path.

## Remaining work before PASS
1. **NB1:** capture card effects as a diff with exclusions, plus a test that fresh and replayed cards match, including `owner_contract`.
2. **NB2:** check the record before the retry journal, plus the stale-journal replay test.
3. **M1–M4:** one paragraph each, because they still leave decisions to the implementer.

After that, a fresh goldfish should re-review.

## Elephant disposition

NB1/NB2 and M1-M4 accepted. Design now captures card diffs with exclusions,
replays before retry admission, uses actual calibration evidence roots, avoids
live gate-detail writes, clears carried fields for all stress-pass routes,
preserves returned infrastructure stops, and never regenerates completed outcomes.
Package disables optional early probe while keeping ordinary checkpoints. Fresh
review required; no production changes yet.
