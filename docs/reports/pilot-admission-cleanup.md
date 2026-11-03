# Serial pilot admission and cleanup — offline handoff

Baseline f9a97ea; branch t3/pilot-admission-cleanup-settlement. Root integrates.
No merge, push, main edits, cloud/provider/model qualification, secrets, deploy,
unlock, workers, paid run or live authority. Root scoreboard files untouched.

## Delivered

Authenticated pilot opt-in on the existing holder/reserve/dispatch/bind path, with
three fresh canonical jobs, concurrency one, six operation attempts, at most two
per case, six-hour admission window, and one full TTL remaining before dispatch.
Money values are manifest parameters; cumulative Boat authority is unchanged.
No manifest or activation pin is supplied. Global holder and diagnosis switches
remain off; ordinary practice stays on its existing service/path.

The existing cleanup owner now supports a persistent batch service, per-operation
ready/status binding and live-before-terminal restart ordering. Both armed checks
require predecessor cleanup settlement; the second is under the batch money lock
before durable dispatch. No shell launch occurs while the predecessor is unknown.

R2-B1 is fixed through the existing ledger: a reconciled failed/preflight_refused
operation with no worker can clear only with free owner locks, intact launch or
reconciliation fence, no creation intent/IDs, and an existing validated ledger
with no row bound to that state. Missing ledger/lock is unknown. Any bound row
retains the existing settlement path, and any pending creation/owner blocks.
The real guard refusal test creates spend-finished without reserving a ledger
row; the next dispatch no longer deadlocks on that operation. Historical home-wide
holds still refuse in the unchanged Boat admission guard. Neither empty inventory
nor missing files are deletion evidence. No reservation, debit or operation slot
is released or reset by this clearance.

Boat's ledger reader was extracted unchanged into boat_lifecycle for reuse;
cleanup explicitly refuses its admission-only missing-ledger default. Reconciliation
can fence a before-controller launch when its launches parent is absent.

## Independent reviews and verification

- Prior design rounds retained verbatim from 963d70d in
  docs/reviews/pilot-admission-cleanup-design-{1,2}.md. The design's continuation
  records the authorized R2-B1 resolution; no third design review was requested.
- Fresh missing settlement diff review: docs/reviews/boat-attributed-settlement-diff-1.md,
  PASS for 2c174ba^..0292abc. Merged settlement code was not rebuilt.
- Fresh pilot diff review: docs/reviews/pilot-admission-cleanup-diff-1.md, PASS.
  Both nonblocking test suggestions implemented. No accepted review repeated.
- Focused: pilot admission 17, Boat settlement 14, practice readiness 15,
  holder 60, control resume 24, worker release 9, launch manifest 2 passed.
  The first manifest check caught the new module missing from its expected
  packaging inventory; expectation updated, same check passed. The first new
  fence test caught the missing launches parent; fixed and passed. These were
  authored offline regression failures, not new observed real-run Murphy events.
- Cap-removal and ready-marker-removal temporary source mutations are detected.
  Fixtures reuse saved public cards, opaque ciphertext, real creation identity and
  real deletion receipts through existing tests; clocks, policy, service/provider
  responses and multi-job bindings remain explicitly authored. No Murphy row closed.
- Exactly one final-candidate full suite follows the commit containing this report:
  `rtk proxy uv run --with numpy --with scipy python -B tests/run.py`.
  Authoritative exact HEAD/tree, exit, wall time and full output are retained at
  `/tmp/pilot-admission-cleanup-suite-20261103T220744Z.{json,log}`. The handback
  reports that run's result; review never substitutes for it.

## Remaining gates and explicit residual decision

This is an inactive offline candidate, not permission to launch. Root/founder must
settle the section-4 no-replacement exception explicitly, plus final lifecycle/time
bounds: this implementation supports only the reviewed six-creations/two-per-case/
six-hour policy, not the later nine-slot/twelve-hour proposal. Supporting the
proposed policy does not approve it. No replacement or second launch path is added.

Live evidence remains required for EVERY created ID: matching creation/deletion
receipts and complete absence inventory, then stopped lifetime per-ID usage after
deletion (including month boundaries), with final cumulative settlement in the
existing home ledger. A 404, unsupported usage verb or incomplete response keeps
the hold and stops reuse; no account-balance substitution is available. Also retain
credit/auto-top-up/snapshot/proxy/containment and strict absolute timing gates.
Provider creation latency precedes the durable start clock; admission-window checks
do not prove an absolute deletion deadline.

Root owns re-pin/deployment/manifest/routes/diagnosis headroom and the tested Stream D
resume-consumer dependency a245768, plus land19 c318fa1 and its 187/0 integration log
`/Users/bugsincode/Developer/land19-suite-20261103T194005Z.log`. They are not merged or
duplicated here. Cleanup policy/release/pin must remain frozen until all known
operations finish; unknown ownership or liability stays fail-closed with cleanup
and provider TTL retained. The six attempt slots include failed/uncertain attempts.
