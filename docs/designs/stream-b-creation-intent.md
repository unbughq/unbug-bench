# Stream B: preserve uncertain creation across controller death

## Problem and scope

Base: factory-simplify 6f30f8d, fast-forwarded into the assigned stream B branch.
This is the next delayed-cleanup/cumulative-cost prerequisite. It does not finish
that whole increment: public evidence still cannot justify a hard USD 5 envelope.
Legacy ownership/inventory is not small enough to combine without fresh VM
provenance. No workers, paid calls, VM mutations, secret inspection, push, main
changes or merge into factory-simplify. Both activation gates remain false.

The previous change retains reserved money until ordinary finish. But guard_new
writes new.N.pending only after a create returns without an ID. SIGKILL between
submission and that write leaves new.N with no ID and no pending marker.
Resumed guard_exit can then call boat-spend --finish and write complete despite
an uncertain create. Existing provider inventory cannot repair this inference.
This is code-inspected crash exposure, not a newly observed live incident.

Impact: a crash during VM creation must never mark uncertain launch money as settled.
Timeline: one offline implementation, suite and fresh-review cycle.

## Change and what it deletes

On guard_new entry clear id and new_status before any possible return.
Before invoking boat new, exclusively create new.N.pending, fsync the file and
its launch directory. Do not truncate an existing response or overwrite an old
pending marker: refuse the create if either new.N or new.N.pending exists.
Persisting this marker must succeed before any provider invocation. Use an inline
python3 helper with O_CREAT|O_EXCL, os.fsync(file) and os.fsync(directory); each
helper failure explicitly returns failure from guard_new, independent of set -e. It contains
no secrets and is only a local uncertainty marker, not a provider request key.
Keep the existing command, timeout, transport and response file. Set id to a
valid reported ID as soon as parsed, before persistence; keep it on persistence
failure so launch.sh can retire that worker in its existing failure branch.

After the command returns, retain the marker on unknown outcome. For a response
with a valid created ID, flush/fsync new.N and persist the merged IDs via temporary file, fsync, rename
and directory fsync (preserving existing reuse-worker IDs), then unlink the pending marker and fsync the directory again.
The shell must return failure if any persistence step fails, even when called
without set -e. Nonzero provider exit with a recorded ID still clears pending
only after persistence, then follows existing retirement and error handling.
The marker means creation identity is uncertain; known IDs remain protected by
the existing deletion/collection protocol. In every guard_exit, live or resumed, reuse the same resolution rule for each new.N.pending:
read a valid created ID in new.N, persist the response and merged IDs, then
unlink/fsync the marker. Missing or malformed identity keeps pending. A live
shell runs its exit trap after the foreground create returns and waits for its
background jobs before reconciliation. A resumed shell runs under controller.lock
reacquired by control_resume; the former shell and boat-call inherit that fd, so a
surviving boat-call must exit before resume can own the lock. The provider subprocess
itself uses close_fds: if boat-call is also SIGKILLed while its provider survives,
the lock does not establish provider quiescence. Unknown output stays pending;
known output follows the existing reported-ID semantics. Detached provider
completion/CLI multiplicity remains unqualified and blocks activation. This is
not a definitive all-provider-outcomes cleanup proof. Failed ID computation or
persistence prevents finish on that exit. A failure only in directory fsync after
unlink need not permanently block finish: response and IDs were already durable;
a crash restoring the marker can only cause idempotent re-resolution next time.
The helper still reports errors; id remains available for retirement.

Reuse the existing marker name, finish guard and batch_holder._reconcile_one
new.* ownership test. A helper replaces all three in-place cp rewrites of merged
IDs (guard_new, guard_exit and launch.sh resume) with atomic durable replacement.
Compute before writing: the result is a superset of existing ids. A read failure
or non-object JSON event must not replace ids or permit finish. Ignore malformed
JSON lines as today (progress text is allowed), but never clear pending without a
valid created event. Read response files matching new.[0-9]+ only, not pending
paths. Any existing pending path, including directory or dangling symlink, counts
as unfinished (-e or -L). A marker that is not a regular file is never resolved.
On merge failure guard_exit retains the existing ids for retirement, marks cleanup
failed and blocks finish. launch.sh resume must propagate merge failure. For
nonpersistent callers, retain the temporary state if unfinished or cleanup failed;
delete it only after successful cleanup, so uncertain evidence is not discarded. Delete the late touch, which
misses death in the provider call. No new journal, supervisor, request adapter,
manual clearing switch or inventory-based non-creation proof. No automatic
replay, even when the provider says a rejected start cannot run later. Historical
markerless new.N files remain an explicit deployment-inventory blocker; this
change cannot retroactively prove their outcome. The future supervisor must
resolve them separately. Guard IDs currently recognizes reported IDs without
proving the CLI creates at most one worker; that qualification remains open.

