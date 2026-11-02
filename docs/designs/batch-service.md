# Control VM owns the batch — stream B

> Shared paid-spend supersession (2026-11-01):
> [router-shared-paid-spend.md](router-shared-paid-spend.md) replaces the per-batch
> router configuration/database/token contract. One control-VM-wide service uses
> the service account's ~/.unbug-control/router/factory.sqlite3; production rejects
> database config and UNBUG_CONTROL_HOME overrides. All batches pin the same global
> accounts/capacities/config/service identity. B3 owns config/RAM delivery and
> drain/restart rotation. Server upgrades precede clients; paid_protocol=1 and
> per-request paid authorization are mandatory. No existing practice pins activate
> this code. New placement of openrouter-key in router RAM for read-only credit
> observations requires founder acknowledgement before deployment. This offline
> implementation supplies no credential and performs no activation.


Design baseline ac33267, router contract read at t3/smart-model-router 25780d4.
Read with ENGINEERING.md, murphy-register.md, interfaces.md §§3–8, status.md,
stream-d.md and factory-single-path.md. This design changes no gate criteria.
Founder authority: scoped VM restore key; no Mac dependency during a batch;
one launch path; plumbing updates at the next checkpoint. A one-time founder
migration command on the Mac is explicitly authorized, not a batch dependency.

## Problem and outcome

The merged batch.launch interface freezes source and consumes a generation once,
but nobody dispatches the manifest after a reboot, drains publication failures,
renews Codex or restores with the VM identity. Worker TTL is not batch authority.
Legacy wrappers and expiring coordinator observations leave human pit stops.
The batch must finish without the Mac, within cumulative money and UTC time.
Success is practice wait → authenticated checkpoint → verified retirement →
launch collected generation → D settlement → finish, with restart at every seam.

Own rows 1,5,6,7,16,19,20,26,27,28,33,34,35,51,new-single-path-1.
Rows 2,4,47,48 also need the shared practice end-to-end proof. No row closes
on a synthetic test or design approval. Partial coverage is recorded as partial.

## One service, existing launcher

Add factory/batch_service.py, stdlib only, supervised by
control/unbug-batch.service. It uses one owner lock per batch and registry.atomic_json
(fsync file + directory) for a small JSON journal; no second router or event engine.
Its tick runs every 15 seconds; blocking cloud operations run as separately
supervised per-launch controllers/outbox tasks, never inside the journal lock.
Existing control_resume owns controller locks. The public entry remains
batch.launch(batch, job, checkpoint_or_empty). No new case-specific launcher.

Manifest policy extends batch with deadline, money bound, target_slots, router
config, restore recipient and job authority from interfaces §8. All
identifiers and finite positive limits are validated before dispatch. Missing
router/D money prerequisites refuse enablement, not a local bypass. Default
UNBUG_PROVIDER_WAIT remains off until A and D merge and qualification passes.

State at ~/.unbug-control/batches/<batch> consists of journal.json, lock,
outbox/, immutable generations/<case>/<sha256>/ and current/<case>.json pointers.
The holder's reservations.json remains launch authority; journal is a scheduling
projection. Each entry key is case + collected sha256 (`fresh` for empty input):
{case,job,generation,state,pending_since,not_before,operation_id,launch_id,
worker_id,collected_generation,retired,reason,relaunches:{reason:count},
credit_topups_consumed:[receipt_id],last_error}. States are
only pending/launched/failed. Public operational metadata only; no prompt text.
state=launched plus no successor collected means running, even after restart.

Before submitting, persist pending with the deterministic operation UUID. Holder enqueue returns
that durable operation ID immediately, after recording the frozen request. The
holder moves expensive validation/inventory/provisioning off its socket accept
loop into the existing controller path. The holder serializes durable reservations
under one lock; every request/retry for an operation has the identical frozen
batch/job/generation/release/money revision. Reuse with different fields refuses.
The same operation is reconciled after lost replies; it is never submitted with
a new ID. The receipt records launch_id before Popen. launched means accepted
worker ownership, not merely a PID. failed is allowed only with positive proof
no worker was created (including bounded creation-query reconciliation); a
Boat create timeout stays pending until inventory/name/launch-ID proves outcome.
E's retries/backoff apply only after that proof. A missing receipt is not proof.

On restart load and validate manifest/journal, reconcile holder receipts and
controller locks, resume existing controllers, then collect and publish before
new dispatch. No live or uncertain case can acquire a second worker. Inventory
is fetched once per tick with pagination (nextCursor, bounded pages, duplicate
IDs/cursor loops rejected), shared with holder for <=15 seconds. Incomplete
inventory prevents creation/retirement claims, never stops healthy peer controllers.

## Manifest authorization and extension boundary

Manifest file is tracked `factory/batches/<batch>.json` within the frozen release
(and therefore in source-manifest.json). The holder's owner-only
~/.unbug-control/policy.json pins batch.manifest_path, batch.manifest_sha256,
batch.release and batch.sha256. Service checks all four against the qualified
release at startup and before dispatch. The service never writes policy.json or
accepts increased authority from a worker/card. Policy is prepared by the parent
from founder-authorized batch bounds; `tools/batch-policy.py install --manifest
PATH --manifest-sha256 HEX --release DIR --release-sha256 HEX` installs only that
explicit public authority, with recorded old/new policy hashes. Amendments use
that same command with a new tracked manifest digest and reviewed release, while
dispatch is locked. Increasing money/deadline/slots needs new founder authority;
a plumbing-only release amendment preserving those fields uses the reviewed
parent merge plus migration record. Existing spend/commitments/terminal records
are loaded first; reject lowering below consumption/commitments or reviving
retired_batch_bound. Host owner is trusted; this is not a signature/vault system.

Schema-v1 example (IDs/amounts are illustrative, not authorization):

```json
{"schema":1,"id":"practice-b","batch_deadline":"2026-11-01T00:00:00Z",
 "money_limit_usd":"3.000000000","target_slots":1,"max_concurrency":1,
 "restore_recipient":"age1...",
 "replacement_policy":{"schema":1,"enabled":true},
 "router":{"config_path":"factory/batches/practice-b-router.json",
           "config_sha256":"<64hex>","url":"https://router.example:8765"},
 "jobs":{"practice":{"case":"case-practice-b-practice","mode":"batch",
          "requested_total_usd":"3.000000000",
          "args":["1","--source","plant","--rotation-slot","0"],
          "max_calls":10}},
 "daily_need":{"boat_usd":"0.100000000","openrouter_usd":"0.200000000"}}
```

`target_slots`/`max_concurrency` positive integers, independent of root job count;
case is exactly case-<batch>-<job>. UTC deadline has explicit zone, amounts are
finite nonnegative decimal strings of nine places (model bound positive),
router config contains database path, capacity integer 0–100 per pool, allowed
public account labels and TLS paths, no token. Token comes from RAM environment.
All hashes lower-case 64hex; relative paths confined to approved release. Jobs retain merged batch.bind non-money argument validation. Increment2 removes
job.max_cost and batch.bind's --max-cost cap emission for authenticated batch
jobs; D's validated job_authority is the sole monetary bound. max_calls stays.
Historical --max-cost may be decoded as metadata only; it enforces nothing on
new-schema factory work. Daily projections optional positive
decimal strings; absent means balance-need comparison unknown, never a guess.
D stages use the same money owner/job. Queue priority belongs to the admission
or revision request, not another commitment. Ordinary scientific spend and
infra-waste are separate report lines; total job authority includes both to keep
batch money conserved. B grants no extension eligibility. Under amended ENGINEERING §3 extensions
draw from the founder-set cumulative batch bound through §8, with no fixed
per-extension dollar allowance; D enforces count, package and progress rules.

Holder protocol and exact control-restore predicate are a required reviewed
addendum before increment 3. They must preserve the three-argument batch.launch
interface: derive stable UUID5 operation ID from batch/job/generation/release,
return the same receipt on replay, and expose read-only operation lookup. The
cache is batches/<batch>/inventory.json with observed_at UTC, complete flag and
page cursor provenance; age >15s or incomplete refuses new launch. Never accept
a worker-supplied inventory. Pending/failed queue entries retain per-case
relaunches by reason and consumed top-up receipt IDs across generations; no
single attempts counter. No holder-refactor code may precede this addendum PASS.

## Waits, capacity, TTL and disappearance

Only latest verified collected cards schedule continuations. For provider_wait,
consume A's public projection verbatim; generation is card.sha256, never a hash
inside provider_wait. Queue oldest ready first per effective route; ask
model_router.capacity(route) and subtract this tick's submissions. Persist one
random jitter 0–60 seconds in not_before, also >= retry_after. Zero capacity
creates no worker. G10 exposure also checks reviewer capacity; if tester/reviewer
share a pool require two free slots (use router status pool mappings).

Before launch require batch deadline, money authority, verified archive/key/card,
retired predecessor and available concurrency. Full holder means queued. Count
only successful relaunches against §4's per-reason backstops: ten for ordinary
provider conditions, one credit relaunch per verified top-up; uncertain submission
counts as outstanding until reconciled. At cap emit unscored
provider_wait_unrecoverable; at batch deadline provider_wait_deadline. Preserve
original collected card and append operational stop in journal; never fabricate
a scored case. label-only exhaustion is a D factory-bug candidate; no gate result.
Cross-batch automatic import is refused; a new authorized manifest migration
must explicitly bind lineage and preserve all spend. No deadline reset.

Each case controller owns its collection/retirement independently (reuse E).
Worker TTL margin is max(45 minutes, measured p99 seal+upload+collect plus 5
minutes), capped by remaining provider lifetime. Start no new paid unit that
cannot finish/cancel/checkpoint within that remaining lifetime. B passes remaining
monotonic budget into bounded seal/transfer subprocesses; no sequential batch
retirement queue. TTL checkpoint stop is ttl_retired with authenticated cause,
not an operator pause. Successful collection plus verified deletion queues the
same launch interface under the absolute batch horizon (which may exceed 48h).
No three-attempt/24h legacy continuation ceiling applies to batch jobs.

