# Holder, ACK and source integration — increment 1

Baseline d0be3c9. Read ENGINEERING.md, batch-service.md (especially the
increment2b.2 host composition), status.md, and interfaces.md section 8.
This increment implements the host seam. It does not enable diagnosis dispatch,
retire the legacy inventory, run a live practice case, or import across batches.
The default disposition of pre-schema cases is retire, never resume. cb5e2 and
14d35 remain set aside. No legacy booking occurs here.

## Problem, deletion, tests and Murphy rows

The holder cannot connect live reservations to status or safely advance a source.
This replaces batch flat-file restore selection and cumulative call admission
with one operation-bound publication/ACK/source path. It adds no alternative
launcher. Tests below use saved cards, ciphertext and real creation records,
with authored bindings explicitly labelled. No real lifecycle evidence or
Murphy closure is claimed. Rows 6,27,28,35,51 and new-batch-service-3 stay open
until practice qualification. No cost or live deployment in this increment.
Paid-only dollar ceilings and free-route token bounds remain router-owned.

## Implementation contract

Plain objective: status must show the worker that the holder really owns. Once
its output is safely stored and its worker is deleted, the holder can continue
from that exact output without losing the money history. Expected work is one
implementation/review increment. Mid-term exam: offline lifecycle and crash
replay tests. Final exam here: full offline suite plus fresh diff review; the
live practice exam and activation remain separate tasks.

### Files and order

1. factory/batch_holder.py owns host operation validation, reserve/reconcile,
   publish/ACK and source preparation. tests/factory/test_batch_holder.py tests
   those paths. factory/batch_service.py extends its shared journal validator;
   factory/batch_status.py reads the persisted lifecycle overlay. Its existing
   tests gain overlay regressions. No cloud reads in status reconciliation.
2. factory/batch_money.py adds strict schema2 read/write, ACK and source history;
   factory/batch_accounting.py remains the pure consumer. Extend
   tests/factory/test_batch_money.py and test_batch_accounting.py only where their
   public contracts change. Integration tests use actual budget API results.
3. factory/key_holder.py routes enabled batch requests to reserve, launches the
   batch_holder.py dispatch child, and periodically reconciles its receipts.
   factory/control_resume.py continues owning shell controller locks and adds
   UNBUG_BATCH_OPERATION to ENVIRONMENT so orphan resumes preserve the binding.
   factory/collect.sh and launch.sh route batch collection to the launch-owned
   directory and invoke the host publication command. Existing transfer.py stays.
   factory/batch.py bind and launch.sh use the immutable source resolver.
4. factory/job_config.py advances checkpoint money/history; factory/run_artifacts.py
   emits the public job_money binding at seal. factory/restore_ledger.py adds the authenticated covered-null import described
   below. factory/run.py removes cumulative
   call metadata on authenticated batch runs (legacy CLI parsing remains).
   tests/factory/test_batch_launch.py and installer tests cover restore and caps.
5. factory/launch_manifest.py pins batch_holder.py in TRUSTED_FILES (and therefore
   HOST_FILES). Add the module to release inventories through the existing lists,
   never edit a previously generated qualified release. Update batch-service.md
   and status.md to point to this superseding holder contract.

Each phase gets focused tests after implementation, then the required full suite.
These are work phases, not separate handbacks or permission gates.

### Gate and protocol

HOLDER_ENABLED=False is a code constant in batch_holder.py. No environment
variable, policy field or socket request can enable it. Production routes retain
the existing fresh-only behavior while false. Integration tests patch the
constant. Enabling it requires the later reviewed activation/practice task.
All new public host commands and the scoped-key exception check this gate.
DIAGNOSIS_ENABLED remains independently false. This increment grants no diagnosis
or replacement dispatch, even when the holder seam is enabled in tests.

New enabled socket launch accepts exactly {op:'launch',batch,job,checkpoint},
checkpoint null or a lower-case SHA256. batch.launch already sends these keys.
Reply is {operation_id,launch_id,state,worker_id}; no PID counts as acceptance.
Lookup accepts exactly {op:'operation',batch,operation_id} and returns that same
shape without mutations. Wrong batch, malformed requests or unknown operations
refuse with fixed labels. The child entry is
python3 -B factory/batch_holder.py dispatch --operation UUID --policy PATH.
Identity is supplied only on stdin, using the holder's existing RAM key.

