**Verdict: BLOCK.** Round 4's G3 blocker is only partly fixed, and that remaining part is the one blocker. The fix for completed rows is right. The fix for incomplete rows doesn't say which worker count to use when checking G3's version. It also doesn't say when any record's version is computed. On the normal resume path this causes a false `extension_comparison_pending` stop, the same kind of stop round 4 blocked on. The operational exclusions are resolved. Everything else from rounds 1–4 holds.

# Goldfish design review (round 5): `docs/designs/stream-d-package-completion.md`

**Personas:** zoom_out, design_critic, implementation_readiness. **Mode:** REVIEW. **Standards:** `heilmeier-standard.md`, `implementation-readiness-standard.md` (and the zoom-out standard named by its persona).

**Setup:**
- Worktree `t3-4ac6b632` at `54344fc`. Read-only, no edits, no subagents.
- Read: `docs/ENGINEERING.md`, the three persona files, the standards, the design, and reviews 1–4.
- Where amendments conflict, later rounds win: round 4 over round 3 over round 2 over the base text.

**Code checked:**
- `run.py`: `g3`, `GATES`/`EARLY_GATES`, `validate_and_repair`, `write_and_attack` final-repair path, `calibrate`, bench-workers flag and uses
- `gate_state.py`: `MEASURE`, `STAGE_DEPENDENCIES`, `dependency_files`, `inputs`, `scientific_version`
- `gate_pipeline.py`: `early_checks`, `run`/`run_gate`
- `gate_attempt.execute`, `run_validity.retry`
- `bench.factory_memory_fits`
- `late_recovery.py`: `mark_gates`, `stop_defect`
- `carry_over.py`: `FACTS`, `DERIVED`, `VOLATILE`
- `launch.sh:346-347`, `resume-in-place.sh:45-47`
- A grep of every card key written in `factory/*.py` and `bin/*.py`, compared with the keys named in the amendments.

**Scope:** I accept the first-slice scope.
- Lines 9–14 and 173–176, and round 3 lines 272–273, keep these open: entry capture, isolated current-version comparison, the writer-validation and public-match outcomes, and version-drift integration.
- The package checklist stays open. The design supports Murphy rows 9 and 13 and closes none.
- Activation stays false.

## Status of the round 4 findings

| Finding | Status | Evidence |
|---|---|---|
| **B1: G3 replay skips machine/process setup** | **Partly fixed. The rest is B1 below.** | **Fixed:** incomplete rows always run ordinary G3 setup, skip in-memory early reuse, and keep the recorded verdict (lines 282–288). This matches the code: `g3` returns True or raises `InvalidInfra` (`run.py:2415-2418`), and `retry` really re-invokes after an earlier success (`run_validity.py:103`), so setup actually runs. Completed replay restores effective workers before later version checks (lines 290–294). Both tests are named.<br>**Open:** which worker count the incomplete-row G3 version check uses, and when record versions are computed. |
| **M1: `calibration_interruptions`** | **Fixed** | Line 300. |
| **N1: `router_pending_requests`, `gate_continuation`** | **Fixed** | Line 300. `gate_continuation` is written by `mark_gates` before the traversal (`late_recovery.py:42`), so excluding it is right. |
| **N2: what a deletion means** | **Fixed** | Lines 301–302. |
| **N3: fresh G3 owns preparation state** | **Partly fixed** | Lines 302–304 protect `factory_slots_prepared` and `prepared_factory_slots`, but not `bench_workers_effective`. See M1. |

**Operational exclusions:**
- I compared every key the code writes with the keys named in the amendments.
- The keys still unnamed are either scientific gate output or writer-phase facts that replay with the same values. Examples: `flakiness_rerun`, `negative_probes_ok`, `freshness_*`, `strategy_reuse`, `calibration_progress`, `stress_review`, `loop_freshness`, `admission`.
- `late_defect` cannot be written during the package traversal, because `validate_and_repair` is not called.
- No plumbing counter is left unexcluded. Ruling keys are covered under N1 below.

---

## Blocker

### B1. The incomplete-row G3 check uses an unspecified worker count, and the time a record's version is computed is unspecified

**Scope:**
- Design lines 285 ("Validate any existing G3 record before setup"), 290–294, and 60 (the `scientific_version` field).
- Code: `gate_state.py:24`, `:45`, `:113`, `:211`; `run.py:2401-2406`; `resume-in-place.sh:45-47`; `launch.sh:347`.

**Why the worker count matters:**
- G3's dependencies are `MEASURE + …`, which includes `bin/factory_pool.py`.
- `dependency_files` drops that file only when `c.args.bench_workers == 1` (`gate_state.py:113`).
- `scientific_version` removes the `bench_workers` setting itself (`:211`), but not this choice of files.
- So G3's version depends on the worker count in `args` when the version is computed.
- G1 and G2 don't depend on `factory_pool.py`, and G4 onward are checked after fresh G3 has run. G3 is the only stage affected.

