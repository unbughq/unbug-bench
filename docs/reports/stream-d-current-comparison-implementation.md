# Current-version comparison implementation

The sole producer is subsequent entry, reached before writer admission. It reuses
verified current receipts, otherwise compares retained revisions in private phase
work with parent-owned retry/accounting/checkpoint scopes. Ordinary gate versions,
limits and activation are unchanged. No Murphy row closes.

The source-copy inventory measured on this checkout is 1,579 included files and
42,277,156 bytes (about 42.3 MB), including the implementation and offline tests.
This is a local size measurement, not an upload time or production cost claim.

Focused checks: first entry 15/15; comparison 27 tests with two Linux-only process
exams skipped on macOS; the opted-in fresh/replay/valid-journal routing and existing
held-attribution main tests pass. Authored model/HTTP/Docker transports are labelled
in the tests. Real saved practice/HTTP/plain/reference bytes, real G1/G2/G3/G4/G5,
category aggregation, router reservation/settlement, records and comparisons are
exercised. No workers or live model calls were made.

Full suite and independent diff review are pending. The Linux-only tests must run
on a qualified Linux test host before activation; no Linux execution is claimed
from this Mac. Remaining implementation is listed in the item-7 checklist.
