# Provision model containment before worker startup

O7 made non-isolated model calls require UNBUG_MODEL_CGROUP_ROOT, but the worker
launch path never provisions it. Missing delegation therefore refuses every such
call. This small follow-up supplies the missing setup; it does not weaken O7 or
claim live CLI/isolated-UID acceptance. Parent requested a short note and one
diff review, without another design-review cycle. Baseline land13 7dbdc58.

Use the existing runner_supervisor entry shared by fresh and same-worker resume
launches. Before any runner subprocess, call processes.prepare_model_containment.
On Linux, a privileged helper mode in the already shipped bin/processes.py creates
/sys/fs/cgroup/unbug-models-<uid> and its runner leaf. Verify cgroup-v2 controls,
delegate the directory and cgroup.procs/subtree_control/threads to the runner UID
and GID, and move the supervisor PID into the runner leaf. This gives the
unprivileged shim migration permission at its common ancestor. No controllers or
host-wide subtree settings need enabling for cgroup.kill. No tree is swept or
removed: per-ledger leftovers retain O7's restart-refusal authority.

Root workers call the same helper directly. Other workers invoke it using the
existing passwordless sudo dependency, sudo -n and isolated Python startup, with
a bounded timeout and no retained stdout/stderr. The helper validates numeric
identity and the target process UID before moving it. It accepts no arbitrary
filesystem path. This is ordinary provisioning under the existing worker trust
model, not a new privilege boundary against same-UID hostile code.

Export the deterministic root in the supervisor environment. Before run.py starts,
construct a real ContainedCall using a separate startup-probe ledger path under
sealed, launch harmless isolated Python, and kill/drain it. This exercises mkdir,
kill and enrollment as the runner user. Failure produces runner-status.json with
phase startup, reason containment_unavailable, exit 78, attempt 0, plus only that
fixed label on stderr. Do not retry or start the runner. Successful starts inherit
UNBUG_MODEL_CGROUP_ROOT through the supervisor's existing explicit environment.

No launch.sh duplication, bake-image requirement, opt-out, cgroup reset or fallback.
Both processes.py and runner_supervisor.py are already bound in worker upload and
frozen-runtime verification. No run.py edit collides with B's startup repair.

Exams: reproduce the existing absent-root refusal; a supervisor wiring regression
fails before this change and checks prepare-before-runner plus environment; startup
provisioning/probe refusal starts no runner and writes only the fixed label. Local
network-disabled privileged Docker with private cgroup namespace runs real-kernel
provisioning, contained execution and delegation to a nonroot UID. Synthetic Mac
supervisor/launch fixtures explicitly replace only their cgroup provisioning edge;
they are not cgroup evidence. The full worker-command exam checks the child start
environment too. Run focused tests, real kernel tests, then plain
`lockf /tmp/unbug-suite.lock uv run --with numpy --with scipy python -B tests/run.py`.
One fresh Claude diff review and immediate handback. No live action or paid call;
no Murphy row closure. Estimated one small offline increment plus suite/review wait.
