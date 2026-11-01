# Shared factory paid-spend enforcement

The existing control-VM router SQLite ledger now owns paid request reservations
across factory batches, workers, diagnosis and qualification. It records each
request before the gate can connect to OpenRouter. There is no new ledger store,
money service, launch path or purchase/top-up operation.

The lifetime ceiling is fixed on first accepted reservation at the lower of
$11.63 and observed account credit. All settled charges and pending/unknown holds
count forever against it. A second check compares pending/unknown holds plus
settlements in the preceding 900 seconds against a new credit observation. This
overlap is a conservative lag cushion, not a claimed provider SLA. An unknown
balance refuses. Credit reads happen outside SQLite write transactions, so slow
provider reads cannot block subscription renewals behind a network-held lock.

Cancellation, expiry, process death and uncertain settlement do not refund a
request. Repeated reservation identities cannot authorize a second forward.
Terminal settlement is immutable, uses the frozen tariff, and occurs before the
CLI receives downstream EOF. Lost acknowledgements can retain extra money. A
definite refusal latches the gate against SDK retries and returns ProviderWait
after receipt/lease cleanup even with UNBUG_PROVIDER_WAIT=0. It does not set the
provider's persistent credit-health block or repeatedly restart a CLI.

Claude and Codex subscriptions have no paid ledger entry. Existing case/batch
list-cost accounting stays separate. Exam/harbor traffic is outside factory
dispatch even when it uses the same account; its observed consumption reduces
available credit. Concurrent external spending and provider observation lag are
not controlled by this ledger. Unknown already-billed calls can conservatively
count twice against available credit and reduce the usable envelope.

## Evidence

Offline tests use real SQLite transactions and six simultaneous processes against
one file, reopening the same file, and real gate HTTP/TLS handling with synthetic
credit and provider responses. They prove cap admission, duplicate/cancellation
retention, frozen settlement tariffs, no network-held database lock, no upstream
connection on refusal, lost-ack retention and settlement-before-EOF ordering.
The existing E interruption test additionally asserts the central paid hold is
unchanged after late upstream data. Router runtime tests assert one CLI start
and no persistent health block on shared refusal with provider-wait disabled.

Retained real tariff sources remain the MiniMax availability and cheap-price
fixtures. There is no raw real credits or terminal OpenRouter usage capture;
credit parsing and settlement responses in these tests are synthetic. No secret,
provider endpoint, model, worker or account setting was accessed by this task.
No Murphy row closes. Full-suite and review records accompany the commit.

## Deployment prerequisites

B3 must retain the blocked historical practice-policy/release-pins bytes, build
and review new host/worker pins, drain old paid clients, then upgrade the router
before clients. All batches share the same global router config, account capacity
ceiling, token and service identity. The service derives
~/.unbug-control/router/factory.sqlite3 from its OS service account, rejecting
database configuration and UNBUG_CONTROL_HOME overrides. Administrative deletion
or relocation of authoritative state is unsupported, not a reset feature.

The router process newly holding openrouter-key in RAM for read-only /credits is
a security-property change requiring founder acknowledgement before deployment.
B3 owns RAM-only delivery and drain/restart rotation. The practice run must
confirm that GET /api/v1/credits accepts the deployed key type and returns the
expected schema. Authorization failure or rate limiting fails closed; historical
funding observations do not qualify a newly deployed credential/endpoint contract. No credential was delivered
or read here; an unconfigured reader refuses paid requests. The lifetime ceiling
cannot be raised at runtime. Any future change requires founder-directed code
and data migration; no credit purchase or top-up is authorized.

Live practice/item-8 feasibility, Codex maxima and account-2 acceptance remain
outside this increment, as requested.

Full suite: 167 scripts, 0 failures, exit 0.
[Unique suite record](router-shared-paid-spend-suite-20261101T150101Z-9bce2a01.json)
contains the command, timestamps and SHA-256 of the committed log.

Diff-review follow-up: the original full-suite result above lacked a tested-source
snapshot and is historical evidence only. The replacement run below names a clean committed source tree, verifies it
remained unchanged, and retains its unique log.
Worker and pilot diagnosis runtime calls now share a real Store across distinct
batch/job authorities in an explicit synthetic transport test. A third batch
cannot replenish the shared allowance. No production code changed after review 1.

Replacement full suite: **167 scripts, 0 failures, exit 0**.
[Source-bound suite record](router-shared-paid-spend-suite-20261101T184931Z-a3a2e902.json)
names tested commit `302677faa677b6e0750b1a7034ce23a1ad091050` and tree
`72513d6c2260f10078503ee8f550b5f9218239e5`. The worktree was clean before
the run and all tracked source remained unchanged at completion. Later commits
add this report and the suite/review artifacts only.
