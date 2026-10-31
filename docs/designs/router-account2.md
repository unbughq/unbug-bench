# Worker Claude account 2 admission

The founder reserves account 1 for builders. Worker routing currently orders
Claude lanes by caller preferences and local credential presence, and treats
spare account-1 capacity as freely available. Labels are not account identity.

Keep existing credential transport: holder launch_accounts selects the token
sent by launch.sh; await_lease requests admission; model_runtime loads the
lease account; account_handoff.choose selects a router-requested missing key; its controller
wiring still needs the pre-activation work described below.
Enforce policy in Store.rpc, the authoritative SQLite router, not transport.

Delete caller ordering for Claude routes: enumerate account 2 then account 1,
intersecting the allowlist without changing that order. Account 1 is eligible
only while account 2 has an unexpired rate or quota provider observation in
health for its pool or applicable route. Existing authenticated observe records
come from trusted provider diagnostics; runtime per-call/synthetic errors do
not publish observations. Credit, outage, missing/expired credentials, busy
capacity, excluded lanes, saved preferences, and account-1-only allowlists do
not establish rate exhaustion. The existing quota classifier distinguishes
subscription usage exhaustion from billing (credit is classified first).

Use the same eligibility predicate for capacity, acquisition, and FIFO older
request competition. Keep already-issued leases replayable and renewable:
existing in-flight work finishes normally. Expiry/healthy observations close
fallback admission; no new credential storage or account configuration path.
Builder tooling and exam credentials remain outside this worker router.

Tests replay saved public Claude limit cards and reset timestamps, with real
SQLite admission state: account-2 default, busy denial, rate/quota fallback,
expiry/restart, nonqualifying failures, allowlists, caller order, exclusions,
FIFO eligibility, and existing lease continuity. Run the full tests/run.py suite.
Add and close new-router-account2-1 using the saved-artifact regression tests.

Read-only VM audit will inspect bundle labels and account identity metadata in
memory, returning only public presence/comparison results. Different tokens
alone do not prove distinct accounts. If identity cannot be established, record
that limitation and require private founder provisioning/confirmation.

## Review clarification and implementation boundary

This is the founder-requested smallest authoritative-router increment, not a
batch activation. Stream B's activation plan is a required companion:
`docs/reports/stream-b-activation-practice-plan-20261031.md`. Before activation,
its policy MUST set `initial_accounts: {claude: 2}`, `claude_accounts: [2, 1]`,
and the router allowlist must include account 2. This branch does not activate
or deploy anything. Legacy launch defaults do not authorize worker model use:
the authoritative router refuses account 1 without current evidence even if
only its key was transported. An unprepared legacy launch waits safely.

The existing one-key transport is intentionally retained, but automatic round
trip is NOT proven or working with current controller wiring. choose() accepts
provider_wait, while launch.sh calls handoff planning/application only for
provider_limit. On relaunch initial_accounts.claude=2 overrides choose(), which
can repeatedly transport account 2 during an account-1 fallback request.
B must fix that controller integration and prove 2 -> 1 -> 2 round trips before
activation, alongside its initial-account policy. This router-only branch
proves admission correctness, not transport liveness. Recorded provider_accounts
is descriptive and never overrides router eligibility. No direct choose() test
will be misrepresented as an end-to-end transport test.

Code changes: factory/model_router.py only. Keep _account_order for non-Claude
compatibility, but remove its effect for Claude in routes by intersecting the
fixed labels (account 2, account 1) in label order. Inside Store.rpc, eligibility
is true for all non-account-1 routes, and for account 1 only if health for
claude-factory-token-2 has reason in {rate, quota} AND blocked_until > now.
Apply it in free() (capacity and acquire), and in FIFO's older-request lane
comparison. Do not change renewal/replay of issued leases. Account-1-only
configuration without evidence waits with credential_expiring (not outage);
it never executes account 1. Preserve waiting semantics instead of raising a
ValueError that the HTTP client converts to router_unavailable. Exclusions
never constitute rate evidence. Non-Claude ordering is unchanged.

Healthy Claude capacity is one account's configured slots, not both accounts'
sum. batch_service.capacity() consumers see only currently eligible work.
Update test_real_claude_reset_shared_switch_expiry_and_restart from account 1
first/two slots to account 2 first/one slot. Update existing runtime tests that
assume account-1 execution (test_model_call_maxima.py), and change the
Stream D cross-lease test in test_stream_d_admission.py to explicit provider
429 evidence in immediate-fallback mode; checkpoint mode still parks unknown
usage. test_stream_d_runtime.py likewise uses a rejected provider
rate_limit_event instead of a generic error for its unknown-usage fallback
exercise. Add focused tests in test_model_router.py, retaining
real saved cards from tests/factory/fixtures/router-provider-limits.json.gz.
These historical artifacts prove provider-limit/reset semantics, NOT historic
account-2 identity; the replay deliberately attributes their failure to a new
account-2 lease. The new row covers code-inspected default routing contrary to
the 2026-10-31 decision, not a falsely claimed live account-2 incident.

VM audit record: docs/reports/router-account2-vm-20261031.md. Both labels exist;
read-only authenticated profile requests returned 403. Distinct human account
mapping is a founder-owned pre-activation prerequisite, not proven by labels.
This branch's router rule assumes the founder-provisioned label mapping.

Payoff: ordinary workers cannot consume the builder account merely because it
has spare capacity. Cost: no paid inference or worker creation, one small local
change and offline test/review cycle in this task. Risks: lower aggregate Claude
concurrency and unresolved controller handoff integration; missing credentials wait, never borrow
account 1. Success: full offline suite, current-evidence-only fallback tests,
fresh diff review, and recorded VM audit. No live deployment claim is made.
