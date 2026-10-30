**PASS.** Round 4's blocker and major are both fixed. I found no implementation-readiness blocker and no major gap. Four nits are left, and none of them needs another review round.

Mode was REVIEW, read-only, using the zoom-out, design-critic and implementation-readiness roles against both standards. I checked the design against the code at d0be3c9 in the worktree and wrote nothing.

## Round-4 findings

| ID | Status |
|---|---|
| B1: a losing child's exit could mark a live operation failed | **Resolved.** `record_exit` takes the operation lock nonblocking. If the lock is busy it ignores that exit and never touches state (lines 425–430, 467). The child's last step under the batch lock now requires `state=pending`, `dispatch_started=false` and `incident=null`, or it exits without starting the creator (464–466). The overlap test is specified and asserts that pending survives and only one creator runs (468–470). I traced the paths where the old child succeeds, fails, or is killed, and none of them now lets a worker start under a failed operation. |
| M1: the `launch.sh` restart guard | **Resolved.** The design now names `factory_auto_resume` (`launch.sh:472`), requires an explicit `return 1`, and keeps the existing `batch_release` guard (`launch.sh:475`). It says `return 0` is forbidden. That matches `bin/boat-launch-guards.sh:323-326`, where a nonzero return falls through to `guard_retire`. The test checks that `guard_retire` is actually called (lines 418–423, 472–475). |
| N1: `max_calls` check on the batch path | Resolved. Lines 477–479 skip the `key_holder.py:355` check for `_batch_job`, and line 266 covers `policy_load` (`key_holder.py:148`) and `check_manifest` (`batch_money.py:54`). |
| N2: missing activation prerequisites | Resolved (lines 480–484). |
| N3: who copies the retirement proof | Resolved. `collect` writes `ACK.retirement=null` and only `reconcile` copies the proof (line 441). |

## Nits (none block implementation)

- **N1. Status has no rule for an operation that was launched, retired, and produced no output** (lines 147–153).
  - The selection rule picks "the unique nonretired operation" or "the latest operation whose output matches current". A retired operation with no output is neither.
  - "With no operation" doesn't apply either, because an operation exists.
  - The tests in this increment can reach this state, since `reconcile` writes it. One sentence fixes it, for example "show stopped with the prior card, or the collected view if there is none". It must not fall into the `launched` → running mapping, which would show a worker that has already been deleted as running.
- **N2. `record_exit` doesn't say what happens when `dispatch_started=true`** (lines 425–430).
  - Line 130 and line 340 depend on the holder recording `dispatch_exit` in that case too.
  - State it directly: once it holds both locks, `record_exit` always stores `dispatch_exit`, and changes state only in the pending/unstarted case.
- **N3. A pending, unstarted operation can respawn a losing child every scan** (lines 342–343, 431–432).
  - This happens while an orphaned child from before a holder restart still holds the operation lock. The losing child's exit is correctly ignored, so `dispatch_exit` stays null and the next scan spawns another child.
  - It is harmless but noisy. Either accept it in one line, or skip the spawn when the scan's own nonblocking probe of the operation lock finds it busy.
- **N4. Add one more activation prerequisite.** An operation with `dispatch_started=true` whose child outlived a holder restart never gets a recorded `dispatch_exit` (line 345).
  - If `launch.sh` then fails before creating a worker, the operation stays pending, keeping its concurrency slot and its hold until the deadline.
  - Staying pending is the right fail-closed choice in this increment. It should still go on the list at lines 454–457 and 480–484 next to the dead-case item.

## Heilmeier and scope

- **Heilmeier:** adequate. The objective is in plain language, there is no new cost, the work is one increment, and the mid-term and final exams are offline.
- **Scope:** holds.
  - The increment covers only the holder, ACK, source chain and current pointer.
  - `HOLDER_ENABLED=False` is a code constant that nothing at runtime can flip, and `DIAGNOSIS_ENABLED` stays false.
  - There is no D dispatcher, no live activity, no legacy booking and no schema-1 migration.
  - Murphy rows 6, 27, 28, 35, 51 and new-batch-service-3 stay open, and cb5e2 and 14d35 stay set aside.
  - Gate-off `authorize` stays schema 1, byte for byte.
- **Implementation readiness:** met.
  - Files and phase order are explicit.
  - The helper boundaries and locking order are fixed, and the schemas are exact.
  - The refusal and incident labels are fixed.
  - The seven-item test matrix plus the overlap and orphan tests are concrete.

The design can go to implementation. Fold N1 and N2 into it during implementation, and add N4 to the activation list.

## Elephant response
PASS accepted. All four nonblocking nits incorporated into the design and implementation plan. No findings rejected.
