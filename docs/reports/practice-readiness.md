# Offline plumbing practice readiness

Base 070a332 includes A shared paid spending and B cumulative clamps. The frozen
preflight was rerun there: PINS STALE, retained in practice-readiness-initial.json.
The current plan and classification are docs/designs/practice-run.md and
practice-readiness.md. Parent approved the sole second-round design blocker fix:
worker start + 30 minutes normal collection < start + 45 minutes deletion <
start + 60 minutes provider TTL. No third design review.

Offline changes: one fresh authenticated zero-baseline manifest and bounded
explicit roles; manifest-specific opt-in using existing release authentication;
independent cleanup service with shared serialized deletion receipts; a one-shot
pre-transport publication fault; current preflight and one-command pin production.
Both global gates remain disabled. No service was installed or activated.

The pin command refuses dirty/stale heads and must run after this reviewed change
is merged: `python3 -B tools/pin-practice.py --output /ABS/NEW`. It cuts whatever
reviewed factory-simplify head is then available, with no lane-2 dependency.
Current preflight reports pins=unpinned; all other offline checks pass. These are
contract checks, not deployment qualification. No final release pins fabricated.

Live-only list and incremental ceilings: provider bounds plus legacy debt $0;
distinct accounts and deployment $0; armed admission $0; one worker through
verified deletion $5; account-2 model work and settlement $19.99; publication
replay included, $0 additional. $0.01 remains unused. Total reserved $25.
Unknown cost/ownership is an abort or retained hold, never a pass or new allowance.
The likely first result remains a $0 abort if the provider bound or legacy debt
cannot be resolved. No cloud guarantee can be manufactured by offline tests.

Queued-child creation is OFFLINE item-8 work outside this one-worker plumbing
practice, as accepted in design review 2; it is not relabeled LIVE or closed.
Helper comparison, diagnosis, replacement and multi-worker carry remain separate.
No Murphy rows closed. No workers, paid calls, live cloud, secrets or pushes.

Validation uses retained collection/creation artifacts with authored bindings;
systemd/provider transports and pin containers are explicit doubles. Existing
isolation and holder tests pass; thirteen new contracts pass, including timing,
wrong ready PID/hash/launch, fault replay, unknown deletion holds, and stale pins.
Full-suite record and a fresh diff review follow.

First full suite: a61b705, 172 scripts, 9 failed. The unique source-bound JSON
and compressed log are retained (20261102T015856Z-68d9ba0b). Fixes restore
guard diagnostic labels, supply the extracted helper to staged layouts, retain
the historical observation grammar and update the explicit worker-file inventory.
The integration test also caught a real worker archive ownership mismatch: host
control/tools files now travel separately in the pin bundle, not as new worker
source roots. Watcher readiness now hashes the complete policy, with a regression
for changed code under an unchanged manifest. No provider calls were involved.
The real commit-built pin artifact smoke test passed at a61b705 with only the
merged-head identity check substituted for this unmerged branch; it was temporary
and removed, never production pins. The CLI guard itself is tested for rejection.