New reservations live at batches/<batch>/reservations.json, separate from the
legacy RUNTIME/reservations.json list. Exact top-level fields:
{schema:1,batch,manifest_sha256,operations:{operation_id:record}}.
This is authoritative for new operations; the journal map is a projection.
All writes use batch_money.locked. No new path writes the legacy list.
Reserve checks pinned manifest, deadline, frozen source/ACK, money freeze and
concurrency, obtains authority and freezes config, then writes the operation,
then projects journal, then replies. Socket handler spawns dispatch only after
reservation. A crash before reservation can retain a money hold; replay obtains
the identical grant. A crash after reservation is repaired by the periodic
holder scan, which projects the map and schedules an unstarted dispatch child.
No cloud I/O occurs under the batch lock or in the accept loop. Release/policy
verification is done at holder startup and by the dispatch child; reserve uses the validated startup policy and checks the pinned manifest bytes
on disk. Existing schema1 money always refuses in the new path.

Dispatch takes a distinct nonblocking operations/<operation_id>.lock before
checking/starting anything. It freezes argv/environment in the reservation before
starting the existing launch.sh. Its reserved launch_id is passed as today.
The shell's existing controller.lock prevents orphan duplicates. The operation
records dispatch_started before Popen: lost Popen replies stay pending; a scan
must not restart initialization without positive precreation failure proof.
The existing --resume-launches path resumes initialized orphan controllers with
monitor.sh and matching launch.json, not another provisioning attempt.
Reconciliation in the holder's periodic scan writes reservations first then
journal. Status only reads the shared-lock journal projection.

UUID5 uses uuid.NAMESPACE_URL and the UTF-8 string
json.dumps([batch,job,source_generation,release_sha256],separators=(',',':')).
Fresh source_generation is JSON null. operation_id is canonical UUID5 text;
launch_id is UUID4 hex. Retry of a positively failed creation is DEFERRED in
this increment: lookup/replay returns failed, never spawns a second attempt.
The later dispatcher adds reviewed per-reason retries. This explicitly narrows
the retry promise of batch-service.md lines 59–60, not uncertain-create safety.

### Exact journal and operation schema

Journal stays schema1. It accepts either its existing exact top-level keys, or
those keys plus operations. Missing operations means {}, never inferred launches.
New writers include operations. Existing collected entries remain unchanged.
This supersedes batch-service.md's proposed fresh entries and optional umbrella
fields; delayed queue timing, credit top-ups and retry counters are deferred.
operations is keyed by canonical operation_id. Each value has exactly:
{operation_id,launch_id,job,case,source_generation,release_sha256,config_sha256,
 authority,state,pending_since,worker_id,dispatch_started,dispatch_exit,output_generation,
 retirement,launch,incident}.
job/case must resolve to the manifest root (derived dispatch stays disabled).
source/output are null or SHA256; release equals the policy release in producer
validation; config is SHA256. authority is the validated nine-field money channel.
launch is null before dispatch, then exactly {argv:list[str],environment:dict}
with only control_resume.ENVIRONMENT keys including UNBUG_BATCH_OPERATION, the canonical public operation UUID.
state is pending/launched/failed. pending_since is ISO UTC. worker_id is null or
[A-Za-z0-9_-]+. dispatch_started is a strict boolean; retirement is null or the exact receipt
hash object defined for ACK.retirement below. dispatch_exit is null or an
integer exit code (not bool), recorded only by the holder reaping its actual
child Popen handle; a lost handle after restart leaves null and never infers exit. incident is null
or a fixed label (creation_unknown, accounting_refused, legacy_retire,
preflight_refused).
Only pending may lack worker ownership; launched requires worker_id. failed
requires worker_id null, output null, retirement null. output requires launched.
Non-null retirement requires a worker; it never implies a collected output.
At most one nonretired/nonfailed operation per case is accepted. All operations
for an owner form a chain: each successor's source equals its predecessor's
ACKed output; the latest authority's source selects the current operation.

Source transitions do not alter old operation rows. Journal validation checks
identity, types, channel/source agreement and duplicate unresolved ownership;
producer reconciliation additionally checks the frozen config and controller.
Status selects the unique nonretired operation, or the latest operation whose
output matches current. With no operation it uses the existing collected view.
pending -> pending; failed -> failed (both carry pending_since).
launched with output_generation null -> running with worker_id and prior card;
launched with output_generation equal current generation -> stopped with that
card. A newer pending/launched successor overrides the predecessor's stopped
view. 'No new card' means no published output bound to that exact operation.

A created event is read from the controller's new.N JSON lines and cross-checked
with its ids file. Exactly one distinct created worker is required; more than
one created event, even with repeated ID, or contradictory ids stays pending.
A failed state requires dispatch child exit recorded by the holder, a present
matching launch.json, a nonblocking exclusive controller.lock, and no new.N
file or worker IDs. Missing launch.json, lost process status or uncertain create
stays pending. PID existence/absence alone is never proof.

