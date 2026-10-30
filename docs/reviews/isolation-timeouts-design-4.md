**Verdict: CHANGES REQUESTED.** Three blockers and four majors are open. All of them are things the design leaves unspecified. The diagnosis itself holds up.

# Goldfish design review: "Loaded launch-guard regression (2026-10-30)"

**Mode:** REVIEW. **Personas:** zoom_out, design_critic, implementation_readiness. **Standards:** heilmeier-standard.md, implementation-readiness-standard.md.

**Scope:** `docs/designs/isolation-timeouts.md` lines 416–454, the uncommitted diff. I read it against `tests/bench/test-launch-guards.py`, `bin/boat-call`, `bin/processes.py` and `bin/boat-launch-guards.sh`. I did not run the full suite.

## What holds up

- **Root cause is right.** In `run()`, the `unreachable` and `hang` cases override `BOAT_COMMAND_TIMEOUT_SECONDS="1"`. `boat-call` applies that limit to every call, including the statement install before the runner starts (fake transport, test line ~194). A timeout there yields an empty, collectable worker, which then gets deleted. That is correct production behaviour. The test's assertion keys off the mode name, so it wrongly expects that worker to be kept. This is a test bug, not lost work.
- **The signal-test diagnosis is right.** Lines 433–441 poll for `polled` with both pipes set to `PIPE` and never read them. Enough output during setup fills the pipe buffer and blocks the launcher, so it never polls. Two changes fix this: have the fake send the signal when the probe actually arrives, and drain output with `communicate`. That also lets the code delete the polling loop and the 30-second readiness deadline. Good deletion.
- **Production stays unchanged, and no Murphy row is closed or needed for a test-only fault.** Both are consistent with ENGINEERING.md §2 and §4.

## Blockers

**B1. The clock seam is not specified (Blocker; implementation_readiness, design_critic).** Affects lines 437–447. "Inject a clock into the temporary copy of boat-call's process owner" leaves these decisions to whoever implements it:

- **How it is injected.** It could be a text patch of `time.monotonic` in the copied `bin/processes.py`, a `sitecustomize`/`PYTHONPATH` shim, or an env-gated hook. The design must name one.
- **Which processes see it.** `processes.py` is also imported by `bin/bench.py`, `bin/boat-spend`, `bin/strategy`, `factory/run.py`, `factory/worker_release.py`, `factory/runner_supervisor.py`, `factory/run_artifacts.py` and `factory/gate_pipeline.py`. Patching the copied module changes the clock for every one of them that runs locally. The design says the seam is for boat-call only. State which processes get the fake clock and how the rest are excluded.
- **How deadlines cross processes.** `envelope()` writes an absolute monotonic time into `UNBUG_PROCESS_DEADLINE`, and children inherit it; `runner_supervisor.py:50` writes it too. If one process uses a frozen fake clock and its child uses the real one, the inherited deadline is either already past or never reached. State which clock each process uses, or prove no child reads the variable.
- **Which call an event belongs to.** Probes run concurrently (`guard_wait` starts one `boat-call ssh … &` per worker; `count=2` cases exist). If one event advances a shared clock, every call in flight times out, including collection and deletion calls. That changes the outcome under test. The design must say how an event is tied to exactly one `boat-call` run, for example a file keyed by the fake's parent PID, which is boat-call's own PID because `processes.run` starts it directly.
- **How far to advance.** "Beyond the configured deadline" doesn't work for the slow-restore case (line ~543). That case must go past the ordinary limit (`0.5`) but stay under the restore limit (`3`), or it proves nothing. State the amount for each case.

**B2. It doesn't say which runs get the frozen clock (Blocker; design_critic).** The design names only the 1-second `unreachable`/`hang` overrides and the restore case. But `run()` sets `BOAT_COMMAND_TIMEOUT_SECONDS="2"` by default for every scenario, and the restore case uses `0.5` globally. Both are the same race against a loaded scheduler, just with more headroom. If the frozen clock covers only the named cases, finish, autoretry and the other modes can still flake under load, and five loaded passes won't reliably catch it. State that the frozen-by-default clock applies to every `run()` call, or justify leaving the 2-second default on real time.

**B3. The retention assertion isn't written as observed facts (Blocker; implementation_readiness).** Affects lines 444–446 and test lines ~465–481. The design says the mode-based assertion was wrong, but it never says what replaces the hard-coded list `("collect-fail", …, "unreachable", "hang")`. To prove live workers are kept, write the rule from observed facts:

- If the runner started (`exec` recorded / `.boat-launch-start` exists), the watchdog probe event occurred, and collection was not verified, then: no `delete` call, `!!! ORPHAN:` is printed, and the reservation is held.
- If the worker timed out before the runner started, then: collection happened, then deletion.

Also name the collection step that leaves collection unverified in `hang` mode. Today that is the collector's own `python3 -c` call hanging, because `ls *.` succeeds. Under B1, each hanging call then needs its own event and advance.

## Majors

**M1. The probe isn't identified (Major; implementation_readiness).** "Only when its actual watchdog probe arrives" (line 435) relies on the fake's current test, "any `python3 -c` after the statement install". Collector calls (`pathlib.Path.home()`/sealed) take the same path. Name a substring that only the probe text contains (`factory/launch.sh:435`, `bin/exam-launch:117`). Also require the fake to send the signal only once, using a marker file. Otherwise the launcher's cleanup calls after the trap will signal it again.

**M2. Progress/stall timing is vague (Major; zoom_out, implementation_readiness).** Lines 447–448: "should also use injected time". Stall detection comes from the shell's `date +%s` and from the probe's own `time.time()` running on the fake VM. Neither goes through `processes.py`, so the boat-call seam doesn't touch it. Pick one:
- (a) reuse the existing `clockbin/date` shim (test line ~335) and state how the probe's time is controlled; or
- (b) drop this item as out of scope. No failure has been reported here; the five loaded passes are the exam.

"Should" is not something anyone can implement.

**M3. Nothing checks that the seam actually took effect (Major; design_critic).** If the seam is a text patch of the copied `processes.py`, a later refactor can make the patch match nothing. The tests would then quietly go back to real 1-second timing and the flake would return. Require a hard assertion that the patch matched the expected number of places, plus an explicit "event observed" assertion in each timeout case.

**M4. The backpressure regression has no size (Major; implementation_readiness).** Line 451: "add an output-backpressure signal regression". Specify it:
- **What:** the fake writes more than 64 KiB to stderr and to stdout before the probe.
- **In which mode:** a mode that then receives SIGINT or SIGTERM.
- **What passes:** exit code `128+sig` within the single outer `communicate` budget.

## Nits

- **N1.** `unreachable` never needed the 1-second command timeout. The fake exits 1 at once, and the UNREACHABLE result comes from `BOAT_UNREACHABLE_SECONDS` and `date`. Dropping the override fixes that case with no seam at all. Only `hang` (and restore) needs the clock.
- **N2.** For "three CPU burners", give the exact command and the exact 1.5-second delay hook used to reproduce the failure, so the old-harness repro can be repeated.
- **N3.** Heilmeier: cost and timeline aren't stated, which is acceptable for a test-only change, but one line would close it. The objective sentence is jargon-heavy: "process owner", "phase announces its event".
- **N4.** Once the signal path uses `communicate(IDENTITY, timeout=60)` like the non-signal path, merge the two branches of `run()` into one.

## Validation plan

The plan is adequate once B1–B3 are fixed:
- old-harness repro under load;
- 5 consecutive loaded passes of the whole script;
- a fresh full suite;
- a fresh goldfish diff review.

---

I didn't write any files, run the suite, make any Boat calls, or merge.

## Implementation responses

B1/B2: specified and implemented a boat-call-only copied helper, per-invocation
PID event/acknowledgement, frozen clocks for every scenario, and exact elapsed
values. Documented all child clock consumers and unchanged host helpers.
B3: phase, failed-collection, orphan and spend assertions precede retention;
added a pre-run timeout/empty-worker deletion countercase.
M1: only `.boat-launch-start` marks watchdog probes; signal is one-shot.
M2: fixed worker epoch and explicit per-probe progress timestamps; parent
directory timestamps cannot mask a missing scan. Host retry shim is unchanged.
M3: exact-one import insertion assertion and observed-event assertions.
M4: stdout prelude and stderr setup each exceed 64 KiB and are fully counted;
both signals use one communicating/draining path and the existing outer bound.
N1/N4 implemented. N2 reproduction commands and final validation evidence will
be recorded with the results. No blocker was rejected; a fresh design review
will assess the clarified design.