Liveness distinguishes no runner, unreachable SSH and absent worker. A crash
restores only the latest acknowledged immutable checkpoint after provider worker
absence/deletion is proved. Unreachable means unknown and keeps ownership/money.
D conservatively settles uncertain invocation reservations on restore. Never
resume a case with no trustworthy generation; mark unreadable and retry collection.
The 22 historical paused/stopped real cases remain read-only, excluded from the
manifest. Their files may be read for qualification and migrated ciphertext only
by the explicit founder command below; no automatic dispatch/import.

## Collection and publication

Extend transfer.py/collect.sh, rather than restore_sync's bundle publisher.
Collect into a new staging directory, with bounded calls and resumable chunks.
Required set: archive, card, casekey; statement/search ciphertext and accounting/
retirement receipts when referenced. Verify case, archive sha256, release lineage,
source generation, cumulative ledger metadata and every referenced file digest.
A terminal card waits for matching terminal archive; a quiescent checkpoint may
publish while worker lives but cannot authorize a successor before retirement.

Write immutable generation directory then its manifest of filename/digest/size;
fsync before enqueueing a durable outbox entry. Outbox key is case/generation;
states pending/acknowledged with attempt,next_retry,error. Retry 15/30/60s then
5min capped, until batch_deadline; bounded transport timeout, no signed URLs in logs. Destination is
the VM's configured canonical generation store (same filesystem for VM launches);
legacy remote producers use bounded SSH to the same verifier. R2 ciphertext
objects use generations/<case>/<digest>/archive.age, never overwrite vm/ID links.
After PUT, GET-stream and compare ciphertext digest; upload card/key/manifests as
bound objects. Only then atomically replace one current/<case>.json pointer with
{generation, manifest_sha256}. Re-read it to acknowledge, then update journal and
money under the lock. Crash before pointer leaves old generation; after pointer
replay acknowledges the same complete set. No consumer reads a partial canonical
flat-file mix: update batch.bind/holder/launcher/status to resolve this pointer.
Legacy sealed flat files remain read-only compatibility inputs until migrated.

Worker checkpoints synchronously await durability ACK before the next paid unit
(D boundary hook); failed upload stays retryable and blocks expensive work rather
than silently advancing. Reuse RunArtifacts.seal and durable_checkpoint; the VM
composes committed immutable unit receipts, not a tar of mutating active model
state. D owns completed writer/stress/calibrator hooks. Mechanical unit boundaries
join writers before sealing. Mid-call resume is not claimed; retain conservative
reservation for any unacknowledged operation. B/D share row35 until those hooks
prove real loss bounds. Public progress/receipts never contain case findings.

## Scoped key and one-time legacy migration

VM control.key stays 0600 on the VM, never copied to workers. Remove holder's
blanket control-identity restore refusal only for manifest-bound batch jobs with
verified casekey/generation/release/retirement/money authority. Legacy any-case,
audits and arbitrary caller-selected case paths stay refused. Validate control
identity's public recipient equals the manifest's restore recipient. Batch holder
horizon uses batch deadline; systemd restart reopens only that bounded authority.
New case_recipient wraps casekey to founder + VM recipient, archive still founder
+ case recipient. Worker config receives public VM recipient from the pinned
manifest; the restore transport unwraps only a small casekey on the VM.

Add tools/migrate-legacy-checkpoints.py and a one-command .sh wrapper. Founder
runs it on the Mac, one hidden getpass prompt, identity bytes only to age stdin,
never argv/env/file. The founder approved immutable outputs in place of the
earlier in-place swap proposal: originals stay untouched; activation is one
verified pointer switch after VM qualification, rollback moves that pointer back.
Use the existing generation store, no swap journal or rescue directory protocol.

### Pinned inventory and founder run

The source of truth is a digest-pinned union plan, not either host overwriting
the other. Read-only evidence: docs/reports/batch-service-inventory-20261030.json.
Mac source is exactly /Users/bugsincode/Developer/unbug-bench/sealed (Git common
checkout, never implicit current-worktree fallback). VM source is exactly
/home/user/unbug-bench/sealed. Mac has 43 checkpoints; VM has 46. The three
VM-only keyed recent recovery checkpoints c7d405/e15450/873d7f join key-only
rewrapping; their archive ciphertext and original key remain untouched. All 30 unwrapped case prefixes are on both hosts.
One checkpoint, case-20261017T125556Z-18681d, differs between hosts (new Murphy
row new-batch-service-1); preserve both digests. Its final archive/card agree.
Twenty-nine other legacy entries match exactly. There are 17 sibling final
archives: 19 current legacy cards bind present checkpoints, 10 bind present
finals, and case-20261017T114431Z-9d2b0e names absent digest 4982654d… on both
hosts (available checkpoint digest 651038ab…). The exact full digests are in
the survey/plan. This new observed failure is registered separately. No input
is invented to satisfy that card. Preserve every
unique checkpoint/final input and its exact old card; no mtime-based choice.
The 22 historical paused cases are a subset of the corpus, not an assertion
that there are only 22 case prefixes. No historical case is dispatched.

Agent prepares the plan and stages the divergent VM ciphertext to Mac cache
~/.cache/unbug-bench/batch-migration-inputs/<old-sha>/archive.age over verified
SSH, checks ciphertext hash, and records source host/path. No plaintext. Plan
schema 1: {founder_recipient,restore_recipient,mac_root,vm_root,
entries:[{case,sources:[{host,path}],local_path,size,archive_sha256,
card_path,card_sha256,card_archive_sha256,kind,active_source}],
excluded:[{case,reason}],survey_sha256,vm_restore_recipient}.
kind is checkpoint|final|divergent_checkpoint|card_bound_absent|rewrap_key.
card_bound_absent still migrates its available checkpoint; its immutable original
card is preserved, projected-card has bound_archive:{status:"absent",sha256:old}
and active_source:false, so no current pointer can select it. Qualification
expects exactly this plan-listed missing-digest exception and proves no activation.
It remains unreadable/VM-unrestorable as a current case until original evidence
is recovered or an explicitly authenticated import chooses the saved historical
checkpoint. It is not silently relabeled or made eligible.
rewrap_key entries instead have key_sha256/key_size and archive provenance
metadata from survey; archive_sha256 still names the selected immutable archive,
local_path names old wrapped key. Original-key bytes and original card remain
unchanged. All 13 keyed Mac prefixes AND all 3 keyed VM-only prefixes get these
entries: their current wrappers are founder-only (one stanza in survey), so
merely migrating the 30 unkeyed prefixes would leave 16 VM-unrestorable cases.
The agent stages VM-only encrypted keys/public cards to Mac cache before plan
freeze, verifies hashes, and includes every unique old key, including any
cross-host key variants. Founder unwraps those existing case keys in memory,
rewraps founder+VM, verifies founder unwrap, publishes immutable key migration
record referencing unchanged ciphertext (no archive reencrypt/copy on Mac).
VM proves its unwrap and full archive decryption/hash before activation.
No second founder session is planned. Legacy generation keys stay distinct if
different old keys exist for one prefix; the immutable binding selects by input
key/ciphertext digest. Header count alone does not prove the recipient identity.
Deduplicate identical inputs by digest only; retain all provenance. Agent freezes
this local plan before the founder command. Both recipients are public: founder
from pinned run.py FOUNDER_RECIPIENT (c.recipient for normal sealing), VM from
factory/control-recipient.txt, equal to the plan and approved manifest. The
founder command takes --plan PATH --plan-sha256 HEX; rejects digest or recipient
mismatch before prompting. No discovery silently adds inputs. Plan modifications
require a new explicit digest. The survey records VM public key derived read-only with age-keygen -y on the
VM; agent verified equality to tracked recipient before freezing the plan, and
command requires plan.vm_restore_recipient equal both. No founder key is used
for this probe.

`tools/migrate-legacy-checkpoints.sh --plan PATH --plan-sha256 HEX --dry-run`
prints 30 archive-migration prefixes (48 unique archive variants, 3,251,961,841
bytes in current survey), 16 key-only rewrap prefixes, the absent-card exception,
ciphertext paths/sizes, output space and conservative time. Reencrypt estimate
= four full crypto passes at 10 MiB/s for unkeyed archive bytes; rewrap estimate
= 1 second per key plus VM verification cost (two read passes of its unchanged
archives at 10 MiB/s), reported separately. No full reencrypt of keyed archives. It
requires no identity, writes no generation, and fails if disk free < sum of archive-reencrypt
input sizes + 10% + keywrap output sizes + 64 MiB. Agent provides that exact command/digest to founder;
run the same command without --dry-run to migrate. Wrapper uses caffeinate -i
on Mac; absence refuses real migration. Python sets RLIMIT_CORE=0, umask 077,
requires TTY and treats GetPassWarning as error. Acquire one migration lock; open
inputs O_NOFOLLOW, verify regular file/owner and every planned digest before
prompt; reuse those open descriptors during crypto. Derive founder public key
with age-keygen -y on stdin and require exact pinned match before decryption.
No key value appears in diagnostics.

For archive-migration entries, one temporary in-memory case key per case prefix encrypts all its checkpoint,
final and divergent variants. This fits existing prefix.casekey.age semantics.
Capture age-keygen in memory; wrap that key to founder+VM. On replay use the
already verified wrapped key (founder decrypt in memory), never silently generate
a different key for that prefix. No case key plaintext file on Mac. Generation
output at sealed/generations/<case>/<new-ciphertext-sha>/ contains archive.age,
casekey.age, original-card.json (byte-for-byte), projected-card.json (operational
new digest plus migration lineage), migration.json and manifest.json. No pointer
or flat original is changed by the founder command. A projected card grants
no new recovery eligibility. Historical frozen bundles retain their own bytes
and pins; future explicit authorized imports consume migration.json.

### Streaming acceptance and replay

Reuse unlock_sealed_audit.decrypt_one's age Popen/pass_fds pattern without its
extraction: ciphertext through /dev/fd/N, identity only on age -d stdin. Relay
bounded chunks from decrypt stdout to age -e stdin while hashing/counting and
validating gzip+tar structure without extraction (streaming reader with bounded
chunks, CRC/end-of-stream checked). This is structural validation only: regular
files, directories and normal link metadata are preserved, not extracted;
restore's existing case_permissions owns extraction security.
Encryption writes only ciphertext to a new staging directory. Acceptance requires
EOF from decrypt, exit 0 from original decrypt AND encrypt, and fsynced staged
archive. An authenticated partial reencrypt after a decrypt failure is discarded.
Verify staged decryptions with founder AND case identities each reach EOF, exit
0, match plaintext byte count and SHA. Verify founder unwrap of wrapped case key
equals generated identity; check two X25519 stanzas in archive and wrapped key.
A stanza count is supplemental, never recipient proof. VM verifies its own unwrap
before qualification/activation. Wrong VM recipient requires rewrapping keys only,
not reencrypting archives. Record recipients and validation booleans/digests in
immutable migration.json; never keys or plaintext.

