**Verdict: FAIL.** I found one blocking finding. It has a one-line fix, and after it lands a goldfish re-check of that hunk is enough.

### Blocking: the host launcher runs unpinned code
- **Where:** `factory/job_config.py:15`, `from budget import BudgetError` at the top of the module.
- **What goes wrong:** `launch.sh` runs `job_config.py check` on the host before it creates a VM. That top-level import loads and runs `factory/budget.py` in the trusted launcher. `budget.py` is not in `launch_manifest.TRUSTED_FILES`, which means it is also missing from `HOST_FILES`. So neither the holder's policy fingerprint nor `batch.verify`'s host-file check covers it. Someone could edit `budget.py` on the host and it would run inside the launch path without changing the approved `code_sha256`.
- **Scope:** I checked every local import in the pinned host modules (`key_holder`, `batch`, `batch_money`, `job_config`, `control_resume`). This is the only one that is not pinned. `job_authority` is also unpinned, but it is imported inside `install`, which only runs on the worker, so it is fine.
- **Minimal fix:** move `from budget import BudgetError` to the first line of `install()`. Only that worker-side function uses it, so the host-side `check`/`deliver` path no longer touches `budget.py`. Pinning `budget.py` would also close the gap, but it would pull worker accounting code into the holder fingerprint for no benefit. Optionally, add one small assertion that the local imports of `TRUSTED_FILES` modules form a closed set.

### Checked against the addendum and interfaces §8, no finding
- **Manifest trust chain:**
  - On the host, `batch.verify` checks the release and its host files. The manifest bytes are checked against `manifest_sha256` and against the release's `source-manifest.json`. The policy's `jobs` and `max_concurrency` must exactly equal the manifest's, and the restore recipient must match.
  - On the worker, the chain is `batch-release.json` (the SHA from the argument), then `worker-release-manifest.json`, then the hash of `factory/batches/<id>.json`, then the recipient. `WORKER_GLOBS` and `WORKER_CONFIG` now include those files.
- **Config, case and UID checks:**
  - The holder writes a content-addressed, mode-0600 config after `attest_launch` and before `consumed`.
  - Before creating a VM, `launch.sh` checks that the config's case equals `--case-id`, its generation equals `--checkpoint-sha256` (null when there is none), and its release equals `--batch-sha256`. The read uses no-follow, owner and 0600 checks.
  - RAM delivery is atomic with an fsync and happens after `push-secrets` wipes the directory. Account handoff uses `--merge`, so the file survives. An in-place restart reuses the same argv, and its RAM file is still present.
  - In `run.py`, `install` runs after `authenticate_gates` and after `c.work` exists, and before `raised_limits` and any model work.
- **Checkpoint revision and crash handling:**
  - A same revision must be byte-equal. A changed revision must be exactly old+1 with an amount that does not decrease. Owner, case, reservation and deadline must not change.
  - The history file is written first, then `job-money.json`. A crash between the two writes is repaired by replaying the same transition. A different transition under the same key refuses.
  - A missing `job-money.json` on resume refuses. So does any non-null source or an existing file on a fresh job. A `retired_batch_bound` on the current card or the checkpoint card refuses.
- **Budget duplicate, resume and rollback risks:**
  - The total is the sum of max(committed, collected) under `flock`. `money.json` is authoritative and written before the projections and configs. Same-job, same-source replay returns the stored authority and produces byte-identical config bytes.
  - Every source change refuses, and nothing invents a proof type.
  - When a launch fails after funding, the grant is kept by design, and `consumed` blocks a relaunch.
- **Legacy paths:**
  - Non-batch launches with config flags refuse. Without them, `install` is never called.
  - The `max_cost` checks only stop applying for jobs that went through `bind` (`_batch_job`). The historical `--max-cost` is stripped from args, with its value validated.
  - The VM restore recipient is added only for batch jobs, so `case_recipient` is unchanged for non-batch.
- **Tests:** The integration test openly authors the revision-2 grant in place of 2b. `--consumer-root` is used only for cross-branch qualification, and the normal merged run does not skip.

### Later work, not blocking this increment
- **Attempt limit for batch jobs:** `key_holder.admit_attempt` now returns `None` for `_batch_job`, which removes the legacy 3-attempt cohort limit before increment 3's per-case relaunch accounting exists. It cannot be reached today because `authorize` refuses every source change. The 2b/3 addendum must name the bound that replaces it before source advancement is enabled.
- **Config directory symlinks:** `batch_money.configuration` checks for a symlink on the config file but not on the `configs/` directory. That directory lives in the trusted control home, so this is a nit only.
- **Still open:** 2b store/journal/outbox, 3 scoped restore/async, 4 Codex/status and 5 the real practice end-to-end run, as you listed.

I saved no files and made no edits.


## Elephant response

Blocking host trust-closure finding fixed: BudgetError import is now inside
worker-only install(), not host check/deliver. Added a fresh-process regression
asserting import job_config loads neither budget nor job_authority. No need to
expand the holder fingerprint to worker accounting. No findings rejected.
Later source advancement remains gated on the reviewed per-reason relaunch
backstops and collection/retirement proof; no new source grant is enabled.
