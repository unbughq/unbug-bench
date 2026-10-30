**FAIL.** Round 3 closed M1 and M3. N1, N2 and N4 are fixed and N3 is listed. One new blocker comes from the round-3 crash-recovery rule itself. The fix for round-3 B1 also points at a function that doesn't exist and leaves its return code open. Both need only short edits.

Mode: REVIEW, read-only, using the zoom-out, design-critic and implementation-readiness roles against both standards. I checked the code at d0be3c9 in the worktree and wrote nothing.

## Round-3 findings

| ID | Status |
|---|---|
| B1 orphan restart | **Open.** The variable is now named and kept across an orphan resume (lines 129, 416–421). The `launch.sh` change is wrong; see M1 below. |
| M1 legacy `authorize` | Resolved (lines 280–283, with a gate-off byte test). |
| M2 preflight crash | **Partly open.** The holder-alive and holder-restart paths are now specified (lines 425–432), but together they create B1 below. |
| M3 retirement writer | Resolved. One ordered writer, a proof object, equality required by PRE, and null-to-proof only (lines 434–444, 124, 131). |
| N1–N4 | Resolved (lines 266, 446–449, 451–457). |

## Blocker

**B1. After a holder restart, a busy-lock child's exit can mark a live operation failed, and the still-running old child then starts a worker.** Lines 336–345 and 425–432.
- Dispatch children are started with `start_new_session=True` (as in `key_holder.py:553` and `:671`), so they outlive a holder restart.
1. The old child is still in preflight, which includes decrypting the credential bundle and fetching the Boat inventory. The record shows pending, `dispatch_started=false` and `dispatch_exit=null`.
2. The restarted holder's scan sees exactly those values and spawns a second child. The rule "never duplicates its own live child" doesn't cover the old child.
3. The second child can't take the nonblocking `operations/<id>.lock`, so it exits.
4. The holder reaps it, and `record_exit` writes `failed/preflight_refused` (line 426).
5. The old child then "revalidate[s] POST under batch lock". POST doesn't check the operation's state (lines 317–321), so the child sets `dispatch_started=true` and starts `launch.sh`.
- Result: a real Boat worker belongs to a failed operation.
  - The concurrency count ignores failed operations (line 296).
  - A failed operation must have a null `worker_id` (line 138), so reconcile has nowhere to record the worker and can never retire it.
- Fix, in two parts:
  - `record_exit` takes the operation lock nonblocking and writes `failed` only if it gets the lock. Alternatively, a busy-lock exit uses a reserved code that `record_exit` ignores.
  - The child's final step under the batch lock requires `state=pending`, `dispatch_started=false` and `incident=null` before it sets `dispatch_started=true`, and otherwise exits.
- Add a matrix test: the old child is paused in preflight, the holder restarts, and the second child loses the lock. Assert the operation stays pending and there is at most one creator invocation.

## Major

**M1. The `launch.sh` restart guard names a function that doesn't exist, says nothing about its return code, and duplicates a guard that is already there.** Lines 417–423.
- There is no `restart_stopped`. The `restart.py` calls are in `factory_auto_resume` (`launch.sh:472`).
- That function already does `[ -z "${batch_release:-}" ] || return 1` at line 475. `--batch-release` is in the argv that `launch.json` stores (`launch.sh:36`, `control_resume.py`), so orphan batch controllers already skip the same-worker restart.
- The return code matters. The caller at `bin/boat-launch-guards.sh:323` treats a 0 return as "resumed": it sets `pending=1` and never calls `guard_retire`. If the implementer reads "returns without producing a restart plan" as `return 0`, every batch worker that reaches DONE is never deleted. No deletion receipt is ever written, so the operation never retires and its concurrency slot is never freed.
- Fix:
  - Name `factory_auto_resume`.
  - Either rely on the existing line-475 guard, or require `return 1` explicitly so control falls through to `guard_retire`.
  - Extend the planned test (line 422) to assert that DONE then leads to `guard_retire`.

## Nits

- **N1.** `key_holder.py:355` still checks `calls >= job['max_calls']` on the batch recovery path. If a manifest omits `max_calls` (which line 263 allows), that line raises `KeyError`, not the refusal it is meant to give. State that the check is skipped for batch jobs or removed.
- **N2.** Add two items to the activation prerequisites (lines 451–457):
  - **Dead case.** A worker that is launched and retired without producing output leaves its case unable to continue. Its fresh ID is used up and there is no successor (line 438).
  - **Existing schema-1 money.** The active batch's `money.json` written by the gate-off `authorize` is schema 1, and the new path always refuses it (line 176). So activation needs a new batch or manifest, not just flipping the gate.
- **N3.** Line 439: "If ACK is added later, it copies…". Say that `collect` writes `ACK.retirement=null` and that `reconcile` does the copy. Otherwise the implementer could read it as `collect` copying the proof, which would break the single-writer rule.

## Heilmeier and scope

- **Heilmeier:** adequate. The doc has a plain objective, states no new cost, covers one increment, and gives offline mid-term and final exams.
- **Scope:** holds.
  - Increment 1 only. `HOLDER_ENABLED` is a false code constant and `DIAGNOSIS_ENABLED` stays false.
  - There is no D dispatcher dependency, no live activity and no legacy booking. Murphy rows 6, 27, 28, 35, 51 and new-batch-service-3 stay open.
  - cb5e2 and 14d35 stay set aside.
  - The legacy public `authorize` is unchanged while the gate is off.

Close B1 and M1, then send it for a fresh review.

## Elephant response
All findings accepted. record_exit now takes the operation lock nonblocking; final creator admission requires pending/unstarted/no incident. Added overlap race regression. Corrected factory_auto_resume and explicit return 1 plus DONE retirement assertion. Clarified ACK retirement single writer, batch call telemetry and activation prerequisites. Fresh review pending.
