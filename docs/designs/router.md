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
(FACTORY_SECRETS_DIR is a test-only path override), then uses
codex_login.worker_auth to strip refresh authority. A missing/expired source is
credential_expiring; there is no stale ~/.codex/auth.json fallback for credentials.
CODEX_HOME still supplies CLI config.toml only. Parent explicitly accepted this exact RAM path, per-call re-read with no cache,
and removal of launch.sh's copy into ~/.codex/auth.json. A makes that minimal
launch.sh edit in E/B's area; CODEX_HOME supplies config.toml only. A implements both the reader and launch edit now. A missing or
expired RAM file enters await_lease's credential_expiring path. Parent owns the
matching update to interfaces.md, so A does not mutate that passed contract. This
intermediate A slice may defer Codex until B provisions it, as expected: no batch
runs between A and B merges.

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
known refusal:* tries approved alternatives at most once per effective model,
then enters an outage wait rather than repeatedly invoking the refused route. Do not claim full row 48 closure. Money/call ceilings, unknown
usage, cleanup errors, timeout and non-provider failures propagate unchanged.
Nonzero CLI exit is an outage observation. Preflight retains provider_wait and
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
wins. D settles these by event ID/wait_id. The selected lease/route/account belongs
to an interrupted call if one exists; latest retry_after covers all queued waits.

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
