# Worker containment provisioning

Original baseline: `7dbdc58`. Provisioning source: `c9d7cd2` on
`t3/isolation-provisioning`. Parent-directed merge of `parallel-tests` at
`89934c9` produced tested head `300c1a7`. The provisioning diff for review is
`89934c9..HEAD`; inherited stream-D changes are outside this increment.

The absent-root regression confirms the O7 provisioning gap. The worker supervisor
now provisions a cgroup-v2 root and runner leaf, delegates access to its UID,
exports `UNBUG_MODEL_CGROUP_ROOT`, and probes real contained execution before
starting run.py. Setup failure records startup `containment_unavailable`, attempt
0, exit 78, without model admission. Fresh launches and same-worker resumes share
this supervisor. No launcher, settlement, ledger or B startup-repair files change.

## Evidence

- `worker-cgroup-provisioning/kernel.log`: six tests pass in the cached
  `unbug-bench-box:v2-dev` image, network disabled, private cgroup namespace.
  These include actual root provisioning, supervisor-to-runner environment
  inheritance, and nonroot membership and kill permission. No cgroup operation
  is mocked in these kernel tests.
- `worker-cgroup-provisioning/negative-control.log`: running the new environment
  test against the original `7dbdc58` supervisor fails because preparation is
  never called. The production checkout was not patched for this control.
- Focused supervisor tests: 4 passed. Full worker-command delivery exam: passed,
  including its runner environment assertion. These transport fixtures author
  only the provisioning edge; they do not claim kernel evidence.
- An earlier kernel attempt in `python:3.12-slim` passed nonroot delegation but
  lacked `ps`, required by the existing supervisor cleanup. The cached worker
  image supplies `ps`; the six-test result above uses that image. No runtime or
  timing limit was weakened.
- Full suite: first attempt hit the 7200-second outer wrapper timeout after
  spending almost the entire interval waiting for the shared lock. It reached
  `tests/bench/test-launch-guards.py`; no full-suite verdict was produced. The
  incomplete output is retained in `full-suite-attempt1.log`. No process retained
  that log after exit. Attempt 2 also hit the outer timeout, entirely in the
  lock queue, without running tests (`full-suite-attempt2.log`, empty). Attempt
  3 keeps the 7200-second execution bound, measured from first test output,
  separately from the plain-lockf queue wait. Test limits are unchanged. Command:
  `lockf /tmp/unbug-suite.lock uv run --with numpy --with scipy python -B tests/run.py`.

Parent then retired the shared suite lock. Attempt 3 was still queued and was
stopped by matching its process cwd to this worktree, then terminating only its
own process group (lockf PID 33462). No tests ran in that attempt; its empty log
is retained as `full-suite-attempt3.log`. After merging `parallel-tests`, the
full suite uses the exact command:
`uv run --with numpy --with scipy python -B tests/run.py`.
The first unlocked run was interrupted by the parent's model switch; its partial
output is retained in `full-suite-interrupted.log`. On the requested rerun,
185 scripts ran with one failure in `test_batch_launch.py` at credential-bundle
metadata extraction (888.962 s; `full-suite-first-unlocked.log`). That error was
not a timeout, so no timing-only cause is claimed. Running that file alone with
unchanged limits passed all 8 tests (125.485 s wall, 122.783 s test time;
`batch-launch-rerun.log`). The final aggregate reused 184 identical-code passes
and reran only that script: **185 scripts, 0 failed, exit 0**, 542.632 s
(`full-suite.log`). The earlier rerun reused 179 passes from the interrupted
run. No production source or test limit changed during these runs.

The noninteractive sudo invocation and refusal are unit-tested; real delegation
is kernel-tested with a root helper and a nonroot child. No live worker, provider
or model call was made. Live VM provisioning, actual-CLI cancellation and
isolated-UID acceptance remain unqualified. No Murphy row is closed here.

One fresh Claude diff review follows the suite, as requested. Pilot admission
implementation remains parked until this increment is handed back.
