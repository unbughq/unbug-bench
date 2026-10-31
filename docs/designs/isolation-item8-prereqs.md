# Item 8 isolation prerequisites: let Boat finish cleanup

## Problem

At factory-simplify f829df7, six Python call sites impose subprocess timeouts
on bin/boat-call: key_holder (25 s), batch_holder (25 s), coordinator_inventory
(two at 25 s), batch_status (30 s), and ttl_continuation (120 s). Boat owns its
child process and a shared command deadline, but cleanup can spend 60 s probing
ancestry. Killing that owner at an outer wall can leave its separate session alive.
This is Murphy new-isolation-outer-wall-1. Item 8 in stream-d.md requires this
hardening before live qualification; no live qualification is authorized here.

## Change and deletion

Delete these six competing subprocess timeout arguments. Pass each existing
limit as BOAT_COMMAND_TIMEOUT_SECONDS in a copied environment instead. Preserve
UNBUG_PROCESS_DEADLINE, which boat-call already takes as an earlier bound.
Keep existing argv, check/capture behavior and error handling. Timeout now exits
124 from boat-call after cleanup; checked callers raise CalledProcessError, and
unchecked callers retain their existing nonzero refusal. No timeout retry or
successful remote outcome is inferred. No new transport/helper/module or manifest
entry is needed. Existing subprocess owners and cloud deletion policy are unchanged.

The waiting caller intentionally has no second timer. This follows transfer.py
and the shell callers: boat-call owns command termination and finalization. The
command limit includes version discovery. Cleanup does not buy additional command
time. Cleanup runs on success as well as failure. A pinned executable can require
two cleanup passes (version and command), but the version cleanup consumes the
shared command deadline. At most one cleanup pass overruns that deadline, with
a 60 s ps probe and 2 s reap. These are implementation allowances, not a
hard real-time guarantee: process scheduling and the probe-timeout drain are not
strictly bounded. Caller death/SIGKILL, repeated cancellation during finalization,
escaped/reparented descendants and remote processes are outside this increment.
No claim of a cloud billing bound follows from local process cleanup.

## Tests and evidence

Use saved isolation-timeouts Boat version/list/created/launch artifacts, the real
boat-call and processes.py, and an explicitly injected local transport. No cloud,
credential, decryption, or model call. Exercise actual call expressions from all
six production sites in a minimal namespace (AST extraction avoids unlocking a
holder merely to test its subprocess contract), checking their configured owner
limit and absence of an outer timeout. Run normal saved inventory output and
nonzero refusal; inherit a short process deadline for timeout injection. A slow
ps wrapper and a real heartbeat-writing descendant in a separate session prove
that the caller returns only after cleanup and that the descendant stops.
Also exercise real boat-call SIGTERM cancellation once, retaining exit status and
elapsed time. Keep a generous test hang guard separate from tested deadlines.
Tests label the local fault injection honestly; saved artifacts are not generated
by the code under test. Preserve the full suite log at a unique committed path.

Close only new-isolation-outer-wall-1 if those real-process tests pass and the
fresh diff reviewer accepts the evidence. Do not close any settlement or live
infrastructure row. Record observed local timing, without presenting it as a
maximum stopped-worker billing tail. Remaining Item 8 work is A/D cancellation
and unknown-usage settlement acceptance, B/E verified creation-through-deletion
cleanup timing, authoritative provider receipts and current-price exposure under
the separately approved practice manifest. Diagnosis stays disabled.

## Review

Fresh design review precedes implementation; a fresh diff review follows the
full suite. Any blocking fix receives another fresh review. No push or merge.

## Design-review-2 resolution and limits

Objective/impact: stop a timed-out provider query from killing its own cleanup
process and leaving local work running. Cost: local testing only, $0 cloud/model
spend. Timeline: one reviewed increment, followed by separate live qualification.

Accept B1 option (b) for this first increment, explicitly not as Item 8 readiness.
A detached descendant retaining a capture pipe can now wedge a caller indefinitely
because subprocess.run waits for EOF after boat-call exits. The single-threaded
key_holder serve loop is most exposed: one wedged inventory blocks all requests
and batch ticks. Track new-isolation-outer-wall-2 as OPEN; do not hide this under
the generic escaped-descendant exclusion. This accepts the same transport risk
already present in transfer.py and shell captures, while fixing premature owner
termination for ordinary still-owned descendants. Before Item 8 activation,
remove this risk (e.g. temporary-file capture at these bounded metadata queries)
and qualify it separately. This increment is not sufficient to launch real cases.
The test will demonstrate this limitation under a separate hang guard, terminate
the caller and explicitly kill the escaped test process so tests leak nothing.

The key_holder launch client still has a 60 s socket timeout. Slow cleanup may
outlive it, so a late successful inventory can precede an authorized launch after
the client observes uncertainty; preserve the existing no-retry/reconcile rule.
The coordinator tick deadline governs its decision after inventory, not cleanup;
retain its existing refusal at an expired decision deadline. TTL bounds are
checked before remote commands and do not interrupt them; late retirement must
remain uncertain and cannot establish deletion or a billing bound. These are
accepted pre-existing surrounding-authority limitations; no new admission or
remote-success inference is introduced. Batch status may return late, and the
batch holder's durable pending operation remains authoritative. A blocking
inventory must never be reported as a verified absent worker.

Other outer timers in tools/public-qualification/finish.py and
 tools/factory_dashboard.py (also used by factory_board.py) are excluded: these
operator/display tools need separate cleanup-policy work, especially finish.py
before live deletion qualification. This design covers the six factory call
sites only; closing outer-wall-1 does not certify every caller in the repository.

Per-site edits: key_holder and batch_holder drop timeout=25 and copy os.environ
with BOAT_COMMAND_TIMEOUT_SECONDS='25'. Both coordinator_inventory calls do the
same, adding import os. ttl_continuation drops timeout=120 and copies os.environ
with BOAT_COMMAND_TIMEOUT_SECONDS='120', adding import os. batch_status already
sets the owner variable and only drops its outer timeout keyword.

New tests: tests/factory/test_isolation_outer_callers.py. Execute the actual
subprocess call expressions for six-site contract coverage; additionally call
batch_status._boat and ttl_continuation.request_retirement directly. Holder code
extraction avoids private key/serve setup; coordinator's existing whole-function
tests retain decision/refusal coverage. Update
 tests/factory/test_coordinator_inventory.py's timeout assertion to check the
owner environment limit and absence of an outer timeout. Log the full suite at
 docs/reports/isolation-item8-prereqs-suite-<UTC timestamp>-<unique suffix>.log,
and summarize timings/limitations in docs/reports/isolation-item8-prereqs.md.