**Failure 1: incomplete resume (the normal path):**
1. The VM is small. `launch.sh` and `resume-in-place.sh` always pass `--bench-workers $(nproc/2)`, so 2 are requested. Memory fits only 1.
2. In the original run, `early_checks` G3 lowered `args.bench_workers` to 1. Traversal G3 then started from 1, so G3's record version was computed with 1 worker, without `factory_pool.py`.
3. The process is killed after the G10 record. On resume, `args.bench_workers` is 2 again. `write_and_attack` raises its terminal handoff at once, so no early G3 runs.
4. The package replays G1 and G2, then hits G3.
5. Line 285 says to check the G3 record *before* setup. With current args (2 workers), the version includes `factory_pool.py` and differs from the record.
6. The run stops at `extension_comparison_pending`. It stops the same way on every later resume, and no route exists until the comparison slice lands.

Line 294's "using recorded effective workers as well" sits in the completed-row paragraph. The implementer has to guess whether it also covers incomplete rows. The incomplete-replay test at lines 296–297 doesn't require reduced workers, so it can pass with this bug.

**Failure 2: when the version is computed:**
1. The run crashes after stress but before G3's record exists.
2. On resume, traversal G3 runs fresh starting from the requested 2 workers.
3. If the record's version is computed *before* invoke, it includes `factory_pool.py`.
4. Completed replay then checks it "using recorded effective workers" (1), so it doesn't match. That is a false drift stop again.

The design never says whether `scientific_version` is computed before or after invoke.

**Required change (two sentences plus one test):**
- Compute each record's `scientific_version` after invoke returns.
- Before checking any existing G3 record, on both completed and incomplete rows, set `c.args.bench_workers` to the recorded effective count.
  - Fresh G3 setup then starts from that value and can only lower it.
  - This replaces the two-source rule (context `args.bench_workers` and card `bench_workers_effective`) with one source.
- Extend the incomplete-replay test: requested 2, recorded effective 1, kill after the G10 record, resume with `--bench-workers 2`. G3 setup runs, there is no drift stop, and fresh G17/G11 run with 1 worker.

---

## Major

### M1. Later stages' projections overwrite the `bench_workers_effective` that fresh G3 sets

**Scope:**
- Lines 250–251, which keep `bench_workers_effective` as scientific output.
- Lines 302–304, which protect only `factory_slots_prepared` and `prepared_factory_slots`.
- Code: `run.py:2406`, `carry_over.py:37` (`VOLATILE`).

**Problem:**
- On an incomplete replay, fresh G3 writes the effective count for this machine.
- Each replayed G4+ record holds a complete projection that includes the old value, and replay overwrites the fresh one.
- The published scorecard then reports a worker count the gates did not use. The key is `VOLATILE` and only reported, so this is a wrong scorecard field, not a wrong verdict.

**Fix:** add `bench_workers_effective` to the runtime fields owned by fresh G3 in lines 302–304.

---

## Nits

- **N1. Ruling keys in the projection.** `founder_ruling`, `call_cap_ruling` and `freshness_archive_ruling` are founder authority, not gate output (`founder_ruling.py:115`, `founder_decisions.py:27-32`). Today they replay with the same values. Excluding them would keep a later ruling from being overwritten by an older projection.
- **N2. How to skip G3's early reuse.** "Bypass in-memory early reuse for G3" names no mechanism. `around_gate` only receives `invoke`, and `invoke` checks `c.early` first (`gate_pipeline.py:133-137`). Say "pop `c.early['G3']` at package entry". It is the only option that needs no new pipeline API.
- **N3. Image ID in G3's verdict.** On incomplete rows the recorded G3 `info.image` may differ from the image fresh setup reports. It is reported, not part of the scientific identity (`MEDUSA_DEPS_IMAGE` is). One sentence saying it is accepted would stop a reader treating it as drift.

## Heilmeier and readiness

- **Heilmeier:**
  - The objective, current practice and new approach are stated plainly at lines 5–21.
  - Impact: recoverable work. Risks and payoff are named.
  - Cost: no new spend authority, completed replay spends nothing, and production cost stays the stream-d qualification measurement.
  - Timeline: one cycle in two stable commits.
  - Exams: the midterm is the gate record restart tests; the final is full package replay, the seal contract and the full suite.
- **Readiness:** this fails only on B1, an implementer decision that produces a real false stop. Files, hooks, keys, error strings and tests are otherwise named. Phasing is two stable commits.

## Zoom-out

The design reuses the ordinary pipeline and adds no new launch path:
- `replay_gate`/`around_gate`;
- one record per stage;
- `snapshot()` unchanged;
- no-op money checks on completed replay;
- `no_early_probe` in place of a new API.

The G3 exception is the minimum the code needs. B1 is a one-rule fix, not a redesign.

## Before PASS

1. **B1:** compute versions after invoke, restore the recorded effective workers before any G3 record check, and add the reduced-workers incomplete-resume test.
2. **M1:** fresh G3 also owns `bench_workers_effective`.
3. A fresh goldfish reviews again.

## Elephant disposition

B1 and M1 accepted. Record versions are post-invoke; both G3 replay modes restore
the single recorded effective worker count before version validation. Added both
reduced-memory replay cases and preservation of all fresh G3 runtime fields.
Nits accepted (explicit early-cache pop, image-ID metadata, ruling exclusions).
Fresh design review required before implementation.
