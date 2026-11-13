**Blocking**

- [engine.py:625](/Users/bugsincode/Developer/unbug-bench/.claude/worktrees/agent-ab3131d23824af05e/factory/durable/engine.py:625) accepts an earlier diverged workflow even when its live work is absent from the latest held workflow’s path. For example, two overlapping resumes can share a factory-bug diagnosis; the later-created one holds there, while the earlier one runs another writer attempt, records its own second factory-bug diagnosis, and diverges before the next rerun. The earlier workflow passes the new guard, but the global attempt list includes its writer attempt and the selected path does not. The lookup at [engine.py:784](/Users/bugsincode/Developer/unbug-bench/.claude/worktrees/agent-ab3131d23824af05e/factory/durable/engine.py:784) then raises `KeyError`. An in-memory DBOS-record check reproduced this. The waste-key preflight catches only `ContractError`, so a later resume crashes rather than continuing or giving a controlled refusal. The histories need reconciliation or a conservative refusal.

**Non-blocking**

- [test_durable_engine.py:2156](/Users/bugsincode/Developer/unbug-bench/.claude/worktrees/agent-ab3131d23824af05e/tests/factory/test_durable_engine.py:2156) does not prove several key conditions: missing or earlier-owned parent IDs, an unsafe nonlatest diverged workflow, a held successor with the error still in the lineage, or divergence through `_Case.finish`. The incident test also does not assert the exact resume point, renumbering, and waste keys. The overlapping case above needs a regression as well.
- [resume-after-diverged-diff-1.md](/Users/bugsincode/Developer/unbug-bench/.claude/worktrees/agent-ab3131d23824af05e/docs/reviews/resume-after-diverged-diff-1.md:1) and [resume-after-diverged-diff-2.md](/Users/bugsincode/Developer/unbug-bench/.claude/worktrees/agent-ab3131d23824af05e/docs/reviews/resume-after-diverged-diff-2.md:1) add review dossiers to the source tree, contrary to [AGENTS.md:11](/Users/bugsincode/Developer/unbug-bench/.claude/worktrees/agent-ab3131d23824af05e/AGENTS.md:11), which directs findings to the PR.

**Nits:** None.

In-memory checks of the incident-shaped records produced the requested point and writer waste keys, and a missing parent was refused. I did not inspect the control-VM records or run the disk-backed suite in the read-only environment.

Verdict: FAIL

## Disposition (elephant)

- Blocking (an overlapping diverged workflow's live work is missing from the latest history):
  accepted, with a conservative refusal. Every attempt that a diverged workflow kept in the
  lineage started must now be in the latest workflow's history, or be a diagnosis that a
  factory_bug resume dropped. Otherwise `resume:diverged_not_replayed`, a ContractError, so the
  waste preflight refuses it cleanly. The overlapping-start race itself predates this branch.
- Non-blocking, tests: the rerun test now goes on to a later resume (an override past the cap)
  with the ERROR workflow still in the lineage, and it seals. The overlap, the missing parent and
  the non-latest unsafe cases are guards with no fake test: the fake harness cannot start two
  workflows of one case at once and always records parents. The exact points, renumbering and
  waste keys were checked against the real records; they are listed in the PR.
- Non-blocking, review files in the tree: kept, because the founder's process for this change
  asks for reviews under docs/reviews.