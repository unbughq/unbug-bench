# Fresh stop capture delta

Evidence: root smoke-independent-local-verification.json and smoke-terminal-control-probe.json
for bx_bykfqbyn show stop request persisted, no meter proof, deletion within15s of
120s window, unknown reserved0.036. Exact live exception was swallowed; no evidence
identifies whether asynchronous info, shape, wrapper/FD or RPC failure triggered it.
No live root cause is claimed. Saved pre-existing stopped DTO is not fresh-stop proof.

Reproducible code defect: after a fresh request capture assumes immediate info.stop.id,
then assumes info already says stopped after by-ID completion. Official retained stop
contract says stop is asynchronous. Replace these immediate assertions with bounded
info polling within the SAME original meter deadline. Missing/null stop while waiting
is transient; malformed non-null stop identity refuses. Once an ID is observed, changed
identity/superseded refuses. Poll pending/failing operations as before; wait for stopped
info after completed status, then retain existing strict stopped/meter/recheck predicates.
No force, new window, repeated stop request, stale receipt fallback or duplicate DELETE.

Add atomic public capture-stage.json under existing worker evidence directory. Exact keys:
schema=1, retirement_id, worker_id, stage, outcome, error_class, observed_at. Stage is a
fixed code label (initial_info, stop_request, stop_identity, stop_status, stopped_info,
usage, recheck_info, proof_commit); outcome running/failed/complete. error_class null
or fixed enum timeout/rpc/io/invalid_response; never str(exception), provider text,
commands, arbitrary keys, environment or raw errors. Failed receipt survives retries:
if it exists with outcome failed, retain it unchanged while existing capture/recheck rules may retry only within the original window. Diagnostic state grants no authority.
Existing safety deletion and unknown hold remain; receipt is never billing authority.

Tests use AUTHORED fresh-stop transitions with real retained stopped DTO as final
observation. Red regression: request id only, delayed null info.stop, pending then
completed status, delayed stopped state; proof commits only after strict recheck.
Negative RPC/shape failures yield fixed public receipt and no proof/settlement. No
historical debit changes; bx_bykfqbyn hold remains unknown. No Murphy closure for
new-boat-stop-capture-1. No provider/VM/worker/model calls or full suite here; root
owns live diagnosis/export, qualification and integration. Cost zero live spend.


Review1 blockers accepted: timeout means TimeoutError/subprocess.TimeoutExpired;
rpc means other subprocess.SubprocessError (including nonzero exit); io means other
OSError (spawn and filesystem); invalid_response means ValueError/KeyError/TypeError
including JSON/DTO validation. Proof write OSError is io. Failure-receipt write failure
propagates, never allows proof/settlement; it cannot guarantee a receipt on broken disk.
No arbitrary error text is persisted even then. Tests assert schema, fixed labels,
no provider secret sentinel, failed-generation replay and no committed proof.
Files: factory/boat_lifecycle.py and tests/factory/test_boat_retirement.py, this design
and verbatim review records. Sequence: authored fresh-transition red test; shared
bounded polling and receipt wrapper; negative error/replay tests; focused Mac/Linux
wrapper checks and fresh diff review. Offline effort approximately one hour; no full
suite until root elects to run it after this contract diagnosis. No rows closed.
