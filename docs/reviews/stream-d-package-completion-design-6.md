**PASS.** No blocking finding remains open. Round 5's B1 and M1 are fixed in both replay modes, and the first-slice scope still keeps the package checklist open. I found one new Major and three Nits. None of them blocks.

# Goldfish design review (round 6): `docs/designs/stream-d-package-completion.md`

**Personas:** zoom_out, design_critic, implementation_readiness. **Mode:** REVIEW. **Standards:** `heilmeier-standard.md`, `implementation-readiness-standard.md`.

**Setup:**
- Worktree `t3-4ac6b632` at `54344fc`, with the design and reviews 1–5 untracked.
- Read-only: no edits, no subagents.
- Read: `docs/ENGINEERING.md`, the three persona files, both standards, the whole design, review 5 in full and the end of review 4.
- Where amendments conflict, later rounds win: round 5 > 4 > 3 > 2 > the base text.

**Code checked:**
- `gate_state.py`: `MEASURE`, `DEPENDENCIES`, `STAGE_DEPENDENCIES`, `dependency_files` (line 113), `judge_dependencies` (`include_pool=True`), `scientific_version` (lines 199–212).
- `run.py`: `g3` (lines 2397–2418), the early-check calls inside `write_and_attack` (lines 1489 and 1505), the bench-workers argument check (lines 3164–3170).
- `bench.py`: `factory_memory_fits` and `docker_memory_bytes`.
- `gate_pipeline.py`: `early_checks` and the early-reuse branch (lines 74–137).
- `carry_over.VOLATILE`.
- Every place that raises `extension_comparison_pending`, and `diagnosis_dispatch.STOPS`.

**Scope:** accepted.
- Lines 9–14, 120–122, 173–176 and 272–273 keep these open: entry capture, isolated current-version comparison, the writer-validation and public-match outcomes, and version-drift integration.
- The package checklist stays open. The design supports Murphy rows 9 and 13 and closes none.
- Activation stays false. No section 4 or security rule changes.

## Round 5 findings

| Finding | Status | Evidence |
|---|---|---|
| **B1: version timing** | **Fixed** | Line 308 computes every new record's `scientific_version` after invoke. `g3` sets `c.args.bench_workers` to the effective count before it returns (`run.py:2402-2406`), so a fresh G3 record is versioned with the reduced count. Whether `factory_pool.py` counts as a dependency (`gate_state.py:113`) is then decided by the count that actually ran. |
| **B1: restored workers, completed rows** | **Fixed** | Lines 309–312 restore `args.bench_workers` from the G3 record's `bench_workers_effective` before checking G3's version. That key is always written (`run.py:2406`, before setup), so it is always in the post-invoke projection. Stages checked before G3 don't depend on the worker count: G1 and G2 have no `MEASURE` dependencies, and stress uses `include_pool=True` and drops `bench_workers` from its settings. The order is therefore safe. |
| **B1: restored workers, incomplete rows** | **Fixed** | The same restore runs before checking G3's version (line 310, "BOTH"). Ordinary G3 then starts from the restored count and can only lower it, because the `while > 1` loop never raises it. Test 1 (lines 317–319) covers the round 5 failure: requested 2, effective 1, kill after the G10 record, resume requesting 2. Test 2 (lines 319–320) covers "no G3 record yet". |
| **B1: one source of truth** | **Fixed** | Line 312 removes the duplicate `args.bench_workers` context field. The value is stored only in the G3 record and must be a positive integer, so a bad value is an invalid record and refuses (NB2). |
| **M1: runtime field preservation** | **Fixed** | Lines 321–323 make fresh G3 own `bench_workers_effective`, `factory_slots_prepared` and `prepared_factory_slots`, and later replayed projections must keep them. On completed replay no G3 runs, so the recorded values replay unchanged and stay consistent with the restored workers. |
| **N1–N3 (round 5)** | **Fixed** | Line 315 pops early G3; line 323 records image-ID drift as metadata only; line 327 excludes the ruling keys. |

---

## Blockers

None.

## Major (non-blocking)

### M1. Fresh G3 can lower the worker count below the recorded count, which makes later saved records show drift

