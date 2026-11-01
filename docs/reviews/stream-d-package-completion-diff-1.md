**BLOCK.** The code matches the design and I found no defect in it. Two tests the design requires are missing, and that is what blocks the merge.

# Goldfish diff review: `stream-d-package-completion`, base `54344fc` → head `d1917ed`

**Setup:**
- **Personas:** zoom_out and implementation_readiness. **Mode:** REVIEW. **Standard:** `implementation-readiness-standard.md`.
- **Read first:** `docs/ENGINEERING.md`, both persona files, the standard, the whole design including all amendments (later rounds win), design review 6 and the availability note.
- **Read-only:** no edits, no subagents, no checkout created. The worktree is at HEAD and clean.
- I re-ran `tests/factory/test_stream_d_execution.py` myself: 23 tests, OK.
- The suite record `…155420Z-c9044583.json` shows 160 scripts and 0 failed at `895221b`. Between `895221b` and `d1917ed` only docs and reports changed: `git diff --name-only` lists only `docs/` paths.

## Checklist you asked for

| Item | Result | Where |
|---|---|---|
| Identity and support bytes | OK | `extension_package.py:57-91`. The record checks: the digest envelope, the exact key set, the writer operation and round, `case_sha256` (from `runner.case_hash`), excluded keys, result shapes accepted by `_pending`, support paths under this stage's own prefix, and a hash for every copied file. Symlinks and `..` are refused by `extension_compare._path`. |
| Scientific version computed after invoke | OK | `:188` runs inside `save()`, which only runs after `invoke()` returns (`:206-215`). |
| G3 worker count restored before its version check, both modes | OK | `:83-88` restores `bench_workers_effective` before checking the version. Incomplete rows return `None` (`:119`), then `capture` runs real setup and stops `extension_comparison_pending` if the count dropped further (`:208-214`). Early G3 is popped just before `run_gates` (`:294`). Fresh G3 with no record yet saves a version that reflects the reduced count. |
| Fresh setup on incomplete rows | OK | G3 always goes through `capture`. A G3 record never short-circuits setup on an incomplete row (`:201`). |
| Runtime fields preserved | OK | `PREPARATION` plus `prepared_factory_slots` are skipped once `prepared` is set (`:95-99`). The exclusion list matches design rounds 1–5 key for key. |
| Replay before the retry journal, and retry after a committed record | OK | `gate_pipeline.py:139-142` checks the record before `gate_attempt.execute`. `capture` re-checks the record on an in-process retry (`:200-203`). Both are tested. |
| Early gate effects and plumbing exclusions | OK | The card is projected after invoke, so early-reused G4 and G5 keep their effects. `no_early_probe` is set and then restored to its prior value or absence (`:295-303`), and it is not part of the retry or version identity. Overlap is forced off with `serial=True` (`run.py:2999`). |
| Completed route checked before model selection | OK | `completed_route` checks only the stress record with `check_version=False`. The test deletes `c.models` before calling it. |
| Completed replay: no snapshot, no complete, no spend | OK | `replay_only` turns `budget_boundary` into a no-op. A missing record raises `extension_outcome_changed`. Stage statuses are compared against `row.outcome` (`:305-309`). The test forbids both `snapshot` and `complete` and runs on slot 9. |
| Infrastructure stop labels | OK | If the run stopped, the package returns at once (`:304`), keeping `infrastructure_exhausted` and leaving history open. `record_exhaustion` queues no diagnosis while the row is open (`diagnosis.py:146-147`). |
| Ordinary seal and exam eligibility | OK by reading the code; not tested end to end | When every gate passes, the package returns normally and the existing `finally` block seals (`run.py:3383`), so `retain_delivery` runs. `statement` comes back through the context fields. See M3. |
| Real-artifact tests | **Partial** | See B1 and B2. |

## Blockers

**B1. The new crash-recovery route in `diagnosis_dispatch.apply` has no test** (`diagnosis_dispatch.py:236-247`).
- **Design requirement:** a test of outcome history-before-card replay through dispatch.
- **What is missing:** nothing calls `apply` with a completed history row. That leaves four new pieces of logic unexercised:
  - looking up the last history row when no row is active;
  - matching its `exhaustion_id` against the manifest;
  - choosing `completed_route` instead of `writer_receipt`;
  - returning the extension ID when `DIAGNOSIS_ENABLED` is set.
- `test_stream_d_dispatch.py` stubs `extension_package.run`, and the package test calls `completed_route` directly.
- **Fix:**
  1. Admit a row, complete the package, then roll the card's `extension_history` back to `outcome_sha256=None`.
  2. Call `apply(..., resume=True)` with `DIAGNOSIS_ENABLED`. Assert it returns the ID and never calls `writer_receipt`.
  3. Also assert that a different `exhaustion_id` gives the plain `stop` path.

