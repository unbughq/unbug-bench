# Cross-release checkpoint carry-over

Design 4. Intended integration target is factory-simplify; no merge is authorized.
Branch t3/batch-carry-over was cut from factory-simplify 56b4c13.
Owns new-batch-service-4. No activation, workers or paid calls are authorized.

## Objective and existing contract

Continue a stopped case after the factory is fixed without buying its old work
again, forgetting its history, or starting it twice. Use the existing
batch.launch(batch, job, checkpoint) path. A resume is a launch from a checkpoint.

The authoritative meaning of same-owner is interfaces §8 (held lifecycle) and
stream-d's held-lifecycle schema: the same continuing case gets a new B monetary
reservation across batches. Preserve case identity, lifetime ledger, history and
job identity; issue the new batch/job/reservation normally. Design 1 incorrectly
proposed preserving the reservation UUID. This revision retracts that proposal;
it does not amend D's contract. Same-batch continuations still retain reservation.

D admits at most three distinct factory-bug findings for lifetime resume. The
later approved manifest is the operator's fix decision. There is no separate fix
credential. Unproven historical waste cannot be invented: interfaces §8 and
stream-d explicitly retain empty eligible/failure sets until a separately
reviewed causal-receipt producer activates attribution. This increment implements
resume admission under that existing restriction, and preserves all existing
waste and lifetime totals. It does not claim Item 8's causal waste qualification.
No arbitrary post-resume work is labelled waste. No ordinary exhaustion,
extension, role binding or replacement allowance resets on transfer.

## Smallest B transfer: freeze one finished source batch

Transfer between two releases only after EVERY source operation is retired or
positively failed before creation. Freeze the whole source batch to one target.
This deletes the need for per-owner exports competing against source admissions
or for a separate shared-allocation service. Source money/operations/journal and
all acknowledged generations remain immutable. Collection must finish first;
pending, uncertain, uncollected and accounting-incident sources refuse. A source
with unfinished unrelated work must finish it before transfer. This deliberate
restriction supports sequential transfers; Item 8 still has the exclusions below.

Target authority cannot exceed the source batch money limit. Every imported
job retains exactly its prior lifetime commitment; unused source owners remain
charged at max(held, known floor) in the target's carried debit. This includes
owners intentionally omitted from further work. Therefore transferring only the
original after its replacement finishes cannot recover or regrant the
replacement's allocation. Source export disables all further source admission.
The target may use only remaining headroom under this same cumulative envelope.
Repeated transfers retain earlier carried debit. No increases or decreases to
per-owner commitment are implemented here. Explicit founder-authorized wider
batch-bound changes remain a separate reviewed amendment.

Queued replacement handling transfers only an ALREADY-reserved derived money
row with no ever-created operation, together with its verified one-child latch.
A derivation-only queue entry without money refuses import. No source write or
reservation occurs during snapshot construction or target import. Source
reservation must happen before snapshot pinning under normal source authority
and its reviewed practice clamp. Item 8 scenario 5 remains blocked if B has not
yet reserved the queued child. This is a refusal, not a new allocation.

This increment includes the shared resolver swap specified in interfaces §8:
all direct root lookups in batch_money.channel/authorize/authorize_locked,
batch_holder.validate_operations/reserve, batch.bind, job_config.install and
key_holder batch job selection use batch_service.resolve_job. Host admission of
a derived name additionally requires _lineage against the verified journal;
the pure resolver alone never grants admission. Worker installation accepts a
derived identity only in authenticated RAM config and the pinned manifest
replacement policy. Root maps remain immutable and contain roots only.

## Exact manifest and durable contracts

Canonical hashes mean carry_over.digest (sorted compact UTF-8 JSON, no NaN).
File hashes use transfer.digest. New files use registry.atomic_json (0600,
fsync/rename/directory fsync), within the existing owner-only batch directories.
Reject symlinks/nonregular inputs using batch_service._regular. Identifiers,
UUIDs, amounts and hashes use existing validators. Reject unknown fields in the
new records. No credentials or private findings enter host records.

The target manifest optionally contains exactly:

