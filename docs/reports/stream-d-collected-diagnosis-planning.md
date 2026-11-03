# Authenticated collected-generation planning

Implementation baseline: b80929a (accepted opt-in plus parallel-tests ee17a83).
Design reviews: stream-d-collected-diagnosis-planning-design-1.md (findings
accepted), design-2.md (PASS, no blocker or major).

The existing holder tick now calls plan_collections. Production plan requests
supply a durable producing-operation ID and revalidate current source, immutable
collection, ACK/outbox/pointer, retirement, frozen config and money state inside
plan's existing money lock. Facts and queue identity commit together. The shared
_post prefix is reused, one snapshot is verified per attempt, consumed/retired
sources are skipped, and refusals retry after a 60-second process-local delay.

No pilot activation, reserve/dispatch path, money grant or schema changes.
No manifest opts in and no Murphy row closes. Resume queue draining remains
the next increment; this caller alone does not execute diagnosis.

Focused verification: test_batch_planning.py 11 tests OK; test_batch_holder.py
60 tests OK. The first exploratory planning run also included the imported
HolderTests class (58 tests OK); the import was corrected to module-only before
the focused 11-test run so the handback suite does not duplicate those tests.
Controls are explicitly labelled: retained ciphertext/card/creation event with
authored bindings, retirement proof and diagnosis API projection. No real
diagnosis eligibility or live qualification is claimed.

Full suite: 185 scripts, 1 failed (184 passed), exit 1 at implementation
3e3528081d1ccf0ffbd126bb292370a8875b2368. Command:
uv run --with numpy --with scipy python -B tests/run.py (no lockf).
Record: stream-d-collected-diagnosis-planning-suite-20261103T174906Z-80c52ba9.json/.log.
Only test_control_resume.py failed: five deadline failures at existing 10/20-second
controller windows. That test, factory/control_resume.py and factory/launch.sh
are unchanged in b80929a..3e35280. All 11 planning tests and all 60 holder tests
passed in the full suite. No timeout was weakened and no source fix was made.
The first focused recheck exited 1 (24 tests, nine failures). Its command
omitted BENCH, unlike tests/run.py, and its detached supervisor failures are
not comparable to the full-suite result: runner_supervisor uses BENCH to locate
bin imports. This was an invocation mistake. The exact suite environment is
being used for a corrected focused recheck; no source change or timeout change.
At 2026-11-03T18:30:33Z the host load averages were 44.86/56.35/74.06;
this observation alone does not prove the full-suite failure was load-only.
No repeat full suite is queued.
Diff round 1: production has no findings; code NOT PASS on a test guard that
batch_tick could swallow. All findings accepted; recorder/assertion guards,
scan-to-plan depth coverage and journal byte assertion fixed in tests only.
Final diff round 2: Code PASS, no blockers, all round-1 findings independently
verified fixed. Record: stream-d-collected-diagnosis-planning-diff-2.md.
Post-fix focused command was BENCH=<own worktree> python3 -B
tests/factory/test_batch_planning.py, native session 93434, exit 0: 11 tests
in 15.156s. Run before commit 6bd0515 on its exact test-file content, with
HEAD then 986d788 and that test edit uncommitted. No production edits followed.
The uncached replacement handback suite also exercises this final test source.



## Parent runner correction

Parent requested parallel-tests 74dc5c7 for handback after removing its pass
cache. Merged as 5ffb0c2. This changes only the separately reviewed suite runner
and its docs/tests; the planning production source is still 3e35280.
A new handback full suite on that runner is required by this explicit correction,
without lockf. Wait for the focused controller recheck to finish before starting
it; keep the earlier 185/1 record unchanged.


## Corrected controller recheck

stream-d-collected-diagnosis-planning-controller-bench-recheck-20261103T183244Z-c07827b6.json/.log:
exit 0, all 24 tests OK, with BENCH set exactly as tests/run.py sets it.
No controller, test, timeout or planning production change was needed.
Recorded host load was 48.65/53.51/70.40 before and 58.18/54.83/66.95 after;
this was not claimed to be a quiet-host proof. The earlier full result stays
185 scripts / 1 failure. The focused pass supports the parent's existing
unrelated timing-failure rule; the merged tree remains the parent's gate.

All design and diff review rounds are complete and Code PASS. Start the
explicitly requested replacement handback full suite on the uncached runner.


## Interrupted uncached handback attempt

Uncached suite at 1ebd144 exited 143 after about six minutes, with an empty
log and no summary. The wrapper did not reach its 7200-second timeout; the
termination reason is unknown. Record marks interrupted=true, verdict=null
and suite_started=null (buffered output cannot prove no scripts ran).
A cwd-scoped process check found no remaining suite process in this worktree.
Preserve the non-result and restart for one completed uncached handback run.
