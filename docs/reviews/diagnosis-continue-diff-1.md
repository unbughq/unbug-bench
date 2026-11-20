# Review: diagnosis-continue, diff 1

Reviewer: fresh goldfish subagent (Claude, read-only). It used the zoom_out and
implementation_readiness lenses directly, because `tools/egm` is not in the repo.

## Review (verbatim)

**Verdict: FAIL.** The code looks correct and the tests pass (16 run, 3 Linux-pilot tests skipped on macOS), but the design closes Murphy row `new-diagnosis-early-stop-1` without proof. Nothing has shown that OpenCode 1.19.0 actually resumes the session.

### BLOCKING

- **docs/designs/diagnosis-continue.md:101-102 and tests/factory/test_durable_diagnosis_invocation.py:280-328 — the Murphy row is closed without a real-artifact proof.**
  - `ContinuedSession` stubs `run_budgeted`, `enforce`, `pwd.getpwnam` and `_opencode_flags`. It checks only the argv (`... + ['--continue']`) and that both runs get the same `XDG_DATA_HOME` string.
  - No session is ever created or resumed. The only real artifact is the router lease row, which has nothing to do with the failure.
  - So three claims are untested:
    - that `opencode run --continue` under `sudo -H -u pilot` finds the first run's session in `/home/pilot/.local/share`;
    - that it continues with the prior context;
    - that a MiMo session continued after a stop actually writes `result.json`.
  - The row's failure mode is exactly the behaviour the code assumes, and the workers pin 1.19.0. The local binary is 2.2.7, which talks to a background service unless `--standalone` is passed, so session storage is version-sensitive.
  - Fix: either add a test under `LinuxHelperQualification`/`linux_pilot()` that runs the real 1.19.0 binary twice in a pilot tmpfs home and asserts that the second run's events carry the first run's `sessionID`, or mark the row "mitigated, open" until a live diagnosis shows a continuation writing its result.

### NIT

- **factory/model_runtime.py:820 — `--continue` picks the "last session" by guess.** The first run's `--format json` events already carry `sessionID`, and the transcript is saved. Passing `--session <id>` would make the choice certain, so a retry inside the runtime or a second root session could never be picked up by mistake. Today there is only one root session, because `task` is denied, so this is a robustness point rather than a live bug.
- **factory/durable/diagnosis_invocation.py:119 — `before_attempt=reset` runs before each continuation and wipes `output/`.** That folder is the session's working directory, so any notes or partial files the model wrote there are gone while its history still points to them. Skipping reset on continuations would be safe: collect has already returned `missing`, not `unsafe`, and `O_NOFOLLOW` still catches a planted link. Otherwise the design should say the wipe is intended.
- **factory/durable/diagnosis_invocation.py:18 (and design line 32) — worst-case spend per diagnosis attempt rises from 1 to 3 call windows (up to $37.50).**
  - Each continuation takes a new lease and reservation under `call_window` and the attempt's `money_ceiling`, so no limit is broken.
  - But because of `new-cached-window-1`, each continuation's first request re-sends the whole history priced at the full input rate.
  - The Limits section should state this, given the founder's "no money until a seal" rule.
- **factory/durable/diagnosis_invocation.py:118-124 — a continuation that fails replaces the original reason.** `timeout` (from `engine_call_window` near the deadline), `model_call_cap` and similar errors hide `diagnosis_result_missing`, which changes how `repeated_infra_stop` sees the history. Consider chaining the original error, or noting this as a limit.
- **factory/model_runtime.py:841-842 — transcripts now stay in `/home/pilot` until disposal**, where before they were unmounted after each run. If `dispose_diagnosis_pilot` fails at the `pilot_home` unmount, the mounted home keeps the private diagnosis transcript, and `engine_seal` (run.py:3835) copies any existing `/home/pilot` into `agent-state`. The window is narrow because `make_pilots` refuses a leftover mounted home and workers are ephemeral, but it is new. Nothing becomes visible to other UIDs: the home is mode 0700 and owned by the pilot.
- **factory/durable/diagnosis_invocation.py:115 — the Codex/Claude exclusion checks the requested model's prefix**, while the runtime picks the driver from the leased route. It is correct today because no entry in `CHAINS` mixes `claude/` or `codex/` with OpenCode routes, but it would silently break if a chain ever did. Checking the leased route's driver would be safer.

### Checked, no issue

- **Flag leakage:** `--continue` needs `user == 'pilot'`, a `diagnosis-*` name and `c.diagnosis_continue`. `copy.copy(c)` in `_call` carries the flag through, and the `finally` resets it first. The reviewer case in the test confirms no leak.
- **Retries inside the runtime during a continuation:** they re-run `--continue` against the same session. Usage events are keyed `sessionID:messageID:partID` and `seen` is seeded from the ledger, so a replayed event cannot be double-booked.
- **Engine checkpoint replay:** it does not apply, because the diagnosis working directory is outside `c.work`.
- **Gate identity:** unchanged. `diagnosis_invocation.py` and `model_runtime._invoke` are outside the `runner_inputs` closure (`run.py` only), outside `STAGE_DEPENDENCIES`, and outside `model_science` (`family`, `model_effort`, both untouched).
- **Network access:** Go, NW and free routes still refuse `user=pilot`, so diagnosis stays on the gated OpenRouter, Claude and Codex lanes.

## Response (elephant)

- **BLOCKING, fixed** with the reviewer's second option. Row `new-diagnosis-early-stop-1` is now
  "mitigated, open", and the design says how it will close.
  - The first option, a Linux pilot test on the real 1.19.0 binary, needs that binary and a model
    call.
  - The pinned binary is not on this machine, and the VM is read-only for this work.
- **Nits:** all are now stated in the design's Limits section. None changes the code:
  - `--continue` versus `--session`: only one root session exists today.
  - The `reset` wipe is intended.
  - Worst-case spend.
  - A failed continuation replaces the reason.
  - Transcripts stay longer in the pilot's home.
  - The Codex/Claude test reads the requested model's prefix.
- **Re-review:** a fresh goldfish should confirm before merge. This was not done in this stream.

## Follow-up

- The coordinator then asked for the first option.
- `tests/factory/test_opencode_continue_linux.py` runs OpenCode 1.19.0 twice on worker box
  bx_zgwcjuqa:
  - it passes;
  - it fails with the old per-run data home.
- The row is now closed by that test; see diff-2.
