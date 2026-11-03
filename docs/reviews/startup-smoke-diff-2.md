Verdict: **PASS**

Reviewed the startup-smoke scoped diff from `f9a97ea` through candidate `f9429d270daec2811ab215693fd3fe073e367738`, against `docs/designs/startup-smoke.md`, both accepted design-review resolutions, and the blocker in `docs/reviews/startup-smoke-diff-1.md`. Applied the zoom-out and implementation-readiness personas and standards. This was a read-only review; no tests, Docker actions, live/cloud operations, secret access, edits or pushes were performed.

**Prior blocker B1 is resolved.** `tests/factory/test_startup_smoke.py:205` now decorates the real Docker qualification with `unittest.skipUnless(os.environ.get('UNBUG_LOCAL_DOCKER_SMOKE') == '1', ...)`. Without explicit selection, unittest skips the method before its body executes: neither the `run.py` startup subprocess nor the destructive Compose teardown in its `finally` runs. The default offline suite therefore excludes this shared-project Docker qualification. Its docstring and the accepted design require running it separately on a quiet daemon. The shared Compose project remains intentional for that explicitly selected qualification.

The remaining scoped implementation matches the accepted design:

- The authenticated `-3` manifest and `practice.EXPECTED` give smoke $0.01 and practice $19.98 within the unchanged $19.99 batch ceiling. Smoke adds `--dry-run` to the practice launch arguments.
- Dry-run final accounting uses a fresh empty ledger default. Non-dry missing-ledger behavior remains unchanged and is covered by refusal assertions using the retained canary scorecard.
- Batch dry-run sealing wraps the case key needed by collection. The regression test exercises real age encryption/decryption and `batch_service._card` acceptance, while mocking the R2 upload.
- Activation, cleanup-unit and holder-drop-in identifiers consistently use `-3`; the preflight practice ceiling is $19.98. The retained `-2` manifest remains available as historical evidence and as the prior-version test input.
- The runbook qualifies, reserves and arms smoke first, requires collection, publication, G1 and verified deletion before practice admission, and applies disconnect and publication-fault steps only to practice.
- The change reuses the existing batch launch, accounting, sealing and collection paths. It introduces no unnecessary production abstraction or parallel launch path.
- `new-smoke-1` remains open until a test replays the first live smoke’s retained collected card. The scoped changes do not claim Boat qualification.

No blocking findings or additional actionable findings remain in the reviewed scope. Preflight dependency logic and provisioning were excluded as requested. Focused tests, explicit local startup qualification, exact-head full-suite results and the final source-evidence record remain separate verification records; this review does not substitute for them.
