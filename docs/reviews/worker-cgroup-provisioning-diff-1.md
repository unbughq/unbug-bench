**Verdict: BLOCKED.** Two blocking findings, both outside the four files the brief scoped. I read the design (`docs/designs/worker-cgroup-provisioning.md`), the report, the evidence and logs, and the code diff `89934c9..HEAD`. I also read the files that start or watch the supervisor: `factory/launch.sh`, `bin/boat-launch-guards.sh`, `factory/collect.sh`, `factory/account_handoff.py` and `factory/resume-in-place.sh`. Nothing was run and nothing was edited. Personas: `zoom_out`, `implementation_readiness`. Mode: REVIEW, round 1 of 1.

---

## Goldfish diff review: worker-cgroup-provisioning, diff round 1

### Blocker 1: the control side drops the new startup failure

- **Severity:** Blocker
- **Scope:** `factory/runner_supervisor.py:43-48`, which now writes a status the existing readers don't accept. The readers are:
  - `factory/launch.sh:471` (the `probe_python` helper);
  - `bin/boat-launch-guards.sh:252` (the wait loop that reads its reply);
  - `factory/collect.sh:25-41` (the status validator).
- **What goes wrong:**
  - On failure the supervisor writes `{attempt: 0, phase: 'startup', reason: 'containment_unavailable', exit_status: 78}`.
  - The launch probe prints `STARTUP_FAILED` only when `reason == 'startup_failed'` or `phase in ('finished', 'stopped')`. This status matches neither, so the probe falls through to the idle-time check.
  - `guard_wait` therefore treats the VM as a healthy running case. It only notices after `BOAT_STALL_MINUTES` (default 45) or the TTL margin, and then reports it as "STALLED", which is the wrong class.
  - When the case is retired, `collect.sh` rejects the file: it requires `1 <= attempt <= 3` and a `reason` from a fixed list that has no `containment_unavailable`. It exits 1 and deletes the temporary copy, so the label never reaches the control side.
  - The supervisor's stderr goes to `/dev/null` in production (`launch.sh:637` and `:785`, `2>/dev/null`). So the status file was the only record, and it is lost.