Durability applies to the existing local control filesystem and fsync contract,
not hardware destruction. No parent-directory creation durability is claimed.
All changes affect future execution, including non-batch guard callers; deployment
remains separately gated. No security property or section 4 rule changes.

## Cumulative cost qualification

Retained public pages in docs/reports/stream-b-cost-contract-20261031 have their
URLs, UTC fetch timestamps and SHA256 in sources.json. These extend the prior
stream-b-provider-contract-20261031 evidence, not live account qualification.

- pricing.md confirms default USD 0.036/hour, per-second billing, automatic
  snapshot retention included, and no network egress charge. Paid saved snapshots
  are a distinct feature; the workload must not create them.
- limits.md gives extra starts up to USD 0.07 each. Rate-refused starts are not
  queued. This does not resolve a lost success reply or bound CLI internal retries.
- stop.md says refused-stop billing pauses, but auto-stop use can restart its
  meter. It specifies eventual forced stop after three days of failed saves,
  not a hard billing upper bound for every stop failure/delay. The no-snapshot
  workload also has different stop mechanics. Do not substitute the normal
  approximately five-second timer delay for a guaranteed maximum.
- member-caps.md caps organization-billed machine time per billing window, not
  every infrastructure charge; its stop timing is approximate. It does not prove
  a cumulative batch cap covering starts and concurrent unrelated work.
- ai-credentials.md documents account/profile proxy switches and ongoing daily
  charges. --no-env alone is not evidence that no proxy charge is attributable.

The desired inequality is settled upper bounds + unresolved full holds + next
worst-case hold <= USD 5. Each worst-case hold needs a bounded number of starts,
USD 0.07 per start, a justified billable-seconds ceiling at the pinned rate, and
any proxy/storage charges. Egress is now documented as zero. No balance delta
is attributed to this batch. Use the selected BOAT_TYPE rate, not always default: small/default/large/xlarge
are USD 0.018/0.036/0.072/0.200 per hour. The default cloud is Hetzner: the shared
crash fix applies there too, but these Boat cost claims do not.
Current --max-spend remains a per-launch estimate;
there is still no cumulative infrastructure ledger. Do not implement a guessed
bound or enable admission. Remaining contract work: exceptional billable lifetime,
CLI multiplicity or a reviewed single-request API adapter, and runtime proof of
no paid snapshot/proxy use. A later deployment must revalidate rates and scope.

## Tests and acceptance

Use tests/factory/test_control_resume.py's real control_resume.py exec path for
controller lock/crash tests, extending its existing local transport harness.
Copy the real boat-call/processes wrappers for the new creation tests; the fake
provider runs in the session established by processes.run. The controller and
boat-call remain in the controller group. Use isolation-timeouts/created.json,
billing.json and list.json as saved provider artifacts. Deletion operation fields
in test_control_resume's existing harness are authored transport responses, not
saved live receipts; use them, bound to the saved created ID, and exercise the
real guard_delete_receipt verifier. Do not claim live deletion qualification.
Authored timing is fault injection. Tests must:

1. Start creation through real control_resume exec into the launcher, then kill
   the controller group and the fake provider group separately before any ID.
   Resume through control_resume in fresh processes. Assert pending persists,
   no finish/complete, unchanged reserved hold and no duplicate creation. Transfer
   this crash directory to test_batch_holder's existing operation fixture binding;
   with free locks holder.reconcile stays pending/creation_unknown. record_child
   increments failures exactly once for an unsuccessful resume.
