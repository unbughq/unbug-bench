# Item 8 router prerequisites: interrupted response settlement

2026-10-31. First increment from factory-simplify f829df7. Prove that cutting a
Claude call off mid-response retains its worst-case charge exactly once, without
refunding unfinished usage. No paid calls, worker creation, activation, push or
merge is authorized by this change.

## Founder qualification authority (parent instruction, 2026-10-31)

The separate item-8 live qualification is approved up to USD 100, conditional
on staying within existing Claude and Codex subscription limits. Prefer the
existing Claude accounts and Codex login wherever each role allows them.
OpenRouter may consume only credit already on the account: no top-ups and no
new paid plans. This supersedes stream-d.md's pending-approval wording, but
does not waive its route enforcement, accounting, lifecycle or evidence gates.
This offline increment uses none of that live allowance.

Smaller Claude profiles must make subscription execution fit small reservations;
they are not a justification for substituting paid routes. Codex login likewise
still needs an enforced maximum before admission. Scenarios 1–5 and the slot-1
replacement in 7 currently need a smaller Claude writer/strong profile; scenario
6 needs smaller Claude diagnosis and bounded OpenAI strong-calibrator execution.
Scenarios 4 and 6 also depend on bounded OpenAI reviewer/gate execution. Their
subscription feasibility is unproved, not demonstrated impossible. Required
MiniMax/DeepSeek roles in the item-8 role map cannot be replaced by Claude/Codex
without changing family bindings: scenarios 1–3 use MiniMax stress and DeepSeek
reviewer, 5 and 7 DeepSeek diagnosis, and 6 MiniMax writer/DeepSeek stress. They
need approved free routes or existing-credit OpenRouter routes with maxima;
the whole qualification therefore cannot currently be promised subscription-only.

## Problem, impact and order

Item 8 in docs/designs/stream-d.md requires smaller Claude profiles, maxima
for every selected route, feasible role execution, cancellation/settlement,
and account-2 acceptance. The cheapest useful order is:

1. Offline cancellation and settlement regression on the existing Claude gate.
2. Smaller enforced Claude profiles; the current request hold is $8.65536,
   so simply replacing the $50 invocation ceiling with $5 cannot work.
3. Enforced OpenAI and remaining selected route maxima.
4. Live writer/strong-calibrator feasibility on those exact profiles.
5. Account-2 acceptance correlated with necessary live role calls.

The last two share authorized live qualification, after stream B (batch lifecycle)
supplies eligible artifacts. The first is free and protects the accounting seam
future profiles will reuse. This does not complete cancellation acceptance on
future routes or live workers. It changes no advertised maximum or activation flag.

## What exists today

In tests/factory/test_model_call_maxima.py,
`test_real_route_maximum_fits_D_decimal_authority_and_unknown_settlement_once`
already covers a hand-written receipt, real Lease admission, unknown-gap settlement
and replay. `test_concurrent_reservations_and_close_never_refund_unknown` covers
late finish/closed reservation; `test_close_between_connect_and_request_cannot_reconnect_or_forward`
covers closing before sending; `test_factory_dispatch_preserves_lease_maximum_gate_and_invocation_identity`
covers runtime interruption without upstream traffic. The missing window is the
real Handler.do_POST `sent=True` window after headers and prefix were relayed.
The existing `test_successful_cli_cannot_hide_gate_unknown_usage_in_real_runtime_receipt`
is the runtime/client wiring precedent, but covers a complete malformed response
without factory job accounting.

## Change and exact test

Modify only tests/factory/test_model_call_maxima.py (ProtocolTests.setUp and
the new method), plus this design, review records and the suite log/record named
below. The amendment below adds one production file. Add
`ProtocolTests.test_runtime_close_mid_response_retains_hold_once`. Reuse the
loopback fixture with an optional stalled-response object containing prefix bytes,
release and late-write-attempted events (default None, so all
existing tests behave identically). Only for this test, the upstream sends HTTP
200, Content-Type text/event-stream, and Content-Length for the full stream. Send
and flush just message_start, then wait on an explicit release event before
attempting message_delta and message_stop. Use synthetic counters input=1,
cache_read=0, cache_creation=0, output=1. Do not describe these as real provider
artifacts. Saved counters add no proof here and are deliberately not replayed.

Run actual ModelRuntime.call, router Store admission and factory job accounting,
using the synthetic job binding pattern from the existing dispatch test and a
single dummy account-2 credential. Patch only pinned_cli, run_budgeted and the
existing HTTPS-to-loopback connection boundary (plus router transport/secret path).
The fake process calls on_started, starts a client reader in a thread, waits until
that client has read the entire message_start prefix through the real gate, then
raises BudgetError('cancelled'). That exception exits the real enforce context:
_wall_access -> Gate.close -> cap_used snapshot -> runtime receipt writer ->
budget.complete_invocation. Do not call active.close directly, and do not claim
that cancel.set alone interrupts a socket.

Observe the actual gate instance and wrap Handler.do_POST only to signal handler
completion in a finally block; delegate both to their real implementations.
Observe the gate through run_budgeted kw['cancel']. Call runtime.call with
timeout=30 and assert BudgetError matching ^cancelled$. The client gets a
truncated 200 stream ending at clean EOF (the gate strips Content-Length), never a timeout
accepted as success. Withhold upstream release until runtime completion, handler
completion and client read completion have all been asserted within 5 seconds
of the fake process raising cancellation. Use a 30-second gate/client timeout,
so passing the 5-second bound cannot be caused by normal timeout expiry. Use
bounded event waits and thread joins; release and join in finally even on failure.

