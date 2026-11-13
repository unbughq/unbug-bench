**Blocking**

- [engine.py:608](/Users/bugsincode/Developer/unbug-bench/.claude/worktrees/agent-ab3131d23824af05e/factory/durable/engine.py:608) — Treating every owned divergence as a hold can bypass a required diagnosis. For example, a resumed workflow can exhaust a live writer step’s infrastructure retries, then diverge when a stale restore requires a missing diagnosis attempt. The next resume point restores the failed writer attempts and starts another writer attempt with a fresh allowance, rather than running the diagnosis the exhausted retries required. An in-memory record check reproduced that resume point.

- [engine.py:608](/Users/bugsincode/Developer/unbug-bench/.claude/worktrees/agent-ab3131d23824af05e/factory/durable/engine.py:608) — The same classification permits an override to rerun a completed scientific step. If live GATES passes and the workflow then diverges restoring a missing SEAL attempt, an override restores the successful GATES attempt and starts another one. That can reroll a gate result; an in-memory check reproduced the returned point.

**Non-blocking**

- [engine.py:605](/Users/bugsincode/Developer/unbug-bench/.claude/worktrees/agent-ab3131d23824af05e/factory/durable/engine.py:605) — Missing parent IDs are treated as proof that a diverged workflow owned no attempt. DBOS’s migration adds `parent_workflow_id` as nullable without backfilling older rows. If such rows are present, a workflow with live work is silently dropped. In a simulated 1bb2ad-shaped lineage, this changed the point from the writer rerun with one factory-bug resume and waste keys to the earlier diagnosis with zero resumes and no waste keys. Confirm the database has no such rows, or handle unknown ownership conservatively.

- [engine.py:606](/Users/bugsincode/Developer/unbug-bench/.claude/worktrees/agent-ab3131d23824af05e/factory/durable/engine.py:606) — A no-attempt workflow is dropped from `runs`, but its role swaps and extra-money grant still carry into later resumes through separate lineage scans. That conflicts with the commit’s “as if it never ran” description. The intended treatment of those authorizations needs clarification.

- [test_durable_engine.py:2156](/Users/bugsincode/Developer/unbug-bench/.claude/worktrees/agent-ab3131d23824af05e/tests/factory/test_durable_engine.py:2156) — The new tests cover the two incident-shaped paths and exercise the rerun cap, but do not cover divergence after other live work, missing ownership, the exact waste keys and resume point, or a further resume after a subsequent held workflow.

**Nits:** None.

An in-memory check of the 1bb2ad-shaped records produced the requested sequence, restore, renumbering, count, and waste keys. A simulated later held resume retained the expected count with the ERROR workflow present. I could not run the SQLite integration tests in the read-only environment or inspect the live control records.

Verdict: FAIL

## Disposition (elephant)

- Blocking 1 and 2 (an owned divergence taken as a hold of whatever ran last): accepted. A
  diverged workflow with attempts of its own now continues only in the 1bb2ad shape: its last
  attempt is a factory_bug diagnosis whose in-place rerun broke before it started. Any other one
  is refused with `resume:diverged_after_live_work` for a founder to look at. New test:
  ReleaseHolds.test_a_resume_after_one_that_diverged_past_other_live_work_is_refused.
- Non-blocking, missing parent ids: handled conservatively. When any attempt of a lineage with a
  diverged workflow has no parent, the resume is refused (`resume:diverged_unknown_owner`).
  Checked read-only: none of the 75 attempts of 1bb2ad, 86b100 and 22e434-3 lacks one.
- Non-blocking, role swaps and money grants of a dropped workflow: kept on purpose. They are the
  operator's authorizations for that resume and still apply to the next one. "As if it never ran"
  refers to its attempts and resume record.
- Non-blocking, tests: the refusal is now a test. The exact points and waste keys were checked
  against the real records; they are listed in the PR.