# O7 escaped-session containment: fresh goldfish diff review, round 1 of 2

**Verdict: PASS. There are no blockers. Closing Murphy row `new-isolation-settlement-1` is justified in its narrow wording.**

**Scope:** I reviewed `ff31d87..HEAD` (`1ff485f`) against `docs/designs/escaped-session-containment.md`, including the "Parent-approved after round 2" section (B3 per-call flocks, M7–M9, N4, N5, and the `if user` clarification). I read `bin/processes.py`, `factory/budget.py`, `factory/model_runtime.py`, the new and changed tests, the report, the evidence JSON and the kernel and negative-control logs.

**Offline checks I ran:**
- All 30 sha256 values in the evidence JSON (17 source/test files, 13 logs) match the working tree.
- `git diff 29cad10..HEAD` touches only `docs/`, so the tested source is the reviewed source.
- `model_runtime.py:663` is the only production caller of `run_budgeted`. No caller is left on the default path.
- `extension_evaluator.py:401` already waits for one thread and no `active_model_calls` before its fork, as the design says.

## Checks against the design

1. **Scoped ownership.** Each ledger gets its own scope, named by the SHA-256 of its resolved path. A short scope mutex (`<ledger>.containment.lock`) covers the leftover check, mkdir plus flock, removal, and poisoning; it is never held during execution. Each call holds its directory flock for the whole call. A leftover is a directory whose lock can be acquired. Live calls in the same process, other processes or other threads fail `LOCK_NB` and are skipped. Locks are per open file, so threads in one process exclude each other correctly. Nothing sweeps the whole root. This is correct.

2. **Fork behaviour.** Lock and pipe file descriptors are non-inheritable (PEP 446), so neither the model CLI nor other `Popen` calls inherit them. A forked child on the same ledger works (parent call, then child call, then a child-created leftover the parent refuses on). The "fork only while idle" precondition is enforced by the existing quiescence wait.

3. **Enrollment before exec.**
   - The shim argv matches M8: `-I` with `pass_fds=(read_fd,)`, `close_fds=True` and `start_new_session=True`.
   - The write end is never in the child, so EOF from a dead parent exits 125 without exec.
   - The admission byte is sent only after the `cgroup.procs` write succeeds.
   - `on_started` runs only after `launch` returns, so a refusal keeps `started=False` and gives the denied outcome.
   - The `cgroup.kill` probe runs while the cgroup is still empty.
   - The `-I` claim is backed by a hostile-PYTHONPATH test.

4. **No unsafe fallback.** With `containment=True`, a missing root, non-Linux, a non-cgroupfs directory, missing control files or any OSError all raise `containment_unavailable`. That error is converted to `BudgetError` both at entry and in the handler. Neither label maps to a router failure reason, so both re-raise and hard-stop routing. Runtime passes `containment=not user`, the same predicate as UID setup, which closes the empty-string bypass. An AST test pins this. Only test emitters opt out, and those diffs are mechanical.

5. **Kill and drain before settlement.**
   - On success, `stop_process()` runs before the success transaction, and a test observes an empty leaf and a dead escaped process at the moment `terminal_stop='complete'` is saved.
   - On any exception, contained cleanup runs first in the handler, before the usage drain and active/terminal settlement.
   - A failure records `cleanup_errors`, marks usage unknown (`cancellation-failed:` start) and replaces the error with `cancellation_failed`.
   - The `finally` re-call is idempotent and cannot turn a failure into success: `stop()` re-raises when `failed` is set.
   - Bottom-up rmdir runs inside the same five-second bound, and the nested-cgroup case is tested.

6. **Poison and restart refusal.** On cleanup failure, `.poisoned` is created under the mutex and the lock is then released, so an unlocked directory still refuses even if marker creation fails. M7 is met: `run_budgeted` entry (isolated calls included), the in-`try` re-check after lock waits, and `resume_ledger` (before and after the lock, before any stop-state clearing) all refuse whenever the root is configured. Real tests cover:
   - an owner that is SIGKILLed;
   - a fresh process after a real nonroot EACCES on `cgroup.kill`;
   - an isolated call (`containment=False`) on a poisoned scope.

