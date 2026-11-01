**Verdict: BLOCK.** Round 3's B1, M-A and M-B are all fixed. One new blocker remains. Replaying G3 from its saved record skips work that G3 does on the machine and in the running process, and the fresh and replayed gates after it depend on that work. Neither earlier round raised this. The fix is a short design rule.

# Goldfish design review (round 4): `docs/designs/stream-d-package-completion.md`

**Personas:** zoom_out, design_critic, implementation_readiness. **Mode:** REVIEW. **Standards:** `heilmeier-standard.md`, `implementation-readiness-standard.md`.
**Worktree:** `t3-4ac6b632` @ `54344fc`. I worked read-only, made no edits and started no subagents.
**Read:**
- `docs/ENGINEERING.md`, the three persona files and both standards.
- The design. The Round 3 amendments are treated as binding over any earlier text they contradict.
- Reviews 1, 2 and 3.

**Code checked:**
- `carry_over.py`: `FACTS`, `DERIVED`, `VOLATILE`.
- Every key written to `card` across `factory/*.py`.
- `gate_pipeline.run`, `run._opencode`, `_gate_completed`, `_gate_pipeline`, `g3`/`g4`/`g5`, `checkpoint`, `calibrate`, `main`, `write_and_attack`.
- `gate_state.dependency_files`, `inputs`, `scientific_version`, `REUSABLE`.
- `bin/factory_pool.prepare`, `fairness.review_attempts`/`diagnose`, `late_recovery`, `model_router` (line 491), `key_holder.concurrent_peer_cancel`, `sealed_audit`'s use of `no_early_probe`, `model_runtime.update_case_budget`, `diagnosis_dispatch.CARRY`.

**Scope:** I accept the first-slice scope. Lines 9–14 and 173–176 keep these open, with no claim of package completion:
- entry capture;
- isolated current-version comparison;
- the writer-validation and public-match outcomes;
- version-drift integration.

Package increment 2 is still unchecked (`stream-d.md:3726`). The design supports Murphy rows 9 and 13 and closes none, which is correct.

## Status of the round 3 findings

| Finding | Status | What I checked |
|---|---|---|
| **B1(a): plumbing keys in the record** | **Fixed** | Lines 236–248 list every key round 3 asked for, plus the plumbing and identity keys from `FACTS`/`DERIVED`. The required test, where a model call changes `cleanup_errors` and `durable_checkpoint`, is at lines 259–261. Two gaps are left (M1 and N1 below). Neither blocks. |
| **B1(b): early-reused gates recorded empty** | **Fixed** | The record now holds the whole scientific card projection taken after `invoke`. So when `invoke` returns `c.early[gate]` (`gate_pipeline.py:135-137`), the record still holds the G3/G4/G5/G15 fields set during `early_checks`. Context values are captured whole too, so `prepared_factory_slots` survives. The equality test covers early-reused G4/G5 and `owner_contract` (line 259). |
| **M-A: replacement calibration roots** | **Fixed** | `fairness-replacement-<sha>/` holds `results.json`, `try-N/execution.json` and `guard/` (`fairness.py:63-74`). The transcript glob `strong-calibrator-<folder>-*.jsonl` matches `fairness.py:129-130`. |
| **M-B: completed replay hits the money check** | **Fixed** | A no-op `budget_boundary` covers both pipeline checks (`gate_pipeline.py:163`, `:200`). Completed replay skips `write_and_attack` and every `invoke`, so `checkpoint`'s own `case_budget_boundary` (`run.py:1713`) is never reached. `update_case_budget` in `after_gate` only reports. |
| Round 3 nits | **Fixed** | A missing record on completed replay raises `extension_outcome_changed` before `invoke`. One `reused=True` progress event is published. Version drift on completed replay is stated as accepted. The probe is disabled with `args.no_early_probe`, which has a precedent at `sealed_audit.py:191`. It is read at `run.py:892`, and it is not in the retry-journal identity, `gate_state.inputs` or `calibration_identity`. |

---

## Blocker

### B1. Replaying G3 from its record skips G3's work on the machine and in the process, which later gates depend on
**Scope:**
- Design: lines 74–76 ("any valid pass OR fail is replayed without calling invoke") and lines 96–98 plus Round 3 (the list of context keys).
- Code: `run.py:2397-2418`, `gate_state.py:24`, `:113`, `:154`, `:211`, `bin/factory_pool.py:26-44`, `run.py:1704-1711`, `gate_pipeline.py:139`.

**What G3 does besides returning its verdict:**
- It shrinks `c.args.bench_workers` in place when memory is short (`run.py:2401-2406`).
- It runs `factory_pool.prepare(..., fresh=True)`. Only this call clears and reseeds bench slot zero (`factory_pool.py:30`).
- It reads the Docker image ID.

**What replay keeps:**
- The record keeps the card value `bench_workers_effective`, but not `c.args.bench_workers`.
- On resume, `write_and_attack` raises its terminal handoff straight away, so no early checks run. G3 therefore never executes in the resumed process.

**What the ordinary path does today:** G3 is not in `REUSABLE`, so every ordinary resume runs G3 again. Later gates are never run in a process without a fresh G3.

