# Diagnosis continue: resume a session that stopped before its result

## Problem

`case-import-cb5e26-h5-1` is held. Its diagnosis attempts 2-1, 3-1 (19:10 UTC) and 4-1 (19:21) on
2026-11-19 each ended `infra:diagnosis_result_missing`. After the infra retries ran out, the engine
held the case.

- **Where the reason comes from.** `diagnosis_invocation._helper` raises it when the root helper's
  `collect` finds no `result.json` in the task output (status `missing`).
- **Why no result was written.** OpenCode `run` ends the session at the first step that finishes
  with reason `stop`, meaning a reply with no tool call, and it exits 0.
- **What the model did.** The diagnosis model is the case's reviewer, MiMo
  (`openrouter/xiaomi/mimo-v2.6-pro`). In all three attempts it replied without a tool call before
  writing the result:
  - 2-1: after 9 requests, an 88-token message;
  - 3-1: after 25 requests, 2,779 output tokens, 2,778 of them reasoning;
  - 4-1: after 4 requests, 152 output tokens, 151 of them reasoning.
- **No error.** No requests were refused by the gate, and no error events were recorded.
- **The same stop on other MiMo work that day.** MiMo reviewer transcripts from the same window
  stopped the same way, for example `22e434-h2`:
  - reviewer-g16 stopped on reasoning alone (output 1, reasoning 9,662);
  - reviewer-g2-confirm narrated a next step and stopped.
- **Why the retries did not help.** Each engine retry started a fresh session with the same prompt,
  met the same stop, and threw away everything the session had already read.

## Change

1. **Continue the same session.** `diagnosis_invocation.invoke` runs the session, and if `collect`
   says `missing`, it reruns OpenCode with `--continue` and a short fixed prompt, `CONTINUE`. The
   prompt names the output path and the rule that a reply without a tool call ends the session.
   - Up to `CONTINUATIONS = 2` continuations. Each one is its own accounted model call, under the
     same lease, cap and `before_attempt=reset` as the first.
   - Any other collect status (`unsafe`, `oversized`, `input_invalid`, invalid) still stops at once.
2. **Keep the session between runs.** `model_runtime._invoke` puts the OpenCode data home
   (`XDG_DATA_HOME`, where OpenCode keeps its sessions) for a diagnosis inside the pilot's memory
   home (`pilot_home('pilot')/.local/share`).
   - This applies only to a pilot run named `diagnosis-*`.
   - The pilot's memory home lasts for the whole invocation, and `dispose_diagnosis_pilot`
     unmounts it, so the session is gone afterwards.
   - Other runs keep their per-run scratch data home.
3. **Codex and Claude.** Diagnoses on these models keep one session as before. Their runners keep
   no OpenCode session to continue.

A continuation is passed to the runtime as the attribute `c.diagnosis_continue`. The `finally`
block resets it.

## What it deletes

Nothing. The change adds a loop and an `--continue` flag; it replaces no path.

## Gate identity

No gate reruns.

- **The changed files are in no gate identity.** `diagnosis_invocation.py` and
  `model_runtime._invoke` are outside every gate's `runner_inputs` closure, outside
  `STAGE_DEPENDENCIES`, and outside `model_science`. `model_science` covers only
  `model_router.family` and `model_runtime.model_effort`.
- **What a resume reruns.** Only the diagnosis step.

## Tests

All in `tests/factory/test_durable_diagnosis_invocation.py`.

- **`test_a_session_that_stops_before_its_result_is_continued`**
  - Collect says missing, missing, then ok: there are three sessions, the second and third are
    continuations with `CONTINUE`, and the call returns the result.
  - Collect always says missing: the call stops `diagnosis_result_missing` after
    `1 + CONTINUATIONS` sessions.
  - Collect says `unsafe`: the call stops at once, with no continuation.
- **`test_codex_and_claude_diagnoses_are_not_continued`.** A Codex or Claude diagnosis runs one
  session and stops `diagnosis_result_missing`.
