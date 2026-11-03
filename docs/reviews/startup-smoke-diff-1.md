Verdict: **BLOCKED**

Reviewed the startup-smoke changes from baseline `f9a97ea` through integrated HEAD `4abae00`, against `docs/designs/startup-smoke.md` and the accepted resolutions in both design reviews. This is a read-only diff review using the zoom-out and implementation-readiness personas. No tests or live actions were run. Preflight dependency logic and provisioning logic were excluded as requested.

**B1 — Blocker: the new default-suite Docker test can tear down another running test or bench.**

Affected scope: `tests/factory/test_startup_smoke.py:207–246`, especially the unconditional `docker compose ... down -v --remove-orphans` in `finally`.

The test uses the repository's real Compose file, whose project name is fixed to `unbug-bench`, with shared images, database volume and host ports 9000–9001. `tests/run.py` discovers this test automatically and explicitly supports concurrent suites through a multi-slot host pool. Separate worktrees also address the same Docker project.

Two concurrent runs can therefore interfere. In particular, `factory_pool.prepare(..., fresh=True)` acquires the bench lock nonblocking and releases it after preparation. If another run owns that lock, startup fails, but this test's `finally` still deletes the other run's containers and database volume. The lock does not cover the complete test or its teardown.

Make this real-Docker qualification explicitly selectable outside the default offline suite, or isolate its Docker project, ports, images and bench artifacts. If shared Docker state is intentional, hold a host-wide exclusive lock across the entire run and teardown, and execute destructive teardown only after acquiring that lock. Preserve the real startup/G1 evidence.

The remaining scoped implementation matches the accepted design:

- Smoke receives $0.01 and practice $19.98 within the unchanged $19.99 allocation.
- Smoke dispatch adds `--dry-run`; the existing dry-run path bypasses model selection and model gates.
- Dry-run finalization supplies a fresh empty ledger, while non-dry missing-ledger accounting remains refused.
- Batch dry-run sealing creates the wrapped case key required by collection. The test checks real age decryption and archive acceptance.
- The runbook now qualifies, reserves and arms smoke first, requires its pass before practice admission, and limits disconnect/fault steps to practice.
- The hard-coded activation, cleanup and drop-in sites consistently use `-3`.
- Accounting tests use the retained canary scorecard rather than the log-excerpt fixture.
- `new-smoke-1` remains open pending evidence from the first live smoke; no live qualification is claimed.

No additional architectural or implementation blockers were found in the reviewed scope. Required focused and exact-head full-suite results remain separate from this review.

---

Elephant resolution: accepted. The shared-project real-Docker qualification now
requires UNBUG_LOCAL_DOCKER_SMOKE=1 and a quiet daemon outside the concurrent
offline suite. Its actual local result and artifacts are retained separately.
No production launch path changes, and no blocker is rejected.