All subprocesses have deadline max(1200, 2 + ceil(ciphertext_bytes / 262144)) seconds; on failure, SIGTERM
or KeyboardInterrupt kill/join owned children, clear identity/key byte buffers,
remove incomplete ciphertext staging and print a fixed safe failure code. Before
an output generation becomes discoverable fsync every member and directory then
rename the complete staging directory to its digest path. Replay verifies every
manifest, old-input digest and new-output digest, then skips complete entries.
Incomplete .migration-stage directories are never discoverable and may be removed
under the lock. Summary: migrated/failed/skipped, exit 0 all complete, 1 partial
failure, 2 invalid plan/preflight. Rerun exact command; prompt once on each real
run, skip verified generations, retain every original. No secrets on errors.

Agent, not founder, copies new ciphertext generations to VM after migration.
Before any VM mutation: complete read-only fleet pagination/controller ownership
check, prove no live/uncertain worker, record unit state and hashes, stop batch
dispatch/holder/resume timer, stage and verify generations. If ownership cannot
be proved, leave existing units running and delay activation; no refresh beneath
controllers. Record each change and exact reversal in batch-service-vm.md. VM
unwraps each casekey with scoped control.key into an age pipe, verifies archive
roundtrip by streaming hash (no case disk/print), uploads immutable R2 ciphertext
with PUT/GET hash proof and verifies card/key/manifest bindings. Original frozen
card references remain valid in historical storage. Do not bulk import cases.

Qualification test gains --inventory-root and --migration-plan modes: every
planned input has a verified immutable generation; zero unwrapped in the selected
migrated store; projected cards bind correct ciphertext; both recipient proofs
and R2 GET digest evidence required. Run required qualification on VM, archive
report, then atomically activate one migration catalog pointer listing all
qualified generation manifests. Default legacy flat inventory remains available
until consumers use that pointer. The 527,987,760-byte 1ad7fa checkpoint is ALREADY KEYED: only rewrap its
case key and verify its unchanged ciphertext on VM. Largest unkeyed input is
the 455,502,549-byte 18681d final. The large 1ad7fa sample is retired only from the active canonical pointer set if a newer
verified successor with unchanged accounting/lineage exists. Retain original and
migrated sample as historical evidence; qualification covers the full set and
active subset without requiring that sample to remain active. Rollback restores
previous catalog pointer; no unique artifact is deleted. Future authorized
manifest import is the restore consumer; migration grants no case-run authority.

Synthetic tests with throwaway keys satisfy the founder's requested crypto test;
reuse an existing saved public card/layout as plaintext metadata (disclosed test
input, not a newly generated case). Test truncated/corrupt tail, killed decrypt,
ENOSPC, wrong founder/VM recipient, plan mismatch, replay and dry-run no prompt.
These tests close no real-artifact row. New single-path and inventory-divergence
rows close only after the real VM qualification.

## Codex renewal and top-ups

Extend codex_login.py with host-only renewal using pinned Codex app-server:
initialize JSON-RPC, then account/read {refreshToken:true}, no inference turn.
Official API documents forced refresh in managed ChatGPT mode:
https://learn.chatgpt.com/docs/app-server#1-check-auth-state (checked Oct 30).
Local CLI is 0.164.0, so this is NOT yet proof of the worker/host pin 0.162.1.
Before increment 4, the addendum records a credential-free schema probe from
0.162.1 and a host refresh test; unsupported pin means row20 remains partial
and renewal cannot be enabled. Use managed auth on host, external-token mode
on workers. Host app-server uses owner-only /run/unbug-bench/codex-host on tmpfs,
with no transcripts. Serialize under a single host lock; refresh tokens remain in
VM owner-only encrypted credentials/RAM, never delivered to workers. Replace
host encrypted credentials at ~/.config/unbug-bench/codex-host.age atomically
after validation, sealed founder+VM, preserving rotated refresh authority. Persist
rotation before distribution; recover pending host state first after restart.
Activation prerequisite: founder provisions a refresh-capable Codex login and a
scoped R2 token in the existing dual-recipient secrets.age on VM once. Never
copy founder identity. R2 scope is only the batch generation object prefix;
bootstrap provisioning belongs to the reviewed addendum and uses existing
secret transport, never CLI args/env token contents. Existing host credential
file availability is not yet verified; no autonomous renewal claim until proven. If refresh needs interactive re-login, report top up / re-login;
do not claim revoked OAuth can always refresh automatically.

For every active worker, pipe worker_auth(auth) (refresh stripped) over existing
Boat stdin SSH into a 0600 sibling in /dev/shm/secrets, fsync, os.replace onto
codex-auth.json. Verify installed digest + validate lifetime metadata without
returning token bytes. Failed/uncertain deliveries remain queued; no healthy
observation until all active Codex workers acknowledge that revision. Then call
observe('codex-auth.json', healthy=True, observation_id=durable renewal UUID).
Same ID is reused after reply loss. Credential health is not a quota assertion.
For top-up, read provider credit metadata host-side, compare verified provider
receipt/balance increase, persist receipt ID then observe(pool,...). No timer
clears credit. TLS router uses A's unit, trusted certificate and RAM token;
credentials travel only existing encrypted/SSH transport, never router RPC.

## Money and status

interfaces §8 is part of this design and must be goldfish-reviewed here before
D relies on it. No new spend ledger. Admission/read/collection share the batch
lock; commitments survive failed publication and unknown workers. A local money
file copied to a worker is authenticated by frozen launch config and restore
ledger binding; users cannot increase it via public-card edits.

Install repo bin/unbug at /usr/local/bin/unbug (symlink to approved release);
implement `unbug status` with factory/batch_status.py per status.md exactly.
Read journal/manifest, one full Boat inventory, then one read-only progress.json
cat per running worker. Stopped card only if sha equals journal collected sha;
stale card ignored/flagged. Sealed requires G12 pass, no failed_gate, null/complete
stop. Paused/complete/rejected are known normal stops. Missing sources unreadable;
Boat failure produces boat unreadable, never false worker gone. Thresholds in one
table. Spend/rounds unknown show em dash, never guessed. Print counts, action flags,
one line/case and nothing needs you when empty. Balances come from Boat billing
and OpenRouter key info; under-one-day uses manifest daily projected need, missing
projection shows unknown, no fabricated threshold. No dashboard or alert service.

## Implementation increments, tests and rollout

1. Founder migration command (dual wrapping of migration outputs only), no VM mutations. Synthetic tests
exercise streaming roundtrip, wrong key, corrupt archive, failed encrypt,
immutable output replay, dry-run no prompt. Keep real rows open.
2. Money authority and durable journal/store; real saved public-card and E launch
receipt corpus plus fault injection around every persist/submit/collect boundary.
3. Holder/launcher dispatch, async reconciliation, VM restore, immutable outbox,
TTL/worker recovery and next-checkpoint release migration. Remove batch use of
coordinator's operator quota/three-action/legacy TTL rules; keep legacy controllers
until drained. For plumbing update, publish new approved release; checkpoint
migration binds old/new release and gate-version vector, preserving compatible
gates and spend. Switch only after old worker retirement; no live source patch.
4. Codex renewal transport, status, D hooks and A/D integration; real cards for
status (including deliberately edited running/journal inputs disclosed in test).
5. Practice qualification on real control VM + one real Boat worker at a time;
record worker/launch/generation/release IDs, model receipts, Boat cash and cleanup.

Every increment: full `uv run --with numpy --with scipy python -B tests/run.py`,
fresh read-only goldfish diff review, commit, report to parent; parent alone merges.
Rebase onto parent's merged A/D/E/C before final integration review. Reviews saved
verbatim as batch-service-design-N/diff-N.md, fixes appended. Interface review
gets interfaces-design-N.md as well. Never reject own blocking review finding.

Live qualification hard stops: one practice case only, maximum $3 model and $1
infra, enforce per-call conservative bounds/reserved Boat cash before creation;
no second worker until predecessor deleted and list proves absent. If installation
cannot fit the remaining envelope, stop and report rather than exceed it. Use
recorded structured provider denial from real logs, with fixed public event ID,
never force a real paid outage. Prove settled wait not charged/counted twice,
including wait → collect `total_spent_usd:null` with mapped admitted maxima →
retire → same-owner/same-revision resume from that generation → settle first →
finish. While unknown, assert the full old commitment stays held and no increase,
old+1 revision, replacement, diagnosis or extension is admitted. Also collect a
late actual receipt lowering a conservative total (for example10 to8), verify
its invocation ID against the immediately previous ACK's estimated map and its
`reconciled_decrease` record under increment2b.2, replay without double counting,
and refuse a decrease beyond the bounded rounding allowance without evidence.
Verify later valid revisions remain admissible and unused authority is released
only after terminal collection plus retirement. Record real denial/receipt IDs
and conservative charges; authored fault injections are labelled as such and
cannot alone close a real-artifact row. These assertions are required before
enabling continuations; increment2's fresh-only tests do not claim them.
restart service after checkpoint and after accepted launch before ACK, zero
capacity makes zero workers, relaunch uses collected card sha, finish unscored
infrastructure attempts and normal sealed result distinct. Include independent
retirement/deletion receipts. Never use a real exam case.

VM changes go in docs/reports/batch-service-vm.md with command, prior file hash,
new hash, service state and exact reversal; use versioned staged directories,
backup policy/units, atomic switch and rollback. No VM source refresh under live
holder/controllers. Read-only VM survey found 46 checkpoints, 30 unwrapped,
control key present and system holder/resume timer active on 2026-10-30; do not
stop those without proving no active ownership. No real VM mutation yet.

