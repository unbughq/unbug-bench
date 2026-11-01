# Shared cumulative factory OpenRouter spend

## Problem and scope

Existing invocation and batch limits do not prevent
different workers, diagnosis and qualification runs spending the same account
credit. Router SQLite transactions already serialize admission on the control VM,
but the original documented database is per batch. Worker-local Allowance bounds
individual calls and E's settlement closes unknown calls without releasing them.

Deliver one offline increment: a single cumulative paid authority in the existing
router ledger, mandatory before each OpenRouter request. No new store, service,
worker, model call, secret access, top-up, purchase or live qualification. No
Codex maxima, live role feasibility or account-2 acceptance. No Murphy row closes:
offline concurrency/crash tests are not live financial/lifecycle acceptance.

## Objective, impact and exams

Make every factory OpenRouter request reserve money from one durable wallet before
it can reach the provider. This prevents different batches and diagnosis runs
from independently promising the same dollars. A known completed request releases
its unused reservation; cancellation or missing usage keeps the reservation.
Claude and Codex subscriptions keep their existing accounting and use none of this
wallet. Existing paid holds are $0.23 MiniMax, $0.5701632 MiMo and $0.58720256
DeepSeek. About 19–50 wholly unknown requests can exhaust $11.63; that is retained
liability, not a reason to reset the cap. Safe refusal can require later real
settlement evidence, which this increment does not fabricate.

Cost and timeline: one offline design/implementation cycle, full suite and fresh
reviews; no money spent and no promised live qualification date. Mid-term exams
are multi-process reservation and cancellation races against SQLite. Final exams
are real gate loopback/TLS regression, full suite and fresh diff review. Payoff:
no factory-paid overcommit across batches/restarts. Main risks: lost RPC replies
retain extra holds; provider credit is a lagging observation; unavailable credit
blocks paid requests; old clients need an ordered rollout. These are explicit
limits, not claims of current live acceptance.

## Authority and canonical persistence

Reuse model_router.Store and its BEGIN IMMEDIATE transactions. Add paid_requests
and paid_account tables to the same SQLite database; do not use batch_money grants
as paid authority. Those include subscription equivalents and remain independent
additional constraints. No second ledger file or money daemon.

The production router database becomes the canonical
~/.unbug-control/router/factory.sqlite3 under the service account. main rejects
any database key in config and any UNBUG_CONTROL_HOME override in its environment.
Resolve the service account home using pwd rather than an overridable HOME. No
configurable production path; test Store(path) is explicit dependency injection. The unit continues to run the existing single router service. Different
batches/releases use that same service/database. Store(path) remains an internal
test seam, not a worker-local production fallback. No batch reset, carry-over
import, healthy observation, account handoff, lease expiry, release install or
configuration can delete/regrant paid authority. SQLite synchronous=FULL on EVERY connection; commit
must succeed before a permit is returned. Reopening preserves all paid rows.

This supersedes router.md's per-batch database prescription for new deployment.
Old deployment is not silently migrated/activated: B3 must drain old paid clients,
pin the new host and worker releases, and use the canonical ledger. B owns
/run/unbug-bench/router.json and router.env as control-VM-wide configuration,
accounts/capacities and token, shared by all concurrent batches. Each batch's
router pin references the same global config hash and service identity, not a
batch-specific database/token. Per-job account choices still restrict admission;
the global allowed accounts/capacities provide a ceiling, never a job grant. No claim is
made to reconstruct unledgered historical spending; this is the newly authorized
remaining-credit envelope. Refuse missing credit, including on a fresh database.

## Amounts and credit

Hard-coded lifetime ceiling: 11,630,000,000 integer nanodollars. All reservations
round up; available credit rounds down. No float accumulation. Use batch_money's
exact fixed-9-place amount convention in public records, with Decimal conversion
for provider JSON. Persist the latest accepted-reservation observation only for audit, never as a
cached authorization. Status reports counted total and last accepted credit observation; that field is
not a live balance and is never used for a new grant.

Every NEW paid reservation obtains GET https://openrouter.ai/api/v1/credits from
the control service, using openrouter-key newly placed in the router process RAM via
OPENROUTER_API_KEY. This is a new credential placement/security property, not an
existing router capability. ENGINEERING.md requires founder acknowledgement before
deployment. B3 owns RAM delivery via router.env and drain/restart on rotation,
just as for the global token. This offline code may be implemented without
activation; no credential is supplied here and missing reader/key refuses. Implementation adds this read-only
adapter; this task never runs it. No key management endpoint or purchase operation.
Decode numbers with Decimal; require finite nonnegative total_credits,total_usage
and nonnegative difference. Missing token, malformed/oversized response, redirect,
timeout or network error means unknown credit and refuses. Never log response,
headers or exceptions; only fixed error labels. Only dollar figures are persisted.
Production Store receives this reader from main; missing reader refuses paid
reservations. Tests supply a deterministic local reader and no real credential.

