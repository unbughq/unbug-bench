# Router item 8 validation record

Scope: existing Claude gate cancellation; plain-HTTP loopback only. No TLS,
real CLI, provider or live worker acceptance. All transport payloads and bindings
are synthetic. No benchmark model or infrastructure spend: USD 0.

## Before fix

Command: `uv run --with numpy --with scipy python -B tests/factory/test_model_call_maxima.py`.
Result: exit 1, 22 tests in 9.071s; the new mid-response test failed at
`self.assertTrue(handler_done.wait(max(0,end-time.monotonic())))`.
An isolated protocol comparison then passed HTTP/1.1 in 0.535s and failed HTTP/1.0
at the same assertion in 5.023s. Design reviewer 3 independently reproduced the
socket detachment and verified saved-socket shutdown on plain HTTP.

## Negative control

The companion -negative.py script temporarily changes Allowance.close in memory
to consult connection.sock, reproducing the old behavior. It runs only the
HTTP/1.1 Connection: close variant and exits nonzero on failure. No source file
mutation persists. Command and raw output are retained alongside this record.

Command: `uv run --with numpy --with scipy python -B docs/reports/router-item8-prereqs-suite-20261031T131807Z-a6eb8a94-negative.py`.
Expected failure observed: exit 1, 1 test in 5.035s, handler completion assertion
failed before upstream release. Raw output: companion `-negative.log`.

## Focused module after fix

Command: `uv run --with numpy --with scipy python -B tests/factory/test_model_call_maxima.py`.
Exit 0: 22 tests in 4.464s, OK, including HTTP/1.0, HTTP/1.1 keep-alive and
HTTP/1.1 Connection: close variants. Runtime receipt, unknown hold and repeated
ledger reconciliation assertions all passed. No production source mutation remains.

## Full suite

Command: `uv run --with numpy --with scipy python -B tests/run.py`.
Output: `router-item8-prereqs-suite-20261031T131807Z-a6eb8a94.log`.

Completed: exit 0, **158 test scripts run; 0 failed**.
Log SHA-256: `9349ce79449aad5bca9ec8225bb2dc5852da73b6e85957dd2ec4fb8c7385bf89`.
Unittest skipped-test summaries: OK (skipped=1), OK (skipped=1), OK (skipped=1).

## Outcome and remaining prerequisites

Fixed new-router-item8-prereqs-1: keep the connected socket for cancellation after
HTTPConnection detaches it. Closure is plain-HTTP loopback only; TLS wake remains
unproved. No broad item-8 acceptance row closes. The real socket regression,
real runtime receipt writer and accountant retain $8.655360 exactly once under
synthetic process interruption. The repeated reconciliation leaves ledger bytes
unchanged. All 22 maxima tests also passed in the full suite (4.602s).

All five prerequisites remain incomplete. Smaller enforced Claude profiles and
Codex/OpenAI plus remaining route maxima are next; selected-role feasibility,
TLS/worker/selected-route cancellation and account-2 acceptance need their own
evidence. No inference or infrastructure was purchased: USD 0 benchmark spend.
Fresh reviews used the requested Claude subscription delegate; no paid fallback
was used and no review cash charge was reported by the delegate service.

The parent's USD 100 qualification approval is recorded in the design, conditional
on existing Claude/Codex subscription limits and existing OpenRouter credit only.
No top-up or new plan. Required MiniMax/DeepSeek roles in scenarios 1–3, 5–7 cannot
run through Claude/Codex without changing family bindings; they need approved
free or existing-credit routes. Claude/Codex feasibility is otherwise unproved,
not demonstrated impossible. No diagnosis flag changed; nothing pushed or merged.