**Scope:**
- Design line 313 ("may lower it further").
- Code: `gate_state.py:24` and `:113`, `bench.py:172-185`.

**Problem:**
- `MEASURE`, which includes `bin/factory_pool.py`, is a dependency of every stage from G4 onward.
- Suppose the G3 record holds 2 workers and saved G4–G10 records were versioned with 2. On an incomplete resume, fresh G3 can drop to 1 in two ways:
  - Docker reports less total memory, for example after a restore onto a smaller VM.
  - Any exception inside `factory_memory_fits` returns `False`. A transient `docker compose config` or `docker info` failure is enough, even on the same VM.
- The saved G4+ records then fail their version check and the run stops at `extension_comparison_pending`.
- `diagnosis_dispatch.STOPS` treats that stop as a held case, so a human has to step in.

**Why this does not block:**
- The stop is conservative. Nothing is rerolled or mis-scored.
- It happens off the normal path, and the next resume restores 2 and passes if Docker is healthy.
- Lines 120–122 and 272–273 already leave version-drift handling to the comparison slice.

**Recommendation:** add one sentence and one test. State that a fresh G3 count lower than the recorded count stops with `extension_comparison_pending`, and that the comparison slice owns it. List it in the remaining obligations at line 175 so it is not lost. Test: recorded effective 2, `factory_memory_fits` forced to `False` on resume. The run stops pending, and no saved record is rewritten or re-invoked.

## Nits

- **N1. Where to pop early G3 (line 315).** On an unfinished row, `write_and_attack` runs `early_checks` again (`run.py:1489`, `:1505`). That happens after a pop "at package entry", so the traversal reuses that early G3 result instead of running setup again. The reuse is harmless:
  - it ran in this process on this machine;
  - the post-invoke projection and version capture its reduced count;
  - this is the same as ordinary flow;
  - no G3 record can exist before stress passes.

  Still, it contradicts round 4's "execute ordinary G3 setup on every incomplete-row traversal". Say "pop immediately before `run_gates`" or "same-process early G3 reuse is acceptable".
- **N2. The G3 replay sequence is spread over three amendments.** The incomplete-row G3 sequence is split across rounds 2, 4 and 5:
  1. `replay_gate` checks the record and returns `None` so setup runs.
  2. `around_gate` keeps the recorded result and writes no new record.

  A three-line summary of that sequence would spare the implementer from piecing it together across rounds.
- **N3. The base text is still superseded in five places.** These include the closed allowlist at lines 91–96, the statement reconstruction at line 98, and the probe parameter at lines 225–227. Before implementation, think about folding the amendments into the body. That is optional, since ENGINEERING.md accepts superseding amendments.

## Heilmeier

All eight questions are answered:
- **Objective, current practice, new approach and impact:** stated plainly at lines 5–21.
- **Risks and payoff:** risks are stale score reuse, lost supporting bytes and replaying a completed rejection; the payoff is recoverable work.
- **Cost:** no new spend authority. Completed replay uses no-op money checks (line 267).
- **Timeline:** one cycle in two stable commits (line 231).
- **Exams:** the midterm is the gate record restart tests; the final is full package replay, the seal contract and the full suite.

## Implementation readiness

This passes:
- Files, hooks, record schema, exclusions, error strings, ordering rules and tests are all named.
- Both reduced-worker replay tests are named with concrete inputs.
- Each of the two commits leaves the code in a stable state.

M1 is an unstated outcome, not a choice left to the implementer: the code as designed stops conservatively.

## Zoom-out

The design reuses what exists and adds no new launch path:
- the ordinary pipeline plus `replay_gate` and `around_gate`;
- one record per stage;
- `snapshot()` unchanged;
- `no_early_probe` in place of a new API;
- a single stored worker count.

The G3 exception is the minimum the code needs. No YAGNI or reinvention found.

## Verdict

**PASS.** Implementation may start. Addressing M1 and the nits is recommended but optional. The diff review must check:
- versions are computed after invoke;
- the G3 restore happens before the version check in both modes;
- the fresh G3 runtime fields are preserved;
- both reduced-worker tests exist and use real G3.
