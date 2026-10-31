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
time. A pinned executable may require two cleanup passes (version and command),
each with a 60 s ps probe and 2 s reap. These are implementation allowances, not a
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
