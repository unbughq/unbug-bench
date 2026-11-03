**Verdict: PASS.** No blocking finding remains in the reviewed provisioning scope at `f9429d2`.

Mode: REVIEW. Personas: `zoom_out` and `implementation_readiness`; standards: `zoom-out-standard.md` and `implementation-readiness-standard.md`. I read `AGENTS.md`, `docs/ENGINEERING.md`, the provisioning design, both saved provisioning diff reviews, the scoped changes against `f9a97ea`, and the correction against `b72ea97`. This review was read-only: no edits, tests, live actions, cloud operations, secrets access, or pushes. Preflight dependency `c93f91e` and startup-smoke logic were excluded.

### Prior blockers

1. **Helper deployment destination: resolved.** `factory/resume-in-place.sh` extracts `factory/` into the worker home and separately extracts `bin/processes.py` under `${BENCH:-$HOME/unbug-bench}`. That matches the existing import root in `runner_supervisor.py`. An older parked worker therefore receives the matching helper at the location the supervisor actually imports.

2. **Deployment regression: resolved.** `test_in_place_upload_carries_matching_supervisor_and_process_helper` now goes beyond archive inspection. It creates the existing worker bench layout, installs a stale helper that raises if imported, executes the production extraction line, and imports the staged supervisor in an isolated Python subprocess. It verifies the imported helper path and bytes, calls `supervise`, and checks that the preparation boundary is reached and the public startup refusal is retained. Replacing preparation with an authored failure is appropriate for this deployment test; real cgroup behavior has separate coverage.

3. **Startup status readers: resolved.** The launch probe recognizes `containment_unavailable` as `STARTUP_FAILED`. Collection permits attempt 0 only for the exact `startup` / `containment_unavailable` / exit-78 tuple. The launch-guards regression drives this tuple through the actual probe and collection readers and verifies the retained receipt.

4. **Direct in-place runner invocation: resolved.** `account_handoff.worker_resume` invokes the shared supervisor before `run.py`, preserves runner arguments and credential environment, and supplies the normal duration/grace defaults while preserving existing explicit values.

### Implementation assessment

- Preparation runs before runner creation. Failure returns 78, writes the fixed startup receipt, and starts no runner. Successful preparation exports the deterministic cgroup root through the existing child environment.
- Provisioning reuses `processes.py`, the supervisor, and the existing passwordless sudo dependency. The helper uses numeric identity/process inputs, verifies the process UID, creates the deterministic cgroup location, and delegates the common ancestor required for nonroot migration.
- The original containment admission, leftover refusal, and kill/drain machinery remain intact. Provisioning does not sweep prior call scopes or introduce a fallback.
- Fresh launch, automatic continuation, and account/in-place resume share the supervisor. The corrected extraction fixes deployment at its source without adding another import path or resume implementation.
- The design accurately describes the corrected deployment destination and regression. No new Murphy closure is claimed.

### Validation boundary

This is a **code and diff review PASS**, independent of the forthcoming focused and full-suite evidence. I did not rerun or certify those tests. Historical evidence does not establish a full-suite pass on `f9429d2`. Live worker provisioning, actual CLI cancellation, and isolated-UID acceptance remain outside this review.

**Result: PASS for the scoped provisioning changes at `f9429d2`; no actionable blocking findings.**