```
carry_from = {schema:1, manifest_json:<exact source manifest UTF-8 string>, policy:{batch:<old public batch policy>, jobs:<old jobs>},
              snapshot_sha256:<canonical hash>, jobs:{<job>:{generation:<sha|null>,case,committed_total_usd}}}
```

Only batch and jobs from the old policy are accepted (never holder secrets).
manifest_json hashes byte-for-byte to policy.batch.manifest_sha256 and must
match the member read from the verified source bundle on the host. Keeping its
exact bytes in the approved target manifest lets the worker authenticate all
predecessor manifests without another transfer format or copying old bundles.
Verify its release inventory with batch.verify(..., root=None); read the old
manifest bytes from its verified public-source.tar.gz member
unbug-bench/factory/batches/<id>.json without extracting it; require the source
manifest and policy digest pins and exact old root map. The current target still
uses batch_money.manifest with host verification. Source and target batch IDs
and release digests must differ. Target jobs corresponding to carry_from.jobs
must have the source case, identical non-money job fields/args and identical
commitment. Derived names live ONLY in carry_from.jobs, never in manifest.jobs or
policy.jobs. Each carry_from.jobs value becomes exactly
{generation:<sha|null>, case:<original case>, committed_total_usd:<amount>}.
The resolver gets imported case/commitment from this pinned map and non-money
fields from its source root template. Unimported roots retain normal name
checks. A root imported into the target jobs map has its original case and
requested_total_usd equal to the SOURCE AUTHORITY's committed_total_usd (which
may differ from the source manifest after revision). Source and target non-money
root fields must agree. For a derived import that same equality is checked
against carry_from.jobs[name].committed_total_usd. No new root suffix exception.

Snapshot (exact fields):

```
{schema:1, batch:<source id>, manifest_sha256, release_sha256,
 money:<complete validated schema2 money state>,
 derivations:<complete validated source derivation map>,
 entries:<source entries referenced by those derivations>,
 operations:<complete validated source operation map>,
 imported_derivations:<validated source journal imported map>,
 prior_import:<source import.json or null>}
```

The operator pins this snapshot's digest in the target manifest. Read-only
snapshot construction uses the existing validated state loaders. Every imported
parent retains its one-child latch even if its child is omitted. Ancestor
latches are pinned one level at a time: prior_import is the exact source import
receipt, and imported_derivations must equal that receipt's projected latches.
Its predecessor snapshot in turn pins the earlier receipt. Validate each level
with a visited-batch set to refuse cycles. Derivation records keep the existing exact
seven fields from batch_service._load; referenced entries keep their existing
facts. The source snapshot validator authenticates their original bindings.

Target journal adds optional imported_derivations, a map keyed by parent case.
Each value is exactly {source_batch, derivation:<existing seven-field row>}.
batch_transfer.latches(receipt) returns union of snapshot.imported_derivations
and snapshot.derivations wrapped with snapshot.batch; conflicting parent/child
identities refuse. batch_service._load validates exact equality of this optional
map with latches(import.json). Imported entries do not enter target entries.
_lineage consults both local and imported maps. _enqueue consults both for
parent and claimed-child latches; an imported parent emits NO replacement queue
entry (its child is either explicitly imported or intentionally left behind).
Normal new parent derivations still write the ordinary local map. This rule
preserves latches even where no old eligible generation exists in target entries.
No copied entry is passed off as a target collection or new eligibility proof.

Source `export.json` and target `import.json` contain IDENTICAL bytes:

```
{schema:1, source_batch, target_batch, target_manifest_sha256,
 target_release_sha256, snapshot:<snapshot above>,
 jobs:{<job>:{generation:<sha|null>, authority:<new nine-field channel>}},
 carried_debit_usd:<nine-place amount>}
```

Each new authority is schema1, batch/job/case/deadline from the target, UUID4
reservation minted once in export, revision 1, source_generation from jobs,
and committed_total_usd identical to its source reservation. Generation null is
legal only for a verified derived queued job with no ever-created operation;
its collected total is zero. No root with missing checkpoint can masquerade as
queued work. A non-null generation must be source CURRENT, ACKed, bound to its
operation authority, snapshot and verified retirement. Sealed/retired-science
sources refuse resume; operational deadline stops and factory-bug holds may
resume. Normal plumbing/science replays of sealed cases remain outside this
increment, so Item 8 scenario 6 is not unblocked by this change alone.

