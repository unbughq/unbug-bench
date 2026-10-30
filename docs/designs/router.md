# Factory model router — stream A

## Problem and authority

Every factory role already enters ModelRuntime.call, but that method silently
maps free DeepSeek to paid OpenRouter and has one worker-local GLM fallback.
account_handoff permanently blacklists exhausted accounts. Independent workers
retry shared accounts; coordinator quota assertions expire hourly.
ENGINEERING.md overrides the Mac-online sections of factory-single-path.md.
The control VM owns the batch. docs/designs/interfaces.md is the cross-stream
contract supplied by the parent: A provides routing and provider-wait records;
D owns reservations/usage settlement; B owns batch lifecycle and host Codex
renewal. No new security property or gate scoring rule is introduced.

## Change: one routing authority

Add one stdlib module, factory/model_router.py: plain route data, SQLite state,
a small authenticated TLS RPC server, and its HTTP client. The control VM runs
it under control/unbug-model-router.service; its public batch config supplies
lane capacities (initially one per account, matching single-path evidence).
State is ~/.unbug-control/router/<batch>.sqlite3. Only the router owns model-call
capacity, health, cooldown and wallet availability. Coordinator cloud inventory
continues to prove worker retirement, but its model-account scheduling and
operator quota assertions are deleted. B's batch service consumes router status
and pending provider_wait checkpoints; no second dispatcher is added by A.

Workers and host callers always use the client via FACTORY_ROUTER_URL and
FACTORY_ROUTER_TOKEN. No production worker-local fallback/store bypass exists. The one public admission seam is
model_router.await_lease(role, case, deadline) -> Lease. Bare admit is private
to this module. Lease has lease_id, route, account and expires_at. All callers
(including D before reservations) use await_lease; opencode accepts lease=lease.
The wrapper renews every 60 seconds; no renewal for 180 seconds releases the slot.
Every exit calls finish(lease_id, outcome, receipt), with outcome done, interrupted
or denied. Finish releases capacity and books nothing. capacity(route) returns
free slots without reserving, for B's relaunch pacing. The case
argument is public scheduling data built by the runtime: requested model,
authorized account labels, invocation duration, case/job/batch identifiers and
logical call ID. Wire deadline is a UTC epoch; callers convert monotonic remaining
time. D passes the returned Lease to the model-call wrapper after recording lease_id.
The wrapper also exposes c.model_lease for legacy before_attempt callbacks.
Tests inject the service RPC or run its real server on loopback. Missing URL,
connection failure, RPC timeout or uncertain acquire/finish goes through the same
provider-wait path within 60 seconds; never call another provider on uncertainty.
The server suppresses request/exception logging. Requests contain only scheduling
metadata, never prompts, transcripts, responses or credentials. Requests are
bounded and validated; the bearer token only authorizes public scheduling.

B provisions the batch-scoped router-token in /run/unbug-bench (RAM), delivers
it through ordinary secret transport, and sets an https control-VM URL on workers.
The service binds 0.0.0.0:8765 with stdlib TLS, using FACTORY_ROUTER_CERT and
FACTORY_ROUTER_KEY from /run/unbug-bench/router.env. Normal certificate validation
is mandatory. Loopback http is allowed only for offline tests. Token rotation
requires draining the batch. A supplies the unit and client contract; B owns
startup, token/credential delivery and the timer that dispatches pending jobs.

## Approved routes and independence

Plain data in the router contains approved same-family chains. Claude keeps the
requested model and effort, choosing claude-token or claude-factory-token-2;
never claude-token-2 (exam) or unverified factory label 3. Codex stays its configured
subscription model. DeepSeek probes native opencode/deepseek-v4.1-flash-free,
then explicitly paid openrouter/deepseek/deepseek-v4.1-flash. Native availability
is not assumed; the real paid DeepSeek cards collected on 2026-10-29 prove the
paid route was needed. MiniMax, MiMo, Muse and GLM use the already-approved
same-family routes in model_runtime/rotation config. Unknown models have only
their explicitly requested route. Every chain is validated as one family.
The existing four-family role check remains. Fallback never changes role family,
model effort or the strong-subscription/easy-noncontestant restrictions.

Literal chain table (reverse chains start with the explicitly requested provider):

| Requested model | Ordered effective routes | Billing / pool |
| --- | --- | --- |
| claude/<model> | same model on claude-token, then claude-factory-token-2 | subscription / each account label |
| codex/<model> | same model on codex-auth.json | subscription / codex-auth.json |
| opencode/deepseek-v4.1-flash-free or legacy opencode-go/deepseek-v4.1-flash | opencode/deepseek-v4.1-flash-free, openrouter/deepseek/deepseek-v4.1-flash | free / opencode-free; paid / openrouter-key |
| opencode/minimax-m3.1-flash-free | same native route, openrouter/minimax/minimax-m3.1-flash:free | free / selected opencode-go-key; free / openrouter-key |
| opencode-go/mimo-v2.6-pro | same Go route, openrouter/xiaomi/mimo-v2.6-pro | subscription / selected opencode-go-key; paid / openrouter-key |
| opencode-go/muse-spark-1.3-contributor | same Go route, openrouter/meta/muse-spark-1.3-contributor | subscription / selected opencode-go-key; paid / openrouter-key |
| opencode/glm-5.3-flash-free | same native route, opencode-go/glm-5.3-flash | free / opencode-free; subscription / selected opencode-go-key |
| Explicit OpenRouter or Go counterpart of a row above | requested route first, then the other route in that row | same billing and pools as above |
| Any other explicitly requested model | itself only | subscription for Claude/Codex/Go, free for -free/:free, otherwise paid; its existing provider/account pool |

Authority: task explicitly approves native DeepSeek then OpenRouter; MiniMax native
free is authorized by free_models.provider_config and its existing OpenRouter-free
alias; MiMo/Muse Go-first is the founder's 2026-10-19 routes_note in both rotation
files; GLM free-to-Go is the existing FREE_FALLBACK. Public Go accounts are
opencode-go-key and opencode-go-key-2, constrained by batch authorization.
Pricing remains driver-native: token_prices prices Claude/Codex subscriptions;
OpenCode must emit a finite actual cost on each usage event, otherwise existing
budget enforcement fails closed. Do not invent API prices in token_prices.
Keep the existing pinned DeepSeek (.02 input/1 output) and Muse (.10/.20, cache
.002/.10) overrides in opencode_config; MiniMax OpenRouter :free has zero price.
The chain-data test checks billing/pool/family and subscription pricing via
existing token_prices, and paid pricing via real OpenCode receipt cost fields.

