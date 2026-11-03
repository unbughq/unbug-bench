# Partial first-entry reconstruction

Implementation e70949c retains a verified contiguous prefix when closed.json is
absent. Only a prevalidated missing record becomes unreached. Corrupt proof,
later records and checkpoint pass/fail labels still hold. G3 versions are pinned
after restoring workers on a copied context. Every retained case copy covers its
support map; historical freshness may differ, but the last record and retained
G2/G8/G9 copies must match live freshness. No evaluation or new score is added.

## Integration and validation

Merged factory-simplify 7dbdc58 into this branch at 502b15b. This includes upstream
E's O7 containment and O5b request-only retirement work. The partial-entry code
and tests retain their implementation from e70949c; the qualifying full suite
runs on the integrated head, not the earlier pre-merge tree. Focused entry tests
passed 19/19 before integration and again afterward (59.720s).

Qualifying record: stream-d-partial-entry-suite-20261103T120754Z-b0d5253d.json
and its .log. Head 502b15b2ecd2a2cd08f88e70eed57ce015d29a76;
tree 8e06c2b83f85fff25bfe4ac803c22539ff034bcf. Result: 182 scripts, 0 failed,
exit 0. Log SHA-256: 51f5ff86f813d618061630127848014713e568450ed663a25672f38e2a4376d4.
The updated entry file also passed all 19 tests in the full run (44.965s).

The parent approved a validation-policy change: detached nohup/lockf execution,
no -t, with the 7200000ms timeout starting AFTER lock acquisition. Queue time does
not count. The log ends with exit 0. Execution took 2916.3s; queue wait was 5083.7s.
The record includes the command, timeout runner source, timestamps and log hash.

Earlier attempts adca5675 and beb1ca4a are retained as non-qualifying interruptions,
not test failures. The first was stopped safely before the former outer deadline
after about 88 minutes queued. The second was stopped to adopt the parent-approved
runner after about 90 minutes queued. Both have null final counts, an explicit
interruption reason and no passing claim. No production/test fix separates them
from the implementation; upstream integration precedes the qualifying run.

## Review and scope

Design review rounds 1 and 2 are retained in docs/reviews/stream-d-partial-entry-design-{1,2}.md;
round 2 passes. Fresh diff review remains required. The exact three prior hold
expectations change as the approved design specifies. Existing outcome-route,
attribution and retry assertions are unchanged by this slice.

No Murphy rows close for this slice. Activation stays off. Remaining item-7 work:
legacy evidence adapters (4–7h), then all-outcomes integration (4–6h, including
irrelevant-edit progress checks), plus shared-lock/provider queues. No pilot is
started here. The founder's three-case pilot follows item 7.