Retirement is proved only by the controller's spend_file (read as a validated
path from its frozen monitor metadata) and
<spend>.deletions/<worker>/deletion-request.json plus deletion-completion.json.
Both have the same nonempty id and targetId=owned worker, kind=sandbox. Completion
has status=stage=completed and timezone-aware completedAt. Worker must occur in
that launch's ids/created record. .deleted, .parked, .retired, complete, inventory
absence and controller exit never substitute. Persist the exact receipt hashes
in the money ACK's retirement field before admitting a successor.

### Exact money and publication state

Money schema2 top-level keys are schema,batch,manifest_sha256,money_limit_usd,
batch_deadline,jobs,incidents. Header bindings match the manifest. An existing
schema1 file always refuses; there is no automatic migration path.
Each jobs[name] has exactly authority,held_usd,known_floor_usd,previous,acks,sources,overrun.
held_usd is canonical money, initially requested_total_usd and never reduced here.
known_floor_usd is canonical money, initially zero, and is max(old floor, T)
on each known-total ACK; a null ACK never lowers it.
previous={total_usd:nullable canonical money,estimated:{UUID4:canonical money}}.
acks is keyed by output generation. sources is an ordered list starting [null];
overrun is bool. authority follows the existing exact nine-field channel schema.
Each ACK is {operation_id,generation,manifest_sha256,authority,previous,facts,
 retirement}; facts is collection_facts' exact returned object; previous records
the input facts. retirement is null until verified, then
{worker_id,request_sha256,completion_sha256}. Same generation replay returns the
saved ACK and never recomputes the previous estimate map. ACKs count the full
known total even over hold. Aggregate is sum(max(held_usd,known_floor_usd)).
Any nonempty incidents map freezes all new admission; replay/collection remain
available. An owner with overrun cannot advance authority.

incidents is keyed by operation_id+'/'+generation, each value exactly
{operation_id,generation,manifest_sha256,reason}, reason a fixed accounting refusal
label. Evidence is the immutable snapshot. No incident can clear by timeout,
manual boolean or unrelated owner ACK. Automatic clearing requires later output
from the same operation with exact authority, and an extension of every refused
ledger: all earlier events appear unchanged in order, all earlier reservation
identities retain their immutable fields, and all earlier unpriced invocation
identities are either still present or settled by the real budget API. Reject
legacy/unkeyed ambiguous markers. Each previously estimated reservation may
settle only with the validated D decrease record; all others retain state or
advance pending->estimated/settled. Then run collection_facts against saved
previous and recompute aggregate. A refusal preserves every incident. Known
overrun remains counted and owner-blocking even after accounting freeze clears.

Outbox is batches/<batch>/outbox/<operation_id>.json with exact keys
{schema:1,operation_id,generation,manifest_sha256,state}; state=pending/acknowledged.
It names one candidate. A new candidate cannot overtake an unACKed candidate,
except an authentic evidence-extension reconciliation of its recorded incident.
A completed ACK can be republished idempotently. Old ACK replay never rolls back
the pointer. New candidate must belong to the current operation; historical
operation output refuses once source advanced. Persist candidate, upload all members and manifest, then reacquire the batch
lock and revalidate operation/candidate. Compute collection_facts and incident
reconciliation BEFORE changing the pointer. A refusal atomically saves incidents
and projects accounting_refused, leaving the prior pointer unchanged. On success,
write/re-read current pointer, atomically write ACK and incident changes in money,
then mark outbox acknowledged and project output.
Crash repair always resumes the saved candidate. No per-file uploaded flag is
trusted: replay PUT/GET verifies the complete set again.

The command is batch_holder.py collect --operation UUID --policy PATH. It reads
launches/<launch_id>/collected, not an arbitrary directory argument. collect.sh
uses that directory for batch operations (no flat writes) and calls the command
after collection verification. Publication uses bin/r2-presign GET/PUT in memory
and Python urllib streaming HTTP with finite timeouts; errors are fixed labels.
The transport takes an object key and a local file, streams PUT, GETs and hashes.
Tests use an in-memory object-store double only for transport, with corrupt GET
and interrupted PUT cases. Retained ciphertext/card verification stays real.
Object keys are generations/<case>/<generation>/<filename>, including archive's
original filename. This supersedes the archive.age alias in batch-service.md.

### Exact resume predicate and worker update

Scoped-key restore requires ALL: HOLDER_ENABLED; manifest-bound root job;
recipient equals manifest.restore_recipient; valid current pointer; matching
immutable snapshot and complete saved publication; saved ACK for its generation
with exact operation/config/authority binding; completed retirement receipt;
no batch incident; no owner overrun; owner source-history excludes output;
current authority source equals predecessor input; deadline still future.
No worker-supplied grant, arbitrary case path, legacy case or derived owner
satisfies this predicate. batch.bind and launch.sh both call this resolver;
the holder cannot bypass it. The shell uses the returned immutable directory
for card/archive/key, never a flat-file mtime. Config is frozen only after money
source advancement. Resolver replay accepts the already-advanced source only
for the same reserved successor operation. Founder identity behavior is unchanged.