Overrun sources refuse (known floor must not exceed held commitment), as do
unknown latest totals. At import require source aggregate <= target money bound
<= source money bound before writing export.

Source `export.json` is the single ownership commit point. Target `import.json`
is a repairable copy. Target money rows add optional `imported` containing exactly
`{generation, authority, previous, known_floor_usd}`: authority is the new initial
channel from export, previous is the source latest accounting projection, floor
is the source known floor. Existing row keys remain; initial sources is
[generation] (including [null] for queued), local acks is {}, overrun is false.
The header adds optional `carried_debit_usd`, equal to import.json's debit.
Old schema2 states without these fields remain valid. Imported base generation
requires import.json proof rather than a fabricated local ACK. Floor validation
starts at imported floor, then includes local ACKs. Every later source must have
an ordinary local ACK. aggregate adds carried debit exactly once. The debit is
source aggregate minus imported owners' held/floor charges, including inherited
debit. No owner or historical charge disappears.

## Lock, replay and integration order

batch_transfer.prepare(policy, root, home) is called by holder.reserve BEFORE
its ordinary single-batch lock. Acquire source and target locks lexicographically.
Revalidate manifests, snapshot, target deadline, money bound and all source
retirements under those locks. Validate all target jobs before any durable write.
Write source export first, then identical target import, then target money state
and derived-latch projection. An existing exact export repairs target files;
changed target, pins, snapshot or owner bindings refuse. Never overwrite advanced
target money. If target already has unrelated state, refuse initial import.
Crash after export leaves the source frozen and resumes only the same target.
Enforce freeze centrally in batch_money.locked(home,batch,*,read_export=False):
after locking, presence of export.json refuses unless read_export=True. Only
batch_transfer's read/repair transaction and read-only status may opt in. All
ordinary source writers use the default: service.collect/plan, holder.reserve,
collect/reconcile/record_exit/record_child and controller recovery/publication
entry points. Readers that launch or publish (schedule_waits, orphaned,
unpublished, publish_replay, resume_controller) explicitly guard export under
the same lock before returning actionable work. _post guards export for its
shared-lock path too. No post-export ACK/retirement/journal mutation is allowed.
Old source launch retries, authorize and dispatch refuse under their batch lock. Thus a pending
source dispatch cannot race export. Export is never removed on rollback.

Keep transfer code in batch_transfer.py. Narrow calls integrate it with:
- batch_money.check_manifest/load_locked/aggregate: imported case grammar and
  validated initial accounting floor/debit; authorize refuses exported sources.
- batch_service.resolve_job/_lineage/_enqueue: imported derived identities and
  imported one-child latch, without creating another child on later exhaustion.
- batch_holder.reserve/_post/_source/source_directory: imported initial source
  resolves through the original source's immutable generation and ACK; later
  sources use today's local path. Return the original source directory, never
  synthesize a predecessor operation. Queued import launches empty once through
  the ordinary path. Both target config and deterministic operation UUID5 remain
  today's shapes.
- batch.bind: use manifest-resolved case and authenticated source release for
  the initial import; remove the duplicate same-release-only refusal.

_source verifies original source snapshots with their source manifest/release.
Later target collection writes ordinary target generation manifests. For a
second transfer of a locally produced successor, its source is that target;
prior export/import receipts stay available to authenticate ancestry. No ABA
source replay: reject any generation already consumed in the imported source
chain except the exact idempotent launch replay.

## Worker installation and exact D admission

launch.sh passes --job-config /dev/shm/secrets/factory-job.json and
--job-config-sha256 <existing authenticated digest> to restore_ledger.py along
with the target --release-sha256. These args are required together. Factor
job_config.verified_config(path,digest,case,generation,release) from install's
existing release/worker-manifest/manifest/channel checks; restore_ledger calls
it before choosing source release. It verifies owner-only RAM bytes, target
release, worker manifest and manifest digest pins, then exact case/source.
No different-release restore without this verified config is accepted.
Transport receives the current authenticated RAM config as today. Its pinned
manifest carry_from supplies the expected old release and generation for the
first imported restore. restore_ledger.install accepts that exact original
release, still authenticates archived/public ledger and saved job-money equality,
and writes the usual accounting receipt. run's early release-equality predicate
moves into job_config.install after restore authentication, before dispatch.
No bare different-release bypass is allowed.

