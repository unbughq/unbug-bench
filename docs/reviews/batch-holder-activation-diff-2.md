**FAIL/PASS verdict: PASS.** No blocking finding is left open in the final holder activation increment: 150800a plus 564c1c8, integrated with b500db9 by 9d39185, reviewed at HEAD 564c1c8.

**The diff-1 blockers are all fixed:**
- **B1 (fixed).** `_reconcile_one` (`factory/batch_holder.py:339-350`) now checks things in a safe order:
  - It first needs a free operation lock, a matching `launch.json` and a free nonblocking `controller.lock`.
  - Any `new.*` file keeps the operation `pending`.
  - Only then does it read `ids`, and it treats only `FileNotFoundError` as empty.
  - A symlinked or nonregular `ids` still fails with `ELOOP` or `ValueError` and stays `pending`.

  This is safe because of how `control_resume.py` works. It takes `controller.lock` before it writes `launch.json`, and `launch.sh` inherits that lock. So a free lock plus a matching record means no controller is alive, and with no `new.*` file no worker was ever created. `test_early_exit_before_guard_init_has_no_ids` builds the real layout `control_resume` leaves behind (directory, `launch.json`, `controller.lock`, no `ids`) and covers four cases:
  - held controller lock → `pending`;
  - `new.1.pending` present → `pending`;
  - dangling `ids` symlink → `pending`;
  - none of these → `failed`/`preflight_refused`, with `dispatch_exit` still None, so no recorded exit is needed.
- **B2 (fixed).** The fence test now passes the valid argv `'1'`. It requires `FileExistsError` in stderr and checks that neither `launch.json` nor `controller.lock` appeared, so only the `mkdir` fence can make it pass. This matches `control_resume.py`, which runs `state.mkdir(mode=0o700)` with no `exist_ok`.
- **B3 (fixed).** `test_publication_replay_and_terminal` now covers the real publish path:
  - **Failed transport first:** `collect` with a raising transport leaves the outbox `pending`, no ACK and no pointer, and `unpublished` lists the operation.
  - **Real `main` publish path:** argparse `publish` → `stdin.buffer` → `bytearray` → `publish_replay` → the real `_r2_env`.
  - **Only two doubles:** a stub `age` that cats a real tar, and the R2 transport.
  - **Real parsing:** the tar holds an `r2-env` member in the exact four-line `printf` format of `bin/setup-secrets:77`, and the secret value includes `/+=`.
  - **Credentials reach transport:** the transport asserts the parsed values are in `os.environ`.
  - **Success:** ACK, pointer generation, outbox `acknowledged`, objects uploaded, and the operation drops out of `unpublished`.
  - **Identity zeroing:** the test captures the same `bytearray` object `main` passed and checks it is all zeros after `main` returns.
  - **Environment:** it is restored with `patch.dict` (diff-1 N4).

**Other required evidence:**
- **Bounded retry and restart (M2):** the test asserts the 60/120/240/480 s windows exactly and that nothing respawns at window minus 1 s. A fresh `children`/`waits` after two failures continues to `failures == 3`. It ends terminal at `RETRY_LIMIT`, and a later fresh tick does not respawn.
- **M3:** real corrupt `money.json` goes through the real `reconcile` inside `batch_tick`, and the resume and publish scans still run. The canonical `$UNBUG_CONTROL_HOME/policy.json` passes the policy check and reaches runtime setup. This is a narrow test and the elephant does not overclaim it.
- **Documented ceilings:** M1 (a stale ACKed generation is not replayed), N1 (shared failure counter), N5 (old reservations rejected; brief `running` display) and the residual where a controller killed between `mkdir` and `launch.json` stays `pending` (`docs/designs/batch-holder.md:602-605`). All four are written into the design as accepted ceilings.
- **Murphy rows:** none are claimed closed, and no live gate is enabled.

**Nits (optional):**
- **N-a.** Backoff waits live only in memory. A holder restart respawns at once, ignoring the remaining backoff window; the durable count still caps retries. The test's restart happens after the window has passed, so it does not show this. One design line accepting it would be enough.
- **N-b.** The failed-transport step calls `holder.collect` directly, not through a holder publish child. Together with the replay through `main`, this proves the stated property, but a failure inside a holder-spawned publish child is only covered by the separate five-failure terminal path.
- **N-c.** In `_reconcile_one`, `ids = b''` relies on `_regular` returning a binary stream. That is correct today; a comment-free coupling.

**Limitations:**
- I read `docs/ENGINEERING.md`, `zoom_out.md`, `implementation_readiness.md`, the readiness standard, the design addendum and clarifications, `diff-1` with its elephant response, `factory/control_resume.py`, `bin/setup-secrets` and the changed code and tests.
- At 564c1c8 I ran only `tests/factory/test_batch_holder.py` (46 tests OK) and `tests/factory/test_batch_status.py` (14 tests OK). I did not run the full suite, because the final one is running elsewhere.
- Nothing ran against a real VM, real `age`, real R2 or a real `launch.sh` early exit. The lock-ownership argument comes from reading the source.
- I did not review the proposed account-router handoff plan as an implementation.
- I changed nothing in the worktree.

---
Reviewer: goldfish (Claude Opus 5.5), final diff review of 150800a+564c1c8 at HEAD 564c1c8. Mode: REVIEW, personas `zoom_out` + `implementation_readiness`, `implementation-readiness-standard`.

## Elephant response (2026-10-31)

Accepted PASS. B1-B3 are fixed; no blocker was rejected. N-a is now explicitly
recorded in the design: backoff timers are in-memory and can restart immediately,
but the durable failure count still limits attempts. N-b and N-c are accepted
optional nits; no code changes are needed. Full-suite completion is recorded in
docs/reports/stream-b-activation-suite-20261031.md. No Murphy rows closed, no
live gates enabled, no paid practice run authorized or performed.
