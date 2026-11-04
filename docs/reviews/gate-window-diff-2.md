# Goldfish review: gate-window diff 2 (verbatim)

Reviewer: fresh general-purpose subagent (Claude opus), personas zoom_out and implementation_readiness; Mode: REVIEW; reviewed `dd81ff8..2689a08`.

---

# Goldfish review: gate-window, `dd81ff8..2689a08` (Mode: REVIEW)

**Verdict: BLOCKING.** The `run_gate` and `early_checks` windows are correct, and so is the G14 `execute_cached` wiring. The extension comparison wrap doesn't do what the design claims: the comparison child is forked once and reused for later stages, so it keeps whatever deadline was current when it was forked.

## Blocking

**B1. In `extension_evaluator.__call__`, the window either bounds nothing or carries a stale deadline into later stages.**
- **Where:** `factory/extension_evaluator.py:587`; the design at `docs/designs/gate-window.md:38-40`; disposition 3 in `docs/reviews/gate-window-design-1.md:112`.
- **Why:** `start_child` returns early if a child already exists (`:399`). One forked child serves every stage of a phase through the `pipe.recv()` loop (`:280`), and it calls `getattr(r, stage.lower())(c)` directly (`:313`). A forked child gets a copy of the contextvar as it was at fork time, and nothing updates it later. The parent's window never reaches an existing child: the parent's `receive()` loop doesn't check a deadline, and `processes.deadline` doesn't change `os.environ`. I checked this with the real `processes` module and a long-lived forked child. A child forked inside `deadline(100)` still reports that same end time for the later `G14` and `G7` requests, even after the parent has entered `deadline(10000)` or left all windows.
- **Fresh comparison:** the stage order is `stress, G1…G6, G13, G14, G15, G7, G10, G17, G11`, so the child is forked at `stress`, outside any window. G13, G14 and G15 then run in the child with no deadline at all, the same as baseline. Row 42's gap on this path is still open.
- **Retry or resume where stress…G6 are already recorded:** the first fork happens inside G13's window, and G13's end time sticks to that child. G14 and G15 get only what G13 left over instead of a window each. The non-mechanical stages G7, G10, G17 and G11 inherit the deadline too. That is a regression: it can kill pilot or model children mid-call, leading to spurious `invalid-infra` results, a used-up infrastructure attempt (the retry re-forks outside the window and then succeeds), and lost spend.
- **Fix, pick one:**
  - Send the absolute end time in the `('stage', …)` message. The child wraps each stage in that deadline, or in no deadline for non-mechanical stages. The monotonic clock is system-wide, so an absolute time is valid in the child.
  - Or call `close_child()` before each mechanical stage. That is costlier, because it repeats the `g3` setup.
- **Test needed:** add one test with the real `start_child` (as `test_stream_d_comparison.py:261` already does). The "no dedicated test" note in Limits (`gate-window.md:86`) covers exactly the path that is broken.

## Verified OK

1. **`run_gate` and `early_checks` share one window.**
   - The window wraps the whole `gate_attempt.execute` call (`gate_pipeline.py:89`, `:158`).
   - `deadline` takes `min(end, previous)`, so the window inside `check` only ever shrinks it.
   - The retained-replay path returns before the window.
   - `self.r._gate_pipeline()` works for every `r` passed: in production and in the stream-d tests it is the `run` module, and `window` only reads `c.args.agent_timeout`, with a 14400 default.
2. **`strategy_run` is byte-identical to baseline.**
   - Its source hashes the same at both commits, and `gate_state.source_inputs` matches baseline for `g13`, `g15` and `strategy_run`. Only `g14` differs, as the design states.
   - `execute_cached` gets the same positional arguments as `checkpoint`, and `workers` is set to `bench_workers`.
   - Labels only name the results directory (`bin/bench.py:732`); seeds use `seed_base` and are unchanged. The `reference-<id>` label keeps one real run per rule, so baseline run counts hold. Guards, counts and the verdict logic are untouched.
   - Expiry ends as `invalid-infra` / `infrastructure_exhausted` with no `failed_gate`; the tests assert this.
3. **Tests.** `test_gate_window.py` passes 4 of 4 on HEAD. The tests match the Tests section of the design: the window tests drive the real `pipeline.run` and `early_checks`, and the G14 test uses a synthetic checkpoint wrapper. The design's wording about what is replaced is now accurate.
4. **Murphy.** `docs/murphy-register.md` is untouched. Row 42 stays `open` and row 35 stays `open`, and the design claims neither. That is honest; B1 is one more reason row 42 must stay open.

## Nits

- **N1.** `g14_binding` (`factory/run.py:1907-1916`) copies the body of `strategy_run.signature()`. That is the price of keeping `strategy_run` byte-identical, but the docstring could say the two must stay in step.
- **N2.** No test covers the `reference-<rule id>` label (two rules on one step should mean two executions). A small assertion on the `executed` labels in `G14ResumeTests` would pin it.
- **N3.** `gate-window.md:62` is one overlong line, and "A honest" at line 82 should be "An honest".

## Earlier-round dispositions

- **Diff review 1:** items 1, 2, 3 and 6 were really applied. I confirmed item 1 independently by comparing `source_inputs`.
- **Design review 1, item 3:** only partly applied. The wrap was added, but its stated reason ("the fork inherits the context deadline") is false for the reused child, which is finding B1.

---

## Disposition (elephant, commit 2849c99)

- B1 fixed: the parent sends the window's absolute monotonic end in the `('stage', ...)` message (`None` outside a window); the child clears its fork-time deadline at start and wraps each gate call in that end with `independent=True`. Test: `test_stream_d_comparison.py` `test_long_lived_child_takes_each_stage_window_from_the_message_not_from_its_fork`, driving the real child loop. Parent half untested (stated in the design Limits).
- N1 (docstring), N2 (label assertion `g14-reference-manual-holds-1`), N3 fixed.