job_config.install recognizes an imported first source only when the current
manifest lists the exact source generation, old authority is validated against
the pinned old manifest, and archive/public saved money and accounting receipt
agree. Require unchanged case/job/commitment, new target batch/deadline, a new
reservation UUID and revision 1. Append the existing history shape
`{old,new,config_sha256,source_generation}` under the existing key
new-reservation/revision/source. Normal same-batch changes keep today's rules.
The public source release and pinned source policy bind the old release; do not
add a parallel fix credential. Preserve every prior transition and ledger byte.

Add diagnosis.resume_factory_bug(c), called in diagnosis_dispatch._dispatch
AFTER its last carry_context and BEFORE prepare_dispatch/queued_inputs/replay.
It returns False for ordinary cases and True for authenticated resumed findings,
or raises BudgetError for held/invalid/retired states. It uses c.checkpoint_card,
c.authenticated_job_config, the verified job-money history and retained finding.
The last installed history transition supplies the predecessor authority;
follow earlier transitions when an already-admitted finding spans more releases.
The predecessor RELEASE comes from verified carry_from.policy.batch.sha256,
which must equal the input public and archived scorecard release on first
import. For older holdings, follow that source manifest's pinned carry_from
policies recursively, validating release and manifest hashes at each level.
Worker code resolves each source from carry_from.manifest_json, checks its
exact byte hash against policy.batch.manifest_sha256 and validates the policy
and manifest relation before following its own carry_from. The current release
already authenticates this complete chain of public pins. Reject repeated batch
IDs/releases, malformed metadata or absent proof before any model call.
Same-batch replay uses current release plus the verified job-money transitions.
No monetary transition hash alone is treated as release proof.
Authenticate finding.held_batch_id/held_release_sha256 against that historical
binding, not the current release. Use the existing _read_factory_bug_finding
validator with that explicit historical authority/release, and its original
inputs/manifest.json generation/evidence directory. Never infer those from model
prose. Validate history with _factory_bug_history before making a decision.

For a held finding not already in history, require current batch/release both
differ from held binding. If history has three entries: publish status stopped,
terminal_stop retired_factory_bug_limit, count 3; retain finding and stop before
any lease. Otherwise create UUID4 resume_id and append EXACTLY stream-d's row:
`{schema_version:1,resume_id,finding_id,case,held_batch_id,batch_id,job_id,
reservation_id,source_generation,batch_release_sha256}`. All new binding values
come from the current verified config; source_generation is its INPUT hash.
Write history before clearing the hold. Replaying an existing finding validates
its recorded binding and the authenticated transition chain to current authority;
reuse its row/UUID/count, including same-batch waits and later-batch moves.

After durable admission remove active factory_bug, diagnosis_state,
infrastructure_gate, terminal_stop and failed_gate from the new active card,
set status running and factory_bug_resume_count to history length, and persist
scorecard. Retain immutable private finding, diagnosis inputs and history.
Do not modify c.checkpoint_card or its receipts. The dispatch caller returns
False to ordinary pipeline execution immediately when resume_factory_bug is
True; it must not recopy CARRY or replay the old completed diagnosis afterward.
require_model_work continues to reject active hold markers; admitted resume has
none. Normal exhaustion later creates a new ID. _factory_bug_history gains keyword-only admitted_replay=None, supplied ONLY
by resume_factory_bug after finding/config verification; persist/restore callers
retain strict count equality. Permit count len(history)-1 only if the LAST row
matches finding_id, case and held_batch_id, and its batch/job/reservation/release
match the authenticated admission binding. Its source_generation must equal
the source_generation of that exact admission binding, found by walking the
verified transitions back with exact old/new equality (including intermediate
releases and repeated append-ahead checkpoints). An absent or branching chain
refuses. In all cases only ONE append may be ahead. Repair count after
validation; all other mismatches stop factory_bug_history_invalid. History missing after a finding never initializes.
Retained work/gates/extension history and ordinary budget exhaustion stay intact.

