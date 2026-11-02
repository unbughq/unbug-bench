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

Live-only list and incremental ceilings: live Boat credit/top-up verification $0;
distinct accounts and deployment $0; armed admission $0; one worker through
verified deletion $5; account-2 model work and settlement $19.99; publication
replay included, $0 additional. $0.01 remains unused. Total reserved $25.
New-run unknown cost/ownership is an abort or retained hold, never a pass or new
allowance. The founder decisions below resolve the former provider-bound and
legacy-debt prerequisites. Live credit/top-up, account, deployment and lifecycle
checks remain; this is no longer characterized as a likely $0 abort for those
two superseded prerequisites.

Queued-child creation is OFFLINE item-8 work outside this one-worker plumbing
practice, as accepted in design review 2; it is not relabeled LIVE or closed.
Helper comparison, diagnosis, replacement and multi-worker carry remain separate.
No Murphy rows closed. No workers, paid calls, live cloud, secrets or pushes.

Validation uses retained collection/creation artifacts with authored bindings;
systemd/provider transports and pin containers are explicit doubles. Existing
isolation and holder tests pass; thirteen new contracts pass, including timing,
wrong ready PID/hash/launch, fault replay, unknown deletion holds, and stale pins.
Full-suite records are below; a fresh diff review is required before handback.

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

Packaging-fix validation: all 24 controller-resume and 16 account-handoff tests
pass with the canonical suite BENCH environment; all 6 batch-launch integration
tests pass. The pin, inventory, TTL and gate-smoke contracts pass. The real
commit-built pin smoke also passes at 08d7228 with the same explicitly substituted
merged-head identity check; the temporary bundle was removed. The refreshed
preflight names that source commit and still refuses uncut final pins. Production
pinning remains one command after the reviewed merge; no lane-2 dependency.

Final implementation validation: `uv run --with numpy --with scipy python -B
tests/run.py` passed at 6e67efa33f089a8e4277591b0a0cbd2acbac1d05: **172 scripts,
0 failed**, exit 0. The source tree, timestamps and compressed/uncompressed hashes
are in practice-readiness-suite-20261102T024431Z-8ee060ec.json; its .log.gz is
committed beside it. This supersedes the failed first run as implementation
validation. The full launch-guard scenarios also passed separately (450 seconds,
no real Boat calls). No code or test changed after the passing suite source commit.

Fresh Claude diff review round 1: PASS, no blockers; saved verbatim in
../reviews/practice-readiness-diff-1.md. Per the parent instruction to hand back
as soon as review passes, this increment stops without another implementation
or review round. One non-blocking major remains open (M1): an exception from the
practice activation check in batch_tick can stop the key-holder loop and lose
its in-memory identity. The reviewer recommends catching it and testing the
refusal. This is an OFFLINE issue, not a live-only deferral; it is handed back
explicitly, not rejected or claimed fixed. Seven optional nits remain recorded.
No source/tests changed after the passing suite, and no Murphy rows closed.


Parent follow-up before merge: M1 is implemented by catching activation-check
failures in batch_tick, logging only `batch activation refused`, and returning.
One new regression corrupts the authenticated manifest with the practice
environment set, checks repeated refusal without exceptions, and then checks a
successful following scan after restoring the manifest. Nit 1 is a five-line
runtime correction for an authenticated pre-creation wait; creation intent still
produces uncertainty. Step 6 documents the missing-start TTL backstop and the
fault-command export (nits 3 and 4). Nits 2, 5, 6 and 7 stay open. Fourteen focused
practice tests pass. Full-suite validation and the scoped Claude re-check follow.
No live action or Murphy closure. This obvious-cause fix has fewer than 20 runtime
lines and uses the ENGINEERING.md small-fix exception, with a fresh diff re-check.

A premature suite start (20261102T033050Z-08be06c5) was stopped after a shell
quoting error prevented the preceding commit. Its source fields identify only the
base commit, not the uncommitted patch. The retained record explicitly marks the
run non-qualifying; it is not used as validation. A new run follows the commit.

## Founder decisions — 2026-11-02

> Provider bound ACCEPTED: Boat's prepaid credit balance (below $5, no auto top-up) together with the 60-minute TTL auto-delete is the accepted $5 infrastructure cap. A hard provider-side cap is not required.

> Legacy launch b275ffccd6134a33833853ad1d31ed16 is WRITTEN OFF as having created nothing, based on the empty Boat inventory plus no unexplained billing. Any later charge traced to it goes on the infra-waste line.

Launch b275ffccd6134a33833853ad1d31ed16 is **disposed by founder write-off**.
No legacy file is deleted and no completion marker is fabricated. A later charge
traced to it belongs on the infra-waste line. This records an accepted disposition,
not a newly observed provider deletion or billing receipt.

Step 1 must read the live Boat credit balance and verify auto top-up is off.
Abort if balance exceeds $5, auto top-up is on, or those checks cannot be completed.
No hard provider-side cap or further reconciliation of this disposed launch is
a prerequisite. These decisions supersede the earlier provider-contract and
legacy-debt requirements in the readiness design and historical preflight group
labels. They do not remove the other live entry checks or authorize live action
in this increment. They are included in the scoped M1 re-check.

The founder requested these decisions in the same M1 commit while its suite was
running. Only practice-run.md and this report were amended; runtime and test
bytes are unchanged. Suite provenance records both the initial source commit and
the final doc-only amendment, with the changed paths verified.

M1 full-suite validation passed: **172 scripts, 0 failed**, exit 0, using
`uv run --with numpy --with scipy python -B tests/run.py`. The committed record is
`practice-readiness-m1-suite-20261102T033207Z-0c21fe85.json`, with its hashed
`.log.gz`. The run began at e4715b760b63e18091b2a6938a76a5f37df6cc2e;
fd92c3d10b07b28d35a6be840fb5dd935bcd5bf1 amended only the two decision documents.
The JSON retains both source commits/trees and the verified changed paths. No
runtime or test bytes changed during or after this passing run. The scoped fresh
Claude re-check is diff round 2 of 2; nits 2, 5, 6 and 7 remain open.