- **`ContinuedSession.test_a_diagnosis_session_outlives_its_run_and_is_continued`**
  - **Setup.** The test uses the real router lease row of cb5e26-h5's diagnosis 4-1 (MiMo,
    `openrouter-key`, $12.50 window). It runs the real `ModelRuntime._invoke` and the real
    `openrouter_environment` twice for one diagnosis.
  - **What it checks.**
    - Both runs share the pilot's data home.
    - The second command is the first plus `--continue`.
    - A reviewer run never continues and keeps its own data home.

Red check: on the unfixed code the two new behaviour tests fail and every other test passes.

These tests prove the loop and the command. They do not prove that the pinned OpenCode resumes the
session (see Limits and the Murphy row).

## Limits

- **Resumption is not proven on the pinned binary.** The tests prove the command and the shared data
  home, not that OpenCode 1.19.0 under `sudo -H -u pilot` finds and resumes the first run's session.
  The first live continuation shows whether it does.
- **`--continue` takes the most recent session.** It does not name one. Within one invocation there
  is only one root session in the pilot's home, because `task` is denied. `--session <id>` from the
  first run's events would be exact, but it is not needed today.
- **`reset` still runs before each continuation.** It wipes `output/`, the session's working folder.
  This is intended: every model run starts from a checked, empty output, and collect has just said
  the result is missing.
- **Worst-case spend per diagnosis attempt rises from one call window to three ($37.50).**
  - Each continuation takes its own lease under the call window and the attempt's money ceiling.
  - Until `new-cached-window-1` is fixed, each continuation's first request is priced at the full
    input rate for the whole history.
  - Before this change, the engine's fresh retries spent up to a window each, three times.
- **A failed continuation replaces the reason.** If the continuation itself fails (for example
  `model_call_cap` or `timeout`), that error, not `diagnosis_result_missing`, becomes the stop.
- **Transcripts stay longer.** The diagnosis session stays in the pilot's 0700 memory home until
  disposal, where before it was in per-run scratch. A failed unmount leaves it there, but
  `make_pilots` refuses a leftover home and workers are ephemeral.
- **The Codex/Claude test reads the requested model's prefix.** It does not read the leased route.
  This is correct while no chain mixes those drivers with OpenCode routes.
- **Repeated stops still hold the case.** A model that stops three times in a row holds it as
  before, but after one invocation instead of three fresh ones.
- The failed sessions' transcripts are not kept. A failed diagnosis seals no snapshot and the worker
  is ephemeral, so the evidence above comes from engine records and router receipts. Keeping the
  transcript on failure is a separate change.

## Murphy rows

The register is not on `main`. The rows are recorded here and go into the register when that file
lands.

- **New row `new-diagnosis-early-stop-1`:** "a diagnosis model replies without a tool call before
  writing its result; OpenCode ends the run and every fresh retry repeats it" (seen 2026-11-19 on
  cb5e26-h5, diagnoses 2-1, 3-1 and 4-1).
  - Status: mitigated, open (review diff-1).
    - `tests/factory/test_durable_diagnosis_invocation.py` proves the continuation loop, and the
      `ContinuedSession` test uses the real 4-1 lease.
    - Neither shows OpenCode 1.19.0 resuming a real session.
    - The row closes when a live diagnosis records a continuation that writes its result, or when
      a Linux pilot test runs the pinned binary twice and sees the same `sessionID`.
- **New row `new-cached-window-1`:** "the model-call gate prices cached prompt tokens at the full
  input rate, so a long cached session hits `model_call_cap` far below its real cost" (open).
  - **Seen** 2026-11-19 on cb5e26-h5:
    - gates 1/17-1 (G10 easy calibrator) stopped `model_call_cap`, which sent the case to
      diagnosis;
    - diagnosis 1-1 was cut at $12.05 against the $12.50 window, while OpenRouter charged $2.40
      for 27.6M prompt tokens, 74% of them cached.
  - **The token cap binds too.** The lease's input-token cap (max_usd / input price = 28.7M) binds
    at almost the same point.
  - **Not fixed here.** `model_call_gate` and its pricing are not touched by this change.