Risks: service-host outage delays progress but loses no acknowledged generation;
R2 outage blocks new paid units; OAuth revocation may require founder login;
legacy migration remains external until founder executes approved command.
These are visible bounded states, not claims of completed unattended operation.

## Plain-language delivery and deletion plan

The founder gets a batch that runs to completion with the Mac off. Today only
launch/controller ownership is durable; this design adds standing scheduling,
money admission, collection/publication and host credential upkeep. Estimated
effort: five to eight implementation/review sessions after A/D prerequisites,
plus one founder migration session; not a completion-date promise while those
prerequisites are absent. Increment 1 target Oct 30 (migration crypto/replay exam);
2 Oct 31 (crash-safe money and pointer exam); 3 Nov 1–2 (no duplicate worker
after lost reply/TTL exam); 4 Nov 3 (renewal/status and D settlement exam);
5 Nov 4–6 (bounded real VM/Boat practice lifecycle). Costs: offline work launches
no models/workers; practice maximum $3 model + $1 infra. Reviewer-agent costs are
not measured by batch receipts and are excluded from those live-test figures.
If live qualification hits a cap: cancel/checkpoint if possible, collect, delete
worker, prove deletion, record failed/unscored qualification and actual costs on
infra-waste reporting; do not exceed the bound or claim rows closed.

Delete: batch use of ttl_continuation's three-attempt/24h ceilings; coordinator
operator quota observations and three-action recovery limits (A removes scheduling
first); synchronous launch work from holder socket loop; batch legacy founder-only
restore refusal; worker mutable R2 object uploads and optional durability;
restore_sync.py bundle publisher after old controllers drain and invariant tests
move to generation-store tests. Preserve frozen historical bundles as evidence.
Delete batch.bind max_cost validation/cap emission for authenticated batch jobs.
Remove legacy streaming restore only after every real input qualifies; no deletion
on design approval. There is no .pre-vmkey or partial-swap journal in this design.

Umbrella approval covers all B contracts. Before coding increment 3, append and
review exact holder/restore predicate and next-checkpoint release migration
protocol details; before increment 4 append/review the verified pinned Codex
refresh probe and scoped credential rollout. Those reviews are required gates,
not claims that unspecified details are ready to implement.

## Increment 1 rewrap layout and scope (round 3 clarification)

One immutable rewrap generation per prefix and original key digest lives at
`sealed/generations/<case>/key-<old-key-sha256>/`: casekey.age (founder+VM),
original-card.json (byte-for-byte), migration.json, manifest.json. It contains
no archive.age and no projected card. migration.json binds plan digest, original
key digest, every archives[] ciphertext digest/size unchanged, recipients and
validation booleans. Replay skips only after every output manifest digest and
old key digest verifies. New founder unwrap must equal byte-for-byte the
in-memory unwrap of the original wrapper. VM qualification unwraps with its
scoped identity and stream-decrypts every listed unchanged archive to EOF; no
projected-card test is applied to rewrap entries. Stanza count is supplemental;
an original founder unwrap failure fails that entry with exit1, reports it as
VM-unrestorable and continues all other entries.

Throwaway-key tests include single-stanza key → dual wrapper, both identities
recover identical key bytes, new key opens unchanged archive, originals unchanged,
cache-sourced VM-only input, completed-rewrap replay, and card_bound_absent
(original card preserved, projected bound_archive.status=absent, cannot activate).
Add sealed/generations/**/archive.age to .gitignore in increment1.

Increment1 does not change r2_upload.case_recipient or seal any live case. New
case dual wrapping ships with increment2's manifest wiring, before B enablement.
A founder-only wrapper created after the frozen survey is a known input requiring
a new explicit plan; never silently include it or claim the current plan covers
it. No batches run between A and completed B as interfaces §6 requires.

## Stream D integration assertions (founder amendment adopted)

Parent reports ENGINEERING §3 amended after 72d5c8f: extensions draw from the
founder-set cumulative batch bound through §8; no fixed $15 allowance. Earlier
verbatim reviews describe the old rule as historical review context only.

Before G10/exam-gate relaunch, the VM checks both tester and reviewer effective
route capacity. Map routes to pools using the pinned router config plus live
status; when the pools coincide require two free slots in that pool. Capacity
reads are advisory, so a race may still wait after launch; retain D's tester
reservation and conservative charge, never refund it as zero or book it twice.

Practice end-to-end test must explicitly assert: reviewer capacity zero while
tester is free creates no worker; tester zero while reviewer free creates no
worker; shared pool needs two slots; both available allows one predecessor-
retired relaunch. Evidence records owner-admission wait IDs, parent tester lease/
operation IDs, duration, settled known usage and conservative gap charges, with
event/wait-ID deduplication on replay. Qualification reports those waits/charges
even if nonzero, rather than hiding held tester capacity behind a success label.
Real provider denial/receipt artifacts are required for closure; authored zero-
capacity inputs alone prove scheduling invariants, not production throughput.

Worker money delivery/context installation is specified in interfaces §8's
"Worker installation and D's context". Increment2 supplies job_config.install
and the two launcher SHA-pinned config flags, checkpointed job-money state and
verified revision transitions, before D is enabled. D's attribute names are
unchanged; current binding fields never originate from restored files.

## Increment 2 addendum: money and the worker context

This increment supplies interfaces§8 end-to-end through the existing synchronous
holder/launcher. It does not enable batches, change the provider-wait flag,
relax control-key restore refusal, or implement the async holder protocol.
Generation-store/journal/outbox implementation follows as increment2b; all
restore dispatch remains gated on the later reviewed holder predicate. No VM
mutation or real case run in this increment.

### Files and authority

Add factory/batch_money.py and factory/job_config.py. Change batch.py,
key_holder.py, launch.sh, run.py, run_artifacts.py, r2_upload.py and the shared
launch_manifest.py. Tests: tests/factory/test_batch_money.py and
test_job_config.py plus existing batch/launcher/key wrapping suites. No new
service, dependency or spend-booking API. Reuse registry.atomic_json, holder
private directory checks and D's job_authority.read/for_case (after D merges).

The tracked factory/batches/<id>.json manifest is pinned as already specified.
batch.bind stays pure: validate manifest/release/job and derive args; never
reserve funds merely while policy_load validates every job. Manifest jobs omit
max_cost, bind stops emitting it. Legacy non-batch paths retain their existing
cost field/validation. New-schema holder recovery ignores max_cost only when
job is manifest-bound batch work with verified money authority; no global bypass.
D's authenticated path passes max_cost=None to the budget runner; run.py's legacy
default5 remains for non-factory work. No batch is enabled before D supplies
that path, so removing bind's emission cannot silently reintroduce a paid cap.

Under batches/<id>/lock, batch_money.authorize(policy,job,source_generation)
loads/creates money.json (schema1, batch/manifest digest, jobs map). Each job has
case, its nine-field authority, last acknowledged cumulative total (decimal
string, initially0), source generation. Job+source is the idempotency key; no independent request
identity field. Terminal/retirement collection state is deferred to increment2b. No events/costs are booked here. Project each committed authority to
batch-money/<batch>/jobs/<job>.json. money.json is authoritative; persist/fsync
it before projection. Startup/retry repairs projections from that state before
returning a config; a stale projection can only refuse admission.

Initial authorization uses manifest job.requested_total_usd. Require sum over
jobs of max(latest acknowledged total, committed_total_usd) <= money_limit_usd.
Reserve before holder's uncertain process start and retain on unknown outcome.
An insufficient request returns money_wait without launching. All dollar math
is exact USD to9 places (integer nanodollars internally), rounding nonnegative historical numbers upward;
reject nonfinite/negative/unknown new money. Batch deadline is absoluteUTC.
Reservation UUID4 is durable per job; revision starts1. Same job/source/request
replay is byte-identical. In this increment authorize refuses every source value
different from its stored value, and every non-null source for a new job, as
money_wait. Revision advancement and its proof format belong to2b; no dead
production branch or invented proof parameter. Installer revision tests directly
author old/new channels and current RAM bindings, without issuing a fake grant.
An existing job never gains money merely by repeating launch or changing stage.

For this increment, only fresh job funding can succeed. Source-changing
continuations are refused until2b's acknowledged-generation/retirement contract
is reviewed and implemented. Tests author channel pairs for the installer, not
a pretend authorization receipt.

Future collection updates preserve the same aggregate: replace a job's latest
verified cumulative total, never add it. Unsettled new-schema provider waits
or crashes may continue at the same owner and revision, with the same or lower
operating commitment, only when every unknown part maps to an unpriced invocation
or wait with an admitted maximum and verified coverage fits the old full held
commitment. Count that owner once at the old full commitment, retaining it even
if the operating commitment is lower. Unknown legacy usage never qualifies.
No increase, old+1 revision, replacement, diagnosis or extension is admitted while
this owner's total is unknown. Settle runs first on the permitted resume.
Increment2b must authenticate retirement/collection and perform a same-revision
source rebind to the exact restored generation, advancing the persisted channel
before D checks equality with RAM authority. This requires history keyed by
reservation/revision/source, not a new monetary grant. No extra money is granted,
released or transferred while totals are unknown.

A late actual receipt may lower a conservative cumulative total. Apply the
concrete increment2b.2 rule: the invocation was estimated in the immediately
previous ACK and is settled now; a pending/unpriced row supplies no decrease
record. Identity is invocation_id, never wait_id. Record qualified releases,
old/new totals, generation and receipt digest idempotently. Replace the latest
total without a refund event. Decreases beyond the defined rounding allowance
need qualifying records. Only terminal+retired+settled proof may release
unused commitment; no missing/unreachable worker releases it. These are the
binding interfaces§8 collection rules for2b, not implemented by this fresh-only
increment. Review their concrete coverage/receipt proof inputs with collection
before enabling continuations.

### Host configuration and delivery

After all existing launch refusals, immediately after attest_launch and before
consumed.add(stamp), the holder obtains the channel via batch_money.authorize, mapping holder's fresh generation 'new' to
source_generation=None. Build exactly interfaces§8's root config;
write immutable configs/<sha256>.json under the batch state directory. Append
the two host --factory-job-config / --factory-job-config-sha256 flags to the
bound launcher argv; callers cannot override them in job.args. Existing launch
state freezes argv and the host config digest across restart. No new launch API.

