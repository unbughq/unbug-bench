# Factory efficiency implementation — 2026-10-20

Status: implementation, offline tests and bounded public cloud recovery qualification;
real-case production activation pending.
The under-24-hour objective has not been demonstrated. Existing cloud runs have not
been modified by this implementation work.

## Implemented

| Area | Behavior now implemented | Boundary |
|---|---|---|
| Candidate board | Serialized encrypted reservations, revision checks, historical imports, complete hashed snapshots, Boat/Hetzner delivery. | Delivery is separate from authorized resume; the recurring coordinator does not yet operate the selection round. |
| Admission | Candidate selection precedes construction; missing board evidence blocks construction; duplicate and public-bug checks run early. | Complete old cases retain their authored files; an independent idea-only realism review remains to be added. |
| Prototype | Tests a minimal bug, reference repair, legitimate traffic, refusal control and wrong repair before full construction. | Full final checks remain required; automatic prototype repair/reselection remains to be wired. |
| Calibration | Each completed attempt is committed atomically, bound to inputs/configuration, and validated on resume; an unchanged early strong attempt counts symmetrically. | Interrupted incomplete attempts restart; a different model or changed case cannot inherit another attempt's result. |
| Local repair | Up to two later gate repair rounds on the same worker, within existing budgets. | Operational errors propagate to recovery; unchanged repairs stop; early construction checks can still repeat. |
| Check reuse | Dependency hashes and retained evidence determine reuse; missing evidence means rerun. | Flakiness and solved-guard validation rerun; legacy pass flags alone are insufficient. |
| Checkpointing | Encrypted checkpoints at safe completed-call/gate boundaries, throttled to 15 minutes; explicit remote-durability receipt. | Long in-flight calls can lose work since the last safe boundary; local-only checkpoints do not survive worker loss. |
| Collection | Resumable ciphertext chunks, final digest verification, atomic promotion; uncertain collection retains the worker and prior good archive. | Recovery still needs a verified checkpoint and reconciled budget. |
| Account recovery | Bounded coordinator selects an authorized available Claude account with matching model/effort; holder rechecks generation and recovery configuration. | Requires a fresh complete inventory snapshot, reviewed fixed-job policy, unlocked holder and known previous launch outcome. |
| Worker qualification | Source manifest and selected CLI versions verified before restoring secrets/case; timeout overrides isolated; TTL margin bounded. | A refreshed Boat environment is baked and clone-checked; Boat still replaces CLI links at startup, so the existing pre-secret pin step remains necessary. Full-case qualification is pending. |
| Migration | Preserves authored case files; validates calibration receipts and gate evidence before reuse. | Old checkpoints without sufficient evidence rerun checks; they do not require rewriting the case from scratch. |

## Remaining before unattended production

1. Install the recurring invocation of `coordinator_inventory.py` after canary qualification; its fresh provider census and persistent account concurrency configuration are implemented. Connect statement reservation/delivery to the same lifecycle.
2. Qualify and update the trusted holder policy for the changed runner/launcher, preserving original models, limits, seed, source, rotation and deadline; activate through the existing private unlock path.
3. Resume one checkpointed real case as the canary and qualify live account handoff. Public mechanical controls and bounded graceful-stop/SIGKILL recovery passed on a cloud worker; full semantic/model gates and full-case seal remain unqualified.
4. Reconcile uncertain worker loss and spend explicitly; an absent worker alone must not authorize duplicate execution or reset a budget.
5. Complete real-case qualification on the refreshed, clone-checked environment before scaling; add measured capacity/credit checks and TTL extension to the coordinator.
6. Add an automatic stage funnel/time/cost report and measure end-to-end time-to-seal before publishing a speedup claim.

Additional savings still open: shared reusable public-search evidence with expiry,
multiple candidate fallback, idea-only realism review, bounded prototype repair,
and broader deterministic-test reuse where dependency evidence permits it.

## Offline verification

Regression coverage includes interrupted calibration after a committed attempt,
same-worker repair, stale/missing evidence, reservation races, repeated pilot setup,
interrupted transfer, checkpoint publication failure, account capacity, stale holder
attestation and cumulative-budget regression. These tests use synthetic fixtures;
they do not establish live provider or full Docker calibration behavior.

Verified locally: factory discovery passed 78 tests with one skip and no failures/errors;
import-time regression scripts also completed. Python compilation, changed-shell syntax,
guard-bound regression and tracked diff whitespace checks passed.

Run the factory unit suite from the repository root with:

```sh
BENCH="$PWD" python3 -m unittest discover -s tests/factory -p 'test*.py'
```

Some repository checks are executable scripts with their own entrypoints, outside
unittest discovery; run the focused recovery/transport/guard checks as well. Preserve
all existing staged and unstaged work when reviewing this change.

Stage 2 evidence and the prepared migration policy: [qualification report](../results/infrastructure/2026-10-20-factory-stage2/README.md).
