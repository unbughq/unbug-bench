**Verdict: FAIL — two blocking findings remain. Round 2 of 2; return to parent.**

Reviewed frozen HEAD `b79362e10011a8a2360f72b6fd8f408105d741ef` in `/Users/bugsincode/Developer/ub-preflight`, against merge-base `5b3cd0b` with `factory-simplify`. Excluded incoming land17/parallel-runner changes and evidence-only commits. Applied `zoom_out` and `implementation_readiness`, Mode: REVIEW, after reading the engineering rules, standards, design and previous reviews.

1. **Blocker — preflight still misses a deterministic launcher refusal.**  
   [factory/practice_preflight.py:245](/Users/bugsincode/Developer/ub-preflight/factory/practice_preflight.py:245) calls `router_delivery.pack` directly. The launcher invokes `router_delivery.main`, which additionally rejects **base64 input** exceeding 16 MiB at [factory/router_delivery.py:73](/Users/bugsincode/Developer/ub-preflight/factory/router_delivery.py:73). `pack` checks decoded archive size instead.

   Reproduced with the normal authored bundle plus a selected `statements-key` containing 13 MiB:
   - Real dispatch returned `0`, recorded `dispatch_started=True`, and reached the mocked launcher spawn without a hold.
   - The corresponding selected archive encoded to 18,186,240 bytes. Preflight router validation passed, while the real `router_delivery.main` returned `1`, printing `router delivery refused`.

   This retains round-1 B1’s failure mode: a bundle passes preflight and becomes irreversibly started before a predictable launcher refusal. Enforce the launcher’s encoded-input limit on the actual selected archive before dispatch starts, preferably through shared validation. Add a real-dispatch regression asserting `TEMPFAIL`, pending state, `dispatch_started=False` and no spawn.

2. **Blocker — round-1 B2’s saved-release requirement remains incomplete.**  
   [tests/factory/test_preflight.py:107](/Users/bugsincode/Developer/ub-preflight/tests/factory/test_preflight.py:107) creates a temporary source commit and calls `batch.build`; setup then replaces the saved policy’s release path and digest. The retained release record is described but never loaded or verified.

   The retained policy and unchanged manifest are now used, `batch.verify` is real, and the host-drift negative control is useful. Nevertheless, this verifies a freshly generated release rather than the saved pinned release required by the brief and design. The incompatibility of the historical release explains the substitution but does not provide the missing evidence.

   Load an independently retained, compatible release and its pinned digest for these dispatch regressions. If that artifact is unavailable, leave the evidence requirement unresolved and adjust [docs/murphy-register.md:83](/Users/bugsincode/Developer/ub-preflight/docs/murphy-register.md:83) accordingly.

The specific duplicate-member, unsupported-type, nested-name and prefixed-label regressions from round 1 now retain pending state. Recipient and fingerprint refusals remain terminal. The single-status-RPC correction and removal of the unused paid-ceiling calculation are present. Resolved-role Codex gating and the Boat installer checksum guard are present. No additional launch path was introduced.

Focused tests, all with `BENCH` set to the reviewed checkout:

- `test_preflight.py`: 27 passed.
- `test_batch_holder.py`: 60 passed.
- `test_router_delivery.py`: 5 passed.
- `test_control_vm.py`: 22 passed.
- Additional in-memory oversized-bundle probes reproduced finding 1; no test files were edited.

The recorded 186-script full-suite pass at `b0024a2` was inspected, not rerun. HEAD remains frozen and the worktree clean. No live qualification, provider access, deployment, merge or activation was performed. Latest-`factory-simplify` integration remains the parent’s responsibility. The deliberate fingerprint additions do not resolve the pending founder acknowledgement of future unlock friction.

## Parent disposition

Both blockers accepted; no rejection and no third review round.
B1: reproduced through the real dispatch with a selected 13 MiB member: it
returned 0 instead of TEMPFAIL. The shared router_delivery.pack now enforces
the same encoded-input limit as its CLI, before config/RPC work. The new
dispatch regression requires pending state, dispatch_started=false and no spawn.
B2 remains unresolved: the tracked retained practice release is 6ac450e with
44 host files, incompatible with the current 55-file host contract. No
compatible independently retained release was found among the tracked release
fixtures/reports. Do not manufacture a fixture with batch.build to claim closure.
new-preflight-2 is reopened and the design's closure statement corrected.
Preflight remains unmerged and live qualification is not authorized here.

## Parent focused verification

The new oversized selected-bundle dispatch test failed before the one-line fix
(returned 0 instead of TEMPFAIL=75), then passed in the full touched test file.
BENCH=/Users/bugsincode/Developer/ub-preflight python3 -B tests/factory/test_preflight.py:
28 tests passed in 15.597 seconds (plus four import-time support tests).
BENCH=/Users/bugsincode/Developer/ub-preflight python3 -B tests/factory/test_router_delivery.py:
5 tests passed in 3.028 seconds. No cloud/provider activity.
The earlier 186-script result belongs to b0024a2, not this follow-up. A new full
suite and integration validation remain required before handback/merge, after
the retained-release evidence blocker is resolved. The round-2 verdict stays FAIL.

## Integration evidence resolution (2026-11-03)

The historical FAIL above is retained unchanged. B1 was fixed at c93f91e.
B2 is now resolved by the real candidate deployment release frozen at 8a5c38f,
retained under tests/factory/fixtures/preflight-deployment-release, with saved
policy/provenance and unchanged practice manifest. Independent artifact audit:
docs/reviews/pilot-deployment-retained-evidence-audit.md (PASS). Root observed
28 passing dispatch/preflight tests with no batch.build or release repinning in
test setup. This is evidence resolution, not a third implementation review or
live qualification. Final combined suite and live launch prerequisites remain.
