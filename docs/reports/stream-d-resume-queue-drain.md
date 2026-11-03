# Diagnosis resume queue drain

Land18 at 15a5c6a was merged. Design:
stream-d-resume-queue-drain.md; reviews design-1 (all three Majors accepted)
and design-2 (PASS, no blockers or Majors).

The holder tick now drains opted-in resume rows through the existing reserve,
reconcile and dispatch path. It checks the exact row and recomputed diagnosis
facts against the authenticated source while holding the existing money lock;
it validates source ACK, pointer, retirement, producing config, cumulative
money, deadline and legacy markers. Existing operation IDs are the replay latch.
Settlement priority, 60-second process-local refusal backoff, and the explicit
replacement-enabled diagnosis deferral follow the reviewed design.

Focused tests: BENCH=<this worktree> python3 -B
tests/factory/test_batch_resume_queue.py: 21 tests OK (8.180 seconds);
tests/factory/test_batch_planning.py: 11 tests OK (3.457 seconds).
These use saved card/ledger/ciphertext and creation artifacts with authored
batch, deletion, transport and dispatch controls. The two-leg unknown settlement
uses real accounting reconciliation, followed by an authored worker-boundary
diagnosis_pending card. No live model or worker qualification is claimed.
The imported-source case uses an explicitly authored imported queue control.

Diff round 1 found that the new _admit argument broke its direct qualification
tool and test callers. The finding is accepted; every direct caller is migrated,
the design is corrected, and the named regression files pass. With the final
test edits and BENCH set to this worktree, uv Python runs gave:
test_batch_resume_queue.py 21/21, test_batch_admission_clamps.py 9/9,
test_batch_transfer.py 14/14, and test_qualify_batch_inputs.py 11/11.
Additional predecessor-facts and non-directory-marker tests cover the review nits.
Fresh final diff review is required. One full no-lockf suite follows.
No Murphy row closes; item 9 and new-stream-d-current-comparison-1 retain their
real-artifact/live integration requirements. B retains pilot admission, lifecycle
limits, cleanup and Boat settlement. Known-total diagnosis resumes in
replacement-enabled batches remain queued until replacement priority is wired.

