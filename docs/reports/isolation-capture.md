# Stream E metadata capture qualification

Base: factory-simplify 022ee5b, fast-forwarded into t3/isolation-item8-prereqs.
Scope: new-isolation-outer-wall-2, six metadata queries only.

The focused isolation regression passed all eight tests. Each of the six real
production call expressions returned while a separate-session, reparented local
transport descendant retained both output descriptors. The active-write variant
preserved the saved Boat stdout artifact and synthetic diagnostic prefix while
the escaped descendant appended whitespace to both streams. Nonzero exit 9 was
preserved. Each test explicitly killed its injected escaped descendant afterward.
The tests intentionally prove no remote cancellation or cloud deletion.

Additional checks passed: either output stream exceeding 8 MiB yields 125 and
no captured stdout/stderr; positional short reads preserve the shared file offset
while the file grows and reject truncation; unselected calls still stream before
cleanup finishes; saved success/failure outputs; actual batch-status and TTL
functions; slow owned cleanup for inherited deadlines; SIGTERM owner exit 143.
Observed focused-run capture returns were about 3.3 seconds with the injected
3-second ancestry probe, inherited-deadline cleanup about 5.1–5.2 seconds, and
SIGTERM cleanup 3.25 seconds. These are local observations, not upper bounds.

Full suite passed: 159 test scripts, 0 failed, exit 0, 1648.459 seconds.
Log: isolation-capture-suite-20261031T134911Z-de8c60b4.log; its sibling JSON
records the command, branch, base, exit code, elapsed time and log SHA-256.
Design review 1 blocked shared-file-offset reads. The fix specifies positional
reads and active-write/offset tests; independent design review 2 passed.
The fresh diff review is recorded in docs/reviews/isolation-capture-diff-*.md.

No cloud worker was created; no factory/model request was sent. Cloud/factory
spend: USD 0. Reviewer delegation uses the requested Claude provider; no reviewer
billing receipt is exposed here, so no provider-token cost is inferred.

Remaining: cancellation and unknown-usage settlement qualification; verified
cloud creation-through-deletion timing and billing exposure, with any approved
Boat experiment kept below USD 1. Broader escaped-process termination, arbitrary
streaming callers, and full Item 8 activation are not certified by this increment.
Anonymous-file replay assumes trusted ordinary appending transport writers and
caps memory per stream, not disk growth from an escaped writer.
