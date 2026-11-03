# Escaped-session containment (O7)

## Problem and impact

`budget.run_budgeted` kills a process group. A double-forked setsid descendant
can outlive that group and modify the next invocation’s work. An ancestry scan
cannot recover ownership after reparenting. This blocks the approved three-case
pilot. Murphy `new-isolation-settlement-1` is the specific row to close.

## Change

For every `ModelRuntime` invocation with `user=None`, require a fresh Linux
cgroup v2 below an explicitly configured delegated `UNBUG_MODEL_CGROUP_ROOT`.
No process-group fallback: missing delegation, missing cgroup.kill, unsupported
platform, or failed enrollment prevents the command from executing. Isolated UID
calls retain their current cleanup and are not qualified here. Containment is on
by default; synthetic emitters explicitly opt out in tests. The option is not a
CLI/environment opt-out.

Put the small containment owner in bin/processes.py (already released). A private
per-invocation directory owns membership independently of sessions and parentage.
Popen runs a tiny exec entry point in processes.py, with an inherited anonymous
pipe read descriptor; it blocks before executing the CLI. The owner writes that
PID to cgroup.procs, then sends the admission byte. EOF, enrollment failure or
parent death before admission means exit without executing the command. Close all
unneeded pipe ends and descriptors. Do not use preexec_fn in the threaded runner.

On success, cancellation, timeout, accounting failure and exception, write 1 to
cgroup.kill and wait until cgroup.events reports populated 0 before deleting the
cgroup and allowing invocation cleanup/settlement to finish. This replaces group
cleanup for the contained call; it does not supplement ancestry polling. Keep a
bounded cleanup wait (five seconds, matching current budget cleanup); a failure
raises cancellation_failed and durably records cleanup_errors, never success.
A failed cgroup remains retained for diagnosis; later dispatch in any process
must refuse after containment cleanup failure. No inferred
process death, deleted work, retry or reusable containment directory on failure.
The group-kill boundary includes nested cgroups. Concurrent calls get separate
random directories and cannot cancel each other.

The delegated root is runner-owned deployment configuration, not model input.
This addresses descendants using setsid/setpgid/double-fork, not same-UID tool descendants deliberately migrating tasks through writable
cgroupfs or remote daemon-owned workloads. The pilot must provision delegation before any model
call; no provisioning or cloud/live worker action belongs to this change. Missing
support on macOS refuses non-isolated CLI dispatch. Existing synthetic runtime
tests may replace only containment enrollment; they cannot qualify O7.

## Deletions and scope

Delete reliance on process-group ownership for non-isolated ModelRuntime calls.
Do not change factory/run.py, diagnosis, holder paths, isolated-UID cleanup,
science gates, budgets, or activation flags. Add no alternate launch or accounting
path. The cgroup helper receives argv only for execution and never logs it or
environment values. Existing launch manifest already carries processes.py.

## Tests and acceptance

Add tests/factory/test_escaped_session_containment.py. Offline Linux real-process
tests require real writable cgroup v2 and never mock membership/kill/population.
Launch a synthetic executable through real run_budgeted with containment enabled;
its child double-forks, setsid, ignores SIGTERM, closes inherited stdout, and
writes heartbeat plus a delayed contamination marker. Synchronize readiness
before cancellation. Assert CLI reaped, escaped process no longer running,
heartbeat stopped, cgroup empty/deleted, and no late write while a subsequent
invocation uses the same work directory. Cover cancellation, timeout, ordinary
CLI exit with lingering descendants, concurrent invocation separation, and
startup/enrollment refusal before a sentinel command executes. Test cleanup
failure prevents the next dispatch. Each test has independent finally cleanup
using its private cgroup, so removing production containment cannot leak children.
A negative-control run removing cgroup.kill must fail the descendant-death test.

Run real containment tests inside a local disposable Linux Docker container with
writable private cgroup v2, if available; no cloud workers or model calls. macOS
runs platform/delegation refusal and wiring tests and explicitly skips kernel
containment tests. If real kernel tests cannot run, the row stays OPEN and O7 is
not claimed complete. Save exact test commands/results and negative-control
evidence. Full suite exactly under the shared lock:
`lockf -t 7000 /tmp/unbug-suite.lock uv run --with numpy --with scipy python -B tests/run.py`.
Timing-only failures get a standalone rerun, retaining both results without
weakening limits. Close only new-isolation-settlement-1 after real kernel tests
and fresh diff review pass. Live isolated-UID and actual model CLI cancellation
acceptance remain explicitly required.

## Cost, risks and review

One offline implementation/review increment; no paid calls, live actions, pushes
or merges. Kernel/cgroup delegation availability is a deployment prerequisite;
refusal is intentional on an unsupported host. Other main risk is accidental
admission before enrollment, covered by the sentinel and negative controls.
Fresh design review uses zoom_out, design_critic, implementation_readiness; fresh
diff review uses zoom_out and implementation_readiness. At most two rounds each.

## Round-1 resolution (authoritative where it refines the above)

Accept B1/B2 and M1–M6; no finding is rejected. Timeline: one to two working
days including offline kernel tests, full suite and reviews.

Ownership is scoped by SHA-256 of the canonical absolute ledger path, under the
configured root. That path is stable for a case resumed into the same work
directory. A new host cannot retain the old host's processes; changing the
ledger path on the same host is not a supported cleanup/recovery operation.
Different cases have separate scopes; no root-wide sweep ever runs. Ownership
uses per-call locks as specified in the parent decision below. Retained processes
require explicit recovery and cannot silently coexist with a resumed call.
Empty scope directories are harmless. Cleanup errors reach both ledger and card;
resetting a budget never overrides containment refusal.

