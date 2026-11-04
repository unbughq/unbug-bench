# One window per mechanical gate (G13/G14/G15)

## Problem

`GatePipeline.check` wraps G13/G14/G15 in `processes.deadline(agent_timeout)`
(default 4h; `docs/designs/isolation-timeouts.md`). Every child inherits the
remaining time, so one attempt is bounded. But the retry loop sits *outside*
`check` (`gate_attempt.execute`, `attempts=2`), so each retry opens a fresh
window. A gate whose nested scenario/guard checkpoints outrun 4h burns 4h, is
retried, and burns another 4h before `infrastructure_exhausted` — an 8h gate
that delays collection. Reproduced with a controlled clock at
`processes.py` (`tests/factory/test_gate_window.py`, 8 units run in a 4h
window on baseline dd81ff8).

G14 also calls `bin/strategy checkpoint` directly, with none of the completed-
checkpoint reuse that G13/G15 get from `strategy_resume.execute_cached`, so any
retry or restart redoes every completed scenario/guard unit.

## Change

1. `GatePipeline.window(c, gate)`: the existing deadline context, for the three
   mechanical gates only. `run_gate` and `early_checks` wrap the *whole*
   `gate_attempt.execute` in it; `check` keeps its own (nested windows only
   shrink), so direct callers are unchanged. A retry inside an expired window
   fails at once at the first child spawn and spends the existing
   infrastructure allowance; it buys no new time.
2. G14 `run()` goes through `execute_cached` with its own exact binding
   (`g14_binding`: case tree, `gate_state.inputs(c, "G14")`, seed). `strategy_run`
   is untouched, so G13/G15 gate fingerprints and receipts are byte-identical to
   baseline dd81ff8 (checked with `gate_state.source_inputs`); only G14's
   fingerprint changes. Cache key covers scenarios, guard, report, runs, seed,
   label, workers and the bench. Per-rule `reference` runs get the rule id in
   their label so two rules on one step stay two real runs. Live silent windows
   are never cached (unchanged). G14 caches announced units even when the case
   has unannounced steps (`simulate` refuses that for strategies); it is safe
   because `bin/checkpoint` is a standalone call with a fixed report and
   explicit history.
3. `extension_evaluator` runs G13/G14/G15 in one long-lived forked comparison
   child per phase, outside `GatePipeline.check`. A fork keeps the deadline it
   was forked under, so inheritance cannot work. Instead the parent wraps its
   `gate_attempt.execute` in the same `window()` (retries share it) and sends the
   window's absolute monotonic end in the `('stage', ...)` message; the child
   clears its fork-time deadline at start and wraps each gate call in that end
   (`None` for non-mechanical stages = no deadline). The monotonic clock is
   system-wide, so an absolute end is valid in the child.

Expiry stays `infrastructure_exhausted` / `invalid-infra`: never a gate pass,
fail, or writer feedback. Run counts, guards, seeds, and allowances are
unchanged. Extension re-runs call `run_gates` again and get their own window.

## Deletes

Nothing; the per-attempt window moves outward. `check` keeps its own, now always
dominated, for direct `checked_gate` callers.

## Cost

G14's gate fingerprint changes, so any cached G14 pass re-runs once on rollout.

## Tests

`tests/factory/test_gate_window.py`: (a) retry shares one window for G13, G14
and G15, and for early G15 (baseline: 8 units, now 4); in-window work passes;
(b) real retained `cases/medusa-oversell-v2` step order through real `run.g14`,
real `execute_cached` and real `processes.run`; the `bin/strategy checkpoint`
wrapper (docker bench, `read_completed`) is replaced by a fake that writes
synthetic summaries, so G14's verdict logic is not exercised on cached data.
Three expired windows never redo a completed unit (baseline redoes them). The
real comparison child loop gets each stage's window from the message
(`test_stream_d_comparison.py`, `long_lived`). `tests/bench/test_strategy.py` gains the `work` dir real cards
always have.

## Murphy rows

Row 42: implemented and tested, **not closed** — no live bench run proves it,
so ENGINEERING section 2 closure is not claimed. Row 35: not claimed; this
test shows reuse of completed G14 units inside one runner, not an off-worker
checkpoint boundary.

## Limits

- Not closed: no live bench run, and G13/G15 checkpoint reuse is off on every v2
  case (`simulate` disables it when any step is `unannounced`; unchanged here).
- Expiry spends the two-attempt infrastructure allowance, and that allowance
  persists in `infra-attempts.json` (no reset on retry, as required). A resume
  of the same unchanged execution after expiry is therefore exhausted before it
  starts; the G14 cache pays off after a worker crash (one stale `running`
  attempt) or after a code/identity change. An honest workload longer than
  `agent_timeout` cannot finish without such a change; it stops as
  infrastructure, never as a case result.
- The deadline bites at child spawns and child timeouts; in-process work (silent
  window sleeps, tree hashing) runs on until the next spawn.
- The parent half of the comparison wiring (`invoke` sending the end) has no
  dedicated test; the child half does.
- The window is still `agent_timeout`; the two retries share it, they do not
  shrink it.
- The unit in flight when the window ends is lost (a child is killed).
- Unannounced (live window) units in G14 always re-run.
- A fresh `run_gates` (repair, extension, resume) opens a new window by design.
