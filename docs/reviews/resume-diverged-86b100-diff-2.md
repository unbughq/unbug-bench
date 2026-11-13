**Blocking:** None.

**Non-blocking:** None.

**Nits:** None.

1. The reported root cause matches the code: the former merge could restore a diagnosis skip removed by a later rewind. Read-only, in-memory checks reproduced that behavior. The live records for 86b100 and 22e434 were unavailable for independent verification. [engine.py:584](/Users/bugsincode/Developer/unbug-bench/.claude/worktrees/agent-ab3131d23824af05e/factory/durable/engine.py:584)

2. I found no needed skip lost in the gates-repair, override, infra-stop, factory-bug, or original non-resume workflow paths. Each new resume carries the surviving map, then applies the appropriate truncation and stop count. [engine.py:603](/Users/bugsincode/Developer/unbug-bench/.claude/worktrees/agent-ab3131d23824af05e/factory/durable/engine.py:603)

3. `_resume_point` is called while preparing a new resume batch. Recorded workflows replay their persisted inputs, so this change does not alter their DBOS replay. [engine.py:2123](/Users/bugsincode/Developer/unbug-bench/.claude/worktrees/agent-ab3131d23824af05e/factory/durable/engine.py:2123)

4. The regression test exercises the reported sequence. A mocked check of the actual replay code confirmed that the stale `skip[5] = 2` seeks the nonexistent `stress:2/2` and raises `resume:diverged`; without it, `stress:2/1` advances. The test itself could not be run here because it requires temporary SQLite files. [test_durable_engine.py:1281](/Users/bugsincode/Developer/unbug-bench/.claude/worktrees/agent-ab3131d23824af05e/tests/factory/test_durable_engine.py:1281)

The previously identified in-place rerun issue remains open, as recorded in the earlier review; it is outside this net change.

Verdict: PASS