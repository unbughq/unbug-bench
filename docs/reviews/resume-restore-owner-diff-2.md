**Blocking**

- [engine.py:607](/Users/bugsincode/Developer/unbug-bench/.claude/worktrees/agent-ab3131d23824af05e/factory/durable/engine.py:607) assumes attempt creation timestamps strictly order the history. DBOS records millisecond timestamps without a uniqueness guarantee. In an in-memory lineage with zero infra retries, diagnosis `5/1` and `5/2` stop on infra across two resumes; `5/3` returns `factory_bug`; the in-place writer rerun `4/2` fails; and diagnosis `5/4` starts in the same millisecond as that writer. The next resume returns `at=[5,"diagnosis",1]` and `restore=[[5,"diagnosis",1,4]]`. Replay therefore skips the factory-bug verdict and writer rerun, then continues without restoring the writer’s state. The two diagnosis runs must remain separate. This collision was reproduced with mocked records, not observed on live Postgres.

- [runtime.py:365](/Users/bugsincode/Developer/unbug-bench/.claude/worktrees/agent-ab3131d23824af05e/factory/durable/runtime.py:365) in the requested two-dot snapshot ignores the case-money grants already supported on `origin/main`. A lineage with an approved raised ceiling is rejected as `resume_money` once its spend plus the next allowance exceeds $50; the CLI grant options are also absent. The branch is behind `origin/main`, so integrating main may preserve the feature, but this HEAD should not be treated as a release without it.

**Non-blocking**

- [test_durable_engine.py:2076](/Users/bugsincode/Developer/unbug-bench/.claude/worktrees/agent-ab3131d23824af05e/tests/factory/test_durable_engine.py:2076) covers two diagnosis runs and one rerun-counting case, but the added tests do not directly exercise the prior review’s higher-sequence restore on rewind, a legacy skip dropped and reintroduced with the same value, or a restored diagnosis followed by an in-place recertification gate repair. They also do not cover timestamp ties.
- [test_durable_engine_fakes.py:672](/Users/bugsincode/Developer/unbug-bench/.claude/worktrees/agent-ab3131d23824af05e/tests/factory/test_durable_engine_fakes.py:672) strips fields from a newly generated resume; it does not recover a DBOS workflow recorded before this change. Inspection of DBOS 3.4.0’s checkpoint behavior found no separate patch-placement error, but the test does not establish historical replay compatibility.
- [resume-restore-owner-diff-1.md:1](/Users/bugsincode/Developer/unbug-bench/.claude/worktrees/agent-ab3131d23824af05e/docs/reviews/resume-restore-owner-diff-1.md:1) adds a review dossier to the source tree, contrary to [AGENTS.md:11](/Users/bugsincode/Developer/unbug-bench/.claude/worktrees/agent-ab3131d23824af05e/AGENTS.md:11), which directs review findings to the PR.

Read-only, in-memory checks of the five prior examples produced the intended resume points when timestamps were strictly ordered; a representative ordinary legacy resume also retained what its skips covered. These checks do not prove full replay behavior. Disk-backed tests and live recovery were not run in the read-only environment.

**Nits:** None.

Verdict: FAIL