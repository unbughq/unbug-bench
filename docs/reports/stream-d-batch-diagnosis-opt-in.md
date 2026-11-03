# Authenticated batch diagnosis opt-in — increment 1

This increment replaces the global diagnosis switch with the optional pinned
manifest policy diagnosis_policy={schema:1, enabled:true}. Host planning and
worker diagnosis/extension capture use the same strict policy shape; the worker
also checks current money authority and its batch/deadline binding. No tracked
batch opts in, and no worker or live call was launched.

The existing worker config schema and authenticated manifest installation are
reused. Cards, checkpoints and environment variables cannot activate diagnosis.
Cheap observation exclusions run first. A deadline after a durable diagnosis
decision refuses safely; replay consumes that exact decision without a new call.
The historical preparation preflight and rollback instructions are updated.

Design review: docs/reviews/stream-d-batch-diagnosis-opt-in-design-1.md, PASS.
Four Majors and four Nits accepted and addressed. Full-suite record and fresh
diff review follow below when complete. No Murphy row closes.

Still required: production collection-to-plan wiring, then durable resume queue
draining through existing holder reserve/reconcile/dispatch with ACK, retirement
and money checks. B retains pilot admission, cleanup and Boat settlement.
O7 is paused/assigned elsewhere with no lane-1 O7 design or implementation.
The founder replacement pilot decision is recorded without deleting historical
item-8 analysis; this code grants no pilot spend or launch authority.

First locked attempt: ...T063326Z-320e3f27, command exit 2 before tests;
uv could not resolve pypi.org for scipy. This is not a suite result. Cached
numpy/scipy imports succeed with UV_OFFLINE=1; retry uses that environment
setting with the unchanged locked suite command. Both records are retained.

Parent follow-up: DNS is restored; run the normal locked command on d7250f9's
implementation tree, timeout 7200000 ms, retry once only for DNS failure, then
fresh diff review (cap 2). Rebase onto land12 only if it conflicts. The queued
cached-dependency attempt ...T075852Z-f5e16073 was cancelled before it spawned
any suite child, not counted as a suite result. No duplicate suite was launched.

The parent-requested normal attempt ...T080941Z-4e1f7d59 exited 75 after
7000 seconds waiting for the shared lock (lockf: already locked). No tests
started, so there is no suite verdict and no DNS retry was used. Requeue the
same locked command with the same 7200000 ms per-attempt timeout; retain this
admission timeout instead of labelling it a test run or a pass. Source remains
byte-identical to d7250f9 under factory/tests/bin/tools.

Parent clarification: exit 75 from lockf -t is only a lock-wait timeout, not a
test result, failure or blocker. It has no suite verdict. If it recurs, requeue
immediately with plain lockf /tmp/unbug-suite.lock (no -t). The current requeued
run acquired the lock and was already running tests at this clarification.

Actual locked suite on d7250f9 production/tests: 180 scripts, 1 failed (exit 1),
...T100805Z-12f8ac07. Only test_batch_service_d.py failed: four assertions still
assumed returning from an enabled helper would restore the old global-off gate.
The manifest policy is immutable instead. Fix the test controls to use separately
pinned enabled/disabled fixtures; retain the real D projection in the stored-facts
negative, explicitly labelled as an authored control. No production change.
Run this file, then a fresh full suite under plain lockf (no -t), per parent.

Parent scope clarification: O5b request-only stress disposition belongs to stream
E on t3/isolation-o5b. Lane 1 takes no O5b code. After this authenticated batch
opt-in increment passes, finish production diagnosis scheduling: authenticated
collected generations to batch_service.plan, then resume requests through the
existing holder reserve/reconcile/dispatch path. The pilot uses pinned manifest
opt-in; the old global DIAGNOSIS_ENABLED switch is removed by this increment.
B retains pilot admission and Boat settlement. This first increment alone does
not yet provide the production plan/drain caller.

Final locked suite PASS: 180 scripts, 0 failed, exit 0. Record:
stream-d-batch-diagnosis-opt-in-suite-20261103T111704Z-83f1739e.json and .log.
Command: lockf /tmp/unbug-suite.lock uv run --with numpy --with scipy python -B tests/run.py.
Timeout 7200000 ms; no DNS retry needed. Tested head cf3415a; later changes are
documentation only. Production implementation remains identical to d7250f9.
The real-D fixture migration is included and all 15 tests pass in the full run.

Landing check: factory-simplify 7dbdc58 (land12 plus E O5b) dry-merges cleanly
with this branch. Parent requested rebase only for conflicts, so no rebase.
Its changes since ff31d87 add four test controls that still patch the removed
DIAGNOSIS_ENABLED symbol. Those controls need the same manifest-policy migration
when integrating; flag this explicitly in the fresh review and handoff. No
production caller/drain code is added in this opt-in increment. Fresh diff
review round 1 is pending. No Murphy row closes; no batch is opted in.

Parent approved after diff round 1: code PASS and I1 accepted. Rebased cleanly
onto factory-simplify 7dbdc58. Apply exactly the four reviewer-specified test
migrations: three runtime.diagnosis_policy(self.c) contexts and one direct
service.plan call using ServiceTests' already pinned enabled policy. Remove
unused batch_service imports. No production edits. Re-grep expects only the
job-config environment spoof. One plain-lockf full suite on the combined tree
is the parent-approved merge gate; round-2 review is explicitly skipped.
Final passing commit subject must contain "pass". Next increment: production
batch_service.plan caller; no O5b, pilot admission or Boat settlement work.

Combined-tree attempt ...T130047Z-e646d12a was interrupted at the outer 7200-second
harness deadline (exit 124), which included waiting for the shared lock. It
stopped during test_stream_d_execution.py; there is no full-suite verdict.
The log contains 99 completed unittest files (1556.6 logged seconds) and no
reported unittest FAIL/ERROR lines before the cutoff. The migrated blocking-
stress tests passed 18/18. Retain the partial record honestly; do not call it
a test assertion failure or a pass.

Retry operational change only: plain lockf still owns the shared lock, with
unbounded admission wait. Start the same 7200000-ms execution deadline AFTER
acquisition, around the unchanged uv suite command. Record acquisition time and
the exact Python timeout wrapper in the JSON for audit. No production or test
source changes; parent-approved mechanical migration remains exactly four
contexts and unused-import cleanup. No round-2 review is started.
