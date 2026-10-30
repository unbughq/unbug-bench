**FAIL.** I found two blockers and five majors that should be fixed before merge. The money arithmetic and the source-chain replay logic are sound. What fails is the robustness of the controller wiring, and the shell path has no test behind it.

Mode was REVIEW, read-only. I read the zoom-out and implementation-readiness roles and the standard, then checked diff `d0be3c9..4281f83` against `batch-holder.md` and the referenced batch-service and status obligations. I did not run the tests. I took the passing full-suite evidence as given.

## Blockers

**B1. Any exception in the batch tick kills the whole key holder.** (`factory/key_holder.py:488-511`, called at `:525`)
- `batch_tick()` runs inside the accept loop with no try. An exception in it escapes `while` and ends `serve`.
- Many routine conditions raise there: `reconcile`, `orphaned` and `record_exit` all raise on a corrupt `money.json`, an `_operations` refusal, or a worker or proof mismatch (`batch_holder.py:312, 317, 320`). An `OSError` on the log `open('xb')` raises too.
- When the holder dies it loses its RAM identity. It also stops supervising every legacy job, and orphans of the dispatch child can no longer get a `dispatch_exit` recorded, so they stay pending until the deadline.
- One more case makes this worse. If `reconcile` raises partway through its loop, it has already written `money.json` for earlier operations but not saved `reservations.json`. The same raise then happens on every scan.
- The design expects a fail-closed scan *per operation*. This fails stop for the whole process.
- No test exercises `batch_tick`.
- **Fix:** catch exceptions per operation in reconcile and orphan discovery, and catch around the whole tick. Log a fixed label and carry on. Add a test.

**B2. The shell and socket wiring is not substantiated by any test.**
- `collect.sh` → `batch_holder.py collect` (`collect.sh:9-12, 87-89`): the only test that touches it (`test_control_resume.py:177-186`) swaps `collect.sh` for a double. Nothing proves that `UNBUG_LAUNCH_STATE/collected` and the holder's `home/launches/<id>/collected` resolve to the same place in a real run, or that the R2 environment reaches `r2-presign`.
- `launch.sh` restore with the marker (`launch.sh:192-197, 228-233`): `source` and `restore-check`, and the use of `source_dir` for the card, archive and case key, are never run.
- The checkpoint branch in `batch.bind` when the gate is on (`batch.py:156-163`) is untested. The dispatch test uses a fresh source, so it never reaches `source_directory`.
- The socket routes `launch` and `operation` (`key_holder.py:540-552`) are untested: the reply shape, the wrong-batch refusal, and falling through to the legacy path when the gate is off.
- All three shell-invoked commands load `--policy` from the default `$UNBUG_CONTROL_HOME/policy.json` (`batch_holder.py:589`). `serve` was started with whatever `--policy` path was given (`key_holder.py:766`), and nothing checks that the two are the same file. The convention in `batch-service.md:74` makes it likely, not guaranteed.
- This review was asked to check the actual shell and controller wiring. Right now it is asserted, not tested.
- **Fix:** add one offline integration test that runs `collect.sh` with the marker against the real holder `collect` and a transport double. Add a `launch.sh` restore test, a bind-enabled test and socket route tests. Either pass the policy path through the frozen environment, or check its digest against `policy_sha256`.

## Majors

**M1. Nonblocking locks turn routine contention into a permanent case failure.** (`batch_holder.py:222, 377`)
- `source_directory` takes `LOCK_SH|LOCK_NB`. The design asks for nonblocking only in status (`batch-holder.md:367`).
- The holder's scan takes the exclusive lock about once a second. If `source_directory` collides with it during dispatch preflight (it runs once directly at `:539` and again through `bind` at `:541`), the error hits `except Exception` and the operation becomes `failed/preflight_refused`.
- The same collision inside `launch.sh` after dispatch has started exits before a VM exists. `reconcile` then marks the operation failed.
- In this increment that operation ID is consumed and there is no retry, so the case is lost.
- **Fix:** use a blocking shared lock everywhere except status.