launch.sh parses these host flags before forwarding runner args, checks the
config bytes/hash before creation, requiring config.case_id==--case-id,
config.source_generation==--checkpoint-sha256 (null iff no checkpoint), and
config.batch_release_sha256==--batch-sha256. Refuse before creating a worker if
any differs. The RAM source_generation is trusted only through these checks.
Then streams the public
config over Boat stdin SSH after source qualification, into a0600 sibling under
/dev/shm/secrets. Verify SHA there, fsync and replace factory-job.json. Runner
gets the same flag names with the RAM path and trusted expected digest. No
refresh token/key is in this file. No copies under a model/contestant home.

### Installer and resume

job_config.install(c,args) is mandatory when args.batch_release_sha256 is set;
one or both missing config flags refuse before model work. It opens RAM config
O_NOFOLLOW and checks regular/owner0600, SHA, exact root schema, case_id==
c.case_id derived from argv and release SHA against HOME/batch-release.json.
Read the tracked manifest from ~/factory/batches/<batch_id>.json (the installed
factory root beside run.py, not the duplicate BENCH copy), require
its SHA==config.manifest_sha256, source commit's public source manifest binding,
restore recipient==tracked control-recipient and matching job/case. Require
job_money.committed_total_usd<=manifest.money_limit_usd and exact deadline
equality; do not require equality to initial requested_total_usd, since later
serialized grants may exceed that request. Add factory/batches/*.json to
WORKER_GLOBS, including token-free manifest/router files. The exact public source
binding is worker-release-manifest.files[manifest_relative_path] ==
config.manifest_sha256, after existing worker-release verification.
Call D's read(channel,channel) only AFTER these independent authentication checks.
The holder's pinned file SHA, not this equality check, authenticates authority.

Place install in run.py's ordinary startup try block after the existing
late_recovery.authenticate_gates (resume), or at that same point (fresh), before
raised_limits, restore_gate_crash and any model call. c.work/c.ledger/prev_card
and founder_ruling.context already exist. record_founder_decisions may remain
before it: that function checks call limits/writes rulings and makes no model
call. Do not move or duplicate gate authentication.
Audit/legacy non-batch flows keep existing behaviour and get no invented grant.
B supplies c.authenticated_job_config, c.batch_id/job_id/batch_deadline/
source_generation from current RAM bytes and a separate c.job_money as §8 says.
Persist new-case job-money.json atomically before D can reserve any invocation.

On resume require job-money.json from the authenticated checkpoint. Parse old
channel separately; validate owner/case/reservation/deadline unchanged, current
revision >= old revision, and current amount >= old total authority. Same revision
requires byte-equivalent channel (canonical JSON bytes) and source; a changed
revision must be exactly old+1 and root source_generation must equal the
launcher-verified collected checkpoint. Append idempotent history keyed by
reservation_id/revision: {old,new,config_sha256,source_generation}. Fsync history
then atomically replace job-money.json; D admission follows only both writes.
Crash before checkpoint loses both together; same local replay repairs the
history/file pair without a second grant. Model calls never happen in the gap.
Older file revision, mismatched owner/source, lowered amount or same-revision
different bytes => money_wait, no call. A prior retired_batch_bound never revives.
These are increment2's implemented restrictions. Increment2b must add the
reviewed conservative same-revision source transition described above; it is the
only planned exception to same-revision byte equality and the no-lowered-amount
rule. It retains the old full host hold and keeps independent RAM provenance.

Legacy-import assignment is NOT implemented or allowed here: a restored archive
without job-money.json refuses money_wait even when given a current config.
G2's future import-record format must get its own reviewed addendum before any
legacy case is assigned. The existing22 historical cases remain read-only;
key migration/VM decrypt qualification does not authorize their execution.

### New keys and tests

Only authenticated batch sealing (args.batch_release_sha256 set) adds the VM
recipient in r2_upload.case_recipient, read from installed tracked
control-recipient.txt. Non-batch/audit flows retain founder-only wrapping; batch installer verifies equality
to the pinned manifest. Add the public file to WORKER_CONFIG and both new host
modules to the shared trusted manifest. Missing/malformed VM recipient fails
batch sealing; no unwrapped new batch checkpoint. Archive still founder+case,
no VM identity on a worker. Test with an explicit throwaway VM recipient,
retaining existing founder/case decrypt proofs and no real identities. In-place
restart sends no new config: it reuses existing RAM bytes and identical flags,
so installer treats it as a same-revision, byte-equivalent replay.

Tests exercise fresh funding, two concurrent reservations under one bound,
replay after money.json-before-projection crash, expiry/no headroom, no cost
reset on resume, tampered config SHA/mode/case/source and missing mandatory
flags, separate object identity, exact same-revision replay and mismatch,
old+1 revision history repair, lowered/stale authority and legacy-file absence.
Use saved real public cards/receipts as accounting metadata, not generated cases.
Integration tests must call actual D job_authority.for_case for fresh install,
revision bump, stale revision and non-equivalent same-revision replay. No stub
consumer counts as this proof. If D is not yet merged, run against its actual
reviewed module in an isolated process, record branch/SHA, and repeat in the
merged tree before enablement. No skip authorizes enablement. Full suite and
fresh goldfish diff review are mandatory before parent merges this increment.

## Increment2b scheduling hook for D

Use this service's existing durable admission queue and `launch(batch, job,
checkpoint_or_empty)` for all job kinds. No second launcher or service. Requests
carry the original owner, source generation and stable request ID; persist queue
sequence and deduplicate before launch. Covered same-owner/same-revision resumes
that can settle unknown usage go first, then replacements, same-owner exhaustion
resumes, extensions and ordinary work, FIFO within each class. Blocked requests
retain their place without blocking later eligible requests. Capacity, deadline
and money admission still apply. Rebind starts at the current persisted source
and advances along acknowledged collection lineage; stale A→B→A refuses.
The extension priority class comes only from a verified same-owner section8
money_wait.priority request. It is money scheduling metadata, not extension
eligibility. Without such a request, use ordinary continuation priority; never
infer the class from close_to_passing or another public outcome.

Diagnosis adds no launch mode, flags or frozen-config fields. B uses D's pure
diagnostic predicates (consistency checks only) and content-free pending-diagnosis
projection, not a predicate re-derived from public stop labels/spend/counters.
B relaunches the exhausted original through the ordinary same-owner launch;
the worker reads its authenticated restored card, settles, requires a known
total and then D runs the read-only diagnosis with the original money owner.
No diagnosis call is admitted while usage is unknown. A known settled checkpoint
must reach B's verified collection/ACK before dependent replacement admission;
that acknowledgment does not wait for the diagnosis result. This uses the
existing checkpoint/collect path, not another launcher or a host-side settler:
if the exhausted owner's total was unknown at launch, D checkpoints and exits
after settlement without a model call; collection/ACK follows, and diagnosis
runs on the next ordinary same-owner relaunch. The worker decides this from its
authenticated restored state and D projection; B adds no mode/config field.
Unknown-total exhaustion resumes are in the first settlement class; known-total
ones are in the exhaustion/diagnosis resume class.

Apply the one-child journal first. First derivation requires a present D
pending_projection with replacement_eligible exactly true; None never permits
derivation, regardless of exhaustion or actual_model_work. Never wait for
diagnosis or recreate D's stop predicates in B.
Unknown original totals still block replacement admission until settlement.
Extensions preserve the original owner. D alone decides count/package/progress
eligibility and starts an admitted extension in the same worker. B schedules
ordinary continuations and handles authenticated money_wait requests under
interfaces section 8; it never decides an extension and needs no extension
projection. Any revision/increase follows section 8's money admission, collection
and retirement rules, never a close_to_passing label on a public card.

### Authorized replacement chains

The manifest roots are templates, not a finite work queue. Its pinned
replacement_policy:{schema:1,enabled:true} explicitly authorizes derived jobs;
absent/disabled refuses them. Increment2b's check_manifest validates the exact
replacement_policy keys/types {schema:1,enabled:bool}. Root job names forbid the
terminal -r<digits> suffix, including -r01; derived ordinals are canonical positive
decimal without leading zeros. Root J yields J-r1, whose one replacement
is J-r2, and so on, with case-<batch>-<job> case IDs. No root may use that suffix,
so template lookup and child identity are unambiguous. Each child inherits the
root's approved source/roles/non-money args and initial requested authority;
it has a distinct cumulative money owner and reservation.

Under the batch lock, journal derivation binds parent case/job, root job,
ordinal, child case/job and D's eligible collected generation before reservation.
The deduplication key is the immediate parent case, not generation or extension.
Replay returns its already-recorded child, even when the parent is collected or
extended again. A child that D later declares eligible may itself yield one
child. The same pure template resolver is used by batch.bind, holder, batch_money
and job_config.install; holder admission additionally requires the journal-bound
derivation and D eligibility. Do not mutate the frozen manifest/policy jobs map
or change the existing RAM config shape to represent these jobs.

Increment2b removes both check_manifest's and key_holder.policy_load's current
<=len(jobs) restrictions. Replace direct derived-job lookups in batch.bind,
key_holder.serve (all policy['jobs'] lookups, including policy['jobs'][name] and
orphan-resume policy_job membership), batch_money.channel/authorize and
job_config.install (record['jobs'][job_id]) with the shared resolver before
derived work is enabled. Keep manifest.jobs==policy.jobs as the root-map check.
target_slots remains the reporting goal; max_concurrency
is a simultaneous-worker bound independent of root count. No hidden chain cap
comes from manifest job count, replacement count or number of sealed candidates.
The cumulative batch bound and deadline limit total derived work; capacity and
verified retirement constrain dispatch as usual. Both sealed originals and
replacements are retained under ENGINEERING§3.

Tests: root-only manifest, max_concurrency greater than root count, J→J-r1→J-r2,
deterministic IDs and distinct owners, once per parent despite generation and
extension replays, actual-work eligibility including denied-zero and zero-cash,
FIFO/eligible bypass, settlement resume ahead of a blocked replacement, known
settlement checkpoint/exit and collection ACK without waiting for diagnosis,
then an ordinary same-owner diagnosis relaunch, same-owner extension,
and refusal at money/deadline. Actual eligibility calls use D's implementation;
until its concrete adapter and tests pass, derived/diagnosis integration stays
disabled. This is planned2b scope, not authority granted by increment2.

## Increment2b.1: verified collection journal and draft D queue adapter

Problem: D now supplies concrete draft projection signatures, but no durable
queue binds those facts to the exact collected generation. Implement that core
before holder/restore enablement. This increment issues no money transitions,
submits no launch and changes no VM state. It builds toward rows6,27,28,51 and
the D lifecycle seam; it closes none without the later real VM/Boat exam.

Add factory/batch_service.py, using existing batch_money.manifest/locked,
collection.verify, transfer.digest and registry.atomic_json. No new dependency,
daemon, CLI launcher or spend ledger. Add it to TRUSTED_FILES so eventual host
imports stay fingerprinted, and the explicit independent worker-file test list.
The existing factory/*.py worker inventory already includes it.

`collect(policy, root, home, job, directory)` verifies the manifest/release via
batch_money.manifest and resolves the root or already-journal-derived job. It
copies only launch_manifest.collection_files(case) members to a private stage
under batches/<batch>/generations/<case>/. Required: the exact card-bound archive,
scorecard and casekey. Refuse symlinks/nonregular files, foreign names/case/release,
checkpoint_error, missing key, conflicting generations or hash mismatch. Hash
each copied member, fsync it, then reuse collection.verify on the staged copy;
require verify to return exactly {case}. A statement_cipher_sha256 or
public_search.cipher_sha256 reference requires statement.age or search.age,
respectively, and its bytes must match; a missing referenced file refuses.
statement_sha256 is plaintext and is never compared to ciphertext. Preserve
unreferenced companions too, but exclude the alternative archive not bound by
this card. Without an archive field, the unique archive matching card.sha256 is
the bound archive. Ignore other cases in the source directory; never rewrite sources.
No decryption.

Publish by fsynced atomic rename to <generation>/ with manifest.json containing
schema1,batch,job,case,generation,batch_release_sha256 and a files map of filename
to {sha256,size}. This is a local verified snapshot, not an R2/durability or money
ACK. An existing generation must match the manifest and all member bytes exactly;
changed card/key/companion bytes at the same generation refuse. A rename-before-
journal crash is repaired by replaying collect. No current pointer is written.

Under the same batch lock, journal.json has schema1,batch,manifest_sha256,
entries,derivations,queue,next_sequence. Entries keyed case+'/'+generation have
job,case,generation,manifest_sha256,state:'pending',facts:null. facts is null or
{exhaustion:bool,actual_model_work:bool,pending_projection:None|projection}; null
alone means unplanned, so a legitimate None projection still replays. They point to
the immutable verified snapshot; projection never arrives as a caller argument.
Re-read/verify snapshot manifest+members on replay/planning. Bad state/manifest
or missing/corrupt snapshot refuses; no silent reset of existing state.
This concrete schema supersedes the earlier illustrative journal shape for this
increment; fresh launch/operation fields wait for the holder addendum.

Implement pure `resolve_job(manifest, job_id)` alongside this queue core: return
the approved root template with deterministic case ID, root ID and ordinal.
Every collect/plan resolves root jobs too. It validates the reviewed
replacement-policy/suffix grammar and supports J-rN
with no count cap; the finite map is roots only. It grants no admission. Actual
collection of a derived job additionally requires its recorded parent derivation.
Do not yet change holder/bind/installer or the fresh-only money authorizer: their
derived-job and source-transition restrictions remain until the complete2b/3
integration addendum. The final shared resolver replaces their listed root-only
lookups before enablement; no copied replacement-eligibility logic.

`plan(policy, root, home, case, generation, now=None)` loads only that journal's verified
snapshot card. Production D adapter gate is a tracked False constant, not an
environment flag. While false, plan returns diagnosis_unavailable without
importing D or creating requests. Behind it, lazily import diagnosis and call
exactly exhaustion(card), actual_model_work(card), pending_projection(card).
Require strict bool predicates, None or the exact schema1/pending/bool projection,
and unchanged input. Exceptions refuse this entry. D's host module and local
dependencies must enter the trusted import closure in the activation review;
this increment never loads that draft module in production.

Activation prerequisite from reviewed D section8: before using any D facts for
projection-based scheduling, the collected card must have a top-level
diagnosis_state object, or an authenticated explicit import/migration record.
No such import-record format is accepted by this increment. Missing/non-object
diagnosis_state therefore refuses planning with legacy_projection_unbound,
leaving facts and queue unchanged, including for entries collected while the
adapter was off. This is provenance checking, not a copied stop predicate;
D still owns validation of the object's contents. It creates no legacy resume
as a way around import. Existing independently authorized work is unaffected.
Implement and test this gate before adapter activation; 2b.1's authored API
tests alone are not evidence that this later prerequisite is implemented.

Use a pure projection wrapper and queue transition for authored contract tests;
they cannot issue money or launch. Persist D's returned facts bound to the entry
key. Parent ruling 2026-10-30: first derivation requires a present pending
projection with replacement_eligible:true, with both predicates true as the
contract consistency check. A None projection never creates a child, whatever
the predicates say; B does not copy D's stop predicates. Queue an ordinary
same-owner resume, after the provenance gate above, when pending_projection is present or the exhausted total is
unknown as below. This combines D's API
answers; B never inspects events/tokens/receipts to recreate eligibility. Preserve
the original API projection verbatim in the journal. replacement_eligible:true
with either predicate false refuses as a D contract violation. An exhausted
parent that passes that provenance gate and whose case_budget.total_spent_usd is null or absent always gets the
same-owner settlement resume, even when pending_projection is None. This is the
only total field B reads; missing case_budget or total is unknown, never zero.
Stored facts win on
replay: return them and existing queue metadata without calling D or overwriting
facts. Launch state stays pending; facts, derivation and requests are persisted
atomically in one journal replacement.

Derivations keyed immediate parent case bind parent job/case, root job, ordinal,
child job/case and eligible generation. Compute child ordinal parent+1 and persist
before requests. Replays return the same child across generations/extensions;
an already-claimed child ID or changed lineage refuses. Queue dedup keys are
replacement/<parent-case> and resume/<case>/<generation>; record kind, job, case,
source_generation (null for child), owner_job, parent_case, sequence and reason.
Unknown-total parent: enqueue child but mark unknown_total; same-owner resume
has settlement priority. Known-total pending diagnosis gets exhaustion priority.
Only distinguish null/known total for scheduling; do not value usage or validate
financial coverage here. Monetary admission/retirement/R2 ACK remain unverified,
so this core exposes ordered queue metadata only, no ready/dispatch/grant API.
Future admission checks those proofs before launch.
Under interfaces §8, unknown legacy/unpriced usage without mapped admitted maxima
refuses conservative admission; the queue alone cannot authorize its resume.
Only D's authenticated coverage within the held commitment can admit it, and
settlement must produce a known checkpoint before any dependent model work.
No extra attempt or call-count cap is introduced to handle missing coverage.
Order settlement, replacement, exhaustion resume, extension, ordinary; FIFO
sequence survives restart. Blocked
entries retain their order and cannot prevent later eligible dispatch in that
future dispatcher. Deadline-expired planning refuses new requests using injected
now or time.time(), as batch_money.authorize does. Cumulative calls are telemetry;
no call-count admission rule is added. Money/deadline and per-invocation limits
remain the bounds.

Tests: saved public card metadata/ciphertext, clearly labelled authored batch
wrong case/release, symlink, immutable collision, interrupted publication/journal
repair, journal restart and generation binding. A recording draft API proves
all three signatures, purity/schema refusal, absent projection and denied-zero
answer handling; it tests the adapter contract, not D's eligibility predicate.
Also test unreferenced companion ciphertext, unbound archive exclusion, unknown
exhausted total with absent projection, and replay without re-calling a changed
draft module. Gate-off must not import or call draft D. Root-only manifest resolves a two-child
chain; replay at another generation creates no second child, lineage collisions
refuse, source config shape is untouched, queue priorities/dedup and deadline
hold. Run actual D implementation once its reviewed increment lands; absence
now is an explicit enablement blocker, never a passing D integration claim.
Name checks for contradictory eligible:true/false predicates and deadline-expired
plan with injected now. Neither can create a request.

Delete nothing from legacy live controllers yet; this replaces no launch path.
Full suite, fresh diff review and parent merge precede further integration.
The outbox, pointer activation, monetary collection proofs, source transitions,
capacity dispatch and holder/scoped-restore addendum remain next work.

## Increment2b.2: D collection accounting proofs

Status: final integration design against D increment3a, reviewed code 9cb25e6
merged into factory-simplify at cfe616f. B rebased onto cfe616f. The exact APIs
are in factory/budget.py and factory/diagnosis.py; producer replay fixtures are
tests/factory/test_stream_d_coverage.py, tests/factory/test_stream_d.py and
projection fixtures tests/factory/test_stream_d_projection.py at that merge.
Design13 passed the earlier contract. Design14 found two implementation-readiness
issues; fresh design15 passes the resolutions below.
DIAGNOSIS_ENABLED stays False until the later activation review and practice
qualification. This increment implements the offline accounting consumer and
real-D projection regressions, not money ACK, holder, outbox or resume authority.

The provenance gate runs after snapshot verification and the disabled-adapter
check, before the deadline check and stored-facts replay or importing/calling D. Every card without
an object diagnosis_state refuses legacy_projection_unbound while enabled,
including non-exhausted cards; no request is lost and the label is an internal
refusal, not a public status. D validates object contents. A malformed object returns exhaustion:false and
pending_projection:None, so B queues neither settlement nor diagnosis nor a child,
for both known and unknown totals. B never infers exhaustion itself. This can
strand the owner's hold; new-batch-service-3 records the activation prerequisite
for a durable holder incident/freeze and evidence-backed recovery. The gate also
refuses new non-exhausted cards without diagnosis_state; activation must review
that classification before enabling. Adapter-off returns diagnosis_unavailable
even for stored facts; the gate never replays those facts while disabled.
Regressions pin these behaviors and unchanged journal bytes on provenance refusal. Use the shared total normalization helper in
_enqueue solely to distinguish unknown from known, including case_budget:null;
this replaces its unsafe .get chain, with no accounting/admission wiring.

Problem: increment2b.1 authenticates local snapshot bytes and schedules opaque D
answers, but cannot justify a null total or a lower cumulative total. The
fresh-only money channel correctly refuses source changes. D now defines the
missing accountant evidence, so B can specify its consumer without duplicating
D's event attribution or inferring eligibility from stop labels.

This increment is an offline proof consumer, not the holder/outbox activation.
Add factory/batch_accounting.py with one pure function:
collection_facts(card, previous, held, accountant). It returns the next public
accounting checkpoint described below or raises ValueError with a fixed refusal
label. The fixed labels are invalid_accounting_input, accounting_api_refused,
malformed_reconciliation, unsupported_decrease and uncovered_total. accountant
is the reviewed budget module in production and an explicitly authored API
double only in contract tests. This injectable seam exists to test purity and
malformed API results while D is not integrated; remove double-only checks when
real-D tests cover the same refusals. No file, network, clock, environment,
model, crypto or money mutation occurs in this function. Existing
batch_money.amount supplies exact integer nanodollar validation. Reuse D's
case_spending and usage_coverage; do not add a tariff, event join, receipt reader,
spend ledger or new caller-supplied proof endpoint.

The future locked ACK path, not an external requester, supplies card from
batch_service._snapshot and supplies previous and held from durable host money
state. In this offline increment inputs are built ONLY by tests; no existing
money row feeds this function and no ACK is persisted. These are internal
verified inputs in the eventual composition; the pure function cannot authenticate
their provenance or authorize a launch. The next subsection fixes this boundary,
so a passing pure test cannot be misreported as authenticated resume support.

### Verified inputs and host composition

The card is exactly the immutable public scorecard pinned by the selected
(case, output generation) journal entry. Its continuation_budget is D's public
ledger, including invocation_reservations, unpriced_invocations, events,
wait_settlements and reconciled_decreases. There is no separate public
usage_coverage field to trust or persist. The output generation is the enclosing
snapshot digest, never a field injected into D's ledger or records.

For eventual ACK, B must additionally bind this output to its own frozen launch
operation: batch/job/case/reservation/revision/deadline and that worker's input
source_generation come from the holder's authenticated configuration and durable
operation record. Compare the configuration's full nine-field job_money with the
held authority used for that operation. Never infer the input generation from
the output digest, a file timestamp, a worker's proposed grant or D's projection.
The holder operation/output binding and retirement evidence formats are still
part of the required holder addendum, not invented D card fields. No ACK
entrypoint or source-changing authorize branch is added in this offline increment.

held is the full unreleased committed_total_usd string for this owner. The future
money row must retain that value separately if it delivers a lower operating
commitment. previous is exactly {total_usd, estimated}, where total_usd is null
or a canonical nine-place string, and estimated maps canonical UUID4 invocation
IDs to canonical nonnegative nine-place estimated_gap_usd strings. Validate all
these shapes and values even though the eventual caller reads trusted state.
Initial fresh authority has previous={total_usd:"0.000000000",estimated:{}}.
An existing schema1 row may map to that initial input only if its validated
authority has revision1 and source_generation:null, collected_total_usd is
exactly "0.000000000", and the complete host operation/collection history proves
no prior ACK. Missing/ambiguous history refuses; it is not a zero-spend default.
Other old rows require an explicit reviewed migration and cannot be guessed.
The holder addendum must specify and review the versioned money-row migration,
nullable ACK writer, estimated map, retained full hold and incident state before
this function is wired. authorize currently writes none of these. This consumer
does not make legacy cases executable.

Known totals are read from case_budget.total_spent_usd; missing case_budget,
null case_budget, missing total or null total means unknown. Any other non-object
case_budget refuses. Normalize finite, nonnegative JSON numbers/decimal strings
through Decimal(str(value)), rounding upward once to nine places; bool,
nonfinite or negative values refuse. Call accountant.case_spending on an
unchanged copy of continuation_budget, require its total to agree after the same
normalization with the card total (including null), and reject malformed ledgers.
Do not sum the reported ordinary and waste subtotals in B. A missing/non-object
continuation_budget refuses accounting even if the scheduler can display it.
Put the total normalization in one batch_accounting helper; eventual _enqueue
wiring must use that helper too, fixing its current null-case_budget exception.
Only that normalization helper is shared with _enqueue in this increment;
no monetary proof or admission wiring is added. Both card and API total are
normalized upward from their reported values; a historical higher-precision
card disagreeing with D's rounded reported total refuses rather than guessing.

Only the consumed D record shapes and API result shapes have exact field sets;
do not impose a new closed schema on the entire historical ledger or card.
For invocation_reservations, use the existing lease-keyed map (absent means an
empty map, null/non-object refuses): every
row's lease_id must equal its key, invocation_id must be a canonical UUID4,
state must be pending/estimated/settled, and invocation_id must be unique across
ALL reservation rows, even if the repeated rows are identical. These public
identity/state checks do no event attribution or valuation.
The next estimated map contains precisely current state=estimated rows and their
validated estimated_gap_usd, including zero gaps. It replaces previous.estimated
on EVERY successful accounting checkpoint, even with a null total or no receipt.
No consumed-ID set or search of older ledgers is added.

### Null-total coverage

Call accountant.usage_coverage(card.continuation_budget) if and ONLY if normalized
T is null, with no extra argument. Never call it for a known T; a known-total
card whose coverage API would return None is not refused for that reason.
Its exact result is {schema_version:1, booked_total_usd, covered_total_usd,
invocations:[{invocation_id,lease_id,wait_ids,maximum_usd,booked_usd,remaining_usd}]}.
Validate strict schema version, exact keys, canonical money strings/UUID4 IDs,
nonempty opaque lease strings, sorted unique invocation rows and sorted unique
wait_ids, and unchanged input. None, malformed output, exceptions or mutation
refuse the unknown-total checkpoint. A historical stored usage_coverage field
never substitutes for the API result.

Compare the API's covered_total_usd directly to held. Do not sum its rounded row
booked/remaining amounts: D sums raw Decimal event charges and remaining maxima
before rounding upward once. D owns unknown-marker coverage, admitted maxima,
event deduplication, legacy remainders, waste and lease/invocation joins. B
does not reproduce them. Missing/unbounded legacy usage therefore refuses through
the API. If P and T are known and pass reconciliation, return T even when it
exceeds held: the host must ACK and count the full T in max(held,T), mark the
owner's overrun incident, and block new owner authority/revision. It cannot
truncate T or leave P as the collected total merely because the owner overran.
No new return field is needed; the host compares returned T with held.

The reviewed interface still refuses null-P/known-T with T>held, and null-T
with covered_total_usd>held. Before wiring, the holder must durably freeze ALL
new batch admission on any authentic collection's accounting refusal, retaining
the full old hold and the immutable refused evidence until reconciliation. It
must not continue admitting other owners from a stale lower total. Persist that
incident before releasing the batch lock; restart preserves the freeze. This
batch-wide fail-closed state and its reconciliation transition are explicit
holder-schema prerequisites, not implemented by this pure function.
The holder addendum must clear the freeze automatically after later authentic
same-owner evidence covering each refused collection is successfully ACKed and
every implicated accounting incident is reconciled. Recompute the full batch
aggregate under the lock before permitting admission; known overruns still
count in full and keep the overrun owner's authority blocked. Repeated refused
evidence, missing lineage or unresolved incidents never clear the freeze. No
routine founder approval is required for evidence-backed reconciliation; without
proof the batch remains operationally blocked, never scored as a case failure.

This proof only permits the eventual same-owner, same-revision settlement path
after durability and retirement. It grants no increase, new revision,
replacement admission, diagnosis or extension while total is unknown. A lower
operating commitment cannot lower the full held amount in batch conservation.
Calls remain telemetry; neither calls nor max_total_calls enters this consumer.

### Decrease receipts and ACK values

Read continuation_budget.reconciled_decreases as a list (absent means empty;
null/non-list refuses). Each record has EXACTLY the D keys:
schema_version, kind, invocation_id, wait_id, receipt_sha256,
booked_before_usd, previous_estimate_usd, actual_charge_usd, released_usd.
Require integer schema_version=1, kind="reconciled_decrease", canonical UUID4
invocation_id, null or canonical UUID4 wait_id, lowercase 64-hex digest, and the
four canonical nonnegative nine-place money strings. Check exactly in
nanodollars:
released_usd = booked_before_usd + previous_estimate_usd - actual_charge_usd,
with released_usd > 0. Identity is invocation_id alone. Identical repeated
records count once; conflicting duplicates refuse. Hash equality alone never
identifies a release, and different hashes cannot multiply one invocation.

D owns final-private-receipt retention, final-known state, hash/lease validation,
event valuation and settlement transition. B does not decrypt or claim to
verify those private invariants. EVERY record, including historical and in-run
records absent from previous.estimated, must match exactly one reservation by
invocation_id, and that row must be settled. No row, duplicate invocation IDs,
or a pending/estimated matching row refuses with malformed_reconciliation.
Only after these checks does qualification require its ID in previous.estimated and
0 < released_usd <= that immediately previous estimated gap. Valid records for
estimates created and released entirely within this worker run contribute zero;
absence from the previous map is not itself a refusal. Historical records
remain non-qualifying after their invocation leaves that map, but still pass
the same shape/arithmetic/settled-row validation as every other record.

Let P=previous.total_usd, T=the new normalized total, R=sum of qualifying releases,
and M=previous.estimated. Evaluate qualification even if P or T is null.
The reviewed 6055678 rule supersedes the earlier draft: epsilon is
(2*len(M)+1) nanodollars for EVERY known-P/known-T comparison, including with
no qualifying record and an empty M. Accept only T >= P-R-epsilon. A decrease
larger than this allowance without qualifying evidence refuses; a rounding-only
decrease within it can pass. Null T must pass the coverage/held checks above.
Null P with known T permits T<=held after the same owner/collection checks.
The tolerance never reduces held authority or creates new batch headroom.

Return exactly {total_usd, estimated, reconciled_decreases}. The last field is
the sorted list of qualifying original D records, once per invocation. The
future ACK binds these records to old/new totals and the enclosing collected
generation plus snapshot manifest digest. It records an accounting replacement,
never a negative spend event. It persists the new estimated map and total in
one money-state write; no journal-only "ACK" may advance authority.
Replay of the already-ACKed generation returns its saved ACK before re-evaluating
against the now-replaced map. A different snapshot at the same generation
refuses under existing immutable collection rules. This is why generation-keyed
replay belongs around the pure consumer, not inside D's receipt identity.

### Source transition and scheduler integration gates

The next holder/outbox addendum must compose this proof with the existing
publication order: immutable local collection, R2 PUT plus GET/hash proof for
all bound members, one verified current pointer switch, then durable money ACK.
Pointer-before-ACK recovery completes that same candidate; dispatch requires
pointer and ACK agreement. A bare local snapshot or pointer alone never admits
a successor. Missing/unreachable worker retains ownership and its full hold;
retirement must be positively proved before launch. Collection may ACK a
quiescent live worker, but ACK alone cannot retire it.

For known totals, an admitted ordinary resume advances revision exactly by one
and binds source to the new ACKed generation. For unknown totals, preserve
reservation/revision/deadline and full host hold, deliver the same or lower
operating amount, and advance source only along that owner's acknowledged
lineage. Persist the old/new source transition before producing a new immutable
config; repair its money projection on replay. The installer must advance its
authenticated checkpointed job-money copy and history before D compares it to
RAM configuration. Old source replay, including A-to-B-to-A, refuses. No live
worker authority update, alternate launch mode or counter reset is allowed.
These production state-machine/file formats still require the holder review;
this proof-only draft does not relax current fresh-only refusal.

Projection handling follows the explicit parent ruling and diff12:
apply the diagnosis_state/import provenance gate above before acting on D facts.
first derivation requires present replacement_eligible:true, with the two bool
predicates as consistency checks. None never derives. Preserve an existing
valid child and its original eligible generation across later None projections.
B copies no stop predicates or actual-work eligibility rules. Unknown exhausted
owners passing that provenance gate retain settlement priority even with None. An eligible child can be
queued immediately, but admission waits for known settlement collection/ACK,
not for the diagnosis outcome. J-to-J-r1-to-J-r2 has distinct owners and no
call-count/ordinal cap; money/deadline and simultaneous capacity remain bounds.

### Tests, deletion and delivery

Files: add factory/batch_accounting.py and tests/factory/test_batch_accounting.py;
edit factory/batch_service.py (provenance gate and normalized total only),
tests/factory/test_batch_service.py (authored contract fixture provenance),
add tests/factory/test_batch_service_d.py (real D projection integration), and
add the new host module to factory/launch_manifest.py TRUSTED_FILES and the
independent worker inventory in tests/tools/test_launch_manifest.py.

Refusal labels are deterministic: invalid_accounting_input for input shape,
money, reservation identity/state or card/D total disagreement;
accounting_api_refused for API exception, mutation, None or malformed API result;
malformed_reconciliation for any decrease record shape, arithmetic, conflict or
missing/non-settled matching row; uncovered_total for null-T coverage > held or
null-P/known-T > held; unsupported_decrease for T < P-R-epsilon.

Planned tests: tests/factory/test_batch_accounting.py. Separate the evidence:

- Unmodified saved e15450 passes known-total accounting with authored previous/
  held inputs. Unmodified 5813be has case_budget:null but D reports13.779870815;
  it refuses invalid_accounting_input. A separately labelled authored variant
  supplies case_budget.total_spent_usd from D and passes. Neither unmodified
  card exercises the consumer's null-T coverage path; D's direct legacy-coverage
  tests own that proof. These saved cards contain no reconciliation transitions.
  Owner/previous ACK inputs are authored because the cards predate B authority.
- D-produced ledger sequences from D's reviewed public settlement path or
  reviewed fixtures exercise receipt-backed 10-to-8, duplicate record replay,
  an in-run estimate absent from the previous map, null-P/null-T map replacement,
  and a later growing receipt after a release. Design15 verified these source paths at merged cfe616f. B asserts the ACK/map sequence only.
  B re-drives budget.settle and complete_invocation using
  test_stream_d.AccountingTests.setUp/ledger/reserve/receipt/wait helpers, as
  test_stream_d_coverage.py does. It never calls _settle_leaf.
  Leaf-order invariance, creation of estimated-to-settled records and growing
  receipt producer properties stay in D's suite; B never calls _settle_leaf.
- Explicitly authored ACK maps/held amounts layered on those ledger outputs
  test P-R-epsilon at the boundary and one nanodollar below, with qualifying
  records, no qualifying record, zero-rounded releases, re-estimation and empty
  M. Test known-P/known-T overrun returns the full total, null-P overrun refuses,
  known T never calls usage_coverage (even when it would return None), and
  null T checks the returned covered amount against the full held amount.
- Clearly labelled mutations of retained public records test malformed metadata,
  conflicting duplicate records, missing reservation, pending/estimated matches,
  duplicate invocation IDs and unsupported decreases. These are consumer
  rejection tests, not claims that D produced invalid ledgers. Contract doubles
  test API mutation/extra-field refusal only, never real usage qualification.

D's reviewed coverage fixtures must additionally cover booked3/maximum10 as10,
sub-nanodollar valuation, missing maximum and unknown waste. B checks the returned
amount; D proves its event joins and raw-Decimal rounding. Cross-check that adding
or replaying public reconciliation records never changes D case_spending totals.

D interface review18 adds three explicit B obligations to the final 2b.2 review:
the old predicate-fallback sentence above is deleted; extensions defer to D's
eligibility and section8 money; and an actual D projection integration test must
show infrastructure exhaustion with actual work derives no child both while
pending and after completion. Design15 verified tests/factory/test_stream_d_projection.py at cfe616f. Its infrastructure
states are authored D states layered on the real paused5813be card, not saved
infrastructure-exhaustion artifacts. Use that fixture and public diagnosis API
(the completed-state regression is present in merged cfe616f). Feed those returned facts to
B's journal with clearly authored collection bindings. For the parent's known-total lifecycle, explicitly author case_budget.total_spent_usd
from D's real case_spending: pending yields replacement_eligible:false, one
same-owner resume with reason exhaustion, and no child. Completed diagnosis
sets terminal_stop:factory_bug_held and the public finding card; with a known
total it yields None and no queue or child. Step2's status regression additionally
asserts "factory bug: see finding <id>". The retained infrastructure_gate marker
may keep exhaustion true; it never substitutes for a present projection.
Separate variants retaining 5813be's case_budget:null queue only a same-owner
settlement resume in both pending and completed infrastructure phases (the
completed variant retains the infrastructure marker). No child is derived.
These queue-only tests grant no accounting ACK; the unmodified null card's
card/D mismatch refuses accounting as specified above. Preserve existing deterministic two-child,
same-parent replay and changed-projection tests. No B stop predicates are added.
Also pass an authored legacy exhausted state with actual work but no
diagnosis_state through D's real pending_projection. Even when that projection
is present and eligible, B must refuse with legacy_projection_unbound, create
neither child nor resume request, and leave journal bytes/facts unchanged. Cover
known (explicitly authored from D) and unknown totals and a pre-existing facts:null entry collected with the
adapter off. No import fixture may bypass the absent reviewed import format.

The later integration exam additionally proves durable ACK replay, rollback at
every pointer/money/config boundary, source A-to-B-to-A refusal, retired-old-worker
requirement, distinct replacement owners and exact two-child chain, plus
tester/reviewer capacity before G10. Only the authorized practice case may spend,
under $3 model and $1 infra, one worker at a time with verified deletion. Record
IDs and receipts. This draft performs none of those live actions.

Delete no live path in this increment. It replaces the speculative accounting
proof language in the increment2 addendum with reviewed interface6055678;
it creates no second money ledger. Target cost is one offline implementation/
review increment, estimated one to two work sessions after D3a merges and the
final B design review passes. The mid-term exam is the pure suite passing on
named D-produced ledgers at that reviewed SHA; the final exam is the bounded
practice lifecycle above. Neither is claimed by this draft.
Risks are producer integration drift and mistakes at ACK/state boundaries;
the gates above keep them away from launch authority. Full suite and a fresh
diff review remain mandatory. Builds toward rows6,27,28,35,51; closes none
without the required real lifecycle artifacts. Migration command/qualification
and holder/scoped-restore work remain separately gated as specified above.

Design15 test clarification: pending/completed queue assertions each use a fresh
journal; an existing pending row is never silently removed by later planning.

## Later increment: cross-batch carry-over

Parent backlog ruling, 2026-10-30; D factory-bug amendment review305c10c.
Order: implement/review only after2b.2 and the end-to-end practice qualification.
This is a backlog record, not a change to current bind/owner/import authority.

Problem: bind currently rejects a card from a different batch release, so a case
held for a factory bug cannot resume in the next batch release containing its fix.
A reviewed cross-batch addendum must let a new batch import a held or
deadline-stopped case from the previous batch's verified collected generation,
under the same owner, retaining cumulative spend and D's lifetime history. The
retained spend and commitment count against the new batch money bound. D's
lifetime maximum of3 factory-bug resumes remains enforced; import resets nothing.

The later addendum must specify authenticated source/retirement/fix/history
bindings and owner transfer without duplicate live authority, new-batch money
admission, restart/replay and refusal behavior before changing bind. It must use
the same ordinary checkpoint launch path. D's review305c10c history contract is
the producer prerequisite; B owns this reviewed cross-batch integration.

Tests will use a real held/deadline-stopped collected generation, retain its
spend/history through import, prove new-bound accounting and replay, reject
unqualified fixes or simultaneous old authority, and enforce the fourth-resume
refusal. Real-artifact proof is required before closing new-batch-service-4.
Current cross-batch resume stays blocked. No implementation is included here.

## Holder integration addendum (2026-10-30)

See [batch-holder.md](batch-holder.md) for the reviewed implementation of the
shared journal operations map, pending/launched/failed status, immutable current
pointer publication, money ACK and same-owner source transitions. It supersedes
the earlier speculative holder fields in this document. HOLDER_ENABLED remains
false; this is offline integration, not activation. Legacy cases default to
retire; cb5e2 and 14d35 stay set aside. No legacy booking or Murphy closure occurs.
