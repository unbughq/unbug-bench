# Startup smoke design review 2 (final round)

Goldfish: fresh Claude (claude-opus-5-5) general-purpose subagent, read-only. Personas: zoom_out, design_critic, implementation_readiness; Mode: REVIEW. Design: docs/designs/startup-smoke.md at cdb3133.

## Verdict: FAIL. Two new blockers, both text only. All three review-1 code fixes are verified correct.

### Review-1 blockers
- **B1 (money): resolved.**
  - `check_manifest` requires each request > 0 (`:55`), each incremental > 0 (`:72`), and a sum ≤ `money_limit_usd` (`:74`). 0.01 + 19.98 = 19.99 passes.
  - When practice is admitted, the smoke's 0.01 stays held: `aggregate` takes max(held, floor) (`:318-320`). `authorize_locked` (`:338`) sees 0.01 + 19.98 = 19.99, which is not above the limit.
  - At G1 (`gate_pipeline.py:178` → `model_runtime.case_budget_boundary` → `budget.py:716`), spent 0 ≥ committed 0.01 is false, so G1 runs. A missing ledger reads as `{}` and spends 0.
- **B2 (case key): resolved.**
  - `vm_recipient` exists at `run_artifacts.py:105`. In batch mode it is `factory/control-recipient.txt`, which equals the manifest `restore_recipient` (required at `batch_money.py:101`).
  - `case_recipient` needs only the work dir, the sealed dir, the case id, `c.recipient` (the throwaway public key, set at `run.py:3380-3385` before sealing) and `vm_recipient`. A dry run has all of these.
  - `_card` (`batch_service.py:180`) then finds `casekey.age`. No collection code checks `dry_run`.
- **B3 (-2 sites): resolved.** A repo-wide grep finds no other hard-coded sites: `practice.py:8,11,22`, the cleanup unit `:9`, `practice_preflight.py:19` and `test_practice_readiness.py:92-93`. Everything else goes through `practice.BATCH`.
- **Ledger fix:** `jload` takes a default (`run.py:165`), and `reconcile_reservations` writes nothing when there is no ledger.
- **Two operations:** cleanup state and arming are per operation (`practice_cleanup.py:22,31-46`), and `max_concurrency` (`batch_holder.py:242-245`) stops overlap.

### Leak check
No leak.
- `casekey.age` is wrapped to the throwaway key plus the control-VM restore key. The archive is sealed to the throwaway key plus the case key.
- The contents are the fixture work tree plus the opencode state from `run.py:40-41`, with no credentials.
- The throwaway private key already reaches the control VM via `collect.sh:55,72`; that is existing dry-run behavior.
- One new side effect: a batch dry run now uploads its ciphertext to R2 (`run_artifacts.py:128`), because `case_key` is set. That is harmless.

### Blocking
**B1. The runbook rewrite replaces steps 4–6, but step 3 is what breaks the order.**
- Design `:94-103`. `practice-run.md` step 3 runs `qualify-batch-inputs.py --job practice`, reserves practice and starts its cleanup unit.
- Followed literally, practice becomes the pending operation. Reserving smoke is then refused (`batch_holder.py:242-245`), and `<smoke-op>` can't exist. Either practice runs without a smoke, or the batch stalls.
- Fix: the rewrite covers steps 3–6.
  - Qualify and reserve `--job smoke`, then start `cleanup@<smoke-op>`.
  - After the smoke passes, qualify and reserve `--job practice`, then start `cleanup@<practice-op>`.
  - The step-4 disconnect and the step-6 `practice-fault.py` arm apply to the practice operation only.

**B2. The test plan names a fixture that holds no card.**
- Design `:126-130`. On `t3/batch-service-control-vm`, `practice-startup-conflict-20261103.json` is a list of 7 `{location, message}` log excerpts, not a scorecard.
- That leaves the `finalize_accounting` test without a real card, which breaks the section 4 real-artifacts rule.
- Fix: name a real collected batch card, such as `tests/factory/fixtures/canary6-collected-card.json` on that branch, or feed a real dry-run `run.py` card.

### Nits
- **N1.** `test_practice_readiness.py:94-97` asserts practice 19.990000000, which fails after the reallocation. Add it to the update list, and change `old['id']` at `:105-106` to -2.
- **N2.** Line drift:
  - `batch_money.py` `:51`/`:65` are now `:55`/`:72`, and the sum check is at `:74`;
  - `DROPIN` is at `practice_preflight.py:19`.
- **N3.** "Order enforced by existing code" overstates it. The code only stops the jobs overlapping; smoke-first and the pass gate before practice are the operator's job.
- **N4.** `terminal_stop` can be `runner_error:<Type>` (`run.py:3145`), so the pass rule should be "does not start with `runner_error`".
- **N5.** `practice_preflight.LIVE` still shows 19.990000000 for the practice ceiling (`:22`). Update it to 19.98, or note why not.
- **N6.** Use a fresh dict literal for the empty-ledger default, not a shared constant.
- **N7.** The deployment step should say that the control-VM `policy.json` and the release/pins bundle are rebuilt for -3. `manifest()` checks the release's `source-manifest.json`, and the pins include `practice.conf`.

## Elephant resolution (parent decision at the 2-round cap)
Both blockers are accepted and fixed in revision 3 without a third design round, since each has an exact fix and doesn't change direction. The diff goldfish confirms them. All of N1–N7 are adopted.