Fetch BEFORE opening the write transaction, with a 2-second timeout. After fetching,
BEGIN IMMEDIATE and check all committed holds. No network operation holds a SQLite
lock. Measure handling from do_POST entry (TLS handshake precedes that). Before
insertion, refuse if handling elapsed time is >=4 seconds (including
fetch and lock wait). This reduces late commits; it cannot eliminate lost replies.
A committed reservation with a lost reply always remains held. Renewals and
subscription RPCs are not queued behind network reads. Duplicate request replay
never forwards even if its first response was lost.

Two distinct checks, both atomic with insertion:
(a) lifetime counted total (settled + pending + unknown) + next hold <= the
non-replenishing funding ceiling. This is min($11.63, available credit observed
for the FIRST accepted reservation), persisted once and never increased. This
initial floor protects the original envelope even with arbitrary provider lag.
(b) pending + unknown + recently settled charges + next hold <= newly observed
available credit. Recently settled means settlement timestamp >= credit-fetch
start time minus 900 seconds. Include rows settled concurrently with the fetch.
The 15-minute overlap is a conservative lag cushion, not a proven provider update
SLA; it cannot authorize exceeding (a). Old settled spending is not subtracted
again from current available credit, so this does not permanently halve authority.
Unknown credit always refuses, including after a previously successful observation.
The 900-second cushion may temporarily defer paid work; no healthy/top-up command
is required to retry. Persist timestamps from the control service, not callers.

All factory settled spend stays in (a) forever. Unknown holds stay in both checks
forever. No lease expiry, balance change, release or batch can refund them. A
balance rise cannot raise the original funding ceiling. Exam/harbor traffic
(bin/exam-launch, bin/exam-round, bin/run-exam, harbor/run-audited.py) also uses
openrouter-key but is outside factory dispatch and the factory lifetime counter;
its observed account consumption lowers check (b). Concurrent external usage or
provider accounting lag can make an observation stale; no local mechanism can
promise their future behavior. This task enforces factory reservations against
observed credit plus its fixed initial envelope, never purchases/replenishes it.

## Wire and state machine

Existing authenticated router RPC gains paid_reserve and paid_settle. Worker CLI
never receives router credentials or direct upstream key in paid mode, as today.
Trusted gate/runtime holds the RPC client. Prompts/content are never sent to router.

Acquire adds paid_protocol=1 from the current client. Server excludes paid routes
for missing/incorrect protocol; start also refuses a persisted legacy paid lease.
Thus an old client cannot obtain/use a new paid lease without the mandatory gate
protocol. A new server accepts protocol as optional for subscription admissions.
A new client against an old server fails all admission because the old exact-field
schema rejects paid_protocol; there is no subscription compatibility in that
rollout direction. Upgrade/restart the router service first, then worker/client
releases. Test that old-server refusal causes no model process start. Old server returns
an error on the new paid operation, so a new gate refuses before upstream. Unknown
OpenRouter routes remain unbounded/refused. No free/subscription route gets a paid
record, including Claude and Codex CLI.

paid_reserve takes only lease_id and fresh request_id (32 lowercase hex). Validate
active, started lease, route in GATED_OPENROUTER, expected OpenRouter billing/account, exact server-owned maximum
and admitted protocol. Infer route, provider context/output and tariff from the
lease and GATED_OPENROUTER, never caller-supplied price/hold/limit. Worst hold is
full provider context times prompt price plus full output times output price,
matching Allowance.reserve. Freeze route, tariff, bounds and price_source in row.
Reserve only if both monetary checks hold; insert pending row and return granted=true
after commit. Success is HTTP 200 {"granted":true}. Definite refusal is HTTP 200
{"granted":false,"reason":"credit"|"duplicate"|"binding"}; unavailable/invalid
credit uses credit, never a guessed number. Malformed RPC envelopes remain HTTP
400 and transport failures stay RouterUnavailable. Identity is globally unique. Duplicate identity never returns a new
forwarding permit (even on identical replay), but does not add another charge.
Changed identity binding refuses. No caller retries forwarding after uncertain
reserve: a fresh actual HTTP attempt requires a fresh reserved request identity.