Known-total source advances revision by one; unknown keeps it exactly, preserving
full committed amount. Reservation/batch/job/case/deadline never change. Sources
append exactly once; replay repairs config/projections without another append.
Before D admission, job_config.install checks the authenticated restore receipt
written by restore_ledger.install names incoming source, saved authority matches
predecessor, and history has no return to an earlier source. Same-revision source
advance additionally requires null total on the restored public card and equal
commitment. History key includes reservation/revision/source, so same revision
has distinct transitions. Persist history before saved money; replay repairs
that write only for the exact recorded old/new/config tuple.
RunArtifacts.seal copies c.job_money to card.job_money before embedding the card.
Missing binding is legacy_retire. A batch legacy card receives no money ACK,
source grant or diagnosis dispatch in this increment.

This addendum overrides 'max_calls stays' in batch-service.md. New manifest jobs
may omit max_calls; existing positive integer max_calls is accepted as historical
metadata only. bind removes both --max-total-calls forms and --max-cost forms.
current_generation never tests a batch's cumulative calls against max_calls.
policy_load and check_manifest no longer require that field for batch jobs. run.py leaves the CLI
option available for legacy/exam compatibility, but authenticated batch config
removes max_total_calls from the new recovery_config; model_runtime/budget already
skip cumulative enforcement for factory jobs. Per-invocation max_role_calls and
run-exam limits are unchanged. No zero or infinity sentinel is substituted.

## Transaction and launch sequence (round 2 clarifications)

All round2 blockers and major findings are accepted. The following refines the
steps above; implementations must use these helper boundaries.

- batch_money.load_locked(directory,record,manifest_sha) validates/returns schema2.
- batch_money.authorize_locked(state,record,name,source_generation) issues/replays
  only fresh or already-current authority, mutating state in memory, never locking
  or writing. The existing public authorize remains schema1 and unchanged while the gate
  is off; only batch_holder.reserve uses these schema2 helpers. No old wrapper
  is redirected to them. Test existing gate-off authority replay and schema1
  bytes remain unchanged by calling legacy authorize and gate-off batch launch.
- batch_money.advance_locked(state,record,name,source_generation,ack) is the ONLY
  source writer: validates pre-advance predicates, appends source once, changes
  revision iff ACK total is known, mutates in memory. It does not write a config.
- batch_holder.reserve(policy,root,home,name,source_generation) acquires exactly
  one batch lock. Under it: load reservations/journal/money; validate freeze,
  deadline and current ownership; check pre-advance source; authorize or advance;
  persist money; freeze immutable config; write authoritative reservation; project
  journal. It never calls public authorize, collect or another lock-taking helper.
- batch_service.collect remains its own lock-taking immutable ingestion API.
  The host collection command calls it BEFORE taking the ACK critical section.
  That section rechecks its returned immutable entry against the operation.

Concurrency counts operations with state in {pending,launched} and retirement=null
in batch reservations, not the legacy receipt list. This count and the per-owner
check occur in the same critical section as grant and operation creation. No
source advancement if a predecessor isn't positively retired. A failed operation
is still a consumed deterministic ID, so same-source replay returns failed.

A money-write-before-reservation crash is recovered using sources and ACK lineage:
if requested source is already the current source and there is no matching
operation, reserve recreates its deterministic ID/config from that exact current
authority, provided the predecessor ACK/retirement still match. It does not bump
revision or append again. Fresh grant without operation is recovered identically.
An old request whose source differs from current authority refuses even if its
old operation exists. Operation lookup remains available for history.

bind is pure and NEVER changes money. Enabled key_holder bypasses its legacy
pre-bind branch: it calls reserve directly, then starts dispatch. Dispatch calls
batch.bind only after the successor reservation exists. The pure resolver has
exactly two modes:
PRE: current authority source == predecessor input, requested generation == its
ACKed output, output absent from sources, predecessor retired, no freeze/overrun,
publication/pointer/ACK/config bindings match, deadline future.
POST: operation_id exists and is the deterministic ID for requested source;
operation.authority == current money authority; current source == requested
source == sources[-1]; preceding source/ACK/retirement match (or fresh null);
frozen config equals operation authority; publication and pointer still agree;
no freeze/overrun and deadline future. Both reject foreign/legacy/derived cases.
PRE is only used inside reserve; POST is used by bind and launch.sh, which receive
the reserved operation ID through a public environment variable. No mutation is
performed by either resolver mode. HISTORICAL source replay is always refused.

