# Design review 4: neuralwatt-first (goldfish)

**Scope:** the "Neuralwatt first (2026-11-20)" section of `docs/designs/neuralwatt-routes.md` (lines 327-691) at 038643c1, checked against `git diff 3dfdde3c -- factory tests`. Lenses: zoom_out, design_critic, implementation_readiness. I treated the operator's `systemctl cat` output as given.

**Tests run:**
- `test_neuralwatt_routes.py`, `test_neuralwatt_runtime.py` and `test_model_router.py` all pass.
- The step 2 assert passes on this tree, and `CHAINS[0]` is the DeepSeek chain.
- The code has not changed since round 3 (`git diff --stat 5ba15c89 038643c1` shows docs only). So round 3's mutation result still holds: removing either `knows` filter fails the tests.

**Earlier blocking findings, re-checked**

- **R1 B1 (off-switch loop): resolved.**
  - `_admit` sends `chain=chain(model)` (`model_router.py:889`).
  - The router filters by `knows()` in `choices` (`:540`) and in the queue-ahead check (`:567`).
  - `LATE_ROUTES` (`:68`) covers the one late lane.
  - A malformed chain is refused (`:529-530`).
- **R1 B2 (list price is also what each step books): resolved.**
  - The text at `:356-366` matches `budget.py:1410-1413`.
  - `runtime_prices` and `nw_request_worst` both read `_nw_profile` (`token_prices.py:81-84`, `:101`, `:144`).
- **R2 B1 (rollback hard-stops cases): resolved.** `:674-691` has the never-downgrade rules, withdrawing the key as the loop-free path, and `disabled_routes` as emergency only.
- **R3 B1 (router checkout): partly resolved.**
  - Given the operator data, `:438-444` is now correct: the last `ExecStart` wins, and both drop-ins reset it.
  - The router and the controller both run from `source-current`.
  - So pointing `source-current` at the release and restarting does move the router onto new code.
  - But the way step 2 does the switch is not safe. See finding 1.

**Findings**

1. **BLOCKING: deploy step 2 switches `source-current` and restarts the controller without the repo's drain check, and the order leaves a window.**
   - **What step 2 says (`:651-661`):** point `source-current` at the release, run the assert, do "one drained router restart", then restart `unbug-durable-case-campaign.service`.
   - **Problem 1: the controller restart is never gated on the controller being drained.**
     - The repo's gate for this is `control/check-drained.py`. It checks two things:
       - no attempt holds a leased worker without a recorded `attempt_step`;
       - no router lease is still unexpired.
     - Its docstring says a controller restart mid-step "cost 19 hours of infra:worker_lost".
     - A drained router (no model call in flight) does not mean a drained controller: a step can hold a worker between model calls.
   - **Problem 2: the symlink moves before anything is proven drained.**
     - For the whole router drain, which may be long, the old controller runs with its files replaced. That is the mixed state `:660-661` itself warns against.
   - **Problem 3: "the release" source tree is never named.** `unbug install` (step 1) installs the worker bundle, not a tree for `source-current`.
   - **The repo already has the sanctioned path, and the design never mentions it.**
     - `control/release.py switch --config C --plumbing <commit> --source-current <path> --unit unbug-model-router.service --unit unbug-durable-case-campaign.service` (`release.py:416-424`):
       - refuses unless `check-drained.py` exits 0;
       - then prints `ln -sfn <build-plumbing tree> <source-current>` and both restarts, back to back.
     - `release.py build-plumbing <commit>` builds the tree (`:323-345`).
   - **Fix (text only).** Rewrite step 2 as:
     1. Confirm the router's `ExecStart` (see finding 2).
     2. Run `release.py build-plumbing <release>`.
     3. Run the assert with `cwd=` the built tree.
     4. Run `release.py switch … --router-db <router db> --unit unbug-model-router.service --unit unbug-durable-case-campaign.service`.
     5. Run the printed root commands at once.

2. **NIT: verify the router config systemd has loaded, before and after the restart.**
   - `systemctl cat` prints the files on disk, but a restart without `daemon-reload` uses the loaded unit.
   - **Before:** use `systemctl show -p ExecStart --value unbug-model-router.service`.
   - **After the restart:**
     - check that `readlink -f ~/durable-first-case-20261106/source-current` is the release tree;
     - check that `/proc/$(systemctl show -p MainPID --value unbug-model-router.service)/cmdline` names `source-current`.
     - Then resume launches (step 3). Today the first proof comes at step 4, after launches have resumed.
   - Use `/usr/bin/python3` for the assert, matching the `ExecStart`.

3. **NIT: the fallback branch of step 2 is ambiguous.**
   - `:653-654` says "steps 2 and 5 apply to that checkout instead". If the router ran from somewhere else, the controller would still need `source-current` moved.
   - Say "as well as `source-current`", and name both checkouts in the rollback.

4. **NIT: stale router-checkout text is still in the same doc and repo.**
   - Rollout runbook step 3 (`:193-199`) still tells the operator to fast-forward `/home/user/unbug-bench`.
   - `control/unbug-model-router.service:14` still names that path, but on the VM it is overridden.
   - The new section notes this (`:442-443`), but the next operator who follows the runbook will update the wrong checkout.
   - Fix: mark `:193-199` as superseded by the 11-20 finding, or check the two drop-ins into `control/`.

5. **NIT (carried from round 3): items still open, not blocking.**
   - The founder has not yet confirmed booking case money at 1.8× (`:367-370`).
   - The Murphy rows (`:628-639`) are still not in the register.

**Verdict: FAIL** (1 blocking)

## Elephant response (2026-11-20)

Everything is fixed in the text, and nothing is rejected.

- **B1.** The deploy is now built on the repo's own release path.
  - Step 2 runs `control/release.py build-plumbing <release>` (or the equivalent 11-19 hand form) and runs the assert inside that tree with `/usr/bin/python3`. It installs nothing and does not touch `source-current`.
  - Step 4 runs `control/release.py switch … --router-db … --unit unbug-model-router.service --unit unbug-durable-case-campaign.service`. That refuses until `check-drained.py` exits 0, then the printed `ln -sfn` and both restarts run at once. The symlink no longer moves before the drain.
  - `unbug install`, the `campaign-request.json` and `resume_case.py` updates, and launches all move to step 5, after step 4 is verified.
- **N2.** Step 3 reads the loaded unit with `systemctl show -p ExecStart --value`. Step 4 verifies `readlink -f source-current` and the router's `/proc/<MainPID>/cmdline` before anything resumes.
- **N3.** The fallback says "as well as `source-current`", and says to name both checkouts in the rollback.
- **N4.** Rollout runbook step 3 is marked superseded for the VM. The "where the router runs" note now names `control/unbug-model-router.service` as stale too.
- **N5.** Both are still open. The founder confirmation goes in the hand-back report, and the Murphy rows stay in the design until the register is on `main`.

**Also found while waiting (not from the review):** the full suite at 5ba15c89 failed two tests that pinned the old DeepSeek chain.
- `test_free_routes.py`: the DeepSeek route order now includes the Neuralwatt lane, and the walled-role exclusion list now includes it. That is the wall doing its job: Neuralwatt is ungated, so walled roles exclude it.
- `test_model_runtime.py`: the OpenRouter execution test now drops `neuralwatt-key` as well as the Go accounts, so it still exercises the OpenRouter path.
