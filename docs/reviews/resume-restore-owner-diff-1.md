**Blocking**

- [engine.py:698](/Users/bugsincode/Developer/unbug-bench/.claude/worktrees/agent-ab3131d23824af05e/factory/durable/engine.py:698) prunes restores by numeric sequence even when a higher-sequence step must replay before an in-place rerun. For example, diagnosis 3 restores attempts 1–2, attempt 3 says `factory_bug`, and the rerun of writer at seq 2 stops on `infra:roles_refused`. The next point is `at=[2, "writer:1", 3]`, but pruning drops the diagnosis restore at seq 3. Replay reaches the old diagnosis infra hold and raises `resume:diverged` before reaching `at`.

- [engine.py:700](/Users/bugsincode/Developer/unbug-bench/.claude/worktrees/agent-ab3131d23824af05e/factory/durable/engine.py:700) keys restores only by `(seq, step)`, so it cannot retain two runs of the same step at the same seq. If diagnosis 3/1–2 is restored, diagnosis 3/3 triggers an in-place writer rerun, and diagnosis 3/4–5 then stops on infra, the next point replaces `[3, "diagnosis", 1, 2]` with `[3, "diagnosis", 4, 5]`. The first diagnosis run reaches its old hold instead of continuing, and replay diverges. `first_attempt` finds the second run correctly, but the restore map loses the first.

- [engine.py:617](/Users/bugsincode/Developer/unbug-bench/.claude/worktrees/agent-ab3131d23824af05e/factory/durable/engine.py:617) assigns a legacy skip to its first occurrence, even if a rewind dropped that skip and a different step later reused the same seq and attempt number. A legacy diagnosis skip `3:1` can be dropped by a factory-bug rewind; stress can later stop at `3/1` and reintroduce `3:1`. A subsequent resume derives diagnosis as the owner, although renumbering excludes that diagnosis. Stress’s recorded stop is then not restored, so replay diverges.

- [engine.py:581](/Users/bugsincode/Developer/unbug-bench/.claude/worktrees/agent-ab3131d23824af05e/factory/durable/engine.py:581) counts reruns by seq even when `at` requires those reruns to replay. If diagnosis 5 reruns writer 4 in place, stress 5 then fails and diagnosis 6 holds, the next resume at stress 5 counts the seq-5 rerun as unreplayed while replay will count it again. With a cap of two, the historical diagnosis sees the cap already exhausted and retires before `at`, causing `resume:diverged`.

- [engine.py:635](/Users/bugsincode/Developer/unbug-bench/.claude/worktrees/agent-ab3131d23824af05e/factory/durable/engine.py:635) drops needed diagnosis restores and returns no `at` for `gates_repair`. A recertified GATES 2 can stop on infra, resume its failed diagnosis 3, rerun GATES in place, and retire on a repairable gate failure. The repair resume returns `seq=3` with an empty restore. Its historical diagnosis is treated as live, repeats its infra hold, and never reaches the recorded gate repair.

**Non-blocking**

- [test_durable_engine_fakes.py:675](/Users/bugsincode/Developer/unbug-bench/.claude/worktrees/agent-ab3131d23824af05e/tests/factory/test_durable_engine_fakes.py:675) strips `restore` and `at` from a *new* resume; it does not recover a workflow recorded before the patch. The added tests target the reported in-place failure, but do not establish historical DBOS replay compatibility. Inspection of DBOS 3.4.0’s checkpoint behavior found no separate patch-placement regression, and moving the attempt-counter read introduces no DBOS operation.

Read-only, in-memory checks against `_resume_point`, `_Case.run_seq`, and the diagnosis policy reproduced the blocking resume records and replay failures. I found no independent waste-key error. The disk-backed tests and comparison run against `origin/main` were not run because the filesystem is read-only.

**Nits:** None.

Verdict: FAIL

## Disposition (elephant)

All five blocking findings accepted and fixed in 990e2620. Restores are now keyed by run (seq, step,
first attempt) and pruned by recorded time, not seq:
1. Rewind pruning by seq: a resume keeps restores of runs that start before the continued run ends,
   less diagnoses a factory_bug resume no longer replays (renumber).
2. Two runs of one step at one seq: separate restores; covered by
   ReleaseHolds.test_two_runs_of_a_diagnosis_at_one_seq_each_restore_their_own_attempts.
3. Legacy owner: taken from the resume that set the skip's current value (walking back from the
   latest resume while the value holds), not its first occurrence.
4. Rerun counting: an in-place rerun counts as replayed when its diagnosis comes before the continued
   run starts, outside any restored run; the two-runs test checks it under a cap of 2.
5. gates_repair: keeps restores of runs before the repaired GATES attempt and names its writer round
   (writer:<gates round + 1>) in `at`.

Non-blocking (legacy_resume strips the new fields rather than replaying a recording made before the
patch): accepted as a limit of the fake harness; the read-only VM check covers the real records.