Current findings have empty eligible/failure sets. Preserve that restriction and
emit no new waste record. D's documented future causal attribution remains a
separate addendum; this design does not claim a fixed-cost or arbitrary-work
exception. Existing ledger waste is imported byte-for-byte and remains in total
spend. Scope is the held-resume lifecycle, not Item 8 live waste activation.

## Tests, cost, risks and delivery

Offline implementation costs $0 in workers/model calls. Working estimate:
one session for reviewed contracts, two for implementation/offline fixtures,
one for full-suite and diff-review fixes; review rounds can extend this estimate.
No deployment date is promised. Sequence: reviewed
schemas/contract, host transfer and restart tests, worker admission tests, full
suite, fresh diff review. No paid qualification is authorized.
Mid-term exam is transfer of saved card/ledger bytes with explicitly authored
binding/deletion fixtures: cumulative spend, idempotence, old-owner refusal,
changed args/pins refusal, derived queued authority, omitted-child debit and
one-child latch after two releases. Those authored fields do NOT prove real
publication, deletion, diagnosis or a live held transition.

Use tests/factory/test_batch_transfer.py for host/restore integration and
extend tests/factory/test_stream_d_held.py for admission. Add a batch_status
mapping for retired_factory_bug_limit to retired, not scored failure/attention;
document the literal in interfaces §8. Use status='running' for active cards.
Clearing hold markers ONLY through this verified admission is the guard update
required by stream-d; require_model_work itself keeps fail-closed behavior.

Worker tests use real saved 5813be/practice ledger/card bytes with labelled
held/admission overlays: first/second/third finding, fourth retirement, same
finding replay, cross-release replay, missing/corrupt history, append-before-card
crash, wrong old release/authority and retained cumulative waste. Test through
ordinary bind/config/restore/dispatch seams, no paid model calls.

Final command: uv run --with numpy --with scipy python -B tests/run.py. Retain
unique log, exact tested code commit, exit status, and verbatim reviews. Every
blocker fix gets a fresh review. Never merge or push. Activation flags unchanged.

Risks: duplicate ownership (export under both locks); lost prior spend (debit and
unchanged commitments); forged lineage (pinned snapshot and source validation);
reintroduced holds (single final carry_context ordering); lifetime reset (strict
history with crash repair). Tight host integration calls isolate B's parallel work.

The Murphy row remains OPEN until real saved held and deadline-stopped generations
prove the transition. The closure route is separately authorized Item 8 scenario
5 plus a deadline-stop artifact, after practice clamp, causal attribution and
other Item 8 prerequisites. Implementing the offline increment precedes that run;
there is no requirement to fabricate a held artifact to break this ordering.
This increment alone does not authorize Item 8 scenarios 5/6 or paid work.

## Design 4 exact integration decisions (supersedes ambiguities above)

D3-B1: Legacy batch_money.authorize refuses any manifest containing carry_from
and any derived name BEFORE resolving jobs or reading/minting money. The
non-holder branch of batch.bind does the same, and KEEPS its current
same-release check. Only a holder-verified imported initial source is permitted
to differ in release. Tests assert each refusal with HOLDER_ENABLED=False and
verify money/launch state is unchanged. Schema1 source money refuses transfer;
there is no implicit migration of current legacy cases. HOLDER_ENABLED remains
unchanged by this increment.

D3-M1: Target _source/_post/source_directory call
batch_transfer.source(home, record, name, generation), which checks the exact
immutable export/import pairing and pinned snapshot, then reads WITHOUT taking
a second lock the immutable original ACK/current/outbox/generation using
source manifest/release bindings. It returns (ack, entry, card, directory).
A missing export refuses; no unlocked read of a mutable source is allowed. For imported-base
sources == [generation], reserve and _post bypass their sources[-2] comparison
ONLY after that reader verifies the imported initial channel. Ordinary local
sources retain the existing comparison. The transfer reader acquires no locks; callers already hold the target lock.
Source is permanently frozen. This avoids lock inversion with prepare replay.
Initial two-lock prepare still uses lexicographic ordering.

