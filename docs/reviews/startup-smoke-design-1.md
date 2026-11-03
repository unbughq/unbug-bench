# Startup smoke design review 1

Goldfish: fresh Claude (claude-opus-5-5) general-purpose subagent, read-only. Personas: zoom_out, design_critic, implementation_readiness; Mode: REVIEW. Design: docs/designs/startup-smoke.md at 65b530a.

## Verdict: FAIL

The plan stands: one launch path, a smoke job the operator runs first, and deletion of the separate gate-smoke path. But a $0 smoke job as specified never reaches G1, and its card can't be collected. Both problems sit in money and sealing code that the design assumed needed no change.

## Blocking

B1. A $0 job is refused, and would stop before G1 even if accepted.
- `factory/batch_money.py:51` refuses any job with `requested_total_usd <= 0`, and `:65` refuses `incremental_usd <= 0`. This runs inside `money.manifest()`, so the smoke entry makes the whole -3 manifest unreadable, and every operation, practice included, sits in `money_wait`.
- Even if admitted, `gate_pipeline.py:178` checks the budget before every gate, including G1. Under a job budget, `budget.py:716` raises `money_wait` when `spent + outstanding >= committed`, and 0 ≥ 0, so the run stops with `terminal_stop=money_wait` and never runs G1.
- The smoke's allocation is held and never released (`batch_money.py:291`, `aggregate`), and `:68` refuses allocations that sum above `money_limit_usd`.
Smallest fix: give the smoke a small non-zero allocation, for example `0.010000000` for both `requested_total_usd` and `incremental_usd`, and either lower practice to 19.98 or have the founder raise the $19.99 limit. Pick one, and use that value in the test "admission accepts smoke".

B2. Batch collection refuses every dry-run card.
- `batch_service.py:180` (`_card`) requires `<case>.casekey.age`, and `run_artifacts.py:109` sets `case_key = None if c.args.dry_run`. So `service.collect` fails with "missing wrapped key", and the pass condition "collected and published" can never be met.
- The design's sealing claims don't match the code. `collect.sh` does copy `*.throwaway-key.txt`, but `service.collect` copies only `COLLECTION_SUFFIXES` (`launch_manifest.py:119`), so the throwaway key is dropped. Collection never checks an archive's recipient, so "refuse throwaway-key cards for non-dry jobs" describes a check that doesn't exist.
Smallest fix: in `run_artifacts.py:109`, still wrap a case key for a batch-mode dry run, i.e. when the restore recipient is set: `case_key = None if c.args.dry_run and not vm_recipient else r2_upload.case_recipient(...)`. The archive is then sealed to throwaway + case key, and `_card` passes unchanged, with no change to collection or publication. Drop the "refuse throwaway-key for non-dry" requirement: only `--dry-run` ever makes a throwaway key (`run.py:3380`).

B3. "Nothing else changes" is false: renaming to -3 stalls the first live smoke. `b-plumbing-practice-2` is hard-coded in three more places: `control/unbug-practice-cleanup@.service:9` (`Environment=... UNBUG_PRACTICE_BATCH=b-plumbing-practice-2`), `factory/practice_preflight.py:18` (`DROPIN`) and `tests/factory/test_practice_readiness.py:92-93`. With the unit still at -2, `practice_cleanup.main` exits on `practice.active()` with "request_refused", so `armed()` raises `MoneyWait("cleanup not armed")` and `dispatch` returns TEMPFAIL for ever. That is exactly the live pit stop this design exists to prevent. Fix: list these files, and redeploy the cleanup unit and the drop-in.

## Answers
1. The dry run has no other blockers on the batch path:
   - `batch.bind` doesn't forbid `--dry-run` (`batch.py:154`);
   - `launch.sh` still delivers the router secrets and worker qualification, and skips only the selection board (`:381`);
   - `run.py` skips pick_models, provider preflight, early probes and durable checkpoints under `dry_run`;
   - account selection is the same as practice.

   The only blockers are B1 and B2. `coordinator.configuration_args` forbids `--dry-run`, but only TTL continuation calls it, and batch dispatch doesn't arrange continuation.
2. The ledger fix is correct and sufficient. Tracing `collection_facts` with `{'cost':0,'calls':0,'events':[]}` gives card total = reported total = 0.000000000, prior 0.000000000 from authorize_locked, and no refusal. A one-line option: `jload(c.ledger, EMPTY if c.args.dry_run else None)` in finalize_accounting (`run.py:3139`). A $0 job does not pass admission (B1).
3. Two jobs, smoke first, work with operator ordering. `max_concurrency: 1` blocks practice until the smoke's deletion is verified (`batch_holder.py:242-245`, `_reconcile_one`). Cleanup and fault are keyed per operation, and `roles()` reads only `jobs['practice']`. The operator must start one cleanup unit per operation.
4. There's no measured setup or G3 time on the Boat image, so nothing shows G3 fits in 1800 s. The dependency branch also adds a fresh `factory_pool.prepare(1)` before G1, and G3 prepares fresh again. If the cap hits mid-gate, collect.sh sends SIGTERM, run.py stops, seals a checkpoint and writes DONE, so once B2 is fixed the card is collected with `terminal_stop=paused`. Cleanup deletes at start + 2700 s, but the pause allows up to 1200 s from 1800 s, so a slow seal can lose the card. That limit already applies to practice.
5. Deleting gate-smoke is safe for callers (only `tests/tools/test_gate_smoke.py` uses it), but coverage is lost (N2).
6. The design moves toward one launch path and deletes the second one. The only over-built part is the throwaway-key refusal in B2.

## Nits
N1. Give G3 timing evidence, or make G1 plus startup prepare the pass bar and only record G3.
N2. Deleting gate-smoke drops coverage the smoke job doesn't replace:
- G15 strategy on the real image (dry runs skip G15);
- the restored-state leftover `unbug-factory-1-seed` container;
- the `case_permissions` restore EACCES check;
- the two-slot parallel proof.
State that this loss is accepted.
N3. If the smoke's accounting is refused, `state['incidents']` blocks admission for the whole batch (`batch_holder.py:224`), so practice can't run in -3. Note the fallback: cut a -4.
N4. "Closes when the first live smoke passes" misses the ENGINEERING section 2 rule that a closing test uses real artifacts. Name a test that replays the saved smoke card.
N5. "Runs automatically before every practice and pilot attempt, no founder pause" contradicts "the operator dispatches smoke" and "first live run confirmed with the founder", and pilot manifests are out of scope.
N6. The practice-run step 4–6 rewrite is too vague: list the per-operation cleanup-unit start for each job.
N7. `practice-startup-error.md` and the fixture exist only on `t3/batch-service-control-vm`. That fits the stated dependency, but say so.

## Elephant resolution
All three blockers are accepted. B1: the smoke gets 0.010000000, and practice drops to 19.980000000, inside the founder-approved $19.99 total. That reallocates approved money rather than adding any. B2: adopt the case-key wrap fix and drop the non-dry refusal. B3: list and update all -2 sites, with a redeploy step. N1: the pass bar becomes G1 plus startup prepare, with G3 recorded. N2: keep gate-smoke for now and don't delete it; deleting it is a separate decision. N3–N7 adopted.