Child preflight, in order: load and fingerprint policy/release; validate POST
reservation/config; derive approved account labels by decrypting the existing
credential bundle with stdin identity (existing secret_labels helper); choose
accounts with launch_accounts and freeze only public labels; fetch bounded Boat
inventory and refuse incomplete/duplicate/foreign ownership; revalidate POST
under batch lock; freeze argv/environment; mark dispatch_started=true under lock;
start launch.sh with reserved launch_id and identity on stdin. No legacy
attest_launch/TTL/additional-attempt path is used for these exact batch requests.
No caller overrides are accepted. Legacy request paths remain unchanged.

Before dispatch_started=true, a failed preflight writes state=failed and
incident=preflight_refused while holding operations/<id>.lock AND the batch lock.
That is positive proof that this operation never invoked the creator; there is
no launch.json requirement for this one path. After dispatch_started=true,
failures stay pending unless holder-recorded dispatch_exit and the earlier
matching-launch.json/no-new.N/controller-lock predicate prove no creation.
The scan spawns only pending operations with dispatch_started=false and
 dispatch_exit=null and incident=null, and never duplicates its own live child.
The child operation lock prevents cross-process duplicate preflight. Missing
exit evidence after restart is pending; it is not a failed/retry signal.
The operation schema is identical in reservations and the journal projection.
A release change while operations exist refuses; cross-release upgrades are
outside this increment. Fixed public refusal labels are request_refused,
operation_unknown,money_wait,retired_batch_bound,legacy_retire.
Accounting incident reasons are exactly invalid_accounting_input,
accounting_api_refused,malformed_reconciliation,unsupported_decrease,uncovered_total.

Overrun means known T > held_usd. The flag is sticky once true, and ALL authority
advancement (including null/same-revision) is blocked for that owner. Known P /
known T overrun is ACKed in full; null P / known T over hold remains the reviewed
uncovered_total incident and freezes the batch. The known floor also preserves
known-overrun accounting across a later null ACK. Tests cover hold5/known6/null
and assert batch aggregate remains6, overrun stays true and no resume is granted.

An ACK is immutable except retirement: only null -> verified exact receipt hashes
is allowed, under the batch lock. Replay compares all other fields identically,
returns the saved ACK including current retirement, and never reruns accounting.
After pointer-before-money crash, status must report unreadable if the selected
pointer lacks a matching operation.output_generation. The repairing collect
command completes that same saved candidate, then projects output. It never
allows dispatch from the pointer alone. Existing status uses its current
batch_service._regular(lock) plus shared nonblocking flock; it must not call
batch_money.locked or read/reconcile controller directories.

## Covered-null worker restore and regression matrix

The ordinary legacy restore importer keeps refusing unknown spend. A new batch
restore may retain null only when the archived public card, retained ledger,
restored job-money.json and public card.job_money all agree and release is pinned.
restore_ledger.install validates the saved nine-field channel with job_authority,
uses real budget.usage_coverage on the unchanged retained ledger, requires a
valid result and covered_total_usd <= saved committed_total_usd, then writes its
existing authenticated receipt with nullable case_spent_usd. It does not grant
new authority or modify any ledger. job_config.install then validates the receipt
case/generation/public card hash against incoming source and authenticates the
incoming config before any model admission. No unknown legacy allowance, absent
channel, changed authority, unsupported maximum or public-only delta passes.
Pass null permission internally from install to authenticate only after these
checks; no CLI boolean can authorize it. Add tests to test_restore_ledger.py.

For new batch controllers, disable the legacy same-worker restart path in
launch.sh; checkpoint/retirement/new launch is the sole continuation path.
This also avoids restart.py's historical cumulative cap and same-worker grants.
Per-invocation/exam limits remain unchanged. The holder still allows normal
orphan-controller monitoring, which does not launch a second worker.

Integration test matrix in test_batch_holder.py:
1. Saved created event + real card/ciphertext with authored bindings: reserve,
   pending status, created reconciliation/running status, publish/ACK, exact
   deletion proof/retirement, source reserve, successor status. No live spend.
2. Fresh card absence, malformed schema/UUID/duplicate unresolved workers,
   multiple created events, incomplete inventory, lost controller/creation reply,
   preflight refusal, precreation exit proof and no retry after failed.
3. Crashes after money/config/reservation/journal writes, outbox/PUT/GET/pointer/
   ACK writes and installer history/money writes: replay one operation/grant.
4. Wrong operation/config/source/card authority, corrupted R2 GET, old-source
   replay A-B-A, pointer without ACK, missing deletion receipt and parked marker.
