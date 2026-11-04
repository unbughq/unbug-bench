# Goldfish review: gate-window diff 3 (verbatim)

Reviewer: fresh general-purpose subagent (Claude opus), personas zoom_out and implementation_readiness; Mode: REVIEW; reviewed `dd81ff8..abdf8e5`.

---

**Verdict: BLOCKING.** B1 is fixed, but the fix brings in a new regression: comparison gate stages now ignore the runner's deadline.

## Blocking

**1. `independent=True` makes comparison G13/G14/G15 stages ignore the runner's `UNBUG_PROCESS_DEADLINE`.** `factory/extension_evaluator.py:318`
- `runner_supervisor.py:56` starts the factory runner with `UNBUG_PROCESS_DEADLINE=<runner end>` in its environment. When computing a child's deadline, `processes.envelope` (`bin/processes.py:218`) only reads that inherited value if `reset` is False.
- `independent=True` sets `reset=True`. Child processes started by a comparison G13/G14/G15 stage are then bounded only by the gate window. The runner's end is dropped, even when it comes first.
- At baseline dd81ff8 the comparison child kept `reset=False`, so the runner's end was honored. The parent-side `check` and `window()` also keep `reset=False`.
- The contract in `docs/designs/isolation-timeouts.md:27-29, 45-46` says the effective deadline is `min(caller timeout, context deadline, inherited env deadline)`. It reserves `independent=True` for seal and wipe only.
- Reproduced with the real `processes` module, runner end at +60s and gate window at +3600s: `independent=True`: child deadline about 3600s away. Plain `deadline`: about 60s away.
- Fix: drop `independent=True`. Line 227 already resets the context to `(inf, False)` at child start, so a plain `deadline(...)` gives `min(end, inf) == end` and still respects the runner's env deadline. No stale fork-time value can come back.
- Test gap: `test_stream_d_comparison.py:412` records only `_deadline.get()[0]`. Asserting that `[1] is False` for the G14 stage would pin this.

## B1 verification (previous blocking finding)

- **Child reset:** fixed. `extension_evaluator.py:227` clears the fork-time deadline once, before the stage loop. The end is read from every message (`:285-286`), so a long-lived child gets a fresh window per stage. A stale deadline from an earlier fork cannot reach later stages.
- **Parent send:** `Evaluator.invoke` (`:534-536`) reads `processes._deadline.get()` inside the `window()` that `__call__` (`:596`) puts around the whole `gate_attempt.execute`. Both retries therefore send the same absolute end. A retry that re-forks also resets and takes the end from the message.
- **Message unpack:** `_, stage, attempt_id, *rest` accepts both the 3-tuple and the 4-tuple. The only senders are `invoke` and the test Pipe (`test_stream_d_comparison.py:380`). Compatible.
- **Stages that are not G13/G14/G15** (G7, G10, G17, G11, stress, and the G3 shortcut): `window()` is a `nullcontext` for them, so the parent has no window open. The parent sends `None` only when no outer deadline is in effect. The child then runs these stages with no deadline: stress and the G3 shortcut take their own branches, the rest use `nullcontext`. The test asserts `inf` for G7.
- **Parent outside any window:** the only route in is `extension_package.subsequent_entry` -> `Evaluator`, which runs outside any gate window. So `end` is `inf` and the child is sent `None`. Correct.
- **Expired window:** `max(end - now, 1e-3)` keeps `positive()` from raising, so the next child spawn fails at once. That surfaces as a stop and a spent infrastructure attempt, never as a gate verdict. Matches the design.

## Nits

**2. `child()` has lost its docstring.** `extension_evaluator.py:226-228` puts `import processes` and the `_deadline.set` line before the docstring. Move the two lines below it.

**3. The test does not exercise the real long-lived fork.** `test_stream_d_comparison.py:408-418` makes two separate in-process `child()` calls, one stage each. It never sends two stage messages, with different ends, to one child, and it does not fork through `start_child`. It still fails if the line 227 reset is removed (G7 would see the stale end), so it does guard B1. It is weaker than its name suggests. The parent half has no test, which the design admits at `gate-window.md:93`.

## Earlier dispositions

All earlier dispositions (diff-1 items 1, 2, 3, 6; diff-2 B1, N1, N2, N3; design-1 item 3) confirmed applied. Murphy rows: register untouched, row 42 open, row 35 not claimed. Honest.

## Tests run

`test_gate_window.py` 4/4 OK; `test_stream_d_comparison.py -k long_lived` 1/1 OK.

---

## Disposition (elephant)

- 1 fixed: `independent=True` dropped; the test now asserts `reset` is False for the G14 stage and for the non-mechanical stage.
- 2 fixed (docstring first).
- 3 accepted as stated in the design Limits: the loop and per-stage end are proven on the real child loop; a two-message/real-fork test is not added (nit, row stays open).