**Concrete failures:**
1. **A false comparison-pending stop.**
   - Setup: a launch asks for `bench_workers=2`, and the VM has memory for only 1.
   - Fresh run: G3 lowers the value to 1. `dependency_files` then leaves `bin/factory_pool.py` out of the G4+ inputs, because it is in `MEASURE` and is skipped when `bench_workers == 1` (`gate_state.py:113`).
   - Completed-row replay: G3 is replayed, so `bench_workers` stays at 2. `scientific_version` for G4 now includes `factory_pool.py` and differs from G4's record.
   - Result: replay stops at `extension_comparison_pending`. It never reproduces the committed `extension_incomplete` or the all-pass seal. The resume after a G10 kill, which the design itself tests, stops the same way.
   - Note: `scientific_version` drops the `bench_workers` setting itself (`:211`), but not this choice of files.
2. **Fresh gates run on a machine G3 never prepared.**
   - Setup: a crash after the G10 record, then a resume on a restored or other slot (M4's "another slot" case).
   - Fresh G17 and G11 then run `checkpoint` with the original requested worker count (`run.py:1704-1705`), so they can use more memory than G3 allowed.
   - They also run against a slot zero that this VM never set up. Non-fresh prepare does not seed slot zero.
   - A failure there could be saved as a permanent scientific record. That is the "stale/wrong result" risk named at line 20.

**Why this blocks:** the design gives no rule for G3, so the implementer would have to make a design decision. The zero-decision rule does not allow that.

**Required change (two sentences):**
- **Simplest option.** `g3` cannot fail scientifically: it returns `True` or raises `InvalidInfra` (`run.py:2415-2418`).
  - In any traversal that may run a fresh gate, G3 always goes through ordinary `invoke`, as it does on an ordinary resume. Its saved record is used only for checking.
  - On completed-row replay, where no gate runs fresh, set `c.args.bench_workers` from the recorded `bench_workers_effective` before computing any later stage's version.
  - Either way, add `args.bench_workers` to the replayed context keys.
- **Tests:**
  - a memory-reduced G3 (requested 2, effective 1), with completed replay reproducing the outcome and no drift stop;
  - a resume after the G10 kill showing G3's setup ran before fresh G17/G11.

---

## Major

### M1. `calibration_interruptions` is a plumbing counter missing from the exclusions
**Scope:** Round 3 exclusion list (lines 236–251). Code: `run.py:2643-2645`, `key_holder.py:42-58`.

- This field counts infrastructure interruptions per calibrator. It is written during G10/G16/G17 model calls, and `key_holder.concurrent_peer_cancel` reads it to decide whether a cancel was caused by its peer.
- It works like `cleanup_errors`: an append-only operational counter. It is in `carry_over.FACTS`, but it is neither scientific nor one of the plumbing/identity keys the design says it excludes (line 249).
- As written, replay would put back the values from when the gate ran, over newer counts.
- **Fix:** add it to the exclusions. Optionally add it to the existing `cleanup_errors` test.

---

## Nits

- **N1. Two more fields could be excluded:**
  - `router_pending_requests`, written by `model_router.py:491` on a failed cancel. It is router plumbing next to `router_waits` and nothing reads it.
  - `gate_continuation`, the `late_recovery` marker that `mark_gates` writes before the traversal. Replaying an identical value is harmless today.

  Excluding both keeps the "plumbing never in the bench record" rule exact.
- **N2. Deletion wording.** Line 252 says "absent keys observed before invoke". Say "scientific keys present before invoke and absent after it". The only gate-time deletion I found is `fairness.diagnose` popping `difficulty` (`fairness.py:175`), and it needs that reading.
- **N3. `factory_slots_prepared` / `prepared_factory_slots` are `VOLATILE` in `carry_over.py`.** Replaying them from a dead VM only affects the cleanup range (`run_artifacts.py:141`) and the G6 overlap check, which is forced serial here. Acceptable, but once B1 is fixed, the G3 that actually runs should set them.

## Heilmeier and readiness
- **Heilmeier:** all eight questions are answered in plain language. The objective, current state, approach and impact are clear. Risks and payoff are covered. Cost: there is no new spend authority, production cost stays the stream-d qualification measurement, and completed replay spends nothing. Timeline: one cycle in two stable commits. The midterm and final exams are named.
- **Readiness:** this fails only on B1. Every other step names its files, hooks, keys, error strings and tests.

## Zoom-out
The design reuses the existing machinery and adds no new launch path:
- the ordinary pipeline plus `replay_gate` and `around_gate`;
- one record per stage;
- `snapshot()` unchanged;
- no-op money checks on completed replay;
- `no_early_probe` in place of a new API.

B1 is a G3-specific rule, not a redesign.

## Before PASS
1. **B1:** decide how G3 is replayed (re-run it whenever a fresh gate may follow), restore `c.args.bench_workers` on completed replay, and add the two tests.
2. **M1:** add `calibration_interruptions` to the exclusions.
3. A fresh goldfish reviews again.

## Elephant disposition

B1 accepted: ordinary G3 setup runs on incomplete traversals; completed replay
restores effective workers before later version checks. Added both requested
tests to the design. M1 and nits accepted: exclude operational counters/markers,
clarify deletions and preserve fresh G3 preparation state. No code edits yet;
fresh review requested.
