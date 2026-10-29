# Control VM owns the batch — stream B

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
 "router":{"config_path":"factory/batches/practice-b-router.json",
           "config_sha256":"<64hex>","url":"https://router.example:8765"},
 "jobs":{"practice":{"case":"case-practice-b-practice","mode":"batch",
          "requested_total_usd":"3.000000000",
          "args":["1","--source","plant","--rotation-slot","0"],
          "max_calls":10}},
 "daily_need":{"boat_usd":"0.100000000","openrouter_usd":"0.200000000"}}
```

`target_slots`/`max_concurrency` positive integers, concurrency <= job count;
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
