**Verdict: APPROVED.** No blockers or majors remain. B1–B3 and M1–M4 are closed in both the design addendum and the current test and helper. Five nits are below; none has to be fixed before implementation validation.

# Goldfish design review 5: "Loaded launch-guard regression (2026-10-30)"

**Mode:** REVIEW. **Personas:** zoom_out, design_critic, implementation_readiness. **Standards:** heilmeier-standard.md, implementation-readiness-standard.md.

**Scope:** `docs/designs/isolation-timeouts.md` lines 416–496. I checked it against the uncommitted `tests/bench/test-launch-guards.py` diff, the new `tests/bench/launch_guard_clock.py`, `bin/boat-call`, `bin/processes.py`, `bin/boat-launch-guards.sh`, the `factory/launch.sh` probe (lines 435–455) and the `bin/exam-launch` probe (lines 117–131). I did not run the suite, edit files, make Boat calls, or merge.

## Prior findings

**B1 (clock seam): closed.**
- **How it is injected.** The helper is a text insertion right after `import processes` in the copied `boat-call`. It asserts the line matches exactly once.
- **What it replaces.** Only that executable's `processes.time` is swapped, for a `SimpleNamespace(monotonic=…)`. `processes.py` only ever uses `time.monotonic` (lines 20, 42–43, 94, 108, 134, 139), so nothing else is missing from the namespace. The shared `time` module is not touched, so `subprocess`'s own timeouts stay real.
- **Which processes see it.** Every other process that imports `processes` (`boat-spend` and the other host helpers) loads the unpatched module.
- **Inherited deadlines.** The frozen clock starts at the real monotonic reading. So an inherited `UNBUG_PROCESS_DEADLINE` from `boat-spend` can only be equal or later in fake time, and the parent's real deadline still bounds the call from outside. The fake and its children never read the variable.
- **One event per call.** Events are tied to a single call through `clock-<own pid>` and `.observed`, and `FAKE_STATE` is fresh for each `run()` (line 436).
- **How far to advance.** Each case has a stated amount, and the restore case uses 1, which sits between 0.5 and 3.

**B2 (which runs get the frozen clock): closed.** Every `boat-call` in every scenario is frozen. The fake transport has no real sleeps left; the only waits are the observed handshake and `signal.pause()` after an event.

**B3 (retention written as facts): closed.**
- For `unreachable` and `hang`, the test first requires a recorded `exec`, a `polled` marker for each worker, and both `collect failed for` and `KEEPING it running` in stderr. Only then do the existing no-delete, orphan and spend checks run.
- `hang` also requires `command timed out`, a watchdog event and a collector `hashlib` event.
- The `setup-timeout` countercase requires no `exec`, exactly one statement-stage event, and deletion. Through the generic path it also requires an `ls *.` collection call before that deletion.

**M1 (probe identification): closed.** `.boat-launch-start` appears only in the probe text and in the two `exec` start commands (`factory/launch.sh` lines 605 and 755, `bin/exam-launch` line 116). None of those goes through the fake's `python3 -c` branch, and the signal is one-shot through the `signal-sent` marker.

**M2 (remote watchdog time): closed.**
- Both probes compute `time.time() - latest st_mtime`. The fake sets `time.time` explicitly and sets every worker file's timestamp to the fixed epoch at `exec`.
- In progress mode the age stays at 0 only if the probe actually finds the progress file. If the scan misses it, the age grows by 10 s per poll, well past the 1.2 s stall limit, so a broken scan fails.
- Host `date` is used only for the TTL and unreachable cutoffs, and those stay real.

**M3 (proof the seam took effect): closed.** The test asserts the import line matches exactly once, that every published event was observed, and that each timeout case saw the event count and type it expects.

**M4 (backpressure size): closed.** Each stream carries 16,384 lines, about 400–460 KB, far above 64 KiB. Both counts are asserted exactly, and both signal paths share the single `communicate(timeout=60)` path. The prelude uses `os.execv`, so the signalled PID is still the launcher.

## New findings

**N1. Superseded wording is still in the main text (Nit; implementation_readiness).** Lines 445–446 ("should also use injected time") and line 451 ("Add an output-backpressure signal regression") are the vague sentences the earlier M2 and M4 findings flagged. The addendum now overrides them, but a fresh reader sees both versions. Either fold the addendum into lines 435–454 or label the addendum as the normative version.

**N2. Orphan and spend retention checks are conditional (Nit; design_critic).** Lines 477–479 promise "a live orphan and an unfinished spend record" without conditions. In the code, those checks (test lines ~516–525) run only `if record:`. For `unreachable` and `hang`, add `assert record` so the test matches the design text. The record is probably always written by `boat-spend --check`, so I don't expect a gap in practice.

**N3. A stale clock file could survive PID reuse (Nit; design_critic).** Within a single `run()`, a recycled PID would find a previous call's `clock-<pid>` file. That call would start with its time already advanced and time out at once. It needs a PID wraparound inside a few seconds, so the risk is negligible. Unlinking `event` and `observed` (with `missing_ok`) at the start of `install()` removes it for one line.

**N4. The `launcher.pid` ordering is implicit (Nit; implementation_readiness).** The test writes `launcher.pid` after `Popen` returns. It is guaranteed to exist before the probe only because the 400 KB stdout prelude blocks on the pipe until `communicate` starts draining. Without the prelude this would be a narrow race. A one-line comment would keep someone from removing the prelude as noise.

**N5. The reproduction commands are still owed (Nit; Heilmeier).** The earlier N2 asked for the exact burner command and the 1.5-second delay hook used to reproduce the failure. They are still to be recorded with the validation evidence.

## What holds up

- **The root cause is still right.** The deletion happened during setup, the empty worker was correctly collected and retired, and the assertion keyed off the mode name. This is not lost work.
- **The change stays small.** It adds one 25-line test helper and no production hook. It deletes the polling loop and the 30-second readiness deadline, and merges the two branches of `run()` into one.
- **Production code is unchanged.** No Murphy row is closed or newly needed, which is consistent with ENGINEERING.md.

## Validation plan

The plan is adequate:
- reproduce against the old harness under three CPU burners;
- five consecutive loaded passes of the whole launch-guard script;
- a fresh full suite;
- a fresh goldfish diff review.

## Implementation responses

N1: marked the addendum as normative. N2: required the retention spend record.
N3: event names include monotonic nanoseconds as well as PID to avoid reuse.
N4: documented PID publication before stdin/output release. N5: added the
executable offline baseline reproducer at
`docs/reports/isolation-timeouts-reproduce.py` (phase/signal modes, exact fault
hooks, three CPU loops and nice +10). Validation evidence follows separately.