paid_settle takes lease_id, request_id and either validated usage counters/cost or
null. Server validates integer counters against frozen bounds, cost finite and
<= conservative tariff estimate, and uses the frozen tariff to compute rounded-up
charge <= hold. It never accepts a caller's dollar refund. Row transitions are
pending -> settled(charge) or pending -> unknown(full hold). Terminal replay is
idempotent and cannot change the amount; mismatched replay refuses. Invalid or over-bound usage becomes unknown at the full hold;
reported cost is never allowed to reduce a hold. Existing strict gate rejects
cost above tariff, so it cannot send such a value as known usage. No claim is
made that an unexpected provider overcharge is prevented by local accounting;
the enforced provider price caps are the billing contract. An unknown
row cannot become settled. No generation payload or receipt text is persisted.

Expired/cancelled/finished leases mark all pending paid rows unknown within the
same transaction that closes the lease. Rows never disappear or expire. paid_settle
after that cannot lower the hold. This matches E: cancellation and unknown usage
retain once, late bytes never refund. A process dying without settlement leaves
pending counted forever (lease expiry may rename unknown but never changes total).
No fresh credit is required to retain or settle existing work; outage must not
erase pending liability. A failed settlement RPC leaves the full central hold.

## Gate integration and ordering

Modify existing Handler/Allowance, not a parallel dispatch wrapper. Request body
validation and local reserve still happen first. Then reserve centrally before
constructing/connecting upstream. No affirmative permit means zero upstream
requests. Retain the conservative local hold on uncertainty; expose a fixed
provider failure (credit for refusal, router_unavailable for transport uncertainty)
through enforce and the existing ModelRuntime provider-wait path. Gate sends
HTTP 503 api_error/shared_paid_spend_wait to the CLI; sets a separate paid failure
flag, not local model_call_cap exhaustion. Definite credit/binding/duplicate
refusal releases the never-forwarded local reservation; reserve transport
uncertainty retains it. At enforce exit, attach provider_failure with reason
credit for credit refusal, router_unavailable otherwise, plus shared_paid=True.
ModelRuntime must NOT observe(reason=credit) for shared_paid: that persistent
provider-health flag requires manual clearance. Instead set context.router_deferred for shared_paid failures and publish the
existing Wait/ProviderWait with credit (or router_unavailable), retry_after from
retry_at, lease_id and receipt. Return to the existing provider-wait resume path;
no repeated CLI start inside the same call. On later resumption a new paid
reservation rechecks credit; no top-up or manual health reset is suggested.
No separate paid check on acquire and no cached-credit admission shortcut.
Avoid treating
financial refusal as a case verdict or ordinary model output.

Associate each local request with a fresh central ID. On validated EOF, choose the
local terminal transition under the existing condition lock; only the thread that
successfully removes the active entry can request a known settlement. Release
the lock before RPC. paid_settle runs in Handler.do_POST's finally, after a
successful local finish transition and BEFORE returning from do_POST. Thus the
Connection:close downstream EOF follows the settlement attempt; the final CLI
request cannot routinely lose settlement to invocation finish. Bound settlement
by the ordinary RPC timeout. close retains all still-active local entries and does not
wait on network. Late finish has no settlement authority. Lease finish/expiry is
the central backstop for worker death and close; a settle racing central close
is serialized (settle first is known; close first remains held). Connection
shutdown and E's receipt freeze stay unchanged; no gate lock spans network I/O.
If local completion precedes close but its central RPC loses a race, retaining
extra money is safe. Local invocation receipt and global paid ledger are separate
constraints, so differing conservative upper bounds are not double-counted in
one authority.

All factory calls use ModelRuntime and this gate, including diagnosis_dispatch's
r.opencode and future item-8 calls. Qualification has no privileged bypass; raw
CLI/direct credential use is not an authorized factory dispatch path. Tests must
exercise workers/diagnosis-shaped callers against the same real Store and assert
no batch/job identity is a partition or regrant key.

## Compatibility, files, deletions

Modify factory/model_router.py (same-store schema, credit adapter, RPC, global
production path, client methods/protocol); factory/model_call_gate.py (paid
reservation/settlement at sole forwarding seam); factory/model_runtime.py only if
needed for fixed provider-wait error propagation. Reuse token_prices/batch_money
utilities where they fit; no general accounting framework or new dependency.
Update docs/designs/router.md, docs/designs/batch-service.md and docs/designs/interfaces.md with the superseding
contract, and add docs/reports/router-shared-paid-spend.md with adoption limits.
No changes to saved B3 manifest, practice-policy.json or release-pins.json: their
hashes are immutable and launch_ready remains false. New host/worker code changes
the existing release digests automatically through launch_manifest file lists;
B3 must build/review fresh pins and deliver router env outside this offline task.
Subscription list-cost case/batch accounting remains as-is and does not debit
paid_account. Delete the per-batch production router path choice, not prior audit
artifacts. No reset/release-hold/credit-purchase command is introduced.

## Tests and completion

