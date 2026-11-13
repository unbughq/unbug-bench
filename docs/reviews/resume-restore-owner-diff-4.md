**Blocking**

- [engine.py:765](/Users/bugsincode/Developer/unbug-bench/.claude/worktrees/agent-ab3131d23824af05e/factory/durable/engine.py:765) can apply an override’s resume count to a diagnosis that must replay *before* that override. With `max_factory_bug_resumes=1`, a new-format resume restores an infra-failed diagnosis at seq 5. Its next attempt says `factory_bug`, a release triggers an in-place writer rerun, stress at seq 5 fails, and diagnosis at seq 6 retires at the cap. An authorized override resumes stress with `factory_bug_resumes=1`. During replay, the earlier diagnosis at seq 5 now sees count 1 instead of 0, retires instead of rerunning the writer, and raises `resume:diverged` before reaching stress. A read-only in-memory check reproduced the point and the changed decision.

- [engine.py:1041](/Users/bugsincode/Developer/unbug-bench/.claude/worktrees/agent-ab3131d23824af05e/factory/durable/engine.py:1041) breaks the existing offline DBOS recovery test. Its [fixture](/Users/bugsincode/Developer/unbug-bench/.claude/worktrees/agent-ab3131d23824af05e/tests/factory/test_bound_wait_replay.py:48) evaluates `_Case.replaying` on an object without `live` or `resume_at`. Calling the imported property with that fixture raises `AttributeError` before the test can record and recover the wait.

**Non-blocking**

- [test_durable_engine.py:2086](/Users/bugsincode/Developer/unbug-bench/.claude/worktrees/agent-ab3131d23824af05e/tests/factory/test_durable_engine.py:2086) covers the reported in-place rerun and a subsequent replay, but the added tests do not directly cover the override above, tied attempt timestamps, legacy multi-owner derivation, or an in-place GATES repair. The earlier dispositions report construction and live-record checks for some of these cases.

- [ARCHITECTURE.md:384](/Users/bugsincode/Developer/unbug-bench/.claude/worktrees/agent-ab3131d23824af05e/ARCHITECTURE.md:384) still describes selecting the newest attempt by creation time and replaying earlier numeric sequences. The branch now uses workflow-path order, which can be nonmonotone.

**Nits:** None.

Inspection found no separate ordinary-resume regression or change to the DBOS operation sequence for records without `restore` and `at`; the legacy derivation appears consistent with the old by-sequence behavior for runs on the latest path. The prior dispositions’ live-record inventory was not independently verified. The full offline suite and live recovery were not run in this read-only environment.

Verdict: FAIL
## Disposition (elephant)

- Blocking 1 (an override's count reaches a replayed diagnosis): accepted and reproduced first
  (ReleaseHolds.test_an_override_past_the_cap_replays_the_in_place_rerun_before_it ended in
  engine_error). A replayed diagnosis now sees only the in-workflow count: one that ran at the cap
  ended its workflow, so every replayed one decided under it. The lineage's count binds once the
  case is live. The count feeds only the policy's hold-or-retire choice.
- Blocking 2 (the bound-wait replay fixture lacks `live`/`resume_at`): accepted; the fixture sets
  both, and test_bound_wait_replay passes.
- Non-blocking, tests: the override case is now a test. Ties, legacy owners and an in-place GATES
  repair are covered by construction and by the read-only checks of the real records.
- Non-blocking, ARCHITECTURE.md: updated to the path order, `restore` and `at`.
