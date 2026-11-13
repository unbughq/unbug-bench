**Blocking**

- [engine.py:665](/Users/bugsincode/Developer/unbug-bench/.claude/worktrees/agent-ab3131d23824af05e/factory/durable/engine.py:665) checks for unsafe live work only in the latest retained workflow. Two overlapping resumes can both pass the initial check: A can perform an additional live writer attempt and then diverge, while the later-created B holds at a diagnosis based on an earlier shared attempt. A subsequent resume selects B and ignores A’s unsafe divergence. A mocked call returned a point whose diagnosis history omitted A’s live work. The start race predates this diff, but accepting the earlier `ERROR` makes this lineage resumable.

**Non-blocking**

- [engine.py:669](/Users/bugsincode/Developer/unbug-bench/.claude/worktrees/agent-ab3131d23824af05e/factory/durable/engine.py:669) matches a rerun event to a diagnosis by sequence alone. In a mocked stale record, diagnosis `3/1` triggers a rerun that starts a writer attempt; the workflow then restores an earlier-owned factory-bug diagnosis `3/2` and diverges on missing `3/3`. The event still ends in `3`, so the guard accepts the workflow, drops the completed rerun from the count, and books the new writer attempt as waste against the older verdict. I could not establish that a deployed point builder produces the required combination of stale restore and missing renumbering.

- [ARCHITECTURE.md:384](/Users/bugsincode/Developer/unbug-bench/.claude/worktrees/agent-ab3131d23824af05e/ARCHITECTURE.md:384) says every diverged workflow with its own attempt counts as held. It omits the factory-bug/rerun restriction and the refusal when ownership is unknown.

- [test_durable_engine.py:2172](/Users/bugsincode/Developer/unbug-bench/.claude/worktrees/agent-ab3131d23824af05e/tests/factory/test_durable_engine.py:2172) exercises the rerun cap indirectly, but does not assert the exact resume point, renumbering, or waste keys. The new tests also omit missing-parent refusal and a further resume after a held successor with the `ERROR` workflow still present.

**Nits:** None.

Read-only mocked checks produced the requested 1bb2ad-shaped point and writer waste keys, refused a missing parent, and preserved the count and renumbering through one safe held successor. I did not independently inspect the control-VM records or run the disk-backed suite in the read-only environment.

Verdict: FAIL

## Disposition (elephant)

- Blocking (only the latest diverged workflow was checked): accepted. Every diverged workflow
  with attempts of its own must now have the 1bb2ad shape, whichever of the lineage's workflows
  is latest; otherwise `resume:diverged_after_live_work`.
- Non-blocking (rerun matched to its diagnosis by seq alone): accepted. The check now takes the
  workflow's own last attempt from its step list and requires that the workflow started it (its
  parent), that it is a factory_bug diagnosis, and that the rerun event ends at its seq. An
  earlier-owned diagnosis replayed last no longer qualifies.
- Non-blocking, ARCHITECTURE.md: now states the restriction and the unknown-owner refusal.
- Non-blocking, tests: the exact points, renumbering and waste keys were checked against the real
  1bb2ad, 86b100-r10 and 22e434-3r5 records read-only; they are listed in the PR. The rerun-cap
  test shows the count. The missing-parent refusal is a one-line guard; there is no fake test for
  it, because the fake DBOS always records parents.