2. Kill only the controller PID; release the surviving fake provider to emit the
   saved created event and exit. Assert early resume refuses the inherited lock;
   later resume clears pending and reaches finish only through collection/deletion.
   Repeat resume with no new create or finish. A provider-only orphan after killing
   boat-call remains the declared residual, not proven quiescent by this test.
3. In a bare-shell guard harness without UNBUG_LAUNCH_STATE, send SIGTERM only to
   the controller while new is in flight, then let the provider return. On a valid
   saved event assert IDs persisted, pending cleared, deletion receipt verified,
   finish reached and temporary state removed. Without an ID assert no finish and
   retained pending evidence. The bare shell is for signal/guard behavior only;
   lock inheritance is tested through the real controller in tests 1/2.
4. In test_control_resume, replay the saved event with return status 0 and 9.
   Both persist ID and clear pending. Then force serial 2 begin failure with a
   directory at new.2.pending; assert id is empty immediately after guard_new
   (testing the actual value consumed by launch.sh, not a copied loop). Run
   guard_exit; serial 1 remains in ids, no finish/complete. Re-enter a serial with
   existing response/marker and assert no truncation or replay. Inject unreadable
   response (directory at new.2) and prove merged IDs are not replaced on failure.
5. Strengthen the existing unknown-response test so the transport checks pending
   during the call. Retain the existing shared-guard and holder regressions.

Run the full suite exactly as required, to a unique log; commit a record with
command, timestamps, exit status, script count and SHA256. Fresh design review
uses zoom_out, design_critic and implementation_readiness; fresh diff review
uses zoom_out and implementation_readiness. Never self-verify blocker fixes.

No Murphy rows close. Rows 6, 27, 28, 29, 35, 51 and open batch-service rows stay open;
these tests prove local crash accounting only. No new live failure was observed.
Cost/time: one offline code/test/review cycle plus unauthenticated documentation
reads. Provider clarification, if needed, is later authorized parent work.
Remaining increments: finish delayed cleanup and cumulative cost proof; legacy
ownership and deployment inventory; router provisioning and cheap profile;
reviewed policy/release pins; separate account-2 attribution.

## Implementation clarifications after passing review 3

Every persistence error blocks finish on that exit, including post-unlink fsync
errors. The latter need not permanently block later finish: identity is already
durable. A guard_new error can therefore retire a successfully created worker.
Keeping id lets the caller attempt retirement; Boat's ownership check still
refuses deletion until ids persistence succeeds. Test that failure explicitly.
A marker written just before a signal but before submission is a conservative
false positive; future reconciliation must resolve it, never inventory subtraction.
Saved pretty-printed created.json is serialized as one JSON line for CLI replay.
Admission also queries billing, so finished_at and ledger status prove settlement,
not a counter of billing requests. Bare guard tests premark collected to isolate
creation/retirement, then use authored deletion responses with the real verifier.
Resume recovery asserts the existing missing-start error route to guard_exit;
it does not reset the TTL by assigning a fresh start time.

## Diff-review settlement clarification

The new unfinished condition applies only to guard_ids computation/persistence
failure. Keep the baseline finish semantics for orphan-list errors and TTL-hook
errors once every known worker is marked deleted and no creation is pending.
Those errors still set cleanup_failed and a nonzero exit. A transient list error
must not introduce a permanent reservation leak for a nonpersistent caller.

An isolated regression retires the saved created ID with the real receipt
verifier, leaves no pending marker, then makes new.9 unreadable. Only the merge
failure can block finish/complete. A non-object JSON line is tested independently;
such evidence corruption blocks finish indefinitely until reconciled, including
late output from the already-declared detached-provider residual. Another test
uses the actual Boat ownership check to refuse a reported ID absent from ids.
Direct success, dangling marker, unrelated-list-failure compatibility and real
resume failure propagation are now covered in test_control_resume as well.

Unknown empty-ID resumes currently exit 0 through guard_exit without complete;
assert that route and pass the real exit code to holder.record_child, which counts
resume failure by the missing complete marker rather than exit status. No new
resume exit semantics are introduced. The fsync order is reviewed in code;
the process-crash tests do not simulate storage power loss. Subsequent suite
records identify both the tested HEAD and its git tree.
