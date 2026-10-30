# Deployment readiness clock flake

Base: `820d0fb`. Source fix: `2629f74`.

The sequence harness patched the shared `time.monotonic` and `time.sleep`.
Python subprocess uses an imported `_time` alias for its timed wait deadline,
but calls the shared `time.sleep` while reaping a child. Under load, those
reaping sleeps advanced the readiness clock without waiting for the child.
The readiness loop therefore exhausted its simulated 600 seconds in 59 polls.

A deterministic probe inserted a one-shot `time.sleep(11)` into `Popen.wait`
in the extracted launcher helper wrapper. The original harness failed with
`AssertionError: 59 != 60` (2.305 seconds). The fixed harness passed the same
probe (13.301 seconds): the injected cleanup sleep now consumes real time,
not readiness time. The original unmodified focused test also passed before
the fix, consistent with the reported scheduling-dependent failure.

The fix executes the hash-verified helper in a namespace and replaces only
that namespace's `time` reference before invoking `main`. Subprocess retains
real clocks. A harness assertion checks that a subprocess sleep cannot advance
the readiness clock. Exact 60-attempt timeout and no-mutation assertions remain.
The folding-to-completion test also passes. No production file changed.

Production waits against elapsed time, not an attempt quota. The deadline is
the earliest of the original VM lifetime minus collection reserve, 600 seconds
from helper startup, and an optional controller deadline. Provider expiry can
shorten it further. Slow queries or scheduling legitimately reduce poll count;
production checks elapsed time and does not stop because a poll was skipped.
Extending the deadline to force 60 attempts would violate the lifetime reserve.
No real batch failure was established, so `new-deploy-flake-1` is not added.

The change is 15 added and 3 removed test lines with an obvious cause. It uses
the engineering exception to skip a separate design; the commit message is the
review contract. No Murphy row is closed, no security rule changes.

Validation runs the complete deployment test script five consecutive times
with three CPU burners, concurrently with the required full suite:

```sh
uv run --with numpy --with scipy python -B tests/integration/test_qualified_deployment.py
uv run --with numpy --with scipy python -B tests/run.py
```

Results are recorded in `deploy-readiness-clock-loaded.json`. Local raw logs
are in `/tmp/deploy-readiness-clock-validation/`.

Fresh Claude Opus 5.5 goldfish diff review: PASS, no blockers, saved verbatim
in `docs/reviews/deploy-readiness-clock-diff-1.md`. No findings were rejected.
The optional base-drift nit is left for the parent: this task explicitly
requires branching from `820d0fb`, and authorizes neither rebasing onto a new
base nor merging. The isolation assertion is retained. Production is unchanged.

Final validation: **154 test scripts run; 0 failed.** Five consecutive
loaded runs each passed all 21 deployment tests (19.25, 19.86, 20.70,
20.09, 20.16 seconds). The full suite remained active for every entire run.
Three CPU burners ran through full-suite completion and were then terminated
and joined. Only evidence documentation changed after the tested source fix.
