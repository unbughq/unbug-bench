# Provisioning and startup-smoke offline integration

This branch owns provisioning and startup smoke only. It starts from the
factory-simplify snapshot f9a97ea and retains source branches by merge:

- Provisioning source b72ea97, including corrected cache-free 184-script evidence,
  kernel evidence and the original blocked review.
- Existing preflight dependency c93f91e. Its retained-release evidence blocker and
  correction remain sibling-owned. This branch does not qualify preflight or
  change its logic/release fixtures.
- Startup-smoke source dd1a22e, including accepted design-review resolutions.
- The old smoke checkout's exact uncommitted test diff, copied without changing
  that checkout. The patch and SHA-256 are in provisioning-startup-smoke/.

## Changes beyond the sources

Three merge conflicts were resolved by retaining both Murphy additions, keeping
preflight's phase-A/B runbook and behavior, and applying smoke's -3 batch identity,
19.98 practice ceiling and smoke-first runbook. The runbook describes two serial
workers, concurrency one, within the same model/infrastructure ceilings.

Fresh provisioning review found that in-place resume extracted the helper to
~/bin while the supervisor imports it from the bench tree. Extraction now installs
bin/processes.py under ${BENCH:-$HOME/unbug-bench}. The real archive/layout exam
stages a stale helper, executes extraction, imports the staged supervisor, and
checks the preparation boundary and retained startup refusal.

Fresh smoke review found that its shared-project Docker test could disrupt
parallel offline suites. The actual Docker qualification now requires explicit
UNBUG_LOCAL_DOCKER_SMOKE=1, run separately on a quiet daemon. Default offline
suites never enter its startup or destructive teardown. This changes a test
selection boundary, not the production launch path.

The smoke argv exam's old secret_labels double was incompatible with c93f91e's
bundle-based preflight API. It now uses the same decrypt/dispatch_checks doubles
as the existing holder argv tests; no live checks execute. The initial failure
and corrected result are both retained.

## Reviews

All reviews are saved verbatim, with elephant resolutions appended separately:

- docs/reviews/worker-cgroup-provisioning-diff-2.md: BLOCKED; destination finding
  accepted and fixed.
- docs/reviews/worker-cgroup-provisioning-diff-3.md: fresh independent PASS.
- docs/reviews/startup-smoke-diff-1.md: BLOCKED; shared Docker test finding
  accepted and fixed.
- docs/reviews/startup-smoke-diff-2.md: fresh independent PASS.

No accepted design review was rerun. The later test-double adjustment changes no
production behavior and uses the already established holder-test boundary.

## Evidence

Focused logs and source provenance are under provisioning-startup-smoke/.
The eight focused Python scripts record 112 tests with no failures; three
expected skips are two Linux-only kernel exams and the explicitly selected Docker
qualification. The separate preflight integration exam passed all 28 tests.
Launch guards passed all lifecycle checks in 391.605 seconds, including the
containment startup receipt; no real Boat calls. Its log is retained separately.
Local real Docker qualification at f9429d2 passed in 103.309 seconds:
terminal_stop=stopped_after_g1, G1=true, dry_run_roundtrip.identical=true.
The actual scorecard, G1 result and runner log are saved under local-startup/;
throwaway private keys are not retained. It is local startup evidence, not a
Boat-worker result. Historical provisioning kernel and negative-control evidence
remain byte-preserved under worker-cgroup-provisioning/.

After the focused tests complete, commit this offline candidate and run exactly
one cache-free full suite on that head:
`rtk proxy uv run --with numpy --with scipy python -B tests/run.py`.
The full-suite log and result record are written outside the checkout to
/tmp/provisioning-startup-smoke-<full-HEAD>.{log,json}, keeping the tested head
unchanged. The handoff names the exact head and result; no later code or evidence
commit is made after that suite begins.

## Remaining blockers and live check

This branch grants no live authority. Root owns integration, the sibling preflight
correction and final release pins. No deploy, unlock, provider/model qualification,
secret retrieval, worker, paid run, push or main operation was performed.

After root integrates the sibling correction and all required offline evidence,
the remaining smoke check is the one normal launch path on the real worker:
qualify/reserve/arm smoke first, dispatch it, collect and publish its card, verify
startup/prepare and G1, record G3, verify deletion, then replay that retained
collected card through batch_service and collection_facts. Practice may proceed
only after that smoke passes. Use the same -3 policy/release/cleanup/drop-in pins,
0.01 smoke + 19.98 practice = 19.99 total; no parallel launch path or extra money.
Live provisioning, actual-CLI cancellation and isolated-UID acceptance remain
unqualified. No Murphy row is newly closed; new-smoke-1 remains open.