- **Effect:** on the worker, the failure does stop before `run.py`, so no runner starts and no model is admitted. But the batch sees a misclassified ~45-minute stall instead of the fixed label. That defeats the reason for this change and works against target property §3 ("an infrastructure failure is retried … never counted").
- **Fix (elephant's choice):** have the launch probe treat `reason == 'containment_unavailable'` as a startup failure, and add attempt 0 and that reason to the `collect.sh` allowlist. Add one test in `tests/bench/test-launch-guards.py`, next to the existing `startup_failed` fixture at line 93, that drives this exact status through both the probe and collection. The alternative is to reuse the existing `startup_failed` path, but the brief fixes the label, so widening the readers is the smaller change.

### Blocker 2: one same-worker resume path never goes through the supervisor

- **Severity:** Blocker
- **Scope:** design paragraph 2 ("Use the existing runner_supervisor entry shared by fresh and same-worker resume launches"), and `factory/account_handoff.py:234`.
- **What goes wrong:**
  - Fresh launch (`launch.sh:785`) and auto-resume (`launch.sh:637`) do use `runner_supervisor.py`.
  - In-place resume does not. `factory/resume-in-place.sh:47` calls `account_handoff.py resume-worker`, and `worker_resume` starts `python3 ~/factory/run.py --resume …` directly with `subprocess.Popen`.
  - That path is still used: by account handoff `apply` (`account_handoff.py:210`), by `bin/factory-adopt:48`, and by parked VMs (`bin/hcloud-park`).
  - On it, `UNBUG_MODEL_CGROUP_ROOT` is never set. So every non-isolated model call after a handoff or adopt resume still fails with `containment_unavailable`, which is the original absent-root bug.
  - The process check in `resume-in-place.sh:48` already matches `runner_supervisor`, so wrapping the start fits the existing script.
- **Fix:** route `worker_resume` through `runner_supervisor.py`, giving it `FACTORY_RUNNER_SECONDS` and a grace value the same way `launch.sh:637` does. That keeps one launch path (§4). Alternatively, have the parent explicitly take this path out of scope, and correct the design and report sentence that claims fresh and resume launches share the supervisor.

### Checks that pass

- **Order and environment:** `prepare_model_containment` runs before any `Popen`. On success it sets `os.environ`, and the child receives it through `env={**os.environ, …}`. Both the kernel test (`/sys/fs/cgroup/unbug-models-0` is passed to the runner) and the full worker-command exam (`runner-cgroup-environment`) show this. The negative control against the original supervisor fails for the right reason (zero calls).
- **Delegation and common ancestor:** the supervisor moves into `unbug-models-<uid>/runner`, and `ContainedCall` scopes are made at `unbug-models-<uid>/<hash>/<uuid>`. The common ancestor is `unbug-models-<uid>`, whose `cgroup.procs` is handed to the runner UID. Write access there is what the unprivileged shim needs to move itself. The root has no processes of its own and no controllers are enabled, so the no-internal-process rule is not a problem. `test_real_delegation_allows_nonroot_membership_and_kill` shows that a UID-1000 process can enroll and be killed after the root helper moves it.
- **Helper input checks:** the helper accepts only integers and checks the Uid line in `/proc/<pid>/status`. It takes no path argument, rejects symlinks, and requires `cgroup.kill`. The shim's own `__main__` dispatch can't be confused with the helper flag, because the shim's `argv[1]` is always a file-descriptor number. `sudo -n`, `-I`, the 10-second timeout and DEVNULL output are all unit-tested, and the error is collapsed to the fixed label.
- **O7 unchanged:** the diff leaves `_containment_scope`, `_check_calls`, `ContainedCall` and `check_containment` alone. Nothing is swept or deleted, so leftovers in a ledger's scope still block a restart. A leftover from a failed probe also fails closed on the next start, which is correct. No limits changed.
- **Evidence:** it matches the report. The kernel tests pass 6/6. The final suite is 185 scripts with 0 failures: 184 passes reused from identical code, plus one rerun of `test_batch_launch.py`, which passed 8/8 on its own. The first unlocked run's credential-metadata failure is kept, and no timing-only cause is claimed for it. No Murphy row is closed, and live VM, actual-CLI and isolated-UID acceptance are correctly left unqualified.
- **Simplicity (zoom-out):** it reuses `processes.py`, the supervisor and the existing sudo dependency, and adds no new module, option or fallback. That is the right size of change.
- **Test fixtures:** replacing the provisioning call in the Mac transport fixtures is scoped and labelled as not being cgroup evidence. That is acceptable.

### Nits (optional)

1. The docstring at `tests/factory/test_worker_cgroup.py:1` says "synthetic preparation edge", but the file also contains the real-kernel tests.
2. `KernelTests` is gated on `O7_TEST_CGROUP_ROOT` but never reads its value; the tests use `/sys/fs/cgroup` directly. A boolean name would be clearer, for example `O7_TEST_DISPOSABLE_CGROUP=1`.
3. `test_failed_provisioning_never_starts_runner` doesn't check that stderr is exactly the fixed label, although the design requires that.
4. In `probe_model_containment`, if `call.stop()` raises inside `finally`, the `child.wait` after it is skipped. This leaves at most a short-lived zombie and is harmless.
5. `delegate_model_cgroup` also hands over `cgroup.subtree_control`, which nothing needs while no controllers are enabled. It's harmless, but the delegation could be narrower.

**Result: BLOCKED.** Blocker 1 (the launch probe and `collect.sh` drop the startup status) and Blocker 2 (in-place resume starts `run.py` without the supervisor) must be fixed, or the second goldfish rejects them, before this merges.

---

Elephant resolution: both blockers accepted. The launch probe now classifies
containment_unavailable as STARTUP_FAILED; collection permits the exact attempt-0
startup/containment_unavailable/78 tuple. The authored launch-guard regression
checks prompt failure and the retained control-side receipt. worker_resume now
wraps run.py with the shared supervisor, with explicit normal duration/grace
defaults and preserved arguments/environment. The loader regression pins this
route. No blocker is rejected. This records implementation fixes, not a reviewer
PASS verdict.