**M2. Transient conditions are recorded as a permanent preflight refusal.** (`batch_holder.py:532, 576-582`)
- `_post` raises `MoneyWait` while *any* incident exists in the batch. A peer's accounting incident therefore fails every reserved but unstarted operation for good.
- Timeouts in `age-keygen` or `boat-call` are treated the same way.
- The design sanctions failing on a preflight refusal, but a batch-wide freeze is not a refusal of this operation.
- **Fix:** keep the operation pending on `MoneyWait` and on transient I/O. Fail it only on a positive refusal.

**M3. A repeat refusal overwrites the stored incident.** (`batch_holder.py:489-498`)
- Re-collecting a refused generation replaces the stored incident under `identity/generation`. A later non-extending output does the same. The new entry carries `reason=invalid_accounting_input`, erasing the original reason (for example `uncovered_total`).
- The design says "A refusal preserves every incident" and treats incident evidence as immutable.
- **Fix:** never replace an existing key.

**M4. A collection failure in the holder now keeps the VM running.** (`collect.sh:87-89` → `guard_retire`, `boat-launch-guards.sh:184-190`)
- An accounting refusal or an R2 failure sets `status=1`. `guard_retire` then retries three times and keeps the VM until its TTL.
- The output bytes are already frozen in `generations/`, and replay re-uploads them, so keeping the VM costs money and adds no evidence.
- The design does not decide this either way. Under the zero-decision rule it needs an explicit choice. Report the publication result separately from collection integrity, and add a test.

**M5. Gaps in the test matrix.**
- **Overlap test** (round 4): `test_preflight_overlap_loser_cannot_fail_owner` holds a lock and calls `record_exit`. It never runs two `dispatch` children and never asserts that only one creator ran.
- **Matrix item 2:** nothing tests multiple created events, a repeated ID, `hasMore` or duplicate inventory, a malformed reservation or UUID, or no retry after a failed preflight through `dispatch` itself.
- **Matrix item 3:**
  - There is no test for a crash after the outbox write and before or during PUT.
  - Nor for a crash between reconcile's `ACK.retirement` write in money and its reservations write.
  - Nor for an interrupted PUT. `test_r2_get_hash_must_match` covers only a corrupt GET.
- **Status:** nothing tests the `failed` phase or the `accounting_refused` → unreadable mapping.

## Nits

- **N1.** `record_exit` stores the exit codes of `resume` children as `dispatch_exit` (`key_holder.py:492-496`) and overwrites any value already there. The design says it is recorded only from the dispatch child's handle. The controller-lock predicate keeps this safe in practice. Track the kind of each child and set the value only once.
- **N2.** `reconcile` sets `incident='creation_unknown'` on operations that are already failed, replacing `preflight_refused` (`batch_holder.py:296-310`). Skip failed operations.
- **N3.** On the money path, `job_config.install` expects a revision bump exactly when `card_total(public) is not None`. `advance_locked` bumps exactly when `facts['total_usd'] is not None`. If those two can ever disagree, the worker refuses with `money_wait`. That fails closed, but nothing asserts they agree.
- **N4.** `resume_controller` passes `{**os.environ}` to `launch.sh` (`batch_holder.py:365`), while the existing legacy resume uses a minimal environment (`key_holder.py:584`). `control_resume` does rebuild the frozen keys, but this still leaks the holder's environment. Mirror the minimal environment.
- **N5.** `_retirement` requires `completedAt` and the other completion fields on `deletion-request.json`. That matches the real guard, which saves the full six-key identity, so this is correct. Comment it so nobody "simplifies" it away.

## What holds

