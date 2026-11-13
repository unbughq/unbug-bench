**Blocking**

- [engine.py:666](/Users/bugsincode/Developer/unbug-bench/.claude/worktrees/agent-ab3131d23824af05e/factory/durable/engine.py:666): A legacy skip can have **multiple owners**, but the derivation retains only one. For example, diagnosis `5/1` fails, `5/2` returns `factory_bug`, the in-place writer rerun succeeds, and stress `5/1` holds. A pre-change resume with `skip["5"] = 1` can restore both diagnosis `5/1` and stress `5/1`, then reach a later GATES hold. The next resume keeps only the diagnosis restore; replay reaches the old stress hold and raises `resume:diverged`. I reproduced the incomplete restore with strictly increasing timestamps.

- [engine.py:1609](/Users/bugsincode/Developer/unbug-bench/.claude/worktrees/agent-ab3131d23824af05e/factory/durable/engine.py:1609): The patch can clear a legacy skip needed by a later step at the same sequence. In the lineage above, a pre-change workflow can be parked at the diagnosis release wait with the writer rerun already recorded. At the unrecorded patch frontier, the patch marks it live and removes `skip[5]`. The recorded stress `5/1` hold is then treated as live, so the case holds again instead of restoring it and trying stress `5/2`. Existing checkpoints replay safely; this continuation does not.

- [engine.py:616](/Users/bugsincode/Developer/unbug-bench/.claude/worktrees/agent-ab3131d23824af05e/factory/durable/engine.py:616): A legacy resume can already carry an inflated `factory_bug_resumes` count from the old sequence-based calculation. The new point preserves that count while replaying and counting the same in-place rerun again. In the preceding lineage, if stress `5/2` also holds, the next point correctly restores both runs but carries a count of one; replay increments it to two although only one rerun occurred. With a cap of two, a later factory-bug diagnosis retires prematurely.

- [engine.py:610](/Users/bugsincode/Developer/unbug-bench/.claude/worktrees/agent-ab3131d23824af05e/factory/durable/engine.py:610): The terminal attempt is still selected by creation timestamp before the ordered workflow path is built. If diagnosis `3/1` returns `factory_bug`, its writer rerun `2/2` then holds, and their millisecond timestamps tie, the higher-sequence diagnosis wins. An in-memory check returned a writer restore covering both runs, counted two resumes where one occurred, and marked both writer attempts as diagnosed waste. This selection predates the branch, but it leaves the timestamp-tie fix incomplete.

**Non-blocking**

- [test_durable_engine_fakes.py:672](/Users/bugsincode/Developer/unbug-bench/.claude/worktrees/agent-ab3131d23824af05e/tests/factory/test_durable_engine_fakes.py:672): `legacy_resume` strips fields from a newly generated point; it does not recover a workflow recorded under the old code. The added tests therefore do not establish patch-frontier compatibility or cover the multi-owner skip and inherited-count cases above.

**Nits:** None.

The earlier run-keying, higher-sequence retention, and gate-repair changes address the reported constructions I traced. The legacy-owner and rerun-count fixes remain incomplete as described above. I found no counterexample for an ordinary resume without in-place reruns.

Validation used read-only, in-memory checks with mocked DBOS records and inspection of DBOS 3.4.0. Disk-backed tests and live recovery were not run. The requested persona directory was absent.

Verdict: FAIL

## Disposition (elephant)

- Blocking 1 (a legacy skip has several owners): accepted. A resume made before `restore` now
  restores, at each skipped seq, every run there that starts at or below the skip, as the old
  by-seq replay did. Legacy records are a closed set: every resume made from now on carries
  `restore`. The control VM has 13 lineages whose latest record is legacy. Read-only, 9 refuse as
  not resumable, 1 is still running, and the 3 crashed ones derive the restores listed in the PR.
- Blocking 2 (the `rerun_at_resume_seq_is_live` patch clears a skip a later step needs): accepted.
  The patch is deleted rather than patched. It only helped a workflow already running under a
  legacy record whose diagnosis at its own resume seq says factory_bug. The one such workflow still
  running on the VM (1110a-2r) is at an admit step at seq 1, where no diagnosis can run. A crash
  there would be recovered like 1bb2ad. The legacy variants of the two tests went with it.
- Blocking 3 (an inherited, inflated legacy count): no code change. Of the lineages with a legacy
  record, only 22e434-5 (not resumable) and 1bb2ad (record counts 0) have an in-place rerun on
  their latest path, so no live record carries the inflation.
- Blocking 4 (last attempt chosen by time): accepted. The last attempt is now the last one on the
  latest workflow's step list. The step a factory_bug diagnosis looked at is the last one at
  seq - 1 on that list. Timestamps are only a fallback for a workflow that ran no attempt.
- Non-blocking (legacy_resume fake): removed along with the patch.