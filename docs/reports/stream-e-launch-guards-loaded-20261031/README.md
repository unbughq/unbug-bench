# Stream E loaded validation, 2026-10-31

Tested source: `8ff860637a26c651ed76fa73fa4cd34fb9794d8a`, on `stream-e-launch-guards-clock`, with
`factory-simplify` at `b500db9fff4a719ff8fdf1d74209dd56e7b09448` merged in.

Production changes are needed: a slow control VM can exceed the old two-second
`ps` probe limit, losing the descendant snapshot and leaving nested sessions
alive. The macOS validation host additionally returns EPERM for zombie-only
process groups, which formerly turned successful billing/deletion calls into
cleanup errors. The probe now allows 60 seconds; group signalling tolerates
that error, individual PID signalling stays strict, and the deletion-receipt
outer guard allows cleanup to finish. The timed-out probe's group is killed.
The change is small and follows the engineering rules' obvious-cause exception;
review against the commit messages and existing isolation design.

Five consecutive sequential pairs passed with three CPU burners and test
processes at nice +10 on a 12-logical-CPU macOS host. A full suite ran
alongside; a second full suite started when the first completed, preserving
suite activity through the fifth pair. Every isolation run passed 21 tests.
Load samples and exact timestamps are in `results.json`.

launch-1: exit 0, 476.276 seconds.

isolation-1: exit 0, 22.679 seconds.

launch-2: exit 0, 297.208 seconds.

isolation-2: exit 0, 19.478 seconds.

launch-3: exit 0, 338.550 seconds.

isolation-3: exit 0, 18.260 seconds.

launch-4: exit 0, 290.775 seconds.

isolation-4: exit 0, 20.195 seconds.

launch-5: exit 0, 307.761 seconds.

isolation-5: exit 0, 20.343 seconds.

Full suite command: `uv run --with numpy --with scipy python -B tests/run.py`.
Full suite 1: **155 test scripts run; 0 failed**, exit 0, 1589.415 seconds.
Full suite 2: **155 test scripts run; 0 failed**, exit 0, 1341.209 seconds.
Both full suites finished; all five pairs overlapped suite activity (the restart
gap was under 0.01 seconds). All validation processes have exited. Compressed verbatim logs and SHA-256 hashes are committed here.
Unique raw log directory: `/var/folders/wy/9m9k8zxx55dbm7_s_xqfmc7c0000gn/T/stream-e-b66ae96c-final-20261031-gij6nfyx`.

The initial attempt exposed `os.waitid` missing from uv's macOS CPython 3.11.15,
although system Python exposed it. Replaced that unfinished test edit with
bounded real `ps` zombie observation and guaranteed reaping; recorded Murphy row
`new-isolation-waitid-1`. The focused regression then passed. Restarted all five
pairs and the full suite at the fixed source above. The initial full suite
finished 155/0 but is excluded because source changed while it ran. Its raw logs
remain at `/var/folders/wy/9m9k8zxx55dbm7_s_xqfmc7c0000gn/T/stream-e-b66ae96c-20261031-9tfd2foa`.
Three burners from that superseded attempt also overlapped the first final pair,
then were explicitly stopped. The final run's three burners were stopped after
all five pairs passed, while the second full suite continued to completion;
`results.json` records that stop time.

No push, merge into factory-simplify, or main-branch change was performed.

Fresh Claude `claude-opus-5-5` review is saved verbatim with the implementation
response in `docs/reviews/stream-e-loaded-cleanup-diff-1.md`. Its two blocking
documentation findings were accepted and fixed in `f270a87`: correct the EPERM
closure wording/comment and keep the portability row inside the register table.
No blocking finding was rejected. The original FAIL verdict remains verbatim
in the report; the fixes are documented in the response. No additional review
was requested for these small documentation corrections. A nonblocking outer-wall
mismatch is tracked as open Murphy row `new-isolation-outer-wall-1`.

After review, verified the Python AST and shell noncomment lines match tested
source `8ff8606`; executable behavior is unchanged. The second suite spans only
these comment/documentation changes. Final evidence additions are documentation
and compressed logs only.
