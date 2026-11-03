# Pilot readiness integration — offline candidate

Root staging branch: merge/pilot-readiness-20261103, based on factory-simplify
f9a97ea. This is not merged, deployed, unlocked or activated.

## Integrated sources

- c318fa1: Stream D all-outcomes integration; prior merged-source suite 187/0.
- a245768: reviewed resume consumer; independent design/diff PASS and suite 187/0.
- e2cc157: reviewed bounded pilot roles; prior suite 186/0.
- a43d4a9: reviewed cleanup/serial admission and settlement audit; suite 187/0.
- 8270546: corrected preflight candidate; prior suite 187/0.
- 1a01155: corrected provisioning and startup smoke; suite 189/0, local Docker
  startup/G1/roundtrip 103.3 seconds, fresh scoped reviews PASS.

Integration preserves both retry maps and bounded-role checks in batch_holder,
and updates both old direct _admit test calls with the home argument.
The fresh integration review found a disjoint-ID guard: cleanup activated b-pilot-*
while model restrictions recognized b-real-pilot. The two-line production fix
reuses money.PILOT_BATCH for exact activation/validation. A real pin+reserve test
fails before that fix and passes after it, including invalid roles in a different
template and no authority/journal creation. Cleanup dispatch fixtures now use the
existing preflight decrypt/check doubles; production checks remain exercised by
the real preflight suite. Focused admission 18 and bounded-role 5 tests pass.
Reviews: pilot-readiness-integration-diff-1.md (FAIL, accepted/fixed), diff-2.md
(PASS; exact-ID wording nit fixed).

## Retained release evidence

Normal batch.build ran once from a clean frozen deployment checkout at 8a5c38f
into results/infrastructure/2026-11-03-pilot-deployment/release-8a5c38f. It is the
actual inactive candidate package for later normal-path deployment, not built by
regression setup. Public bytes are preserved in the fixture directory with saved
policy/pins/provenance. Production host bytes have not changed since that freeze.
Independent audit verifies all 57 host and 831 payload files against Git objects,
all release digests, original-package equality and the public policy fingerprint.
The old practice manifest stays unchanged; policy release/path/fingerprint
adaptations are explicit. Only location and throwaway recipient change in test
setup. Root observed all 28 preflight tests pass using the retained package.
Accepted preflight B2 evidence finding is resolved offline; historical review FAIL
is preserved with a separate evidence disposition. No Murphy row closes here.

## Verification and remaining gates

The initial combined suite on 9b0abf3 was interrupted after the integration review
found the ID defect. Its log/exit143 are NONQUALIFYING, not a test PASS.
Final combined exact-tree suite is next; accepted component suites are not a
substitute. No provider, worker, model, deployment, push or secret action occurred.
The founder's unrelated README.md edit and EXAM.md remain untouched.

Still required before live work: combined suite success, exact policy/release
pins and existing unlock, founder acknowledgment of the two fingerprint additions,
and refreshed live prerequisites. Cloud smoke then ordinary practice must prove
startup/G1/collection/publication/deletion and retained-card replay. Practice also
needs active-worker restart/Mac-disconnect, publication-fault replay and attributed
post-deletion per-ID lifetime settlement. Actual CLI cancellation and isolated-UID
acceptance remain unqualified. The pilot is inactive, supports six attempts/two
per case/six-hour admission, and requires an explicit decision on no replacements
and the competing nine-slot/twelve-hour proposal. No fleet or exam readiness is
claimed.
