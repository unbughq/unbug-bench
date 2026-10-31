# Isolation cancellation and cloud qualification handoff

2026-10-31. Scope: local cancellation/settlement evidence plus saved cloud audit.
No cloud creation, provider model call, activation, push or merge into the parent.
Incremental spend: USD 0 model, USD 0 infrastructure. The approved USD 1 remains
unused. This is not completion of both item-8 prerequisites.

## Cancellation and settlement

`tests/factory/test_model_call_maxima.py::ProtocolTests.test_real_process_tls_cancellation_settles_unknown_once`
uses the real ModelRuntime, router Store, run_budgeted, process-group kill/wait,
TLS sockets, gate closure, receipt writer and reservation accountant. The client
executable, protocol payload and job binding are explicitly synthetic. The four
upstream variants are HTTP/1.1 keep-alive, HTTP/1.1 Connection: close, HTTP/1.0
with Content-Length, and HTTP/1.0 without it. TLS hostname and certificate checks
are enabled for localhost.

Before gate close and reservation settlement, the cancellation wrapper requires
that the CLI has been reaped, its same-group heartbeat child is absent/zombie,
and heartbeat writes have stopped. The runtime returns cancelled while the
upstream is still withheld. The gate retains USD 8.655360 of unknown usage once;
its USD 50 invocation reservation becomes an estimated USD 8.655360 gap. The
router releases its lease. Upstream late writes cannot validate usage or mutate
the cap/receipt; two reconciliations leave ledger bytes unchanged. The existing
plain-HTTP regression remains. Timing guards distinguish cleanup from the
60-second upstream deadline; bounded fixture cleanup runs on failures too.

The initial focused attempt failed readiness because a test mock replaced the
module-global HTTPSConnection needed by CPython super(). Redirecting only the
gate's http namespace fixed this harness defect. A second focused run exposed
an old-test timestamp race after refactoring; an explicit cancellation-started
event now orders it. Neither failure required a production change.

Limits: no live provider-generation cancellation, official Claude CLI, isolated
sudo UID, escaped-session cleanup, other routes or future profiles are proved.
Static escaped-session risk is registered open as new-isolation-settlement-1.
No new Murphy row closes. Existing new-router-item8-prereqs-1 gains precisely
scoped TLS/process evidence. Rows 9 and broader item-8 acceptance remain open.

## Saved cloud evidence

Public files and exact provenance hashes are under
`tests/factory/fixtures/isolation-settlement-cloud/`. They derive from the real
restore-14 run for bx_d6dzvjbc. The deletion request and completed operation agree
on bdop_fdc58246dcdd44348ec9d206bd38abca, kind sandbox, target bx_d6dzvjbc.
Completion time is 2026-10-29T11:18:20.705Z. The spend observation starts at
09:52:13.047070Z and finishes at 11:18:22.596883Z. These are run-envelope times;
the saved request has no submitted-at timestamp, so no deletion-request latency
can be computed from it. Readiness was observed before completion.

The preserved `actual_spend_usd: 0.09361` is only the account balance change
4.26532 minus 4.17171. The historical converter (restore-14/bin/boat-spend,
function balance) divides creditBalanceSeconds by 100000. This explains the
saved 417171 credit seconds and USD 4.17171; it is neither worker usage nor
current price verification. Do not charge this historical account observation
to this increment or call it proof that a new worker fits USD 1.

The saved provider documents `docs/reports/stream-b-provider-contract-20261031/billing.md`
and `docs/reports/stream-b-cost-contract-20261031/pricing.md` describe per-sandbox
usage and a default list rate. Their availability does not supply a real usage
receipt for this worker. No current provider billing lookup was made here.
No source supplies a worst-case billing-stop/deletion bound. The saved completed
operation proves that one deletion completed, not future outage behavior.

## What must precede the live cloud qualification

The ordinary launch path requires decrypted credentials on stdin and a verified
release/job configuration for batch work. The existing preparation handoff
`docs/reports/stream-b-activation-practice-plan-20261031.md` records unresolved
bootstrap/checkpoint authentication, scoped control-VM launch deployment and
independent cleanup. HOLDER_ENABLED remains false; DIAGNOSIS_ENABLED remains
false. This task did not bypass or activate either. The intended dependency is
B's reviewed control-VM launch path; a Mac or founder-at-every-launch dependency
would violate the engineering rule. No secret was requested or copied.

B/E still need to provide a concrete ordinary-path workload and manifest whose
model plus machine exposure stays inside the approved USD 1, pre-armed independent
control-VM cleanup, and documented pricing and billing-stop semantics. Then retain
per-sandbox final usage (matching worker/lifetime and running=false), completed
deletion operation, and complete inventory absence, with timestamped requests
and responses. Uncertain deletion must block further creation. A successful
sample measures one cleanup tail; a hard exposure claim additionally needs a
provider billing-stop bound or independently enforced provider limit. Account
balance subtraction is not an accepted substitute.

Until those prerequisites and real receipts exist, cloud cleanup timing/billing
exposure is UNQUALIFIED. Spend approval is present; missing executable launch
and evidence dependencies are the reason no worker was launched. No permission
request or claim of completion is implied by this handoff.

Full-suite command, exit, counts and log hash are recorded separately in
`isolation-settlement-cloud-suite-<UTC>-<nonce>.json` and its matching full log.
Fresh design reviews are isolation-settlement-cloud-design-1.md and -design-2.md.
The fresh diff review is saved under the same topic after suite completion.
