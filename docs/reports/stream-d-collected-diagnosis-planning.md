# Authenticated collected-generation planning

Implementation baseline: b80929a (accepted opt-in plus parallel-tests ee17a83).
Design reviews: stream-d-collected-diagnosis-planning-design-1.md (findings
accepted), design-2.md (PASS, no blocker or major).

The existing holder tick now calls plan_collections. Production plan requests
supply a durable producing-operation ID and revalidate current source, immutable
collection, ACK/outbox/pointer, retirement, frozen config and money state inside
plan's existing money lock. Facts and queue identity commit together. The shared
_post prefix is reused, one snapshot is verified per attempt, consumed/retired
sources are skipped, and refusals retry after a 60-second process-local delay.

No pilot activation, reserve/dispatch path, money grant or schema changes.
No manifest opts in and no Murphy row closes. Resume queue draining remains
the next increment; this caller alone does not execute diagnosis.

Focused verification: test_batch_planning.py 11 tests OK; test_batch_holder.py
60 tests OK. The first exploratory planning run also included the imported
HolderTests class (58 tests OK); the import was corrected to module-only before
the focused 11-test run so the handback suite does not duplicate those tests.
Controls are explicitly labelled: retained ciphertext/card/creation event with
authored bindings, retirement proof and diagnosis API projection. No real
diagnosis eligibility or live qualification is claimed.

Full suite: pending, one run without lockf on the committed implementation.
Fresh diff review: pending.

