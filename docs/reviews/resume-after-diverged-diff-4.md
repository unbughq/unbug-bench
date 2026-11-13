**Blocking**

- [engine.py:698](/Users/bugsincode/Developer/unbug-bench/.claude/worktrees/agent-ab3131d23824af05e/factory/durable/engine.py:698) — The overlap guard checks only attempts owned by diverged workflows. An earlier-created resume can reuse a diagnosis owned by a later-created diverged workflow, then record more writer attempts and hold. The diverged workflow is selected as latest, but the global attempt list includes the sibling’s attempts, which are absent from its path. A read-only DBOS-record reconstruction using legacy and current resume points raised `KeyError` at [engine.py:793](/Users/bugsincode/Developer/unbug-bench/.claude/worktrees/agent-ab3131d23824af05e/factory/durable/engine.py:793). The waste preflight catches `ContractError`, so this crashes the resume request instead of refusing it. Reconcile the overlapping work or refuse when relevant attempts are absent from the selected path.

**Non-blocking**

- [test_durable_engine.py:2156](/Users/bugsincode/Developer/unbug-bench/.claude/worktrees/agent-ab3131d23824af05e/tests/factory/test_durable_engine.py:2156) — The added tests do not cover missing parent IDs, an unsafe nonlatest diverged workflow, `diverged_not_replayed`, reused attempt ownership, or the reverse overlap above. They also do not assert the incident’s exact point, renumbering and waste keys. Mocked DBOS records can exercise these cases without extending the disk-backed fake.

**Nits:** None.

In-memory checks produced the requested 1bb2ad-shaped point and writer waste keys, preserved the prior point after a divergence with no owned attempts, and refused a missing parent. I did not run the disk-backed suite or inspect the live control records.

Verdict: FAIL

## Disposition (elephant)

- Blocking (a sibling's attempts outside the selected path raise KeyError): addressed after this
  review, without another review round, as the coordinator asked. Each position lookup the resume
  point depends on (the GATES repair, the continued run, `at`) now raises
  `resume:history_not_in_latest`, a ContractError. Overlapping workflows of one case therefore get
  a clean refusal rather than a crash. That covers the shape this review found and the earlier
  overlap shapes. The overlapping-start race itself predates both branches. This change has not
  been reviewed.
- Non-blocking, tests: still open. There are no mocked-record tests for a missing parent, an
  unsafe non-latest diverged workflow, `diverged_not_replayed`, `history_not_in_latest`, or the
  exact 1bb2ad point. Those points were checked against the real records read-only.