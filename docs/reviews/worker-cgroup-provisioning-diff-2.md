**Verdict: BLOCKED.** One blocking finding remains in the corrected provisioning scope.

Mode: REVIEW. Personas: `zoom_out` and `implementation_readiness`; standards: `zoom-out-standard.md` and `implementation-readiness-standard.md`. I read `AGENTS.md`, `docs/ENGINEERING.md`, the provisioning design, prior diff review, source report and evidence, and the scoped integrated diff against `f9a97ea`. Corrected provisioning source: `b72ea97`. Preflight `c93f91e` and startup-smoke logic were excluded. This review was read-only; no tests, live actions, cloud operations, secrets access, or edits were performed.

### Blocker: in-place resume installs the helper outside the supervisor’s import path

- **Severity:** Blocker
- **Affected scope:** `factory/resume-in-place.sh:27-34`, `factory/runner_supervisor.py:12-13`, `tests/factory/test_account_handoff.py:244-251`, and the design’s claim that parked workers receive the matching helper.
- **Finding:** The archive contains `factory/` and `bin/processes.py`, but extraction uses `tar -xzf ~/factory.tgz -C ~`. This installs the helper at `~/bin/processes.py`. The supervisor imports `processes` from `$BENCH/bin`, defaulting to `~/unbug-bench/bin`. Neither `worker_resume` nor the remote resume command changes `BENCH` to match the archive destination.
- **Concrete failure:** A parked worker carrying the pre-provisioning `~/unbug-bench/bin/processes.py` receives the new supervisor but continues importing the old helper. Calling `processes.prepare_model_containment(home)` raises `AttributeError`, which the supervisor’s `ContainmentError` handler does not catch. No runner starts and no new `containment_unavailable` receipt is written. Supervisor stderr is discarded by `worker_resume`, so this also bypasses the new public startup-failure path.
- **Why the regression misses it:** `test_in_place_upload_carries_matching_supervisor_and_process_helper` checks archive member bytes only. It does not extract into a real worker layout or verify which helper the staged supervisor imports.
- **Required fix:** Install the helper into the existing bench import location used by both supervisor and runner. Preserve the shared supervisor path. Strengthen the regression using a worker layout containing an old bench helper: apply the actual staging/extraction operation, then verify that the staged supervisor imports the newly supplied helper and reaches the provisioning boundary. Update the design/report claim accordingly.
- **Simplicity rationale:** This needs a corrected deployment destination and a focused regression, not another import fallback or resume implementation.

### Prior blockers

1. **Startup status readers: resolved.** The launch probe recognizes `containment_unavailable` as `STARTUP_FAILED`. Collection accepts attempt 0 only for the `startup` / `containment_unavailable` / exit-78 tuple and rejects that reason outside the tuple. The launch-guards regression drives this receipt through the real probe and collection readers and verifies the retained control-side status.

2. **Direct in-place runner invocation: routing resolved, deployment incomplete.** `account_handoff.worker_resume` now invokes `runner_supervisor.py -- python3 …/run.py`, preserving runner arguments, credential environment, and explicit existing duration/grace values while supplying normal defaults. Fresh launch, automatic continuation, and this resume route therefore share the supervisor. The helper destination blocker above prevents that correction from working on older parked workers.

### Checks that pass

- Provisioning precedes runner creation. Successful preparation exports the deterministic cgroup root through the supervisor’s existing child environment.
- The implementation reuses `processes.py`, the existing supervisor, and passwordless sudo. It adds no alternate launch path, opt-out, cgroup sweep, or fallback.
- The privileged helper takes numeric identity/process arguments rather than an arbitrary filesystem path, checks process UID, uses the deterministic cgroup location, and delegates the common ancestor needed for nonroot migration.
- The original containment admission, leftover refusal, and kill/drain machinery remain intact.
- Synthetic transport fixtures explicitly replace the provisioning boundary and are not represented as kernel evidence. Real-kernel tests separately exercise root provisioning, runner inheritance, and nonroot enrollment/kill.

### Evidence assessment

The report distinguishes historical cached results from the corrected, cache-free run. The retained final log ends with **184 test scripts run; 0 failed**, matching `evidence.json` for tested source `363fe93`. The scoped provisioning implementation and tests have no diff between that source and `b72ea97`. The kernel log records six passing tests; the negative control records failure because the original supervisor never called preparation.

This evidence supports the tested source behavior but does not cover the archive extraction/import mismatch identified above. It is also not a new full-suite result for the current integrated tree. Live VM provisioning, actual CLI cancellation, and isolated-UID acceptance remain explicitly unqualified; no Murphy row is closed.

**Result: BLOCKED until the in-place helper destination and its regression are corrected.**

---

Elephant resolution: accepted. Extraction now installs the helper under the existing
${BENCH:-$HOME/unbug-bench} import root. The regression stages an old helper,
executes the extraction command, imports the staged supervisor, and reaches its
provisioning boundary and retained startup refusal. No blocker is rejected.