- **Money.** Schema 2 is strict and schema 1 is never migrated; gate-off `authorize` is unchanged (tested). `held_usd` is never reduced. The known floor is a sticky max, the aggregate is `max(hold, floor)`, and an overrun blocks advancement (tested, including a later null ACK). `advance_locked` is the only source writer and appends exactly once. A replay after money is written but before the reservation recovers the same authority (tested).
- **Source replay.** Returning to an earlier source (A-B-A) and historical sources are both refused (tested). The successor's PRE check needs an acknowledged outbox, a matching pointer, the snapshot authority and equal retirement proofs.
- **Publication.** The order is pointer, then money, then outbox acknowledged, then projection. A crash between pointer and ACK shows unreadable and replays correctly (tested). The outbox candidate cannot be overtaken without an incident extension.
- **Retirement.** It needs both deletion receipts with the same ID and target. Markers never substitute (tested). Proofs only go from null to a value.
- **Scope.** `HOLDER_ENABLED=False` is a code constant. There is no diagnosis or legacy booking path, no Murphy row is closed, and cb5e2 and 14d35 are untouched.

**Verdict: FAIL.** Fix B1 and B2. M1–M3 are small, so fix them in the same pass. Then rerun the full suite and get a fresh goldfish review.
## Elephant response

Taken over from the Codex writer (usage exhausted) by a Claude elephant on 2026-10-30. No finding is rejected.

- **B1 fixed.** `key_holder.batch_tick` is now a module function. Exit recording, each scan and each spawn are caught separately, logged by a fixed label, and retried on the next tick. `reconcile` runs each operation through `_reconcile_one`; a raising operation is restored to its pre-scan reservation and money state and every other operation still completes. Tests: `test_batch_tick_never_stops_and_records_only_dispatch_exits`, `test_reconcile_isolates_a_refused_operation`.
- **B2 fixed.** New `ShellWiringTests` run the real `collect.sh`, `transfer.py`, `collection.py` and `bin/r2-presign` as subprocesses, through launch.sh's own `collect_vm` with its R2 environment, and the real launch.sh restore snippet with a real age key. Only the process boundary (gate constant, root, control home, `batch.verify`) and the object store are doubles. Socket routes are now `key_holder.batch_request`, tested for reply shape, replay, wrong batch, extra keys and gate-off fall-through. Bind with the gate on is tested. `serve` refuses a policy path other than `$UNBUG_CONTROL_HOME/policy.json`, and `batch_holder.py collect` refuses unless `UNBUG_LAUNCH_STATE` is that operation's launch directory. Each shell test fails when its wiring is reverted.
- **M1 fixed.** `lookup` and `source_directory` take a blocking shared lock. Test: `test_source_lookup_waits_for_the_holder_scan`.
- **M2 fixed.** `MoneyWait`, timeouts, failed helper commands and `OSError` exit dispatch with `TEMPFAIL` (75); `record_exit` ignores it for an unstarted operation and the holder waits 60 s before the next preflight. Test: `test_transient_preflight_stays_pending`, including a peer's accounting incident.
- **M3 fixed.** Incidents use `setdefault`. Test: `test_repeat_refusal_keeps_original_incident` keeps `uncovered_total` across a second refusal.
- **M4 decided and fixed.** A holder publication refusal no longer retains the worker. `collect.sh` reports it on its own line and keeps its collection status; the verified bytes stay for replay. Holder-driven replay is listed as an activation prerequisite in the design. Test: `test_collect_sh_refused_publication_keeps_collection_status`.
- **M5 fixed.** Added `test_overlapping_dispatch_children_invoke_one_creator` (real `dispatch`, one creator), `test_ambiguous_creation_records_stay_pending`, `test_positive_preflight_refusal_fails_once_and_never_retries` (`hasMore`, duplicate inventory, failed status phase), `test_malformed_reservation_and_identity_refuse`, `test_publication_crash_before_and_during_put_replays`, `test_retirement_crash_between_money_and_reservations_repairs`, `test_r2_interrupted_put_is_a_publication_failure`. `accounting_refused` → unreadable is asserted in the M3 test.
- **Nits.** N1, N2, N4 and N5 fixed. N3 is left open; a disagreement fails closed with `money_wait`.