The public run_budgeted containment keyword defaults ON. Only isolated-UID
runtime calls explicitly disable it (their existing UID sweep still applies).
Synthetic budget tests explicitly disable containment; kernel tests explicitly
exercise it. No configuration switch can disable containment in ModelRuntime's
user=None path. The helper takes the delegated root from the runner's os.environ,
never the gate-filtered CLI env, and the scope from ledger_path, not CLI arguments.

Raise `BudgetError('containment_unavailable')` for all pre-admission failures,
never `process_error`; reap a blocked shim and clean its group if needed before
returning. Invoke on_started only after enrollment and successful admission-byte
write. Factory reservation handling therefore retains started=False on refusal,
giving the existing denied outcome. For contained calls stop_process uses only
cgroup kill/drain, without the sudo fallback. Call it before the success ledger
transaction and at the start of the exception handler, before ledger active
removal/terminal settlement. Preserve conservative usage handling; a cleanup
failure is recorded and overrides the error with cancellation_failed. The final
cleanup remains idempotent and must never convert a failed containment into
success. Runtime card propagation applies to both containment error labels.

After populated 0, remove nested cgroup directories bottom-up and finally the
per-call directory, inside the same five-second cleanup bound. A real nested
child-cgroup test verifies this. Migration requires delegated common-ancestor
cgroup.procs permission; provision the runner in a leaf of the delegated subtree
where necessary, with appropriate filesystem ownership. Docker root tests prove
the kernel mechanism, not the live nonroot delegation setup.

The residual is specifically SAME-UID DELIBERATE CGROUP MIGRATION by model tool
descendants, not just an administrator. It is outside this setsid/double-fork fix
and must be explicit in the Murphy closure text; this is not an adversarial
sandbox. Isolated UID boundaries remain the intended protection for untrusted
roles. Daemon-mediated remote processes are likewise outside the local tree.
Local macOS non-isolated model/smoke calls now refuse; pure synthetic emitter
tests and isolated calls retain their explicitly selected test/UID paths.

Kernel cleanup-failure testing uses a delegated nonroot UID: after real admission,
the root test harness revokes that UID's write permission on the call's
cgroup.kill. The real owner must fail cleanup, refuse another call, exit, and a
fresh owner must also refuse before its sentinel runs. The harness restores
permission and performs cgroup.kill in finally. This intentionally uses root only
to induce/recover the real permission failure, never mocks kill or population.
The crash test SIGKILLs an owning process after its double-fork child is ready;
a new process must refuse before the sentinel executes. Finally the harness
kills/drains only the test scope. Concurrent-case and same-case thread tests
prove an unrelated live invocation is not cancelled. The negative control is a
temporary local source-copy edit replacing only the production cgroup.kill write
with a no-op; no runtime flag or committed bypass. Record patch and failing test.

Local feasibility probe succeeded: Docker python:3.12-slim with --network none,
--privileged and --cgroupns private can create a real v2 cgroup with cgroup.kill
and cgroup.events. No cloud worker or model call was involved.


## Parent-approved after round 2

The parent resolved B3 with option (a); there is no design review round 3.
Each call locks its cgroup directory with flock for the entire call. A short
scope mutex (`<ledger>.containment.lock`) serializes checks, directory creation
plus lock acquisition, and directory removal; it is never held during execution.
A leftover is a call directory whose lock can be acquired. Live calls in other
processes are allowed. On cleanup failure create a `.poisoned` child directory
as a durable marker; all processes refuse while it exists. Release the failed
call's ownership lock so the directory is also detectable as a leftover if
marker creation fails. Keep that directory until explicit recovery. Forks occur
only with no call live: extension_evaluator.start_child already waits for one
thread and no active_model_calls. Test a parent call, then a successful forked
child call on the same ledger, then a child-created leftover found by the parent.

M7 option (i): every run_budgeted entry, including isolated-UID calls, and
resume_ledger checks leftovers whenever UNBUG_MODEL_CGROUP_ROOT is configured.
Do not clear ledger stop state before that check. Contained entry still requires
the root; missing configuration is not permission to launch a non-isolated CLI.

M8: the admission shim argv is `[sys.executable, '-I', absolute_processes_path,
read_fd, '--', *cmd]`, with pass_fds=(read_fd,), close_fds=True and
start_new_session=True. Isolated Python prevents cwd/PYTHONPATH/site-user hooks
running before enrollment. The shim closes the pipe and execvpe's the command
with its inherited CLI environment only after the admission byte.

M9: recovery is manual and scope-only, with all case activity stopped: write 1
to cgroup.kill in each retained call, wait for populated 0, remove directories
bottom-up, and record the recovery in the case card. Never remove populated
state, sweep siblings, or rename the ledger to evade refusal. No recovery tool
is built in this increment.

N4: stale default-off and process-only refusal wording has been removed. N5:
runtime card entries are {'stage': 'model_containment', 'error': label}, for
containment_unavailable or cancellation_failed. These labels hard-stop routing.
The parent authorizes implementation and at most two fresh diff review rounds.

Implementation clarification: containment uses the same `if user` predicate as
UID setup and cleanup. An empty user string therefore stays contained; only a
truthy isolated-user selection takes the UID path. This closes an accidental
empty-string bypass, without changing the isolated-UID acceptance scope.