**B2. The design's required real-artifact and stage-rule tests are missing.**
- **Design requirements:** "Run real G1 over practice artifacts and real freshness confirmation fixture", and "a table covering each stage's artifact rule". Round 3 and M1 add the evidence-root rules for G10, G11, G16, G17, G2 and stress.
- **What the tests do now:**
  - The G1 test uses a stand-in invoke, not `run.g1`.
  - Nothing exercises G2.
  - The G10 capture in `test_calibration_delivery.py` makes no assertion about what support was copied.
- **What is therefore unverified:** the copy rules in `sources()` (`:141-159`):
  - the calibration file filter (results, execution, guard files);
  - `fairness-replacement-*` and `g11-evidence`;
  - the G2 public-search, confirmation and retrieval files;
  - transcripts.
- The real-artifacts rule applies here: a regression in any of these would silently drop proof.
- **Fix:**
  - Run real `g1` over the practice case.
  - Run real G2 over the saved freshness and confirmation fixture.
  - Add one table-driven test that lays out each root and asserts which files land in `support`, including the excluded non-calibration files and that pilot homes are never touched.

## Major (non-blocking)

- **M1. Some refusal paths have no test.** The design names "tampered/missing/symlink support" and "stale case/version". Only tampered support is tested, at `:252-260`. Missing support, symlinked support, a mismatched `case_sha256`, and drift in a non-G3 `scientific_version` are not. The code is correct by inspection, because `_path` and `load` handle them.
- **M2. Rebuilding `votes` (G8) and `pilot_passes` (G10) is untested.** These are the design's "G8 votes/G10 pilot reconstruction" tests. The `_guard` and `is_file` paths at `:100-102` and the work-relative encoding at `:184` are never run. G11 depends on them after a restart.
- **M3. No test drives `main()` through the package.** Untested at that level:
  - the `elif` that skips `build`;
  - `validate_and_repair` being skipped when `extension_id` is set;
  - an all-pass run reaching `seal` and G12;
  - `extension_incomplete` going through main's handler.

  The dispatch test stubs the package, and the package tests call `finalize_accounting` by hand. A crash before the record is published is not tested on its own either; the existing test covers a failure after the rename.

## Nits

1. `:284-286` duplicates `:288-290`. The first clear-gates block can go.
2. Some refusal labels are misleading:
   - A bad stress receipt or shape raises the default `extension_snapshot_changed` (`:256-258`).
   - A record with corrupt JSON comes out as `extension_reservation_mismatch` from `_writer_json`, not as a package label.
3. The stress record copies the entire gate inventory because `before={}` (`:260`). That attributes old gate-details and bench results from before the extension to the stress proof, which goes against the spirit of design M2.
4. A failed stress round leaves no `failed_gate`. As a result `_held_stage` reports `'unknown'` instead of `'stress'` in the diagnosis finding (`diagnosis.py:232-235`).
5. Completed replay restores `prepared_factory_slots` from the VM that originally ran G3. This affects only cleanup scope.

## Zoom-out

The design reuses what exists and adds nothing speculative:
- the ordinary pipeline plus two optional hooks;
- one record per stage;
- `snapshot()` unchanged;
- no second publisher or repair loop.

## Out of scope (declined as instructed)

- Terminal writer and public-match outcomes, including writer precheck failure with no stress proof.
- Entry capture, isolated current-version comparison, and resolving version drift, including a further worker reduction. This slice deliberately leaves these as `extension_comparison_pending`.
- Diagnosis outcome routing.
- The unimplemented terminal-outcomes draft.
- Live qualification and cost measurement.
- Deleting the legacy allowances, which belongs to lane 1.
- Murphy closures. None are claimed, and the checkbox correctly stays open.

## Verdict

**BLOCK** on B1 and B2. Both are missing tests the design requires; I found no code defect. Once those tests are added and pass, I expect this to pass. M1–M3 are recommended.


## Implementation disposition (awaiting fresh verification)

B1: Added `test_dispatch_recovers_history_committed_before_card`. It uses real admission and package completion, rolls the public history back to its admitted projection, calls real `diagnosis_dispatch.apply` with activation enabled, forbids writer receipt access, and checks both the matching recovery and different-exhaustion stop.

B2: Added real G1 contract evaluation over retained practice bytes and real G2 retrieval/confirmation validation over saved HTTP bytes (only the model answer and external fetch transport are authored). Added an independent table for G2/G10/G11/G16/G17/stress support roots, calibration exclusions, transcript selection, exact copied bytes, and exclusion of pilot-home layouts. These tests claim local retention mechanics, not live qualification or a Murphy closure.

The non-blocking recommendations M1–M3 and nits remain recorded above; this follow-up is limited to the two blocking test gaps. All listed deferred behaviors remain outside this reviewed slice. No production behavior changed and package increment 2 was not started.

Review policy now forbids paid OpenRouter. Reviewer order is Claude, free OpenCode `opencode/deepseek-v4.1-flash-free`, then fresh Codex `gpt-6.1-sol` with only a brief. The free model hit its usage limit on the first renewed attempt; Claude subsequently completed this review. No paid provider was used for these renewed attempts.