D3-M2: Import writes one ordinary replacement queue row for each null-generation
imported child, with parent_case from its imported derivation and source_generation
null, reason exhaustion, kind replacement, owner_job=job, and next contiguous
sequence. It writes no queue row for a child not selected for import. _load
validates replacement queue rows against the union of local derivations and
imported_derivations' derivation values. Import replay preserves rows/sequences
instead of appending again. The coordinator requests holder.reserve for that child through
ordinary empty launch; deterministic operation UUID prevents a second launch.
Imported parents never derive/enqueue another child on later exhaustion.

D3-M3: Re-export of an imported non-null checkpoint without a LOCAL acknowledged
successor is explicitly refused in this increment, even after a positive
precreation failure. The case remains charged and frozen to its existing target;
it can retry only if that target's ordinary operation recovery allows it.
Otherwise it retires without work; no new reservation or rescue path is created.
This is a documented liveness limitation, not an exception to accounting.
A queued null-generation reservation that has no operation at all can move
again: prior_import is its zero-work proof and its commitment is unchanged.

D3-M4: The resolver integration includes removing root-count caps from
batch_money.check_manifest and key_holder.policy_load while retaining positive
integer concurrency/slot validation; key_holder orphan policy_job membership;
account_handoff.py's batch job selection; and coordinator_inventory.py's batch
job selection. Use the same pure resolver for template/case, with journal lineage
required at the holder admission boundary. Do not add a parallel derived-job
map to policy.jobs. Existing non-batch paths are untouched. Legacy authorize
still refuses derived names despite the resolver integration elsewhere.

Nits: use status='running' for the admitted card (existing run and runtime cards
already use that active convention); tests/factory/test_stream_d_held.py is the
worker test file. In diagnosis_dispatch._dispatch, call resume_factory_bug AFTER
carry_context, INVALID refusal, job_authority.for_case, and the _state check,
but BEFORE prepare_dispatch and any model lease. A missing diagnosis_state on
an ordinary already-cleared continuation is not a held admission; retain its
history without recopying old held state. Source and target restore_recipient
must be identical before export; key rotation is outside this increment.

Review-4 clarifications: a queued null-generation child refuses transfer if ANY
operation exists, including positively failed precreation operations. Importing
a derived name requires target replacement_policy.enabled=true. The imported
queue row remains ordering metadata after launch; repeat reserve returns the
same operation. Every reserve intentionally rechecks prepare/export/import
under both locks; no unchecked fast path.

Implementation clarification: when only a derived child is imported, its root
entry exists solely as the immutable template. Holder admission refuses a fresh
launch of that template-only root. It cannot mint another allocation by omitting
the original from carry_from.jobs. Other unrelated explicitly authorized fresh
roots still use ordinary cumulative admission.


### Diff-review integration clarifications

Ordinary stopped checkpoints may also transfer (for example a provider wait or
exhausted case); transfer does not reset their gates, exhaustion or budget.
Sealed cards and scientific retirement, factory-bug-limit retirement and invalid
input/history stops refuse. Deadline stops and factory-bug holds are the primary
use cases, not an exclusive allow-list.

Admission replay may match the last durable admission to any binding in the
verified, unbranched money transition chain, including an intermediate release.
This preserves one admission across repeated checkpoint failures before the
cleared card is collected. The finding, case, held batch, admission batch/job,
reservation, source generation and release must all match that binding; the
history may run only one ahead of the public count and the admission must be the
last history row. It never creates a new admission for a replayed finding.

An I/O failure writing admission history or its cleared scorecard after input
validation is `factory_bug_resume_io_wait`, not invalid diagnosis input. The
in-memory held markers remain until the cleared card is durably written, so the
ordinary checkpoint/relaunch path can repair the append-ahead state.

Every carried-target reservation revalidates the frozen predecessor release and
snapshot. The old release directory must remain on the control VM while the
target admits work, including unrelated fresh roots.