Add tests/factory/test_router_paid_spend.py using real Store SQLite transactions,
multiple subprocesses and restarts. Real tariff artifacts are
router-item8-minimax-availability.json.gz and router-cheap-price-records.json.gz;
the funding report contains observed dollar figures but no raw credits payload.
There is no retained raw OpenRouter terminal usage/credits response. Settlement
and credit-parser inputs are synthetic documented-schema payloads, not captures. Synthetic transport faults are labeled as such, never
live provider evidence. Cover concurrent last-dollar reservations across distinct
leases/batches, exact boundary, ceiling despite larger credit, lesser credit,
unknown/malformed/negative/nonfinite credit, provider timeout and no cached grant;
duplicate reserve, lost ack/restart, unknown/cancel/expiry once, duplicate settled
usage, changed settlement, late settlement, frozen tariff across release change,
subscription exclusion, legacy-client refusal, canonical production path refusal.
Test the credits adapter with an in-process fake HTTP opener: success parsing,
bounded read, rejection without logging provider data; no internet.

Gate integration tests must route paid RPC through a real Store and count upstream
connections: no permit => none; success => one; truncated/cancelled stream retains;
late complete data cannot refund; settlement transport loss retains. Adapt existing
paid gate tests in test_model_call_maxima.py, test_router_cheap_maxima.py,
test_router_item8_profiles.py and the TLS cases in test_model_call_maxima.py to establish explicit synthetic
shared authority, not permissive no-op mocks. Adapt router tests' paid acquire to
the protocol and add legacy negative coverage. Keep current captured Claude tests.
Use tests' synthetic roots/readers only, never read secrets or launch workers.

Design goldfish before implementation, using zoom_out, design_critic and
implementation_readiness; standards heilmeier and implementation-readiness. Then
implement, run full `uv run --with numpy --with scipy python -B tests/run.py` to a
unique committed log/result, and fresh diff goldfish with zoom_out/readiness.
Reviewer preference: claudeAgent/claude-opus-5-5, then
opencode/deepseek-v4.1-flash-free, then codex/gpt-6.1-sol. Never paid OpenRouter.
Save all reviews verbatim. No blocker self-verification. Stop after one passing
increment with SHA, suite/review records and no rows claimed closed.

## Design review 1 disposition

B1 accepted: separate lifetime and observed-credit checks, with a fixed initial
funding ceiling and 900-second settlement overlap; no permanent double debit.
B2 accepted: all credit I/O before SQLite write lock; elapsed-time refusal, with
no false guarantee that lost acknowledgements cannot leave holds. M1–M7 accepted
through explicit wire/refusal behavior, settlement-before-EOF ordering, rollout
compatibility, global configuration ownership, honest synthetic evidence, named
exam/harbor outside spenders and plain objective/exams/risks. N1,N2,N4–N6 accepted.
N3: invalid/above-tariff usage retains the complete hold and is never known
settlement; existing provider price caps remain the maximum-price contract. No
new untrusted reported dollar charge overrides that contract.

## Review 2 clarifications before implementation

M-A: after the existing receipt and lease-finalization finally block, shared_paid
failures raise ProviderWait directly, with previous_waits, regardless of
UNBUG_PROVIDER_WAIT. This supersedes relying on context.router_deferred above.
A gate failure latch refuses subsequent SDK retry HTTP requests without another
credit read/reservation; no second CLI start inside that call. Test flag=0.

M-B: founder acknowledgement of the new router credential placement is a live
deployment prerequisite, not an approval requested for offline implementation.
No secret store access, provisioning or activation in this increment.

N1: syntactically valid but unknown/inactive/unstarted/closed/nonpaid/protocol-
mismatched lease is HTTP200 granted=false reason=binding. Only malformed envelope
keys/types/identifiers get HTTP400. N2: unknown holds can additionally reduce the
effective spendable envelope by their real billed cost already deducted from
provider credit; this intentional conservative double count persists until proven
settlement, never a timer refund. N3: no control-home environment override allowed
in production. Moving/deleting the authoritative filesystem by an administrator
is outside protection; no supported config/reset operation does it. N4: handler
time starts at do_POST entry; TLS/response loss can still cause orphan holds.
N5: 429 means unknown credit, safe refusal/deferral. Endpoint throughput limits
are an explicit live performance risk, not a safety assumption. N7: increasing
the fixed ceiling would require founder-directed code/data migration; there is
deliberately no runtime authority-increase path.

Implementation precision: a definite pre-forward refusal is represented in the
existing local attempt counters as a validated zero-cost admission attempt; it
performs no provider call and creates no central paid row. An uncertain reserve
retains its local hold. The historical forwarded_requests counter counts local
reserved attempts, including this definite zero-forward decision; it is not used
as proof of upstream traffic. Tests count upstream connections independently.