5. Real D ledger APIs: covered null retains full hold and revision; estimated
   map/decrease receipt accepted once; accounting incident freezes peers; genuine
   evidence extension clears only its incidents; known overrun floor persists.
6. Manifest max_calls absent/historical, bind stripped cumulative flags,
   worker recovery metadata, legacy pre-schema refusal, cb5e2/14d35 untouched.
7. Installer verifies retained source/authority/history and refuses swapped
   generations; covered-null importer preserves ledger bytes and rejects legacy.

Run focused files during implementation, then the complete required suite and a
fresh different-family diff review. Parent merges; no push or main access.

## Round 3 resolutions

All round3 findings accepted. UNBUG_BATCH_OPERATION is the exact variable name.
It joins control_resume.ENVIRONMENT and the frozen environment before launch.
At the start of launch.sh's factory_auto_resume function, a nonempty UNBUG_BATCH_OPERATION returns 1 without producing a
restart plan or starting a worker runner; orphan monitoring/collection/deletion
continues. The batch marker survives --resume-launch's environment rebuild.
The integration test persists a launch.json with that marker, resumes it through
control_resume.py and asserts no restart.py invocation or runner exec occurs, and DONE falls through to
guard_retire. Retain the existing batch_release return-1 guard as well.

record_exit(operation_id,exit_code) is called by the holder only for a reaped
child handle. record_exit first takes operations/<id>.lock nonblocking; a busy lock means
ignore this child exit entirely (an older preflight child may still own it).
Only while holding that operation lock and the batch lock, pending plus
dispatch_started=false becomes
failed/preflight_refused and stores dispatch_exit. No launch.json is required.
After holder restart, an unstarted pending child with no recorded exit can run
preflight again. This is intentional recovery of unattempted creation, protected
by the operation lock. It cannot repeat a Boat create because dispatch_started
is written before creator Popen. Tests cover both alive-holder reap and restart
without exit record, and verify at most one creator invocation.

batch_holder.reconcile is the sole retirement writer. Under the batch lock it
revalidates the deletion evidence, updates each existing operation ACK.retirement
in money first, then writes operation.retirement in reservations, then projects
the journal. A no-output operation stores its proof in operation.retirement and
frees concurrency, but never permits source continuation. collect always writes ACK.retirement=null. If an ACK is added later, reconcile
alone copies and revalidates that same proof. A crash between writes is repaired by
reconcile from the immutable receipt files, with exact hash agreement. PRE uses
both operation.retirement and the selected ACK.retirement and requires equality;
neither alone permits a successor. Retirement object is exactly
{worker_id,request_sha256,completion_sha256}; no separate retired boolean exists.
Only null-to-proof is allowed in either store, never proof replacement.

Both known and unknown source advances retain committed_total_usd == held_usd;
there are no top-ups or lower operating grants in this increment. Unknown retains
revision; known increments one. The current pointer path and exact schema are
inherited unchanged: current/<case>.json = {generation,manifest_sha256}.

Activation prerequisites explicitly remain: per-reason retry identities for
positive precreation failures; a reviewed reconciliation path for incidents on
already-retired operations (no later same-operation worker output can arrive);
and the live practice qualification. Until those are resolved the default-off
holder integration cannot be activated. An incident may legitimately keep the
batch blocked through its deadline; it never releases money or scores a case.
These limitations do not create a legacy resume/booking exception.

## Round 4 resolutions

All findings accepted. Immediately before marking dispatch_started under the
batch lock, the child additionally requires state=pending, dispatch_started=false
and incident=null. If any differs it exits without invoking the creator.
record_exit never touches state while another child holds the operation lock.
Add the explicit overlap test: pause original child during preflight, restart
holder, start a second child that loses the lock, reap it, then release the first.
Assert pending survives the losing child's exit and only one creator runs.

factory_auto_resume already refuses batch_release with return 1; preserve that
existing guard. The operation-marker guard is defense for the integration path
and must also return 1. Returning 0 is forbidden here because it would prevent
DONE from reaching guard_retire. The orphan test checks actual retirement call.

current_generation's calls >= job['max_calls'] expression is explicitly skipped
for _batch_job; calls still require valid nonnegative integer telemetry. No
missing historical max_calls access is evaluated for a batch job.
Activation additionally requires a reviewed recovery/disposition for a retired
worker with no output, and a NEW batch with no schema1 money state. It is not
permitted to activate an old batch by merely flipping HOLDER_ENABLED. No schema1
money migration is introduced. These are blockers for later activation, not
permission to release an unknown hold or replay a consumed fresh operation.

## Passing-review clarifications

A retired operation with no output shows stopped with its prior card, or not
collected if it has none; never running. record_exit always stores the exit code
once it owns both locks, but changes state only for pending/unstarted. The scan
probes the operation lock before spawning and skips busy operations. Activation
also needs recovery for a started orphan whose precreation exit was lost across
holder restart; this increment correctly retains pending ownership in that case.

