**FAIL.** `docs/designs/batch-holder.md` gets the direction and the safety rules right: PID alone means pending, an uncertain create is never retried, no ACK without a matching pointer, schema1 money is not migrated, cb5e2/14d35 stay set aside, and `DIAGNOSIS_ENABLED` stays off. But it is not ready to implement. It leaves the schemas, the order of the holder steps, the file list and two founder decisions for the implementer to work out, and `batch-service.md` lines 122 and 1092 say this addendum must settle exactly those.

Reviewed against `heilmeier-standard.md` and `implementation-readiness-standard.md`, using the zoom-out, design-critic and implementation-readiness roles. No writes.

## Blockers

**B1. No file list, no phases, no test list.** Lines 14 and 104–122 name only "a host-only batch_holder module".
- Missing files include `factory/batch_holder.py` and its test, `key_holder.py`, `batch.py` (bind), `launch.sh`, `job_config.py`, `batch_money.py`, `batch_service.py`, `batch_status.py`, `run.py` (see B5), and `launch_manifest.py`.
- `key_holder.serve` refuses if `fingerprint(ROOT) != policy['code_sha256']`. A new host module it imports has to join `TRUSTED_FILES`/`HOST_FILES` (`launch_manifest.py:40-49`), or the holder runs code that isn't pinned.
- One increment covers the async holder, the journal operations map, money schema2 with ACK and freeze, R2 publication, restore through the pointer, the installer, and removing the call cap. Nothing breaks this into stages that each build and test.
- Suggested split: (1a) operations map, receipt reconciliation and status overlay; (1b) collection, publication, ACK and money schema2; (1c) pointer restore and the scoped key.

**B2. The schemas are only described in prose** (lines 37–46, 57–60, 68–81).
- **Operations map:** no exact key names, types, map key format, or how "at most one unresolved per owner and source" is enforced.
- **Journal schema:** `_load` (`batch_service.py:97`) demands an exact key set. The doc doesn't say whether `operations` is added to schema1 or bumps the schema.
- **Money schema2:** no field names for authority, held amount, `previous`, the ACK record, source history, the incident record, the batch-wide freeze record or the overrun flag.
- **Publication progress:** no record format and no location (journal, outbox or money).
- **UUID5:** no namespace constant, name encoding, or string for a null fresh source.
- `batch-service.md:1092` requires all of this to be "specified and reviewed" before wiring.

**B3. The async holder protocol is not defined** (lines 16–22).
- What the socket handler writes before it replies, and in what format.
- Which program the child runs: a new Python entry, or `launch.sh` directly.
- How the checks that currently run in order in the accept loop stay serialized once they move out: concurrency (`batch_live_reservations`), `authorize`, `configuration`, Boat inventory, `consumed`.
- `reservations.json` lives under `RUNTIME` and is written by `save_receipts` outside the batch lock. The doc says the batch lock covers "all state transitions and reservations" and that the journal holds operations. It never says which store is written first, which one wins, or how a crash between the two writes is repaired.
- The return shape of `batch.launch` and the name of the operation-lookup request are not defined.

**B4. A failed operation can never be relaunched** (lines 18–19, 27–28). The ID is UUID5 of batch/job/source/release, and replay "never spawns again". So a launch proven to have failed before creating a worker would collide with its own retry and could never run again. `batch-service.md:59-60` allows retries after that proof, and lines 128–130 keep per-reason relaunch counts. The doc has to say how a retry gets a distinct identity, or that relaunch is outside this increment.

**B5. The founder's "no cumulative call cap" decision can't be built as written** (lines 100–101).
- Dropping the argv cap in bind is not enough: `run.py:2843` defaults `--max-total-calls` to 5000, and on resume `run.py:2916-2919` falls back to the saved `recovery_config.max_total_calls` (1000).
- `key_holder.current_generation:355` refuses when `calls >= job['max_calls']` for batch jobs.
- `check_manifest` (`batch_money.py:54`) and `policy_load` (`key_holder.py:148`) both require `max_calls`.
- `batch-service.md:111` says "max_calls stays". The doc needs to say explicitly that it overrides that, and specify the `run.py` behaviour for new-schema batch config and what happens to the manifest field.

