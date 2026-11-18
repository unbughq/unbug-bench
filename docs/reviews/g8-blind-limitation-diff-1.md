# Goldfish review: G8 blind-step known limitation (diff 1)

- Branch fix/g8-blind-limitation. Reviewer: goldfish (fresh agent), read-only. Verdict: **PASS**, no blockers.
- Checked: the section says exactly the founder ruling; fit with reviewer.md and run.py review(); fingerprints
  (gate_state.py hashes reviewer-keys.md into G8 and G9: each new launch reruns the panel once; calibration.py
  does not hash it, so sealed cases are safe); bench facts (bench.py:126/337/542/921, bin/land:55); test fails
  without the change; fixture manifest hashes were already stale snapshots.
- The reviewer ran `git stash` / `git stash pop` in the worktree by mistake; diff and stash list verified intact.

Fixed after review:
1. SHOULD reviewer-keys.md: "reading or patching code on the box" could excuse case code hints -> "bench code ... to
   get at them"; the hint rule now names comments and names the case writes in its own code.
2. SHOULD reviewer-keys.md: bench.py sets UNBUG_MONITOR_BLIND on every guarded service, case services included ->
   the switch is excused in any service that honours it.
3. SHOULD builder.md: say how -> the blind step's admin SQL runs `ALTER ROLE bench_checker NOBYPASSRLS;` (the reset
   turns BYPASSRLS back on), as cases/medusa-oversell-v2 S11 does.
4. NIT builder.md: line moved after the monitor_blind paragraph. NIT design doc: G8 and G9, both gate identities.