## Diff review 1 resolutions

All diff-1 blockers and majors are accepted. These decisions are added:

- **Holder scan never stops the holder.** `key_holder.batch_tick` is one
  module function. A raise in exit recording, either scan or a spawn is logged
  by a fixed label and retried on the next tick. `reconcile` handles each
  operation alone: a raising operation keeps its reservation and money state
  as they were before that operation, and every other operation still
  completes and is saved. Failed operations are final and skipped.
- **One policy file.** With the gate on, `serve` refuses unless its `--policy`
  is `$UNBUG_CONTROL_HOME/policy.json`, the default every shell command loads.
- **One collected directory.** `batch_holder.py collect` refuses unless
  `UNBUG_LAUNCH_STATE` resolves to `$UNBUG_CONTROL_HOME/launches/<launch_id>`
  of that operation.
- **Blocking shared lock.** `lookup` and `source_directory` take a blocking
  shared batch lock. Only status stays nonblocking.
- **Transient preflight waits.** `MoneyWait` (any batch freeze), timeouts,
  failed helper commands and `OSError` exit dispatch with `TEMPFAIL` (75).
  `record_exit` ignores that code for an unstarted operation, so it stays
  pending, and the holder waits 60 seconds before the next preflight. Only a
  positive refusal fails an operation.
- **Incident evidence is immutable.** A repeat refusal never replaces an
  existing incident key.
- **Publication never retains the worker.** `collect.sh` reports a holder
  publication refusal on its own line and keeps its own collection status.
  The verified bytes stay in the launch state and the frozen snapshot for
  replay with the same `collect` command. Driving that replay from the holder
  scan is an activation prerequisite.
- **Exit records.** Only a dispatch child's exit reaches `record_exit`.
  Resume children inherit the legacy minimal environment.

## Activation readiness addendum (2026-10-30)

Baseline 200641d. This increment makes the holder safe to switch on for the
live practice run. It does not switch it on: `HOLDER_ENABLED` stays `False`
and no money is spent. The practice run is a separate, parent-approved step.

### Problem

The diff-2 review accepted one major (M1): a resume child that keeps failing
is respawned about once a second, forever. The activation prerequisites above
also leave three gaps that can strand or loop a live practice operation:

1. A dispatch child whose exit is lost across a holder restart, or whose
   `Popen` failed after `dispatch_started=true`, stays `pending` forever and
   holds the only concurrency slot (passing-review clarification).
2. A refused publication is never replayed. `collect.sh` keeps the verified
   bytes, but nothing calls `collect` again (diff-1 resolution).
3. A terminal operation (preflight refused, retired with no output) is not
   flagged in `unbug status`, so nobody is told the case is dead.

The holder also imports `factory/budget.py` and `factory/diagnosis.py` during
publication (`collection_facts` calls `budget.case_spending`/`usage_coverage`),
but neither file is in `TRUSTED_FILES`. A changed accountant would run under
an approved policy. Batch-service section 8 asks for that closure before
activation.

### Change

**Bounded holder retries (M1, N1).** Add one operation field
`failures` (int >= 0, starts 0). `key_holder.batch_tick` calls a new
`batch_holder.record_child(policy, root, home, identity, action, code)` for
every reaped `resume` or `publish` child. Under the nonblocking operation lock
and the batch lock it decides whether the child finished its job:

- resume: done when `launches/<id>/complete` exists;
- publish: done when the child exited 0.

If not done, `failures += 1`. At `RETRY_LIMIT = 5` it sets the terminal
incident `resume_failed` or `publication_failed`. The count is durable, so a
holder restart does not reset it. `batch_tick` waits `60 * 2**(failures-1)`
seconds (60, 120, 240, 480 s) before the next spawn, and pops the wait when it
respawns. A busy operation lock means a live owner; the exit is not counted and
the holder waits 60 s. `orphaned()` and the new publication scan skip both
terminal labels. `_reconcile_one` keeps retirement detection running for them,
so a manually finished launch still frees its slot, and it no longer overwrites
a terminal label with `creation_unknown`. Dispatch exits keep using
`record_exit` and the existing 60 s `TEMPFAIL` wait.

