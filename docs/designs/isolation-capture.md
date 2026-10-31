# Metadata capture without descendant pipe waits

## Problem and objective

A stray background process can freeze the key holder forever, blocking every
request and batch tick in its single-threaded loop. Make the six provider
queries return after their owner finishes.

Murphy new-isolation-outer-wall-2 remains open after 93028e4. An escaped,
reparented transport descendant inherits the outer caller's capture pipes. Boat
finishes cleanup, but subprocess.run in a holder still waits for EOF. The
existing real-process regression demonstrates this failure. Prevent that wait
for the six metadata call sites covered by isolation-item8-prereqs.md. This is
the next increment, not certification of Item 8 or cloud billing.

## Change and deletion

Add opt-in BOAT_CAPTURE_OUTPUT=1 to the six existing per-call environments in
key_holder, batch_holder, coordinator_inventory (two), batch_status, and
ttl_continuation. In bin/boat-call, when opted in, give the command private
binary TemporaryFile stdout/stderr descriptors, instead of inherited pipes.
Wait for processes.run and its cleanup exactly as now, then snapshot each file
size with os.fstat and read only that many bytes using os.pread at explicit
offsets, without seek/read or any change to the shared file position; replay
them to Boat's own stdout/stderr. Never read to an evolving EOF. The only
writer to outer capture pipes is now Boat itself; escaped descendants inherit
anonymous regular files. No additional subprocess or competing timeout is
introduced. Version discovery already uses the bounded processes.run capture
path and never inherits the caller's pipes. Escaped version writers may cause
124 at the command deadline, not an indefinite wait.

Cap accepted metadata at 8 MiB per stream. If either snapshot exceeds the cap,
return 125 with a diagnostic, without emitting either captured stream; only the
owner diagnostic goes to stderr. This 125 overrides an ordinary nonzero command
exit. Read snapshots before emitting either stream; short positional reads are
continued at the next offset, and premature EOF fails closed with 125. Preserve
command exit codes and both output streams on ordinary completion; retain
existing timeout 124 and SIGTERM 143 behavior. For timeout/cancellation,
TemporaryFile contexts wrap processes.run inside processes.deadline and close
during unwinding after cleanup; do not drain failed capture. Partial command
diagnostics on timeout/cancellation are discarded; the owner timeout diagnostic
remains. Remove BOAT_CAPTURE_OUTPUT from the transport environment so nested
calls do not silently inherit this opt-in. An escaped writer may continue
appending to its anonymous file: this does not prove descendant death or remote
completion, and the cap bounds replay memory, not disk consumption while the
command runs. Files use the control VM temp directory (TMPDIR where
configured); losing pipe back-pressure risks disk growth. Transport writers are
trusted to append normally; pread does not prevent them from deliberately
seeking/pwriting over old bytes. Pipes also trusted transport output; this
change introduces no claim of adversarial output integrity. Cleanup cannot
guarantee death of reparented processes; that broader isolation issue stays
separate.

Delete the metadata calls' reliance on inherited transport output pipes and
replace the existing expected-hang regression with a return-before-escaped-
child-exits assertion. Default Boat behavior stays streaming for transfer and
shell callers; their output contracts are not silently changed. No new module,
manifest entry, provider call, retry, accounting behavior, or security
boundary.

## Tests and acceptance

Extend tests/factory/test_isolation_outer_callers.py, using its saved Boat
version/list/created/launch artifacts and injected real local transport.
Execute all six actual production expressions (AST extraction), asserting opt-
in and inherited deadline propagation. Check saved inventory success, nonzero
status, slow owned cleanup after timeout, and SIGTERM cleanup. For each
metadata call, spawn a detached heartbeat writer retaining both streams, delay
ancestry until it is reparented, and verify caller completion while that child
still runs. Explicitly kill every injected escaped child. Include nonzero
escaped command output and an oversized-output failure proving no partial
success leaks. Check TTL stdout/exit status at its production check_output
boundary and stderr at the outer test harness; other sites capture both. Add an
actively writing escaped child: it appends whitespace to saved stdout and a
synthetic stderr marker while the caller returns. Flush the prefix before
spawning the writer. Assert each replay starts with the exact original artifact
bytes and contains only the appended whitespace thereafter (JSON stdout stays
the saved inventory). For deterministic coverage of the shared-offset race,
execute the snapshot helper with a real temporary file whose shared offset is
at EOF, force small positional-read chunks by patching os.pread in the helper
loaded via runpy, and assert that the offset never moves. A real escaped writer
regression and this focused offset check cover both halves. Test default
streaming remains available. The separate generous test hang guard is never a
production timeout. Full suite command: `uv run --with numpy --with scipy
python -B tests/run.py`. Commit its unique log and result record. Fresh
goldfish design and diff reviews are required; fixes for blockers require
another fresh review.

## Scope, cost, and follow-on

Close only new-isolation-outer-wall-2 after real-process tests and accepted
diff review, with tests/factory/test_isolation_outer_callers.py as Closed by.
Expected timeline: one local implementation/test/review cycle. Local testing
costs $0; this increment uses no paid factory calls or cloud workers.
Cancellation/unknown-usage settlement qualification is next, followed by
verified cloud creation-through-deletion timing and billing exposure. No claim
of complete Item 8 readiness, stopped-worker billing bounds, or coverage for
arbitrary shell captures follows from this change.
