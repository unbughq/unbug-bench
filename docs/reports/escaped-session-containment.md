# O7 offline containment evidence

Branch: t3/isolation-o7, based on ff31d87542e404cdcbf16740e4baa10c603b4b88.
Design rounds 1/2 and the parent-approved resolution are retained under the
escaped-session-containment topic. No third design review was requested.

The implementation requires a delegated Linux cgroup-v2 root for non-isolated
ModelRuntime calls. A pipe-gated isolated-Python shim enters its own cgroup before
exec. Cleanup kills the cgroup and verifies populated=0 before ledger completion.
Per-call directory flocks allow the existing same-ledger fork child. Unlocked
leftovers and poison markers refuse dispatch/resume, including isolated calls.
No process-group fallback is available to non-isolated ModelRuntime calls.

## Real kernel tests

Local Docker Desktop Linux, existing python:3.12-slim image, network disabled,
private cgroup namespace and privileged disposable container. No cloud worker,
provider/model invocation, credential or paid call was used. Command:

```
docker run --rm --network none --privileged --cgroupns private \
  -v "$PWD:/repo:ro" -w /repo -e O7_TEST_CGROUP_ROOT=/sys/fs/cgroup \
  python:3.12-slim python -B -W ignore::ResourceWarning \
  tests/factory/test_escaped_session_containment.py
```

Fourteen tests pass, including eleven real Linux cases and three refusal/wiring
checks. The Linux cases cover double-fork/setsid/SIGTERM-immune descendant death
on cancellation and timeout; ordinary exit with a nested child cgroup; no later
heartbeat/contamination writes during a subsequent call; cleanup before the
success ledger transaction; separate concurrent cases and same-ledger threads;
parent then forked-child calls on one ledger, followed by leftover refusal;
SIGKILL of an owner followed by refusal in a fresh process; isolated Python
startup; and real nonroot EACCES on enrollment and cleanup. The permission tests
revoke actual cgroup control-file permission after readiness, then restore it
for independent test cleanup. Kill/procs/events are never mocked in these tests.

The host macOS run passes three checks and explicitly skips eleven kernel tests.
It is not the cgroup evidence. Existing synthetic budget/TLS tests explicitly
disable containment at their emitter boundary; their scope remains unchanged.
The production runtime always passes containment=True when user is None.

Initial kernel development found reused synthetic event IDs (missing_usage on
the second call); the emitter now assigns each invocation a unique session ID.
No production limit was changed. A standalone case-budget run without BENCH
failed two subprocess import checks; rerunning with the BENCH supplied by the
suite passed all 33 tests. Runtime, maxima, budget, resume and stream-D runtime
focused scripts also pass.

## Negative control

In a disposable /tmp copy INSIDE the same local container, replace precisely
`(self.path / 'cgroup.kill').write_text('1')` in bin/processes.py with a no-op.
Run KernelTests.test_cancel_double_fork_before_settlement. It fails because the
real cgroup stays populated, producing cancellation_failed rather than cancelled.
The test's independent finally cleanup writes the kernel kill and drains the
test subtree. No production runtime bypass flag was introduced. The recorded
negative log shows the mutation and expected failing assertion.

## Full suite and review

The exact suite command is queued under the shared lock:

```
lockf -t 7000 /tmp/unbug-suite.lock uv run --with numpy --with scipy python -B tests/run.py
```

Final result and diff review will be recorded here before handback. Logs use the
escaped-session-containment prefix; their hashes/source hashes are in the final
evidence JSON. The suite waited for other agents and did not run concurrently
outside the lock. No timing limit was weakened.

## Remaining live requirements and recovery

This closes only new-isolation-settlement-1's local setsid/double-fork gap,
subject to the fresh diff review. Same-UID deliberate cgroup migration and
daemon-mediated/remote work are excluded, explicitly in the register. This is
not an adversarial sandbox. Actual model-CLI cancellation and isolated-UID
acceptance are still LIVE requirements. No pilot was launched or certified.

Deployment must provision UNBUG_MODEL_CGROUP_ROOT with v2 cgroup.kill, appropriate
delegation/common-ancestor permissions and a stable ledger path. This increment
does not provision a live VM. Missing support (including local macOS dispatch)
refuses before the CLI executes. A restart never automatically sweeps siblings.
For a refused case, stop its activity, kill each retained call in its scope,
wait for populated=0, rmdir bottom-up, and record recovery in the case card.
No recovery tool, activation flag, cloud lifecycle change, push or merge is part
of this increment.