**Lost dispatch exit (prerequisite: started orphan, N2).** The dispatch child
holds `operations/<id>.lock` from preflight until `launch.sh` exits. So a free
operation lock proves the dispatch child is gone. `_reconcile_one` replaces
its `dispatch_exit is not None` test with a nonblocking probe of that lock.
The rest of the no-worker predicate is unchanged (matching `launch.json`, free
`controller.lock`, no `new.*`, empty `ids`). If the launch directory does not
exist and the lock is free, reconcile creates it (`mkdir`, mode 0700) before
marking the operation `failed`/`preflight_refused`. `control_resume.py` creates
that directory with a plain `mkdir`, so a late `launch.sh` can no longer start
a worker for this launch ID. `dispatch_exit` stays as a recorded fact only.
Known ceiling: a dispatch child killed in the microseconds between
`control_resume`'s `mkdir` and its `launch.json` write stays `pending`.

**Publication replay (prerequisite: holder-driven replay).** Add
`unpublished(policy, root, home)`: operations with `state=launched`,
`output_generation=null`, no incident in {`accounting_refused`,
`legacy_retire`, `publication_failed`}, `launches/<id>/complete` present and
`collected/<case>.scorecard.json` present. `complete` means the controller
finished and its workers are deleted, so collection is no longer racing.
`batch_tick` spawns `batch_holder.py publish --operation <id>` for each, with
the identity on stdin as for the other children. The child decrypts
`$UNBUG_SECRETS_FILE` in memory, reads only the four `R2_*` lines of `r2-env`
into its own environment (the same values `launch.sh` exports for
`collect.sh`), then runs the existing `reconcile` and `collect`. No new
publication logic: it is the same idempotent command collect.sh runs.

**Terminal dispositions are visible (prerequisites: retired with no output,
incidents on retired operations).** These stay terminal and money-safe: the
full hold stays committed, no retry identity is issued, and the operation ID
stays consumed. A retry could spend the same hold twice, because the restored
ledger cannot include the lost attempt's spend. `batch_status` adds the row's
operation incident and a `failures` count, and `render` flags:
`resume failed`, `publication failed`, `launch failed` (any `failed`
operation, immediately, replacing the 30-minute `launch stuck` for failed
rows) and `retired without output`. `active` ignores failed operations (N3).

**Trusted closure.** Add `factory/budget.py` and `factory/diagnosis.py` to
`TRUSTED_FILES`. Their local imports (`token_prices`, `recovery`, `registry`)
are already pinned. This changes the holder fingerprint; the practice batch
needs a new policy anyway.

### Not in this increment, and why

- **Per-reason retry identities for positive precreation refusals.** Positive
  refusals are deterministic (fingerprint, recipient, inventory ownership,
  account labels). The fix for one is a new release, and the release hash is
  in the operation ID, so the fixed release already gets a fresh identity. In
  the practice run a refusal stops the case at zero spend and status says
  `launch failed`. This stays an activation prerequisite for the 24-case batch.
- **new-batch-service-3** (malformed diagnosis state). Only reachable with
  `DIAGNOSIS_ENABLED`, which stays `False` for the practice run.
- **The practice manifest, policy, secrets and VM deployment.** These are the
  live test's own steps, listed in the report to the parent.
- **Automatic successor dispatch.** The successor launch from the collected
  generation is the existing CLI request
  `key_holder.py launch --batch <id> --job <job> --checkpoint <generation>`.

### Deletes

The `dispatch_exit` gate in `_reconcile_one`. The unbounded resume respawn.

### Tests (tests/factory/test_batch_holder.py)

1. A resume whose `launch.sh` exits 1 at once is spawned once per wait window
   (real `batch_tick`, real `orphaned`, real `record_child`; the child process
   is the only double). After five failures the operation carries
   `resume_failed`, `orphaned()` is empty, and status flags `resume failed`.
   A holder restart (fresh `waits`) does not reset the count.
2. A resume that leaves `complete` is not counted.
3. Lost dispatch exit: started operation, no exit recorded, free locks, no
   creation records: reconcile fails it. The same state with the operation
   lock held stays `pending`. Missing launch directory: reconcile creates it,
   fails the operation, and a real `control_resume.py` start for that launch
   ID then refuses.
4. Publication replay: a refused first publication (transport raises), launch
   `complete`, then the real `unpublished` lists it and the real `publish`
   command path (secrets decryption is a double at the age boundary) publishes
   and ACKs it; it is then not listed. Five failed publishes give
   `publication_failed` and stop the scan.
5. Status flags for failed, retired-without-output and both terminal labels.
6. N4: `serve` with gate on accepts `$UNBUG_CONTROL_HOME/policy.json`.
   N5: `batch_tick` with the real `reconcile` and a corrupt `money.json` keeps
   running and still runs the other scans.
7. `TRUSTED_FILES` contains budget.py and diagnosis.py (existing pin tests).

### Murphy rows

None closed. Rows 6, 27, 28, 35, 51 and new-batch-service-3 need the live
practice run. This increment narrows 6 (publication replay) and 51 (holder
restart recovery) but proves neither on a real VM.