Before release assert the runtime-produced receipt has outcome interrupted and
final_usage_known False. Its cap has forwarded=1, validated=0, unknown=1,
in_flight=0, settled_usd=0, held_usd=8.655360, closed=True, exhausted=False.
The original reservation is 50.000000000; complete_invocation leaves state
estimated and estimated_gap_usd=8.655360000, total spend equal to that gap and
no billed events. Capture serialized snapshot and receipt bytes. Release the
upstream, wait for its late-write attempt, and assert snapshot and receipt are
unchanged, the client saw only the prefix, and the closed gate refuses reserve.
A late write may fail or reach only the discarded socket; it must never reach
the completed client or refund usage.

Call budget.reconcile_reservations twice from the persisted receipt and ledger;
assert each call leaves the ledger byte-identical and total charge unchanged.
Assert the router has no live lease and exactly one interrupted-call record
identifying the same lease and runtime receipt. Unlike the existing hand-written receipt
test, this proves the mid-response socket cleanup feeds the runtime's real
receipt producer and automatic completion accounting.

## Deletions, risks, cost and validation

Delete no runtime path and add no alternate launch/admission path. The original test-only scope exposed a production defect; see the amendment. If a defect appears, register new-router-item8-prereqs-<n>
before fixing it and obtain fresh review. Future smaller profiles must extend
this same regression with their enforced bounds; no speculative profile API now.

Main risk is a scheduling-sensitive test or hanging fixture. Events, generous
startup waits, a separate 5-second cleanup bound, and finally-based release/join
make failures bounded and distinguish shutdown from upstream cooperation. This
is protocol fault injection, not CLI process-tree, TLS, VM or provider acceptance.
Estimated work: one implementation session plus two fresh reviews and the full
suite, with no provider/model/infrastructure spend. Review runtime is externally
managed and is not a benchmark model call.

Run the focused module, then
`uv run --with numpy --with scipy python -B tests/run.py`, waiting for exit.
Commit the unique log under docs/reports/router-item8-prereqs-suite-<UTC>-<nonce>.log
and a matching .md record containing command, exit status, scope and spend.
Fresh design and diff goldfish reviews are required. Every blocker correction
gets another fresh reviewer; the implementer never verifies its own blocker fix.

## Murphy rows and acceptance limits

The amendment targets new-router-item8-prereqs-1. Rows 9 and 39 remain open. All five requested prerequisites
remain incomplete: smaller Claude profiles and other route maxima are absent;
role feasibility and account-2 need live evidence; cancellation/settlement still
needs selected-route and worker process acceptance. This increment adds only the
missing offline mid-response evidence to cancellation/settlement.


## Amendment: retain the response socket for cancellation

The implemented regression failed on the existing HTTP/1.0 loopback response:
handler completion exceeded 5 seconds. Changing only the upstream to persistent
HTTP/1.1 made it pass in under a second; HTTP/1.0 failed again. CPython
HTTPConnection.getresponse calls self.close when response.will_close is true,
clearing connection.sock while HTTPResponse retains its file/socket reference.
The receipt retains its hold correctly, but a lingering handler can still relay
output and leave upstream generation running until timeout, leaking a thread
and socket after runtime completion.
Allowance.close therefore cannot interrupt that reader. Recorded before fixing
as new-router-item8-prereqs-1. This is an observed real loopback protocol failure,
not live-provider evidence.

Modify factory/model_call_gate.py: replace Allowance.connections' set with a map
from HTTPConnection to its explicitly connected socket (initially None). Register
the connection before connect, then record connection.sock under the allowance
lock after connect, in the same lock block as the closed check, before
request/getresponse. Cancellation
copies the map under lock, retains all unknown holds as before, then shuts down
the saved socket even when HTTPConnection has detached it, and closes the
connection. The handler removes its entry in finally. No lock spans connect,
request, response I/O or socket shutdown. A connection completing after close
sees the closed flag and returns before sending; its finally closes it. Keep
connection.auto_open=0 to prevent reconnects. Do not inspect private response
fields or change timeouts to mask the issue.

Run the regression for HTTP/1.1 keep-alive, HTTP/1.1 Connection: close, and
HTTP/1.0, using the same runtime/receipt assertions and a fresh temporary directory,
Store and events for every variant. Give the fixture optional
protocol and close-header settings before issuing requests; existing tests stay
at their old defaults. Add a negative-control check (temporary mutation restored
before committing) that the connection-close variant fails if retained socket
shutdown is removed. Record that mutation command, exit status and assertion,
plus the original red HTTP/1.0 result, in the suite .md record. No separate runtime or accounting path is added. Full suite
and fresh diff review must cover this small production correction.

Close new-router-item8-prereqs-1 in the fix commit only if the reviewer accepts
that this real socket/runtime regression proves its narrowly stated local defect.
Closed by must explicitly say plain-HTTP loopback; TLS socket wake unproved.
No broader cancellation, live qualification or item-8 row is closed. The test
continues to label the provider payload, process boundary and binding synthetic.