7. **Same-UID migration exclusion.** The register's closure text names deliberate same-UID cgroup migration and daemon-mediated work as excluded. It also keeps live isolated-UID and actual-CLI cancellation as required. That is precise and matches the design residual.

8. **Evidence.**
   - Kernel log: 14 tests OK in 5.2s.
   - Negative-control log: `cancelled` does not match `cancellation_failed`, so the test fails as intended.
   - Full suite: the report is honest. It does not claim an exit-zero full run, and every attempt is retained:
     - first run: 1 failure, the router adapter, not timing; fixed and rerun 42/42;
     - second attempt: a uv DNS failure before any test ran;
     - final run: 1 control-resume readiness failure;
     - an unlocked control-resume rerun also failed;
     - the locked single-file rerun passed 24/24 (113.585s);
     - the first full run had already passed that file on the same production code.

   No limit was weakened. This follows the user's timing-only rerun rule.

## Findings (none blocking)

- **Nit — `bin/processes.py`, `ContainedCall.__init__`.** If the `cgroup.kill` probe, `os.open` or `flock` fails after `mkdir`, the empty, never-admitted directory stays behind unlocked. Every later call, isolated calls and resume on that ledger then refuse until manual M9 recovery, even after the misconfiguration is fixed. This fails closed, so it is safe. But it is inconsistent with the missing-control-files branch, which does `rmdir`, and this path has no test. Removing the provably empty directory under the same mutex would be cheaper for operators. It is acceptable as is.

- **Nit — shim startup.** `-I` blocks env, cwd and user-site hooks. It does not stop the interpreter's own `site-packages` `.pth` processing (that needs `-S`). This only matters for a same-UID writer of the runner's venv, which is inside the declared non-adversarial exclusion. `-S` would be a one-flag hardening if wanted.

- **Nit — exec failure semantics.** A missing CLI binary now fails inside the shim (traceback to the transcript, exit 1). That becomes `process_error`, which routes as an outage and excludes the route per call. Before, `Popen` raised `FileNotFoundError` in the parent. `pinned_cli` normally catches this earlier, so the impact is negligible.

- **Nit — double `cleanup_errors` entry.** After a contained failure, the `finally` `stop_process()` appends a second entry (`BudgetError`) after the `cancellation_failed` one. It is harmless and does not override the error.

- **Nit — sequencing.** The register row already reads `closed` at HEAD, before this review. The report says the closure is subject to this review, so passing it makes the row consistent. The closure text could also state that live delegation provisioning (`UNBUG_MODEL_CGROUP_ROOT` with common-ancestor permissions) is unqualified. The report says so; the register does not.

## Is the narrow Murphy closure justified?

**Yes.** The row's mitigation ("qualify a cleanup mechanism or containment for non-isolated CLI descendants") is met by:
- real kernel tests showing setsid, double-fork and SIGTERM-immune descendants die on cancellation, timeout and ordinary exit;
- no later contamination;
- crash and poison refusal;
- a failing negative control.

The scope is correctly limited. These stay explicitly unqualified, and no pilot was launched:
- live isolated-UID acceptance;
- actual model-CLI cancellation;
- deployment delegation;
- same-UID deliberate migration;
- daemon-mediated work.

**Round 1 result: PASS.** No round 2 is required unless the parent chooses to act on the Nits.

## Implementer response

PASS accepted. No blocking findings were raised or rejected. Optional nits are retained as follow-ups; no executable code or test limits changed after review. The parent requested immediate handback on a passing diff review. Murphy new-isolation-settlement-1 closes only in the reviewed narrow scope; live isolated-UID, actual-CLI cancellation and deployment delegation remain unqualified.

