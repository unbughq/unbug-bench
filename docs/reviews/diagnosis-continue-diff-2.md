# Review: diagnosis-continue, diff 2

Reviewer: fresh goldfish subagent (Claude, read-only). Personas: `zoom_out` and
`implementation_readiness`, from elephant-goldfish-model, with their standards. Scope: `HEAD~2..HEAD`,
because main and this branch share no merge base in the reviewer's checkout.

## Review (verbatim)

**Verdict: PASS.** No blocking findings. The live test runs the binary the way `_invoke` runs a diagnosis closely enough, and it does prove the resume works, which was round 1's blocking finding.

Scope note: `main` has no common ancestor with this branch (`git diff main...HEAD` fails with "no merge base"), so I reviewed `HEAD~2..HEAD`, the two commits. Both test files pass locally: 19 run with 3 skipped, and 1 run with 1 skipped on macOS.

### 1. How closely the live test copies production
These match production:
- **User and home:** `useradd -m`, then a tmpfs mounted over the home with `mode=0700,size=2g,nodev,nosuid,uid,gid`, then `.cache` at 0700. This matches `run.make_pilots(diagnosis=True)`.
- **Environment:** HOME and TMPDIR are the same as `diagnosis_environment`. The XDG config and cache dirs are fresh per run, as in production. The data home sits in the pilot's home, as `_invoke` now sets it.
- **Command:** the same OpenCode flags, `--standalone` detection and `sudo --preserve-env -H -u … sh -c 'cd "$1"…'` wrapper, with the prompt on stdin.
- **Variant:** for MiMo `model_effort` returns `default`, so leaving out `--variant` is correct.
- **No result is fake:** the stub calls `write` only when it sees two user turns (`test_opencode_continue_linux.py:55`). So the result file exists only if the history really carried over.

Differences that are not material, though each is cheap to close:
- **NIT `tests/factory/test_opencode_continue_linux.py:129-135`:** two production steps between runs are skipped.
  - `reset` (`diagnosis_task.py:165-167`) deletes and recreates `output/`, so the working folder has the same path but is a new directory.
  - `_invoke`'s cleanup runs `pkill -KILL -u pilot` and then `_quiet` (`model_runtime.py:974-975`).
  - Neither should affect 1.19.0 finding the session: lookup goes by path, and the first process exited 0 before the second started. Adding both steps would leave nothing to argue about.
- **NIT `tests/factory/test_opencode_continue_linux.py:105-116`:** the provider config and env keys are copied by hand from `model_call_gate.openrouter_environment` instead of calling it. That function is pure (lease, env, and a gate with `server_port` and `token`).
  - If production drifts, the live test keeps passing. For example, if `XDG_DATA_HOME` dropped out of the `keys` tuple at `model_call_gate.py:772`.
  - Today only the stubbed `ContinuedSession` test ties the live test to production code.

### 2. Is the Murphy row properly closed?
Mostly yes. The test uses the real binary and the real VM layout, and the stub is not built from the code under test. It reproduces the stop: a plain reply ending with `stop` and no result. It then shows that `--continue` keeps the `sessionID` and the history, and writes the result. Whether MiMo itself then writes is honestly listed as a limit (design lines 108-109). If it doesn't, the case still stops with the old `diagnosis_result_missing`.

- **NIT `tests/factory/test_opencode_continue_linux.py:117,142`:** the test never checks the OpenCode version.
  - It uses `shutil.which('opencode')`, not `FACTORY_OPENCODE_BIN` (`model_runtime.py:32`), and only prints the version.
  - Closing the row rests on "pinned 1.19.0", but on a box with 2.x the test would pass through the `--standalone` path.
  - Add `assertEqual(version, '1.19.0')`, as `tests/factory/router_cheap_pin_probe.py:43` does.
- **NIT `docs/designs/diagnosis-continue.md:101-104`:** the pass and the red check on worker box bx_zgwcjuqa are claims in prose only.
  - The red check needs the test edited (line 114 hardcodes the new data home), so nobody can rerun it as written.
  - Consider saving the run's output as a fixture, as `tests/factory/fixtures/neuralwatt-smoke-20261119.json` does.
- **NIT `docs/designs/diagnosis-continue.md:136-137`:** `docs/murphy-register.md` is not on this branch (`git ls-files` finds nothing). ENGINEERING §2 requires setting Status and Closed by in the register, so that has to happen when this merges into `factory-simplify`.

### 3. The round-1 nits
All six are written up honestly in the Limits section, and none of them blocks:
- **Failed continuation replaces the reason:** a `model_call_cap` during a continuation turns a retryable infra stop into an out-of-money stop (`classify.py:186`). But the engine's old fresh retry would have hit the same cap.
- **NIT `docs/designs/diagnosis-continue.md:110-112`:** "only one root session … because `task` is denied" is not exactly true.
  - When a provider fails, `ModelRuntime._call` (`model_runtime.py:628-634`) re-runs the first turn without `--continue`. That leaves a second root session in the pilot's data home.
  - `--continue` then picks the newer session, which is the right one, so behaviour is correct. Only the stated reason is wrong.

### 4. Cleanup, gate identity, security
- **NIT `tests/factory/test_opencode_continue_linux.py:80-100`:** the test can leave a user and a mounted tmpfs behind.
  - If setUp fails between lines 83 and 89 (`id`, `mount`, `install` or `mkdtemp`), cleanup crashes on `self.server.shutdown()` because `self.server` does not exist yet. The `pkill`, `umount`, `userdel` and `rm` steps then never run.
  - Cleanup is registered only after `useradd`, so a user left over from an earlier crash makes every later `useradd` fail with nothing cleaned up.
  - The fix: register cleanup before `useradd`, guard each attribute with `getattr`, and run `userdel` on any leftover user first.
  - The risk is limited: the test only runs when `FACTORY_LIVE_OPENCODE=1` is set, workers are ephemeral, and the tmpfs is `nodev,nosuid`.
- **Gate identity:** unchanged. `diagnosis_invocation.py` and `_invoke` are outside `runner_inputs` and outside `model_science`, which covers only `family` and `model_effort` (`gate_state.py:261-266`).
- **Security:** no regression.
  - The session store moves from per-run tmpfs to the pilot's tmpfs home (0700, unmounted when the pilot is disposed). It belongs to the same UID that already reads the inputs.
  - No auth file is copied in for a diagnosis, and the gate token goes only into the env config, never onto disk.

## Response (elephant)

**Fixed:**
- **Version check.** The test now asserts OpenCode `1.19.0`, as `router_cheap_pin_probe.py` does.
- **Cleanup safety.**
  - Cleanup is registered and run before `useradd`, so a leftover user from an earlier crash is removed first.
  - `server` and `work` are guarded.
  - The test was rerun on bx_zgwcjuqa: it passes on 1.19.0, and no user, mount or temp dir is left.
- **Root-session wording.** The design now says a provider retry can add a newer root session, and
  that `--continue` correctly picks it.

**Not taken (nits):**
- **`reset` and `pkill` between runs.** Lookup goes by path, and the first process has exited.
- **Calling `openrouter_environment` directly.** That would make the live test import the factory
  on a bare box. The stubbed `ContinuedSession` test already ties the env keys to production.
- **Run-output fixture.** The pass and the red check are recorded in the design with the box,
  version and date.
- **Register.** The rows move into `docs/murphy-register.md` when that file lands. Noted in the
  design.