Each route receipt records requested model, effective model, public account,
family, billing kind, attempt ID and outcome in the public card. The budget ledger
continues to use the effective model and retains all earlier usage. Native free
and paid OpenRouter are visibly different billing lanes, never a misleading
silent alias. All roles (writer, stress, reviewers, both calibrators, dedup,
freshness, owner answers, G16/G17, preflight and probes) use ModelRuntime.call.
OpenCode config construction accepts the effective route, never remaps it again.

## Admission, observations and bounded waits

RPC has acquire, renew, finish, observe, capacity and status. Each logical call has a random ID;
each execution attempt has a new ID under it. Acquire is idempotent by attempt ID
and rejects reuse with different model/accounts/deadline. A retry of a lost
acquire response uses the same ID. Finish is idempotent; a lost finish is retried
with the same ID, and no subsequent attempt starts until it is acknowledged.
The SQLite transaction serializes allocation and persists leases/cooldowns before
replying. Pending requests retain FIFO order among requests sharing a lane.

All wire deadlines are UTC epoch seconds, derived from each caller's monotonic
remaining duration; never transmit monotonic timestamps across hosts. Lease expiry is last successful renewal UTC + 180 seconds, capped by the
batch deadline. Renewal occurs every 60 seconds while an invocation is active.
On uncertain renewal the wrapper cancels the active CLI through its existing
cancellation event, retains usage evidence, and enters the same bounded
router_unavailable condition path. It never starts another CLI while ownership
is uncertain. Expired leases release capacity. B reconciles interrupted worker ownership
before launching a successor; a stale attempt ID can never obtain a new lease
silently. Batch deadline bounds admission, and actual CLI timeout bounds execution.

Health is shared per account; the OpenRouter key has one shared wallet/capacity
pool. A provider quota/rate/credit observation blocks its appropriate pool until
reported reset/Retry-After, otherwise 15/30/60-minute capped learned backoff plus
small deterministic request jitter. Honor any real reset, without restart.py's former six-hour
cap. Clear expired limits on each transaction; expiry allows one leased readiness
attempt, not an assertion of remaining quota. Credit unknown stays unknown;
402 establishes wallet denial and blocks all paid models sharing the key.
Success records automatic readiness, not fabricated credit balance.

Within model_runtime, a wait under 60 seconds may sleep in <=15-second pieces,
touching .router-wait under work so the watchdog sees progress. Once the provider condition itself has persisted for 60 seconds (not the duration
of a healthy model call), or an enclosing safety deadline is reached, defer the
call. Connection failures and uncertain acquire/finish use the identical bounded
heartbeat policy. Default delays follow interfaces.md: quota/rate/outage 15min,
router unavailable 5min, repeated conditions then 15/30/60min. Credit and
credential_expiring remain blocked until an explicit healthy observation; they
never clear solely by elapsed time. B clears either block with
observe(pool, healthy=True, observation_id=<renewal/top-up receipt ID>),
authorized by the same batch-scoped FACTORY_ROUTER_TOKEN. The RPC durably clears
the block once per observation_id; workers never generate healthy observations
without completed provider work. Test blocked -> B observe -> capacity -> admit. Never sleep beyond 60
seconds, caller deadline, watchdog, TTL or batch deadline. No model invocation,
budget call or before_attempt callback runs while admission is pending.

A selected account whose credential is absent receives a non-executed finish
(release, no health observation), followed by provider_wait with that public
account selection. Only B's existing secret transport installs a replacement.
A does not send two credentials to a worker and does not add a credential service.
account_handoff scheduling is deleted. Its choose helper only validates and
transports the already-selected account from the public provider_wait projection;
it never chooses another account independently. Permanent blacklist logic is
deleted. Its transport remains for B to reuse; A makes no claim that
--merge currently deletes displaced credentials. B owns installation hygiene and
Codex access-token delivery. Runtime reads /dev/shm/secrets/codex-auth.json
(tests patch the module path directly), then uses
codex_login.worker_auth to strip refresh authority. A missing/expired source is
credential_expiring; there is no stale ~/.codex/auth.json fallback for credentials.
CODEX_HOME still supplies CLI config.toml only. Parent explicitly accepted this exact RAM path, per-call re-read with no cache,
and removal of launch.sh's copy into ~/.codex/auth.json. A makes that minimal
launch.sh edit in E/B's area; CODEX_HOME supplies config.toml only. A implements both the reader and launch edit now. A missing or
expired RAM file enters await_lease's credential_expiring path. Parent owns the
matching update to interfaces.md, so A does not mutate that passed contract. Until B provisions that file, Codex routes resolve to credential_expiring;
no batch runs between A and B merges.

## Failure classification (A owns this parser-only budget.py seam)

budget.py already parses trusted provider diagnostic events, excluding tool and
assistant business prose. Attach a sanitized provider_failure object to BudgetError
and the usage ledger at that boundary, retaining the existing stop labels:

- HTTP 402 / insufficient credits: reason credit, scope wallet;
- HTTP 429 / rate limit: reason rate, scope account, Retry-After when structured;
- subscription/weekly/usage limit: reason quota, scope account, structured reset;
- HTTP 5xx / unavailable or removed model: reason outage, scope route;
- codex_login_expired: reason credential_expiring, scope account;
- unknown provider_limit from old cards: reason quota with conservative account
  scope (OpenRouter's account is its shared wallet).

The parser emits only fixed enums, finite timestamps, effective model and no raw
provider strings. Real cards prove legacy reset/paid-ledger behavior; synthetic
trusted provider events exercise distinctions absent from public artifacts.
Ordinary natural-language refusal detection remains incomplete across providers:
known refusal:* tries approved alternatives at most once per account/route,
then enters an outage wait rather than repeatedly invoking the refused route. Do not claim full row 48 closure. Money/call ceilings, unknown
usage, cleanup errors, timeout and non-provider failures propagate unchanged.
Label-only CLI failures, including nonzero exit, are per-call outage evidence;
they never create shared health blocks. Preflight retains provider_wait and
never converts it into provider_preflight_failed. No subprocess/timeouts are
changed in budget.py (stream E), and no invalid-run scoring is changed (stream C).

## Provider-wait record and stream dependencies

The provider-wait writer ships behind UNBUG_PROVIDER_WAIT=0 (off by default).
B enables it only after D/B merge; no batch runs between these merges. While off,
await_lease uses in-worker waits with a work heartbeat and never exits merely
because a provider condition lasted 60 seconds. It writes no provider_wait record.
Operator cancellation and the existing worker lifecycle remain authoritative. The router remains the only admission authority in both rollout states.

Runtime raises a sanitized provider-wait exception carrying public wait metadata,
a lease ID if admitted, and a path to a per-lease usage receipt. run.py's main
stop handler alone writes provider_wait.json, then its existing finally block
seals the normal authenticated checkpoint and exits. Optional early_probe must
re-raise provider_wait rather than swallow it. The model-call wrapper collects
concurrent waits in one shared list under a lock; after peers join, the main stop
handler takes the latest retry_after and lets interrupted evidence win. It writes
one record and, for multiple interrupted calls, one aggregate usage receipt with
the union of already-booked event IDs and all per-lease receipts; no last-writer
wins. D settles these by event ID/wait_id. The lease_id identifies an interrupted attempt if one exists. route/account name
the effective candidate awaiting admission or credential delivery. Its usage
receipt keeps the original lease/account evidence. Earlier serial fallback
receipts inherit the current condition rather than extending another route's
cooldown; concurrent calls still merge at the latest retry_after.

Fields exactly follow interfaces.md: wait_id, case, job, batch,
lease_id (null before admission), role, route, account, reason, retry_after UTC,
evidence, call_id (usage-receipt path relative to work, null before execution),
settled=false, and batch_deadline UTC. The main stop handler sets terminal_stop and the public provider_wait projection
in the same atomic scorecard write. The public card carries only wait_id,
reason,retry_after,role,route,account,evidence,batch_deadline. The record holds no checkpoint hash at all. B launches the
collected output generation, bound by authenticated collection.
The per-lease receipt lists already-booked event IDs, usage delta and known/unknown
state. It books nothing. Existing incremental budget booking stays unchanged;
D alone books missing usage/reservations, deduplicating event IDs and wait_id.
The resumed worker archives provider_wait.json to provider_waits/<wait_id>.json
in await_lease, after D has settled it and before its first resumed admission.
An unsettled record raises fixed BudgetError(provider_wait_unsettled) immediately,
without waiting or invoking a model; stale evidence is never silently discarded.

Before admission, evidence is denied_before_work. A provider limit found after
admission is interrupted even if it looks cheap; retain all usage and mutations.
The receipt marks usage known only when the existing ledger has no active/
unpriced usage and case_spending has known totals. Never clear usage or manufacture zero cost.
A router-unavailable record retains the last public attempt ID/lease in the
card's route receipts for B ownership reconciliation; no other model is called.
The writer must fail closed before useful work if batch/job/deadline metadata is
missing; tests provide those fields explicitly. D owns moving writer repair_pending
and stress reservations behind before_attempt and continuing interrupted receipts.
A does not change D's reservation logic or exemption accounting. B consumes the
record after authenticated collection/retirement and invokes
launch(batch, job, collected_generation) at retry_after, before batch_deadline.

Concrete prerequisites and merge order from interfaces.md:
1. Single launch path (factory/batch.py launch interface).
2. E (worker TTL/process ownership), then C (invalid-run gates).
3. A (this router, provider-wait record writer, coordinator scheduling deletion).
4. D (provider_wait exemptions, interrupted receipt settlement, deferred reservations).
5. B (control-key restores, lifecycle/timer, authenticated wait->checkpoint->retire
   ->collected-generation relaunch->finish; Codex renewal/delivery row 20).

Until D/B merge, A's unit-tested slice is not an unattended production batch.
No target row is closed merely by this slice's admission tests. Parent explicitly
authorized this merge boundary; no lifecycle or key-holder change is hidden in A.

## Deletions and tests

Delete model_runtime PROVIDER_ROUTES/FREE_FALLBACK decisions, c.routes cache and
worker-local fallback handling; remove account_handoff's blacklist scheduling;
remove coordinator account-selection/quota code and inventory operator-quota
expiration. Keep CLI isolation, budgets, role bindings, existing credential
transport and cloud worker retirement evidence. restart reuses the router's
reset calculation and excludes provider_wait deferrals from its restart counter
and three-attempt bound. D owns other reservation/allowance counters.
No new dependencies, framework, launch path or live deployment.

Saved fixtures are exact read-only public VM scorecards and embedded usage
ledgers (8 provider limits, 2 paid DeepSeek cards), with collection hashes and
provenance. No ciphertext/archive, secret, case launch, Boat operation or
decryption is involved. Tests cover real reset replay, two clients sharing lanes,
account switching selection, expiry, crash lease expiry/restart, explicit paid
fallback and unchanged real ledger totals, wallet-wide denial, family/effort
independence, HTTP auth/idempotence, outage/uncertain responses, every role's runtime
entry, provider-wait record and normal checkpoint-and-exit, and callbacks not run
before admission. Parser tests use sanitized synthetic provider events as an
additional check, never as the sole real-artifact closure proof.

Row 3 remains partial: real paid artifacts prove effective billing and family,
but no saved public card distinguishes a real 402 from a 429. Synthetic 402 tests
prove parser/routing behavior, but do not close the row by themselves. Rows 2,4,47,48 stay open
until B's combined recorded-denial lifecycle test. Row 20 moves to B; A emits
credential_expiring and preserves worker-only access-token authority. Ordinary
refusal coverage remains partial and must be reported. Full suite:
uv run --with numpy --with scipy python -B tests/run.py. Save design and diff
reviews verbatim with findings/responses; parent merges only after review passes.

## Resource cost, risks and execution checkpoints

This is one implementation stream plus two fresh reviews; no paid provider call
or cloud worker is required for development. The VM service uses one SQLite file
and one short transaction per admit/finish; initial capacity is conservative and
must be measured before increasing it. A single control-VM outage halts admission
and produces a bounded provider_wait, preserving checkpoint/usage evidence. The
public capacity config can reduce concurrency on restart without clearing leases.
The major risks are uncertain leases, stale waits and duplicate accounting; tests
exercise lost responses, restart, concurrent waits and immutable real ledger totals.

Execution phases: (1) shared router plus artifact tests; (2) runtime and wait record
integration plus parser/coordinate deletions and full suite; (3) diff goldfish and
handoff. Completion for A is all unit/integration tests green and no open blocking
diff finding. Production completion and Murphy closure wait for D/B as above.

Expected implementation effort is one focused agent session (hours), followed by
the full offline suite and independent diff review. New regression suite:
tests/factory/test_model_router.py; adapt test_model_runtime.py,
test_provider_routes.py, test_codex_login_rotation.py, test_account_handoff.py,
test_restart.py, test_coordinator.py and test_coordinator_inventory.py to the
single router authority. Explicit renewal tests use a fake clock at 60/180-second
boundaries. No live performance/capacity claim is made.

Accepted review nits: a missing credential for any provider is credential_expiring.
The shared batch token trusts factory worker code to report public health honestly;
this limited scheduling trust is accepted, and healthy observations on an unblocked
pool are no-ops. B remains the normal source of renewal/top-up observations.

Minimal launch.sh counter seam: a provider_wait resume does not increment the
existing .autoresumes file. All timeout, process and retirement behavior remains
E-owned. restart.plan validates provider-wait eligibility and monetary/usage state
while exempting it from the three-restart limit; it cannot override a non-provider
ledger stop.

The standalone g11_review stop handler also invokes the shared wait-record writer;
otherwise its generic interruption label would swallow provider_wait outside
run.main. This changes no audit verdict or gate scoring rule. The existing launch
manifest includes model_router.py in host trust and required worker release files;
no second file inventory is introduced.

Admission checks credential presence (and Codex expiry) before returning a Lease
to D. It prefers the worker's installed/current authorized account while retaining
other authorized accounts as handoff candidates. Every CLI still re-reads its RAM
credential at execution. Receipt-write failures cannot skip finish; interrupted
final usage is conservatively unknown, while already-booked IDs remain retained.
Queue entries without a poll expire after 180 seconds as well as running leases.

## Diff-review corrections

Flag-off "never exits" means no 60-second provider_wait exit. Explicit caller
and batch deadlines still raise sanitized timeout or provider_wait_deadline.
Flag-off admission polls again after router recovery or credential installation;
an uncertain finish is retried with the same lease and receipt before new work.
The 60-second condition timer starts at the provider failure, including when
finish reconciliation follows that failure, rather than at invocation start.

Outage detection uses structured provider status/error fields only. All shared
health observations require structured provider errors or trusted CLI metadata.
Trusted metadata includes timestamped OpenCode Go limit logs, Claude api_retry
rate-status fields and the CLI's exact Codex login-expiry diagnostics; these are
parsed outside normal response text and retain shared account scope. Generic
failed-turn/error-result labels without provider evidence stay per-call.
Normal assistant prose,
including HTTP 402/404/429/500, credits and quota descriptions, never marks a
route unhealthy. Other unstructured CLI diagnostics stay per-call, as do refusals:
they exclude only their account/pool plus route for that logical call, preserving
the other subscription account. Exhausted candidates retain the last condition's
reason for the provider-wait record. With the rollout flag off, exhausting all
candidates raises provider_routes_exhausted immediately; it is a terminal,
non-resumable rollout stop, never a recovery attempt.
Admission freezes account order for
each request ID, including retries after a lost response. Unknown paid OpenCode
models use the Go account pools rather than the native free pool.

Every cancelled peer that invoked a CLI retains a per-lease usage receipt. The
main provider-wait record unions those receipts with the failing call's, with
interrupted evidence winning over denied-before-work. restart accepts the real
budget ledger's cancelled stop only when the public card establishes a provider
wait. A supplied lease remains in the record if initial renewal fails before
execution, so D can match its pending reservation; its usage is known zero.
Scratch wait/peer lists live on the in-memory case context, shared by shallow
role copies, never on the public card. Old scratch fields are dropped before
admission as well as by the record writer. A fresh process cannot mistake old
cancelled-call entries for a current interrupted lease. c.model_lease remains
available for serial callbacks; concurrent code uses its explicit lease or the
private execution context, since peers overwrite that convenience field.

TLS acceptance does not perform a handshake on the server's accept loop. Each
handler performs its handshake under a five-second timeout, so an idle raw TCP
client cannot delay a concurrent capacity, renewal or finish RPC.
The main service and loopback test use the same TLS-construction helper. Daemon
connection threads are not capped; slow-header clients can retain a thread under
per-read timeouts. This limited availability risk is accepted for the batch
network; it does not block the accept loop or consume model capacity.

Legacy Claude provider_limit restart waits use the actual future reset without
the old six-hour cap; an already-expired reset uses the quota fallback (15
minutes plus the two-minute legacy margin). A reset beyond the worker's remaining
collection deadline refuses that legacy same-worker restart. B owns fresh-worker
continuation before the batch deadline for provider_wait cards.

The FIFO check is deliberately conservative: an older request sharing a possible
pool can delay a newer request even if another pool could serve the older one.
This trades utilization for simple shared admission; it is not a throughput claim.
Regression tests for these corrections are in test_model_router.py, including
the actual budget subprocess cancellation boundary and restart validation.

## Passing diff-review follow-ups

Diff review 4 passes A with these recorded boundaries; none closes a Murphy row.

- B/D should treat repeated label-only exhaustion as a case/factory-bug diagnosis
  candidate, rather than spending all outage relaunches on identical case content.
  A retains the approved per-call outage behavior; B's relaunch cap bounds it.
- The non-response Codex 401/authentication pattern is broader than the exact CLI
  phrases. Its shared credential-expiring scope is accepted here: responses and
  tool output cannot enter it, and B's renewal/healthy observation clears the
  block. Narrow it if a non-CLI source is evidenced. Row 20 stays B-owned/open.
- The per-call Go test proves lane exclusion preserves key 2. The existing
  silent-limit parser test covers the timestamped real Go signal separately;
  combined real-log-to-key-2 lifecycle proof remains part of B's integration.
- The inherited Go log check has a subsecond alias window: a line from key 1
  may share key 2's start second. This narrow scheduling risk is accepted for A,
  with both the real-account lifecycle and paid-fallback proof still open.


## Follow-up: enforceable call maxima (2026-10-30, revised after review 2)

### Objective and evidence

Reserve enough money before sending a model request, and stop sending requests
before the approved ceiling can be exceeded. A returned usage report can release
unused reserved money; it must never authorize an overshoot that already happened.

A Lease covers one invocation of the approved CLI. D owns case reservations and
ledger settlement; this change only enforces that invocation's joint money/token
ceiling. Historical maxima and the $33 import estimate are never enforcement.
Exact public pins: Codex 0.162.1, Claude 2.1.299, OpenCode 1.19.0. Their native
turn/compaction/retry controls do not prove an aggregate bound. The public audit
fixture `tests/factory/fixtures/router-maxima-cli-audit.json.gz` retains version,
help, source hashes, and synthetic, external-network-denied pinned CLI probes.
It must distinguish those probes from real provider usage. Public saved cards
are independent real receipt evidence; no production/case/Boat/secret operation
is authorized here. No Murphy row is closed by this slice.

### One supported route, and an explicit rollout limitation

Only `claude/claude-opus-5-5` on the two existing factory subscription labels
qualifies. Other routes, including direct/free/paid OpenCode, Codex and unknown
models, return no Lease and Wait('unbounded_route'). Consequently **none of the
current four-family rotation packages can finish a case with this slice alone**.
D qualification must refuse such packages until other routes acquire reviewed
enforcement. This increment supplies a genuinely runnable bounded Claude route,
not production batch availability or a change to role independence/bench rules.

The wrapper's local gate covers CLI-owned inference traffic, including client
compaction, retries, side queries and small-model requests routed through the
CLI SDK. It is an operational money bound, not an account-wide or hostile-tool
security boundary. Arbitrary Bash/direct network activity can use credentials
outside the CLI; this increment does not claim to sandbox it. This exact scope
was confirmed by the parent while addressing review 2 M2. No new credential,
key, Mac dependency, endpoint/account ownership or control-VM payload is added.

### Local request gate and preserved subscription transport

Add one stdlib worker module, `factory/model_call_gate.py`. For a valid Lease,
`ModelRuntime` points the exact pinned Claude CLI at an invocation-scoped loopback
HTTP server with ANTHROPIC_BASE_URL. The gate forwards only to
`https://api.anthropic.com/v1/messages` (optional `?beta=true`). It has no remote
URL/config override, logs no payload/header/credential and performs no retry or
redirect. It opens normal certificate-verified HTTPS directly (ignoring proxy
environment). The control VM receives lease metadata only.

Authenticate before reading/accepting the body: require exactly the chosen
account's `Authorization: Bearer <OAuth token>`, constant-time comparison. Wrong
or absent authentication receives local 401 and consumes no allowance, sets no
exhaustion/unsupported flag and cannot stop another caller. Never substitute or
inject a credential. The same incoming OAuth bearer is forwarded unchanged.
Source: https://code.claude.com/docs/en/llm-gateway#subscriptions-and-gateways ;
base-URL alone preserves subscription authentication and OAuth beta capability.
The pinned client constructor and SDK default both respect that base URL.

Allow only POST Messages, bounded 16MiB Content-Length, JSON without duplicate
keys/non-finite values; reject chunked/compressed bodies and other paths/methods.
Allowed top-level fields: model,max_tokens,messages,system,tools,tool_choice,
stream,stop_sequences,temperature,top_p,top_k,thinking,output_config,metadata,
cache_control,service_tier,context_management. Model must match Opus 5.5 exactly.
Remove context_management entirely and its beta (server context edits/compaction
disabled); normalise thinking to adaptive without beta-only display options.
Allow standard text, tool-use/result, thinking/redacted-thinking and inline
image/document content supported by Messages; all count against the hard context.
Reject file-ID/MCP/container/hosted-tool/reference features. Custom tool
schemas may contain ordinary JSON; they grant no server execution.

Tools have only name,description,input_schema,cache_control (optional type custom).
No hosted search or other paid server tool is forwarded. Writer/stress tool lists
remain unchanged: a rejected never-forwarded WebSearch request gets a normal
local unsupported-feature error, not a monetary stop; the CLI can continue using
its other tools, including Bash web/GitHub retrieval. G2's required searches and
verdict rules are unchanged; inability to finish them never waives them. Set the
pin-proven ANTHROPIC_SMALL_FAST_MODEL=claude-opus-5-5 so WebFetch summarisation,
client compaction and other small-model inference use the same admitted model,
price and allowance. Nonmatching requests still fail locally without forwarding.
No claim that every web workflow succeeds is made; the Linux probe must show
unsupported hosted-tool requests do not automatically kill the whole invocation.

Force service_tier=standard_only. Reject speed/fast/priority controls and unknown
premium fields. output_config allows only known effort enum and documented
JSON-schema format, metadata only user_id, cache_control only ephemeral 5m/1h
(including nested cache markers). Forward only fixed version 2023-06-01,
Content-Type, unchanged OAuth bearer, CLI User-Agent/x-app and these pin-verified
capability betas: claude-code-20250219,oauth-2025-04-20,
interleaved-thinking-2025-05-14,effort-2025-11-24. Unknown custom billing/provider
headers never pass. https://platform.claude.com/docs/en/api/service-tiers and
https://platform.claude.com/docs/en/build-with-claude/fast-mode provide the tier
and speed controls. Retain the EXISTING 2*1.1 multiplier for BOTH W and
validated settled usage: budget.subscription_usage(partial=True) calls the
existing claude_cost estimator at that rate if the CLI final result is lost,
even when every HTTP response completed. Dropping 2x only in the gate would let
that already-booked partial estimate exceed the Lease. Premium modes stay blocked;
this deliberately conservative charge matches the unchanged estimator, not a
claim that standard-mode cash billing is doubled. No D accounting/old event is
erased, rebooked or changed.

### Enforce a joint dollar allowance before every forward

The code-owned route profile has max_usd=50.0. `token_prices.py` owns its tariff,
using current input/cache-read/cache-write/output rates (4,.2,8,20 per million)
and its unchanged conservative 2*1.1 multiplier. All arithmetic for admission and
usage replacement uses Decimal from integer usage/rate strings; round the
advertised float maximum upward where necessary. This is a **joint weighted
ceiling**: max_input_tokens and max_output_tokens are independent safety ceilings,
not additive permissions to spend both at their maxima.

Per request, clamp max_tokens to min(requested,32768), including raw thinking.
The provider's hard input context is 1,000,000 tokens. System/messages/tools and
all input/cache-read/cache-creation occupy it; input alone exceeding it returns
400 on every model. Requested input+output need not fit simultaneously; the
provider may stop at the window. Sources:
https://platform.claude.com/docs/en/build-with-claude/context-windows ,
https://platform.claude.com/docs/en/api/http/messages/create ,
https://platform.claude.com/docs/en/models/opus-5-5/overview .
32K is an enforced output setting below the documented 128K, not a historical
maximum. Record the observed per-response iteration range from saved cards
without assuming aggregate invocation counters are individual requests.

Before opening upstream network, under ONE lock, reserve this request's W:
`(1,000,000 * max(input,cache-read,cache-write rate) + requested_clamped_output * output_rate) * 2*1.1 / 1,000,000`.
At 32K, W=$19.041792 (<$50). Require settled dollar usage + ALL in-flight/unknown
allowances + new W <= lease.max_usd. Separately reserve 1M input tokens and the
clamped output tokens, checking the corresponding aggregate ceilings under the
same lock. Keep an additional 0.000001 USD numerical headroom in this
comparison for the unchanged ledger float accumulation/9-decimal presentation;
it is never released or booked. No previous partial or optimistic usage releases anything.

If only ACTIVE refundable allowances prevent admission, wait on the same lock's
Condition, bounded by the invocation's fixed monotonic deadline, close and parent
cancellation. finish/close/terminal exhaustion notify all waiters. Recheck every
inequality before forwarding; no waiter consumes an allowance early. Only when
settled + RETAINED unknown allowances + new W cannot fit is exhaustion terminal.
Temporary concurrency is neither spending nor a factory-limit stop.

When a response completes with strictly valid provider usage, replace that
request's allowance with its actual token counts and conservatively priced cost.
For SSE require exactly one message_start and final message_stop, cumulative
output metadata (never sum duplicates), and complete validated input/cache/output
counters. Only trusted provider usage events qualify; assistant/tool text never
does. Reject duplicate control events, contradictory/decreasing counters,
negative/bool/non-integer/nonfinite/overflow counters, token counts beyond that
request's caps, model mismatch, nonzero server-tool counters and malformed or
missing final usage. A failed/truncated/cancelled/uncertain response retains W
and the full reserved token ceilings for the rest of the invocation. No release
from partial streams or unknown responses. Updating gate allowances books NOTHING
in the case ledger. Existing budget event IDs/accounting are independent.

There is no fixed 8-request limit. The aggregate safety ceilings are computed by
flooring `50/min(input/cache tariff *2*1.1)` and `50/(output tariff *2*1.1)` in tokens:
currently max_input_tokens=113636363 and max_output_tokens=1136363. They are
separately enforced even when a response costs zero. All requests, including
retries/side calls/compaction, contend for the SAME remaining allowance; unknown
responses cannot silently reopen it. A lost worker/process cannot reset it:
the router grants a one-use execution start before callbacks/reservations and
CLI setup. Store a marker with a slash-prefixed ID in the existing observations
table; observe() already rejects slash IDs. A repeated or uncertain start never
launches another CLI. On lost start acknowledgement, finish denied (zero CLI
usage), then ordinary router_unavailable wait/reconciliation before a fresh ID.

### Exact protocol, environment and receipts

Local errors are Anthropic JSON error envelopes. Authentication: 401
`authentication_error`. Unsupported/unrecognised request: 400
`invalid_request_error`, fixed message `route_feature_unsupported`; no allowance
or monetary-stop flag. Exhausted dollar/token allowance: 400
`invalid_request_error`, fixed message `model_call_cap`, set an invocation-private
exhaustion event. No new request is forwarded after exhaustion. A gate object
combines that event with the existing parent cancellation for run_budgeted's
polling, stopping ONLY this CLI; do not set the shared peer cancellation event.
After cleanup, override CLI/process/cancel labels with BudgetError(model_call_cap)
when exhausted, preventing account/provider fallback or a second monetary cap.
Preserve cancellation_failed unchanged: cleanup may have left a child alive;
cap_used.exhausted still records the monetary stop. Cancel/close/deadline denial
uses local invocation_stopped, never a false model_call_cap label. If monetary
exhaustion overrides an inner provider_failure, its account observation is
deliberately dropped; retained W remains conservative and D diagnoses this cap
without automatic provider fallback.
Upstream connection errors: local 502 fixed `api_error`; retain W. Real upstream
status/error bodies and headers are otherwise relayed, preserving the existing
provider classifier. Copy response bytes/SSE incrementally without modification;
inspect a bounded copy of control metadata, retain W on parser uncertainty.
Recompute request Content-Length after normalisation; never forward caller length.
Pass upstream response headers verbatim except hop-by-hop/framing headers
(Connection,Transfer-Encoding,Keep-Alive,Proxy-*,Trailer,Upgrade,Content-Length).
Use connection-close framing; preserve rate/reset/Retry-After/request-ID headers
for budget.py's real Claude limit classifier. Upstream socket timeout is capped
by the invocation's existing remaining timeout; close active connections and
prevent new admissions when the gate closes. Pending/incomplete usage stays
unknown, so reservations remain conservative.

Build CLI environment and the sudo preserve list from ONE enumerated allowlist:
PATH,HOME,LANG,LC_ALL,TMPDIR,CLAUDE_CODE_OAUTH_TOKEN,CLAUDE_CONFIG_DIR,
DISABLE_AUTOUPDATER,CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC,
CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS,CLAUDE_CODE_MAX_OUTPUT_TOKENS,
CLAUDE_CODE_MAX_RETRIES,CLAUDE_CODE_GZIP_REQUEST_BODIES,
ANTHROPIC_BASE_URL,ANTHROPIC_SMALL_FAST_MODEL,
FACTORY_STRATEGY_DIAGNOSTIC,FACTORY_STRATEGY_SECONDS,FACTORY_STRATEGY_WORKERS.
Set the gate-owned values explicitly: base URL, small model, output32768,
beta-disable=1, max-retries=0 (not relied on), gzip=0, noessentialtraffic=1,
autoupdater=1 and fresh config directory. No provider/ingress/Unix-socket/custom
header/proxy/extra-body or inherited alternative auth selector survives. Other
factory diagnostic variables are exactly the three above. Existing direct Unix
user isolation and CLI tools/role effort stay intact.

Required Lease fields: max_usd:float (finite nonnegative joint USD list-price
ceiling), max_input_tokens:int and max_output_tokens:int (nonnegative aggregate
billed input/cache and visible/raw-thinking ceilings), price_source:str (tariff,
standard-mode and enforcement profile provenance). No caller/config override.
Server/client/runtime compare exact types and values against effective-route
policy, plus approved route/account/pool/family/billing. Supplied legacy/tampered
leases fail closed before callbacks or credentials; renewals compare caps too.
Old missing-cap leases cannot replay/renew/start; finish still releases them.
Execution-start markers prevent repeated supplied leases restarting the allowance.
The private invoke consumes a one-use context permit and independently validates
policy before any CLI setup. Other drivers have no enforcement adapter and deny.

Route and per-lease usage receipts retain all four cap fields. `cap_used` v1 is
exactly this object (USD values are finite nonnegative plain base-10 DECIMAL
STRINGS, no exponent; all counters/token fields are nonnegative JSON integers,
never bool; flags are JSON booleans):

```json
{"version":1,"forwarded_requests":2,"validated_requests":1,"unknown_requests":1,
 "in_flight_requests":0,"unsupported_requests":0,
 "settled_usd":"0.00132","held_usd":"19.041792",
 "settled_input_tokens":100,"held_input_tokens":1000000,
 "settled_output_tokens":10,"held_output_tokens":32768,
 "max_request_output_tokens":32768,"exhausted":false,"closed":true}
```

This example has one complete validated 100-input/10-output uncached response,
and one truncated response retaining its entire W/input/output allowance. It is
synthetic schema illustration, not a real receipt. `forwarded_requests` counts
allowances consumed before upstream attempts, including uncertain attempts.
Its disjoint categories obey `forwarded=validated+unknown+in_flight`. Normally
terminated HTTP with malformed/missing usage is UNKNOWN, never validated.
Unsupported counts only authenticated requests rejected before forwarding;
unauthenticated callers change nothing. Settled fields sum VALIDATED requests
only at existing claude_cost conservative rates. Held fields sum UNKNOWN plus
IN_FLIGHT allowances, each exactly once, never also settled. Exhausted means the
settled+retained-unknown monetary/token admission test failed permanently, not
temporary active holds, deadline, cancellation, unsupported or auth rejection.
The maximum request output field is the code-owned per-request clamp, not an
observed output maximum.

At gate close, under the admission lock: prohibit new forwards; convert EVERY
remaining in-flight request to unknown without releasing its allowance; close
active connections; take one immutable snapshot with closed=true and in_flight=0.
A late handler cannot refund or mutate this snapshot. Validated replacement
occurs only after the complete HTTP body/stream EOF and exactly one final stop,
not immediately on a partial event or early message_stop followed by trailing
controls. A duplicate control after message_stop invalidates usage and releases
nothing. Run-time receipts are written after gate close on every exit.

`final_usage_known = (not invoked) OR (outcome == done AND existing ledger/event
checks pass AND cap_used.closed AND cap_used.unknown_requests ==0 AND
cap_used.in_flight_requests ==0)`. Thus even a successful CLI summary cannot hide
a malformed/truncated gate response. The example's final_usage_known is false.
If no CLI ran, the denied-before-work receipt has the zero-count closed snapshot
and known zero usage. A monetary stop remains interrupted, even if prior HTTP
requests validated. This records enforcement and books nothing. D's normal receipt/event settlement
uses the advertised maximum for an unknown gap without double booking. Never
claim a partial HTTP response has exact final usage merely because a later CLI
summary exists. Per-lease public metadata contains no prompt or credential.

### Stop/wait, B/D and rollout contract

unbounded_route uses the same provider-wait checkpoint/restart record; set
retry_after=now+900 as a coordinator recheck hint, not a claimed provider reset.
B's reason table has zero relaunches while capacity(route)=0; do not start idle
workers or consume per-reason attempts. B continues its ordinary capacity polls.
After an approved new enforcement release is bound/migrated through the existing
batch-release path, positive exact-route capacity is the signal to resume normal
admission (before batch deadline). Time, health observations, token renewal or
top-up alone never make this route bounded. D qualification refuses any required
role without a bound. Current rotations are therefore NOT ready for production.

model_call_cap is an unscored operational/factory-limit stop for EVERY role:
writer, stress, reviewer, G2-confirm, G16/G17, calibrators and probes. It is never
case failure, scientific capped try, writer feedback, refusal, provider outage or
automatic inline fallback. Minimal propagation-only C seams: run.py preflight,
early optional probe and standalone provider-probe loop re-raise this fixed label;
calibration.interruption_label preserves it. run_validity.retry already propagates
BudgetError, so no gate verdict/retry algorithm changes. D must diagnose it as a
factory enforcement limit using retained receipts, not "not converging"; any
later authorised invocation needs a NEW Lease/reservation within original batch
money bounds. B does not apply provider-wait relaunch rules to model_call_cap.

Deploy only after draining all old leases to zero at checkpoints; no rolling
router update across an in-flight unbounded old CLI. Missing-cap renewals would
otherwise cancel old calls within60 seconds. No batch runs between A and B merge
under the existing reviewed rollout contract; this increment performs no deploy.

Changed model_runtime, token_prices and calibration source identities invalidate
all saved calibration attempts and G8/G9/G16 reuse records, conservatively causing
paid reruns on resume even without the interruption-label change. No running
batch is migrated here. C's historical compatibility policy stays pinned to its
exact target; tests accept that target and reject the newer identity/panel.
Add model_call_gate to gate_state.MODEL: later gate edits also invalidate model
evidence because normalization/rejection affects inference. This is an evidence
identity seam only; no compatibility/scoring rule is broadened.

Integration base is factory-simplify 6abe169 (D1 Decimal accounting and B1/B2
money/worker authority). Preserve their accounting/authority/installers unchanged.
Extend only D's synthetic Lease constructor fixtures for the four required fields;
they remain accounting-only tests, not route-enforcement evidence. A separate
contract check uses a real policy Lease, B's actual job_authority reader and D's
reserve/settle functions: a sub-$50 commitment refuses before booking; $50 admits
the route's maximum, unknown usage settles that maximum once, replay adds zero,
and a stale authority copy refuses. D2 dispatch/reservation wiring and B's later
practice qualification are still separate increments, not enabled by this test.

With max_usd=50 and a default $50 job commitment, D2 can admit at most one
separately reserved Claude CLI invocation from zero spend once it has any
positive charge; that invocation may itself contain many provider requests.
After settlement at $3, for example, another invocation needs $3+$50 authority
and gets money_wait at a $50 commitment. D's ordinary $50 threshold diagnoses
after any priced ordinary writer call because spent+next_writer_max exceeds $50. Two
concurrent nested owners each reserving this route need $100 plus settled usage.
First-call success therefore does not qualify package availability. Before D2
enablement, the founder, D and B must agree job commitments/revisions sized to
settled usage plus each outstanding/new per-call maximum, or approve a lower
route maximum against the 153-receipt fit table. A chooses neither authority nor
a replacement profile in this slice. D2 must reserve exactly a valid_lease-checked
route-owned lease.max_usd, rounded upward to nine places; a caller's smaller
maximum would under-reserve. D intentionally ignores cap_used for settlement:
unknown usage consumes the reservation maximum minus already-booked events,
not the gate's currently held W.

### Phases, exams, cost and completion

1. Frozen design/interface/audit increment; fresh goldfish using zoom_out,
   design_critic and implementation_readiness. Resolve all review-2 findings.
2. Implement model_router.py, model_runtime.py, token_prices.py and local gate;
   add gate/token_prices to existing launch_manifest trust/required release lists
   and regenerate launcher hashes. Name the run.py/calibration stop propagation
   seams above; no E subprocess or C scoring changes. Offline legacy argv/router
   tests explicitly mock synthetic cap policy AND enforcement context; those mocks
   never prove a production bound.
3. Real-artifact mid-term exam: inspect the153 saved Claude receipts. Report
   guaranteed aggregate+W fits, aggregate failures and order/per-response unknowns
   honestly: these are aggregate receipts, not full request traces. Never split
   them into invented per-request histories or treat past maxima as enforcement.
   Replay real iteration/usage fields to exercise cache/reasoning pricing and
   unchanged ledger bytes. Add the lost-final regression: feed real retained
   per-response iteration usage through completed HTTP responses, then lose the
   CLI result; current budget.partial assistant-event booking MUST remain <=
   Lease.max_usd, including when ALL HTTP responses completed before interruption.
   Include an adversarial near-ceiling float/rounding case and require exact
   already-booked case charge <=max_usd (not an epsilon-tolerant assertion).
   Compare existing events unchanged and never invent per-request splits of an
   aggregate receipt. New direct tests cover pre-network rejection,
   concurrency, all unknown/partial/duplicate/malformed usage retention, separate
   token limits, nonfatal unsupported/auth errors, exact headers/env, supplied/RPC
   tampering, one-use starts, restart and receipt serialization.
4. Drive exact pinned Linux CLI through real gate to a fake local upstream,
   Docker --network=none; stage only public binaries/source and synthetic data,
   never mount real homes/auth/SSH/secrets/Docker socket. Production architecture
   is qualified explicitly (test Linuxx64 under emulation and ARM64 when available).
   Patch the Python HTTPSConnection boundary only inside the test process to the
   fake loopback upstream; production has no URL override. Exercise writer tools,
   rejected hosted WebSearch, same-model side requests, multi-turn Bash tool use,
   max_tokens stop, client compaction and sudo pilot path. Explicitly script a
   retry-producing upstream failure through the ACTUAL pinned Linux CLI: every
   subsequent inference attempt must re-enter the SAME gate/allowance; uncertain
   attempts keep full W, and exhaustion prevents another forward or account
   fallback. Wrapper outcome after cleanup must be model_call_cap, not cancelled
   or provider outage. Do not rely on MAX_RETRIES=0; the earlier pin probe proved
   it insufficient. Add a concurrency exam: three actual pinned native SDK clients share this
   single test gate/Lease; hold two upstream replies until the third queues,
   then validate/release and require all three complete without exhaustion.
   The two extra CLIs are synthetic test clients, not production launches or
   evidence of live parallel WebFetch completion. Re-run the original eight
   architecture/scenario probes on the changed gate source too. Save argv/env names,
   architecture, binary/image hashes, sanitised request shapes/outcomes and commands.
   Existing local Docker was started by parent for this reversible verification;
   no Boat/control-VM operation is authorised. If a platform prerequisite fails,
   report it rather than fabricating qualification.
5. Full `uv run --with numpy --with scipy python -B tests/run.py` (134 scripts
   before increment; record actual total), fresh cross-family diff goldfish,
   verbatim reviews/responses, clean commits and tested-SHA validation log.

Final production exam belongs to B's separately authorised public practice-case
end-to-end run: one real Claude role through gate, real usage plus cap_used,
wait/checkpoint/retire/relaunch/settle/finish. No real model/case launch here.
For a normal completion require validated_requests>0 and unknown_requests==0;
synthetic SSE cannot establish real stream compatibility.
Until that and other-role enforcement qualify, no production readiness or Murphy
row closure is claimed. Rows2,3,4,20,47,48 remain OPEN. One implementation session,
offline suite and Linux probes; no cloud/model spend. Reuse stdlib/existing ledger;
no general proxy/framework, transport replacement or security architecture.


### Integration rebase onto D2/D3a and B journal/status (2026-10-30)

Rebase base: factory-simplify `cfe616f`. Preserve D's serialized dispatch,
per-lease reservations, invocation/operation IDs, parent-call binding, process
start callback, complete/reconcile settlement and lease-aware budget boundary.
The only new D admission wiring replaces its empty ENFORCED_ROUTE_BOUNDS lookup
in `model_runtime.invocation_maximum` with `valid_lease` validation and exactly
`Decimal(str(lease.max_usd))`, rounded upward to nine places. Both pending writer/
stress calls and ordinary wrapper calls already use this helper. D's separate
pricing helper and pinned OpenCode prices remain intact; they grant no admission.

The runtime validates A's full Lease before reserving, preserves D's zero-cost
release of an uninvoked rejected supplied Lease, and combines D's run_budgeted
invocation_id/lease_id/job_authority/on_started/concurrent arguments with A's
real enforcement gate and invocation-local cancellation. Reservation precedes
one-use start (needed for D's pre-start reconciliation); start still precedes
callbacks and CLI setup. Failed start/renewal/setup settles known zero if no
process began; an interrupted process retains A's cap receipt and D's conservative
maximum settlement. No D accounting or C invalid-run classification is changed.
Historical compatibility tests still accept only C's exact registered target
and unconditionally reject newer live source/panel identities. Worker manifest
expectations are the union of A, B and D modules.

Tests adapt D's synthetic route bounds to the Lease policy seam, retain all D
control-flow assertions, and use the real router policy, gate, runtime and D
accountant with only the process boundary mocked to verify $50 reservation,
invocation IDs, known-zero setup failure, unknown cap-stop settlement and replay.
Tampered/expired leases refuse; unsupported routes still wait unbounded_route.
The required full offline suite and a fresh goldfish review cover this integration.
The old Linux probe artifact remains evidence for its recorded source hashes;
it is not relabelled as a native re-run of this new runtime integration.

D can now consume the four validated Lease maxima fields for bounded Claude
admission. The previously documented $50 ordinary-threshold/commitment limits,
unbounded non-Claude roles, drained rollout and B practice qualification remain;
this wiring does not qualify rotation packages or authorize any launch. No Murphy
row closes, no authority increases and no pricing/profile change is introduced.