**B6. The scoped control-key restore is not fully specified and has no off switch** (lines 96–100).
- `batch-service.md:122` requires the *exact* control-restore predicate. The doc gives one sentence: "source/ACK/retirement/config predicates pass". That isn't a list of checks.
- The VM's holder and resume timer are active (`batch-service.md:488`). Code that relaxes the refusal at `key_holder.py` (`control_identity and job['mode'] != 'new'`) becomes a live authority change on the next release, which contradicts "no live activation".
- Either list every check and keep it gated off by default until activation, or move it to a later increment.

## Major

**M1. Retirement proof could be wrongly accepted** (lines 29–31).
- Name the artifact: the guard's `<spend>.deletions/<worker>/deletion-completion.json`. Its `id` must equal `deletion-request.json`'s, `targetId` must be the recorded worker, `kind` sandbox, `status`/`stage` completed, `completedAt` timezone-aware. The worker must be in that launch's `ids`.
- Explicitly exclude `.deleted` and `.parked`: `boat-launch-guards.sh:197` touches `.deleted` on the park path without any deletion.

**M2. The "failed" predicate is underspecified** (line 27).
- Define "controller has exited": `controller.lock` taken with a non-blocking flock, plus the expected launch-directory state.
- Say whether a child that crashed before `launches/<id>/launch.json` existed counts as failed or pending.
- Say that more than one `created` event in a `new.N` file stays pending.

**M3. The doc silently replaces the journal format in `batch-service.md:43-48`.** That format is entries keyed by case/`fresh` with `not_before`, `relaunches`, `credit_topups_consumed` and `last_error`. Line 37 swaps it for a separate operations map and drops those fields without saying so. State the replacement and what is deferred.

**M4. The legacy-money wording invites building a migration** (lines 70–71). "Without a complete host operation history it refuses" suggests a history proof might allow migration. No pre-schema host operation history exists. Under the founder's retire-by-default decision, say flatly that schema1 money rows refuse in this increment and have no mapping path.

**M5. Publication is not pinned down** (lines 52–56).
- The transport isn't named (`r2_upload.py`, `bin/r2-presign`, or `transfer.py`), and neither is the offline R2 test double.
- The object key `generations/<case>/<generation>/<filename>` conflicts with `batch-service.md:188` (`.../archive.age`). Pick one.
- The host collection command has no name or entrypoint.

**M6. The status mapping is incomplete** (lines 41–46 vs `status.md:14-21, 72, 78, 137-145`).
- Map each operation state to a status row exactly: launched → running with `worker_id`, which drives the progress `cat` and the "worker gone" rule; pending and failed with `pending_since`, which drives "launch stuck".
- Define "no new card collected" relative to an operation.
- Status must read only state the journal has already persisted, under its shared non-blocking lock, and never reconcile launch directories itself. The doc doesn't say who persists the launched transition (service tick or holder).

## Nits

- **Heilmeier:** there's no plain-language objective (lines 12–22 are dense jargon), no timeline, and no explicit mid-term or final exam.
- **Naming:** line 18 says "source"; `batch-service.md:124` says "generation" for the same UUID5 input. Pick one.
- **Paid-only dollar caps:** consistent with line 102. No finding.

## What already holds

Increment1 scope is clear: no dispatch, live run, legacy booking, cross-batch import or worker creation, and no Murphy row closed. No D dispatcher dependency was found. The rules that keep authority from being inferred where no inference is safe are correct.

Close B1–B6 and M1–M6, then send it for a fresh review.

## Elephant response
All B1–B6 and M1–M6 accepted. Added an exact implementation contract covering files, phases, schemas, protocol ordering, deferred positive-failure retries, explicit activation gate, retirement predicates, publication transport, status mapping and call-cap behavior. No findings rejected. Fresh review pending.
